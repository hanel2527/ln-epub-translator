import html

CSS = """\
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  max-width: 48em; margin: 2em auto; padding: 0 1em; color: #333; line-height: 1.6;
}
h1 { font-size: 1.6em; margin-bottom: 0.8em; color: #1a1a1a; }
h2 { font-size: 1.2em; margin: 1.2em 0 0.6em; color: #444; }
label { display: block; margin-top: 0.6em; font-weight: 600; font-size: 0.9em; color: #555; }
input, select {
  width: 100%; padding: 0.5em 0.7em; border: 1px solid #ccc;
  border-radius: 4px; font-size: 0.95em; margin-top: 0.2em;
}
input:focus {
  border-color: #4a9eff; outline: none; box-shadow: 0 0 0 2px rgba(74,158,255,0.2);
}
button { cursor: pointer; padding: 0.6em 1.4em; border: none; border-radius: 4px; font-size: 0.95em; font-weight: 600; }
.btn-primary { background: #2563eb; color: #fff; }
.btn-primary:hover { background: #1d4ed8; }
.btn-danger { background: #dc2626; color: #fff; }
.btn-danger:hover { background: #b91c1c; }
.btn-secondary { background: #e5e7eb; color: #333; }
.btn-secondary:hover { background: #d1d5db; }
.card { background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 8px; padding: 1.2em; margin: 1em 0; }
.drop-zone {
  border: 2px dashed #ccc; border-radius: 8px; padding: 2.5em 1em;
  text-align: center; cursor: pointer; transition: background 0.2s, border-color 0.2s;
  position: relative;
}
.drop-zone.drag-over { background: #e0f2fe; border-color: #2563eb; }
.drop-zone-text { pointer-events: none; color: #888; }
.drop-zone-text strong { color: #2563eb; }
.start-btn-wrap { display: none; margin-top: 0.6em; }
.start-btn-wrap.visible { display: block; }
#file-input { display: none; }
.status-box { padding: 0.8em 1em; border-radius: 6px; margin: 0.5em 0; font-weight: 500; }
.status-idle { background: #f3f4f6; color: #666; }
.status-running { background: #dbeafe; color: #1e40af; }
.status-completed { background: #dcfce7; color: #166534; }
.status-error { background: #fee2e2; color: #991b1b; }
a { color: #2563eb; text-decoration: none; }
a:hover { text-decoration: underline; }
.actions { display: flex; gap: 0.6em; margin-top: 1em; flex-wrap: wrap; }
.file-info { font-size: 0.85em; color: #666; margin-top: 0.5em; }
.mt-1 { margin-top: 0.6em; }
.msg-success {
  background: #dcfce7; border: 1px solid #86efac; border-radius: 4px;
  padding: 0.5em 0.8em; color: #166534; font-size: 0.9em; margin-bottom: 0.8em;
}
.msg-error {
  background: #fee2e2; border: 1px solid #fca5a5; border-radius: 4px;
  padding: 0.5em 0.8em; color: #991b1b; font-size: 0.9em; margin-bottom: 0.8em;
}
form.inline { display: inline; }
"""

INDEX_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>EPUB Translator</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>{css}</style>
</head>
<body>
<h1>&#x1F4D6; EPUB Translator</h1>

{message_html}

<div class="card">
<h2>&#x2699;&#xFE0F; Configuration</h2>
<form method="post" action="/">
<input type="hidden" name="_action" value="save_config">
<label for="key">API Key</label>
<input id="key" name="key" type="password" value="{key}" placeholder="sk-...">
<label for="url">API URL</label>
<input id="url" name="url" type="text" value="{url}" placeholder="https://api.example.com/v1">
<label for="model">Model</label>
<input id="model" name="model" type="text" value="{model}" placeholder="model-name">
<label for="target_lang">Target Language</label>
<select id="target_lang" name="target_lang">
{lang_options}
</select>
<div class="actions">
<button type="submit" class="btn-primary">&#x1F4BE; Save Config</button>
</div>
</form>
</div>

<div class="card">
<h2>&#x1F4C2; Upload EPUB</h2>
<form method="post" action="/" enctype="multipart/form-data" id="upload-form">
<input type="hidden" name="_action" value="start">
<input type="hidden" name="epub_data" id="epub-data" value="">
<input type="hidden" name="epub_data_filename" id="epub-data-filename" value="">
<div class="drop-zone" id="drop-zone">
<div class="drop-zone-text">
<strong>Click to browse</strong> or drag an EPUB file here
</div>
</div>
<div class="file-info" id="file-info"></div>
<input type="file" name="epub" accept=".epub" id="file-input">
<div class="start-btn-wrap" id="start-btn-wrap">
<button type="submit" class="btn-primary" id="start-btn">&#x25B6; Start Translation</button>
</div>
</form>
</div>

<div class="card">
<h2>&#x1F4CA; Job Status</h2>
<div class="status-box status-{status_class}">{status_text}</div>
{status_detail}
</div>

