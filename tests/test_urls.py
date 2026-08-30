import unittest

from pawchy_downloader.urls import parse_target


class ParseTargetTests(unittest.TestCase):
    def test_creator_url(self):
        target = parse_target("https://pawchive.pw/fanbox/user/22291115")
        self.assertEqual((target.service, target.creator_id, target.post_id), ("fanbox", "22291115", None))

    def test_post_url_with_query(self):
        target = parse_target("https://pawchive.pw/patreon/user/42/post/99?x=1")
        self.assertEqual((target.service, target.creator_id, target.post_id), ("patreon", "42", "99"))

    def test_rejects_unrelated_host(self):
        with self.assertRaises(ValueError):
            parse_target("https://example.com/fanbox/user/1")

    def test_rejects_unknown_page(self):
        with self.assertRaises(ValueError):
            parse_target("https://pawchive.pw/posts")


if __name__ == "__main__":
    unittest.main()

