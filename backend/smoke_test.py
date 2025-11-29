"""Quick smoke test for the CognitoForge Labs API."""

from __future__ import annotations

import json
import sys
import uuid
from typing import Any, Dict

import requests

API_ROOT = "http://127.0.0.1:8000"


def pretty_print(title: str, data: Dict[str, Any]) -> None:
    """Print JSON responses in a readable format."""

    print(f"\n=== {title} ===")
    print(json.dumps(data, indent=2))


def main() -> int:
    repo_id = f"smoke_{uuid.uuid4().hex[:8]}"
    try:
        upload_resp = requests.post(
            f"{API_ROOT}/upload_repo",
            json={"repo_id": repo_id, "repo_url": "https://github.com/example/repo"},
            timeout=10,
        )
        upload_resp.raise_for_status()
        pretty_print("Upload", upload_resp.json())

        simulate_resp = requests.post(
            f"{API_ROOT}/simulate_attack",
            json={"repo_id": repo_id},
            timeout=15,
        )
        simulate_resp.raise_for_status()
        simulate_payload = simulate_resp.json()
        pretty_print("Simulate", simulate_payload)

        latest_report = requests.get(
            f"{API_ROOT}/reports/{repo_id}/latest",
            timeout=10,
        )
        latest_report.raise_for_status()
        pretty_print("Latest Report", latest_report.json())

        return 0
    except requests.RequestException as exc:
        print(f"Smoke test failed: {exc}", file=sys.stderr)
        if exc.response is not None:
            print(f"Response: {exc.response.text}", file=sys.stderr)
        return 1


if __name__ == "__main__":
     raise SystemExit(main())