<script>
(function() {{
    var zone = document.getElementById('drop-zone');
    var input = document.getElementById('file-input');
    var info = document.getElementById('file-info');
    var wrap = document.getElementById('start-btn-wrap');
    var epubData = document.getElementById('epub-data');
    var epubDataFilename = document.getElementById('epub-data-filename');
    if (!zone || !input || !wrap || !epubData || !epubDataFilename) return;

    function showFile(name) {{
        info.textContent = '\\uD83D\\uDCC4 ' + name;
        wrap.classList.add('visible');
    }}

    zone.addEventListener('click', function() {{ input.click(); }});

    ['dragenter', 'dragover'].forEach(function(ev) {{
        zone.addEventListener(ev, function(e) {{ e.preventDefault(); zone.classList.add('drag-over'); }});
    }});
    ['dragleave'].forEach(function(ev) {{
        zone.addEventListener(ev, function(e) {{ e.preventDefault(); zone.classList.remove('drag-over'); }});
    }});
    zone.addEventListener('drop', function(e) {{
        e.preventDefault();
        zone.classList.remove('drag-over');
        var files = e.dataTransfer.files;
        if (files.length === 0) return;
        var reader = new FileReader();
        reader.onload = function(ev) {{
            epubData.value = ev.target.result;
            epubDataFilename.value = files[0].name;
            showFile(files[0].name);
        }};
        reader.readAsDataURL(files[0]);
    }});

    input.addEventListener('change', function() {{
        epubData.value = '';
        epubDataFilename.value = '';
        if (input.files.length > 0) showFile(input.files[0].name);
    }});
}})();
</script>
</body>
</html>
"""

LANG_OPTIONS = """\
<option value="Korean"{sel_kr}>Korean</option>
<option value="Chinese"{sel_zh}>Chinese</option>
<option value="English"{sel_en}>English</option>
<option value="Vietnamese"{sel_vi}>Vietnamese</option>
<option value="Indonesian"{sel_id}>Indonesian</option>
<option value="Thai"{sel_th}>Thai</option>
<option value="Spanish"{sel_es}>Spanish</option>
<option value="French"{sel_fr}>French</option>
<option value="German"{sel_de}>German</option>
<option value="Russian"{sel_ru}>Russian</option>
"""


def _lang_selected(current: str, val: str) -> str:
    return ' selected' if current.lower() == val.lower() else ''


def _message_html(msg: str | None, is_error: bool = False) -> str:
    if not msg:
        return ""
    cls = "msg-error" if is_error else "msg-success"
    return f'<div class="{cls}">{html.escape(msg)}</div>'


def _progress_link(book_name: str, text: str) -> str:
    url = f"/progress/{html.escape(book_name)}/"
    return f'<div class="mt-1"><a href="{url}" target="_blank">{text}</a></div>'


def _output_link(book_name: str, filename: str, text: str) -> str:
    url = f"/output/{html.escape(book_name)}/{filename}"
    return f'<div class="mt-1"><a href="{url}" download>{text}</a></div>'


def _status_detail_html(
    state: str,
    book_name: str,
    has_progress: bool,
    has_study: bool,
    has_clean: bool,
) -> str:
    parts: list[str] = []

    if state == "running":
        if has_progress:
            parts.append(_progress_link(book_name, "View Progress &#x2197;"))
        cancel_btn = (
            '<form class="inline" method="post" action="/">'
            '<input type="hidden" name="_action" value="cancel">'
            '<button type="submit" class="btn-danger">&#x23F9; Stop</button>'
            '</form>'
        )
        parts.append(f'<div class="actions">{cancel_btn}</div>')

    elif state == "completed":
        if has_progress:
            parts.append(_progress_link(book_name, "View Progress &#x2197;"))
        if has_study:
            parts.append(
                _output_link(book_name, "translated_study.epub", "Download Study EPUB &#x2197;")
            )
        if has_clean:
            parts.append(
                _output_link(book_name, "translated_study.clean.epub", "Download Clean EPUB &#x2197;")
            )

    elif state == "error":
        if has_progress:
            parts.append(_progress_link(book_name, "View Progress &#x2197;"))

    return "\n".join(parts)


def render_index(
    config: dict,
    target_lang: str,
    job_state: str,
    book_name: str = "",
    has_progress: bool = False,
    has_study: bool = False,
    has_clean: bool = False,
    progress_pct: int = 0,
    message: str | None = None,
    is_error: bool = False,
) -> str:
    lang_sel = LANG_OPTIONS.format(
        sel_kr=_lang_selected(target_lang, "korean"),
        sel_zh=_lang_selected(target_lang, "chinese"),
        sel_en=_lang_selected(target_lang, "english"),
        sel_vi=_lang_selected(target_lang, "vietnamese"),
        sel_id=_lang_selected(target_lang, "indonesian"),
        sel_th=_lang_selected(target_lang, "thai"),
        sel_es=_lang_selected(target_lang, "spanish"),
        sel_fr=_lang_selected(target_lang, "french"),
        sel_de=_lang_selected(target_lang, "german"),
        sel_ru=_lang_selected(target_lang, "russian"),
    )

    status_map = {
        "idle": ("idle", "\U0001F4A4 Idle \u2014 upload an EPUB to start"),
        "running": ("running", f"\U0001F504 Translating... ({progress_pct}%)"),
        "completed": ("completed", "\u2705 Translation complete!"),
        "error": ("error", "\u274C Translation failed"),
    }
    status_class, status_text = status_map.get(job_state, ("idle", "\U0001F4A4 Idle"))

    detail = _status_detail_html(
        job_state, book_name, has_progress, has_study, has_clean
    )

    return INDEX_HTML.format(
        css=CSS,
        message_html=_message_html(message, is_error),
        key=html.escape(config.get("key", "")),
        url=html.escape(config.get("url", "")),
        model=html.escape(config.get("model", "")),
        lang_options=lang_sel,
        status_class=status_class,
        status_text=status_text,
        status_detail=detail,
    )
