"""
sync_template.py
----------------
Template for syncing test cases to TestRail.

Usage
-----
1. Fill in SECTION_NAME and PBI_URL below.
2. Define your test cases in the TEST_CASES list.
3. Run:  python sync_template.py

The script will CREATE new cases and UPDATE existing ones (matched by title).
If more than 5 cases would be created, you will be prompted to confirm.
"""

import sys
import requests

from testrail_client import TestrailClient

# ---------------------------------------------------------------------------
# Configuration — edit these before running
# ---------------------------------------------------------------------------

SECTION_NAME = "Transfers"   # Must match an existing section name in TestRail

PBI_URL = "https://dev.azure.com/yourorg/yourproject/_workitems/edit/XXXXX"

# ---------------------------------------------------------------------------
# Test cases to sync
#
# Each entry is a dict with:
#   title         (str, required)   — test case title
#   priority      (str)             — "Low" | "Medium" | "High" | "Critical"
#   type          (str)             — "Manual" | "Functional" | "Regression" | ...
#   steps         (list of dicts)   — [{"action": "...", "expected": "..."}, ...]
#   tags          (str, optional)   — space-separated Cucumber tags e.g. "@smoke @transfers"
#   api_version   (str, optional)   — e.g. "1.36"
#   api_regression (bool, optional) — True / False
# ---------------------------------------------------------------------------

TEST_CASES = [
    {
        "title": "POST /endpoint — happy path",
        "priority": "High",
        "type": "Manual",
        "steps": [
            {
                "action": "Send POST /endpoint with a valid payload",
                "expected": "HTTP 201; response body contains the expected fields",
            },
            {
                "action": "Verify the created resource can be retrieved",
                "expected": "GET /endpoint/{id} returns the same data",
            },
        ],
        "tags": "@smoke @endpoint",
        "api_version": "",
        "api_regression": False,
    },
    {
        "title": "POST /endpoint — missing required field returns 400",
        "priority": "Medium",
        "type": "Manual",
        "steps": [
            {
                "action": "Send POST /endpoint without the required field",
                "expected": "HTTP 400; error message identifies the missing field",
            },
        ],
        "tags": "@endpoint @negative",
        "api_version": "",
        "api_regression": False,
    },
    # Add more cases here ...
]

# ---------------------------------------------------------------------------
# Sync logic — no edits needed below this line
# ---------------------------------------------------------------------------

PRIORITY_MAP = {"low": 1, "medium": 2, "high": 3, "critical": 4}
TYPE_MAP = {
    "manual": 13, "functional": 6, "regression": 9,
    "automated": 3, "smoke & sanity": 11,
}

GUARD_THRESHOLD = 5   # Prompt user if more than this many cases would be created


def main() -> None:
    client = TestrailClient()

    section = client.get_section_by_name(SECTION_NAME)
    if not section:
        print(f"ERROR: Section '{SECTION_NAME}' not found. Run cli.py sections to list available sections.")
        sys.exit(1)

    section_id = section["id"]
    print(f"\nSection  : {SECTION_NAME} (id={section_id})")
    print(f"PBI ref  : {PBI_URL}")
    print(f"Cases    : {len(TEST_CASES)}\n")

    existing = {
        c["title"].strip().lower(): c
        for c in client.get_cases(section_id=section_id)
    }

    creates = [tc for tc in TEST_CASES if tc["title"].strip().lower() not in existing]
    updates = [tc for tc in TEST_CASES if tc["title"].strip().lower() in existing]

    if len(creates) > GUARD_THRESHOLD:
        answer = input(
            f"About to CREATE {len(creates)} new cases. Continue? [y/N] "
        ).strip().lower()
        if answer != "y":
            print("Aborted.")
            sys.exit(0)

    results, errors = [], []

    for tc in creates:
        steps = TestrailClient.build_steps(
            [s["action"] for s in tc["steps"]],
            [s["expected"] for s in tc["steps"]],
        )
        custom = {
            "custom_automated_status": 1,   # To Do
            "custom_automation_type": 4,    # Cucumber
            "custom_difficulty": 2,         # Medium (required field)
        }
        if tc.get("tags"):
            custom["custom_case_cucumber_tags"] = tc["tags"]
        if tc.get("api_version"):
            custom["custom_case_api_version"] = tc["api_version"]
        if "api_regression" in tc:
            custom["custom_case_api_regression"] = tc["api_regression"]

        try:
            case = client.create_case(
                section_id=section_id,
                title=tc["title"],
                template_id=2,
                type_id=TYPE_MAP.get(tc.get("type", "manual").lower(), 13),
                priority_id=PRIORITY_MAP.get(tc.get("priority", "medium").lower(), 2),
                refs=PBI_URL or None,
                steps=steps,
                custom_fields=custom,
            )
            cid = f"C{case['id']}"
            print(f"  CREATE  {cid:<10}  {tc['title'][:70]}")
            results.append({"action": "CREATE", "id": cid, "title": tc["title"], "ok": True})
        except requests.HTTPError as e:
            msg = f"{e.response.status_code} — {e.response.text[:300]}"
            print(f"  ERROR   {'':10}  {tc['title'][:70]}\n           {msg}")
            results.append({"action": "CREATE", "id": "—", "title": tc["title"], "ok": False, "error": msg})
            errors.append(tc["title"])

    for tc in updates:
        existing_case = existing[tc["title"].strip().lower()]
        steps = TestrailClient.build_steps(
            [s["action"] for s in tc["steps"]],
            [s["expected"] for s in tc["steps"]],
        )
        try:
            case = client.update_case(
                existing_case["id"],
                steps=steps,
                refs=PBI_URL or None,
            )
            cid = f"C{case['id']}"
            print(f"  UPDATE  {cid:<10}  {tc['title'][:70]}")
            results.append({"action": "UPDATE", "id": cid, "title": tc["title"], "ok": True})
        except requests.HTTPError as e:
            msg = f"{e.response.status_code} — {e.response.text[:300]}"
            print(f"  ERROR   {'':10}  {tc['title'][:70]}\n           {msg}")
            results.append({"action": "UPDATE", "id": "—", "title": tc["title"], "ok": False, "error": msg})
            errors.append(tc["title"])

    ok_count  = sum(1 for r in results if r["ok"])
    err_count = len(errors)
    print(f"\nDone: {ok_count} synced, {err_count} errors.")
    if errors:
        print("Failed cases:")
        for t in errors:
            print(f"  - {t}")


if __name__ == "__main__":
    main()
