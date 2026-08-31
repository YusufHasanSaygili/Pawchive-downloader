import asyncio
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from rich.console import Console

from pawchive_downloader.downloader import DownloadEngine, DownloadOptions
from pawchive_downloader.history import HISTORY_FILENAME, HistoryStore
from pawchive_downloader.models import Creator, Post


class FakeContent:
    def __init__(self, payload):
        self.payload = payload

    async def iter_chunked(self, size):
        for start in range(0, len(self.payload), size):
            yield self.payload[start : start + size]


class FakeResponse:
    def __init__(self, status, payload=b"", headers=None):
        self.status = status
        self.headers = headers or {}
        self.content = FakeContent(payload)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def read(self):
        return b""

    def raise_for_status(self):
        if self.status >= 400:
            raise OSError(f"HTTP {self.status}")


class FakeSession:
    """Serves canned responses and records the requests it was given."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def get(self, url, headers=None, allow_redirects=True, timeout=None):
        self.requests.append((url, dict(headers or {})))
        return self.responses.pop(0)


def _post():
    return Post.from_api(
        {
            "id": "99",
            "user": "7",
            "service": "patreon",
            "title": "Post",
            "file": {"name": "image.png", "path": "/aa/hash.png"},
            "attachments": [],
        }
    )


CREATOR = Creator(id="7", service="patreon", name="Artist")


def _run(folder, session, **options):
    with HistoryStore(Path(folder) / HISTORY_FILENAME) as history:
        engine = DownloadEngine(
            session, history, DownloadOptions(Path(folder), **options), Console(quiet=True)
        )
        summary = asyncio.run(engine.run([_post()], {("patreon", "7"): CREATOR}))
    return summary


def _destination(folder):
    return Path(folder) / "Artist [patreon-7]" / "image [99].png"


class DownloadTests(unittest.TestCase):
    def test_plain_download_is_written_and_recorded(self):
        with TemporaryDirectory() as folder:
            session = FakeSession([FakeResponse(200, b"payload")])
            summary = _run(folder, session)
            self.assertEqual(summary.downloaded, 1)
            self.assertEqual(_destination(folder).read_bytes(), b"payload")
            with HistoryStore(Path(folder) / HISTORY_FILENAME) as history:
                self.assertEqual(history.lookup("/aa/hash.png"), (_destination(folder), 7))

    def test_existing_file_is_skipped_without_a_request(self):
        with TemporaryDirectory() as folder:
            destination = _destination(folder)
            destination.parent.mkdir(parents=True)
            destination.write_bytes(b"payload")
            session = FakeSession([])
            summary = _run(folder, session)
            self.assertEqual(summary.skipped, 1)
            self.assertEqual(session.requests, [])

    def test_partial_file_resumes_with_a_range_header(self):
        with TemporaryDirectory() as folder:
            destination = _destination(folder)
            destination.parent.mkdir(parents=True)
            destination.with_name(destination.name + ".part").write_bytes(b"pay")
            session = FakeSession([FakeResponse(206, b"load")])
            summary = _run(folder, session)
            self.assertEqual(summary.downloaded, 1)
            self.assertEqual(session.requests[0][1]["Range"], "bytes=3-")
            self.assertEqual(destination.read_bytes(), b"payload")

    def test_matching_partial_is_promoted_on_416(self):
        with TemporaryDirectory() as folder:
            destination = _destination(folder)
            destination.parent.mkdir(parents=True)
            destination.with_name(destination.name + ".part").write_bytes(b"payload")
            session = FakeSession([FakeResponse(416, headers={"Content-Range": "bytes */7"})])
            summary = _run(folder, session)
            self.assertEqual(summary.downloaded, 1)
            self.assertEqual(destination.read_bytes(), b"payload")

    def test_oversized_partial_is_discarded_on_416(self):
        # The partial does not match the remote file, so promoting it would
        # store a corrupt file and record it as complete forever.
        with TemporaryDirectory() as folder:
            destination = _destination(folder)
            destination.parent.mkdir(parents=True)
            destination.with_name(destination.name + ".part").write_bytes(b"garbage-and-more")
            session = FakeSession(
                [
                    FakeResponse(416, headers={"Content-Range": "bytes */7"}),
                    FakeResponse(200, b"payload"),
                ]
            )
            summary = _run(folder, session)
            self.assertEqual(summary.downloaded, 1)
            self.assertEqual(destination.read_bytes(), b"payload")
            # The retry started over instead of resuming the bad partial.
            self.assertNotIn("Range", session.requests[1][1])

    def test_unverifiable_416_restarts_the_download(self):
        with TemporaryDirectory() as folder:
            destination = _destination(folder)
            destination.parent.mkdir(parents=True)
            destination.with_name(destination.name + ".part").write_bytes(b"junk")
            session = FakeSession([FakeResponse(416), FakeResponse(200, b"payload")])
            summary = _run(folder, session)
            self.assertEqual(summary.downloaded, 1)
            self.assertEqual(destination.read_bytes(), b"payload")

    def test_failure_is_counted_and_does_not_raise(self):
        with TemporaryDirectory() as folder:
            session = FakeSession([FakeResponse(404)])
            summary = _run(folder, session, retries=1)
            self.assertEqual(summary.failed, 1)
            self.assertFalse(_destination(folder).exists())

    def test_overwrite_discards_a_stale_partial(self):
        with TemporaryDirectory() as folder:
            destination = _destination(folder)
            destination.parent.mkdir(parents=True)
            destination.write_bytes(b"old")
            destination.with_name(destination.name + ".part").write_bytes(b"stale")
            session = FakeSession([FakeResponse(200, b"payload")])
            summary = _run(folder, session, overwrite=True)
            self.assertEqual(summary.downloaded, 1)
            self.assertNotIn("Range", session.requests[0][1])
            self.assertEqual(destination.read_bytes(), b"payload")

    def test_dry_run_writes_nothing(self):
        with TemporaryDirectory() as folder:
            session = FakeSession([])
            summary = _run(folder, session, dry_run=True)
            self.assertEqual(summary.planned, 1)
            self.assertEqual(summary.downloaded, 0)
            self.assertFalse(_destination(folder).parent.exists())

    def test_known_file_elsewhere_is_reused_instead_of_downloaded(self):
        with TemporaryDirectory() as folder:
            other = Path(folder) / "elsewhere.png"
            other.write_bytes(b"payload")
            with HistoryStore(Path(folder) / HISTORY_FILENAME) as history:
                history.record("/aa/hash.png", other, 7, "patreon", "7", "99")
            session = FakeSession([])
            summary = _run(folder, session)
            self.assertEqual(summary.downloaded, 1)
            self.assertEqual(session.requests, [])
            self.assertEqual(_destination(folder).read_bytes(), b"payload")


if __name__ == "__main__":
    unittest.main()
