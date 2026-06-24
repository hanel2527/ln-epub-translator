import json
import threading
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from epub_translator.study.runner import run_translation


class JobState(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class JobInfo:
    state: JobState = JobState.IDLE
    book_name: str = ""
    book_dir: Path | None = None
    progress_pct: int = 0
    error_message: str = ""
    has_progress_html: bool = False
    has_study_epub: bool = False
    has_clean_epub: bool = False


class TranslationJobManager:
    def __init__(self, output_dir: Path = Path("out")):
        self._output_dir = output_dir
        self._info = JobInfo()
        self._thread: threading.Thread | None = None
        self._abort_event = threading.Event()
        self._lock = threading.Lock()

    @property
    def info(self) -> JobInfo:
        with self._lock:
            return JobInfo(
                state=self._info.state,
                book_name=self._info.book_name,
                book_dir=self._info.book_dir,
                progress_pct=self._info.progress_pct,
                error_message=self._info.error_message,
                has_progress_html=self._info.has_progress_html,
                has_study_epub=self._info.has_study_epub,
                has_clean_epub=self._info.has_clean_epub,
            )

    def _update_file_status(self) -> None:
        if not self._info.book_dir:
            return
        bd = self._info.book_dir
        self._info.has_progress_html = (bd / "_progress.html").exists()
        self._info.has_study_epub = (bd / "translated_study.epub").exists()
        self._info.has_clean_epub = (bd / "translated_study.clean.epub").exists()

        state_path = bd / "_state.json"
        if state_path.exists():
            try:
                data = json.loads(state_path.read_text(encoding="utf-8"))
                completed = data.get("completed_chapters", [])
                total = data.get("total_chapters", 1)
                self._info.progress_pct = int(len(completed) / max(total, 1) * 100)
            except Exception:
                pass

    def start(self, source_path: Path, target_language: str, batch_size: int = 5000,
              dict_path: Path | None = None, resume: bool = False, config: dict | None = None) -> None:
        with self._lock:
            if self._info.state == JobState.RUNNING:
                raise RuntimeError("A translation job is already running")

            self._info = JobInfo(state=JobState.RUNNING, book_name=source_path.stem,
                                 book_dir=self._output_dir / source_path.stem)
            self._abort_event.clear()

        def _run():
            try:
                run_translation(
                    source_path=source_path,
                    target_language=target_language,
                    output_dir=self._output_dir,
                    batch_size=batch_size,
                    dict_path=dict_path,
                    resume=resume,
                    config=config,
                    on_progress=self._on_progress,
                    abort_event=self._abort_event,
                )
                with self._lock:
                    self._info.state = JobState.COMPLETED
                    self._info.progress_pct = 100
                    self._update_file_status()
            except InterruptedError:
                with self._lock:
                    self._info.state = JobState.IDLE
                    self._info.progress_pct = 0
                    self._update_file_status()
            except Exception as exc:
                with self._lock:
                    self._info.state = JobState.ERROR
                    self._info.error_message = str(exc)
                    self._update_file_status()

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        self._abort_event.set()

    def _on_progress(self, chapter_index: int, total: int, title: str) -> None:
        with self._lock:
            self._info.progress_pct = int((chapter_index + 1) / max(total, 1) * 100)
            self._update_file_status()

    def poll(self) -> JobInfo:
        with self._lock:
            if self._info.state == JobState.RUNNING:
                self._update_file_status()
            return JobInfo(
                state=self._info.state,
                book_name=self._info.book_name,
                book_dir=self._info.book_dir,
                progress_pct=self._info.progress_pct,
                error_message=self._info.error_message,
                has_progress_html=self._info.has_progress_html,
                has_study_epub=self._info.has_study_epub,
                has_clean_epub=self._info.has_clean_epub,
            )
