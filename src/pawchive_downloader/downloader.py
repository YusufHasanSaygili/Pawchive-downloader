from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from stat import S_ISREG
from typing import Callable
from urllib.parse import quote

import aiohttp
from rich.console import Console
from rich.markup import escape

from .history import HistoryStore
from .models import Creator, Post, RemoteFile


INVALID_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
# Windows rejects paths longer than 260 characters unless long paths are
# enabled, and a download also needs room for the extra ".part" suffix.
MAX_FULL_PATH = 250
CREATOR_NAME_LIMIT = 120
POST_NAME_LIMIT = 100
# Characters held back from the folder budget so a file name always fits.
MIN_NAME_ROOM = 32
CHUNK_SIZE = 1024 * 1024
# The shared session carries a total timeout that suits small API calls. A large
# attachment must not be killed part way through because of it, so downloads use
# idle-based limits instead.
DOWNLOAD_TIMEOUT = aiohttp.ClientTimeout(total=None, connect=30, sock_connect=30, sock_read=120)


def safe_component(value: str, fallback: str = "unnamed", max_length: int = 120) -> str:
    cleaned = INVALID_FILENAME.sub("_", value).strip().rstrip(". ")
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned:
        cleaned = fallback
    if cleaned.split(".", 1)[0].upper() in WINDOWS_RESERVED:
        cleaned = f"_{cleaned}"
    if len(cleaned) > max_length:
        suffix = Path(cleaned).suffix
        if len(suffix) >= max_length:
            suffix = ""
        room = max_length - len(suffix)
        cleaned = cleaned[: max(room, 1)].rstrip(". ") + suffix
    return cleaned


def fit_in_path(folder: Path, name: str) -> str:
    """Shorten a file name so that folder/name stays inside the path limit."""
    room = MAX_FULL_PATH - len(str(folder)) - 1
    if len(name) <= room:
        return name
    if room < 8:
        # The folder alone is already over the limit; trimming cannot save it.
        return name
    return safe_component(name, fallback=name[-room:], max_length=room)


@dataclass(slots=True)
class DownloadOptions:
    output: Path
    concurrency: int = 6
    retries: int = 4
    overwrite: bool = False
    dry_run: bool = False
    include_cover: bool = True
    include_attachments: bool = True
    metadata: bool = False
    post_folders: bool = False


@dataclass(slots=True)
class DownloadJob:
    post: Post
    creator: Creator
    remote: RemoteFile
    destination: Path

    @property
    def url(self) -> str:
        return f"https://file.pawchive.pw/data{self.remote.path}?f={quote(self.remote.name, safe='')}"


@dataclass(slots=True)
class DownloadSummary:
    planned: int = 0
    downloaded: int = 0
    skipped: int = 0
    failed: int = 0
    bytes_written: int = 0


