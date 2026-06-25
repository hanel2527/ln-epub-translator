import json
import re
import shutil
import threading
from dataclasses import dataclass, field
from pathlib import Path

from epub_translator.epub import Zip, read_toc, search_spine_paths
from epub_translator.epub.metadata import read_metadata
from epub_translator.llm import LLM
from epub_translator.study import (
    KanjiTracker,
    RubyAnnotator,
    StudyTranslator,
    format_dict_for_prompt,
    parse_name_dict,
)
from epub_translator.study.output import StudyOutputGenerator
from epub_translator.utils import read_format_json
from epub_translator.xml import XMLLikeNode, find_first


@dataclass
class TranslationResult:
    output_path: Path
    clean_path: Path
    book_dir: Path
    total_chapters: int
    total_kanji: int
    total_vocab: int
    token_stats: dict = field(default_factory=dict)


def _state_path(book_dir: Path) -> Path:
    return book_dir / "_state.json"


def _progress_path(book_dir: Path) -> Path:
    return book_dir / "_progress.html"


def _load_state(book_dir: Path) -> dict | None:
    path = _state_path(book_dir)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def _save_state(book_dir: Path, data: dict) -> None:
    path = _state_path(book_dir)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _save_progress(progress_path: Path, full_html: str) -> None:
    progress_path.parent.mkdir(parents=True, exist_ok=True)
    progress_path.write_text(full_html, encoding="utf-8")


_AUTO_TITLE_PATTERN = re.compile(
    r"^(?:chapter|chaper|ch|section|sec|part|pt)\s*[0-9]+$",
    re.IGNORECASE,
)


def _is_generated_title(title: str) -> bool:
    return bool(_AUTO_TITLE_PATTERN.match(title.strip()))


def _find_chapter_title(toc_list, chapter_index: int) -> str | None:
    if 0 <= chapter_index < len(toc_list):
        toc = toc_list[chapter_index]
        if toc.title:
            return toc.title
    return None


def _load_llm_from_config(log_dir_path: Path, **extra_args) -> LLM:
    config = read_format_json()
    config.pop("translation", None)
    config.pop("fill", None)
    config = {k: v for k, v in config.items() if not k.startswith("_")}
    study_config = config.pop("study", {})
    return LLM(**config, **study_config, **extra_args, log_dir_path=log_dir_path)


