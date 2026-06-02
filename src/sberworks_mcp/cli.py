from __future__ import annotations

import argparse
import getpass
import importlib.metadata
import json
import platform
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from dotenv import dotenv_values

from sberworks_mcp.config import load_settings
from sberworks_mcp.server import main as serve_main

REQUIRED_ENV = (
    "JIRA_BASE_URL",
    "CONFLUENCE_BASE_URL",
    "BITBUCKET_BASE_URL",
    "AUTH_USERNAME",
    "AUTH_PASSWORD",
)

OPTIONAL_ENV = (
    "BITBUCKET_SERVER_BEARER_TOKEN",
    "REQUESTS_CA_BUNDLE",
    "CLIENT_P12_PATH",
    "CLIENT_P12_PASSWORD",
    "SBERWORKS_MCP_ENABLE_WRITES",
    "SBERWORKS_MCP_TIMEOUT_SECONDS",
)


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command in (None, "serve"):
        serve_main()
        return 0
    if args.command == "init":
        return _init_command(args)
    if args.command == "doctor":
        return _doctor_command(args)
    if args.command == "config-snippet":
        return _config_snippet_command(args)
    raise AssertionError(f"Unhandled command: {args.command}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sberworks-mcp",
        description="Local stdio MCP server for Jira, Confluence and Bitbucket Server/Data Center.",
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("serve", help="Run the MCP stdio server.")

    init_parser = subparsers.add_parser("init", help="Interactively create a local .env file.")
    init_parser.add_argument("--env-file", default=".env", help="Path to write. Defaults to .env.")
    init_parser.add_argument("--force", action="store_true", help="Overwrite an existing env file.")

    doctor_parser = subparsers.add_parser("doctor", help="Check installation and first-run configuration.")
    doctor_parser.add_argument("--env-file", default=None, help="Env file to check. Defaults to SBERWORKS_MCP_ENV_FILE or .env.")

    snippet_parser = subparsers.add_parser("config-snippet", help="Print MCP client configuration.")
    snippet_parser.add_argument("--client", choices=("claude", "codex", "vscode"), required=True)
    snippet_parser.add_argument("--env-file", default=".env", help="Env file path to reference. Defaults to .env.")
    snippet_parser.add_argument("--name", default="sberworks", help="MCP server name. Defaults to sberworks.")
    snippet_parser.add_argument(
        "--runtime",
        choices=("local", "docker"),
        default="local",
        help="Runtime used by the MCP client. Defaults to local Python.",
    )
    snippet_parser.add_argument(
        "--image",
        default="sberworks-mcp:local",
        help="Docker image name for --runtime docker. Defaults to sberworks-mcp:local.",
    )

    return parser


def _init_command(args: argparse.Namespace) -> int:
    env_path = Path(args.env_file).expanduser()
    if env_path.exists() and not args.force:
        print(f"Refusing to overwrite existing env file: {env_path}")
        print("Use --force to replace it.")
        return 1

    values = collect_init_values(input_func=input, secret_func=getpass.getpass)
    write_env_file(env_path, values)
    print(f"Created {env_path.resolve()}")
    print("Secrets were written to the env file and were not printed.")
    print("Next: run `sberworks-mcp doctor --env-file <path>`.")
    return 0


def collect_init_values(
    *,
    input_func: Callable[[str], str],
    secret_func: Callable[[str], str],
) -> dict[str, str]:
    values: dict[str, str] = {}
    values["JIRA_BASE_URL"] = _prompt(input_func, "Jira base URL")
    values["CONFLUENCE_BASE_URL"] = _prompt(input_func, "Confluence base URL")
    values["BITBUCKET_BASE_URL"] = _prompt(input_func, "Bitbucket base URL")
    values["AUTH_USERNAME"] = _prompt(input_func, "Shared basic auth username")
    values["AUTH_PASSWORD"] = secret_func("Shared basic auth password: ").strip()
    values["BITBUCKET_SERVER_BEARER_TOKEN"] = secret_func(
        "Optional Bitbucket bearer token (press Enter to skip): "
    ).strip()
    values["REQUESTS_CA_BUNDLE"] = _absolute_optional_path(
        _prompt(input_func, "Optional CA bundle path (press Enter to skip)", required=False)
    )
    values["CLIENT_P12_PATH"] = _absolute_optional_path(
        _prompt(input_func, "Optional client P12 path (press Enter to skip)", required=False)
    )
    values["CLIENT_P12_PASSWORD"] = secret_func("Optional client P12 password (press Enter to skip): ").strip()
    values["SBERWORKS_MCP_ENABLE_WRITES"] = "false"
    values["SBERWORKS_MCP_TIMEOUT_SECONDS"] = _prompt(
        input_func,
        "HTTP timeout seconds",
        default="30",
    )
    return values


def write_env_file(path: Path, values: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Jira / Confluence / Bitbucket endpoints",
        _dotenv_line("JIRA_BASE_URL", values["JIRA_BASE_URL"]),
        _dotenv_line("CONFLUENCE_BASE_URL", values["CONFLUENCE_BASE_URL"]),
        _dotenv_line("BITBUCKET_BASE_URL", values["BITBUCKET_BASE_URL"]),
        "",
        "# Shared basic auth. Used for Jira, Confluence and Bitbucket fallback.",
        _dotenv_line("AUTH_USERNAME", values["AUTH_USERNAME"]),
        _dotenv_line("AUTH_PASSWORD", values["AUTH_PASSWORD"]),
        "",
        "# Optional Bitbucket bearer token. If set, it takes precedence for Bitbucket.",
        _dotenv_line("BITBUCKET_SERVER_BEARER_TOKEN", values["BITBUCKET_SERVER_BEARER_TOKEN"]),
        "",
        "# Optional corporate TLS settings. Use absolute paths for MCP clients.",
        _dotenv_line("REQUESTS_CA_BUNDLE", values["REQUESTS_CA_BUNDLE"]),
        _dotenv_line("CLIENT_P12_PATH", values["CLIENT_P12_PATH"]),
        _dotenv_line("CLIENT_P12_PASSWORD", values["CLIENT_P12_PASSWORD"]),
        "",
        "# Mutating MCP tools are disabled unless this is true.",
        _dotenv_line("SBERWORKS_MCP_ENABLE_WRITES", values["SBERWORKS_MCP_ENABLE_WRITES"]),
        "",
        "# HTTP behavior",
        _dotenv_line("SBERWORKS_MCP_TIMEOUT_SECONDS", values["SBERWORKS_MCP_TIMEOUT_SECONDS"]),
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def _dotenv_line(name: str, value: str) -> str:
    return f"{name}={_dotenv_value(value)}"


def _dotenv_value(value: str) -> str:
    if value == "":
        return ""
    if any(char.isspace() for char in value) or any(char in value for char in '#"\\'):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value


def _prompt(
    input_func: Callable[[str], str],
    label: str,
    *,
    required: bool = True,
    default: str | None = None,
) -> str:
    suffix = f" [{default}]" if default is not None else ""
    while True:
        value = input_func(f"{label}{suffix}: ").strip()
        if not value and default is not None:
            return default
        if value or not required:
            return value
        print(f"{label} is required.")


def _absolute_optional_path(value: str) -> str:
    if not value:
        return ""
    return str(Path(value).expanduser().resolve())


def _doctor_command(args: argparse.Namespace) -> int:
    report = run_doctor(Path(args.env_file).expanduser() if args.env_file else None)
    for line in report.lines:
        print(line)
    return report.exit_code


class DoctorReport:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.info: list[str] = []

    @property
    def exit_code(self) -> int:
        if self.errors:
            return 1
        if self.warnings:
            return 2
        return 0

    @property
    def lines(self) -> list[str]:
        lines = ["Sberworks MCP doctor"]
        lines.extend(f"OK: {item}" for item in self.info)
        lines.extend(f"WARN: {item}" for item in self.warnings)
        lines.extend(f"ERROR: {item}" for item in self.errors)
        if self.exit_code == 0:
            lines.append("Ready for first MCP client launch.")
        return lines


def run_doctor(env_file: Path | None = None) -> DoctorReport:
    report = DoctorReport()
    report.info.append(f"OS: {platform.system() or 'unknown'} {platform.release()}")
    _check_python(report)
    _check_distribution(report)

    resolved_env = _resolve_env_file(env_file)
    values: dict[str, str | None] = {}
    if resolved_env is None:
        report.warnings.append("No env file found. Expected --env-file, SBERWORKS_MCP_ENV_FILE, or .env.")
    elif not resolved_env.exists():
        report.errors.append(f"Env file does not exist: {resolved_env}")
    else:
        report.info.append(f"Env file: {resolved_env}")
        values = dotenv_values(resolved_env)
        _check_env_values(report, values)

    try:
        settings = load_settings(env_file=str(resolved_env) if resolved_env and resolved_env.exists() else None)
        if settings.enable_writes:
            report.warnings.append("Write tools are enabled. Keep SBERWORKS_MCP_ENABLE_WRITES=false for read-only first launch.")
        else:
            report.info.append("Write tools are disabled by default.")
    except ValueError as exc:
        report.errors.append(f"Invalid numeric env value: {exc}")
    except Exception as exc:  # noqa: BLE001
        report.errors.append(f"Could not load settings: {exc}")

    return report


def _check_python(report: DoctorReport) -> None:
    version = sys.version_info
    if version < (3, 11):
        report.errors.append(f"Python >=3.11 is required; found {platform.python_version()}.")
    else:
        report.info.append(f"Python: {platform.python_version()}")


def _check_distribution(report: DoctorReport) -> None:
    try:
        version = importlib.metadata.version("sberworks-mcp")
    except importlib.metadata.PackageNotFoundError:
        report.warnings.append("Package metadata not found. Editable install may not have been run.")
    else:
        report.info.append(f"Package: sberworks-mcp {version}")
    try:
        importlib.metadata.version("mcp")
    except importlib.metadata.PackageNotFoundError:
        report.errors.append("Python package `mcp` is not installed.")
    else:
        report.info.append("MCP SDK import metadata found.")
    try:
        importlib.metadata.version("cryptography")
    except importlib.metadata.PackageNotFoundError:
        report.errors.append("Python package `cryptography` is not installed.")
    else:
        report.info.append("Cryptography package import metadata found.")


def _resolve_env_file(env_file: Path | None) -> Path | None:
    if env_file is not None:
        return env_file.resolve()
    from_env = load_env_file_path_from_process()
    if from_env:
        return from_env
    default = Path(".env")
    if default.exists():
        return default.resolve()
    return None


def load_env_file_path_from_process() -> Path | None:
    import os

    value = os.getenv("SBERWORKS_MCP_ENV_FILE", "").strip()
    if not value:
        return None
    return Path(value).expanduser().resolve()


def _check_env_values(report: DoctorReport, values: dict[str, str | None]) -> None:
    for name in REQUIRED_ENV:
        if not (values.get(name) or "").strip():
            report.errors.append(f"Missing required env var: {name}")
    for name in ("JIRA_BASE_URL", "CONFLUENCE_BASE_URL", "BITBUCKET_BASE_URL"):
        value = (values.get(name) or "").strip()
        if value and not _valid_http_url(value):
            report.errors.append(f"{name} must be an absolute http(s) URL: {value}")

    timeout = (values.get("SBERWORKS_MCP_TIMEOUT_SECONDS") or "30").strip()
    try:
        timeout_seconds = int(timeout)
    except ValueError:
        report.errors.append("SBERWORKS_MCP_TIMEOUT_SECONDS must be an integer.")
    else:
        if timeout_seconds <= 0:
            report.errors.append("SBERWORKS_MCP_TIMEOUT_SECONDS must be greater than 0.")

    _check_existing_path(report, values.get("REQUESTS_CA_BUNDLE"), "REQUESTS_CA_BUNDLE")
    p12_path = (values.get("CLIENT_P12_PATH") or "").strip()
    p12_password = (values.get("CLIENT_P12_PASSWORD") or "").strip()
    _check_existing_path(report, p12_path, "CLIENT_P12_PATH")
    if p12_path and not p12_password:
        report.errors.append("CLIENT_P12_PASSWORD is required when CLIENT_P12_PATH is set.")


def _valid_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _check_existing_path(report: DoctorReport, value: str | None, name: str) -> None:
    value = (value or "").strip()
    if not value:
        return
    path = Path(value).expanduser()
    if not path.is_absolute():
        report.warnings.append(f"{name} should be an absolute path for MCP clients: {value}")
    if not path.exists():
        report.errors.append(f"{name} does not exist: {path}")


def _config_snippet_command(args: argparse.Namespace) -> int:
    print(
        build_config_snippet(
            client=args.client,
            env_file=Path(args.env_file),
            name=args.name,
            runtime=args.runtime,
            image=args.image,
        )
    )
    return 0


def build_config_snippet(
    *,
    client: str,
    env_file: Path,
    name: str = "sberworks",
    runtime: str = "local",
    image: str = "sberworks-mcp:local",
) -> str:
    env_path = str(env_file.expanduser().resolve())
    if runtime == "local":
        command = str(Path(sys.executable).resolve())
        snippet_args = ["-m", "sberworks_mcp"]
        snippet_env = {"SBERWORKS_MCP_ENV_FILE": env_path}
    elif runtime == "docker":
        command = "docker"
        snippet_args = _docker_run_args(env_file=env_file, image=image)
        snippet_env = None
    else:
        raise ValueError(f"Unsupported runtime: {runtime}")

    if client == "claude":
        server: dict[str, Any] = {
            "command": command,
            "args": snippet_args,
        }
        if snippet_env is not None:
            server["env"] = snippet_env
        payload = {
            "mcpServers": {
                name: server
            }
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)
    if client == "vscode":
        server = {
            "type": "stdio",
            "command": command,
            "args": snippet_args,
        }
        if snippet_env is not None:
            server["env"] = snippet_env
        payload = {
            "servers": {
                name: server
            }
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)
    if client == "codex":
        lines = [
            f"[mcp_servers.{_toml_key(name)}]",
            f'command = "{_toml_string(command)}"',
            f"args = {_toml_array(snippet_args)}",
        ]
        if snippet_env is not None:
            lines.extend(
                [
                    "",
                    f"[mcp_servers.{_toml_key(name)}.env]",
                    f'SBERWORKS_MCP_ENV_FILE = "{_toml_string(env_path)}"',
                ]
            )
        return "\n".join(lines)
    raise ValueError(f"Unsupported client: {client}")


def _docker_run_args(*, env_file: Path, image: str) -> list[str]:
    env_path = str(env_file.expanduser().resolve())
    env_dir = env_file.expanduser().resolve().parent
    return [
        "run",
        "--rm",
        "-i",
        "--env-file",
        env_path,
        "-e",
        "SBERWORKS_MCP_ENV_FILE=/config/.env",
        "-v",
        f"{env_path}:/config/.env:ro",
        "-v",
        f"{env_dir / 'certs'}:/certs:ro",
        "-v",
        f"{env_dir / 'attachments'}:/attachments:ro",
        image,
        "serve",
    ]


def _toml_key(value: str) -> str:
    if value.replace("_", "").replace("-", "").isalnum():
        return value
    return f'"{_toml_string(value)}"'


def _toml_array(values: Sequence[str]) -> str:
    return "[" + ", ".join(f'"{_toml_string(value)}"' for value in values) + "]"


def _toml_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
