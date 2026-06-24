import argparse
import os
import sys
from pathlib import Path

sys.path.append(os.path.abspath(os.path.join(__file__, "..", "..")))

from tqdm import tqdm

from epub_translator.study.runner import run_translation


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

    dict_path = Path(args.dict) if args.dict else None

    bar = tqdm(total=0, desc="Translating", unit="ch")
    bar_closed = False

    def on_progress(chapter_index: int, total: int, title: str) -> None:
        nonlocal bar_closed
        if bar_closed:
            return
        bar.total = total
        bar.n = chapter_index + 1
        bar.refresh()
        if chapter_index >= total - 1:
            bar.close()
            bar_closed = True

    result = run_translation(
        source_path=Path(args.source_path),
        target_language=args.lan,
        output_dir=Path(args.output),
        batch_size=args.batch_size,
        dict_path=dict_path,
        resume=args.resume,
        on_progress=on_progress,
    )

    if not bar_closed:
        bar.close()

    print("\nTranslation complete!")
    print(f"Output: {result.output_path.resolve()}")
    print(f"Total chapters: {result.total_chapters}")
    print(f"Total kanji tracked: {result.total_kanji}")
    print(f"Total vocabulary tracked: {result.total_vocab}")

    stats = result.token_stats
    print("\n" + "=" * 50)
    print("Token Usage Statistics")
    print("=" * 50)
    print(f"  Total tokens:       {stats.get('total_tokens', 0):,}")
    print(f"  Input tokens:       {stats.get('input_tokens', 0):,}")
    print(f"  Input cache tokens: {stats.get('input_cache_tokens', 0):,}")
    print(f"  Output tokens:      {stats.get('output_tokens', 0):,}")
    print("=" * 50)

    clean_path = result.clean_path
    print(f"Clean translation: {clean_path.resolve()}")


if __name__ == "__main__":
    main()
