from __future__ import annotations

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
        else:
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
        if crt.exists() and key.exists():
            return str(crt), str(key)

        private_key, certificate, _additional = pkcs12.load_key_and_certificates(
            source.read_bytes(),
            p12_password.encode("utf-8"),
        )
        if private_key is None or certificate is None:
            raise RuntimeError("CLIENT_P12_PATH does not contain both a private key and certificate")

        crt.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
        key.write_bytes(
            private_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        return str(crt), str(key)
