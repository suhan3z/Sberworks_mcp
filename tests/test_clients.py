from __future__ import annotations

import hashlib
from typing import Any

from sberworks_mcp.clients.bitbucket import BitbucketClient
from sberworks_mcp.clients.confluence import ConfluenceClient
from sberworks_mcp.clients.jira import JiraClient
from sberworks_mcp.clients.zephyr import ZephyrClient


class FakeResponse:
    def __init__(
        self,
        payload: Any,
        status_code: int = 200,
        content_type: str = "application/json",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.payload = payload
        self.status_code = status_code
        self.ok = status_code < 400
        self.headers = {"Content-Type": content_type, **(headers or {})}
        self.content = payload if isinstance(payload, bytes) else b"x"
        self.text = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else str(payload)
        self.closed = False

    def json(self) -> Any:
        return self.payload

    def iter_content(self, chunk_size: int):
        content = self.content
        for index in range(0, len(content), chunk_size):
            yield content[index : index + chunk_size]

    def close(self) -> None:
        self.closed = True


class FakeSession:
    def __init__(self, responses: list[FakeResponse] | None = None) -> None:
        self.responses = responses or [FakeResponse({"ok": True})]
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)


def test_jira_search_and_comment_payloads() -> None:
    session = FakeSession([FakeResponse({"issues": []}), FakeResponse({"id": "10001"})])
    client = JiraClient("https://jira.example.com", session, 30)

    assert client.search("project = TST", max_results=10, start_at=20)["issues"] == []
    assert client.add_comment("TST-1", "hello")["id"] == "10001"

    assert session.calls[0][0] == "GET"
    assert session.calls[0][1] == "https://jira.example.com/rest/api/2/search"
    assert session.calls[0][2]["params"]["jql"] == "project = TST"
    assert session.calls[0][2]["params"]["startAt"] == 20
    assert session.calls[1][0] == "POST"
    assert session.calls[1][2]["json"] == {"body": "hello"}


def test_jira_remote_links_path() -> None:
    session = FakeSession([FakeResponse([{"object": {"url": "https://git/pr/1"}}])])
    client = JiraClient("https://jira.example.com", session, 30)

    assert client.get_remote_links("TST-1") == [{"object": {"url": "https://git/pr/1"}}]
    assert session.calls[0][0] == "GET"
    assert session.calls[0][1] == "https://jira.example.com/rest/api/2/issue/TST-1/remotelink"


def test_jira_development_details_resolves_issue_key_to_id() -> None:
    session = FakeSession(
        [
            FakeResponse({"id": "10001", "key": "TST-1"}),
            FakeResponse({"detail": [{"pullRequests": [{"id": 7}]}]}),
        ]
    )
    client = JiraClient("https://jira.example.com", session, 30)

    result = client.get_development_details("TST-1")

    assert result["detail"][0]["pullRequests"][0]["id"] == 7
    assert session.calls[0][1] == "https://jira.example.com/rest/api/2/issue/TST-1"
    assert session.calls[0][2]["params"] == {"fields": "summary"}
    assert session.calls[1][1] == "https://jira.example.com/rest/dev-status/1.0/issue/detail"
    assert session.calls[1][2]["params"] == {
        "issueId": "10001",
        "applicationType": "stash",
        "dataType": "pullrequest",
    }


def test_jira_development_details_accepts_numeric_issue_id() -> None:
    session = FakeSession([FakeResponse({"detail": []})])
    client = JiraClient("https://jira.example.com", session, 30)

    assert client.get_development_details("10001") == {"detail": []}
    assert len(session.calls) == 1
    assert session.calls[0][2]["params"]["issueId"] == "10001"


def test_jira_transition_payload() -> None:
    session = FakeSession([FakeResponse({"ok": True})])
    client = JiraClient("https://jira.example.com", session, 30)

    client.transition_issue("TST-1", "31", fields={"resolution": {"name": "Done"}})

    assert session.calls[0][1].endswith("/rest/api/2/issue/TST-1/transitions")
    assert session.calls[0][2]["json"] == {
        "transition": {"id": "31"},
        "fields": {"resolution": {"name": "Done"}},
    }


