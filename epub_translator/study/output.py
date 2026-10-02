import html
import posixpath
import re

from ..epub.zip import Zip
from .kanji_tracker import KanjiTracker
from .ruby_annotator import RubyAnnotator
from pathlib import Path


_AMP_PATTERN = re.compile(r"&(?!(?:amp|lt|gt|quot|apos|#[0-9]+|#x[0-9a-fA-F]+);)")



class StudyOutputGenerator:
    def __init__(
        self,
        kanji_tracker: KanjiTracker,
        ruby_annotator: RubyAnnotator,
        target_language: str,
    ) -> None:
        self._kanji_tracker = kanji_tracker
        self._ruby_annotator = ruby_annotator
        self._target_language = target_language

    def generate_chapter_html(
        self,
        chapter_index: int,
        chapter_title: str,
        paragraphs: list[tuple[str, str, list[str]]],
    ) -> str:
        lines: list[str] = []
        if chapter_title:
            lines.append(f"<h1>{chapter_title}</h1>")
        lines.append('<div class="chapter-body">')

        for source_html, translated_html, study_notes in paragraphs:
            lines.append('<div class="para-block">')

            lines.append('<div class="source-text">')
            lines.append(source_html)
            lines.append("</div>")

            lines.append('<div class="translation-text">')
            lines.append(translated_html)
            if study_notes:
                notes_html = "; ".join(
                    f'<span class="study-note">{html.escape(note)}</span>'
                    for note in study_notes
                )
                lines.append(f'<span class="study-notes">{notes_html}</span>')
            lines.append("</div>")

            lines.append("</div>")

        lines.append("</div>")

        return "\n".join(lines)

    def generate_full_html(
        self,
        chapter_htmls: list[tuple[str, list[str]] | None],
        book_title: str = "",
    ) -> str:
        lines: list[str] = []

        lines.append("<!DOCTYPE html>")
        lines.append('<html lang="ja">')
        lines.append("<head>")
        lines.append('<meta charset="utf-8">')
        if book_title:
            lines.append(f"<title>{book_title}</title>")
        else:
            lines.append("<title>翻訳</title>")
        lines.append("<style>")
        lines.append("""
body {
    font-family: serif;
    line-height: 1.8;
    max-width: 50em;
    margin: 0 auto;
    padding: 2em;
    writing-mode: horizontal-tb;
}
.source-text {
    background: #f8f8f8;
    padding: 0.5em 1em;
    border-left: 3px solid #ccc;
    margin: 0.5em 0;
}
.translation-text {
    padding: 0.5em 1em;
    margin: 0.5em 0;
}
.translation-text p {
    display: inline;
    margin: 0;
}
.study-notes {
    margin-left: 0.5em;
    font-size: 0.85em;
    color: #555;
    overflow-wrap: anywhere;
}
.study-note {
    display: inline;
}
.para-block {
    margin: 1.5em 0;
    border-bottom: 1px solid #eee;
    padding-bottom: 1em;
}
ruby rt {
    font-size: 0.6em;
    color: #666;
}
h1 {
    border-bottom: 2px solid #333;
    padding-bottom: 0.3em;
}
hr {
    border: none;
    border-top: 1px dashed #aaa;
    margin: 2em 0;
}
""")
        lines.append("</style>")
        lines.append("</head>")
        lines.append("<body>")

        if book_title:
            lines.append(f"<h1>{book_title}</h1>")

        lines.append('<div class="book-content">')
        for item in chapter_htmls:
            if item is None:
                continue
            _title, html_list = item
            lines.extend(html_list)
        lines.append("</div>")

        all_kanji = self._kanji_tracker.get_all_kanji()
        all_vocab = self._kanji_tracker.get_all_vocab()
        if all_kanji or all_vocab:
            lines.append("<hr/>")
            lines.append("<h2>総合単語帳</h2>")
            lines.append('<table border="1" style="border-collapse:collapse;width:100%">')
            lines.append("<tr><th>表記</th><th>読み</th><th>意味</th><th>비고</th><th>初出</th></tr>")
            for entry in all_vocab:
                lines.append(
                    f"<tr><td><ruby><rb>{html.escape(entry.expression)}</rb><rt>{html.escape(entry.reading)}</rt></ruby></td>"
                    f"<td>{html.escape(entry.reading)}</td>"
                    f"<td>{html.escape(entry.meaning)}</td>"
                    f"<td>{html.escape(entry.notes)}</td>"
                    f"<td>{html.escape(entry.first_appearance)}</td></tr>"
                )
            for entry in all_kanji:
                lines.append(
                    f"<tr><td><ruby><rb>{html.escape(entry.kanji)}</rb><rt>{html.escape(entry.reading)}</rt></ruby></td>"
                    f"<td>{html.escape(entry.reading)}</td>"
                    f"<td>{html.escape(entry.meaning)}</td>"
                    f"<td>{html.escape(entry.first_appearance)}</td></tr>"
                )
            lines.append("</table>")

        lines.append("</body>")
        lines.append("</html>")

        return "\n".join(lines)

    def write_to_zip(
        self,
        chapter_htmls: list[tuple[str, list[str]] | None],
        book_title: str,
        zip: Zip,
        chapter_paths: list[str],
    ) -> None:
        """Write study content into existing Zip, preserving all original resources (images, CSS, fonts, cover)."""

        css = b"""\
body {
    font-family: serif;
    line-height: 1.8;
    margin: 1em;
    writing-mode: horizontal-tb !important;
    -webkit-writing-mode: horizontal-tb !important;
    -epub-writing-mode: horizontal-tb !important;
}
.source-text {
    background: #f8f8f8;
    padding: 0.5em 1em;
    border-left: 3px solid #ccc;
    margin: 0.5em 0;
}
.translation-text {
    padding: 0.5em 1em;
    margin: 0.5em 0;
}
.translation-text p {
    display: inline;
    margin: 0;
}
.study-notes {
    margin-left: 0.5em;
    font-size: 0.85em;
    color: #555;
    overflow-wrap: anywhere;
}
.study-note {
    display: inline;
}
.para-block {
    margin: 1.5em 0;
    border-bottom: 1px solid #eee;
    padding-bottom: 1em;
}
ruby rt {
    font-size: 0.6em;
    color: #666;
}
h1 {
    border-bottom: 2px solid #333;
    padding-bottom: 0.3em;
}
hr {
    border: none;
    border-top: 1px dashed #aaa;
    margin: 2em 0;
}
"""
        zip.writestr(Path("OEBPS/style.css"), css)

        for ch_idx, item in enumerate(chapter_htmls):
            if item is None:
                continue
            ch_title, html_parts = item
            ch_path = Path(chapter_paths[ch_idx])
            stylesheet_href = posixpath.relpath("OEBPS/style.css", ch_path.parent.as_posix())
            escaped_title = html.escape(ch_title, quote=True) if ch_title else book_title or f"Chapter {ch_idx + 1}"
            body = _AMP_PATTERN.sub("&amp;", "\n".join(html_parts))
            ch_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" lang="ja" xml:lang="ja">
