# CLAUDE.md — testrail-api-access

Context for Claude when working inside this folder or when a skill (e.g. `pbi-to-cucumber`)
needs to sync test cases to TestRail.

All field ids and custom field keys below are **verified** against your TestRail instance
via `discover_fields.py` (project 1, suite S2).

---

## Instance details

| Key | Value |
|---|---|
| URL | `https://your-org.testrail.io` |
| Project ID | `1` |
| Suite ID | `2` (Master) |
| Auth | `.env` file → `TESTRAIL_URL`, `TESTRAIL_USER`, `TESTRAIL_API_KEY` |

---

## How to invoke from a skill (Python subprocess)

Write a driver script to the outputs folder, then run it via `mcp__workspace__bash`.
The module is importable as long as you add its folder to `sys.path`.

```python
import sys
sys.path.insert(0, "/path/to/testrail-api-access")

from testrail_client import TestrailClient

client = TestrailClient()   # reads .env automatically

# Resolve section
section = client.get_section_by_name("Transfers")
section_id = section["id"]  # → 330

# Create a case
steps = TestrailClient.build_steps(
    ["Send POST /transfers with valid payload"],
    ["HTTP 201, body contains transfer_id"],
)
case = client.create_case(
    section_id    = section_id,
    title         = "POST /transfers – happy path",
    priority_id   = 3,   # High
    type_id       = 13,  # Manual
    template_id   = 2,   # Steps
    refs          = "https://your-ado-org.visualstudio.com/YourProject/_workitems/edit/XXXXX",
    steps         = steps,
    custom_fields = {
        "custom_automated_status":   1,      # To Do
        "custom_automation_type":    4,      # Cucumber
        "custom_case_api_regression": False,
    },
)
print(f"Created C{case['id']}")
```

Bash run command:

```bash
cd /path/to/testrail-api-access && python3 /path/to/driver.py
```

---

## Verified field ids

### Priority
| id | Name |
|---|---|
| 1 | Low |
| 2 | Medium (default) |
| 3 | High |
| 4 | Critical |

### Case type  ⚠️ Manual = 13 (not 1)
| id | Name |
|---|---|
| 3 | Automated |
| 6 | Functional |
| 9 | Regression |
| 11 | Smoke & Sanity |
| **13** | **Manual** (default) |

### Template
| id | Name |
|---|---|
| 1 | Test Case (Text) |
| 2 | Test Case (Steps) (default) |
| 3 | Exploratory Session |
| 4 | Behaviour Driven Development |

---

## Verified custom field system_names

Use these exact keys in `custom_fields={}`:

| system_name | Label | Usage |
|---|---|---|
| `custom_automated_status` | Automated Status | dropdown (see below) |
| `custom_automation_type` | Automation Type | dropdown (see below) |
| `custom_automation_status` | Automation Status | Manual=1, Automated=2 |
| `custom_difficulty` | Difficulty | Easy=1, Medium=2, Difficult=3 |
| `custom_case_api_regression` | API Regression | `True` / `False` (checkbox) |
| `custom_case_api_version` | API Version | string, e.g. `"1.36"` |
| `custom_case_cucumber_tags` | Cucumber Tags | string, e.g. `"@transfers @smoke"` |
| `custom_case_testing_group` | TestingGroup | string |
| `custom_case_release_version` | Release Version | string |
| `custom_preconds` | Preconditions | HTML text (Steps + Text templates) |
| `custom_steps_separated` | Steps | list of `{content, expected}` dicts (template 2) |
| `custom_testrail_bdd_scenario` | BDD Scenarios | BDD text (template 4) |

### `custom_automated_status` option ids
| id | Value |
|---|---|
| 1 | To Do |
| 2 | In Progress |
| 3 | Done |
| 4 | Can't Automate |
| 5 | Needs Info |
| 6 | On Hold |
| 7 | Automation Candidate |

### `custom_automation_type` option ids
| id | Value |
|---|---|
| 0 | None |
| 1 | Postman |
| 2 | Postman + Query |
| 3 | Reports Automation |
| 4 | Cucumber |

---

## Section resolution

Always call `get_section_by_name(name)` — never hardcode section ids.

Top-level sections in suite S2:

| id | Name |
|---|---|
| 32 | UI Manual Tests |
| 34 | Vulcan Automated Tests |
| 454 | Admin (RR and Latitude) |
| 247 | Athena Automated Tests |
| 5567 | Latitude Client Portal |

ReadyRemit API-related sections (under id=283, ReadyRemit - Admin Portal):

| id | Name |
|---|---|
| 330 | Transfers |
| 331 | Transfer details |
| 333 | Senders |
| 334 | Sender details |
| 332 | One time use |
| 336 | Users |
| 337 | Admins |
| 435 | Login & Account |
| 451 | User Management |
| 4483 | Audit history |

If a section name from the PBI doesn't match, call `get_sections()` to enumerate.
**Do not create sections automatically — ask the user first.**

---

## Steps format

For `template_id=2`, steps are passed as:

```python
steps = TestrailClient.build_steps(
    ["step 1 action", "step 2 action"],
    ["expected result 1", "expected result 2"],
)
# → [{"content": "...", "expected": "..."}, ...]
```

The field name is `custom_steps_separated`. Pass via the `steps=` kwarg in
`create_case` / `update_case` — the client maps it automatically.

---

## Integration with pbi-to-cucumber skill

After Phase 6 (wiki update), optionally sync finalized scenarios to TestRail:

1. Resolve target section via `get_section_by_name()` using the functional area from the PBI.
2. For each approved test case:
   - Search for an existing case with the same title in that section via `get_cases(section_id=...)`.
   - If found → `update_case(existing_id, ...)`.
   - If not found → `create_case(section_id, ...)`.
3. Always set `refs` to the ADO work item URL from the PBI.
4. Set `custom_case_api_version` if the PBI mentions a specific API version.
5. Set `custom_automated_status=1` (To Do) on newly created cases.
6. Set `custom_automation_type=4` (Cucumber) if a feature file was produced.
7. Log every created/updated case id so the user has a direct reference.

**Guard:** if more than 5 cases would be created in one operation, confirm with the user
before executing to avoid duplicates.

---

## Error handling

`TestrailClient` raises `requests.HTTPError` on non-2xx responses. The response body
contains `{"error": "..."}` with a TestRail message. Always surface this to the user:

```python
try:
    case = client.create_case(...)
except requests.HTTPError as e:
    print(f"TestRail error {e.response.status_code}: {e.response.text}")
```

---

## Do not

- Do not import or read `artemis_cadmus_plutus___coreapi.csv` at runtime — it was a one-time
  field-structure reference only.
- Do not hardcode section ids, project ids, or suite ids in driver scripts.
- Do not commit `.env` to the repo.
- Do not create sections programmatically — ask the user.
- Do not use `type_id=1` for Manual — the correct id is **13** in this instance.
