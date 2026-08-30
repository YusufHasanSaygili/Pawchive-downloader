from __future__ import annotations

import re
from urllib.parse import unquote, urlsplit

from .models import Target


SUPPORTED_HOSTS = {"pawchive.pw", "www.pawchive.pw", "pawchive.st", "www.pawchive.st"}
TARGET_PATH = re.compile(
    r"^/(?P<service>[a-zA-Z0-9_-]+)/user/(?P<creator>[^/]+)(?:/post/(?P<post>[^/]+))?/?$"
)


def parse_target(value: str) -> Target:
    value = value.strip()
    if not value:
        raise ValueError("Empty URL")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in SUPPORTED_HOSTS:
        raise ValueError(f"Unsupported Pawchive URL: {value}")
    match = TARGET_PATH.fullmatch(parsed.path)
    if not match:
        raise ValueError(f"Unsupported Pawchive URL format: {value}")
    return Target(
        service=unquote(match.group("service")).lower(),
        creator_id=unquote(match.group("creator")),
        post_id=unquote(match.group("post")) if match.group("post") else None,
    )


def read_url_file(path: str) -> list[str]:
    with open(path, encoding="utf-8-sig") as handle:
        return [line.strip() for line in handle if line.strip() and not line.lstrip().startswith("#")]
