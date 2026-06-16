# testrail-api-access

Python utilities for interacting with TestRail via its REST API v2.  
Field ids and custom field keys in this document are **verified** against a live instance
via `discover_fields.py`.

---

## Setup

### 1. Install dependencies

```bash
pip install requests python-dotenv
```

### 2. Configure credentials

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

| Variable | Description |
|---|---|
| `TESTRAIL_URL` | `https://your-org.testrail.io` |
| `TESTRAIL_USER` | Your TestRail login e-mail |
| `TESTRAIL_API_KEY` | API key from **My Settings → API Keys** |
| `TESTRAIL_PROJECT_ID` | `2` |
| `TESTRAIL_SUITE_ID` | `2` (Master suite) |

> **Never commit `.env` to version control.**

---

## Quick start

```python
from testrail_client import TestrailClient

client = TestrailClient()

# List all sections
sections = client.get_sections()

# Resolve a section by name and get its cases
section = client.get_section_by_name("Transfers")
cases = client.get_cases(section_id=section["id"])

# Create a case
steps = TestrailClient.build_steps(
    ["Send POST /transfers with valid payload"],
    ["HTTP 201, body contains transfer_id"],
)
new_case = client.create_case(
    section_id    = section["id"],
    title         = "POST /transfers – happy path",
    priority_id   = 3,    # High
    type_id       = 13,   # Manual
    refs          = "https://your-ado-org.visualstudio.com/YourProject/_workitems/edit/99999",
    steps         = steps,
    custom_fields = {
        "custom_automated_status":   1,   # To Do
        "custom_automation_type":    4,   # Cucumber
        "custom_case_api_regression": False,
    },
)

# Update an existing case (C774 → case_id=774)
client.update_case(774, priority_id=4, refs="https://...")
```

Run the built-in smoke test (lists all sections to stdout):

```bash
python testrail_client.py
```

---

## CLI

A command-line interface is available via `cli.py`:

```bash
python cli.py sections                         # print full section tree
python cli.py sections --search transfer       # filter by name
python cli.py sections --children-of 283       # direct children of a section

python cli.py cases Transfers                  # list cases by section name
python cli.py cases 330 --search "POST"        # filter cases by title

python cli.py case 774                         # full details for C774
python cli.py find "invalid sender"            # search titles across suite
python cli.py locate 774                       # where does C774 live?
python cli.py locate --section 330             # section path + children
```

See [`md/cli-reference.md`](md/cli-reference.md) for complete usage.

---

## API reference

### `TestrailClient(base_url, user, api_key, project_id, suite_id)`

All parameters default to the values in `.env`. Override at instantiation to target a
different project or suite.

---

### Sections

| Method | Description |
|---|---|
| `get_sections(project_id?, suite_id?)` | All sections for the project/suite |
| `get_section(section_id)` | Single section by id |
| `get_section_by_name(name, ...)` | Exact case-insensitive name lookup; returns `None` if not found |
| `search_sections(query, ...)` | Partial name match; returns list of matching sections |
| `get_section_ancestors(section_id, ...)` | Ancestor chain from root to parent as a list |
| `get_section_path(section_id, ...)` | `"Root > Parent > Section"` breadcrumb string |
| `get_section_children(section_id, ...)` | Direct children of a section (one level) |
| `invalidate_section_cache()` | Clear the in-memory section cache |

> `get_section_by_name`, `search_sections`, `get_section_ancestors`, `get_section_path`,
> and `get_section_children` all share an in-memory cache per `(project_id, suite_id)` pair —
> the section list is fetched only once per client instance.

See [`md/lookup-functions.md`](md/lookup-functions.md) for code examples.

---

### Test cases – read

| Method | Description |
|---|---|
| `get_cases(project_id?, suite_id?, section_id?, filters?)` | Paginated case list |
| `get_case(case_id)` | Single case by numeric id (strip the `C` prefix) |
| `find_cases_by_title(title, section_id?, exact?, ...)` | Search cases by title substring or exact match |
| `get_case_summary(case_id)` | Decoded human-readable dict for a case |
| `locate_case(case_id)` | Section id and breadcrumb path for a case |

Common `filters` keys: `type_id`, `priority_id`, `created_by`, `updated_after`, `updated_before`.

---

### Test cases – write

