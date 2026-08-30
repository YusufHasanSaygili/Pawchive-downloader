from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def parse_timestamp(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


@dataclass(frozen=True, slots=True)
class Target:
    service: str
    creator_id: str
    post_id: str | None = None

    @property
    def key(self) -> tuple[str, str, str | None]:
        return self.service, self.creator_id, self.post_id


@dataclass(frozen=True, slots=True)
class Creator:
    id: str
    service: str
    name: str

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "Creator":
        return cls(
            id=str(data["id"]),
            service=str(data["service"]),
            name=str(data.get("name") or data["id"]),
        )


@dataclass(frozen=True, slots=True)
class RemoteFile:
    name: str
    path: str
    kind: str


@dataclass(slots=True)
class Post:
    id: str
    creator_id: str
    service: str
    title: str
    published: datetime | None
    file: dict[str, Any] | None
    attachments: list[dict[str, Any]]
    raw: dict[str, Any] = field(repr=False)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "Post":
        return cls(
            id=str(data["id"]),
            creator_id=str(data.get("user") or data.get("creator_id") or ""),
            service=str(data["service"]),
            title=str(data.get("title") or "Untitled"),
            published=parse_timestamp(data.get("published")),
            file=data.get("file") if isinstance(data.get("file"), dict) else None,
            attachments=[item for item in data.get("attachments", []) if isinstance(item, dict)],
            raw=data,
        )

    @property
    def key(self) -> tuple[str, str, str]:
        return self.service, self.creator_id, self.id

    @property
    def page_url(self) -> str:
        return f"https://pawchive.pw/{self.service}/user/{self.creator_id}/post/{self.id}"

    def remote_files(self, include_cover: bool = True, include_attachments: bool = True) -> list[RemoteFile]:
        files: list[RemoteFile] = []
        seen_paths: set[str] = set()
        if include_cover and self.file:
            item = self._remote_file(self.file, "cover")
            if item:
                files.append(item)
                seen_paths.add(item.path)
        if include_attachments:
            for attachment in self.attachments:
                item = self._remote_file(attachment, "attachment")
                if item and item.path not in seen_paths:
                    files.append(item)
                    seen_paths.add(item.path)
        return files

    @staticmethod
    def _remote_file(data: dict[str, Any], kind: str) -> RemoteFile | None:
        path = data.get("path")
        if not isinstance(path, str) or not path.startswith("/") or ".." in path.split("/"):
            return None
        name = data.get("name")
        if not isinstance(name, str) or not name.strip():
            name = path.rsplit("/", 1)[-1]
        return RemoteFile(name=name, path=path, kind=kind)