def test_jira_create_issue_payload() -> None:
    session = FakeSession([FakeResponse({"id": "10002", "key": "TST-2"})])
    client = JiraClient("https://jira.example.com", session, 30)

    result = client.create_issue(
        {
            "project": {"key": "TST"},
            "summary": "New issue",
            "issuetype": {"name": "Task"},
            "description": "Details",
        }
    )

    assert result["key"] == "TST-2"
    assert session.calls[0][0] == "POST"
    assert session.calls[0][1] == "https://jira.example.com/rest/api/2/issue"
    assert session.calls[0][2]["json"] == {
        "fields": {
            "project": {"key": "TST"},
            "summary": "New issue",
            "issuetype": {"name": "Task"},
            "description": "Details",
        }
    }


def test_confluence_update_page_fetches_next_version() -> None:
    session = FakeSession(
        [
            FakeResponse({"version": {"number": 7}}),
            FakeResponse({"id": "123", "version": {"number": 8}}),
        ]
    )
    client = ConfluenceClient("https://wiki.example.com", session, 30)

    result = client.update_page("123", "Title", "<p>Body</p>")

    assert result["version"]["number"] == 8
    assert session.calls[0][0] == "GET"
    assert session.calls[0][2]["params"]["expand"] == "version"
    assert session.calls[1][0] == "PUT"
    assert session.calls[1][2]["json"]["version"]["number"] == 8


def test_confluence_create_page_payload() -> None:
    session = FakeSession([FakeResponse({"id": "123"})])
    client = ConfluenceClient("https://wiki.example.com", session, 30)

    client.create_page("SPACE", "Title", "<p>Body</p>", parent_id="42")

    payload = session.calls[0][2]["json"]
    assert payload["space"] == {"key": "SPACE"}
    assert payload["ancestors"] == [{"id": "42"}]
    assert payload["body"]["storage"]["value"] == "<p>Body</p>"


def test_confluence_spaces_and_search_are_paginated() -> None:
    session = FakeSession([FakeResponse({"results": []}), FakeResponse({"results": []})])
    client = ConfluenceClient("https://wiki.example.com", session, 30)

    client.get_spaces(limit=10, start=20)
    client.search("type=page", limit=50, start=100, expand="space")

    assert session.calls[0][1] == "https://wiki.example.com/rest/api/space"
    assert session.calls[0][2]["params"] == {"limit": 10, "start": 20}
    assert session.calls[1][1] == "https://wiki.example.com/rest/api/content/search"
    assert session.calls[1][2]["params"] == {
        "cql": "type=page",
        "limit": 50,
        "start": 100,
        "expand": "space",
    }


def test_confluence_get_attachments_supports_filters() -> None:
    session = FakeSession([FakeResponse({"results": []})])
    client = ConfluenceClient("https://wiki.example.com/wiki", session, 30)

    result = client.get_attachments(
        "123",
        filename="Стандарт Надёжности_V17.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        limit=10,
        start=20,
    )

    assert result == {"results": []}
    assert session.calls[0][1] == "https://wiki.example.com/wiki/rest/api/content/123/child/attachment"
    assert session.calls[0][2]["params"] == {
        "limit": 10,
        "start": 20,
        "filename": "Стандарт Надёжности_V17.xlsx",
        "mediaType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "expand": "version,container,extensions",
    }


def test_confluence_download_attachment_streams_atomically(tmp_path) -> None:
    payload = b"PK\x03\x04workbook"
    metadata = {
        "id": "987",
        "type": "attachment",
        "title": "Стандарт Надёжности_V17.xlsx",
        "container": {"id": "123", "type": "page"},
        "version": {"number": 17},
        "extensions": {
            "mediaType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "fileSize": len(payload),
        },
        "_links": {"download": "/download/attachments/123/reliability.xlsx?version=17"},
    }
    response = FakeResponse(
        payload,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"ETag": '"abc"', "Last-Modified": "Thu, 20 Aug 2026 10:00:00 GMT"},
    )
    session = FakeSession([FakeResponse(metadata), response])
    client = ConfluenceClient("https://wiki.example.com/wiki", session, 30, download_dir=str(tmp_path))

    result = client.download_attachment("987")
    target = tmp_path / "Стандарт Надёжности_V17.xlsx"

    assert target.read_bytes() == payload
    assert result == {
        "path": str(target.resolve()),
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "attachment_id": "987",
        "page_id": "123",
        "file_name": "Стандарт Надёжности_V17.xlsx",
        "media_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "file_size": len(payload),
        "version": 17,
        "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "etag": '"abc"',
        "last_modified": "Thu, 20 Aug 2026 10:00:00 GMT",
    }
    assert response.closed is True
    assert session.calls[0][1] == "https://wiki.example.com/wiki/rest/api/content/987"
    assert session.calls[0][2]["params"] == {"expand": "version,container,extensions"}
    assert session.calls[1][1] == (
        "https://wiki.example.com/wiki/download/attachments/123/reliability.xlsx?version=17"
    )
    assert session.calls[1][2]["stream"] is True
    assert session.calls[1][2]["timeout"] == 30


