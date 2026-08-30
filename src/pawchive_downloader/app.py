from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable

from rich.console import Console
from rich.markup import escape

from .api import PawchiveAPI
from .downloader import DownloadEngine, DownloadOptions, DownloadSummary
from .history import HistoryStore
from .models import Creator, Post, Target


@dataclass(slots=True)
class RunOptions:
    download: DownloadOptions
    history_file: Path
    session_cookie: str | None = None
    timeout: float = 60
    retries: int = 4
    max_posts: int | None = None
    after: date | None = None
    before: date | None = None


async def run(
    targets: list[Target],
    options: RunOptions,
    console: Console,
    progress_callback: Callable[[str, object], None] | None = None,
) -> DownloadSummary:
    creators: dict[tuple[str, str], Creator] = {}
    posts: dict[tuple[str, str, str], Post] = {}
    collect_limit = asyncio.Semaphore(3)

    async with PawchiveAPI(
        session_cookie=options.session_cookie,
        timeout=options.timeout,
        retries=options.retries,
    ) as api:

        async def collect(target: Target) -> None:
            async with collect_limit:
                creator = await api.creator(target)
                creators[(creator.service, creator.id)] = creator
                if target.post_id:
                    post = await api.post(target)
                    if _in_date_range(post, options.after, options.before):
                        posts[post.key] = post
                    return
                async for post in api.creator_posts(target, options.max_posts):
                    if _in_date_range(post, options.after, options.before):
                        posts[post.key] = post

        results = await asyncio.gather(*(collect(target) for target in targets), return_exceptions=True)
        errors = [result for result in results if isinstance(result, Exception)]
        for error in errors:
            console.print(f"[red]SOURCE ERROR[/red] {escape(str(error))}")
        if errors and len(errors) == len(results):
            raise RuntimeError("No source could be read")

        console.print(f"[bold]Found {len(posts)} posts and " f"{sum(len(p.remote_files(options.download.include_cover, options.download.include_attachments)) for p in posts.values())} files.[/bold]")
        if not api.session:
            raise RuntimeError("Download session is unavailable")
        with HistoryStore(options.history_file, enabled=not options.download.dry_run) as history:
            engine = DownloadEngine(api.session, history, options.download, console, progress_callback)
            return await engine.run(list(posts.values()), creators)


def _in_date_range(post: Post, after: date | None, before: date | None) -> bool:
    if not post.published:
        return after is None and before is None
    published = post.published.date()
    if after and published < after:
        return False
    if before and published > before:
        return False
    return True
