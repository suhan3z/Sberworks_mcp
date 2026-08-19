from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import pkcs12
import requests

from sberworks_mcp.config import Settings


class SessionFactory:
    def __init__(self, settings: Settings, cache_dir: Path | str = ".cert_cache") -> None:
        self.settings = settings
        self.cache_dir = Path(cache_dir)

    def create(self, *, service: str) -> requests.Session:
        self.settings.require_service(service)
        session = requests.Session()
        session.trust_env = False

        if service == "bitbucket" and self.settings.bitbucket_server_bearer_token:
            session.headers["Authorization"] = f"Bearer {self.settings.bitbucket_server_bearer_token}"
        elif service != "jenkins":
            session.auth = (self.settings.auth_username, self.settings.auth_password)

        if self.settings.requests_ca_bundle:
            ca_bundle = Path(self.settings.requests_ca_bundle)
            if not ca_bundle.exists():
                raise FileNotFoundError(f"REQUESTS_CA_BUNDLE does not exist: {ca_bundle}")
            session.verify = str(ca_bundle)

        cert_pair = self.ensure_pem_pair()
        if cert_pair is not None:
            session.cert = cert_pair
        return session

    def ensure_pem_pair(self) -> tuple[str, str] | None:
        p12_path = self.settings.client_p12_path
        p12_password = self.settings.client_p12_password
        if not p12_path or not p12_password:
            return None

        source = Path(p12_path)
        if not source.exists():
            raise FileNotFoundError(f"CLIENT_P12_PATH does not exist: {source}")

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        crt = self.cache_dir / "client.crt.pem"
        key = self.cache_dir / "client.key.pem"
        metadata_path = self.cache_dir / "client.source.json"
        source_bytes = source.read_bytes()
        source_digest = hashlib.sha256(source_bytes).hexdigest()
        if self._cache_is_current(source, source_digest, crt, key, metadata_path):
            return str(crt), str(key)

        private_key, certificate, _additional = pkcs12.load_key_and_certificates(
            source_bytes,
            p12_password.encode("utf-8"),
        )
        if private_key is None or certificate is None:
            raise RuntimeError("CLIENT_P12_PATH does not contain both a private key and certificate")

        certificate_bytes = certificate.public_bytes(serialization.Encoding.PEM)
        key_bytes = private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        metadata = {
            "source_path": str(source.resolve()),
            "source_sha256": source_digest,
        }
        self._atomic_write(crt, certificate_bytes)
        self._atomic_write(key, key_bytes)
        self._atomic_write(metadata_path, json.dumps(metadata, indent=2).encode("utf-8"))
        return str(crt), str(key)

    @staticmethod
    def _cache_is_current(
        source: Path,
        source_digest: str,
        crt: Path,
        key: Path,
        metadata_path: Path,
    ) -> bool:
        if not crt.exists() or not key.exists():
            return False
        if metadata_path.exists():
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return False
            return (
                metadata.get("source_path") == str(source.resolve())
                and metadata.get("source_sha256") == source_digest
            )

        # Preserve a legacy working cache. A newer source P12 is still treated as
        # a rotation and must be converted before it can be used.
        source_mtime = source.stat().st_mtime_ns
        return min(crt.stat().st_mtime_ns, key.stat().st_mtime_ns) >= source_mtime

    @staticmethod
    def _atomic_write(path: Path, payload: bytes) -> None:
        temp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        try:
            temp_path.write_bytes(payload)
            os.replace(temp_path, path)
        finally:
            temp_path.unlink(missing_ok=True)
