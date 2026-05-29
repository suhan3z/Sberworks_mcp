from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest
from dotenv import dotenv_values

from sberworks_mcp import cli


def test_init_creates_env_without_printing_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    answers = iter(
        [
            "https://jira.example.com",
            "https://wiki.example.com",
            "https://git.example.com/bitbucket",
            "user",
            "",
            "",
            "45",
        ]
    )
    secrets = iter(["secret-password", "secret-token", "p12-secret"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))
    monkeypatch.setattr("sberworks_mcp.cli.getpass.getpass", lambda prompt: next(secrets))

    env_file = tmp_path / ".env"
    assert cli.main(["init", "--env-file", str(env_file)]) == 0

    written = env_file.read_text(encoding="utf-8")
    output = capsys.readouterr().out
    assert "JIRA_BASE_URL=https://jira.example.com" in written
    assert "AUTH_PASSWORD=secret-password" in written
    assert "BITBUCKET_SERVER_BEARER_TOKEN=secret-token" in written
    assert "SBERWORKS_MCP_ENABLE_WRITES=false" in written
    assert "SBERWORKS_MCP_TIMEOUT_SECONDS=45" in written
    assert "secret-password" not in output
    assert "secret-token" not in output
    assert "p12-secret" not in output


def test_init_env_escapes_values_for_dotenv(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    cli.write_env_file(
        env_file,
        {
            "JIRA_BASE_URL": "https://jira.example.com",
            "CONFLUENCE_BASE_URL": "https://wiki.example.com",
            "BITBUCKET_BASE_URL": "https://git.example.com/bitbucket",
            "AUTH_USERNAME": "user name",
            "AUTH_PASSWORD": 'pass # "quoted"',
            "BITBUCKET_SERVER_BEARER_TOKEN": "",
            "REQUESTS_CA_BUNDLE": r"C:\certs\ca bundle.pem",
            "CLIENT_P12_PATH": "",
            "CLIENT_P12_PASSWORD": "",
            "SBERWORKS_MCP_ENABLE_WRITES": "false",
            "SBERWORKS_MCP_TIMEOUT_SECONDS": "30",
        },
    )

    values = dotenv_values(env_file)

    assert values["AUTH_USERNAME"] == "user name"
    assert values["AUTH_PASSWORD"] == 'pass # "quoted"'
    assert values["REQUESTS_CA_BUNDLE"] == r"C:\certs\ca bundle.pem"


def test_init_refuses_to_overwrite_existing_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("EXISTING=true\n", encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda prompt: pytest.fail("init should not prompt"))

    assert cli.main(["init", "--env-file", str(env_file)]) == 1
    assert env_file.read_text(encoding="utf-8") == "EXISTING=true\n"


def test_doctor_returns_success_for_valid_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "JIRA_BASE_URL=https://jira.example.com",
                "CONFLUENCE_BASE_URL=https://wiki.example.com",
                "BITBUCKET_BASE_URL=https://git.example.com/bitbucket",
                "AUTH_USERNAME=user",
                "AUTH_PASSWORD=pass",
                "BITBUCKET_SERVER_BEARER_TOKEN=",
                "REQUESTS_CA_BUNDLE=",
                "CLIENT_P12_PATH=",
                "CLIENT_P12_PASSWORD=",
                "SBERWORKS_MCP_ENABLE_WRITES=false",
                "SBERWORKS_MCP_TIMEOUT_SECONDS=30",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("sberworks_mcp.cli._check_distribution", lambda report: report.info.append("Package checks skipped"))

    report = cli.run_doctor(env_file)

    assert report.exit_code == 0
    assert not report.errors
    assert "Write tools are disabled by default." in report.info


def test_doctor_returns_errors_for_invalid_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "JIRA_BASE_URL=not-a-url",
                "CONFLUENCE_BASE_URL=",
                "BITBUCKET_BASE_URL=https://git.example.com/bitbucket",
                "AUTH_USERNAME=",
                "AUTH_PASSWORD=",
                "SBERWORKS_MCP_TIMEOUT_SECONDS=0",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("sberworks_mcp.cli._check_distribution", lambda report: report.info.append("Package checks skipped"))

    report = cli.run_doctor(env_file)

    assert report.exit_code == 1
    assert any("Missing required env var: CONFLUENCE_BASE_URL" in error for error in report.errors)
    assert any("JIRA_BASE_URL must be an absolute http(s) URL" in error for error in report.errors)
    assert any("SBERWORKS_MCP_TIMEOUT_SECONDS must be greater than 0" in error for error in report.errors)


def test_config_snippet_generates_claude_json(tmp_path: Path) -> None:
    snippet = cli.build_config_snippet(client="claude", env_file=tmp_path / ".env")

    payload = json.loads(snippet)
    server = payload["mcpServers"]["sberworks"]
    assert Path(server["command"]).is_absolute()
    assert server["args"] == ["-m", "sberworks_mcp"]
    assert Path(server["env"]["SBERWORKS_MCP_ENV_FILE"]).is_absolute()


def test_config_snippet_generates_vscode_json(tmp_path: Path) -> None:
    snippet = cli.build_config_snippet(client="vscode", env_file=tmp_path / ".env")

    payload = json.loads(snippet)
    server = payload["servers"]["sberworks"]
    assert server["type"] == "stdio"
    assert Path(server["command"]).is_absolute()
    assert server["args"] == ["-m", "sberworks_mcp"]


def test_config_snippet_generates_codex_toml(tmp_path: Path) -> None:
    snippet = cli.build_config_snippet(client="codex", env_file=tmp_path / ".env")

    payload = tomllib.loads(snippet)
    server = payload["mcp_servers"]["sberworks"]
    assert Path(server["command"]).is_absolute()
    assert server["args"] == ["-m", "sberworks_mcp"]
    assert Path(server["env"]["SBERWORKS_MCP_ENV_FILE"]).is_absolute()


def test_config_snippet_escapes_windows_paths() -> None:
    assert cli._toml_string(r"C:\Users\me\Sberworks-mcp\.env") == r"C:\\Users\\me\\Sberworks-mcp\\.env"