<head>
<meta charset="utf-8"/>
<title>{escaped_title}</title>
<link rel="stylesheet" type="text/css" href="{stylesheet_href}"/>
</head>
<body>
{body}
</body>
</html>"""
            zip.writestr(ch_path, ch_content)

    def write_clean_to_zip(
        self,
        chapter_translations: list[tuple[str, str] | None],
        book_title: str,
        zip: Zip,
        chapter_paths: list[str],
    ) -> None:
        """Write clean translation-only EPUB into existing Zip."""

        css = b"""\
body {
    font-family: serif;
    line-height: 1.8;
    margin: 1em;
    writing-mode: horizontal-tb !important;
    -webkit-writing-mode: horizontal-tb !important;
    -epub-writing-mode: horizontal-tb !important;
}
p {
    text-indent: 1em;
    margin: 0.5em 0;
}
h1 {
    border-bottom: 2px solid #333;
    padding-bottom: 0.3em;
}
"""
        zip.writestr(Path("OEBPS/style.css"), css)

        for ch_idx, item in enumerate(chapter_translations):
            if item is None:
                continue
            ch_title, trans_html = item
            ch_path = Path(chapter_paths[ch_idx])
            stylesheet_href = posixpath.relpath("OEBPS/style.css", ch_path.parent.as_posix())
            escaped_title = html.escape(ch_title, quote=True) if ch_title else ""
            heading = f"<h1>{escaped_title}</h1>" if ch_title else ""
            trans_body = _AMP_PATTERN.sub("&amp;", trans_html)
            ch_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" lang="{self._target_language}" xml:lang="{self._target_language}">
<head>
<meta charset="utf-8"/>
<title>{escaped_title}</title>
<link rel="stylesheet" type="text/css" href="{stylesheet_href}"/>
</head>
<body>
{heading}
{trans_body}
</body>
</html>"""
            zip.writestr(ch_path, ch_content)