def test_confluence_download_attachment_refuses_overwrite(tmp_path) -> None:
    target = tmp_path / "questionnaire.xlsx"
    target.write_bytes(b"existing")
    metadata = {
        "id": "654",
        "type": "attachment",
        "title": "questionnaire.xlsx",
        "_links": {"download": "/wiki/download/attachments/321/questionnaire.xlsx"},
    }
    session = FakeSession([FakeResponse(metadata)])
    client = ConfluenceClient("https://wiki.example.com/wiki", session, 30, download_dir=str(tmp_path))

    try:
        client.download_attachment("654")
    except FileExistsError as exc:
        assert str(target) in str(exc)
    else:
        raise AssertionError("download_attachment should refuse to overwrite existing files by default")

    assert len(session.calls) == 1


def test_bitbucket_file_and_pr_comment_paths() -> None:
    session = FakeSession(
        [
            FakeResponse("file text", content_type="text/plain"),
            FakeResponse({"id": 1}),
        ]
    )
    client = BitbucketClient("https://git.example.com/bitbucket", session, 30)

    assert client.get_file("PRJ", "repo", "src/main.py", at="develop") == "file text"
    assert client.add_pr_comment("PRJ", "repo", 7, "review") == {"id": 1}

    assert session.calls[0][1].endswith("/rest/api/1.0/projects/PRJ/repos/repo/raw/src/main.py")
    assert session.calls[0][2]["params"] == {"at": "develop"}
    assert session.calls[1][1].endswith("/rest/api/1.0/projects/PRJ/repos/repo/pull-requests/7/comments")
    assert session.calls[1][2]["json"] == {"text": "review"}


def test_bitbucket_download_file_streams_to_output_path(tmp_path) -> None:
    payload = b"abcdef"
    response = FakeResponse(
        payload,
        content_type="application/octet-stream",
        headers={"ETag": '"abc"', "Last-Modified": "Fri, 19 Jun 2026 10:00:00 GMT"},
    )
    session = FakeSession([response])
    client = BitbucketClient("https://git.example.com/bitbucket", session, 30)
    target = tmp_path / "download.snapshot"

    result = client.download_file(
        project="PRJ",
        repo="repo",
        path="snapshots/prod/download.snapshot",
        at="develop",
        output_path=str(target),
    )

    assert target.read_bytes() == payload
    assert result == {
        "path": str(target.resolve()),
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "project": "PRJ",
        "repo": "repo",
        "source_path": "snapshots/prod/download.snapshot",
        "at": "develop",
        "content_type": "application/octet-stream",
        "etag": '"abc"',
        "last_modified": "Fri, 19 Jun 2026 10:00:00 GMT",
    }
    assert response.closed is True
    assert session.calls[0][0] == "GET"
    assert session.calls[0][1].endswith("/rest/api/1.0/projects/PRJ/repos/repo/raw/snapshots/prod/download.snapshot")
    assert session.calls[0][2]["params"] == {"at": "develop"}
    assert session.calls[0][2]["stream"] is True
    assert session.calls[0][2]["timeout"] == 30


def test_bitbucket_download_file_uses_output_dir_and_refuses_overwrite(tmp_path) -> None:
    target = tmp_path / "download.snapshot"
    target.write_bytes(b"existing")
    client = BitbucketClient("https://git.example.com/bitbucket", FakeSession([]), 30)

    try:
        client.download_file("PRJ", "repo", "snapshots/prod/download.snapshot", output_dir=str(tmp_path))
    except FileExistsError as exc:
        assert str(target) in str(exc)
    else:
        raise AssertionError("download_file should refuse to overwrite existing files by default")

    session = FakeSession([FakeResponse(b"new", content_type="application/octet-stream")])
    client = BitbucketClient("https://git.example.com/bitbucket", session, 30)
    result = client.download_file(
        "PRJ",
        "repo",
        "snapshots/prod/download.snapshot",
        output_dir=str(tmp_path),
        overwrite=True,
    )

    assert target.read_bytes() == b"new"
    assert result["path"] == str(target.resolve())
    assert result["bytes"] == 3


