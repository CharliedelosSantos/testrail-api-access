"""
testrail_client.py
------------------
TestRail API client for the ReadyRemit QA project.

Supports:
  - Retrieving sections from a suite
  - Retrieving test cases (all or by section)
  - Creating new test cases
  - Updating existing test cases

Authentication is read from a .env file (see .env.example).

Field reference is based on the Master suite export (artemis_cadmus_plutus___coreapi.csv).
Custom field names follow the TestRail internal key convention (custom_<fieldname>).

Usage examples at the bottom of this file under  if __name__ == "__main__".
"""

import os
import json
import logging
from typing import Any, Optional

import requests
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Load credentials from .env
# ---------------------------------------------------------------------------
load_dotenv()

TESTRAIL_URL      = os.getenv("TESTRAIL_URL", "").rstrip("/")   # e.g. https://yourorg.testrail.io
TESTRAIL_USER     = os.getenv("TESTRAIL_USER", "")              # e-mail address
TESTRAIL_API_KEY  = os.getenv("TESTRAIL_API_KEY", "")           # API key (not password)
TESTRAIL_PROJECT_ID = os.getenv("TESTRAIL_PROJECT_ID", "")      # numeric project id
TESTRAIL_SUITE_ID   = os.getenv("TESTRAIL_SUITE_ID", "")        # numeric suite id  (S2 → "2")

# ---------------------------------------------------------------------------
# Field mapping helpers
# ---------------------------------------------------------------------------

# Priority name → TestRail priority_id
PRIORITY_MAP: dict[str, int] = {
    "Critical": 4,
    "High":     3,
    "Medium":   2,
    "Low":      1,
}

# Type name → TestRail type_id
# Verified via get_case_types on bwp.testrail.io (project 1)
TYPE_MAP: dict[str, int] = {
    "acceptance":    1,
    "accessibility": 2,
    "automated":     3,
    "compatibility": 4,
    "destructive":   5,
    "functional":    6,
    "other":         7,
    "performance":   8,
    "regression":    9,
    "security":      10,
    "smoke & sanity":11,
    "usability":     12,
    "manual":        13,   # ← verified: Manual = 13 in this instance
}

# custom_automated_status dropdown option ids
# Verified via get_case_fields on bwp.testrail.io
AUTOMATED_STATUS_MAP: dict[str, int] = {
    "to do":                1,
    "in progress":          2,
    "done":                 3,
    "can't automate":       4,
    "needs info":           5,
    "on hold":              6,
    "automation candidate": 7,
}

# custom_automation_type dropdown option ids
# Verified via get_case_fields on bwp.testrail.io
AUTOMATION_TYPE_MAP: dict[str, int] = {
    "none":              0,
    "postman":           1,
    "postman + query":   2,
    "reports automation":3,
    "cucumber":          4,
}

# custom_difficulty dropdown option ids
DIFFICULTY_MAP: dict[str, int] = {
    "Easy":      1,
    "Medium":    2,
    "Difficult": 3,
}

# custom_automation_status dropdown option ids (separate from automated_status)
AUTOMATION_STATUS_MAP: dict[str, int] = {
    "manual":    1,
    "automated": 2,
}

# Template name → TestRail template_id
# Verified via get_templates on bwp.testrail.io (project 1)
TEMPLATE_MAP: dict[str, int] = {
    "test case (text)":        1,
    "test case (steps)":       2,
    "exploratory session":     3,
    "behaviour driven development": 4,
}


def _priority_id(name: str) -> int:
    return PRIORITY_MAP.get(name.strip().lower(), 2)   # default Medium


def _type_id(name: str) -> int:
    return TYPE_MAP.get(name.strip().lower(), 13)       # default Manual (=13)


def _template_id(name: str) -> int:
    return TEMPLATE_MAP.get(name.strip().lower(), 2)    # default Steps


def _automated_status_id(name: str) -> Optional[int]:
    return AUTOMATED_STATUS_MAP.get(name.strip().lower())


def _automation_type_id(name: str) -> Optional[int]:
    return AUTOMATION_TYPE_MAP.get(name.strip().lower())


