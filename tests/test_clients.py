from __future__ import annotations

from typing import Any

from sberworks_mcp.clients.bitbucket import BitbucketClient
from sberworks_mcp.clients.confluence import ConfluenceClient
from sberworks_mcp.clients.jira import JiraClient
from sberworks_mcp.clients.zephyr import ZephyrClient


class FakeResponse:
    def __init__(self, payload: Any, status_code: int = 200, content_type: str = "application/json") -> None:
        self.payload = payload
        self.status_code = status_code
        self.ok = status_code < 400
        self.headers = {"Content-Type": content_type}
        self.text = str(payload)
        self.content = b"x"

    def json(self) -> Any:
        return self.payload


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

    assert client.search("project = TST", max_results=10)["issues"] == []
    assert client.add_comment("TST-1", "hello")["id"] == "10001"

    assert session.calls[0][0] == "GET"
    assert session.calls[0][1] == "https://jira.example.com/rest/api/2/search"
    assert session.calls[0][2]["params"]["jql"] == "project = TST"
    assert session.calls[1][0] == "POST"
    assert session.calls[1][2]["json"] == {"body": "hello"}


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


def test_bitbucket_create_pull_request_payload() -> None:
    session = FakeSession([FakeResponse({"id": 9})])
    client = BitbucketClient("https://git.example.com/bitbucket", session, 30)

    client.create_pull_request("PRJ", "repo", "Title", "feature", "develop", "Desc")

    payload = session.calls[0][2]["json"]
    assert payload["title"] == "Title"
    assert payload["fromRef"]["id"] == "refs/heads/feature"
    assert payload["toRef"]["id"] == "refs/heads/develop"
    assert payload["fromRef"]["repository"]["project"]["key"] == "PRJ"


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
