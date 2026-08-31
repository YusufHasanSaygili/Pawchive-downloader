from __future__ import annotations

import os
import shutil
import sqlite3
from stat import S_ISREG
from pathlib import Path


HISTORY_FILENAME = ".pawchive-history.sqlite3"
# Databases written by older releases of this tool. They are adopted on first
# run so an upgrade does not throw away the download history.
LEGACY_HISTORY_FILENAMES = (".pawchy-history.sqlite3",)
# SQLite sidecar files that must travel with the database when it is adopted.
_SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")


class HistoryStore:
    """Records completed downloads so repeat runs can skip or hardlink them."""

    def __init__(self, path: Path, enabled: bool = True, commit_every: int = 64) -> None:
        self.path = path
        self.enabled = enabled
        self.commit_every = max(1, commit_every)
        self.connection: sqlite3.Connection | None = None
        self._pending = 0

    def __enter__(self) -> "HistoryStore":
        if not self.enabled:
            return self
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.adopt_legacy_database()
        # The connection is only used from the download event loop, but the web
        # UI runs that loop on a worker thread, so the same-thread check is off.
        self.connection = sqlite3.connect(self.path, check_same_thread=False)
        # WAL plus NORMAL sync keeps per-file bookkeeping off the fsync path.
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=NORMAL")
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS downloads (
                source_path TEXT PRIMARY KEY,
                destination TEXT NOT NULL,
                size INTEGER NOT NULL,
                service TEXT NOT NULL,
                creator_id TEXT NOT NULL,
                post_id TEXT NOT NULL,
                completed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self.connection.commit()
        self._pending = 0
        return self

    def __exit__(self, *_: object) -> None:
        if self.connection:
            try:
                if self._pending:
                    self.connection.commit()
            finally:
                self._pending = 0
                self.connection.close()
                self.connection = None

    def adopt_legacy_database(self) -> Path | None:
        """Rename a database left by an earlier name of this tool into place.

        Returns the adopted source path, or None when there was nothing to do.
        Only the default history filename is migrated; an explicit --history
        path is always taken literally.
        """
        if self.path.name != HISTORY_FILENAME or self.path.exists():
            return None
        for name in LEGACY_HISTORY_FILENAMES:
            legacy = self.path.with_name(name)
            if legacy == self.path or not legacy.is_file():
                continue
            try:
                os.replace(legacy, self.path)
            except OSError:
                try:
                    shutil.copy2(legacy, self.path)
                except OSError:
                    continue
            # Uncheckpointed transactions live in the sidecars, so move them too.
            for suffix in _SIDECAR_SUFFIXES:
                sidecar = legacy.with_name(legacy.name + suffix)
                if not sidecar.is_file():
                    continue
                try:
                    os.replace(sidecar, self.path.with_name(self.path.name + suffix))
                except OSError:
                    pass
            return legacy
        return None

    def lookup(self, source_path: str) -> tuple[Path, int] | None:
        """Return the recorded (destination, size) for a remote path."""
        if not self.connection:
            return None
        row = self.connection.execute(
            "SELECT destination, size FROM downloads WHERE source_path = ?", (source_path,)
        ).fetchone()
        if not row:
            return None
        return Path(row[0]), int(row[1])

    def contains(self, source_path: str, destination: Path) -> bool:
        record = self.lookup(source_path)
        if not record or record[0] != destination:
            return False
        return _matches_on_disk(destination, record[1])

    def find_existing(self, source_path: str) -> Path | None:
        record = self.lookup(source_path)
        if not record:
            return None
        return record[0] if _matches_on_disk(record[0], record[1]) else None

    def record(
        self,
        source_path: str,
        destination: Path,
        size: int,
        service: str,
        creator_id: str,
        post_id: str,
    ) -> None:
        if not self.connection:
            return
        self.connection.execute(
            """
            INSERT INTO downloads(source_path, destination, size, service, creator_id, post_id)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_path) DO UPDATE SET
              destination=excluded.destination,
              size=excluded.size,
              service=excluded.service,
              creator_id=excluded.creator_id,
              post_id=excluded.post_id,
              completed_at=CURRENT_TIMESTAMP
            """,
            (source_path, str(destination), size, service, creator_id, post_id),
        )
        # Committing per file costs a disk flush each time; batch them instead.
        # A lost batch only means the files are re-checked, never re-downloaded,
        # because an existing destination is skipped on its own.
        self._pending += 1
        if self._pending >= self.commit_every:
            self.connection.commit()
            self._pending = 0

    def flush(self) -> None:
        if self.connection and self._pending:
            self.connection.commit()
            self._pending = 0


def _matches_on_disk(destination: Path, size: int) -> bool:
    try:
        info = os.stat(destination)
    except OSError:
        return False
    return S_ISREG(info.st_mode) and info.st_size == size
