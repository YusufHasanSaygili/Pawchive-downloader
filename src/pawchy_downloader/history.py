from __future__ import annotations

import sqlite3
from pathlib import Path


class HistoryStore:
    def __init__(self, path: Path, enabled: bool = True) -> None:
        self.path = path
        self.enabled = enabled
        self.connection: sqlite3.Connection | None = None

    def __enter__(self) -> "HistoryStore":
        if not self.enabled:
            return self
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
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
        return self

    def __exit__(self, *_: object) -> None:
        if self.connection:
            self.connection.close()
            self.connection = None

    def contains(self, source_path: str, destination: Path) -> bool:
        if not self.connection:
            return False
        row = self.connection.execute(
            "SELECT destination, size FROM downloads WHERE source_path = ?", (source_path,)
        ).fetchone()
        if not row or not destination.is_file():
            return False
        return Path(row[0]) == destination and destination.stat().st_size == row[1]

    def find_existing(self, source_path: str) -> Path | None:
        if not self.connection:
            return None
        row = self.connection.execute(
            "SELECT destination, size FROM downloads WHERE source_path = ?", (source_path,)
        ).fetchone()
        if not row:
            return None
        path = Path(row[0])
        if path.is_file() and path.stat().st_size == row[1]:
            return path
        return None

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
        self.connection.commit()
