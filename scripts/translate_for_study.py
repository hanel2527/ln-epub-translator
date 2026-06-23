import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path

sys.path.append(os.path.abspath(os.path.join(__file__, "..", "..")))

from tqdm import tqdm

from epub_translator.epub import Zip, read_toc, search_spine_paths
from epub_translator.epub.metadata import read_metadata
from epub_translator.llm import LLM
from epub_translator.study import KanjiTracker, RubyAnnotator, StudyTranslator, format_dict_for_prompt, parse_name_dict
from epub_translator.study.output import StudyOutputGenerator
from epub_translator.xml import XMLLikeNode, find_first
from scripts.utils import read_format_json


def load_llm(**args):
    config = read_format_json()
    config.pop("translation", None)
    config.pop("fill", None)
    config = {k: v for k, v in config.items() if not k.startswith("_")}
    study_config = config.pop("study", {})
    llm = LLM(
        **config,
        **study_config,
        **args,
    )
    return llm


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


def main() -> None:
    parser = argparse.ArgumentParser(description="Translate EPUB for Japanese study (with furigana + kanji glossary)")
    parser.add_argument("source_path", type=str, help="Path to the source EPUB file")
    parser.add_argument(
        "-l",
        "--lan",
        type=str,
        default="Chinese",
        help="Target language for translation (default: Chinese)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default="out",
        help="Output directory (default: out). A subdirectory named after the source file will be created.",
    )
    parser.add_argument(
        "-b",
        "--batch-size",
        type=int,
        default=5000,
        help="Characters per batch for LLM translation (default: 5000)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from previous partial run (reads _state.json in book output dir)",
    )
    parser.add_argument(
        "--dict",
        type=str,
        default=None,
        help="Path to markdown dictionary file for proper nouns and style notes",
    )
    args = parser.parse_args()

    source_path = Path(args.source_path)
    if not source_path.exists():
        print(f"Error: Source file '{source_path}' does not exist")
        sys.exit(1)

    target_language = args.lan
    output_dir = Path(args.output)
    batch_size = args.batch_size
    do_resume = args.resume
    dict_path = Path(args.dict) if args.dict else None

    book_dir = output_dir / source_path.stem
    if not do_resume:
        shutil.rmtree(book_dir, ignore_errors=True)
    book_dir.mkdir(parents=True, exist_ok=True)

    output_path = book_dir / "translated_study.epub"
    state_data = _load_state(book_dir) if do_resume else None

    print("Loading LLM configuration...")
    llm = load_llm(
        cache_path=Path(__file__).parent / ".." / "cache",
        log_dir_path=book_dir / "logs",
    )

    dictionary_prompt = format_dict_for_prompt(parse_name_dict(dict_path)) if dict_path else ""
    if dict_path:
        print(f"Loaded dictionary: {dict_path.resolve()}")

    ruby_annotator = RubyAnnotator()
    kanji_tracker = KanjiTracker()
    completed_indices: set[int] = set()

    if state_data:
        completed_indices = set(state_data.get("completed_chapters", []))
        kanji_tracker = KanjiTracker.from_dict(state_data.get("kanji_tracker", {}))
        resume_msg = f"Resuming: {len(completed_indices)} chapters already translated"
        if completed_indices:
            resume_msg += f" (max chapter: {max(completed_indices)})"
        print(resume_msg)

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

    print(f"Opening EPUB: {source_path}")

    with Zip(source_path=source_path.resolve(), target_path=output_path.resolve()) as epub_zip:
        toc_list, _toc_context = read_toc(epub_zip)
        metadata_fields, _metadata_context = read_metadata(epub_zip)

        chapter_paths = list(search_spine_paths(epub_zip))
        total_chapters = len(chapter_paths)

        if total_chapters == 0:
            print("No chapters found.")
            sys.exit(1)

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

        remaining = total_chapters - len(completed_indices)
        with tqdm(total=remaining, desc="Translating", unit="ch") as pbar:
            for chapter_index, (chapter_path, media_type) in enumerate(chapter_paths):
                if chapter_index in completed_indices:
                    continue

                chapter_title = _find_chapter_title(toc_list, chapter_index) or f"Chapter {chapter_index + 1}"

                with epub_zip.read(chapter_path) as chapter_file:
                    xml = XMLLikeNode(
                        file=chapter_file,
                        is_html_like=(media_type == "text/html"),
                    )

                body_element = find_first(xml.element, "body")
                if body_element is None:
                    completed_indices.add(chapter_index)
                    pbar.update(1)
                    continue

                translator.set_chapter(chapter_index, chapter_title)

                results = translator.translate_chapter(body_element)
                if not results:
                    completed_indices.add(chapter_index)
                    pbar.update(1)
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
                    chapter_title=chapter_title,
                    paragraphs=paragraphs,
                )

                chapter_translated = "".join(r.translated_html for r in results)
                chapter_translations[chapter_index] = (chapter_title, chapter_translated)

                chapter_results[chapter_index] = (chapter_title, [chapter_html])
                completed_indices.add(chapter_index)
                pbar.update(1)

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

            print("\nTranslation complete!")
            print(f"Output: {output_path.resolve()}")
            print(f"Total chapters: {total_chapters}")
            print(f"Total kanji tracked: {len(kanji_tracker.get_all_kanji())}")
            print(f"Total vocabulary tracked: {len(kanji_tracker.get_all_vocab())}")

            _print_usage_stats(llm)

        clean_path = output_path.with_suffix(".clean.epub")
        with Zip(source_path=source_path.resolve(), target_path=clean_path.resolve()) as clean_zip:
            output_gen.write_clean_to_zip(
                chapter_translations=chapter_translations,
                book_title=book_title,
                zip=clean_zip,
                chapter_paths=[str(p) for p, _ in chapter_paths],
            )
        print(f"Clean translation: {clean_path.resolve()}")


def _find_chapter_title(toc_list, chapter_index: int) -> str | None:
    if 0 <= chapter_index < len(toc_list):
        toc = toc_list[chapter_index]
        if toc.title:
            return toc.title
    return None


def _print_usage_stats(llm: LLM) -> None:
    print("\n" + "=" * 50)
    print("Token Usage Statistics")
    print("=" * 50)
    print(f"  Total tokens:       {llm.total_tokens:,}")
    print(f"  Input tokens:       {llm.input_tokens:,}")
    print(f"  Input cache tokens: {llm.input_cache_tokens:,}")
    print(f"  Output tokens:      {llm.output_tokens:,}")
    print("=" * 50)


if __name__ == "__main__":
    main()
