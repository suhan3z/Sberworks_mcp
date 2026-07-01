from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from sberworks_mcp.auth import SessionFactory
from sberworks_mcp.config import Settings, load_settings, require_writes


def _settings(**overrides: object) -> Settings:
    settings = Settings(
        jira_base_url="https://jira.example.com",
        confluence_base_url="https://wiki.example.com",
        bitbucket_base_url="https://git.example.com/bitbucket",
        auth_username="user",
        auth_password="pass",
        bitbucket_server_bearer_token=None,
        requests_ca_bundle=None,
        client_p12_path=None,
        client_p12_password=None,
        cert_cache_dir=".cert_cache",
        download_dir="downloads",
        enable_writes=False,
        timeout_seconds=30,
    )
    return replace(settings, **overrides)


def test_load_settings_reports_missing_required(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "JIRA_BASE_URL",
        "CONFLUENCE_BASE_URL",
        "BITBUCKET_BASE_URL",
        "AUTH_USERNAME",
        "AUTH_PASSWORD",
    ):
        monkeypatch.setenv(name, "")

    with pytest.raises(RuntimeError) as exc:
        load_settings(require_all=True)

    assert "JIRA_BASE_URL" in str(exc.value)
    assert "AUTH_PASSWORD" in str(exc.value)


def test_cert_cache_defaults_next_to_env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "JIRA_BASE_URL=https://jira.example.com",
                "CONFLUENCE_BASE_URL=https://wiki.example.com",
                "BITBUCKET_BASE_URL=https://git.example.com/bitbucket",
                "AUTH_USERNAME=user",
                "AUTH_PASSWORD=pass",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("SBERWORKS_MCP_CERT_CACHE_DIR", raising=False)

    settings = load_settings(env_file=str(env_file))

    assert settings.cert_cache_dir == str(tmp_path / ".cert_cache")


def test_download_dir_can_be_configured(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    download_dir = tmp_path / "downloads"
    monkeypatch.setenv("SBERWORKS_MCP_DOWNLOAD_DIR", str(download_dir))

    settings = load_settings()

    assert settings.download_dir == str(download_dir)


def test_bitbucket_bearer_token_takes_precedence() -> None:
    session = SessionFactory(_settings(auth_username="", auth_password="", bitbucket_server_bearer_token="token")).create(
        service="bitbucket"
    )

    assert session.headers["Authorization"] == "Bearer token"
    assert session.auth is None


def test_ca_bundle_path_is_applied(tmp_path: Path) -> None:
    ca_bundle = tmp_path / "ca.pem"
    ca_bundle.write_text("test", encoding="utf-8")

    session = SessionFactory(_settings(requests_ca_bundle=str(ca_bundle))).create(service="jira")

    assert session.verify == str(ca_bundle)


def test_missing_ca_bundle_fails_fast(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        SessionFactory(_settings(requests_ca_bundle=str(tmp_path / "missing.pem"))).create(service="jira")


def test_p12_conversion_uses_cryptography(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p12 = tmp_path / "client.p12"
    p12.write_bytes(b"fake")
    cache_dir = tmp_path / "cache"

    class FakeCertificate:
        def public_bytes(self, encoding: object) -> bytes:
            del encoding
            return b"cert-pem"

    class FakePrivateKey:
        def private_bytes(self, encoding: object, format: object, encryption_algorithm: object) -> bytes:
            del encoding, format, encryption_algorithm
            return b"key-pem"

    def fake_load_key_and_certificates(payload: bytes, password: bytes):
        assert payload == b"fake"
        assert password == b"secret"
        return FakePrivateKey(), FakeCertificate(), []

    monkeypatch.setattr(
        "sberworks_mcp.auth.pkcs12.load_key_and_certificates",
        fake_load_key_and_certificates,
    )

    cert_pair = SessionFactory(
        _settings(client_p12_path=str(p12), client_p12_password="secret"),
        cache_dir=cache_dir,
    ).ensure_pem_pair()

    assert cert_pair == (str(cache_dir / "client.crt.pem"), str(cache_dir / "client.key.pem"))
    assert (cache_dir / "client.crt.pem").read_bytes() == b"cert-pem"
    assert (cache_dir / "client.key.pem").read_bytes() == b"key-pem"


def test_write_guard_requires_explicit_enable() -> None:
    with pytest.raises(PermissionError):
        require_writes(_settings(enable_writes=False))

    require_writes(_settings(enable_writes=True))
