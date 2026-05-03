from __future__ import annotations

import argparse
import json
from pathlib import Path

import httpx


def run_case(payload_path: Path) -> dict:
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    method = payload.get("method", "GET").upper()
    url = payload.get("url", "https://example.com")
    headers = payload.get("headers", {})
    body = payload.get("json")

    with httpx.Client(timeout=15.0) as client:
        response = client.request(method, url, headers=headers, json=body)

    report = {
        "runId": payload.get("runId"),
        "runner": "api",
        "status": "passed" if response.status_code < 400 else "failed",
        "request": {"method": method, "url": url},
        "response": {
            "statusCode": response.status_code,
            "bodyPreview": response.text[:500],
        },
    }
    report_path = payload_path.with_name(f"{payload.get('runId', 'run')}-api-report.json")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run an API test case payload.")
    parser.add_argument("payload", type=Path, help="Path to the JSON payload file.")
    args = parser.parse_args()
    result = run_case(args.payload)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
