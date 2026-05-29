from __future__ import annotations

from typing import Any

import requests


class AtlassianClient:
    def __init__(self, base_url: str, session: requests.Session, timeout_seconds: int) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = session
        self.timeout_seconds = timeout_seconds

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = path if path.startswith(("http://", "https://")) else f"{self.base_url}{path}"
        kwargs.setdefault("timeout", self.timeout_seconds)
        response = self.session.request(method, url, **kwargs)
        if not response.ok:
            body = response.text.replace("\r", "\\r").replace("\n", "\\n")[:1000]
            raise RuntimeError(f"{method} {url} failed: HTTP {response.status_code}; body={body}")
        if response.status_code == 204 or not response.content:
            return {"ok": True}
        content_type = (response.headers.get("Content-Type") or "").lower()
        if "application/json" in content_type:
            return response.json()
        return response.text
