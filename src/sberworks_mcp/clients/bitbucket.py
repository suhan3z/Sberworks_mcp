from __future__ import annotations

from typing import Any
from urllib.parse import quote

import requests

from sberworks_mcp.clients.base import AtlassianClient


class BitbucketClient(AtlassianClient):
    def __init__(self, base_url: str, session: requests.Session, timeout_seconds: int) -> None:
        super().__init__(base_url, session, timeout_seconds)

    @staticmethod
    def _repo_path(project: str, repo: str) -> str:
        return f"/rest/api/1.0/projects/{quote(project, safe='')}/repos/{quote(repo, safe='')}"

    def get_repo(self, project: str, repo: str) -> dict[str, Any]:
        return self.request("GET", self._repo_path(project, repo))

    def list_pull_requests(
        self,
        project: str,
        repo: str,
        state: str = "OPEN",
        limit: int = 25,
        start: int = 0,
    ) -> dict[str, Any]:
        return self.request(
            "GET",
            f"{self._repo_path(project, repo)}/pull-requests",
            params={"state": state, "limit": limit, "start": start},
        )

    def get_pull_request(self, project: str, repo: str, pull_request_id: int) -> dict[str, Any]:
        return self.request("GET", f"{self._repo_path(project, repo)}/pull-requests/{pull_request_id}")

    def get_pr_diff(self, project: str, repo: str, pull_request_id: int, context_lines: int = 10) -> Any:
        return self.request(
            "GET",
            f"{self._repo_path(project, repo)}/pull-requests/{pull_request_id}/diff",
            params={"contextLines": context_lines},
        )

    def get_file(self, project: str, repo: str, path: str, at: str | None = None) -> str:
        params: dict[str, Any] = {}
        if at:
            params["at"] = at
        encoded_path = quote(path.strip("/"), safe="/")
        return self.request("GET", f"{self._repo_path(project, repo)}/raw/{encoded_path}", params=params)

    def add_pr_comment(self, project: str, repo: str, pull_request_id: int, text: str) -> dict[str, Any]:
        return self.request(
            "POST",
            f"{self._repo_path(project, repo)}/pull-requests/{pull_request_id}/comments",
            json={"text": text},
        )

    def create_pull_request(
        self,
        project: str,
        repo: str,
        title: str,
        from_branch: str,
        to_branch: str,
        description: str = "",
    ) -> dict[str, Any]:
        repository = {"slug": repo, "project": {"key": project}}
        payload = {
            "title": title,
            "description": description,
            "state": "OPEN",
            "open": True,
            "closed": False,
            "fromRef": {"id": f"refs/heads/{from_branch}", "repository": repository},
            "toRef": {"id": f"refs/heads/{to_branch}", "repository": repository},
        }
        return self.request("POST", f"{self._repo_path(project, repo)}/pull-requests", json=payload)
