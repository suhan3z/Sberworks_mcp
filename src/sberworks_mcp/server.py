from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP

from sberworks_mcp.auth import SessionFactory
from sberworks_mcp.clients.bitbucket import BitbucketClient
from sberworks_mcp.clients.confluence import ConfluenceClient
from sberworks_mcp.clients.jira import JiraClient
from sberworks_mcp.clients.zephyr import ZephyrClient
from sberworks_mcp.config import Settings, load_settings, require_writes

mcp = FastMCP("Sberworks MCP")


def _settings() -> Settings:
    return load_settings(require_all=False)


def _jira() -> JiraClient:
    settings = _settings()
    return JiraClient(
        settings.jira_base_url,
        SessionFactory(settings).create(service="jira"),
        settings.timeout_seconds,
    )


def _confluence() -> ConfluenceClient:
    settings = _settings()
    return ConfluenceClient(
        settings.confluence_base_url,
        SessionFactory(settings).create(service="confluence"),
        settings.timeout_seconds,
    )


def _bitbucket() -> BitbucketClient:
    settings = _settings()
    return BitbucketClient(
        settings.bitbucket_base_url,
        SessionFactory(settings).create(service="bitbucket"),
        settings.timeout_seconds,
    )


def _zephyr() -> ZephyrClient:
    settings = _settings()
    return ZephyrClient(
        settings.jira_base_url,
        SessionFactory(settings).create(service="jira"),
        settings.timeout_seconds,
    )


def _require_writes() -> None:
    require_writes(_settings())


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


@mcp.tool()
def jira_search(jql: str, max_results: int = 50, fields: str | None = None) -> dict[str, Any]:
    """Search Jira issues using JQL."""
    return _jira().search(jql=jql, max_results=max_results, fields=fields)


@mcp.tool()
def jira_get_issue(key: str, fields: str | None = None, expand: str | None = None) -> dict[str, Any]:
    """Read a Jira issue by key."""
    return _jira().get_issue(key=key, fields=fields, expand=expand)


@mcp.tool()
def jira_get_comments(key: str, start_at: int = 0, max_results: int = 100) -> dict[str, Any]:
    """Read comments from a Jira issue."""
    return _jira().get_comments(key=key, start_at=start_at, max_results=max_results)


@mcp.tool()
def jira_add_comment(key: str, body: str) -> dict[str, Any]:
    """Add a comment to a Jira issue. Requires SBERWORKS_MCP_ENABLE_WRITES=true."""
    _require_writes()
    return _jira().add_comment(key=key, body=body)


@mcp.tool()
def jira_create_issue(fields: dict[str, Any]) -> dict[str, Any]:
    """Create a Jira issue from a fields object. Requires SBERWORKS_MCP_ENABLE_WRITES=true."""
    _require_writes()
    return _jira().create_issue(fields=fields)


@mcp.tool()
def jira_add_attachment(key: str, file_path: str) -> dict[str, Any]:
    """Attach a local file to a Jira issue. Requires SBERWORKS_MCP_ENABLE_WRITES=true."""
    _require_writes()
    return _jira().add_attachment(key=key, file_path=file_path)


@mcp.tool()
def jira_update_issue_fields(key: str, fields: dict[str, Any]) -> dict[str, Any]:
    """Update Jira issue fields. Requires SBERWORKS_MCP_ENABLE_WRITES=true."""
    _require_writes()
    return _jira().update_issue_fields(key=key, fields=fields)


@mcp.tool()
def jira_list_transitions(key: str) -> dict[str, Any]:
    """List available Jira transitions for an issue."""
    return _jira().list_transitions(key=key)


