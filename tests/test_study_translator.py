import unittest
from unittest.mock import MagicMock
from xml.etree.ElementTree import fromstring

from jinja2 import Environment, PackageLoader

from epub_translator.llm.error import EmptyResponseError
from epub_translator.study.translator import StudyTranslator


class TestStudyTranslator(unittest.TestCase):
    def setUp(self):
        self.llm = MagicMock()
        self.llm.template.return_value = Environment(
            loader=PackageLoader("epub_translator", "data")
        ).get_template("translate_study.jinja")
        self.translator = StudyTranslator(
            llm=self.llm,
            target_language="English",
            kanji_tracker=MagicMock(),
            ruby_annotator=MagicMock(),
        )

    def respond_with(self, *responses):
        self.llm.context.return_value.__enter__.return_value.request.side_effect = responses

    def test_notes_stay_with_each_source_paragraph(self):
        results = self.translator._parse_response(
            "<p>First translation.</p>"
            "<study>浮ついた means unsettled; 浮 evokes floating.</study>"
            "<study>This sentence uses an informal tone.</study>"
            "<p>Second translation.</p>"
            "<p>Third translation.</p>"
            "<study>浮ついた reappears here with the same floating image.</study>",
            "<p>一</p>\n\n<p>二</p>\n\n<p>三</p>",
        )
        self.assertIsNotNone(results)
        self.assertEqual(
            [(r.source_html, r.translated_html, r.study_notes) for r in results],
            [
                (
                    "<p>一</p>",
                    "<p>First translation.</p>",
                    [
                        "浮ついた means unsettled; 浮 evokes floating.",
                        "This sentence uses an informal tone.",
                    ],
                ),
                ("<p>二</p>", "<p>Second translation.</p>", []),
                (
                    "<p>三</p>",
                    "<p>Third translation.</p>",
                    ["浮ついた reappears here with the same floating image."],
                ),
            ],
        )

    def test_tag_casing_attributes_fences_and_unclosed_studies(self):
        results = self.translator._parse_response(
            "```html\n<P class='translation'>\nFirst<BR/>line\n</P>\n"
            "<STUDY lang='en'>漢字 explanation\nwith another line\n"
            "<P>Second<STUDY>Nested explanation</P>\n"
            "<STUDY>Final explanation without a closing tag",
            "<p>一</p><p>二</p>",
        )
        self.assertIsNotNone(results)
        self.assertEqual(results[0].translated_html, "<p>First\nline</p>")
        self.assertEqual(results[0].study_notes, ["漢字 explanation\nwith another line"])
        self.assertEqual(results[1].translated_html, "<p>Second</p>")
        self.assertEqual(
            results[1].study_notes,
            ["Nested explanation", "Final explanation without a closing tag"],
        )

    def test_nested_study_does_not_leak_into_translation(self):
        results = self.translator._parse_response(
            "<p>Before <study>Free explanation with 漢字.</study>after.</p>",
            "<p>原文</p>",
        )
        self.assertIsNotNone(results)
        self.assertEqual(results[0].translated_html, "<p>Before after.</p>")
        self.assertEqual(results[0].study_notes, ["Free explanation with 漢字."])

    def test_thought_examples_and_untagged_prose_are_not_translations(self):
        results = self.translator._parse_response(
            "Ignore this untagged preface."
            "<THINKING><p>Example</p><study>Example note</study>"
            "<br/><thought><p>Another example</p></thought></THINKING>"
            "<p>Actual translation<thought><p>Hidden</p></thought>.</p>"
            "<study>Actual note.</study>Trailing untagged prose.\n```",
            "<p>原文</p>",
        )
        self.assertIsNotNone(results)
        self.assertEqual(results[0].translated_html, "<p>Actual translation.</p>")
        self.assertEqual(results[0].study_notes, ["Actual note."])
        self.assertIsNone(self.translator._parse_response("Only untagged prose.", "<p>原文</p>"))

    def test_markup_is_text_and_translation_is_safe_xhtml(self):
        results = self.translator._parse_response(
            '<p>A &amp; B &lt;unsafe&gt; "quoted" <em>bold</em><br/>next</p>'
            '<study>漢字 &amp; &lt;img src="x"&gt;<b> explanation</b><br>next</study>',
            "<p>原文</p>",
        )
        self.assertIsNotNone(results)
        self.assertEqual(
            results[0].translated_html,
            "<p>A &amp; B &lt;unsafe&gt; &quot;quoted&quot; bold\nnext</p>",
        )
        self.assertEqual(
            results[0].study_notes,
            ['漢字 & <img src="x"> explanation\nnext'],
        )
        self.assertEqual(
            fromstring(results[0].translated_html).text,
            'A & B <unsafe> "quoted" bold\nnext',
        )

    def test_incomplete_empty_missing_and_extra_translations_are_rejected(self):
        for response in (
            "<p>First</p><p>Truncated",
            "<p>First<p>Second</p>",
            "<p>First</p>",
            "<p>First</p><p>Second</p><p>Extra</p>",
            "<p>First</p><p> \n </p>",
            "<p>First</p><p><study>Only a note</study></p>",
            "<p>First</p><p/>",
            "<study>Notes cannot replace translation paragraphs.</study>",
            "",
        ):
            with self.subTest(response=response):
                self.assertIsNone(self.translator._parse_response(response, "<p>一</p><p>二</p>"))

    def test_source_text_is_escaped_and_ruby_readings_are_excluded(self):
        self.respond_with("<p>Translated.</p>")
        results = self.translator.translate_chapter(
            fromstring('<body><p>A &amp; B &lt; C "quote" <ruby>漢字<rt>かんじ</rt></ruby></p></body>')
        )
        self.assertEqual(results[0].source_html, "<p>A &amp; B &lt; C &quot;quote&quot; 漢字</p>")
        self.assertEqual(fromstring(results[0].source_html).text, 'A & B < C "quote" 漢字')

    def test_split_fallback_preserves_paragraph_and_note_order(self):
        self.respond_with(
            "<p>Truncated batch",
            "<p>First</p><study>First note</study><p>Second</p>",
            "<p>Missing fourth</p>",
            "<p>Third</p><study>Third note</study>",
            "<p>Fourth</p><study>Fourth note</study>",
        )
        results = self.translator.translate_chapter(
            fromstring("<body><p>一</p><p>二</p><p>三</p><p>四</p></body>")
        )
        self.assertEqual(
            [(r.source_html, r.translated_html, r.study_notes) for r in results],
            [
                ("<p>一</p>", "<p>First</p>", ["First note"]),
                ("<p>二</p>", "<p>Second</p>", []),
                ("<p>三</p>", "<p>Third</p>", ["Third note"]),
                ("<p>四</p>", "<p>Fourth</p>", ["Fourth note"]),
            ],
        )

    def test_empty_response_splits_and_terminal_failure_raises(self):
        self.respond_with(EmptyResponseError(), "<p>First</p>", "<p>Second</p>")
        results = self.translator.translate_chapter(fromstring("<body><p>一</p><p>二</p></body>"))
        self.assertEqual([r.translated_html for r in results], ["<p>First</p>", "<p>Second</p>"])

        for response in (EmptyResponseError(), "", "<p> </p>", "<p>Truncated"):
            with self.subTest(response=response):
                self.respond_with(response)
                with self.assertRaisesRegex(ValueError, "complete, nonempty <p> translation"):
                    self.translator.translate_chapter(fromstring("<body><p>一</p></body>"))

    def test_failed_paragraph_after_success_is_not_silently_dropped(self):
        self.respond_with("", "<p>First</p>", "<p>Still truncated")
        with self.assertRaisesRegex(ValueError, "complete, nonempty <p> translation"):
            self.translator.translate_chapter(fromstring("<body><p>一</p><p>二</p></body>"))
