from __future__ import annotations

import subprocess
import sys
import textwrap
import threading
from pathlib import Path

import pytest

from dealradar.core.errors import LockTimeoutError
from dealradar.db.lock import WriterLock


def test_lock_released_after_use(tmp_path: Path) -> None:
    path = tmp_path / "w.lock"
    with WriterLock(path, 1):
        pass
    with WriterLock(path, 1):
        pass


def test_second_thread_times_out(tmp_path: Path) -> None:
    path = tmp_path / "w.lock"
    errors: list[BaseException] = []

    def contender() -> None:
        try:
            with WriterLock(path, 0.3):
                pass
        except BaseException as exc:
            errors.append(exc)

    with WriterLock(path, 1):
        t = threading.Thread(target=contender)
        t.start()
        t.join()
    assert len(errors) == 1 and isinstance(errors[0], LockTimeoutError)


def test_other_process_blocks_writer(tmp_path: Path) -> None:
    path = tmp_path / "w.lock"
    holder = textwrap.dedent(
        f"""
        import sys, time
        from pathlib import Path
        from dealradar.db.lock import WriterLock
        with WriterLock(Path({str(path)!r}), 5):
            print("locked", flush=True)
            sys.stdin.readline()
        """
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", holder], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True
    )
    try:
        assert proc.stdout is not None and proc.stdout.readline().strip() == "locked"
        with pytest.raises(LockTimeoutError), WriterLock(path, 0.5):
            pass
    finally:
        proc.communicate("\n", timeout=10)
    with WriterLock(path, 2):
        pass
