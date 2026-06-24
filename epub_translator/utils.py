import json
import re
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


def _find_format_json() -> Path:
    """Search for format.json in CWD, then parent directories, then script-relative paths."""
    candidates = [
        Path.cwd() / "format.json",
        Path(__file__).parent.parent / "format.json",
    ]
    for p in candidates:
        resolved = p.resolve()
        if resolved.exists():
            return resolved
    return Path.cwd() / "format.json"


def read_format_json() -> dict:
    path = _find_format_json()
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_format_json(data: dict) -> None:
    path = _find_format_json()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
