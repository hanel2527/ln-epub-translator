import re
from xml.etree.ElementTree import Element

from fugashi import Tagger

_KATAKANA_TO_HIRAGANA = str.maketrans(
    "アイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモヤユヨラリルレロワヲンガギグゲゴザジズゼゾダヂヅデドバビブベボパピプペポァィゥェォッャュョヮヵヶ",
    "あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわをんがぎぐげござじずぜぞだぢづでどばびぶべぼぱぴぷぺぽぁぃぅぇぉっゃゅょゎゕゖ",
)

_KANJI_PATTERN = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")
_RUBY_PATTERN = re.compile(r"<ruby>\s*<rb>(.*?)</rb>\s*<rt>(.*?)</rt>\s*</ruby>", re.DOTALL)
_RT_ONLY_PATTERN = re.compile(r"<rt>(.*?)</rt>", re.DOTALL)
_RB_ONLY_PATTERN = re.compile(r"<rb>(.*?)</rb>", re.DOTALL)

_JISX0213_KANJI = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]")


def _katakana_to_hiragana(text: str) -> str:
    return text.translate(_KATAKANA_TO_HIRAGANA)


def _contains_kanji(text: str) -> bool:
    return bool(_JISX0213_KANJI.search(text))


class RubyAnnotator:
    def __init__(self) -> None:
        self._tagger = Tagger()

    def extract_ruby_from_xml_element(self, element: Element) -> list[tuple[str, str | None]]:
        result: list[tuple[str, str | None]] = []

        def walk(elem: Element) -> None:
            if elem.tag == "ruby":
                rb_part = ""
                rt_part: str | None = None
                for child in elem:
                    if child.tag == "rb" and child.text:
                        rb_part += child.text
                    if child.tag == "rt" and child.text:
                        rt_part = child.text
                    if child.tail:
                        walk_text_simple(child.tail)
                if rb_part:
                    result.append((rb_part, rt_part))
            else:
                if elem.text:
                    walk_text_simple(elem.text)
                for child in elem:
                    walk(child)
                if elem.tail:
                    walk_text_simple(elem.tail)

        def walk_text_simple(text: str) -> None:
            remaining = text
            for match in _RUBY_PATTERN.finditer(text):
                before = text[: match.start()]
                remaining = text[match.end() :]
                if before:
                    result.append((before, None))
                rb = match.group(1)
                rt = match.group(2)
                result.append((rb, rt or None))
            if remaining:
                result.append((remaining, None))

        walk(element)
        return result

    def get_reading(self, text: str) -> str | None:
        if not _contains_kanji(text):
            return None
        readings: list[str] = []
        for word in self._tagger(text):
            feat = word.feature
            if feat is not None:
                kana = getattr(feat, "kana", None) or getattr(feat, "pron", None) or ""
                if kana:
                    readings.append(_katakana_to_hiragana(kana))
                else:
                    readings.append(word.surface)
            else:
                readings.append(word.surface)
        full_reading = "".join(readings)
        if full_reading == text:
            return None
        return full_reading

    def add_ruby_to_html(self, text: str) -> str:
        output: list[str] = []
        pos = 0

        while pos < len(text):
            match = _RUBY_PATTERN.search(text, pos)
            if match and match.start() == pos:
                rb = match.group(1)
                rt = match.group(2)
                output.append(f"<ruby><rb>{rb}</rb><rt>{rt}</rt></ruby>")
                pos = match.end()
            elif match:
                plain_segment = text[pos : match.start()]
                output.append(self._add_ruby_to_plain_text(plain_segment))
                pos = match.start()
            else:
                plain_segment = text[pos:]
                output.append(self._add_ruby_to_plain_text(plain_segment))
                pos = len(text)

        return "".join(output)

    def _add_ruby_to_plain_text(self, text: str) -> str:
        if not _contains_kanji(text):
            return text
        # Strip any ruby-related tags that may have slipped through
        # (malformed LLM output, etc.) to prevent nested ruby corruption
        text = re.sub(r"</?(?:ruby|rb|rt)>", "", text)
        if not _contains_kanji(text):
            return text
        parts = re.split(r"(<[^>]+>)", text)
        result: list[str] = []
        for part in parts:
            if part.startswith("<") and part.endswith(">"):
                result.append(part)
                continue
            if not _contains_kanji(part):
                result.append(part)
                continue
            tokens: list[tuple[str, str | None]] = []
            for word in self._tagger(part):
                surface = word.surface
                feat = word.feature
                if feat is not None and _contains_kanji(surface):
                    kana = getattr(feat, "kana", None) or getattr(feat, "pron", None) or ""
                    if kana:
                        hiragana = _katakana_to_hiragana(kana)
                        if hiragana != surface:
                            tokens.append((surface, hiragana))
                            continue
                tokens.append((surface, None))
            for text_part, reading in tokens:
                if reading:
                    result.append(f"<ruby><rb>{text_part}</rb><rt>{reading}</rt></ruby>")
                else:
                    result.append(text_part)
        return "".join(result)

    def strip_ruby(self, text: str) -> str:
        result = _RUBY_PATTERN.sub(r"\1", text)
        result = result.replace("<rb>", "").replace("</rb>", "")
        result = result.replace("<rt>", "").replace("</rt>", "")
        return result