class DownloadEngine:
    def __init__(
        self,
        session: aiohttp.ClientSession,
        history: HistoryStore,
        options: DownloadOptions,
        console: Console,
        progress_callback: Callable[[str, object], None] | None = None,
    ) -> None:
        self.session = session
        self.history = history
        self.options = options
        self.console = console
        self.summary = DownloadSummary()
        self.progress_callback = progress_callback

    async def run(self, posts: list[Post], creators: dict[tuple[str, str], Creator]) -> DownloadSummary:
        pairs = [(post, self._creator_for(post, creators)) for post in posts]
        jobs: list[DownloadJob] = []
        for post, creator in pairs:
            jobs.extend(self._jobs_for_post(post, creator))
        self.summary.planned = len(jobs)
        self.console.print(f"[bold]Found {len(posts)} posts and {len(jobs)} files.[/bold]")
        self._emit("total", len(jobs))
        if self.options.metadata and not self.options.dry_run:
            # A separate thread hop per post costs more than the writes do, so
            # the whole batch goes over in one go.
            await asyncio.to_thread(self._write_all_metadata, pairs)
        try:
            await self._run_jobs(jobs)
        finally:
            self.history.flush()
        return self.summary

    async def _run_jobs(self, jobs: list[DownloadJob]) -> None:
        """Drain the job list with a fixed worker pool.

        A task per file would allocate thousands of tasks up front for a large
        creator; the pool keeps that flat at the concurrency level.
        """
        if not jobs:
            return
        queue: asyncio.Queue[DownloadJob] = asyncio.Queue()
        for job in jobs:
            queue.put_nowait(job)
        workers = [
            asyncio.create_task(self._worker(queue))
            for _ in range(min(max(1, self.options.concurrency), len(jobs)))
        ]
        try:
            await asyncio.gather(*workers)
        finally:
            for worker in workers:
                worker.cancel()

    async def _worker(self, queue: "asyncio.Queue[DownloadJob]") -> None:
        while True:
            try:
                job = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            await self._guarded_download(job)

    def _creator_for(self, post: Post, creators: dict[tuple[str, str], Creator]) -> Creator:
        creator = creators.get((post.service, post.creator_id))
        if creator:
            return creator
        # A post payload can carry a differently cased or missing user id. That
        # must not abort the whole run, so fall back to the closest match.
        folded = post.creator_id.casefold()
        for (service, creator_id), candidate in creators.items():
            if service == post.service and creator_id.casefold() == folded:
                return candidate
        same_service = [value for (service, _), value in creators.items() if service == post.service]
        if len(same_service) == 1:
            return same_service[0]
        creator_id = post.creator_id or "unknown"
        return Creator(id=creator_id, service=post.service, name=creator_id)

    def _folder_budgets(self) -> tuple[int, int]:
        """Split the remaining path length between the folder levels."""
        room = MAX_FULL_PATH - len(str(self.options.output)) - MIN_NAME_ROOM - 2
        creator_budget = CREATOR_NAME_LIMIT
        post_budget = POST_NAME_LIMIT if self.options.post_folders else 0
        if creator_budget + post_budget > room:
            if post_budget:
                creator_budget = max(room * 2 // 3, 12)
                post_budget = max(room - creator_budget, 12)
            else:
                creator_budget = max(room, 12)
        return creator_budget, post_budget

    def _creator_folder(self, creator: Creator, budget: int = CREATOR_NAME_LIMIT) -> Path:
        name = _tagged_name(creator.name, f"[{creator.service}-{creator.id}]", budget, "creator")
        return self.options.output / name

    def _post_folder(self, post: Post, creator: Creator) -> Path:
        creator_budget, post_budget = self._folder_budgets()
        folder = self._creator_folder(creator, creator_budget)
        if not self.options.post_folders:
            return folder
        prefix = f"{post.published.date().isoformat()} " if post.published else ""
        name = _tagged_name(f"{prefix}{post.title}", f"[{post.id}]", post_budget, f"post {post.id}")
        return folder / name

    def _jobs_for_post(self, post: Post, creator: Creator) -> list[DownloadJob]:
        folder = self._post_folder(post, creator)
        used_names: set[str] = set()
        jobs: list[DownloadJob] = []
        for remote in post.remote_files(self.options.include_cover, self.options.include_attachments):
            original = safe_component(remote.name, fallback=remote.path.rsplit("/", 1)[-1])
            if self.options.post_folders:
                # The folder already identifies the post, so keep the real name.
                name = original
            else:
                original_path = Path(original)
                name = safe_component(
                    f"{original_path.stem} [{post.id}]{original_path.suffix}", max_length=180
                )
            room = max(MAX_FULL_PATH - len(str(folder)) - 1, 8)
            name = _unique_name(fit_in_path(folder, name), remote, used_names, min(180, room))
            jobs.append(DownloadJob(post, creator, remote, folder / name))
        return jobs

    def _write_all_metadata(self, pairs: list[tuple[Post, Creator]]) -> None:
        for post, creator in pairs:
            try:
                self._write_metadata(post, creator)
            except OSError as exc:
                self.console.print(f"[red]METADATA FAILED[/red] {escape(post.id)}: {escape(str(exc))}")

    def _write_metadata(self, post: Post, creator: Creator) -> None:
        folder = self._post_folder(post, creator)
        folder.mkdir(parents=True, exist_ok=True)
        name = fit_in_path(folder, f"post_{safe_component(post.id)}.json")
        (folder / name).write_text(json.dumps(post.raw, ensure_ascii=False, indent=2), encoding="utf-8")

    async def _guarded_download(self, job: DownloadJob) -> None:
        try:
            result, size = await self._download(job)
        except Exception as exc:  # Individual files must not cancel the batch.
            self.summary.failed += 1
            self._emit("failed", job)
            self.console.print(f"[red]FAILED[/red] {escape(job.destination.name)}: {escape(str(exc))}")
            return
        if result == "downloaded":
            self.summary.downloaded += 1
            self.summary.bytes_written += size
            self._emit("downloaded", job)
            self.console.print(f"[green]DONE[/green] {escape(str(job.destination))}")
        elif result == "planned":
            self._emit("skipped", job)
            self.console.print(f"[cyan]PLAN[/cyan] {escape(str(job.destination))} <- {escape(job.url)}")
        else:
            self.summary.skipped += 1
            self._emit("skipped", job)
            self.console.print(f"[yellow]SKIPPED[/yellow] {escape(str(job.destination))}")

    async def _download(self, job: DownloadJob) -> tuple[str, int]:
        destination = job.destination
        if self.options.dry_run:
            return "planned", 0
        if not self.options.overwrite:
            if _file_size(destination) is not None:
                return "skipped", 0
            # A single history lookup answers both "already recorded here?" and
            # "already downloaded somewhere else?".
            record = self.history.lookup(job.remote.path)
            if record and record[0] != destination and _file_size(record[0]) == record[1]:
                destination.parent.mkdir(parents=True, exist_ok=True)
                try:
                    os.link(record[0], destination)
                except OSError:
                    shutil.copy2(record[0], destination)
                size = destination.stat().st_size
                self._complete(job, destination, size)
                # Nothing came over the network, so it adds nothing to the
                # transferred byte count.
                return "downloaded", 0

        destination.parent.mkdir(parents=True, exist_ok=True)
        partial = destination.with_name(destination.name + ".part")
        if self.options.overwrite:
            # Overwrite asks for a fresh copy. Resuming a leftover partial here
            # would append new bytes to stale ones and produce a broken file.
            _unlink(partial)
        attempts = max(1, self.options.retries)
        last_error: Exception | None = None
        for attempt in range(attempts):
            existing = _file_size(partial) or 0
            headers = {"Accept": "*/*", "Referer": job.post.page_url}
            if existing:
                headers["Range"] = f"bytes={existing}-"
            try:
                async with self.session.get(
                    job.url, headers=headers, allow_redirects=True, timeout=DOWNLOAD_TIMEOUT
                ) as response:
                    if response.status == 416:
                        await response.read()
                        total = _content_range_total(response.headers.get("Content-Range"))
                        if total is not None and existing == total:
                            os.replace(partial, destination)
                            self._complete(job, destination, total)
                            return "downloaded", total
                        # The partial file does not match the remote file, so it
                        # must not be promoted. Start over from a clean slate.
                        _unlink(partial)
                        last_error = RuntimeError("Server rejected the resume range")
                        continue
                    if response.status in {429, 500, 502, 503, 504}:
                        await response.read()
                        raise aiohttp.ClientResponseError(
                            response.request_info,
                            response.history,
                            status=response.status,
                            message="temporary server error",
                            headers=response.headers,
                        )
                    response.raise_for_status()
                    mode = "ab" if response.status == 206 and existing else "wb"
                    with partial.open(mode) as handle:
                        async for chunk in response.content.iter_chunked(CHUNK_SIZE):
                            handle.write(chunk)
                os.replace(partial, destination)
                size = destination.stat().st_size
                self._complete(job, destination, size)
                return "downloaded", size
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as exc:
                last_error = exc
                if attempt + 1 < attempts:
                    await asyncio.sleep(min(2**attempt, 15))
        raise RuntimeError(f"Download failed after {attempts} attempts: {last_error}")

    def _complete(self, job: DownloadJob, destination: Path, size: int) -> None:
        if job.post.published:
            timestamp = job.post.published.timestamp()
            try:
                os.utime(destination, (timestamp, timestamp))
            except OSError:
                pass
        self.history.record(
            job.remote.path,
            destination,
            size,
            job.post.service,
            job.post.creator_id,
            job.post.id,
        )

    def _emit(self, event: str, value: object) -> None:
        if self.progress_callback:
            self.progress_callback(event, value)


def _tagged_name(base: str, tag: str, budget: int, fallback: str) -> str:
    """Fit "<base> <tag>" into budget characters without ever losing the tag.

    The tag carries the creator or post id, which is what keeps two similarly
    named folders apart, so trimming has to eat into the base instead.
    """
    tag = safe_component(tag, fallback="", max_length=max(budget, 1))
    room = budget - len(tag) - 1
    if room < 4:
        return safe_component(tag or fallback, fallback=fallback, max_length=max(budget, 1))
    trimmed = safe_component(base, fallback=fallback, max_length=room)
    return safe_component(f"{trimmed} {tag}", fallback=fallback, max_length=budget)


def _unique_name(name: str, remote: RemoteFile, used_names: set[str], max_length: int = 180) -> str:
    """Keep file names unique within a folder, comparing case-insensitively.

    max_length is the room the destination folder leaves, so a disambiguated
    name cannot grow back past the path limit.
    """
    if name.casefold() not in used_names:
        used_names.add(name.casefold())
        return name
    # Prefer the content hash from the remote path, then fall back to a counter,
    # so a post with repeated file names never silently loses one.
    path = Path(name)
    digest = remote.path.rsplit("/", 1)[-1].split(".", 1)[0][:8]
    candidate = safe_component(f"{path.stem}__{digest}{path.suffix}", max_length=max_length)
    counter = 2
    while candidate.casefold() in used_names:
        candidate = safe_component(
            f"{path.stem}__{digest}_{counter}{path.suffix}", max_length=max_length
        )
        counter += 1
    used_names.add(candidate.casefold())
    return candidate


def _file_size(path: Path) -> int | None:
    """Size of an existing regular file, or None when there is no such file."""
    try:
        info = os.stat(path)
    except OSError:
        return None
    return info.st_size if S_ISREG(info.st_mode) else None


def _content_range_total(value: str | None) -> int | None:
    """Total size from a `Content-Range: bytes */12345` style header."""
    if not value:
        return None
    _, _, total = value.rpartition("/")
    return int(total) if total.strip().isdigit() else None


def _unlink(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass
