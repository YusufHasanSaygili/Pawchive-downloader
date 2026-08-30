import unittest

from pawchy_downloader.models import Post


class PostTests(unittest.TestCase):
    def test_extracts_valid_files(self):
        post = Post.from_api(
            {
                "id": "9",
                "user": "2",
                "service": "fanbox",
                "title": "Test",
                "published": "2026-08-30T12:00:00",
                "file": {"name": "cover.jpg", "path": "/aa/bb/hash.jpg"},
                "attachments": [{"name": "archive.zip", "path": "/cc/dd/hash.zip"}],
            }
        )
        files = post.remote_files()
        self.assertEqual([item.kind for item in files], ["cover", "attachment"])
        self.assertEqual(post.published.year, 2026)

    def test_rejects_traversal_path(self):
        post = Post.from_api(
            {
                "id": "9",
                "user": "2",
                "service": "fanbox",
                "file": {"name": "bad", "path": "/../secret"},
                "attachments": [],
            }
        )
        self.assertEqual(post.remote_files(), [])

    def test_deduplicates_same_remote_path(self):
        post = Post.from_api(
            {
                "id": "9",
                "user": "2",
                "service": "fanbox",
                "file": {"name": "a.jpg", "path": "/aa/bb/hash.jpg"},
                "attachments": [{"name": "copy.jpg", "path": "/aa/bb/hash.jpg"}],
            }
        )
        self.assertEqual(len(post.remote_files()), 1)


if __name__ == "__main__":
    unittest.main()
