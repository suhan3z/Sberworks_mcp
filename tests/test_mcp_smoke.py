from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class AtlassianStub(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/jenkins-ci/login":
            self._html("<form action='j_spring_security_check'></form>")
            return
        if self.path == "/jenkins-ci/whoAmI/api/json":
            self._json({"name": "user", "authenticated": True, "anonymous": False})
            return
        if self.path.startswith("/jenkins-ci/api/json"):
            self._json({"mode": "NORMAL", "views": []}, headers={"X-Jenkins": "2.492.3"})
            return
        if self.path.startswith("/rest/api/2/issue/TST-1"):
            self._json({"key": "TST-1", "fields": {"summary": "Smoke"}})
            return
        self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/jenkins-ci/j_spring_security_check":
            self.send_response(302)
            self.send_header("Location", "/jenkins-ci/")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_error(404)

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _json(self, payload: dict[str, Any], headers: dict[str, str] | None = None) -> None:
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _html(self, payload: str) -> None:
        raw = payload.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def test_stdio_server_lists_tools_and_calls_mocked_read() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), AtlassianStub)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        asyncio.run(_run_stdio_smoke(server.server_port))
    finally:
        server.shutdown()
        server.server_close()


async def _run_stdio_smoke(port: int) -> None:
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": str(root / "src"),
            "JIRA_BASE_URL": f"http://127.0.0.1:{port}",
            "CONFLUENCE_BASE_URL": f"http://127.0.0.1:{port}",
            "BITBUCKET_BASE_URL": f"http://127.0.0.1:{port}",
            "JENKINS_BASE_URL": f"http://127.0.0.1:{port}/jenkins-ci",
            "AUTH_USERNAME": "user",
            "AUTH_PASSWORD": "pass",
            "BITBUCKET_SERVER_BEARER_TOKEN": "",
            "REQUESTS_CA_BUNDLE": "",
            "CLIENT_P12_PATH": "",
            "CLIENT_P12_PASSWORD": "",
            "SBERWORKS_MCP_ENABLE_WRITES": "false",
        }
    )
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "sberworks_mcp"],
        cwd=str(root),
        env=env,
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = {tool.name for tool in tools.tools}
            assert "confluence_get_spaces" in names
            assert "confluence_search" in names
            assert "confluence_get_attachments" in names
            assert "confluence_download_attachment" in names
            assert "jira_get_issue" in names
            assert "jira_get_remote_links" in names
            assert "jira_get_development_details" in names
            assert "jira_create_issue" in names
            assert "bitbucket_list_repositories" in names
            assert "bitbucket_create_repo" in names
            assert "bitbucket_create_pull_request" in names
            assert "bitbucket_find_pull_requests_by_issue_key" in names
            assert "bitbucket_put_file" in names
            assert "bitbucket_download_file" in names
            assert "zephyr_get_cycle" in names
            assert "zephyr_get_test_case_details" in names
            assert "zephyr_export_cycle_case_details" in names
            assert "jenkins_get_info" in names
            assert "jenkins_get_console" in names
            assert "jenkins_download_artifact" in names
            assert "jenkins_trigger_build" in names
            assert "jenkins_stop_build" in names
            assert "jenkins_cancel_queue_item" in names

            issue = await session.call_tool("jira_get_issue", {"key": "TST-1"})
            assert issue.isError is False

            jenkins = await session.call_tool("jenkins_get_info", {})
            assert jenkins.isError is False

            denied = await session.call_tool("jira_add_comment", {"key": "TST-1", "body": "blocked"})
            assert denied.isError is True
            assert "SBERWORKS_MCP_ENABLE_WRITES=true" in denied.content[0].text

            jenkins_denied = await session.call_tool("jenkins_trigger_build", {"job_path": "test"})
            assert jenkins_denied.isError is True
            assert "SBERWORKS_MCP_ENABLE_WRITES=true" in jenkins_denied.content[0].text

            jenkins_stop_denied = await session.call_tool(
                "jenkins_stop_build",
                {"job_path": "test", "build_number": 1},
            )
            assert jenkins_stop_denied.isError is True
            assert "SBERWORKS_MCP_ENABLE_WRITES=true" in jenkins_stop_denied.content[0].text

            jenkins_cancel_denied = await session.call_tool(
                "jenkins_cancel_queue_item",
                {"queue_id": 1},
            )
            assert jenkins_cancel_denied.isError is True
            assert "SBERWORKS_MCP_ENABLE_WRITES=true" in jenkins_cancel_denied.content[0].text
