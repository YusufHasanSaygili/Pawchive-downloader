import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from pawchive_downloader.history import HISTORY_FILENAME, HistoryStore


def _legacy_database(folder: Path, destination: Path) -> Path:
    legacy = folder / ".pawchy-history.sqlite3"
    connection = sqlite3.connect(legacy)
    connection.execute(
        """
        CREATE TABLE downloads (
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
    connection.execute(
        "INSERT INTO downloads(source_path, destination, size, service, creator_id, post_id)"
        " VALUES ('/aa/hash.png', ?, 4, 'patreon', '7', '99')",
        (str(destination),),
    )
    connection.commit()
    connection.close()
    return legacy


class LegacyMigrationTests(unittest.TestCase):
    def test_legacy_database_is_adopted(self):
        with TemporaryDirectory() as name:
            folder = Path(name)
            existing = folder / "image.png"
            existing.write_bytes(b"data")
            legacy = _legacy_database(folder, existing)

            with HistoryStore(folder / HISTORY_FILENAME) as history:
                self.assertEqual(history.find_existing("/aa/hash.png"), existing)

            self.assertFalse(legacy.exists())
            self.assertTrue((folder / HISTORY_FILENAME).is_file())

    def test_existing_database_is_not_replaced(self):
        with TemporaryDirectory() as name:
            folder = Path(name)
            _legacy_database(folder, folder / "image.png")
            with HistoryStore(folder / HISTORY_FILENAME) as history:
                history.record("/bb/other.png", folder / "other.png", 1, "patreon", "7", "99")
            with HistoryStore(folder / HISTORY_FILENAME) as history:
                # The legacy file was already adopted, so a second run keeps the
                # database it just wrote instead of overwriting it.
                self.assertIsNotNone(history.lookup("/bb/other.png"))

    def test_custom_history_path_is_taken_literally(self):
        with TemporaryDirectory() as name:
            folder = Path(name)
            legacy = _legacy_database(folder, folder / "image.png")
            with HistoryStore(folder / "custom.sqlite3") as history:
                self.assertIsNone(history.lookup("/aa/hash.png"))
            self.assertTrue(legacy.is_file())


class RecordTests(unittest.TestCase):
    def test_batched_records_survive_close(self):
        with TemporaryDirectory() as name:
            folder = Path(name)
            target = folder / "image.png"
            target.write_bytes(b"data")
            with HistoryStore(folder / HISTORY_FILENAME, commit_every=1000) as history:
                history.record("/aa/hash.png", target, 4, "patreon", "7", "99")
            with HistoryStore(folder / HISTORY_FILENAME) as history:
                self.assertEqual(history.lookup("/aa/hash.png"), (target, 4))

    def test_size_mismatch_is_not_reused(self):
        with TemporaryDirectory() as name:
            folder = Path(name)
            target = folder / "image.png"
            target.write_bytes(b"data")
            with HistoryStore(folder / HISTORY_FILENAME) as history:
                history.record("/aa/hash.png", target, 999, "patreon", "7", "99")
                self.assertIsNone(history.find_existing("/aa/hash.png"))
                self.assertFalse(history.contains("/aa/hash.png", target))

    def test_disabled_store_records_nothing(self):
        with TemporaryDirectory() as name:
            folder = Path(name)
            with HistoryStore(folder / HISTORY_FILENAME, enabled=False) as history:
                history.record("/aa/hash.png", folder / "image.png", 4, "patreon", "7", "99")
                self.assertIsNone(history.lookup("/aa/hash.png"))
            self.assertFalse((folder / HISTORY_FILENAME).exists())


if __name__ == "__main__":
    unittest.main()
