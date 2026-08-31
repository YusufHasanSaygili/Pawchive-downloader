import asyncio
import unittest

from pawchive_downloader.api import PawchiveAPI
from pawchive_downloader.models import Target


def _raw(post_id):
    return {"id": str(post_id), "user": "7", "service": "patreon", "title": f"Post {post_id}"}


class FakeAPI(PawchiveAPI):
    def __init__(self, pages):
        super().__init__()
        self.pages = pages
        self.offsets = []

    async def _json(self, path, params=None):
        offset = int((params or {}).get("o", 0))
        self.offsets.append(offset)
        return self.pages.get(offset, [])


async def _collect(api, max_posts=None):
    target = Target(service="patreon", creator_id="7")
    return [post.id async for post in api.creator_posts(target, max_posts)]


class PaginationTests(unittest.TestCase):
    def test_page_size_is_learned_from_the_first_page(self):
        # A 25 item page used to be treated as the last page, which silently cut
        # a creator off after the first batch.
        pages = {0: [_raw(i) for i in range(25)], 25: [_raw(i) for i in range(25, 40)]}
        api = FakeAPI(pages)
        ids = asyncio.run(_collect(api))
        self.assertEqual(len(ids), 40)
        # The short second page ends the loop, so there is no third request.
        self.assertEqual(api.offsets, [0, 25])

    def test_full_pages_keep_paging(self):
        pages = {0: [_raw(i) for i in range(50)], 50: [_raw(i) for i in range(50, 60)]}
        ids = asyncio.run(_collect(FakeAPI(pages)))
        self.assertEqual(len(ids), 60)

    def test_repeated_page_stops_the_loop(self):
        page = [_raw(i) for i in range(50)]
        api = FakeAPI({offset: page for offset in (0, 50, 100)})
        ids = asyncio.run(_collect(api))
        self.assertEqual(len(ids), 50)

    def test_max_posts_is_respected(self):
        pages = {0: [_raw(i) for i in range(50)], 50: [_raw(i) for i in range(50, 100)]}
        ids = asyncio.run(_collect(FakeAPI(pages), max_posts=60))
        self.assertEqual(len(ids), 60)

    def test_empty_creator(self):
        self.assertEqual(asyncio.run(_collect(FakeAPI({}))), [])


if __name__ == "__main__":
    unittest.main()
