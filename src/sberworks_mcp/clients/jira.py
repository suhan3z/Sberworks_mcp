from __future__ import annotations

from typing import Any

import requests

from sberworks_mcp.clients.base import AtlassianClient


class JiraClient(AtlassianClient):
    def __init__(self, base_url: str, session: requests.Session, timeout_seconds: int) -> None:
        super().__init__(base_url, session, timeout_seconds)

    def search(self, jql: str, max_results: int = 50, fields: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"jql": jql, "maxResults": max_results}
        if fields:
            params["fields"] = fields
        return self.request("GET", "/rest/api/2/search", params=params)

    def get_issue(self, key: str, fields: str | None = None, expand: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if fields:
            params["fields"] = fields
        if expand:
            params["expand"] = expand
        return self.request("GET", f"/rest/api/2/issue/{key}", params=params)

    def get_comments(self, key: str, start_at: int = 0, max_results: int = 100) -> dict[str, Any]:
        return self.request(
            "GET",
            f"/rest/api/2/issue/{key}/comment",
            params={"startAt": start_at, "maxResults": max_results},
        )

    def add_comment(self, key: str, body: str) -> dict[str, Any]:
        return self.request("POST", f"/rest/api/2/issue/{key}/comment", json={"body": body})

    def create_issue(self, fields: dict[str, Any]) -> dict[str, Any]:
        return self.request("POST", "/rest/api/2/issue", json={"fields": fields})

    def update_issue_fields(self, key: str, fields: dict[str, Any]) -> dict[str, Any]:
        return self.request("PUT", f"/rest/api/2/issue/{key}", json={"fields": fields})

    def list_transitions(self, key: str) -> dict[str, Any]:
        return self.request("GET", f"/rest/api/2/issue/{key}/transitions")

    def transition_issue(
        self,
        key: str,
        transition_id: str,
        fields: dict[str, Any] | None = None,
        update: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"transition": {"id": transition_id}}
        if fields:
            payload["fields"] = fields
        if update:
            payload["update"] = update
        return self.request("POST", f"/rest/api/2/issue/{key}/transitions", json=payload)
