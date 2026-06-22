import re
from dataclasses import dataclass, field

_KANJI_CHARS = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")


def _unique_kanji(text: str) -> set[str]:
    return set(_KANJI_CHARS.findall(text))


@dataclass
class KanjiEntry:
    kanji: str
    reading: str
    meaning: str
    first_appearance: str
    examples: list[str] = field(default_factory=list)


@dataclass
class VocabEntry:
    expression: str
    reading: str
    meaning: str
    first_appearance: str
    notes: str = ""
    examples: list[str] = field(default_factory=list)


@dataclass
class ParagraphGlossary:
    paragraph_index: int
    kanji_entries: list[KanjiEntry]
    vocab_entries: list[VocabEntry]


class KanjiTracker:
    def __init__(self) -> None:
        self._seen_kanji: set[str] = set()
        self._kanji_entries: dict[str, KanjiEntry] = {}
        self._seen_vocab: set[str] = set()
        self._vocab_entries: dict[str, VocabEntry] = {}
        self._chapter_kanji_entries: dict[int, list[KanjiEntry]] = {}
        self._chapter_vocab_entries: dict[int, list[VocabEntry]] = {}
        self._paragraph_glossaries: dict[int, ParagraphGlossary] = {}
        self._current_chapter: int = 0
        self._current_paragraph: int = 0
        self._chapter_title: str = ""

    @property
    def current_chapter(self) -> int:
        return self._current_chapter

    def set_chapter(self, chapter_index: int, title: str = "") -> None:
        self._current_chapter = chapter_index
        self._chapter_title = title
        if chapter_index not in self._chapter_kanji_entries:
            self._chapter_kanji_entries[chapter_index] = []
        if chapter_index not in self._chapter_vocab_entries:
            self._chapter_vocab_entries[chapter_index] = []

    def set_paragraph(self, paragraph_index: int) -> None:
        self._current_paragraph = paragraph_index

    def register_new_kanji(
        self,
        text: str,
        reading: str,
        meaning: str,
        chapter_title: str = "",
    ) -> list[KanjiEntry]:
        new_entries: list[KanjiEntry] = []
        new_kanji = _unique_kanji(text) - self._seen_kanji
        for single_kanji in sorted(new_kanji):
            entry = KanjiEntry(
                kanji=single_kanji,
                reading=reading if len(single_kanji) == 1 else "",
                meaning=meaning,
                first_appearance=f"Ch.{self._current_chapter}: {chapter_title}",
            )
            self._seen_kanji.add(single_kanji)
            self._kanji_entries[single_kanji] = entry
            self._chapter_kanji_entries.setdefault(self._current_chapter, []).append(entry)
            new_entries.append(entry)
        return new_entries

    def register_new_vocab(
        self,
        expression: str,
        reading: str,
        meaning: str,
        chapter_title: str = "",
        notes: str = "",
    ) -> VocabEntry | None:
        if expression in self._seen_vocab:
            return None
        self._seen_vocab.add(expression)
        entry = VocabEntry(
            expression=expression,
            reading=reading,
            meaning=meaning,
            first_appearance=f"Ch.{self._current_chapter}: {chapter_title}",
            notes=notes,
        )
        self._vocab_entries[expression] = entry
        self._chapter_vocab_entries.setdefault(self._current_chapter, []).append(entry)
        return entry

    def record_paragraph_glossary(
        self,
        paragraph_index: int,
        kanji_entries: list[KanjiEntry],
        vocab_entries: list[VocabEntry],
    ) -> None:
        if kanji_entries or vocab_entries:
            self._paragraph_glossaries[paragraph_index] = ParagraphGlossary(
                paragraph_index=paragraph_index,
                kanji_entries=kanji_entries,
                vocab_entries=vocab_entries,
            )

    def get_paragraph_glossary(self, paragraph_index: int) -> ParagraphGlossary | None:
        return self._paragraph_glossaries.get(paragraph_index)

    def get_chapter_kanji(self, chapter_index: int) -> list[KanjiEntry]:
        return self._chapter_kanji_entries.get(chapter_index, [])

    def get_chapter_vocab(self, chapter_index: int) -> list[VocabEntry]:
        return self._chapter_vocab_entries.get(chapter_index, [])

    def get_all_kanji(self) -> list[KanjiEntry]:
        return list(self._kanji_entries.values())

    def get_all_vocab(self) -> list[VocabEntry]:
        return list(self._vocab_entries.values())

    def is_vocab_seen(self, expression: str) -> bool:
        return expression in self._seen_vocab

    def is_kanji_seen(self, kanji: str) -> bool:
        return kanji in self._seen_kanji

    def to_dict(self) -> dict:
        return {
            "seen_kanji": list(self._seen_kanji),
            "kanji_entries": [
                {"kanji": k.kanji, "reading": k.reading, "meaning": k.meaning,
                 "first_appearance": k.first_appearance, "examples": k.examples}
                for k in self._kanji_entries.values()
            ],
            "seen_vocab": list(self._seen_vocab),
            "vocab_entries": [
                {"expression": v.expression, "reading": v.reading, "meaning": v.meaning,
                 "first_appearance": v.first_appearance, "notes": v.notes, "examples": v.examples}
                for v in self._vocab_entries.values()
            ],
            "chapter_kanji": {
                str(k): [e.kanji for e in v] for k, v in self._chapter_kanji_entries.items()
            },
            "chapter_vocab": {
                str(k): [e.expression for e in v] for k, v in self._chapter_vocab_entries.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict) -> "KanjiTracker":
        tracker = cls()
        tracker._seen_kanji = set(data.get("seen_kanji", []))
        tracker._seen_vocab = set(data.get("seen_vocab", []))
        for ed in data.get("kanji_entries", []):
            entry = KanjiEntry(**ed)
            tracker._kanji_entries[entry.kanji] = entry
        for ed in data.get("vocab_entries", []):
            entry = VocabEntry(**ed)
            tracker._vocab_entries[entry.expression] = entry
        for ch, kanji_list in data.get("chapter_kanji", {}).items():
            ch_int = int(ch)
            tracker._chapter_kanji_entries[ch_int] = [
                tracker._kanji_entries[k] for k in kanji_list if k in tracker._kanji_entries
            ]
        for ch, vocab_list in data.get("chapter_vocab", {}).items():
            ch_int = int(ch)
            tracker._chapter_vocab_entries[ch_int] = [
                tracker._vocab_entries[v] for v in vocab_list if v in tracker._vocab_entries
            ]
        return tracker

    def extract_new_vocab_from_llm(
        self,
        llm_annotations: list[tuple[str, str, str, str]] | None,
        chapter_title: str = "",
    ) -> list[VocabEntry]:
        new_vocab_entries: list[VocabEntry] = []
        if not llm_annotations:
            return new_vocab_entries
        for expr, reading, meaning, notes in llm_annotations:
            new_vocab = self.register_new_vocab(
                expression=expr,
                reading=reading,
                meaning=meaning,
                chapter_title=chapter_title,
                notes=notes,
            )
            if new_vocab:
                new_vocab_entries.append(new_vocab)
        return new_vocab_entries
