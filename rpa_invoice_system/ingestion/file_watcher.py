"""
Watches the inbox folder for new invoice files and queues them for processing.
Uses watchdog for real-time detection + APScheduler for periodic sweeps.
"""
import hashlib
import logging
import shutil
import time
from datetime import datetime
from pathlib import Path
from queue import Queue
from typing import Callable, Optional

from watchdog.events import FileCreatedEvent, FileSystemEventHandler
from watchdog.observers import Observer

from config import config

logger = logging.getLogger(__name__)


def file_hash(path: Path) -> str:
    sha256 = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


class InvoiceEventHandler(FileSystemEventHandler):
    def __init__(self, queue: Queue, callback: Optional[Callable] = None):
        super().__init__()
        self.queue = queue
        self.callback = callback
        self._seen: set = set()

    def on_created(self, event: FileCreatedEvent):
        if event.is_directory:
            return
        path = Path(event.src_path)
        self._enqueue(path)

    def _enqueue(self, path: Path):
        if path.suffix.lower() not in config.SUPPORTED_EXTENSIONS:
            logger.debug("Skipping unsupported file: %s", path.name)
            return
        if path in self._seen:
            return

        # Brief wait for file to finish writing
        time.sleep(0.5)
        if not path.exists():
            return

        self._seen.add(path)
        item = {
            "path": path,
            "file_hash": file_hash(path),
            "received_at": datetime.utcnow(),
            "file_type": path.suffix.lower().lstrip("."),
        }
        self.queue.put(item)
        logger.info("Queued invoice file: %s", path.name)

        if self.callback:
            try:
                self.callback(item)
            except Exception as exc:
                logger.error("Callback error for %s: %s", path.name, exc)


class InvoiceFileWatcher:
    """
    Monitors config.INBOX_DIR for new invoice files.
    Call .start() to begin watching, .stop() to halt.
    Items placed in self.queue are dicts:
        {path, file_hash, received_at, file_type}
    """

    def __init__(self, callback: Optional[Callable] = None):
        self.inbox = config.INBOX_DIR
        self.queue: Queue = Queue()
        self._handler = InvoiceEventHandler(self.queue, callback)
        self._observer = Observer()
        self._observer.schedule(self._handler, str(self.inbox), recursive=False)

    def start(self):
        self.inbox.mkdir(parents=True, exist_ok=True)
        self._observer.start()
        logger.info("File watcher started on: %s", self.inbox)
        # Sweep for files already sitting in the inbox
        self._sweep_existing()

    def stop(self):
        self._observer.stop()
        self._observer.join()
        logger.info("File watcher stopped.")

    def _sweep_existing(self):
        """Enqueue any files already present in the inbox at startup."""
        for path in sorted(self.inbox.iterdir()):
            if path.is_file():
                self._handler._enqueue(path)

    def move_to_processed(self, path: Path) -> Path:
        dest = config.PROCESSED_DIR / path.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(dest))
        logger.info("Moved to processed: %s", dest.name)
        return dest

    def move_to_failed(self, path: Path) -> Path:
        dest = config.FAILED_DIR / path.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(dest))
        logger.warning("Moved to failed: %s", dest.name)
        return dest