**`create_case(section_id, title, *, template_id, type_id, priority_id, estimate, refs, preconditions, steps, custom_fields)`**

Creates a new case. Returns the created case dict.

**`update_case(case_id, *, title, template_id, type_id, priority_id, estimate, refs, preconditions, steps, custom_fields)`**

Updates only the fields explicitly passed. Returns the updated case dict.

---

### Static helpers

**`TestrailClient.build_steps(contents, expected)`**  
Zips two parallel lists into the `custom_steps_separated` format.

**`TestrailClient.field_ids(priority, case_type, template, automated_status?, automation_type?, difficulty?)`**  
Converts string labels to their verified numeric ids.

---

## Field value reference (verified)

### Priorities

| id | Name |
|---|---|
| 1 | Low |
| 2 | Medium |
| 3 | High |
| 4 | Critical |

### Case types

| id | Name |
|---|---|
| 1 | Acceptance |
| 2 | Accessibility |
| 3 | Automated |
| 4 | Compatibility |
| 5 | Destructive |
| 6 | Functional |
| 7 | Other |
| 8 | Performance |
| 9 | Regression |
| 10 | Security |
| 11 | Smoke & Sanity |
| 12 | Usability |
| **13** | **Manual** |

### Templates

| id | Name |
|---|---|
| 1 | Test Case (Text) |
| 2 | Test Case (Steps) |
| 3 | Exploratory Session |
| 4 | Behaviour Driven Development |

---

## Custom fields (verified system_names)

| system_name | Label | Type | Notes |
|---|---|---|---|
| `custom_automated_status` | Automated Status | dropdown | See options below |
| `custom_automation_type` | Automation Type | dropdown | See options below |
| `custom_automation_status` | Automation Status | dropdown | Manual=1, Automated=2 |
| `custom_difficulty` | Difficulty | dropdown | Easy=1, Medium=2, Difficult=3 |
| `custom_case_api_regression` | API Regression | checkbox | `True` / `False` |
| `custom_case_api_version` | API Version | string | e.g. `"1.36"` |
| `custom_case_cucumber_tags` | Cucumber Tags | string | e.g. `"@transfers @smoke"` |
| `custom_case_testing_group` | TestingGroup | string | free text |
| `custom_case_release_version` | Release Version | string | free text |
| `custom_automated_test_case` | Automated Test Case | string | free text |
| `custom_automation_id` | Automation ID | text | free text |
| `custom_preconds` | Preconditions | text | HTML supported |
| `custom_expected` | Expected Result | text | HTML supported |
| `custom_notes` | Notes | text | HTML supported |
| `custom_steps` | Steps (text) | text | used with template_id=1 |
| `custom_steps_separated` | Steps (steps) | steps | used with template_id=2 |
| `custom_testrail_bdd_scenario` | BDD Scenarios | bdd | used with template_id=4 |

### `custom_automated_status` options

| id | Value |
|---|---|
| 1 | To Do |
| 2 | In Progress |
| 3 | Done |
| 4 | Can't Automate |
| 5 | Needs Info |
| 6 | On Hold |
| 7 | Automation Candidate |

### `custom_automation_type` options

| id | Value |
|---|---|
| 0 | None |
| 1 | Postman |
| 2 | Postman + Query |
| 3 | Reports Automation |
| 4 | Cucumber |

---

## Suite sections (top-level, S2 Master)

The Master suite contains 170 sections. Top-level groups:

| id | Name |
|---|---|
| 32 | UI Manual Tests |
| 34 | Vulcan Automated Tests |
| 454 | Admin (RR and Latitude) |
| 247 | Athena Automated Tests |
| 5567 | Latitude Client Portal |

Notable API-related sub-sections under **UI Manual Tests → ReadyRemit - Admin Portal** (id=283):

| id | Name |
|---|---|
| 330 | Transfers |
| 331 | Transfer details |
| 333 | Senders |
| 334 | Sender details |
| 332 | One time use |
| 336 | Users |

> Run `python cli.py sections` to print the live full section tree with ids.

---

## Further reading

| File | Contents |
|---|---|
| [`md/cli-reference.md`](md/cli-reference.md) | Full CLI usage guide with examples |
| [`md/lookup-functions.md`](md/lookup-functions.md) | Lookup helper quick reference + code patterns |
| [`md/section-tree.md`](md/section-tree.md) | Static snapshot of known section hierarchy |
