import argparse
import os
import queue
import shutil
import sys
import tempfile
import threading
from pathlib import Path
import webbrowser

sys.path.append(os.path.abspath(os.path.join(__file__, "..", "..")))

import gradio as gr

from epub_translator.study.runner import run_translation
from epub_translator.utils import read_format_json, write_format_json


def load_config():
    try:
        cfg = read_format_json()
    except Exception:
        cfg = {}
    return (
        cfg.get("key", ""),
        cfg.get("url", ""),
        cfg.get("model", ""),
        cfg.get("target_language", "Korean"),
    )


def save_config(key: str, url: str, model: str, target_lang: str) -> str:
    try:
        cfg = read_format_json()
    except Exception:
        cfg = {}
    cfg["key"] = key
    cfg["url"] = url
    cfg["model"] = model
    cfg["target_language"] = target_lang
    write_format_json(cfg)
    return "Saved"


def start_translate(
    epub_file: str | None,
    target_lang: str,
    key: str,
    url: str,
    model: str,
    progress: gr.Progress = gr.Progress(),
):
    if epub_file is None:
        return "No file uploaded", *([None] * 2)

    save_config(key, url, model, target_lang)

    source_path = Path(epub_file)
    tmp_dir = Path(tempfile.mkdtemp(prefix="epub_translate_"))
    tmp_path = tmp_dir / source_path.name
    shutil.copy2(source_path, tmp_path)

    output_dir = Path("out")
    cfg = read_format_json()
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

    progress_q: queue.Queue[tuple[int, int, str] | None] = queue.Queue()
    result_container: list = []
    error_container: list = []

    def on_progress(chapter_idx: int, total: int, title: str) -> None:
        progress_q.put((chapter_idx, total, title))

    def worker() -> None:
        try:
            result_container.append(
                run_translation(
                    source_path=tmp_path,
                    target_language=target_lang,
                    output_dir=output_dir,
                    config=config_for_llm,
                    on_progress=on_progress,
                )
            )
        except Exception as e:
            error_container.append(e)

    t = threading.Thread(target=worker, daemon=True)
    t.start()

    while t.is_alive():
        try:
            chapter_idx, total, title = progress_q.get(timeout=0.5)
            pct = (chapter_idx + 1) / total
            progress(pct, desc=f"Ch {chapter_idx+1}/{total}: {title}")
        except queue.Empty:
            pass

    progress(None)  # hide progress bar
    shutil.rmtree(tmp_dir, ignore_errors=True)

    if error_container:
        return f"Error: {error_container[0]}", *([None] * 2)

    result = result_container[0]
    stats = result.token_stats
    msg = (
        f"Complete! {result.total_chapters} chapters, "
        f"{result.total_kanji} kanji, {result.total_vocab} vocab. "
        f"Tokens: {stats.get('total_tokens', 0):,}"
    )
    return (
        msg,
        gr.update(value=str(result.output_path), visible=True),
        gr.update(value=str(result.clean_path), visible=True),
    )


def main():
    parser = argparse.ArgumentParser(description="Start EPUB Translator Web UI (Gradio)")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=2527, help="Port (default: 2527)")
    parser.add_argument("-o", "--output", type=str, default="out", help="Output directory (default: out)")
    args = parser.parse_args()

    key, url, model, target_lang = load_config()
    theme = gr.themes.Soft()

    with gr.Blocks(title="EPUB Translator") as demo:
        gr.Markdown("# 📖 EPUB Translator")

        with gr.Tabs():
            with gr.Tab("Translation"):
                with gr.Row():
                    with gr.Column(scale=1):
                        key_in = gr.Textbox(label="API Key", type="password", value=key)
                        url_in = gr.Textbox(label="API URL", value=url)
                        model_in = gr.Textbox(label="Model", value=model)
                        lang_in = gr.Dropdown(
                            choices=["Korean", "Chinese", "English", "Vietnamese", "Indonesian",
                                     "Thai", "Spanish", "French", "German", "Russian"],
                            label="Target Language",
                            value=target_lang,
                        )
                        save_btn = gr.Button("Save Config", variant="secondary")
                        save_msg = gr.Textbox(label="", visible=False)

                    with gr.Column(scale=2):
                        file_in = gr.File(label="Upload EPUB", file_types=[".epub"])
                        trans_btn = gr.Button("Start Translation", variant="primary")
                        status = gr.Textbox(label="Status")

                        with gr.Row():
                            study_out = gr.File(label="Study EPUB", visible=False)
                            clean_out = gr.File(label="Clean EPUB", visible=False)

        save_btn.click(save_config, inputs=[key_in, url_in, model_in, lang_in], outputs=[save_msg])

        trans_btn.click(
            start_translate,
            inputs=[file_in, lang_in, key_in, url_in, model_in],
            outputs=[status, study_out, clean_out],
        )
    print(f"Running webui at http://localhost:{args.port}")
    webbrowser.open(f"http://localhost:{args.port}")
    demo.launch(server_name=args.host, server_port=args.port, theme=theme, quiet=True)

if __name__ == "__main__":
    main()
