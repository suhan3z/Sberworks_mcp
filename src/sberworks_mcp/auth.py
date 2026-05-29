from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

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

        if shutil.which("openssl") is None:
            raise RuntimeError("CLIENT_P12_PATH is configured, but openssl is not available in PATH")

        source = Path(p12_path)
        if not source.exists():
            raise FileNotFoundError(f"CLIENT_P12_PATH does not exist: {source}")

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        crt = self.cache_dir / "client.crt.pem"
        key = self.cache_dir / "client.key.pem"
        if crt.exists() and key.exists():
            return str(crt), str(key)

        env = os.environ.copy()
        env["P12_PASS"] = p12_password
        subprocess.run(
            [
                "openssl",
                "pkcs12",
                "-in",
                str(source),
                "-clcerts",
                "-nokeys",
                "-out",
                str(crt),
                "-passin",
                "env:P12_PASS",
            ],
            check=True,
            env=env,
            capture_output=True,
        )
        subprocess.run(
            [
                "openssl",
                "pkcs12",
                "-in",
                str(source),
                "-nocerts",
                "-nodes",
                "-out",
                str(key),
                "-passin",
                "env:P12_PASS",
            ],
            check=True,
            env=env,
            capture_output=True,
        )
        return str(crt), str(key)
