from __future__ import annotations

from typing import Any

import requests

from sberworks_mcp.clients.base import AtlassianClient


class ConfluenceClient(AtlassianClient):
    def __init__(self, base_url: str, session: requests.Session, timeout_seconds: int) -> None:
        super().__init__(base_url, session, timeout_seconds)

    def search(self, cql: str, limit: int = 25, expand: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"cql": cql, "limit": limit}
        if expand:
            params["expand"] = expand
        return self.request("GET", "/rest/api/content/search", params=params)

    def get_page(self, page_id: str, expand: str = "body.storage,body.view,version,ancestors") -> dict[str, Any]:
        return self.request("GET", f"/rest/api/content/{page_id}", params={"expand": expand})

    def get_children(self, page_id: str, limit: int = 25, start: int = 0) -> dict[str, Any]:
        return self.request(
            "GET",
            f"/rest/api/content/{page_id}/child/page",
            params={"limit": limit, "start": start},
        )

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