def run_translation(
    source_path: Path,
    target_language: str,
    output_dir: Path = Path("out"),
    batch_size: int = 5000,
    dict_path: Path | None = None,
    resume: bool = False,
    config: dict | None = None,
    on_progress: callable = None,
    abort_event: threading.Event | None = None,
) -> TranslationResult:
    if not source_path.exists():
        raise FileNotFoundError(f"Source file '{source_path}' does not exist")

    book_dir = output_dir / source_path.stem
    if not resume:
        shutil.rmtree(book_dir, ignore_errors=True)
    book_dir.mkdir(parents=True, exist_ok=True)

    output_path = book_dir / "translated_study.epub"
    state_data = _load_state(book_dir) if resume else None

    cache_dir = output_dir.parent / "cache"

    if config is not None:
        cfg = dict(config)
        study_cfg = cfg.pop("study", {})
        llm = LLM(**cfg, **study_cfg, log_dir_path=book_dir / "logs", cache_path=cache_dir)
    else:
        llm = _load_llm_from_config(log_dir_path=book_dir / "logs", cache_path=cache_dir)

    dictionary_prompt = ""
    if dict_path:
        dictionary_prompt = format_dict_for_prompt(parse_name_dict(dict_path))

    ruby_annotator = RubyAnnotator()
    kanji_tracker = KanjiTracker()
    completed_indices: set[int] = set()

    if state_data:
        completed_indices = set(state_data.get("completed_chapters", []))
        kanji_tracker = KanjiTracker.from_dict(state_data.get("kanji_tracker", {}))

    translator = StudyTranslator(
        llm=llm,
        target_language=target_language,
        kanji_tracker=kanji_tracker,
        ruby_annotator=ruby_annotator,
        batch_size=batch_size,
        dictionary_prompt=dictionary_prompt,
    )
    output_gen = StudyOutputGenerator(
        kanji_tracker=kanji_tracker,
        ruby_annotator=ruby_annotator,
        target_language=target_language,
    )

    with Zip(source_path=source_path.resolve(), target_path=output_path.resolve()) as epub_zip:
        toc_list, _toc_context = read_toc(epub_zip)
        metadata_fields, _metadata_context = read_metadata(epub_zip)

        chapter_paths = list(search_spine_paths(epub_zip))
        total_chapters = len(chapter_paths)

        if total_chapters == 0:
            raise ValueError("No chapters found in EPUB")

        chapter_results: list[tuple[str, list[str]] | None] = [None] * total_chapters
        chapter_translations: list[tuple[str, str] | None] = [None] * total_chapters

        if state_data:
            loaded_results = state_data.get("chapter_results", [])
            loaded_trans = state_data.get("chapter_translations", [])
            for i in range(min(len(loaded_results), total_chapters)):
                chapter_results[i] = loaded_results[i]
            for i in range(min(len(loaded_trans), total_chapters)):
                chapter_translations[i] = loaded_trans[i]

        book_title = ""
        for field in metadata_fields:
            if field.tag_name == "title":
                book_title = field.text
                break

        for chapter_index, (chapter_path, media_type) in enumerate(chapter_paths):
            if abort_event and abort_event.is_set():
                raise InterruptedError("Translation cancelled by user")

            chapter_title = _find_chapter_title(toc_list, chapter_index) or f"Chapter {chapter_index + 1}"
            display_title = "" if _is_generated_title(chapter_title) else chapter_title

            if chapter_index in completed_indices:
                if on_progress:
                    on_progress(chapter_index, total_chapters, chapter_title)
                continue

            with epub_zip.read(chapter_path) as chapter_file:
                xml = XMLLikeNode(
                    file=chapter_file,
                    is_html_like=(media_type == "text/html"),
                )

            body_element = find_first(xml.element, "body")

            if body_element is None:
                completed_indices.add(chapter_index)
                if on_progress:
                    on_progress(chapter_index, total_chapters, chapter_title)
                continue

            translator.set_chapter(chapter_index, chapter_title)

            results = translator.translate_chapter(body_element)
            if not results:
                completed_indices.add(chapter_index)
                if on_progress:
                    on_progress(chapter_index, total_chapters, chapter_title)
                continue

            paragraphs: list[tuple[str, str]] = []

            for result in results:
                for v in result.vocabulary:
                    expr = v.get("expression", "")
                    reading = v.get("reading", "")
                    meaning = v.get("meaning", "")
                    notes = v.get("notes", "")
                    if expr:
                        kanji_tracker.extract_new_vocab_from_llm(
                            llm_annotations=[(expr, reading, meaning, notes)],
                            chapter_title=chapter_title,
                        )

                src_paras = re.findall(r"<p>(.*?)</p>", result.source_html, re.DOTALL)
                trans_paras = re.findall(r"<p>(.*?)</p>", result.translated_html, re.DOTALL)
                for src_p, trans_p in zip(src_paras, trans_paras):
                    src_p_html = ruby_annotator.add_ruby_to_html(f"<p>{src_p}</p>")
                    trans_p_html = ruby_annotator.add_ruby_to_html(f"<p>{trans_p}</p>")
                    paragraphs.append((src_p_html, trans_p_html))

            chapter_html = output_gen.generate_chapter_html(
                chapter_index=chapter_index,
                chapter_title=display_title,
                paragraphs=paragraphs,
            )

            chapter_translated = "".join(r.translated_html for r in results)
            chapter_translations[chapter_index] = (display_title, chapter_translated)
            chapter_results[chapter_index] = (display_title, [chapter_html])
            completed_indices.add(chapter_index)

            full_html = output_gen.generate_full_html(
                chapter_htmls=chapter_results,
                book_title=book_title,
            )

            _save_progress(_progress_path(book_dir), full_html)
            _save_state(
                book_dir,
                {
                    "completed_chapters": sorted(completed_indices),
                    "kanji_tracker": kanji_tracker.to_dict(),
                    "chapter_results": chapter_results,
                    "chapter_translations": chapter_translations,
                    "book_title": book_title,
                    "total_chapters": total_chapters,
                },
            )

            if on_progress:
                on_progress(chapter_index, total_chapters, chapter_title)

        output_gen.write_to_zip(
            chapter_htmls=chapter_results,
            book_title=book_title,
            zip=epub_zip,
            chapter_paths=[str(p) for p, _ in chapter_paths],
        )

        full_html = output_gen.generate_full_html(
            chapter_htmls=chapter_results,
            book_title=book_title,
        )

        _save_progress(_progress_path(book_dir), full_html)

    clean_path = output_path.with_suffix(".clean.epub")
    with Zip(source_path=source_path.resolve(), target_path=clean_path.resolve()) as clean_zip:
        output_gen.write_clean_to_zip(
            chapter_translations=chapter_translations,
            book_title=book_title,
            zip=clean_zip,
            chapter_paths=[str(p) for p, _ in chapter_paths],
        )

    return TranslationResult(
        output_path=output_path,
        clean_path=clean_path,
        book_dir=book_dir,
        total_chapters=total_chapters,
        total_kanji=len(kanji_tracker.get_all_kanji()),
        total_vocab=len(kanji_tracker.get_all_vocab()),
        token_stats={
            "total_tokens": llm.total_tokens,
            "input_tokens": llm.input_tokens,
            "input_cache_tokens": llm.input_cache_tokens,
            "output_tokens": llm.output_tokens,
        },
    )