def test_bitbucket_create_repo_payload() -> None:
    session = FakeSession([FakeResponse({"slug": "repo"})])
    client = BitbucketClient("https://git.example.com/bitbucket", session, 30)

    result = client.create_repo("PRJ", "repo", forkable=False, default_branch="main")

    assert result["slug"] == "repo"
    assert session.calls[0][0] == "POST"
    assert session.calls[0][1] == "https://git.example.com/bitbucket/rest/api/1.0/projects/PRJ/repos"
    assert session.calls[0][2]["json"] == {
        "name": "repo",
        "scmId": "git",
        "forkable": False,
        "defaultBranch": "main",
    }


def test_bitbucket_list_repositories_path_and_pagination() -> None:
    session = FakeSession([FakeResponse({"values": [{"slug": "repo"}]})])
    client = BitbucketClient("https://git.example.com/bitbucket", session, 30)

    result = client.list_repositories("PRJ", limit=50, start=100)

    assert result["values"][0]["slug"] == "repo"
    assert session.calls[0][0] == "GET"
    assert session.calls[0][1] == "https://git.example.com/bitbucket/rest/api/1.0/projects/PRJ/repos"
    assert session.calls[0][2]["params"] == {"limit": 50, "start": 100}


def test_bitbucket_put_file_payload() -> None:
    session = FakeSession([FakeResponse({"id": "abc"})])
    client = BitbucketClient("https://git.example.com/bitbucket", session, 30)

    result = client.put_file("PRJ", "repo", "src/main.py", "print('ok')\n", "main", "Add file")

    assert result["id"] == "abc"
    assert session.calls[0][0] == "PUT"
    assert session.calls[0][1].endswith("/rest/api/1.0/projects/PRJ/repos/repo/browse/src/main.py")
    assert session.calls[0][2]["data"] == {"branch": "main", "message": "Add file"}
    assert session.calls[0][2]["files"] == {"content": (None, "print('ok')\n")}


def test_bitbucket_create_pull_request_payload() -> None:
    session = FakeSession([FakeResponse({"id": 9})])
    client = BitbucketClient("https://git.example.com/bitbucket", session, 30)

    client.create_pull_request("PRJ", "repo", "Title", "feature", "develop", "Desc")

    payload = session.calls[0][2]["json"]
    assert payload["title"] == "Title"
    assert payload["fromRef"]["id"] == "refs/heads/feature"
    assert payload["toRef"]["id"] == "refs/heads/develop"
    assert payload["fromRef"]["repository"]["project"]["key"] == "PRJ"


def test_bitbucket_find_pull_requests_by_issue_key_scans_refs_and_states() -> None:
    session = FakeSession(
        [
            FakeResponse(
                {
                    "values": [
                        {
                            "id": 1,
                            "title": "Feature TST-42",
                            "description": "",
                            "fromRef": {"displayId": "feature/no-key", "id": "refs/heads/feature/no-key"},
                        },
                        {
                            "id": 2,
                            "title": "Other",
                            "description": "",
                            "fromRef": {"displayId": "feature/other", "id": "refs/heads/feature/other"},
                        },
                    ],
                    "isLastPage": True,
                }
            ),
            FakeResponse(
                {
                    "values": [
                        {
                            "id": 3,
                            "title": "Other",
                            "description": "",
                            "fromRef": {"displayId": "feature/TST-42", "id": "refs/heads/feature/TST-42"},
                        },
                    ],
                    "isLastPage": True,
                }
            ),
        ]
    )
    client = BitbucketClient("https://git.example.com/bitbucket", session, 30)

    matches = client.find_pull_requests_by_issue_key(
        project="PRJ",
        repos=["repo"],
        issue_key="TST-42",
        states=["OPEN", "MERGED"],
    )

    assert [item["id"] for item in matches] == [1, 3]
    assert matches[0]["repositorySlug"] == "repo"
    assert session.calls[0][2]["params"]["state"] == "OPEN"
    assert session.calls[1][2]["params"]["state"] == "MERGED"


