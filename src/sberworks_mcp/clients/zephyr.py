from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import requests

from sberworks_mcp.clients.base import AtlassianClient


@dataclass(frozen=True)
class ZephyrTestStep:
    index: int
    id: int | None
    description: str
    action_text: str
    expected_result: str
    test_data: str | None = None
    attachment_refs: list[str] | None = None


class ZephyrClient(AtlassianClient):
    """Zephyr Scale/ATM client for the enterprise /rest/atm/latest namespace."""

    COMPLIANT_MESSAGE = "Zephyr integration uses the newer /rest/atm/latest API namespace."

    def __init__(self, base_url: str, session: requests.Session, timeout_seconds: int) -> None:
        super().__init__(base_url, session, timeout_seconds)

    def get_cycle(self, cycle_key: str) -> dict[str, Any]:
        payload = self.request("GET", f"/rest/atm/latest/testrun/{quote(cycle_key, safe='')}")
        return self._cycle_to_payload(payload)

    def get_cycle_case_keys(self, cycle_key: str) -> list[str]:
        payload = self.request("GET", f"/rest/atm/latest/testrun/{quote(cycle_key, safe='')}")
        return self.extract_cycle_case_keys(payload)

    def get_test_case(self, case_key: str) -> dict[str, Any]:
        payload = self.request("GET", f"/rest/atm/latest/testcase/{quote(case_key, safe='')}")
        return self._test_case_to_payload(payload)

    def get_test_cases(self, case_keys: list[str]) -> list[dict[str, Any]]:
        return [self.get_test_case(case_key) for case_key in case_keys]

    def get_test_case_details(self, case_key: str) -> dict[str, Any]:
        payload = self.request("GET", f"/rest/atm/latest/testcase/{quote(case_key, safe='')}")
        return self.parse_detailed_case(payload)

    def export_cycle_cases(self, cycle_key: str) -> dict[str, Any]:
        cycle_payload = self.request("GET", f"/rest/atm/latest/testrun/{quote(cycle_key, safe='')}")
        case_keys = self.extract_cycle_case_keys(cycle_payload)
        return {
            "cycle": self._cycle_to_payload(cycle_payload),
            "case_keys": case_keys,
            "cases": self.get_test_cases(case_keys),
        }

    def export_cycle_case_details(self, cycle_key: str) -> dict[str, Any]:
        export = self.export_cycle_cases(cycle_key)
        export["detailed_cases"] = [self.get_test_case_details(key) for key in export["case_keys"]]
        return export

    def probe_cycle_endpoints(self, project_id: int, cycle_key: str) -> list[dict[str, Any]]:
        testcase_key = self._first_cycle_case_key(cycle_key)
        urls = [
            ("cycle_page", "GET", f"{self.base_url}/secure/Tests.jspa#/testCycle/{cycle_key}"),
            ("testrun_latest", "GET", f"{self.base_url}/rest/atm/latest/testrun/{cycle_key}"),
        ]
        if testcase_key is not None:
            urls.append(("testcase_latest", "GET", f"{self.base_url}/rest/atm/latest/testcase/{testcase_key}"))
        return [self._probe(name, method, url, project_id=project_id) for name, method, url in urls]

    @classmethod
    def v1_prohibited_message(cls) -> str:
        return cls.COMPLIANT_MESSAGE

    @staticmethod
    def parse_detailed_case(payload: dict[str, Any]) -> dict[str, Any]:
        test_script = payload.get("testScript") or payload.get("test_script") or payload
        return {
            "id": int(payload.get("id", 0) or 0),
            "key": str(payload.get("key") or payload.get("issueKey") or ""),
            "project_id": int(payload.get("projectId", 0) or 0),
            "project_key": _optional_text(payload.get("projectKey") or payload.get("project_key")),
            "name": str(payload.get("name") or payload.get("title") or ""),
            "objective": _optional_text(payload.get("objective")),
            "precondition": _optional_text(payload.get("precondition")),
            "folder_name": _optional_text(_nested_name(payload.get("folder"), "fullName") or payload.get("folderName")),
            "status_name": _optional_text(_nested_name(payload.get("status"), "name") or payload.get("statusName")),
            "priority_name": _optional_text(_nested_name(payload.get("priority"), "name") or payload.get("priorityName")),
            "owner": _optional_text(payload.get("owner")),
            "labels": [str(item) for item in (payload.get("labels") or []) if str(item).strip()],
            "steps": [step_to_payload(step) for step in extract_steps(test_script)],
        }

    @staticmethod
    def extract_cycle_case_keys(payload: dict[str, Any]) -> list[str]:
        keys: list[str] = []
        for item in payload.get("items") or []:
            value = str(item.get("testCaseKey") or "").strip()
            if value and value not in keys:
                keys.append(value)
        return keys

    @staticmethod
    def extract_attachment_refs(value: str) -> list[str]:
        refs: list[str] = []
        for pattern in (r'src="([^"]+)"', r'href="([^"]+)"'):
            for match in re.findall(pattern, value or ""):
                ref = str(match).strip()
                if ref and ref not in refs:
                    refs.append(ref)
        return refs

    @staticmethod
    def body_preview(text: str, limit: int = 1200) -> str:
        compact = " ".join(text.split())
        return compact[:limit]

    def _cycle_to_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": int(payload.get("id", 0) or 0),
            "key": str(payload.get("key") or ""),
            "project_id": int(payload.get("projectId", 0) or 0),
            "project_key": _optional_text(payload.get("projectKey")),
            "issue_key": _optional_text(payload.get("issueKey")),
            "name": str(payload.get("name") or ""),
            "test_case_count": int(payload.get("testCaseCount", 0) or 0),
            "status_name": _optional_text(_nested_name(payload.get("status"), "name") or payload.get("statusName")),
            "folder_name": _optional_text(_nested_name(payload.get("folder"), "fullName") or payload.get("folderName")),
        }

    def _test_case_to_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": int(payload.get("id", 0) or 0),
            "key": str(payload.get("key") or ""),
            "project_id": int(payload.get("projectId", 0) or 0),
            "name": str(payload.get("name") or ""),
            "priority_id": int(payload["priorityId"]) if payload.get("priorityId") is not None else None,
            "status_id": int(payload["statusId"]) if payload.get("statusId") is not None else None,
            "owner": _optional_text(payload.get("owner")),
        }

    def _first_cycle_case_key(self, cycle_key: str) -> str | None:
        try:
            return next(iter(self.get_cycle_case_keys(cycle_key)), None)
        except Exception:
            return None

    def _probe(self, name: str, method: str, url: str, *, project_id: int) -> dict[str, Any]:
        try:
            response = self.session.request(method, url, timeout=self.timeout_seconds)
            return {
                "name": name,
                "method": method,
                "url": url,
                "project_id": project_id,
                "status_code": response.status_code,
                "content_type": response.headers.get("Content-Type"),
                "ok": response.ok,
                "body_preview": self.body_preview(response.text),
                "error": None,
            }
        except Exception as exc:
            return {
                "name": name,
                "method": method,
                "url": url,
                "project_id": project_id,
                "status_code": None,
                "content_type": None,
                "ok": False,
                "body_preview": "",
                "error": str(exc),
            }


