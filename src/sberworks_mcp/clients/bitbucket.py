from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

from sberworks_mcp.clients.base import AtlassianClient


class BitbucketClient(AtlassianClient):
    def __init__(
        self,
        base_url: str,
        session: requests.Session,
        timeout_seconds: int,
        download_dir: str | None = None,
    ) -> None:
        super().__init__(base_url, session, timeout_seconds)
        self.download_dir = download_dir or str(Path(tempfile.gettempdir()) / "sberworks-mcp-downloads")

    @staticmethod
    def _repo_path(project: str, repo: str) -> str:
        return f"/rest/api/1.0/projects/{quote(project, safe='')}/repos/{quote(repo, safe='')}"

    def get_repo(self, project: str, repo: str) -> dict[str, Any]:
        return self.request("GET", self._repo_path(project, repo))

    def list_repositories(self, project: str, limit: int = 25, start: int = 0) -> dict[str, Any]:
        return self.request(
            "GET",
            f"/rest/api/1.0/projects/{quote(project, safe='')}/repos",
            params={"limit": limit, "start": start},
        )

    def create_repo(
        self,
        project: str,
        name: str,
        scm_id: str = "git",
        forkable: bool = True,
        default_branch: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": name,
            "scmId": scm_id,
            "forkable": forkable,
        }
        if default_branch:
            payload["defaultBranch"] = default_branch
        return self.request(
            "POST",
            f"/rest/api/1.0/projects/{quote(project, safe='')}/repos",
            json=payload,
        )

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

    def find_pull_requests_by_issue_key(
        self,
        project: str,
        repos: list[str],
        issue_key: str,
        states: list[str] | None = None,
        limit_per_repo_state: int = 100,
    ) -> list[dict[str, Any]]:
        states = states or ["OPEN", "MERGED", "DECLINED"]
        matches: list[dict[str, Any]] = []
        seen: set[tuple[str, int]] = set()

        for repo in repos:
            for state in states:
                start = 0
                scanned = 0
                while scanned < limit_per_repo_state:
                    page_limit = min(50, limit_per_repo_state - scanned)
                    payload = self.list_pull_requests(
                        project=project,
                        repo=repo,
                        state=state,
                        limit=page_limit,
                        start=start,
                    )
                    values = payload.get("values") or []
                    for item in values:
                        pr_id = int(item.get("id") or 0)
                        key = (repo, pr_id)
                        if pr_id and key not in seen and self._pr_mentions_issue(item, issue_key):
                            seen.add(key)
                            enriched = dict(item)
                            enriched["repositorySlug"] = repo
                            enriched["matchedIssueKey"] = issue_key
                            matches.append(enriched)
                    if payload.get("isLastPage", True) or not values:
                        break
                    scanned += len(values)
                    start = int(payload.get("nextPageStart") or start + len(values))
        return matches

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

    def download_file(
        self,
        project: str,
        repo: str,
        path: str,
        at: str | None = None,
        output_path: str | None = None,
        output_dir: str | None = None,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        encoded_path = quote(path.strip("/"), safe="/")
        url = f"{self.base_url}{self._repo_path(project, repo)}/raw/{encoded_path}"
        params: dict[str, Any] = {}
        if at:
            params["at"] = at

        target = self._download_target(path=path, output_path=output_path, output_dir=output_dir)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and not overwrite:
            raise FileExistsError(f"Output file already exists: {target}")

        response = self.session.request(
            "GET",
            url,
            params=params,
            stream=True,
            timeout=self.timeout_seconds,
        )
        try:
            if not response.ok:
                body = response.text.replace("\r", "\\r").replace("\n", "\\n")[:1000]
                raise RuntimeError(f"GET {url} failed: HTTP {response.status_code}; body={body}")

            digest = hashlib.sha256()
            byte_count = 0
            temp_name = ""
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
        except Exception:
            if "temp_name" in locals() and temp_name:
                try:
                    Path(temp_name).unlink(missing_ok=True)
                except OSError:
                    pass
            raise
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()

        return {
            "path": str(target.resolve()),
            "bytes": byte_count,
            "sha256": digest.hexdigest(),
            "project": project,
            "repo": repo,
            "source_path": path,
            "at": at,
            "content_type": response.headers.get("Content-Type"),
            "etag": response.headers.get("ETag"),
            "last_modified": response.headers.get("Last-Modified"),
        }

    def _download_target(self, path: str, output_path: str | None, output_dir: str | None) -> Path:
        if output_path:
            return Path(output_path).expanduser()

        file_name = Path(path.strip("/")).name
        if not file_name:
            raise ValueError("Bitbucket path must include a file name when output_path is not set")
        return Path(output_dir or self.download_dir).expanduser() / file_name

    def put_file(
        self,
        project: str,
        repo: str,
        path: str,
        content: str,
        branch: str,
        message: str,
        source_branch: str | None = None,
        source_commit_id: str | None = None,
    ) -> dict[str, Any]:
        data: dict[str, Any] = {
            "branch": branch,
            "message": message,
        }
        if source_branch:
            data["sourceBranch"] = source_branch
        if source_commit_id:
            data["sourceCommitId"] = source_commit_id
        encoded_path = quote(path.strip("/"), safe="/")
        return self.request(
            "PUT",
            f"{self._repo_path(project, repo)}/browse/{encoded_path}",
            data=data,
            files={"content": (None, content)},
        )

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

    @staticmethod
    def _pr_mentions_issue(pr: dict[str, Any], issue_key: str) -> bool:
        fields: list[str] = [
            str(pr.get("title") or ""),
            str(pr.get("description") or ""),
        ]
        for ref_name in ("fromRef", "toRef"):
            ref = pr.get(ref_name) or {}
            fields.append(str(ref.get("displayId") or ""))
            fields.append(str(ref.get("id") or ""))
        return issue_key.upper() in "\n".join(fields).upper()
