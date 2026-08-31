import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from rich.console import Console

from pawchive_downloader.downloader import (
    MAX_FULL_PATH,
    DownloadEngine,
    DownloadOptions,
    _content_range_total,
    fit_in_path,
    safe_component,
)
from pawchive_downloader.history import HistoryStore
from pawchive_downloader.models import Creator, Post


def _engine(folder, **options):
    return DownloadEngine(
        None,  # type: ignore[arg-type]
        HistoryStore(Path(folder) / "history", False),
        DownloadOptions(Path(folder), **options),
        Console(),
    )


def _post(**overrides):
    data = {
        "id": "99",
        "user": "7",
        "service": "patreon",
        "title": "Post",
        "file": {"name": "image.png", "path": "/aa/hash.png"},
        "attachments": [],
    }
    data.update(overrides)
    return Post.from_api(data)


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

    def test_absurd_extension_does_not_exceed_limit(self):
        value = safe_component("name." + "x" * 300, max_length=40)
        self.assertLessEqual(len(value), 40)

    def test_files_go_directly_into_creator_folder(self):
        with TemporaryDirectory() as folder:
            job = _engine(folder)._jobs_for_post(_post(), Creator(id="7", service="patreon", name="Artist"))[0]
            self.assertEqual(job.destination.parent, Path(folder) / "Artist [patreon-7]")
            self.assertEqual(job.destination.name, "image [99].png")


class PostFolderTests(unittest.TestCase):
    def test_each_post_gets_its_own_folder(self):
        with TemporaryDirectory() as folder:
            post = _post(published="2024-03-05T10:00:00Z", title="My Post")
            job = _engine(folder, post_folders=True)._jobs_for_post(
                post, Creator(id="7", service="patreon", name="Artist")
            )[0]
            self.assertEqual(
                job.destination.parent,
                Path(folder) / "Artist [patreon-7]" / "2024-03-05 My Post [99]",
            )
            # Inside a post folder the post id in the file name is redundant.
            self.assertEqual(job.destination.name, "image.png")

    def test_folder_without_publish_date(self):
        with TemporaryDirectory() as folder:
            job = _engine(folder, post_folders=True)._jobs_for_post(
                _post(published=None), Creator(id="7", service="patreon", name="Artist")
            )[0]
            self.assertEqual(job.destination.parent.name, "Post [99]")

    def test_metadata_lands_in_the_post_folder(self):
        with TemporaryDirectory() as folder:
            engine = _engine(folder, post_folders=True, metadata=True)
            post = _post(published="2024-03-05T10:00:00Z", title="My Post")
            creator = Creator(id="7", service="patreon", name="Artist")
            engine._write_metadata(post, creator)
            written = Path(folder) / "Artist [patreon-7]" / "2024-03-05 My Post [99]" / "post_99.json"
            self.assertTrue(written.is_file())


class JobBuildingTests(unittest.TestCase):
    def test_repeated_file_names_are_kept_apart(self):
        with TemporaryDirectory() as folder:
            post = _post(
                file={"name": "image.png", "path": "/aa/one.png"},
                attachments=[
                    {"name": "image.png", "path": "/bb/two.png"},
                    {"name": "image.png", "path": "/cc/three.png"},
                ],
            )
            jobs = _engine(folder)._jobs_for_post(post, Creator(id="7", service="patreon", name="Artist"))
            names = [job.destination.name for job in jobs]
            self.assertEqual(len(names), 3)
            self.assertEqual(len(set(names)), 3, names)

    def test_paths_stay_within_the_windows_limit(self):
        with TemporaryDirectory() as folder:
            post = _post(
                id="1234567890",
                title="t" * 150,
                file={"name": "n" * 200 + ".png", "path": "/aa/hash.png"},
            )
            creator = Creator(id="7", service="patreon", name="c" * 150)
            for post_folders in (False, True):
                job = _engine(folder, post_folders=post_folders)._jobs_for_post(post, creator)[0]
                self.assertLessEqual(len(str(job.destination)), MAX_FULL_PATH, job.destination)
                self.assertTrue(job.destination.name.endswith(".png"))

    def test_unknown_creator_does_not_abort_the_run(self):
        with TemporaryDirectory() as folder:
            engine = _engine(folder)
            creator = Creator(id="7", service="patreon", name="Artist")
            # The profile answered with "7" while the post payload says "0007".
            resolved = engine._creator_for(_post(user="0007"), {("patreon", "7"): creator})
            self.assertEqual(resolved, creator)

    def test_missing_creator_id_falls_back_to_a_placeholder(self):
        with TemporaryDirectory() as folder:
            resolved = _engine(folder)._creator_for(_post(user=""), {})
            self.assertEqual(resolved.service, "patreon")
            self.assertEqual(resolved.id, "unknown")


class HelperTests(unittest.TestCase):
    def test_content_range_total(self):
        self.assertEqual(_content_range_total("bytes */1234"), 1234)
        self.assertEqual(_content_range_total("bytes 0-9/10"), 10)
        self.assertIsNone(_content_range_total("bytes */*"))
        self.assertIsNone(_content_range_total(None))

    def test_fit_in_path_keeps_short_names(self):
        self.assertEqual(fit_in_path(Path("C:/out"), "image.png"), "image.png")


if __name__ == "__main__":
    unittest.main()