def extract_steps(test_script: dict[str, Any]) -> list[ZephyrTestStep]:
    step_candidates = (test_script.get("stepByStepScript") or {}).get("steps") or test_script.get("steps") or []
    steps: list[ZephyrTestStep] = []
    for raw in step_candidates:
        test_data = str(raw.get("testData") or raw.get("test_data") or "") or None
        steps.append(
            ZephyrTestStep(
                index=int(raw.get("index", 0) or 0),
                id=int(raw["id"]) if raw.get("id") is not None else None,
                description=str(raw.get("description") or ""),
                action_text=str(raw.get("text") or raw.get("action_text") or raw.get("description") or ""),
                expected_result=str(raw.get("expectedResult") or raw.get("expected_result") or ""),
                test_data=test_data,
                attachment_refs=(
                    [str(item) for item in (raw.get("attachment_refs") or []) if str(item).strip()]
                    or ZephyrClient.extract_attachment_refs(test_data or "")
                ),
            )
        )
    return sorted(steps, key=lambda item: item.index)


def step_to_payload(step: ZephyrTestStep) -> dict[str, Any]:
    return {
        "index": step.index,
        "id": step.id,
        "description": step.description,
        "action_text": step.action_text,
        "expected_result": step.expected_result,
        "test_data": step.test_data,
        "attachment_refs": step.attachment_refs or [],
    }


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _nested_name(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return value
