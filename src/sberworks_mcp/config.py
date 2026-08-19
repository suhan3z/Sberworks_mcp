from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    jira_base_url: str
    confluence_base_url: str
    bitbucket_base_url: str
    jenkins_base_url: str
    auth_username: str
    auth_password: str
    bitbucket_server_bearer_token: str | None
    requests_ca_bundle: str | None
    client_p12_path: str | None
    client_p12_password: str | None
    cert_cache_dir: str
    download_dir: str
    enable_writes: bool
    timeout_seconds: int

    def require_service(self, service: str) -> None:
        missing: list[str] = []
        if service == "jira" and not self.jira_base_url:
            missing.append("JIRA_BASE_URL")
        if service == "confluence" and not self.confluence_base_url:
            missing.append("CONFLUENCE_BASE_URL")
        if service == "bitbucket" and not self.bitbucket_base_url:
            missing.append("BITBUCKET_BASE_URL")
        if service == "jenkins" and not self.jenkins_base_url:
            missing.append("JENKINS_BASE_URL")
        if not self.auth_username and not (
            service == "bitbucket" and self.bitbucket_server_bearer_token
        ):
            missing.append("AUTH_USERNAME")
        if not self.auth_password and not (
            service == "bitbucket" and self.bitbucket_server_bearer_token
        ):
            missing.append("AUTH_PASSWORD")
        if missing:
            raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")

    def validate_required(self) -> None:
        missing = []
        for name, value in (
            ("JIRA_BASE_URL", self.jira_base_url),
            ("CONFLUENCE_BASE_URL", self.confluence_base_url),
            ("BITBUCKET_BASE_URL", self.bitbucket_base_url),
            ("AUTH_USERNAME", self.auth_username),
            ("AUTH_PASSWORD", self.auth_password),
        ):
            if not value:
                missing.append(name)
        if missing:
            raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _optional(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


def load_settings(*, env_file: str | None = None, require_all: bool = False) -> Settings:
    dotenv_path = env_file or os.getenv("SBERWORKS_MCP_ENV_FILE", "").strip()
    if dotenv_path:
        env_path = Path(dotenv_path)
        load_dotenv(dotenv_path=env_path, override=False)
    else:
        env_path = None
        load_dotenv(override=False)

    cert_cache_dir = _optional(os.getenv("SBERWORKS_MCP_CERT_CACHE_DIR"))
    if cert_cache_dir is None:
        cert_cache_dir = str((env_path.resolve().parent / ".cert_cache") if env_path else Path(".cert_cache"))
    download_dir = _optional(os.getenv("SBERWORKS_MCP_DOWNLOAD_DIR"))
    if download_dir is None:
        download_dir = str(Path(tempfile.gettempdir()) / "sberworks-mcp-downloads")

    settings = Settings(
        jira_base_url=os.getenv("JIRA_BASE_URL", "").rstrip("/"),
        confluence_base_url=os.getenv("CONFLUENCE_BASE_URL", "").rstrip("/"),
        bitbucket_base_url=os.getenv("BITBUCKET_BASE_URL", "").rstrip("/"),
        jenkins_base_url=os.getenv("JENKINS_BASE_URL", "").rstrip("/"),
        auth_username=os.getenv("AUTH_USERNAME", ""),
        auth_password=os.getenv("AUTH_PASSWORD", ""),
        bitbucket_server_bearer_token=_optional(os.getenv("BITBUCKET_SERVER_BEARER_TOKEN")),
        requests_ca_bundle=_optional(os.getenv("REQUESTS_CA_BUNDLE")),
        client_p12_path=_optional(os.getenv("CLIENT_P12_PATH")),
        client_p12_password=_optional(os.getenv("CLIENT_P12_PASSWORD")),
        cert_cache_dir=cert_cache_dir,
        download_dir=download_dir,
        enable_writes=_truthy(os.getenv("SBERWORKS_MCP_ENABLE_WRITES")),
        timeout_seconds=int(os.getenv("SBERWORKS_MCP_TIMEOUT_SECONDS", "30")),
    )
    if require_all:
        settings.validate_required()
    return settings


def require_writes(settings: Settings) -> None:
    if not settings.enable_writes:
        raise PermissionError(
            "Mutating tools are disabled. Set SBERWORKS_MCP_ENABLE_WRITES=true to enable write operations."
        )
