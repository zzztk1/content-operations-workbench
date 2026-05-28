from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "benchmarks" / "latest_deployment_surface_report.json"


def fetch_json(url: str) -> tuple[int, Dict[str, Any]]:
    req = Request(url, headers={"User-Agent": "media-agent-deploy-check/1.0"})
    with urlopen(req, timeout=20) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        body = resp.read().decode(charset)
        return resp.status, json.loads(body)


def fetch_status(url: str) -> int:
    req = Request(url, headers={"User-Agent": "media-agent-deploy-check/1.0"})
    with urlopen(req, timeout=20) as resp:
        return resp.status


def fetch_text(url: str) -> tuple[int, str]:
    req = Request(url, headers={"User-Agent": "media-agent-deploy-check/1.0"})
    with urlopen(req, timeout=20) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        body = resp.read().decode(charset)
        return resp.status, body


def main() -> int:
    base_url = os.getenv("BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    report: Dict[str, Any] = {
        "base_url": base_url,
        "all_passed": False,
        "checks": {},
    }

    try:
        health_status, health = fetch_json(f"{base_url}/health")
        docs_status = fetch_status(f"{base_url}/docs")
        demo_status, demo_html = fetch_text(f"{base_url}/demo")
        studio_status, studio_html = fetch_text(f"{base_url}/studio")
        caps_status, caps = fetch_json(f"{base_url}/v2/workflow-capabilities")

        report["checks"]["health"] = {
            "passed": health_status == 200 and health.get("status") in {"ok", "degraded"},
            "status_code": health_status,
            "status": health.get("status"),
            "postgres_connectivity": health.get("checks", {}).get("postgres_connectivity"),
            "llm_model": health.get("llm_model"),
            "image_model": health.get("image_model"),
            "vision_model": health.get("vision_model"),
        }
        report["checks"]["docs"] = {
            "passed": docs_status == 200,
            "status_code": docs_status,
        }
        report["checks"]["demo"] = {
            "passed": demo_status == 200 and '<div id="root"></div>' in demo_html,
            "status_code": demo_status,
        }
        report["checks"]["studio"] = {
            "passed": studio_status == 200 and '<div id="root"></div>' in studio_html,
            "status_code": studio_status,
        }
        report["checks"]["workflow_capabilities"] = {
            "passed": caps_status == 200
            and bool(caps.get("run_modes"))
            and bool(caps.get("export_formats")),
            "status_code": caps_status,
            "run_modes": list((caps.get("run_modes") or {}).keys()),
            "export_formats": list((caps.get("export_formats") or {}).keys()),
        }
        report["all_passed"] = all(item.get("passed") for item in report["checks"].values())
    except HTTPError as exc:
        report["error"] = f"HTTPError {exc.code}: {exc.reason}"
    except URLError as exc:
        report["error"] = f"URLError: {exc.reason}"
    except Exception as exc:  # noqa: BLE001
        report["error"] = str(exc)

    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
