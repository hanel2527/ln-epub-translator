import json
import re
from dataclasses import dataclass
from xml.etree.ElementTree import Element

from ..llm import LLM, Message, MessageRole
from ..llm.error import EmptyResponseError
from ..segment import InlineSegment, search_inline_segments, search_text_segments
from .kanji_tracker import KanjiTracker
from .ruby_annotator import RubyAnnotator

_JSON_PATTERN = re.compile(r"\{.*\}", re.DOTALL)
_P_PATTERN = re.compile(r"<p>(.*?)</p>", re.DOTALL)


@dataclass
class StudyTranslationResult:
    source_html: str
    translated_html: str
    vocabulary: list[dict[str, str]]


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
    ) -> None:
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
            source_parts.append(text)
        return "<p>" + "".join(source_parts) + "</p>"

    def _translate_batch_with_fallback(self, batch: list[InlineSegment]) -> list[StudyTranslationResult]:
        try:
            result = self._translate_batch(batch)
        except EmptyResponseError:
            result = None

        if result is not None:
            return [result]

        if len(batch) <= 1:
            return []

        mid = len(batch) // 2
        first = self._translate_batch_with_fallback(batch[:mid])
        second = self._translate_batch_with_fallback(batch[mid:])
        return first + second

    def _translate_batch(self, batch: list[InlineSegment]) -> StudyTranslationResult | None:
        combined_source = "\n\n".join(self._build_inline_source(s) for s in batch)

        user_message_text = f"Translate the following Japanese text:\n\n{combined_source}"

        prompt = self._llm.template("translate_study").render(
            target_language=self._target_language,
            source_text=combined_source,
            dictionary=self._dictionary_prompt,
        )

        with self._llm.context(cache_seed_content=None) as ctx:
            response = ctx.request(
                input=[
                    Message(role=MessageRole.SYSTEM, message=prompt),
                    Message(role=MessageRole.USER, message=user_message_text),
                ],
                max_tokens=4096,
                temperature=0.3,
            )

        return self._parse_response(response, combined_source)

    def _parse_response(self, response: str, source_html: str) -> StudyTranslationResult | None:
        json_match = _JSON_PATTERN.search(response)
        if not json_match:
            return None

        try:
            data = json.loads(json_match.group())
        except json.JSONDecodeError:
            return None

        translated_html = data.get("translation", "")
        vocabulary = data.get("vocabulary", [])

        return StudyTranslationResult(
            source_html=source_html,
            translated_html=translated_html,
            vocabulary=vocabulary,
        )

    def strip_ruby_from_source(self, text: str) -> str:
        return self._ruby_annotator.strip_ruby(text)
