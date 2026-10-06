from __future__ import annotations

from typing import Any

import requests

from sberworks_mcp.clients.base import AtlassianClient


class JiraClient(AtlassianClient):
    def __init__(self, base_url: str, session: requests.Session, timeout_seconds: int) -> None:
        super().__init__(base_url, session, timeout_seconds)

    def search(
        self,
        jql: str,
        max_results: int = 50,
        fields: str | None = None,
        start_at: int = 0,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"jql": jql, "maxResults": max_results, "startAt": start_at}
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

    def get_remote_links(self, key: str) -> list[dict[str, Any]]:
        payload = self.request("GET", f"/rest/api/2/issue/{key}/remotelink")
        return payload if isinstance(payload, list) else []

    def get_development_details(
        self,
        issue_id_or_key: str,
        application_type: str = "stash",
        data_type: str = "pullrequest",
    ) -> dict[str, Any]:
        issue_id = issue_id_or_key
        if not issue_id_or_key.isdigit():
            issue = self.get_issue(issue_id_or_key, fields="summary")
            issue_id = str(issue.get("id") or issue_id_or_key)
        return self.request(
            "GET",
            "/rest/dev-status/1.0/issue/detail",
            params={"issueId": issue_id, "applicationType": application_type, "dataType": data_type},
        )

    def add_comment(self, key: str, body: str) -> dict[str, Any]:
        return self.request("POST", f"/rest/api/2/issue/{key}/comment", json={"body": body})

    def create_issue(self, fields: dict[str, Any]) -> dict[str, Any]:
        return self.request("POST", "/rest/api/2/issue", json={"fields": fields})

    def add_attachment(self, key: str, file_path: str) -> dict[str, Any]:
        headers = {"X-Atlassian-Token": "no-check"}
        with open(file_path, "rb") as file:
            files = {"file": file}
            return self.request(
                "POST",
                f"/rest/api/2/issue/{key}/attachments",
                headers=headers,
                files=files,
            )

    def update_issue_fields(
        self,
        key: str,
        fields: dict[str, Any] | None = None,
        update: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not fields and not update:
            raise ValueError("Either fields or update must be provided")
        payload: dict[str, Any] = {}
        if fields:
            payload["fields"] = fields
        if update:
            payload["update"] = update
        return self.request("PUT", f"/rest/api/2/issue/{key}", json=payload)

    def list_issue_link_types(self) -> dict[str, Any]:
        return self.request("GET", "/rest/api/2/issueLinkType")

    def create_issue_link(
        self,
        link_type: str,
        inward_key: str,
        outward_key: str,
        comment: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "type": {"name": link_type},
            "inwardIssue": {"key": inward_key},
            "outwardIssue": {"key": outward_key},
        }
        if comment:
            payload["comment"] = {"body": comment}
        return self.request("POST", "/rest/api/2/issueLink", json=payload)

    def delete_issue_link(self, link_id: str) -> dict[str, Any]:
        return self.request("DELETE", f"/rest/api/2/issueLink/{link_id}")

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
