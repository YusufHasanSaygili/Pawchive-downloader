from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import date
from pathlib import Path

from rich.console import Console
from rich.markup import escape

from .app import RunOptions, run
from .downloader import DownloadOptions
from .urls import parse_target, read_url_file


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pawchy",
        description="Download Pawchive posts asynchronously in bulk.",
    )
    parser.add_argument("urls", nargs="*", help="Pawchive creator or post URL")
    parser.add_argument("-i", "--input", action="append", default=[], help="UTF-8 file containing a URL list")
    parser.add_argument("-o", "--output", type=Path, default=Path("downloads"), help="Download folder")
    parser.add_argument("--history", type=Path, help="SQLite history file")
    parser.add_argument("--concurrency", type=int, default=6, help="Number of concurrent downloads")
    parser.add_argument("--retries", type=int, default=4, help="Attempts per request")
    parser.add_argument("--timeout", type=float, default=120, help="Request timeout in seconds")
    parser.add_argument("--max-posts", type=int, help="Maximum posts per creator")
    parser.add_argument("--after", type=_date, metavar="YYYY-MM-DD", help="Skip posts older than this date")
    parser.add_argument("--before", type=_date, metavar="YYYY-MM-DD", help="Skip posts newer than this date")
    parser.add_argument("--session", default=os.environ.get("PAWCHIVE_SESSION"), help=argparse.SUPPRESS)
    parser.add_argument("--overwrite", action="store_true", help="Redownload existing files")
    parser.add_argument("--dry-run", action="store_true", help="Show the download plan without writing files")
    parser.add_argument("--no-cover", action="store_true", help="Do not download post cover files")
    parser.add_argument("--no-attachments", action="store_true", help="Do not download attachments")
    parser.add_argument("--metadata", action="store_true", help="Save post data as post.json")
    return parser


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Date must use YYYY-MM-DD format") from exc


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    console = Console(stderr=True)
    values = list(args.urls)
    try:
        for input_file in args.input:
            values.extend(read_url_file(input_file))
    except OSError as exc:
        parser.error(f"Could not read URL file: {exc}")
    if not values:
        parser.error("At least one URL or --input file is required")
    if args.concurrency < 1 or args.retries < 1 or args.timeout <= 0:
        parser.error("concurrency, retries, and timeout must be greater than zero")
    if args.max_posts is not None and args.max_posts < 1:
        parser.error("--max-posts must be greater than zero")
    if args.after and args.before and args.after > args.before:
        parser.error("--after cannot be later than --before")
    if args.no_cover and args.no_attachments:
        parser.error("--no-cover and --no-attachments cannot be used together")

    targets = []
    seen = set()
    for value in values:
        try:
            target = parse_target(value)
        except ValueError as exc:
            parser.error(str(exc))
        if target.key not in seen:
            targets.append(target)
            seen.add(target.key)

    output = args.output.expanduser().resolve()
    history_file = (args.history.expanduser().resolve() if args.history else output / ".pawchy-history.sqlite3")
    download = DownloadOptions(
        output=output,
        concurrency=args.concurrency,
        retries=args.retries,
        overwrite=args.overwrite,
        dry_run=args.dry_run,
        include_cover=not args.no_cover,
        include_attachments=not args.no_attachments,
        metadata=args.metadata,
    )
    options = RunOptions(
        download=download,
        history_file=history_file,
        session_cookie=args.session,
        timeout=args.timeout,
        retries=args.retries,
        max_posts=args.max_posts,
        after=args.after,
        before=args.before,
    )
    try:
        summary = asyncio.run(run(targets, options, console))
    except KeyboardInterrupt:
        console.print("[yellow]Cancelled.[/yellow]")
        raise SystemExit(130) from None
    except Exception as exc:
        console.print(f"[red]Failed:[/red] {escape(str(exc))}")
        raise SystemExit(1) from None

    console.print(
        f"[bold]Finished:[/bold] {summary.downloaded} downloaded, {summary.skipped} skipped, "
        f"{summary.failed} failed, {summary.bytes_written / (1024 * 1024):.2f} MiB written."
    )
    if summary.failed:
        raise SystemExit(2)


if __name__ == "__main__":
    main(sys.argv[1:])
