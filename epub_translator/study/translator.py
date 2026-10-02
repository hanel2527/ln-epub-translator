import re
from dataclasses import dataclass
from html import escape
from html.parser import HTMLParser
from xml.etree.ElementTree import Element

from ..llm import LLM, Message, MessageRole
from ..llm.error import EmptyResponseError
from ..segment import InlineSegment, search_inline_segments, search_text_segments
from .kanji_tracker import KanjiTracker
from .ruby_annotator import RubyAnnotator

DEFAULT_MAX_OUTPUT_TOKENS = 16384

_SOURCE_PARAGRAPH_PATTERN = re.compile(r"<p>.*?</p>", re.DOTALL)


@dataclass
class StudyTranslationResult:
    source_html: str
    translated_html: str
    study_notes: list[str]


class _StudyResponseParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.paragraphs: list[tuple[str, list[str]]] = []
        self.invalid = False
        self._paragraph_parts: list[str] | None = None
        self._paragraph_notes: list[str] | None = None
        self._study_parts: list[str] | None = None
        self._study_notes: list[str] | None = None
        self._ignored_depth = 0

    def _finish_study(self) -> None:
        if self._study_parts is not None and self._study_notes is not None:
            note = "".join(self._study_parts).strip()
            if note:
                self._study_notes.append(note)
        self._study_parts = None
        self._study_notes = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("thought", "thinking"):
            self._ignored_depth += 1
            return
        if self._ignored_depth:
            return
        if tag == "p":
            self._finish_study()
            if self._paragraph_parts is not None:
                self.invalid = True
            self._paragraph_parts = []
            self._paragraph_notes = []
        elif tag == "study":
            self._finish_study()
            self._study_parts = []
            self._study_notes = self._paragraph_notes
            if self._study_notes is None and self.paragraphs:
                self._study_notes = self.paragraphs[-1][1]
        elif tag == "br":
            self.handle_data("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("thought", "thinking"):
            if self._ignored_depth:
                self._ignored_depth -= 1
            return
        if self._ignored_depth:
            return
        if tag == "study":
            self._finish_study()
        elif tag == "p":
            # Some models close a sibling <study> with </p>. Only the note is
            # ending in that case; a real open translation still needs closing.
            closing_study = self._study_parts is not None
            self._finish_study()
            if self._paragraph_parts is None or self._paragraph_notes is None:
                if not closing_study:
                    self.invalid = True
                return
            translation = "".join(self._paragraph_parts).strip()
            if not translation:
                self.invalid = True
            self.paragraphs.append((translation, self._paragraph_notes))
            self._paragraph_parts = None
            self._paragraph_notes = None

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        if self._study_parts is not None:
            self._study_parts.append(data)
        elif self._paragraph_parts is not None:
            self._paragraph_parts.append(data)

    def finish(self) -> None:
        self.close()
        self._finish_study()
        if self._paragraph_parts is not None:
            self.invalid = True


class StudyTranslator:
    def __init__(
        self,
        llm: LLM,
        target_language: str,
        kanji_tracker: KanjiTracker,
        ruby_annotator: RubyAnnotator,
        batch_size: int = 2000,
        max_paragraphs: int = 120,
        chapter_index: int = 0,
        chapter_title: str = "",
        dictionary_prompt: str = "",
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    ) -> None:
        if isinstance(max_output_tokens, bool) or not isinstance(max_output_tokens, int) or max_output_tokens <= 0:
            raise ValueError("max_output_tokens must be a positive integer")
        self._max_output_tokens = max_output_tokens
        self._llm = llm
        self._target_language = target_language
        self._kanji_tracker = kanji_tracker
        self._ruby_annotator = ruby_annotator
        self._batch_size = batch_size
        self._max_paragraphs = max_paragraphs
        self._chapter_index = chapter_index
        self._chapter_title = chapter_title
        self._dictionary_prompt = dictionary_prompt

    def set_chapter(self, chapter_index: int, title: str = "") -> None:
        self._chapter_index = chapter_index
        self._chapter_title = title
        self._kanji_tracker.set_chapter(chapter_index, title)

    def translate_chapter(self, body_element: Element) -> list[StudyTranslationResult]:
        text_segments = list(search_text_segments(body_element))
        inline_segments = list(search_inline_segments(text_segments))
        if not inline_segments:
            return []

        results: list[StudyTranslationResult] = []
        current_batch: list[InlineSegment] = []
        current_batch_len = 0

        def flush(batch: list[InlineSegment]) -> None:
            if not batch:
                return
            for res in self._translate_batch_with_fallback(batch):
                results.append(res)

        for segment in inline_segments:
            seg_text = self._build_inline_source(segment)
            seg_len = len(seg_text)
            if current_batch and (
                current_batch_len + seg_len > self._batch_size
                or len(current_batch) >= self._max_paragraphs
            ):
                flush(current_batch)
                current_batch = [segment]
                current_batch_len = seg_len
            else:
                current_batch.append(segment)
                current_batch_len += seg_len

        flush(current_batch)

        return results

    def _build_inline_source(self, inline_segment: InlineSegment) -> str:
        source_parts: list[str] = []
        for text_segment in inline_segment:
            if text_segment.parent_stack[-1].tag == "rt":
                continue
            text = text_segment.text
            source_parts.append(escape(text))
        return "<p>" + "".join(source_parts) + "</p>"

    def _translate_batch_with_fallback(self, batch: list[InlineSegment]) -> list[StudyTranslationResult]:
        try:
            result = self._translate_batch(batch)
        except EmptyResponseError:
            result = None

        if result is not None:
            return result

        if len(batch) <= 1:
            raise ValueError("Study translation failed: expected one complete, nonempty <p> translation.")

        mid = len(batch) // 2
        first = self._translate_batch_with_fallback(batch[:mid])
        second = self._translate_batch_with_fallback(batch[mid:])
        return first + second

    def _translate_batch(self, batch: list[InlineSegment]) -> list[StudyTranslationResult] | None:
        combined_source = "\n\n".join(self._build_inline_source(s) for s in batch)

        user_message_text = f"Translate the following Japanese text:\n\n{combined_source}"

        prompt = self._llm.template("translate_study").render(
            target_language=self._target_language,
            dictionary=self._dictionary_prompt,
        )

        with self._llm.context(cache_seed_content=None) as ctx:
            response = ctx.request(
                input=[
                    Message(role=MessageRole.SYSTEM, message=prompt),
                    Message(role=MessageRole.USER, message=user_message_text),
                ],
                max_tokens=self._max_output_tokens,
                temperature=0.3,
            )

        return self._parse_response(response, combined_source)

    def _parse_response(self, response: str, source_html: str) -> list[StudyTranslationResult] | None:
        parser = _StudyResponseParser()
        parser.feed(response)
        parser.finish()
        # Source blocks are produced by _build_inline_source, with all inner text escaped.
        source_paragraphs = _SOURCE_PARAGRAPH_PATTERN.findall(source_html)
        if parser.invalid or not source_paragraphs or len(parser.paragraphs) != len(source_paragraphs):
            return None

        return [
            StudyTranslationResult(
                source_html=source,
                translated_html=f"<p>{escape(translation)}</p>",
                study_notes=notes,
            )
            for source, (translation, notes) in zip(source_paragraphs, parser.paragraphs, strict=True)
        ]

    def strip_ruby_from_source(self, text: str) -> str:
        return self._ruby_annotator.strip_ruby(text)
