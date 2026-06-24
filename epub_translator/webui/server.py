import json
import mimetypes
import re
import tempfile
import urllib.parse
from functools import partial
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from epub_translator.utils import read_format_json, write_format_json
from epub_translator.webui.manager import TranslationJobManager
from epub_translator.webui.templates import render_index


def _parse_multipart(body: bytes, boundary: str) -> dict:
    """Parse multipart/form-data body. Returns dict of field name -> value (bytes)."""
    result: dict[str, bytes] = {}
    delimiter = b"--" + boundary.encode()
    parts = body.split(delimiter)
    for part in parts:
        if part.strip() in (b"", b"--"):
            continue
        header_end = part.find(b"\r\n\r\n")
        if header_end == -1:
            continue
        headers_raw = part[:header_end].decode("utf-8", errors="replace")
        content = part[header_end + 4:]
        if content.endswith(b"\r\n"):
            content = content[:-2]

        name_match = re.search(r'name="([^"]*)"', headers_raw)
        if not name_match:
            continue
        name = name_match.group(1)

        filename_match = re.search(r'filename="([^"]*)"', headers_raw)
        if filename_match:
            result[name] = content
            result[name + "_filename"] = filename_match.group(1)
        else:
            result[name] = content
    return result


def _try_decode(v: bytes) -> str | bytes:
    try:
        return v.decode("utf-8")
    except UnicodeDecodeError:
        return v


def _parse_form(body: bytes) -> dict:
    text = body.decode("utf-8", errors="replace")
    parsed = urllib.parse.parse_qs(text)
    return {k: v[0] for k, v in parsed.items()}


