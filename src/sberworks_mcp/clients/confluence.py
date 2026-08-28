from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import requests

from sberworks_mcp.clients.base import AtlassianClient


class ConfluenceClient(AtlassianClient):
    def __init__(
        self,
        base_url: str,
        session: requests.Session,
        timeout_seconds: int,
        download_dir: str | None = None,
    ) -> None:
        super().__init__(base_url, session, timeout_seconds)
        self.download_dir = download_dir or str(Path(tempfile.gettempdir()) / "sberworks-mcp-downloads")

    def get_spaces(self, limit: int = 25, start: int = 0) -> dict[str, Any]:
        return self.request("GET", "/rest/api/space", params={"limit": limit, "start": start})

    def search(self, cql: str, limit: int = 25, expand: str | None = None, start: int = 0) -> dict[str, Any]:
        params: dict[str, Any] = {"cql": cql, "limit": limit, "start": start}
        if expand:
            params["expand"] = expand
        return self.request("GET", "/rest/api/content/search", params=params)

    def get_page(self, page_id: str, expand: str = "body.storage,body.view,version,ancestors") -> dict[str, Any]:
        return self.request("GET", f"/rest/api/content/{page_id}", params={"expand": expand})

    def get_children(self, page_id: str, limit: int = 25, start: int = 0) -> dict[str, Any]:
        return self.request(
            "GET",
            f"/rest/api/content/{quote(page_id, safe='')}/child/page",
            params={"limit": limit, "start": start},
        )

    def get_attachments(
        self,
        page_id: str,
        filename: str | None = None,
        media_type: str | None = None,
        limit: int = 25,
        start: int = 0,
        expand: str | None = "version,container,extensions",
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit, "start": start}
        if filename:
            params["filename"] = filename
        if media_type:
            params["mediaType"] = media_type
        if expand:
            params["expand"] = expand
        return self.request(
            "GET",
            f"/rest/api/content/{quote(page_id, safe='')}/child/attachment",
            params=params,
        )

    def get_attachment(
        self,
        attachment_id: str,
        expand: str = "version,container,extensions",
    ) -> dict[str, Any]:
        return self.request(
            "GET",
            f"/rest/api/content/{quote(attachment_id, safe='')}",
            params={"expand": expand},
        )

    def download_attachment(
        self,
        attachment_id: str,
        output_path: str | None = None,
        output_dir: str | None = None,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        metadata = self.get_attachment(attachment_id)
        if metadata.get("type") != "attachment":
            raise ValueError(f"Confluence content {attachment_id} is not an attachment")

        links = metadata.get("_links") or {}
        download_link = str(links.get("download") or "").strip()
        if not download_link:
            raise RuntimeError(f"Confluence attachment {attachment_id} has no download link")

        file_name = self._attachment_file_name(metadata)
        target = self._download_target(file_name, output_path, output_dir)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and not overwrite:
            raise FileExistsError(f"Output file already exists: {target}")

        url = self._download_url(download_link)
        response = self.session.request(
            "GET",
            url,
            stream=True,
            timeout=self.timeout_seconds,
        )
        digest = hashlib.sha256()
        byte_count = 0
        temp_name = ""
        try:
            if not response.ok:
                body = response.text.replace("\r", "\\r").replace("\n", "\\n")[:1000]
                raise RuntimeError(f"GET {url} failed: HTTP {response.status_code}; body={body}")

            with tempfile.NamedTemporaryFile(
                "wb",
                delete=False,
                dir=str(target.parent),
                prefix=f".{target.name}.",
                suffix=".part",
            ) as temp_file:
                temp_name = temp_file.name
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    temp_file.write(chunk)
                    digest.update(chunk)
                    byte_count += len(chunk)
            os.replace(temp_name, target)
            temp_name = ""
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()
            if temp_name:
                Path(temp_name).unlink(missing_ok=True)

        extensions = metadata.get("extensions") or {}
        container = metadata.get("container") or {}
        version = metadata.get("version") or {}
        return {
            "path": str(target.resolve()),
            "bytes": byte_count,
            "sha256": digest.hexdigest(),
            "attachment_id": str(metadata.get("id") or attachment_id),
            "page_id": str(container.get("id") or "") or None,
            "file_name": file_name,
            "media_type": extensions.get("mediaType"),
            "file_size": extensions.get("fileSize"),
            "version": version.get("number"),
            "content_type": response.headers.get("Content-Type"),
            "etag": response.headers.get("ETag"),
            "last_modified": response.headers.get("Last-Modified"),
        }

    @staticmethod
    def _attachment_file_name(metadata: dict[str, Any]) -> str:
        title = str(metadata.get("title") or "").strip()
        file_name = title.replace("\\", "/").rsplit("/", 1)[-1].rstrip(" .")
        if not file_name or file_name in {".", ".."}:
            raise RuntimeError(f"Confluence attachment {metadata.get('id')} has no usable file name")
        return file_name

    def _download_target(self, file_name: str, output_path: str | None, output_dir: str | None) -> Path:
        if output_path:
            return Path(output_path).expanduser()
        return Path(output_dir or self.download_dir).expanduser() / file_name

    def _download_url(self, download_link: str) -> str:
        if download_link.startswith(("http://", "https://")):
            return download_link

        parsed_base = urlparse(self.base_url)
        path = f"/{download_link.lstrip('/')}"
        context_path = parsed_base.path.rstrip("/")
        if context_path and (path == context_path or path.startswith(f"{context_path}/")):
            return f"{parsed_base.scheme}://{parsed_base.netloc}{path}"
        return f"{self.base_url}{path}"

    def create_page(
        self,
        space_key: str,
        title: str,
        body: str,
        parent_id: str | None = None,
        representation: str = "storage",
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "type": "page",
            "title": title,
            "space": {"key": space_key},
            "body": {representation: {"value": body, "representation": representation}},
        }
        if parent_id:
            payload["ancestors"] = [{"id": parent_id}]
        return self.request("POST", "/rest/api/content", json=payload)

    def update_page(
        self,
        page_id: str,
        title: str,
        body: str,
        version: int | None = None,
        representation: str = "storage",
    ) -> dict[str, Any]:
        if version is None:
            current = self.get_page(page_id, expand="version")
            version = int(current.get("version", {}).get("number", 0)) + 1
        payload = {
            "id": page_id,
            "type": "page",
            "title": title,
            "version": {"number": version},
            "body": {representation: {"value": body, "representation": representation}},
        }
        return self.request("PUT", f"/rest/api/content/{page_id}", json=payload)

    def add_comment(self, page_id: str, body: str, representation: str = "storage") -> dict[str, Any]:
        payload = {
            "type": "comment",
            "container": {"id": page_id, "type": "page"},
            "body": {representation: {"value": body, "representation": representation}},
        }
        return self.request("POST", f"/rest/api/content/{page_id}/child/comment", json=payload)