def test_zephyr_exports_cycle_case_details_from_atm_latest() -> None:
    session = FakeSession(
        [
            FakeResponse(
                {
                    "id": 78,
                    "key": "MTRAVEL-C78",
                    "projectId": 10001,
                    "projectKey": "MTRAVEL",
                    "name": "Regression",
                    "testCaseCount": 2,
                    "status": {"name": "Active"},
                    "folder": {"fullName": "web/regression"},
                    "items": [
                        {"testCaseKey": "MTRAVEL-T1"},
                        {"testCaseKey": "MTRAVEL-T2"},
                        {"testCaseKey": "MTRAVEL-T1"},
                    ],
                }
            ),
            FakeResponse({"id": 1, "key": "MTRAVEL-T1", "projectId": 10001, "name": "Login", "priorityId": 10}),
            FakeResponse({"id": 2, "key": "MTRAVEL-T2", "projectId": 10001, "name": "Search", "statusId": 20}),
            FakeResponse(
                {
                    "id": 1,
                    "key": "MTRAVEL-T1",
                    "projectId": 10001,
                    "projectKey": "MTRAVEL",
                    "name": "Login",
                    "objective": "Check login",
                    "precondition": "User exists",
                    "folder": {"fullName": "web/auth"},
                    "status": {"name": "Ready"},
                    "priority": {"name": "High"},
                    "testScript": {
                        "stepByStepScript": {
                            "steps": [
                                {
                                    "index": 2,
                                    "id": 12,
                                    "text": "Submit form",
                                    "expectedResult": "User is logged in",
                                    "testData": '<a href="../rest/tests/1.0/attachment/file/42">file</a>',
                                },
                                {
                                    "index": 1,
                                    "id": 11,
                                    "description": "Open login page",
                                    "expectedResult": "Form is visible",
                                },
                            ]
                        }
                    },
                }
            ),
            FakeResponse(
                {
                    "id": 2,
                    "issueKey": "MTRAVEL-T2",
                    "projectId": 10001,
                    "projectKey": "MTRAVEL",
                    "name": "Search",
                    "testScript": {"steps": [{"index": 1, "text": "Search", "expectedResult": "Results"}]},
                }
            ),
        ]
    )
    client = ZephyrClient("https://jira.example.com", session, 30)

    export = client.export_cycle_case_details("MTRAVEL-C78")

    assert export["cycle"]["key"] == "MTRAVEL-C78"
    assert export["cycle"]["status_name"] == "Active"
    assert export["case_keys"] == ["MTRAVEL-T1", "MTRAVEL-T2"]
    assert export["cases"][0]["priority_id"] == 10
    assert export["detailed_cases"][0]["precondition"] == "User exists"
    assert export["detailed_cases"][0]["steps"][0]["action_text"] == "Open login page"
    assert export["detailed_cases"][0]["steps"][1]["attachment_refs"] == ["../rest/tests/1.0/attachment/file/42"]
    assert session.calls[0][1] == "https://jira.example.com/rest/atm/latest/testrun/MTRAVEL-C78"
    assert session.calls[1][1] == "https://jira.example.com/rest/atm/latest/testcase/MTRAVEL-T1"
    assert session.calls[2][1] == "https://jira.example.com/rest/atm/latest/testcase/MTRAVEL-T2"


def test_zephyr_probe_reports_endpoint_status() -> None:
    session = FakeSession(
        [
            FakeResponse({"items": [{"testCaseKey": "MTRAVEL-T1"}]}),
            FakeResponse("<html>cycle</html>", content_type="text/html"),
            FakeResponse({"key": "MTRAVEL-C78"}),
            FakeResponse({"key": "MTRAVEL-T1"}),
        ]
    )
    client = ZephyrClient("https://jira.example.com", session, 30)

    results = client.probe_cycle_endpoints(project_id=10001, cycle_key="MTRAVEL-C78")

    assert [item["name"] for item in results] == ["cycle_page", "testrun_latest", "testcase_latest"]
    assert all(item["ok"] for item in results)
    assert results[0]["project_id"] == 10001
