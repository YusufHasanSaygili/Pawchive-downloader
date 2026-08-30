import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from rich.console import Console

from pawchive_downloader.downloader import DownloadEngine, DownloadOptions, safe_component
from pawchive_downloader.history import HistoryStore
from pawchive_downloader.models import Creator, Post


class FilenameTests(unittest.TestCase):
    def test_windows_invalid_characters(self):
        self.assertEqual(safe_component('a<b>:c?.jpg'), "a_b__c_.jpg")

    def test_windows_reserved_name(self):
        self.assertEqual(safe_component("CON.txt"), "_CON.txt")

    def test_empty_name(self):
        self.assertEqual(safe_component("... ", fallback="file.bin"), "file.bin")

    def test_preserves_extension_when_truncated(self):
        value = safe_component("a" * 200 + ".jpeg", max_length=40)
        self.assertEqual(len(value), 40)
        self.assertTrue(value.endswith(".jpeg"))

    def test_files_go_directly_into_creator_folder(self):
        with TemporaryDirectory() as folder:
            post = Post.from_api({"id":"99","user":"7","service":"patreon","title":"Post","file":{"name":"image.png","path":"/aa/hash.png"},"attachments":[]})
            creator = Creator(id="7", service="patreon", name="Artist")
            engine = DownloadEngine(None, HistoryStore(Path(folder)/"history",False), DownloadOptions(Path(folder)), Console())  # type: ignore[arg-type]
            job = engine._jobs_for_post(post, creator)[0]
            self.assertEqual(job.destination.parent, Path(folder)/"Artist [patreon-7]")
            self.assertEqual(job.destination.name, "image [99].png")


if __name__ == "__main__":
    unittest.main()
