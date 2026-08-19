from __future__ import annotations

import hashlib
import os
import tempfile
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin, urlparse

import requests


class _FormParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.forms: list[dict[str, Any]] = []
        self._current: dict[str, Any] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "form":
            self._current = {
                "action": values.get("action") or "",
                "method": (values.get("method") or "get").lower(),
                "inputs": [],
            }
            self.forms.append(self._current)
        elif tag == "input" and self._current is not None:
            self._current["inputs"].append(
                {
                    "name": values.get("name"),
                    "type": (values.get("type") or "text").lower(),
                    "value": values.get("value") or "",
                }
            )

    def handle_endtag(self, tag: str) -> None:
        if tag == "form":
            self._current = None


class JenkinsClient:
    def __init__(
        self,
        base_url: str,
        session: requests.Session,
        timeout_seconds: int,
        username: str,
        password: str,
        download_dir: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = session
        self.timeout_seconds = timeout_seconds
        self.username = username
        self.password = password
        self.download_dir = download_dir or str(Path(tempfile.gettempdir()) / "sberworks-mcp-downloads")
        self._authenticated = False
        self._crumb: tuple[str, str] | None = None
        self._authentication_mode: str | None = None

    def login(self) -> dict[str, Any]:
        self.session.auth = None
        return_path = f"{urlparse(self.base_url).path.rstrip('/')}/"
        if self._saml_form_login(return_path):
            self._authentication_mode = "saml_form"
        else:
            self._jenkins_form_login(return_path)
            self._authentication_mode = "jenkins_form"

        whoami = self._verify_session()
        self._authenticated = True
        self._crumb = None
        return whoami

    def _saml_form_login(self, return_path: str) -> bool:
        response = self._raw_request(
            "GET",
            "/securityRealm/commenceLogin",
            params={"from": return_path},
            allow_redirects=True,
        )
        if not response.ok:
            return False

        saml_form = self._find_form(response.text, "SAMLRequest")
        if saml_form is None:
            return False
        idp_response = self._submit_form(response.url, saml_form)

        assertion_form = self._find_form(idp_response.text, "SAMLResponse")
        if assertion_form is None:
            login_form = self._find_login_form(idp_response.text)
            if login_form is None:
                raise RuntimeError("Jenkins SAML login did not return a supported identity-provider form.")
            login_data = self._form_data(login_form, include_submit=True)
            login_data["username"] = self.username
            login_data["password"] = self.password
            login_response = self._submit_form(idp_response.url, login_form, data=login_data)
            assertion_form = self._find_form(login_response.text, "SAMLResponse")
            if assertion_form is None:
                raise RuntimeError(
                    "Jenkins SAML form login rejected configured AUTH_USERNAME/AUTH_PASSWORD."
                )
            assertion_base_url = login_response.url
        else:
            assertion_base_url = idp_response.url

        finish_response = self._submit_form(assertion_base_url, assertion_form)
        if not finish_response.ok:
            raise RuntimeError(
                f"Jenkins SAML assertion exchange failed: HTTP {finish_response.status_code}."
            )
        return True

    def _jenkins_form_login(self, return_path: str) -> None:
        login_page = self._raw_request("GET", "/login", allow_redirects=False)
        self._raise_for_status(login_page, "GET", "/login")

        response = self._raw_request(
            "POST",
            "/j_spring_security_check",
            data={
                "j_username": self.username,
                "j_password": self.password,
                "remember_me": "on",
                "from": return_path,
            },
            allow_redirects=False,
        )
        location = response.headers.get("Location") or ""
        if response.status_code not in {302, 303} or "loginError" in location:
            raise RuntimeError(
                "Jenkins form login failed for configured AUTH_USERNAME; verify AUTH_PASSWORD."
            )

    def _verify_session(self) -> dict[str, Any]:
        whoami_response = self._raw_request("GET", "/whoAmI/api/json", allow_redirects=False)
        self._raise_for_status(whoami_response, "GET", "/whoAmI/api/json")
        whoami = self._json(whoami_response, "/whoAmI/api/json")
        if whoami.get("anonymous") or not whoami.get("authenticated"):
            raise RuntimeError("Jenkins form login completed without an authenticated user session.")

        return whoami

    def get_info(self) -> dict[str, Any]:
        response = self._request(
            "GET",
            "/api/json",
            params={
                "tree": "mode,nodeDescription,numExecutors,quietingDown,useCrumbs,views[name,url]"
            },
        )
        payload = self._json(response, "/api/json")
        whoami = self._json(self._request("GET", "/whoAmI/api/json"), "/whoAmI/api/json")
        payload["version"] = response.headers.get("X-Jenkins")
        payload["authentication_mode"] = self._authentication_mode
        payload["user"] = {
            "name": whoami.get("name"),
            "authenticated": bool(whoami.get("authenticated")),
            "anonymous": bool(whoami.get("anonymous")),
        }
        return payload

    def list_jobs(self, folder_path: str | None = None, max_results: int = 100) -> dict[str, Any]:
        max_results = self._bounded(max_results, "max_results", maximum=100)
        prefix = self._job_path(folder_path) if folder_path else ""
        response = self._request(
            "GET",
            f"{prefix}/api/json",
            params={"tree": "jobs[name,url,color,_class]"},
        )
        payload = self._json(response, f"{prefix}/api/json")
        jobs = payload.get("jobs") or []
        return {
            "folder_path": folder_path,
            "jobs": jobs[:max_results],
            "total": len(jobs),
            "truncated": len(jobs) > max_results,
        }

    def get_job(self, job_path: str) -> dict[str, Any]:
        path = self._job_path(job_path)
        response = self._request(
            "GET",
            f"{path}/api/json",
            params={
                "tree": (
                    "name,url,color,_class,buildable,inQueue,"
                    "queueItem[id,url,why,blocked,stuck],"
                    "lastBuild[number,url],lastCompletedBuild[number,url,result],"
                    "lastSuccessfulBuild[number,url,result],lastFailedBuild[number,url,result]"
                )
            },
        )
        return self._json(response, f"{path}/api/json")

    def list_builds(self, job_path: str, limit: int = 20) -> dict[str, Any]:
        limit = self._bounded(limit, "limit", maximum=100)
        path = self._job_path(job_path)
        tree = f"builds[number,url,result,building,timestamp,duration,estimatedDuration]{{0,{limit}}}"
        response = self._request("GET", f"{path}/api/json", params={"tree": tree})
        payload = self._json(response, f"{path}/api/json")
        return {"job_path": job_path, "builds": payload.get("builds") or []}

    def get_build(self, job_path: str, build_number: int) -> dict[str, Any]:
        path = self._build_path(job_path, build_number)
        response = self._request(
            "GET",
            f"{path}/api/json",
            params={
                "tree": (
                    "number,url,displayName,fullDisplayName,result,building,timestamp,duration,"
                    "estimatedDuration,description,queueId,artifacts[fileName,relativePath],"
                    "actions[causes[*],parameters[name,value]]"
                )
            },
        )
        return self._json(response, f"{path}/api/json")

    def get_console(
        self,
        job_path: str,
        build_number: int,
        start: int = 0,
        max_chars: int = 50_000,
    ) -> dict[str, Any]:
        if start < 0:
            raise ValueError("start must be greater than or equal to 0")
        max_chars = self._bounded(max_chars, "max_chars", maximum=200_000)
        path = f"{self._build_path(job_path, build_number)}/logText/progressiveText"
        response = self._request("GET", path, params={"start": start})
        complete_text = response.text
        text = complete_text[:max_chars]
        truncated = len(complete_text) > len(text)
        server_next_start = int(response.headers.get("X-Text-Size") or start)
        if truncated:
            encoding = response.encoding or "utf-8"
            next_start = start + len(text.encode(encoding, errors="replace"))
        else:
            next_start = server_next_start
        return {
            "job_path": job_path,
            "build_number": build_number,
            "text": text,
            "start": start,
            "next_start": next_start,
            "server_next_start": server_next_start,
            "more_data": truncated or (response.headers.get("X-More-Data") or "").lower() == "true",
            "truncated": truncated,
        }

    def list_queue(self) -> dict[str, Any]:
        response = self._request(
            "GET",
            "/queue/api/json",
            params={
                "tree": (
                    "items[id,url,why,blocked,buildable,stuck,inQueueSince,"
                    "task[name,url,color],actions[parameters[name,value]],executable[number,url]]"
                )
            },
        )
        return self._json(response, "/queue/api/json")

    def get_queue_item(self, queue_id: int) -> dict[str, Any]:
        if queue_id <= 0:
            raise ValueError("queue_id must be greater than 0")
        path = f"/queue/item/{queue_id}/api/json"
        return self._json(self._request("GET", path), path)

    def list_artifacts(self, job_path: str, build_number: int) -> dict[str, Any]:
        path = self._build_path(job_path, build_number)
        response = self._request(
            "GET",
            f"{path}/api/json",
            params={"tree": "number,url,artifacts[fileName,relativePath]"},
        )
        payload = self._json(response, f"{path}/api/json")
        return {
            "job_path": job_path,
            "build_number": build_number,
            "artifacts": payload.get("artifacts") or [],
        }

    def download_artifact(
        self,
        job_path: str,
        build_number: int,
        artifact_path: str,
        output_path: str | None = None,
        output_dir: str | None = None,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        encoded_artifact = self._artifact_path(artifact_path)
        target = self._download_target(artifact_path, output_path, output_dir)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and not overwrite:
            raise FileExistsError(f"Output file already exists: {target}")

        path = f"{self._build_path(job_path, build_number)}/artifact/{encoded_artifact}"
        response = self._request("GET", path, stream=True)
        digest = hashlib.sha256()
        byte_count = 0
        temp_name = ""
        try:
            with tempfile.NamedTemporaryFile(
                "wb",
                delete=False,
                dir=str(target.parent),
                prefix=f".{target.name}.",
                suffix=".part",
            ) as temp_file:
                temp_name = temp_file.name
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    temp_file.write(chunk)
                    digest.update(chunk)
                    byte_count += len(chunk)
            os.replace(temp_name, target)
            temp_name = ""
        finally:
            response.close()
            if temp_name:
                Path(temp_name).unlink(missing_ok=True)

        return {
            "path": str(target.resolve()),
            "bytes": byte_count,
            "sha256": digest.hexdigest(),
            "job_path": job_path,
            "build_number": build_number,
            "artifact_path": artifact_path,
            "content_type": response.headers.get("Content-Type"),
        }

    def trigger_build(
        self,
        job_path: str,
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        path = self._job_path(job_path)
        data = self._build_parameters(parameters) if parameters is not None else None
        endpoint = "buildWithParameters" if parameters is not None else "build"
        response = self._request(
            "POST",
            f"{path}/{endpoint}",
            data=data,
            add_crumb=True,
            allow_redirects=False,
        )
        location = response.headers.get("Location")
        return {
            "accepted": response.status_code in {200, 201, 202, 302, 303},
            "status_code": response.status_code,
            "queue_url": location,
            "queue_id": self._queue_id(location),
            "job_path": job_path,
        }

    def stop_build(self, job_path: str, build_number: int) -> dict[str, Any]:
        path = f"{self._build_path(job_path, build_number)}/stop"
        response = self._request("POST", path, add_crumb=True, allow_redirects=False)
        return {
            "accepted": response.status_code in {200, 201, 202, 302, 303},
            "status_code": response.status_code,
            "job_path": job_path,
            "build_number": build_number,
        }

    def cancel_queue_item(self, queue_id: int) -> dict[str, Any]:
        if queue_id <= 0:
            raise ValueError("queue_id must be greater than 0")
        response = self._request(
            "POST",
            "/queue/cancelItem",
            params={"id": queue_id},
            add_crumb=True,
            allow_redirects=False,
        )
        return {
            "accepted": response.status_code in {200, 201, 202, 302, 303},
            "status_code": response.status_code,
            "queue_id": queue_id,
        }

    def _request(
        self,
        method: str,
        path: str,
        *,
        add_crumb: bool = False,
        retry_auth: bool = True,
        **kwargs: Any,
    ) -> requests.Response:
        self._ensure_authenticated()
        if add_crumb:
            headers = dict(kwargs.pop("headers", {}) or {})
            field, crumb = self._get_crumb()
            headers[field] = crumb
            kwargs["headers"] = headers

        response = self._raw_request(method, path, **kwargs)
        location = response.headers.get("Location") or ""
        auth_failed = response.status_code in {401, 403} or (
            response.is_redirect and "/login" in location
        )
        if auth_failed and retry_auth:
            response.close()
            self._authenticated = False
            self._crumb = None
            self.login()
            return self._request(
                method,
                path,
                add_crumb=add_crumb,
                retry_auth=False,
                **kwargs,
            )
        self._raise_for_status(response, method, path)
        return response

    def _get_crumb(self) -> tuple[str, str]:
        if self._crumb is None:
            response = self._request("GET", "/crumbIssuer/api/json", allow_redirects=False)
            payload = self._json(response, "/crumbIssuer/api/json")
            field = payload.get("crumbRequestField")
            crumb = payload.get("crumb")
            if not isinstance(field, str) or not field or not isinstance(crumb, str) or not crumb:
                raise RuntimeError("Jenkins crumb endpoint returned an invalid response.")
            self._crumb = (field, crumb)
        return self._crumb

    def _ensure_authenticated(self) -> None:
        if not self._authenticated:
            self.login()

    def _raw_request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        kwargs.setdefault("timeout", self.timeout_seconds)
        return self.session.request(method, f"{self.base_url}{path}", **kwargs)

    def _submit_form(
        self,
        base_url: str,
        form: dict[str, Any],
        data: dict[str, str] | None = None,
    ) -> requests.Response:
        action_url = urljoin(base_url, str(form.get("action") or ""))
        action = urlparse(action_url)
        expected = urlparse(self.base_url)
        if action.scheme not in {"http", "https"} or action.hostname != expected.hostname:
            raise RuntimeError("Jenkins login refused to submit credentials or SAML data to an untrusted host.")
        method = str(form.get("method") or "post").upper()
        if method != "POST":
            raise RuntimeError("Jenkins login returned an unsupported non-POST form.")
        return self.session.request(
            method,
            action_url,
            data=data if data is not None else self._form_data(form),
            timeout=self.timeout_seconds,
            allow_redirects=True,
        )

    @staticmethod
    def _parse_forms(payload: str) -> list[dict[str, Any]]:
        parser = _FormParser()
        parser.feed(payload)
        return parser.forms

    @classmethod
    def _find_form(cls, payload: str, input_name: str) -> dict[str, Any] | None:
        for form in cls._parse_forms(payload):
            if any(item.get("name") == input_name for item in form.get("inputs") or []):
                return form
        return None

    @classmethod
    def _find_login_form(cls, payload: str) -> dict[str, Any] | None:
        for form in cls._parse_forms(payload):
            names = {item.get("name") for item in form.get("inputs") or []}
            if {"username", "password"}.issubset(names):
                return form
        return None

    @staticmethod
    def _form_data(form: dict[str, Any], include_submit: bool = False) -> dict[str, str]:
        values: dict[str, str] = {}
        for item in form.get("inputs") or []:
            name = item.get("name")
            input_type = item.get("type")
            if not name or input_type in {"button", "file"}:
                continue
            if input_type == "submit" and not include_submit:
                continue
            values[str(name)] = str(item.get("value") or "")
        return values

    @staticmethod
    def _json(response: requests.Response, path: str) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError(f"Jenkins {path} returned invalid JSON.") from exc
        if not isinstance(payload, dict):
            raise RuntimeError(f"Jenkins {path} returned a non-object JSON response.")
        return payload

    @staticmethod
    def _raise_for_status(response: requests.Response, method: str, path: str) -> None:
        if not response.ok:
            raise RuntimeError(f"Jenkins {method} {path} failed: HTTP {response.status_code}.")

    @staticmethod
    def _bounded(value: int, name: str, maximum: int) -> int:
        if value < 1 or value > maximum:
            raise ValueError(f"{name} must be between 1 and {maximum}")
        return value

    @classmethod
    def _job_path(cls, job_path: str | None) -> str:
        if not job_path or "://" in job_path or job_path.startswith(("/", "\\")):
            raise ValueError("job_path must be a relative Jenkins job or folder path")
        segments = job_path.split("/")
        if any(not segment or segment in {".", ".."} or "\\" in segment for segment in segments):
            raise ValueError("job_path contains an invalid path segment")
        return "".join(f"/job/{quote(segment, safe='')}" for segment in segments)

    @classmethod
    def _build_path(cls, job_path: str, build_number: int) -> str:
        if build_number <= 0:
            raise ValueError("build_number must be greater than 0")
        return f"{cls._job_path(job_path)}/{build_number}"

    @staticmethod
    def _artifact_path(artifact_path: str) -> str:
        if (
            not artifact_path
            or "://" in artifact_path
            or artifact_path.startswith(("/", "\\"))
            or "\\" in artifact_path
        ):
            raise ValueError("artifact_path must be a relative Jenkins artifact path")
        segments = artifact_path.split("/")
        if any(not segment or segment in {".", ".."} for segment in segments):
            raise ValueError("artifact_path contains an invalid path segment")
        return "/".join(quote(segment, safe="") for segment in segments)

    def _download_target(
        self,
        artifact_path: str,
        output_path: str | None,
        output_dir: str | None,
    ) -> Path:
        if output_path and output_dir:
            raise ValueError("Use either output_path or output_dir, not both")
        if output_path:
            return Path(output_path).expanduser().resolve()
        directory = Path(output_dir or self.download_dir).expanduser().resolve()
        return directory / Path(artifact_path).name

    @staticmethod
    def _build_parameters(parameters: dict[str, Any]) -> dict[str, str]:
        converted: dict[str, str] = {}
        for name, value in parameters.items():
            if not isinstance(name, str) or not name:
                raise ValueError("Jenkins parameter names must be non-empty strings")
            if isinstance(value, bool):
                converted[name] = "true" if value else "false"
            elif isinstance(value, (str, int, float)):
                converted[name] = str(value)
            else:
                raise ValueError("Jenkins build parameters must be scalar values")
        return converted

    @staticmethod
    def _queue_id(location: str | None) -> int | None:
        if not location:
            return None
        segments = [segment for segment in urlparse(location).path.split("/") if segment]
        try:
            queue_index = segments.index("queue")
            if segments[queue_index + 1] != "item":
                return None
            return int(segments[queue_index + 2])
        except (ValueError, IndexError):
            return None
