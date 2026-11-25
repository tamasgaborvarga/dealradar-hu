"""Single-writer lock (ADR-018): an OS-level lock on ``<data_dir>/dealradar.lock``.

Held by every writer (CLI runs, UI actions, migrations). Not re-entrant: do not nest writers.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from types import TracebackType
from typing import IO

from dealradar.core.errors import LockTimeoutError

_THREAD_LOCK = threading.Lock()  # serialises writers inside one process (Streamlit threads)
_POLL_S = 0.1


def _try_lock(handle: IO[bytes]) -> bool:
    if sys.platform == "win32":
        import msvcrt

        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True
    import fcntl

    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _unlock(handle: IO[bytes]) -> None:
    if sys.platform == "win32":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class WriterLock:
    def __init__(self, path: Path, timeout_s: float) -> None:
        self.path = path
        self.timeout_s = timeout_s
        self._handle: IO[bytes] | None = None
        self._thread_locked = False

    def acquire(self) -> None:
        deadline = time.monotonic() + self.timeout_s
        if not _THREAD_LOCK.acquire(timeout=self.timeout_s):
            raise LockTimeoutError("another writer in this process holds the lock")
        self._thread_locked = True
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            handle = open(self.path, "a+b")  # noqa: SIM115 - closed in release()
            if handle.seek(0, 2) == 0:
                handle.write(b"\0")
                handle.flush()
            while not _try_lock(handle):
                if time.monotonic() >= deadline:
                    handle.close()
                    raise LockTimeoutError(f"database is busy (lock held: {self.path})")
                time.sleep(_POLL_S)
            self._handle = handle
        except BaseException:
            self._release_thread_lock()
            raise

    def release(self) -> None:
        if self._handle is not None:
            try:
                _unlock(self._handle)
            finally:
                self._handle.close()
                self._handle = None
        self._release_thread_lock()

    def _release_thread_lock(self) -> None:
        if self._thread_locked:
            self._thread_locked = False
            _THREAD_LOCK.release()

    def __enter__(self) -> WriterLock:
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.release()