@mcp.tool()
def jira_transition_issue(
    key: str,
    transition_id: str,
    fields: dict[str, Any] | None = None,
    update: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Move a Jira issue through a transition. Requires SBERWORKS_MCP_ENABLE_WRITES=true."""
    _require_writes()
    return _jira().transition_issue(key=key, transition_id=transition_id, fields=fields, update=update)


@mcp.tool()
def confluence_get_spaces(limit: int = 25, start: int = 0) -> dict[str, Any]:
    """List Confluence spaces."""
    return _confluence().get_spaces(limit=limit, start=start)


@mcp.tool()
def confluence_search(cql: str, limit: int = 25, expand: str | None = None, start: int = 0) -> dict[str, Any]:
    """Search Confluence content using CQL."""
    return _confluence().search(cql=cql, limit=limit, expand=expand, start=start)


@mcp.tool()
def confluence_get_page(page_id: str, expand: str = "body.storage,body.view,version,ancestors") -> dict[str, Any]:
    """Read a Confluence page by id."""
    return _confluence().get_page(page_id=page_id, expand=expand)


@mcp.tool()
def confluence_get_children(page_id: str, limit: int = 25, start: int = 0) -> dict[str, Any]:
    """Read child pages for a Confluence page."""
    return _confluence().get_children(page_id=page_id, limit=limit, start=start)


@mcp.tool()
def confluence_create_page(
    space_key: str,
    title: str,
    body: str,
    parent_id: str | None = None,
    representation: str = "storage",
) -> dict[str, Any]:
    """Create a Confluence page. Requires SBERWORKS_MCP_ENABLE_WRITES=true."""
    _require_writes()
    return _confluence().create_page(
        space_key=space_key,
        title=title,
        body=body,
        parent_id=parent_id,
        representation=representation,
    )


@mcp.tool()
def confluence_update_page(
    page_id: str,
    title: str,
    body: str,
    version: int | None = None,
    representation: str = "storage",
) -> dict[str, Any]:
    """Update a Confluence page. Requires SBERWORKS_MCP_ENABLE_WRITES=true."""
    _require_writes()
    return _confluence().update_page(
        page_id=page_id,
        title=title,
        body=body,
        version=version,
        representation=representation,
    )


@mcp.tool()
def confluence_add_comment(page_id: str, body: str, representation: str = "storage") -> dict[str, Any]:
    """Add a Confluence page comment. Requires SBERWORKS_MCP_ENABLE_WRITES=true."""
    _require_writes()
    return _confluence().add_comment(page_id=page_id, body=body, representation=representation)


@mcp.tool()
def bitbucket_get_repo(project: str, repo: str) -> dict[str, Any]:
    """Read Bitbucket repository metadata."""
    return _bitbucket().get_repo(project=project, repo=repo)


@mcp.tool()
def bitbucket_create_repo(
    project: str,
    name: str,
    scm_id: str = "git",
    forkable: bool = True,
    default_branch: str | None = None,
) -> dict[str, Any]:
    """Create a Bitbucket repository in a project. Requires SBERWORKS_MCP_ENABLE_WRITES=true."""
    _require_writes()
    return _bitbucket().create_repo(
        project=project,
        name=name,
        scm_id=scm_id,
        forkable=forkable,
        default_branch=default_branch,
    )


@mcp.tool()
def bitbucket_list_pull_requests(
    project: str,
    repo: str,
    state: str = "OPEN",
    limit: int = 25,
    start: int = 0,
) -> dict[str, Any]:
    """List Bitbucket pull requests."""
    return _bitbucket().list_pull_requests(project=project, repo=repo, state=state, limit=limit, start=start)


@mcp.tool()
def bitbucket_get_pull_request(project: str, repo: str, pull_request_id: int) -> dict[str, Any]:
    """Read a Bitbucket pull request."""
    return _bitbucket().get_pull_request(project=project, repo=repo, pull_request_id=pull_request_id)


@mcp.tool()
def bitbucket_get_pr_diff(project: str, repo: str, pull_request_id: int, context_lines: int = 10) -> Any:
    """Read a Bitbucket pull request diff."""
    return _bitbucket().get_pr_diff(
        project=project,
        repo=repo,
        pull_request_id=pull_request_id,
        context_lines=context_lines,
    )


@mcp.tool()
def bitbucket_get_file(project: str, repo: str, path: str, at: str | None = None) -> str:
    """Read a file from Bitbucket."""
    return _bitbucket().get_file(project=project, repo=repo, path=path, at=at)


@mcp.tool()
def bitbucket_put_file(
    project: str,
    repo: str,
    path: str,
    content: str,
    branch: str,
    message: str,
    source_branch: str | None = None,
    source_commit_id: str | None = None,
) -> dict[str, Any]:
    """Create or update a Bitbucket file. Requires SBERWORKS_MCP_ENABLE_WRITES=true."""
    _require_writes()
    return _bitbucket().put_file(
        project=project,
        repo=repo,
        path=path,
        content=content,
        branch=branch,
        message=message,
        source_branch=source_branch,
        source_commit_id=source_commit_id,
    )


@mcp.tool()
def bitbucket_add_pr_comment(project: str, repo: str, pull_request_id: int, text: str) -> dict[str, Any]:
    """Add a Bitbucket pull request comment. Requires SBERWORKS_MCP_ENABLE_WRITES=true."""
    _require_writes()
    return _bitbucket().add_pr_comment(project=project, repo=repo, pull_request_id=pull_request_id, text=text)


@mcp.tool()
def bitbucket_create_pull_request(
    project: str,
    repo: str,
    title: str,
    from_branch: str,
    to_branch: str,
    description: str = "",
) -> dict[str, Any]:
    """Create a Bitbucket pull request. Requires SBERWORKS_MCP_ENABLE_WRITES=true."""
    _require_writes()
    return _bitbucket().create_pull_request(
        project=project,
        repo=repo,
        title=title,
        from_branch=from_branch,
        to_branch=to_branch,
        description=description,
    )


@mcp.tool()
def zephyr_get_cycle(cycle_key: str) -> dict[str, Any]:
    """Read Zephyr test cycle metadata using /rest/atm/latest."""
    return _zephyr().get_cycle(cycle_key=cycle_key)


@mcp.tool()
def zephyr_get_cycle_case_keys(cycle_key: str) -> list[str]:
    """Read Zephyr testcase keys linked to a test cycle."""
    return _zephyr().get_cycle_case_keys(cycle_key=cycle_key)


@mcp.tool()
def zephyr_get_test_case(case_key: str) -> dict[str, Any]:
    """Read Zephyr testcase summary metadata."""
    return _zephyr().get_test_case(case_key=case_key)


@mcp.tool()
def zephyr_get_test_cases(case_keys: list[str]) -> list[dict[str, Any]]:
    """Read Zephyr testcase summaries by keys."""
    return _zephyr().get_test_cases(case_keys=case_keys)


@mcp.tool()
def zephyr_get_test_case_details(case_key: str) -> dict[str, Any]:
    """Read Zephyr testcase details including manual steps and attachments."""
    return _zephyr().get_test_case_details(case_key=case_key)


@mcp.tool()
def zephyr_export_cycle_cases(cycle_key: str) -> dict[str, Any]:
    """Export Zephyr test cycle metadata and testcase summaries."""
    return _zephyr().export_cycle_cases(cycle_key=cycle_key)


@mcp.tool()
def zephyr_export_cycle_case_details(cycle_key: str) -> dict[str, Any]:
    """Export Zephyr test cycle metadata and detailed testcases with steps."""
    return _zephyr().export_cycle_case_details(cycle_key=cycle_key)


@mcp.tool()
def zephyr_probe_cycle_endpoints(project_id: int, cycle_key: str) -> list[dict[str, Any]]:
    """Probe Zephyr cycle page and /rest/atm/latest endpoints for diagnostics."""
    return _zephyr().probe_cycle_endpoints(project_id=project_id, cycle_key=cycle_key)


@mcp.resource("jira://issue/{key}")
def jira_issue_resource(key: str) -> str:
    """Jira issue resource."""
    return _json(_jira().get_issue(key=key))


@mcp.resource("confluence://page/{page_id}")
def confluence_page_resource(page_id: str) -> str:
    """Confluence page resource."""
    return _json(_confluence().get_page(page_id=page_id))


@mcp.resource("bitbucket://projects/{project}/repos/{repo}/files/{path}?at={ref}")
def bitbucket_file_resource(project: str, repo: str, path: str, ref: str) -> str:
    """Bitbucket file resource."""
    return _bitbucket().get_file(project=project, repo=repo, path=path, at=ref)


@mcp.resource("zephyr://cycle/{cycle_key}")
def zephyr_cycle_resource(cycle_key: str) -> str:
    """Zephyr test cycle resource."""
    return _json(_zephyr().export_cycle_cases(cycle_key=cycle_key))


@mcp.resource("zephyr://testcase/{case_key}")
def zephyr_testcase_resource(case_key: str) -> str:
    """Zephyr testcase resource."""
    return _json(_zephyr().get_test_case_details(case_key=case_key))


def main() -> None:
    mcp.run()