# ---------------------------------------------------------------------------
# Core client
# ---------------------------------------------------------------------------

class TestrailClient:
    """
    Thin wrapper around the TestRail REST API v2.

    All calls raise requests.HTTPError on non-2xx responses.
    """

    def __init__(
        self,
        base_url: str = TESTRAIL_URL,
        user: str = TESTRAIL_USER,
        api_key: str = TESTRAIL_API_KEY,
        project_id: str | int = TESTRAIL_PROJECT_ID,
        suite_id: str | int = TESTRAIL_SUITE_ID,
    ) -> None:
        if not all([base_url, user, api_key]):
            raise ValueError(
                "TESTRAIL_URL, TESTRAIL_USER and TESTRAIL_API_KEY must all be set "
                "(check your .env file)."
            )
        self.base_url   = base_url.rstrip("/")
        self.project_id = int(project_id) if project_id else None
        self.suite_id   = int(suite_id)   if suite_id   else None
        self._session   = requests.Session()
        self._session.auth    = (user, api_key)
        self._session.headers.update({"Content-Type": "application/json"})
        self._section_cache: dict = {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _url(self, endpoint: str) -> str:
        return f"{self.base_url}/index.php?/api/v2/{endpoint.lstrip('/')}"

    def _get(self, endpoint: str, params: Optional[dict] = None) -> Any:
        url = self._url(endpoint)
        log.debug("GET %s  params=%s", url, params)
        resp = self._session.get(url, params=params)
        resp.raise_for_status()
        return resp.json()

    def _post(self, endpoint: str, payload: dict) -> Any:
        url = self._url(endpoint)
        log.debug("POST %s  body=%s", url, json.dumps(payload)[:200])
        resp = self._session.post(url, json=payload)
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Sections
    # ------------------------------------------------------------------

    def get_sections(
        self,
        project_id: Optional[int] = None,
        suite_id: Optional[int] = None,
    ) -> list[dict]:
        """
        Return all sections for the given project / suite.

        Falls back to the instance-level project_id / suite_id when not supplied.

        Each section dict contains at minimum:
            id, name, depth, parent_id, suite_id, description
        """
        pid = project_id or self.project_id
        sid = suite_id   or self.suite_id
        if not pid:
            raise ValueError("project_id is required.")

        params = {}
        if sid:
            params["suite_id"] = sid

        data = self._get(f"get_sections/{pid}", params=params)
        sections = data.get("sections", data) if isinstance(data, dict) else data
        log.info("Retrieved %d sections for project %s suite %s", len(sections), pid, sid)
        return sections

    def get_section(self, section_id: int) -> dict:
        """Return a single section by id."""
        return self._get(f"get_section/{section_id}")

    def get_section_by_name(
        self,
        name: str,
        project_id: Optional[int] = None,
        suite_id: Optional[int] = None,
    ) -> Optional[dict]:
        """
        Find and return the first section whose name matches *name* (case-insensitive).
        Returns None when not found.
        Uses the in-memory sections cache to avoid repeated API calls.
        """
        for section in self._cached_sections(project_id, suite_id):
            if section.get("name", "").strip().lower() == name.strip().lower():
                return section
        return None

    # ------------------------------------------------------------------
    # Section cache
    # ------------------------------------------------------------------

    def _cached_sections(
        self,
        project_id: Optional[int] = None,
        suite_id: Optional[int] = None,
    ) -> list[dict]:
        """
        Return sections, fetching from TestRail only on the first call per
        (project_id, suite_id) pair.  Subsequent calls within the same client
        instance return the cached list.

        Use ``invalidate_section_cache()`` to force a fresh fetch.
        """
        pid = project_id or self.project_id
        sid = suite_id   or self.suite_id
        key = (pid, sid)
        if key not in self._section_cache:
            self._section_cache[key] = self.get_sections(project_id, suite_id)
        return self._section_cache[key]

    def invalidate_section_cache(self) -> None:
        """Clear the cached sections so the next lookup fetches fresh data."""
        self._section_cache.clear()
        log.debug("Section cache cleared.")

    # ------------------------------------------------------------------
    # Section lookup helpers
    # ------------------------------------------------------------------

    def search_sections(
        self,
        query: str,
        project_id: Optional[int] = None,
        suite_id: Optional[int] = None,
    ) -> list[dict]:
        """
        Return all sections whose name contains *query* (case-insensitive partial match).

        Example
        -------
        client.search_sections("transfer")
        # → [{"id": 330, "name": "Transfers", ...}, {"id": 331, "name": "Transfer details", ...}]
        """
        q = query.strip().lower()
        return [
            s for s in self._cached_sections(project_id, suite_id)
            if q in s.get("name", "").lower()
        ]

    def get_section_ancestors(
        self,
        section_id: int,
        project_id: Optional[int] = None,
        suite_id: Optional[int] = None,
    ) -> list[dict]:
        """
        Return the ancestor chain for *section_id* as a list ordered from the
        root section down to (but not including) *section_id* itself.

        Returns an empty list for top-level sections.

        Example
        -------
        client.get_section_ancestors(330)
        # → [{"id": 32, "name": "UI Manual Tests", ...},
        #    {"id": 283, "name": "ReadyRemit - Admin Portal", ...}]
        """
        by_id = {s["id"]: s for s in self._cached_sections(project_id, suite_id)}
        target = by_id.get(section_id)
        if target is None:
            return []
        chain: list[dict] = []
        current = target
        while current.get("parent_id") is not None:
            parent = by_id.get(current["parent_id"])
            if parent is None:
                break
            chain.append(parent)
            current = parent
        return list(reversed(chain))

    def get_section_path(
        self,
        section_id: int,
        project_id: Optional[int] = None,
        suite_id: Optional[int] = None,
    ) -> str:
        """
        Return a human-readable breadcrumb path for *section_id*.

        Example
        -------
        client.get_section_path(330)
        # → "UI Manual Tests > ReadyRemit - Admin Portal > Transfers"
        """
        by_id = {s["id"]: s for s in self._cached_sections(project_id, suite_id)}
        target = by_id.get(section_id)
        if target is None:
            return f"<section {section_id} not found>"
        parts = [target["name"]]
        current = target
        while current.get("parent_id") is not None:
            parent = by_id.get(current["parent_id"])
            if parent is None:
                break
            parts.append(parent["name"])
            current = parent
        return " > ".join(reversed(parts))

    def get_section_children(
        self,
        section_id: int,
        project_id: Optional[int] = None,
        suite_id: Optional[int] = None,
    ) -> list[dict]:
        """
        Return the direct children of *section_id* (one level deep only).

        Example
        -------
        client.get_section_children(283)
        # → [{"id": 330, "name": "Transfers", ...}, ...]
        """
        return [
            s for s in self._cached_sections(project_id, suite_id)
            if s.get("parent_id") == section_id
        ]

    # ------------------------------------------------------------------
    # Test Cases  –  read
    # ------------------------------------------------------------------

    def get_cases(
        self,
        project_id: Optional[int] = None,
        suite_id: Optional[int] = None,
        section_id: Optional[int] = None,
        filters: Optional[dict] = None,
    ) -> list[dict]:
        """
        Return test cases for the project/suite, optionally scoped to a section.

        Optional *filters* dict is forwarded as query params (e.g. {"type_id": 1}).
        TestRail paginates at 250 items; this method follows the cursor automatically.

        Commonly used filter keys:
            type_id, priority_id, created_by, updated_after, updated_before
        """
        pid = project_id or self.project_id
        sid = suite_id   or self.suite_id
        if not pid:
            raise ValueError("project_id is required.")

        params: dict = filters.copy() if filters else {}
        if sid:
            params["suite_id"] = sid
        if section_id:
            params["section_id"] = section_id

        cases: list[dict] = []
        offset = 0
        limit  = 250

        while True:
            params.update({"limit": limit, "offset": offset})
            data = self._get(f"get_cases/{pid}", params=params)
            page = data.get("cases", data) if isinstance(data, dict) else data
            cases.extend(page)
            # Follow pagination
            if isinstance(data, dict) and data.get("_links", {}).get("next"):
                offset += limit
            else:
                break

        log.info(
            "Retrieved %d cases for project %s suite %s section %s",
            len(cases), pid, sid, section_id,
        )
        return cases

    def get_case(self, case_id: int) -> dict:
        """Return a single test case by numeric id (without the C prefix)."""
        return self._get(f"get_case/{case_id}")

    # ------------------------------------------------------------------
    # Test Cases  –  lookup helpers
    # ------------------------------------------------------------------

    def find_cases_by_title(
        self,
        title: str,
        section_id: Optional[int] = None,
        *,
        exact: bool = False,
        project_id: Optional[int] = None,
        suite_id: Optional[int] = None,
        filters: Optional[dict] = None,
    ) -> list[dict]:
        """
        Search test cases by title.

        Parameters
        ----------
        title      : Search string.  Partial match by default; set ``exact=True``
                     for a case-insensitive exact match.
        section_id : Scope to a single section (optional).
        exact      : When True, the title must match exactly (case-insensitive).
        filters    : Extra query params forwarded to ``get_cases()``.

        Example
        -------
        client.find_cases_by_title("POST /transfers")
        # → all cases whose title contains "POST /transfers"

        client.find_cases_by_title("POST /transfers – happy path", exact=True)
        # → exact-match only
        """
        cases = self.get_cases(project_id, suite_id, section_id, filters)
        t = title.strip().lower()
        if exact:
            return [c for c in cases if c.get("title", "").strip().lower() == t]
        return [c for c in cases if t in c.get("title", "").lower()]

    def get_case_summary(self, case_id: int) -> dict:
        """
        Return a human-readable summary dict for *case_id*.

        Numeric ids are decoded to their string labels using the module-level
        mapping constants, so the output is immediately readable without
        cross-referencing the field tables.

        Keys returned
        -------------
        id, title, section_id, section_path, template, type, priority,
        refs, preconditions, steps, bdd_scenario, automated_status,
        automation_type, cucumber_tags, api_version, api_regression.
        """
        c = self.get_case(case_id)

        raw_steps = c.get("custom_steps_separated") or []
        steps = [
            {"step": s.get("content", ""), "expected": s.get("expected", "")}
            for s in raw_steps
        ]

        section_id = c.get("section_id")
        path = self.get_section_path(section_id) if section_id else ""

        def _reverse_map(mapping: dict, val: Any) -> Any:
            return next((k for k, v in mapping.items() if v == val), val)

        return {
            "id":               f"C{c['id']}",
            "title":            c.get("title", ""),
            "section_id":       section_id,
            "section_path":     path,
            "template":         _reverse_map(TEMPLATE_MAP, c.get("template_id")),
            "type":             _reverse_map(TYPE_MAP, c.get("type_id")),
            "priority":         _reverse_map(PRIORITY_MAP, c.get("priority_id")),
            "refs":             c.get("refs", ""),
            "preconditions":    c.get("custom_preconds", ""),
            "steps":            steps,
            "bdd_scenario":     c.get("custom_testrail_bdd_scenario", ""),
            "automated_status": _reverse_map(AUTOMATED_STATUS_MAP, c.get("custom_automated_status")),
            "automation_type":  _reverse_map(AUTOMATION_TYPE_MAP, c.get("custom_automation_type")),
            "cucumber_tags":    c.get("custom_case_cucumber_tags", ""),
            "api_version":      c.get("custom_case_api_version", ""),
            "api_regression":   c.get("custom_case_api_regression"),
        }

    def locate_case(self, case_id: int) -> dict:
        """
        Return the section location and breadcrumb path for *case_id*.

        Example
        -------
        client.locate_case(774)
        # → {
        #     "case_id":    "C774",
        #     "title":      "POST /transfers – happy path",
        #     "section_id": 330,
        #     "path":       "UI Manual Tests > ReadyRemit - Admin Portal > Transfers",
        #   }
        """
        c = self.get_case(case_id)
        section_id = c.get("section_id")
        path = self.get_section_path(section_id) if section_id else ""
        return {
            "case_id":    f"C{c['id']}",
            "title":      c.get("title", ""),
            "section_id": section_id,
            "path":       path,
        }

    # ------------------------------------------------------------------
    # Test Cases  –  write
    # ------------------------------------------------------------------

    def create_case(
        self,
        section_id: int,
        title: str,
        *,
        template_id: int = 2,
        type_id: int = 13,
        priority_id: int = 2,
        estimate: Optional[str] = None,
        refs: Optional[str] = None,
        preconditions: Optional[str] = None,
        steps: Optional[list[dict]] = None,
        custom_fields: Optional[dict] = None,
    ) -> dict:
        """
        Create a new test case inside *section_id*.

        Parameters
        ----------
        section_id    : TestRail section id (required).
        title         : Case title (required).
        template_id   : 1=Text, 2=Steps, 3=Exploratory, 4=BDD. Default: Steps.
        type_id       : 13=Manual, 3=Automated, 6=Functional, 9=Regression, …
        priority_id   : 1=Low, 2=Medium, 3=High, 4=Critical.
        estimate      : Time string, e.g. "30s", "1m 30s".
        refs          : Comma-separated reference / ticket links.
        preconditions : Plain-text or HTML precondition string.
        steps         : List of step dicts for the Steps template.
                        Each dict: {"content": str, "expected": str}
        custom_fields : Arbitrary key/value pairs forwarded verbatim
                        (use TestRail internal names, e.g. "custom_automation_type").

        Returns the newly created case dict.
        """
        payload: dict = {
            "title":       title,
            "template_id": template_id,
            "type_id":     type_id,
            "priority_id": priority_id,
        }
        if estimate:
            payload["estimate"] = estimate
        if refs:
            payload["refs"] = refs
        if preconditions:
            payload["custom_preconds"] = preconditions
        if steps:
            payload["custom_steps_separated"] = steps
        if custom_fields:
            payload.update(custom_fields)

        result = self._post(f"add_case/{section_id}", payload)
        log.info("Created case C%s  '%s'", result.get("id"), title)
        return result

    def update_case(
        self,
        case_id: int,
        *,
        title: Optional[str] = None,
        template_id: Optional[int] = None,
        type_id: Optional[int] = None,
        priority_id: Optional[int] = None,
        estimate: Optional[str] = None,
        refs: Optional[str] = None,
        preconditions: Optional[str] = None,
        steps: Optional[list[dict]] = None,
        custom_fields: Optional[dict] = None,
    ) -> dict:
        """
        Update an existing test case.

        Only fields that are explicitly passed (not None) are included in the
        request body, so you can update a single field without touching others.

        *case_id* is the numeric id (strip the leading "C").
        """
        payload: dict = {}
        if title         is not None: payload["title"]                    = title
        if template_id   is not None: payload["template_id"]              = template_id
        if type_id       is not None: payload["type_id"]                  = type_id
        if priority_id   is not None: payload["priority_id"]              = priority_id
        if estimate      is not None: payload["estimate"]                  = estimate
        if refs          is not None: payload["refs"]                      = refs
        if preconditions is not None: payload["custom_preconds"]           = preconditions
        if steps         is not None: payload["custom_steps_separated"]    = steps
        if custom_fields:             payload.update(custom_fields)

        if not payload:
            log.warning("update_case called for C%s with no fields to update.", case_id)
            return self.get_case(case_id)

        result = self._post(f"update_case/{case_id}", payload)
        log.info("Updated case C%s", case_id)
        return result

    # ------------------------------------------------------------------
    # Convenience: build a step list from parallel arrays
    # ------------------------------------------------------------------

    @staticmethod
    def build_steps(
        step_contents: list[str],
        step_expected: list[str],
    ) -> list[dict]:
        """
        Zip two parallel lists (step text, expected result) into the
        ``custom_steps_separated`` format expected by TestRail.

        Example
        -------
        steps = TestrailClient.build_steps(
            ["Send POST /transfers", "Verify response code"],
            ["201 Created",          "Response body contains transfer id"],
        )
        """
        return [
            {"content": s, "expected": e}
            for s, e in zip(step_contents, step_expected)
        ]

    # ------------------------------------------------------------------
    # Convenience: map raw strings to TestRail ids
    # ------------------------------------------------------------------

    @staticmethod
    def field_ids(
        priority: str = "Medium",
        case_type: str = "Manual",
        template: str = "Test Case (Steps)",
        automated_status: Optional[str] = None,
        automation_type: Optional[str] = None,
        difficulty: Optional[str] = None,
    ) -> dict:
        """
        Convert human-readable field strings (as they appear in the TestRail export)
        to their numeric TestRail ids, using keys verified against bwp.testrail.io.

        Returns a dict ready to be spread into create_case / update_case kwargs:
            {
              "type_id":       ...,
              "priority_id":   ...,
              "template_id":   ...,
              "custom_fields": { ... }   # only populated when optional args are set
            }

        Custom field system_names (verified):
            custom_automated_status   – dropdown: To Do=1, In Progress=2, Done=3,
                                        Can't Automate=4, Needs Info=5, On Hold=6,
                                        Automation Candidate=7
            custom_automation_type    – dropdown: None=0, Postman=1,
                                        Postman + Query=2, Reports Automation=3, Cucumber=4
            custom_difficulty         – dropdown: Easy=1, Medium=2, Difficult=3
        """
        result: dict = {
            "type_id":     _type_id(case_type),
            "priority_id": _priority_id(priority),
            "template_id": _template_id(template),
        }
        custom: dict = {}
        if automated_status:
            val = _automated_status_id(automated_status)
            if val is not None:
                custom["custom_automated_status"] = val
        if automation_type:
            val = _automation_type_id(automation_type)
            if val is not None:
                custom["custom_automation_type"] = val
        if difficulty:
            val = DIFFICULTY_MAP.get(difficulty.strip().lower())
            if val is not None:
                custom["custom_difficulty"] = val
        if custom:
            result["custom_fields"] = custom
        return result


# ---------------------------------------------------------------------------
# Quick smoke-test / usage examples
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    client = TestrailClient()

    # ── 1. List all sections ──────────────────────────────────────────────
    print("\n=== Sections ===")
    sections = client.get_sections()
    for s in sections:
        indent = "  " * s.get("depth", 0)
        print(f"{indent}[{s['id']}] {s['name']}")

    # ── 2. Retrieve test cases for one section ────────────────────────────
    # section = client.get_section_by_name("Transfers")
    # if section:
    #     cases = client.get_cases(section_id=section["id"])
    #     print(f"\nFound {len(cases)} case(s) in '{section['name']}'")
    #     for c in cases[:5]:
    #         print(f"  C{c['id']}  {c['title']}")

    # ── 3. Create a new test case ─────────────────────────────────────────
    # ids = TestrailClient.field_ids(priority="High", case_type="Manual")
    # steps = TestrailClient.build_steps(
    #     ["Send POST /transfers with valid payload"],
    #     ["HTTP 201, body contains transfer_id"],
    # )
    # new_case = client.create_case(
    #     section_id   = 123,          # replace with real section id
    #     title        = "POST /transfers – happy path",
    #     template_id  = ids["template_id"],
    #     type_id      = ids["type_id"],
    #     priority_id  = ids["priority_id"],
    #     refs         = "https://dev.azure.com/brightwell/ReadyRemit/_workitems/edit/99999",
    #     steps        = steps,
    # )
    # print(f"\nCreated C{new_case['id']}")

    # ── 4. Update an existing test case ──────────────────────────────────
    # updated = client.update_case(
    #     case_id    = 774,            # C774 → 774
    #     priority_id = _priority_id("High"),
    #     custom_fields = {"custom_labels": "Artemis"},
    # )
    # print(f"\nUpdated C{updated['id']}  priority → {updated['priority_id']}")
