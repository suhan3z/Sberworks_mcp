from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sberworks_mcp.clients.jenkins import JenkinsClient


class FakeResponse:
    def __init__(
        self,
        payload: Any = None,
        status_code: int = 200,
        content_type: str = "application/json",
        headers: dict[str, str] | None = None,
        url: str = "",
    ) -> None:
        self.payload = payload
        self.status_code = status_code
        self.ok = status_code < 400
        self.headers = {"Content-Type": content_type, **(headers or {})}
        if isinstance(payload, bytes):
            self.content = payload
            self.text = payload.decode("utf-8", errors="replace")
        elif isinstance(payload, str):
            self.content = payload.encode("utf-8")
            self.text = payload
        else:
            self.content = b"x" if payload is not None else b""
            self.text = str(payload) if payload is not None else ""
        self.encoding = "utf-8"
        self.closed = False
        self.is_redirect = 300 <= status_code < 400 and bool(self.headers.get("Location"))
        self.url = url

    def json(self) -> Any:
        return self.payload

    def iter_content(self, chunk_size: int):
        for index in range(0, len(self.content), chunk_size):
            yield self.content[index : index + chunk_size]

    def close(self) -> None:
        self.closed = True


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.auth: Any = ("unexpected", "basic")

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append((method, url, kwargs))
        response = self.responses.pop(0)
        if not response.url:
            response.url = url
        return response


def _authenticated() -> list[FakeResponse]:
    return [
        FakeResponse(status_code=404),
        FakeResponse("<form></form>", content_type="text/html"),
        FakeResponse(status_code=302, headers={"Location": "/jenkins-ci/"}),
        FakeResponse({"name": "user", "authenticated": True, "anonymous": False}),
    ]


def _client(session: FakeSession, download_dir: str | None = None) -> JenkinsClient:
    return JenkinsClient(
        "https://jenkins.example.com/jenkins-ci",
        session,
        30,
        "user",
        "top-secret",
        download_dir=download_dir,
    )


def test_form_login_lists_nested_jobs_without_http_basic() -> None:
    session = FakeSession(
        _authenticated()
        + [FakeResponse({"jobs": [{"name": "one"}, {"name": "two"}]})]
    )
    client = _client(session)

    result = client.list_jobs("Folder/feature main", max_results=1)

    assert result["jobs"] == [{"name": "one"}]
    assert result["total"] == 2
    assert result["truncated"] is True
    assert session.auth is None
    assert session.calls[2][1].endswith("/j_spring_security_check")
    assert session.calls[2][2]["data"]["j_username"] == "user"
    assert session.calls[4][1].endswith("/job/Folder/job/feature%20main/api/json")


def test_saml_form_login_uses_shared_credentials_and_preserves_assertion() -> None:
    session = FakeSession(
        [
            FakeResponse(
                """
                <form method="post" action="/keycloak/auth/realms/Sberworks/protocol/saml">
                  <input type="hidden" name="SAMLRequest" value="request-value">
                  <input type="hidden" name="RelayState" value="relay-one">
                </form>
                """,
                content_type="text/html",
            ),
            FakeResponse(
                """
                <form method="post" action="/keycloak/auth/realms/Sberworks/login-actions/authenticate">
                  <input name="username">
                  <input name="password" type="password">
                  <input type="hidden" name="credentialId" value="">
                  <input type="submit" name="login" value="Sign In">
                </form>
                """,
                content_type="text/html",
            ),
            FakeResponse(
                """
                <form method="post" action="/jenkins-ci/securityRealm/finishLogin">
                  <input type="hidden" name="SAMLResponse" value="assertion-value">
                  <input type="hidden" name="RelayState" value="relay-two">
                </form>
                """,
                content_type="text/html",
            ),
            FakeResponse("ok", content_type="text/html"),
            FakeResponse({"name": "user", "authenticated": True, "anonymous": False}),
            FakeResponse({"mode": "NORMAL"}, headers={"X-Jenkins": "2.492.3"}),
            FakeResponse({"name": "user", "authenticated": True, "anonymous": False}),
        ]
    )

    result = _client(session).get_info()

    assert result["authentication_mode"] == "saml_form"
    assert result["user"]["authenticated"] is True
    assert session.calls[1][2]["data"] == {
        "SAMLRequest": "request-value",
        "RelayState": "relay-one",
    }
    assert session.calls[2][2]["data"] == {
        "username": "user",
        "password": "top-secret",
        "credentialId": "",
        "login": "Sign In",
    }
    assert session.calls[3][2]["data"] == {
        "SAMLResponse": "assertion-value",
        "RelayState": "relay-two",
    }
    assert all(url.startswith("https://jenkins.example.com/") for _, url, _ in session.calls)


def test_saml_login_rejects_untrusted_form_host_before_submission() -> None:
    session = FakeSession(
        [
            FakeResponse(
                """
                <form method="post" action="https://attacker.example/saml">
                  <input type="hidden" name="SAMLRequest" value="request-value">
                </form>
                """,
                content_type="text/html",
            )
        ]
    )

    with pytest.raises(RuntimeError) as exc:
        _client(session).list_jobs()

    assert "untrusted host" in str(exc.value)
    assert "top-secret" not in str(exc.value)
    assert len(session.calls) == 1


def test_login_error_is_clear_and_does_not_expose_password() -> None:
    session = FakeSession(
        [
            FakeResponse(status_code=404),
            FakeResponse("login", content_type="text/html"),
            FakeResponse(status_code=302, headers={"Location": "/jenkins-ci/loginError"}),
        ]
    )

    with pytest.raises(RuntimeError) as exc:
        _client(session).list_jobs()

    assert "AUTH_PASSWORD" in str(exc.value)
    assert "top-secret" not in str(exc.value)


