from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import quote

import aiohttp

from .models import Creator, Post, Target


class ApiError(RuntimeError):
    pass


class PawchiveAPI:
    def __init__(
        self,
        *,
        session_cookie: str | None = None,
        timeout: float = 60,
        retries: int = 4,
        base_url: str = "https://pawchive.pw/api/v1",
        connection_limit: int = 6,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.session_cookie = session_cookie
        self.timeout = timeout
        self.retries = max(1, retries)
        self.connection_limit = max(1, connection_limit)
        self.session: aiohttp.ClientSession | None = None

    async def __aenter__(self) -> "PawchiveAPI":
        headers = {
            "User-Agent": "PawchiveDownloader/0.1 (+https://pawchive.pw/)",
            "Accept": "application/json",
        }
        cookies = {"session": self.session_cookie} if self.session_cookie else None
        timeout = aiohttp.ClientTimeout(total=self.timeout)
        # Downloads share this session, so the pool has to be at least as wide as
        # the requested concurrency. A fixed limit_per_host would otherwise cap
        # the whole run at ten parallel transfers no matter what the user asked
        # for, because every file comes from the same host.
        per_host = max(self.connection_limit, 10)
        connector = aiohttp.TCPConnector(
            limit=per_host + 4, limit_per_host=per_host, ttl_dns_cache=300
        )
        self.session = aiohttp.ClientSession(headers=headers, cookies=cookies, timeout=timeout, connector=connector)
        return self

    async def __aexit__(self, *_: object) -> None:
        if self.session:
            await self.session.close()
            self.session = None

    async def creator(self, target: Target) -> Creator:
        path = f"/{quote(target.service, safe='')}/user/{quote(target.creator_id, safe='')}/profile"
        data = await self._json(path)
        if not isinstance(data, dict):
            raise ApiError("Unexpected API response for creator profile")
        return Creator.from_api(data)

    async def post(self, target: Target) -> Post:
        if not target.post_id:
            raise ValueError("Post ID is missing")
        path = (
            f"/{quote(target.service, safe='')}/user/{quote(target.creator_id, safe='')}"
            f"/post/{quote(target.post_id, safe='')}"
        )
        data = await self._json(path)
        if not isinstance(data, dict):
            raise ApiError("Unexpected API response for post")
        return Post.from_api(data)

    async def creator_posts(self, target: Target, max_posts: int | None = None) -> AsyncIterator[Post]:
        offset = 0
        page_size = 0
        seen: set[tuple[str, str, str]] = set()
        while max_posts is None or len(seen) < max_posts:
            path = f"/{quote(target.service, safe='')}/user/{quote(target.creator_id, safe='')}"
            data = await self._json(path, params={"o": offset})
            if not isinstance(data, list):
                raise ApiError("Unexpected API response for post list")
            if not data:
                break
            # The page size is whatever the API decides to return. Assuming 50
            # would stop paging after the first page on any other size, silently
            # downloading part of a creator.
            if not page_size:
                page_size = len(data)
            new_items = 0
            for raw in data:
                if not isinstance(raw, dict):
                    continue
                post = Post.from_api(raw)
                if post.key in seen:
                    continue
                seen.add(post.key)
                new_items += 1
                yield post
                if max_posts is not None and len(seen) >= max_posts:
                    return
            if len(data) < page_size or new_items == 0:
                break
            offset += len(data)

    async def _json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        if not self.session:
            raise RuntimeError("API session has not been started")
        url = f"{self.base_url}{path}"
        last_error: Exception | None = None
        for attempt in range(self.retries):
            try:
                async with self.session.get(url, params=params, allow_redirects=True) as response:
                    if response.status == 404:
                        raise ApiError(f"Pawchive resource not found: {url}")
                    if response.status == 429 or response.status >= 500:
                        retry_after = response.headers.get("Retry-After")
                        delay = float(retry_after) if retry_after and retry_after.isdigit() else min(2**attempt, 15)
                        await response.read()
                        # Without this the final error would read "failed: None"
                        # when every attempt was throttled.
                        last_error = ApiError(f"Pawchive API HTTP {response.status}")
                        if attempt + 1 >= self.retries:
                            break
                        await asyncio.sleep(delay)
                        continue
                    if response.status >= 400:
                        body = (await response.text())[:300]
                        raise ApiError(f"Pawchive API HTTP {response.status}: {body}")
                    return await response.json(content_type=None)
            except ApiError:
                raise
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                last_error = exc
                if attempt + 1 < self.retries:
                    await asyncio.sleep(min(2**attempt, 15))
        raise ApiError(f"Pawchive API request failed: {last_error}")
