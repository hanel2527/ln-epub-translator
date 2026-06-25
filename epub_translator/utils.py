import json
import re
import shutil
from collections.abc import Iterable
from pathlib import Path
from typing import TypeVar

K = TypeVar("K")
T = TypeVar("T")

_WHITESPACE_PATTERN = re.compile(r"\s+")


def normalize_whitespace(text: str) -> str:
    return _WHITESPACE_PATTERN.sub(" ", text)


def is_the_same(elements: Iterable[T]) -> bool:
    iterator = iter(elements)
    try:
        first_element = next(iterator)
    except StopIteration:
        return True

    for element in iterator:
        if element != first_element:
            return False
    return True


def nest(items: Iterable[tuple[K, T]]) -> dict[K, list[T]]:
    nested_dict: dict[K, list[T]] = {}
    for key, value in items:
        ensure_list(nested_dict, key).append(value)
    return nested_dict


def ensure_list(target: dict[K, list[T]], key: K) -> list[T]:
    value = target.get(key, None)
    if value is None:
        value = []
        target[key] = value
    return value


_DEFAULT_FORMAT = {
    "key": "",
    "url": "",
    "model": "",
    "token_encoding": "o200k_base",
    "timeout": 360.0,
    "retry_times": 10,
    "retry_interval_seconds": 0.75,
    "target_language": "Korean",
    "study": {"temperature": 0.3, "top_p": 0.9},
}


def _find_format_json() -> Path:
    """Search for format.json, auto-creating from template or defaults if missing."""
    candidates = [
        Path.cwd() / "format.json",
        Path(__file__).parent.parent / "format.json",
    ]
    for p in candidates:
        resolved = p.resolve()
        if resolved.exists():
            return resolved

    target = (Path.cwd() / "format.json").resolve()

    # Try to copy from template
    template_candidates = [
        Path.cwd() / "format.template.json",
        Path(__file__).parent.parent / "format.template.json",
    ]
    for tp in template_candidates:
        if tp.exists():
            shutil.copy2(str(tp), str(target))
            return target

    # Create with defaults
    target.write_text(json.dumps(_DEFAULT_FORMAT, indent=2) + "\n", encoding="utf-8")
    return target


def read_format_json() -> dict:
    path = _find_format_json()
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_format_json(data: dict) -> None:
    path = _find_format_json()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
