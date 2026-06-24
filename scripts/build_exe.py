#!/usr/bin/env python3
"""
Build a standalone Windows executable for the EPUB Translator Web UI.

Run this ON WINDOWS (PyInstaller cannot cross-compile):
    uv sync --group dev
    python scripts/build_exe.py

Output: dist/epub-translator-webui/epub-translator-webui.exe
"""

import os
import sys
import shutil
from pathlib import Path


def _sep() -> str:
    """Path separator for --add-data: ; on Windows, : on other platforms."""
    return ";" if sys.platform == "win32" else ":"


def _find_unidic_dir() -> str | None:
    """Locate the unidic-lite dictionary directory so PyInstaller can bundle it."""
    try:
        import unidic_lite
        dicdir = os.path.join(os.path.dirname(unidic_lite.__file__), "dicdir")
        if os.path.isdir(dicdir):
            return dicdir
    except ImportError:
        pass
    return None


def main():
    import PyInstaller.__main__

    root = Path(__file__).resolve().parent.parent
    os.chdir(root)

    # Clean previous builds
    for d in ["build", "dist"]:
        shutil.rmtree(d, ignore_errors=True)

    entry = root / "scripts" / "run_webui.py"
    sep = _sep()

    args = [
        str(entry),
        "--name=epub-translator-webui",
        "--onedir",
        "--console",
        "--clean",
        "--noconfirm",
        "--distpath", str(root / "dist"),
        "--workpath", str(root / "build"),
        "--paths", str(root),
        # ── Data files: Jinja templates ──────────────────────────
        *[a for f in (root / "epub_translator" / "data").glob("*.jinja")
          for a in ("--add-data", f"{f}{sep}epub_translator/data")],
        # ── Collect data from packages with bundled resources ────
        "--collect-data", "unidic_lite",
        "--collect-data", "gradio",
        "--collect-data", "jinja2",
        # ── Hidden imports ───────────────────────────────────────
        *[a for mod in (
            "tiktoken", "openai", "jinja2", "gradio",
            "fugashi", "unidic_lite",
            "bs4", "mathml2latex", "resource_segmentation",
            "httpx", "requests",
            "pydantic", "uvicorn", "fastapi", "anyio",
            "websockets", "aiofiles",
            "epub_translator", "epub_translator.epub",
            "epub_translator.llm", "epub_translator.translation",
            "epub_translator.xml", "epub_translator.xml.friendly",
            "epub_translator.segment", "epub_translator.serial",
            "epub_translator.xml_translator", "epub_translator.study",
            "epub_translator.study.kanji_tracker",
            "epub_translator.study.name_dict",
            "epub_translator.study.ruby_annotator",
            "epub_translator.study.translator",
            "epub_translator.study.output",
            "epub_translator.study.runner",
        ) for a in ("--hidden-import", mod)],
    ]

    # ── Optionally bundle unidic-lite dictionary as data ──
    unidic_dir = _find_unidic_dir()
    if unidic_dir:
        args.extend(["--add-data", f"{unidic_dir}{sep}unidic_lite/dicdir"])

    print("=" * 60)
    print("Building epub-translator-webui.exe with PyInstaller")
    print("=" * 60)
    print()

    PyInstaller.__main__.run(args)

    print()
    print("=" * 60)
    print("Build complete!")
    print(f"  EXE: dist{sep}epub-translator-webui{sep}epub-translator-webui.exe")
    print()
    print("To distribute:")
    print("  Zip the entire dist/epub-translator-webui/ folder.")
    print()
    print("The user needs a format.json next to the .exe (see format.template.json).")
    print("=" * 60)


if __name__ == "__main__":
    main()