class WebUIRequestHandler(BaseHTTPRequestHandler):
    server_version = "EPUBTranslatorWebUI/0.1"

    def __init__(self, *args, manager: TranslationJobManager, output_dir: Path, **kwargs):
        self._manager = manager
        self._output_dir = output_dir
        super().__init__(*args, **kwargs)

    def _send_html(self, content: str, status: int = 200) -> None:
        body = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path) -> None:
        if not path.exists() or not path.is_file():
            self.send_error(404, "File not found")
            return
        mime_type, _ = mimetypes.guess_type(str(path))
        if mime_type is None:
            mime_type = "application/octet-stream"
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Disposition", f"attachment; filename=\"{path.name}\"")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, data: dict, status: int = 200) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _get_config(self) -> dict:
        try:
            return read_format_json()
        except Exception:
            return {"key": "", "url": "", "model": ""}

    def _get_target_language(self) -> str:
        cfg = self._get_config()
        return cfg.get("target_language", "Korean")

    def _render_index(self, message: str | None = None, is_error: bool = False) -> str:
        cfg = self._get_config()
        info = self._manager.poll()
        has_prog = info.has_progress_html
        return render_index(
            config=cfg,
            target_lang=self._get_target_language(),
            job_state=info.state.value,
            book_name=info.book_name,
            has_progress=has_prog,
            has_study=info.has_study_epub,
            has_clean=info.has_clean_epub,
            progress_pct=info.progress_pct,
            message=message,
            is_error=is_error,
        )

    def _handle_save_config(self, form: dict) -> None:
        cfg = self._get_config()
        if "key" in form:
            cfg["key"] = form["key"]
        if "url" in form:
            cfg["url"] = form["url"]
        if "model" in form:
            cfg["model"] = form["model"]
        target_lang = form.get("target_lang", "")
        if target_lang:
            cfg["target_language"] = target_lang
        try:
            write_format_json(cfg)
            self._redirect("/", "Config saved")
        except Exception as exc:
            self._redirect("/", f"Failed to save config: {exc}", is_error=True)

    @staticmethod
    def _decode_epub_data(form: dict) -> tuple[bytes, str] | None:
        epub_data_field = form.get("epub_data", "")
        if epub_data_field and isinstance(epub_data_field, str) and epub_data_field.startswith("data:"):
            import base64
            try:
                header, encoded = epub_data_field.split(",", 1)
                epub_bytes = base64.b64decode(encoded)
                epub_filename = form.get("epub_data_filename", "dropped.epub")
                return epub_bytes, epub_filename
            except Exception:
                pass
        epub_bytes = form.get("epub", b"")
        if isinstance(epub_bytes, str):
            epub_bytes = epub_bytes.encode()
        if epub_bytes:
            epub_filename = form.get("epub_filename", "book.epub")
            return epub_bytes, epub_filename
        return None

    def _handle_start(self, form: dict) -> None:
        decoded = self._decode_epub_data(form)
        if decoded is None:
            self._redirect("/", "No EPUB file uploaded", is_error=True)
            return

        epub_data, epub_filename = decoded
        if not epub_filename.lower().endswith(".epub"):
            epub_filename += ".epub"

        tmp_dir = Path(tempfile.mkdtemp(prefix="epub_upload_"))
        epub_path = tmp_dir / epub_filename
        epub_path.write_bytes(epub_data)

        cfg = self._get_config()
        config_for_llm = {
            "key": cfg.get("key", ""),
            "url": cfg.get("url", ""),
            "model": cfg.get("model", ""),
            "token_encoding": cfg.get("token_encoding", "o200k_base"),
            "timeout": cfg.get("timeout", 360.0),
            "retry_times": cfg.get("retry_times", 10),
            "retry_interval_seconds": cfg.get("retry_interval_seconds", 0.75),
            "study": cfg.get("study", {"temperature": 0.3, "top_p": 0.9}),
        }

        target_lang = self._get_target_language()
        try:
            self._manager.start(
                source_path=epub_path,
                target_language=target_lang,
                config=config_for_llm,
            )
            self._redirect("/", f"Started translating '{epub_filename}'")
        except RuntimeError as exc:
            self._redirect("/", str(exc), is_error=True)

    def _handle_cancel(self) -> None:
        self._manager.cancel()
        self._redirect("/", "Translation cancelled")

    def _redirect(self, path: str, message: str = "", is_error: bool = False) -> None:
        if message:
            encoded = urllib.parse.quote(message)
            sep = "&" if "?" in path else "?"
            path = f"{path}{sep}msg={encoded}&error={'1' if is_error else '0'}"
        self.send_response(303)
        self.send_header("Location", path)
        self.end_headers()

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return b""
        return self.rfile.read(length)

    def _parse_form_data(self) -> dict:
        ctype = self.headers.get("Content-Type", "")
        body = self._read_body()
        if "multipart/form-data" in ctype:
            boundary_match = re.search(r'boundary=([^;]+)', ctype)
            if not boundary_match:
                return {}
            boundary = boundary_match.group(1).strip()
            raw = _parse_multipart(body, boundary)
            return {k: _try_decode(v) if isinstance(v, bytes) else v for k, v in raw.items()}
        else:
            return _parse_form(body)

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path == "/" or path == "":
            query = urllib.parse.parse_qs(parsed.query)
            msg = query.get("msg", [None])[0]
            error = query.get("error", ["0"])[0]
            html = self._render_index(message=msg, is_error=(error == "1"))
            self._send_html(html)

        elif path.startswith("/progress/"):
            rel = path[len("/progress/"):]
            book_dir = self._output_dir / rel
            prog_path = book_dir / "_progress.html"
            self._send_file(prog_path)

        elif path.startswith("/output/"):
            rel = path[len("/output/"):]
            file_path = self._output_dir / rel
            self._send_file(file_path)

        elif path == "/status":
            info = self._manager.poll()
            self._send_json({
                "state": info.state.value,
                "book_name": info.book_name,
                "progress_pct": info.progress_pct,
                "has_progress_html": info.has_progress_html,
                "has_study_epub": info.has_study_epub,
                "has_clean_epub": info.has_clean_epub,
                "error_message": info.error_message,
            })

        else:
            self.send_error(404, "Not found")

    def do_POST(self) -> None:
        form = self._parse_form_data()
        action = form.get("_action", "")

        if action == "save_config":
            self._handle_save_config(form)
        elif action == "start":
            self._handle_start(form)
        elif action == "cancel":
            self._handle_cancel()
        else:
            self._redirect("/", "Unknown action", is_error=True)


class WebUIServer:
    def __init__(self, host: str = "0.0.0.0", port: int = 2527, output_dir: str = "out"):
        self.host = host
        self.port = port
        self._output_dir = Path(output_dir).resolve()
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._manager = TranslationJobManager(output_dir=self._output_dir)

    def start(self) -> None:
        handler = partial(
            WebUIRequestHandler,
            manager=self._manager,
            output_dir=self._output_dir,
        )
        server = HTTPServer((self.host, self.port), handler)
        print(f"Web UI started at http://localhost:{self.port}")
        print(f"Output directory: {self._output_dir}")
        print("Press Ctrl+C to stop")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down...")
            self._manager.cancel()
            server.server_close()
