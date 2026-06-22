"""
app.py
------
Local web UI for browsing and editing TestRail test cases,
and managing local case draft files before syncing to TestRail.

Run:   python app.py
Open:  http://localhost:5000

The CLI (cli.py) and sync_template.py continue to work independently.
"""

import glob
import json
import os
import re
import sys
import logging
from datetime import datetime, timezone

from flask import Flask, jsonify, render_template, request, session

sys.path.insert(0, os.path.dirname(__file__))
from testrail_client import TestrailClient
import requests as req_lib

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", os.urandom(24))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

DRAFTS_DIR = os.path.join(os.path.dirname(__file__), "case_drafts")
os.makedirs(DRAFTS_DIR, exist_ok=True)

PRIORITY_MAP = {"low": 1, "medium": 2, "high": 3, "critical": 4}
TYPE_MAP     = {"manual": 13, "functional": 6, "regression": 9,
                "automated": 3, "smoke & sanity": 11}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _client() -> TestrailClient:
    creds = session.get("creds")
    if not creds:
        raise RuntimeError("not_connected")
    return TestrailClient(
        base_url=creds["url"],
        user=creds["user"],
        api_key=creds["api_key"],
        project_id=creds.get("project_id", ""),
        suite_id=creds.get("suite_id", ""),
    )


def _err(msg: str, status: int = 400):
    return jsonify({"error": msg}), status


def _draft_path(filename: str) -> str:
    """Resolve and validate a draft filename (no path traversal)."""
    base = os.path.basename(filename)
    if base.endswith(".json"):
        base = base[:-5]
    safe = re.sub(r"[^a-zA-Z0-9_\-]", "_", base) + ".json"
    return os.path.join(DRAFTS_DIR, safe), safe


