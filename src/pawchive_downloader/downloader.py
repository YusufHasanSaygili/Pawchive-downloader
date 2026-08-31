from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
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


def safe_component(value: str, fallback: str = "unnamed", max_length: int = 120) -> str:
    cleaned = INVALID_FILENAME.sub("_", value).strip().rstrip(". ")
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned:
        cleaned = fallback
    if cleaned.split(".", 1)[0].upper() in WINDOWS_RESERVED:
        cleaned = f"_{cleaned}"
    if len(cleaned) > max_length:
        suffix = Path(cleaned).suffix
        room = max_length - len(suffix)
        cleaned = cleaned[: max(room, 1)].rstrip(". ") + suffix
    return cleaned


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
    separate_post_folders: bool = False


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
        self.semaphore = asyncio.Semaphore(max(1, options.concurrency))
        self.summary = DownloadSummary()
        self.progress_callback = progress_callback

    async def run(self, posts: list[Post], creators: dict[tuple[str, str], Creator]) -> DownloadSummary:
        jobs: list[DownloadJob] = []
        for post in posts:
            creator = creators[(post.service, post.creator_id)]
            if self.options.metadata and not self.options.dry_run:
                await asyncio.to_thread(self._write_metadata, post, creator)
            jobs.extend(self._jobs_for_post(post, creator))
        self.summary.planned = len(jobs)
        self._emit("total", len(jobs))
        await asyncio.gather(*(self._guarded_download(job) for job in jobs))
        return self.summary

    def _post_folder(self, post: Post, creator: Creator) -> Path:
        creator_folder = safe_component(f"{creator.name} [{creator.service}-{creator.id}]")
        folder = self.options.output / creator_folder
        if self.options.separate_post_folders:
            post_folder = safe_component(f"{post.title} [{post.id}]", fallback=f"Post [{post.id}]", max_length=150)
            folder /= post_folder
        return folder

    def _jobs_for_post(self, post: Post, creator: Creator) -> list[DownloadJob]:
        folder = self._post_folder(post, creator)
        used_names: set[str] = set()
        jobs: list[DownloadJob] = []
        for remote in post.remote_files(self.options.include_cover, self.options.include_attachments):
            original = safe_component(remote.name, fallback=remote.path.rsplit("/", 1)[-1])
            original_path = Path(original)
            name = safe_component(f"{original_path.stem} [{post.id}]{original_path.suffix}", max_length=180)
            key = name.casefold()
            if key in used_names:
                path = Path(name)
                digest = remote.path.rsplit("/", 1)[-1].split(".", 1)[0][:8]
                name = safe_component(f"{path.stem}__{digest}{path.suffix}")
                key = name.casefold()
            used_names.add(key)
            jobs.append(DownloadJob(post, creator, remote, folder / name))
        return jobs

    def _write_metadata(self, post: Post, creator: Creator) -> None:
        folder = self._post_folder(post, creator)
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"post_{safe_component(post.id)}.json"
        target.write_text(json.dumps(post.raw, ensure_ascii=False, indent=2), encoding="utf-8")

    async def _guarded_download(self, job: DownloadJob) -> None:
        async with self.semaphore:
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
            if self.history.contains(job.remote.path, destination):
                return "skipped", 0
            if destination.is_file():
                return "skipped", 0
            previous = self.history.find_existing(job.remote.path)
            if previous and previous != destination:
                destination.parent.mkdir(parents=True, exist_ok=True)
                try:
                    os.link(previous, destination)
                except OSError:
                    shutil.copy2(previous, destination)
                size = destination.stat().st_size
                self._complete(job, destination, size)
                return "downloaded", 0

        destination.parent.mkdir(parents=True, exist_ok=True)
        partial = destination.with_name(destination.name + ".part")
        last_error: Exception | None = None
        for attempt in range(max(1, self.options.retries)):
            existing = partial.stat().st_size if partial.exists() else 0
            headers = {"Accept": "*/*", "Referer": job.post.page_url}
            if existing:
                headers["Range"] = f"bytes={existing}-"
            try:
                async with self.session.get(job.url, headers=headers, allow_redirects=True) as response:
                    if response.status == 416 and partial.exists():
                        os.replace(partial, destination)
                        size = destination.stat().st_size
                        self._complete(job, destination, size)
                        return "downloaded", size
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
                    if mode == "wb":
                        existing = 0
                    with partial.open(mode) as handle:
                        async for chunk in response.content.iter_chunked(256 * 1024):
                            handle.write(chunk)
                os.replace(partial, destination)
                size = destination.stat().st_size
                self._complete(job, destination, size)
                return "downloaded", size
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as exc:
                last_error = exc
                if attempt + 1 < max(1, self.options.retries):
                    await asyncio.sleep(min(2**attempt, 15))
        raise RuntimeError(f"Download failed after {self.options.retries} attempts: {last_error}")

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
