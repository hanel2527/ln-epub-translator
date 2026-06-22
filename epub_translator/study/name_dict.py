from pathlib import Path


def parse_name_dict(path: str | Path) -> dict[str, str | None]:
    """Parse markdown dictionary file.

    Format:
        # Name Dictionary
        - 馬剃天愛星: 바소리 티아라
        - 氷堂伊吹: 히도 이부키

        # Notes
        - Use informal speech for first-person narrative

    Returns: { term: translation or None if it's a plain note }
    """
    path = Path(path)
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    return _parse_dict_text(text)


def _parse_dict_text(text: str) -> dict[str, str | None]:
    entries: dict[str, str | None] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("- "):
            continue
        line = line[2:]
        if ":" in line:
            term, _, translation = line.partition(":")
            term = term.strip()
            translation = translation.strip()
            if term:
                entries[term] = translation if translation else None
        else:
            entries[line] = None
    return entries


def format_dict_for_prompt(entries: dict[str, str | None]) -> str:
    if not entries:
        return ""
    parts: list[str] = []
    terminologies: list[str] = []
    notes: list[str] = []
    for term, translation in entries.items():
        if translation:
            terminologies.append(f"- {term} → {translation}")
        else:
            notes.append(f"- {term}")
    if terminologies:
        parts.append("TERMINOLOGY DICTIONARY:\n" + "\n".join(terminologies))
    if notes:
        parts.append("NOTES:\n" + "\n".join(notes))
    return "\n\n".join(parts)
