import posixpath
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest

from epub_translator.epub.zip import Zip
from epub_translator.study.kanji_tracker import KanjiTracker
from epub_translator.study.output import StudyOutputGenerator
from epub_translator.study.ruby_annotator import RubyAnnotator


@pytest.fixture
def tracker():
    return KanjiTracker()


@pytest.fixture
def generator(tracker):
    return StudyOutputGenerator(tracker, RubyAnnotator(), "ko")


def test_notes_stay_with_each_translation_including_repeated_occurrences(generator, tracker):
    tracker.set_chapter(0, "Chapter")
    tracker.register_new_vocab("言葉", "ことば", "word")
    repeated_note = "言葉(ことば): word"
    chapter = generator.generate_chapter_html(
        0,
        "Chapter",
        [
            (
                "<p><ruby><rb>言葉</rb><rt>ことば</rt></ruby>一</p>",
                "<p>First translation</p>",
                [repeated_note, "A second explanation"],
            ),
            ("<p>言葉二</p>", "<p>Second translation</p>", [repeated_note]),
            ("<p>三</p>", "<p>Third translation</p>", []),
        ],
    )
    root = ET.fromstring(f"<root>{chapter}</root>")
    blocks = root.findall("./div/div[@class='para-block']")
    assert len(blocks) == 3
    for block, translation, notes in zip(
        blocks,
        ["First translation", "Second translation", "Third translation"],
        [[repeated_note, "A second explanation"], [repeated_note], []],
        strict=True,
    ):
        source, translated = list(block)
        assert source.get("class") == "source-text"
        assert translated.get("class") == "translation-text"
        assert translated.find("p").text == translation
        note_wrapper = translated.find("span[@class='study-notes']")
        if notes:
            assert list(translated)[1] is note_wrapper
            assert [note.text for note in note_wrapper.findall("span[@class='study-note']")] == notes
        else:
            assert note_wrapper is None
    assert blocks[0].find("./div[@class='source-text']/p/ruby/rt").text == "ことば"
    assert root.findall(".//details") == []
    assert root.findall(".//study") == []
    assert list(root.find("div")) == blocks


def test_freeform_notes_are_text_not_injectable_markup(generator):
    note = 'Compare A & B: <script>alert("x")</script> > C; <b>not bold</b>'
    chapter = generator.generate_chapter_html(
        0, "", [("<p>原文</p>", "<p>Translation</p>", [note])]
    )
    root = ET.fromstring(chapter)
    rendered_note = root.find(".//span[@class='study-note']")
    assert rendered_note.text == note
    assert list(rendered_note) == []
    assert "&amp;" in chapter
    assert "&lt;script&gt;" in chapter
    assert "&gt; C" in chapter
    assert root.findall(".//script") == []
    assert root.findall(".//b") == []


def test_book_end_glossary_preserves_entries_as_plain_text(generator, tracker):
    tracker.set_chapter(7, "Chapter")
    title = "<em>Chapter & >"
    expression = "言葉<&>"
    reading = "ことば<&>"
    meaning = '<script>alert("x")</script> & >'
    notes = "<b>explanation</b> & >"
    tracker.register_new_vocab(expression, reading, meaning, title, notes)
    tracker.register_new_kanji("字", "じ<&>", meaning, title)
    chapter = generator.generate_chapter_html(
        7, "Chapter", [("<p>原文</p>", "<p>Translation</p>", [])]
    )
    preview = generator.generate_full_html([("Chapter", [chapter])], "Book")
    table_html = preview[preview.index("<table "):preview.index("</table>") + len("</table>")]
    table = ET.fromstring(table_html)
    rows = table.findall("tr")
    assert "総合単語帳" in preview
    assert len(rows) == 3
    vocab_cells = rows[1].findall("td")
    assert vocab_cells[0].find("ruby/rb").text == expression
    assert vocab_cells[0].find("ruby/rt").text == reading
    assert [cell.text for cell in vocab_cells[1:]] == [
        reading, meaning, notes, f"Ch.7: {title}"
    ]
    kanji_cells = rows[2].findall("td")
    assert kanji_cells[0].find("ruby/rb").text == "字"
    assert kanji_cells[0].find("ruby/rt").text == "じ<&>"
    assert [cell.text for cell in kanji_cells[1:]] == [
        "じ<&>", meaning, f"Ch.7: {title}"
    ]
    assert table.findall(".//script") == []
    assert table.findall(".//b") == []
    assert table.findall(".//em") == []
    assert "<details" not in preview


@pytest.mark.parametrize("chapter_path", ["chapter.xhtml", "OEBPS/chapter.xhtml", "OEBPS/Text/chapter.xhtml"])
@pytest.mark.parametrize("clean", [False, True])
def test_epub_stylesheet_resolves_and_clean_output_has_only_translation(generator, tmp_path, chapter_path, clean):
    source_path = tmp_path / "source.epub"
    target_path = tmp_path / "output.epub"
    with ZipFile(source_path, "w"):
        pass
    translation = "<p>Translated text</p>"
    with Zip(source_path, target_path) as archive:
        if clean:
            generator.write_clean_to_zip([("Chapter", translation)], "Book", archive, [chapter_path])
        else:
            chapter = generator.generate_chapter_html(
                0, "Chapter", [("<p>原文</p>", translation, ["An explanation & context"])]
            )
            generator.write_to_zip([("Chapter", [chapter])], "Book", archive, [chapter_path])

    ns = {"x": "http://www.w3.org/1999/xhtml"}
    with ZipFile(target_path) as archive:
        chapter_root = ET.fromstring(archive.read(chapter_path))
        stylesheet_link = chapter_root.find("x:head/x:link[@rel='stylesheet']", ns)
        stylesheet_path = posixpath.normpath(
            posixpath.join(posixpath.dirname(chapter_path), stylesheet_link.get("href"))
        )
        assert stylesheet_path == "OEBPS/style.css"
        assert stylesheet_path in archive.namelist()
        body = chapter_root.find("x:body", ns)
        if clean:
            assert [element.tag for element in body] == [
                "{http://www.w3.org/1999/xhtml}h1", "{http://www.w3.org/1999/xhtml}p"
            ]
            assert body.find("x:p", ns).text == "Translated text"
            assert body.findall(".//x:span[@class='study-notes']", ns) == []
            assert "原文" not in "".join(body.itertext())
            assert "An explanation" not in "".join(body.itertext())
        else:
            translated = body.find(".//x:div[@class='translation-text']", ns)
            assert translated.find("x:p", ns).text == "Translated text"
            assert translated.find("x:span/x:span[@class='study-note']", ns).text == "An explanation & context"