def test_anonymous_session_is_rejected_without_exposing_password() -> None:
    session = FakeSession(
        [
            FakeResponse(status_code=404),
            FakeResponse("login", content_type="text/html"),
            FakeResponse(status_code=302, headers={"Location": "/jenkins-ci/"}),
            FakeResponse({"name": "anonymous", "authenticated": False, "anonymous": True}),
        ]
    )

    with pytest.raises(RuntimeError) as exc:
        _client(session).list_jobs()

    assert "authenticated user session" in str(exc.value)
    assert "top-secret" not in str(exc.value)


def test_request_reauthenticates_once_after_forbidden() -> None:
    session = FakeSession(
        _authenticated()
        + [FakeResponse({}, status_code=403)]
        + _authenticated()
        + [FakeResponse({"jobs": []})]
    )
    client = _client(session)

    assert client.list_jobs()["jobs"] == []
    assert sum(call[1].endswith("/j_spring_security_check") for call in session.calls) == 2


def test_progressive_console_returns_bounded_cursor() -> None:
    session = FakeSession(
        _authenticated()
        + [
            FakeResponse(
                "abcdef",
                content_type="text/plain",
                headers={"X-Text-Size": "16", "X-More-Data": "true"},
            )
        ]
    )

    result = _client(session).get_console("Folder/job", 7, start=10, max_chars=3)

    assert result["text"] == "abc"
    assert result["next_start"] == 13
    assert result["server_next_start"] == 16
    assert result["more_data"] is True
    assert result["truncated"] is True


def test_trigger_build_uses_parameters_crumb_and_queue_location() -> None:
    session = FakeSession(
        _authenticated()
        + [
            FakeResponse({"crumbRequestField": "Jenkins-Crumb", "crumb": "crumb-value"}),
            FakeResponse(status_code=201, headers={"Location": "https://jenkins.example.com/jenkins-ci/queue/item/42/"}),
        ]
    )

    result = _client(session).trigger_build(
        "Folder/main",
        {"DEPLOY": True, "VERSION": 17},
    )

    assert result["queue_id"] == 42
    method, url, kwargs = session.calls[-1]
    assert method == "POST"
    assert url.endswith("/job/Folder/job/main/buildWithParameters")
    assert kwargs["data"] == {"DEPLOY": "true", "VERSION": "17"}
    assert kwargs["headers"] == {"Jenkins-Crumb": "crumb-value"}


def test_trigger_build_without_parameters_uses_build_endpoint() -> None:
    session = FakeSession(
        _authenticated()
        + [
            FakeResponse({"crumbRequestField": "Jenkins-Crumb", "crumb": "crumb-value"}),
            FakeResponse(status_code=201, headers={"Location": "/jenkins-ci/queue/item/8/"}),
        ]
    )

    result = _client(session).trigger_build("Folder/проект main")

    assert result["queue_id"] == 8
    method, url, kwargs = session.calls[-1]
    assert method == "POST"
    assert url.endswith(
        "/job/Folder/job/%D0%BF%D1%80%D0%BE%D0%B5%D0%BA%D1%82%20main/build"
    )
    assert kwargs.get("data") is None


def test_expired_session_during_crumb_fetch_reauthenticates_once() -> None:
    session = FakeSession(
        _authenticated()
        + [FakeResponse({}, status_code=403)]
        + _authenticated()
        + [
            FakeResponse({"crumbRequestField": "Jenkins-Crumb", "crumb": "fresh"}),
            FakeResponse(status_code=201, headers={"Location": "/jenkins-ci/queue/item/5/"}),
        ]
    )

    result = _client(session).trigger_build("test")

    assert result["queue_id"] == 5
    assert sum(call[1].endswith("/j_spring_security_check") for call in session.calls) == 2
    assert session.calls[-1][2]["headers"] == {"Jenkins-Crumb": "fresh"}


def test_stop_and_cancel_reuse_session_crumb() -> None:
    session = FakeSession(
        _authenticated()
        + [
            FakeResponse({"crumbRequestField": "Jenkins-Crumb", "crumb": "crumb-value"}),
            FakeResponse(status_code=302, headers={"Location": "/jenkins-ci/job/test/7/"}),
            FakeResponse(status_code=302, headers={"Location": "/jenkins-ci/"}),
        ]
    )
    client = _client(session)

    assert client.stop_build("test", 7)["accepted"] is True
    assert client.cancel_queue_item(9)["accepted"] is True

    assert session.calls[-2][1].endswith("/job/test/7/stop")
    assert session.calls[-1][1].endswith("/queue/cancelItem")
    assert session.calls[-1][2]["params"] == {"id": 9}
    assert session.calls[-1][2]["headers"] == {"Jenkins-Crumb": "crumb-value"}


def test_artifact_download_is_atomic_and_rejects_traversal(tmp_path: Path) -> None:
    session = FakeSession(_authenticated() + [FakeResponse(b"artifact", content_type="application/octet-stream")])
    client = _client(session, download_dir=str(tmp_path))

    result = client.download_artifact("folder/job", 3, "reports/result.zip")

    assert Path(result["path"]).read_bytes() == b"artifact"
    assert result["bytes"] == 8
    assert session.calls[-1][1].endswith("/job/folder/job/job/3/artifact/reports/result.zip")

    with pytest.raises(ValueError):
        client.download_artifact("folder/job", 3, "../secret")


def test_job_and_parameter_validation_rejects_unsafe_values() -> None:
    client = _client(FakeSession([]))

    with pytest.raises(ValueError):
        client.get_job("https://attacker.example/job/x")
    with pytest.raises(ValueError):
        client.trigger_build("job", {"FILE": {"name": "secret"}})