def _load_draft(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save_draft(path: str, draft: dict) -> None:
    if "meta" not in draft:
        draft["meta"] = {}
    draft["meta"]["updated_at"] = datetime.now(timezone.utc).isoformat()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(draft, f, indent=2, ensure_ascii=False)


def _sync_one(client: TestrailClient, draft: dict, idx: int) -> dict:
    """
    Sync a single case (by index) to TestRail.
    Mutates draft['cases'][idx] in place.
    Returns {"action": "created"|"updated", "testrail_id": int}.
    """
    meta = draft["meta"]
    case = draft["cases"][idx]

    # Per-case section takes priority over file-level section
    case_section_name = case.get("section_name") or meta.get("section_name")
    case_section_id   = case.get("section_id")   or meta.get("section_id")

    if not case_section_id:
        if not case_section_name:
            raise ValueError("No section specified for this case.")
        sec = client.get_section_by_name(case_section_name)
        if not sec:
            raise ValueError(f"Section '{case_section_name}' not found in TestRail.")
        case_section_id = sec["id"]
        # Cache back on the case (not meta) so each case tracks its own resolved id
        case["section_id"] = case_section_id

    section_id = case_section_id

    steps = TestrailClient.build_steps(
        [s.get("action", "") for s in case.get("steps", [])],
        [s.get("expected", "") for s in case.get("steps", [])],
    )
    _DIFF_NAMES = {"easy": 1, "medium": 2, "difficult": 3}
    difficulty  = case.get("difficulty")
    if difficulty is None:
        raise ValueError("Difficulty is required before syncing.")
    if isinstance(difficulty, str):
        difficulty = _DIFF_NAMES.get(difficulty.lower())
        if difficulty is None:
            raise ValueError(f"Unknown difficulty '{case['difficulty']}'. Use Easy, Medium, or Difficult.")
    difficulty = int(difficulty)
    if difficulty not in (1, 2, 3):
        raise ValueError(f"Difficulty must be 1 (Easy), 2 (Medium), or 3 (Difficult); got {difficulty}.")

    custom = {
        "custom_automated_status": 1,          # To Do
        "custom_automation_type":  4,          # Cucumber
        "custom_difficulty":       difficulty,
    }
    if case.get("tags"):
        custom["custom_case_cucumber_tags"] = case["tags"]
    if case.get("api_version"):
        custom["custom_case_api_version"] = case["api_version"]
    if "api_regression" in case:
        custom["custom_case_api_regression"] = case["api_regression"]

    refs = case.get("refs") or meta.get("pbi_url") or None

    if case.get("testrail_id"):
        result = client.update_case(
            case["testrail_id"],
            title=case["title"],
            type_id=TYPE_MAP.get(case.get("type", "manual").lower(), 13),
            priority_id=PRIORITY_MAP.get(case.get("priority", "medium").lower(), 2),
            refs=refs,
            steps=steps,
            custom_fields=custom,
        )
        action = "updated"
    else:
        result = client.create_case(
            section_id=section_id,
            title=case["title"],
            template_id=2,
            type_id=TYPE_MAP.get(case.get("type", "manual").lower(), 13),
            priority_id=PRIORITY_MAP.get(case.get("priority", "medium").lower(), 2),
            refs=refs,
            steps=steps,
            custom_fields=custom,
        )
        action = "created"

    case["testrail_id"] = result["id"]
    case["status"]      = "synced"
    return {"action": action, "testrail_id": result["id"], "title": case["title"]}


# ---------------------------------------------------------------------------
# Core routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/env-defaults")
def env_defaults():
    return jsonify({
        "url":        os.getenv("TESTRAIL_URL", ""),
        "user":       os.getenv("TESTRAIL_USER", ""),
        "api_key":    os.getenv("TESTRAIL_API_KEY", ""),
        "project_id": os.getenv("TESTRAIL_PROJECT_ID", ""),
        "suite_id":   os.getenv("TESTRAIL_SUITE_ID", ""),
    })


@app.route("/api/connect", methods=["POST"])
def connect():
    data = request.get_json(force=True)
    try:
        client = TestrailClient(
            base_url=data["url"],
            user=data["user"],
            api_key=data["api_key"],
            project_id=data.get("project_id", ""),
            suite_id=data.get("suite_id", ""),
        )
        client._get("get_projects")
        session["creds"] = data
        return jsonify({"ok": True})
    except req_lib.HTTPError as e:
        return _err(f"TestRail {e.response.status_code}: {e.response.text[:400]}")
    except Exception as e:
        return _err(str(e))


@app.route("/api/disconnect", methods=["POST"])
def disconnect():
    session.pop("creds", None)
    return jsonify({"ok": True})


@app.route("/api/sections")
def sections():
    try:
        return jsonify(_client().get_sections())
    except RuntimeError:
        return _err("not_connected", 401)
    except req_lib.HTTPError as e:
        return _err(e.response.text, e.response.status_code)


@app.route("/api/cases")
def cases():
    section_id = request.args.get("section_id", type=int)
    try:
        return jsonify(_client().get_cases(section_id=section_id))
    except RuntimeError:
        return _err("not_connected", 401)
    except req_lib.HTTPError as e:
        return _err(e.response.text, e.response.status_code)


@app.route("/api/case/<int:case_id>")
def get_case(case_id):
    try:
        return jsonify(_client().get_case(case_id))
    except RuntimeError:
        return _err("not_connected", 401)
    except req_lib.HTTPError as e:
        return _err(e.response.text, e.response.status_code)


@app.route("/api/case/<int:case_id>", methods=["PUT"])
def update_case(case_id):
    data = request.get_json(force=True)
    try:
        client   = _client()
        steps    = data.pop("custom_steps_separated", None)
        preconds = data.pop("custom_preconds", None)
        title    = data.pop("title", None)
        type_id  = data.pop("type_id", None)
        priority = data.pop("priority_id", None)
        estimate = data.pop("estimate", None)
        refs     = data.pop("refs", None)
        custom   = {k: v for k, v in data.items() if k.startswith("custom_")}
        result   = client.update_case(
            case_id, title=title, type_id=type_id, priority_id=priority,
            estimate=estimate, refs=refs, preconditions=preconds,
            steps=steps, custom_fields=custom or None,
        )
        return jsonify(result)
    except RuntimeError:
        return _err("not_connected", 401)
    except req_lib.HTTPError as e:
        return _err(e.response.text, e.response.status_code)
    except Exception as e:
        return _err(str(e))


# ---------------------------------------------------------------------------
# Draft routes  — /api/drafts/*
# ---------------------------------------------------------------------------

@app.route("/api/drafts")
def list_drafts():
    files = []
    for path in sorted(glob.glob(os.path.join(DRAFTS_DIR, "*.json"))):
        fname = os.path.basename(path)
        try:
            d     = _load_draft(path)
            meta  = d.get("meta", {})
            cases = d.get("cases", [])
            files.append({
                "filename":     fname,
                "section_name": meta.get("section_name", ""),
                "pbi_url":      meta.get("pbi_url", ""),
                "updated_at":   meta.get("updated_at", ""),
                "case_count":   len(cases),
                "synced_count": sum(1 for c in cases if c.get("testrail_id")),
            })
        except Exception:
            files.append({"filename": fname, "case_count": 0, "synced_count": 0})
    return jsonify(files)


@app.route("/api/drafts", methods=["POST"])
def create_draft():
    data     = request.get_json(force=True)
    path, fn = _draft_path(data.get("name", "draft"))
    if os.path.exists(path):
        return _err(f"'{fn}' already exists.")
    draft = {
        "meta": {
            "section_name": data.get("section_name", ""),
            "section_id":   data.get("section_id"),
            "pbi_url":      data.get("pbi_url", ""),
            "created_at":   datetime.now(timezone.utc).isoformat(),
            "updated_at":   datetime.now(timezone.utc).isoformat(),
        },
        "cases": [],
    }
    _save_draft(path, draft)
    return jsonify({"filename": fn, **draft})


@app.route("/api/drafts/<filename>")
def get_draft(filename):
    path, _ = _draft_path(filename)
    if not os.path.exists(path):
        return _err("Draft not found.", 404)
    return jsonify(_load_draft(path))


@app.route("/api/drafts/<filename>", methods=["PUT"])
def update_draft(filename):
    path, _ = _draft_path(filename)
    if not os.path.exists(path):
        return _err("Draft not found.", 404)
    draft = request.get_json(force=True)
    _save_draft(path, draft)
    return jsonify(draft)


@app.route("/api/drafts/<filename>", methods=["DELETE"])
def delete_draft(filename):
    path, _ = _draft_path(filename)
    if os.path.exists(path):
        os.remove(path)
    return jsonify({"ok": True})


@app.route("/api/drafts/<filename>/sync/<int:idx>", methods=["POST"])
def sync_one(filename, idx):
    path, _ = _draft_path(filename)
    if not os.path.exists(path):
        return _err("Draft not found.", 404)
    try:
        client = _client()
    except RuntimeError:
        return _err("not_connected", 401)

    draft = _load_draft(path)
    if idx >= len(draft["cases"]):
        return _err("Case index out of range.", 400)
    try:
        result = _sync_one(client, draft, idx)
        _save_draft(path, draft)
        return jsonify({"ok": True, "draft": draft, **result})
    except req_lib.HTTPError as e:
        return _err(e.response.text, e.response.status_code)
    except Exception as e:
        return _err(str(e))


@app.route("/api/drafts/from-cases", methods=["POST"])
def draft_from_cases():
    data     = request.get_json(force=True)
    case_ids = data.get("case_ids", [])
    name     = data.get("name", "imported-cases")
    pbi_url  = data.get("pbi_url", "")
    section_name_override = data.get("section_name", "")

    if not case_ids:
        return _err("No case ids provided.")

    try:
        client = _client()
    except RuntimeError:
        return _err("not_connected", 401)

    _PRIORITY_INV = {1: "Low", 2: "Medium", 3: "High", 4: "Critical"}
    _TYPE_INV     = {13: "Manual", 6: "Functional", 9: "Regression",
                     3: "Automated", 11: "Smoke & Sanity"}

    cases = []
    for cid in case_ids:
        try:
            c = client.get_case(int(cid))
        except req_lib.HTTPError as e:
            return _err(f"Error fetching C{cid}: {e.response.text[:200]}", e.response.status_code)

        raw_steps = c.get("custom_steps_separated") or []
        steps = [
            {"action": s.get("content", ""), "expected": s.get("expected", "")}
            for s in raw_steps
        ]
        preconds = re.sub(r"<[^>]+>", "", c.get("custom_preconds") or "").strip()

        cases.append({
            "title":         c.get("title", ""),
            "priority":      _PRIORITY_INV.get(c.get("priority_id"), "Medium"),
            "type":          _TYPE_INV.get(c.get("type_id"), "Manual"),
            "difficulty":    c.get("custom_difficulty"),
            "section_id":    c.get("section_id"),
            "section_name":  section_name_override or "",
            "steps":         steps,
            "tags":          c.get("custom_case_cucumber_tags", ""),
            "api_version":   c.get("custom_case_api_version", ""),
            "api_regression": c.get("custom_case_api_regression", False),
            "refs":          c.get("refs", ""),
            "preconditions": preconds,
            "testrail_id":   c["id"],
            "status":        "synced",
        })

    first_section_id = cases[0]["section_id"] if cases else None
    path, fn = _draft_path(name)
    if os.path.exists(path):
        return _err(f"'{fn}' already exists.")

    draft = {
        "meta": {
            "section_name": section_name_override,
            "section_id":   first_section_id,
            "pbi_url":      pbi_url,
            "created_at":   datetime.now(timezone.utc).isoformat(),
            "updated_at":   datetime.now(timezone.utc).isoformat(),
        },
        "cases": cases,
    }
    _save_draft(path, draft)
    return jsonify({"filename": fn, **draft})


@app.route("/api/drafts/<filename>/sync", methods=["POST"])
def sync_all(filename):
    path, _ = _draft_path(filename)
    if not os.path.exists(path):
        return _err("Draft not found.", 404)
    try:
        client = _client()
    except RuntimeError:
        return _err("not_connected", 401)

    draft   = _load_draft(path)
    results = []
    errors  = []
    for i in range(len(draft["cases"])):
        try:
            r = _sync_one(client, draft, i)
            results.append({"idx": i, "ok": True, **r})
        except req_lib.HTTPError as e:
            msg = e.response.text[:300]
            results.append({"idx": i, "ok": False, "title": draft["cases"][i]["title"], "error": msg})
            errors.append(msg)
        except Exception as e:
            results.append({"idx": i, "ok": False, "title": draft["cases"][i]["title"], "error": str(e)})
            errors.append(str(e))

    _save_draft(path, draft)
    return jsonify({"results": results, "errors": errors, "draft": draft})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"\n  TestRail Client UI  ->  http://localhost:{port}\n")
    app.run(debug=True, port=port)
