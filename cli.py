"""
cli.py
------
Command-line interface for the TestRail API client.

Usage
-----
  python cli.py sections [--search QUERY]
  python cli.py sections --children-of SECTION_ID
  python cli.py cases <section-name-or-id> [--search TITLE]
  python cli.py case <case-id>
  python cli.py find <title-substring>
  python cli.py locate <case-id>
  python cli.py locate --section <section-id>

All commands read credentials from the .env file in this directory.
Run ``python cli.py --help`` for full usage.
"""

import argparse
import json
import sys
import textwrap

from testrail_client import TestrailClient


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _col(value: str, width: int) -> str:
    """Left-pad *value* to *width*, truncating with ellipsis if too long."""
    s = str(value) if value is not None else ""
    if len(s) > width:
        s = s[: width - 1] + "…"
    return s.ljust(width)


def _print_table(rows: list[list], headers: list[str]) -> None:
    """Print a simple fixed-width table."""
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell) if cell is not None else ""))

    sep = "  ".join("-" * w for w in widths)
    header_line = "  ".join(str(h).ljust(w) for h, w in zip(headers, widths))
    print(header_line)
    print(sep)
    for row in rows:
        print("  ".join(_col(cell, w) for cell, w in zip(row, widths)))


def _resolve_section(client: TestrailClient, name_or_id: str) -> dict:
    """Resolve a section from a name string or numeric id string."""
    if name_or_id.lstrip("-").isdigit():
        return client.get_section(int(name_or_id))
    section = client.get_section_by_name(name_or_id)
    if section is None:
        print(f"ERROR: No section found with name '{name_or_id}'", file=sys.stderr)
        sys.exit(1)
    return section


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def cmd_sections(client: TestrailClient, args: argparse.Namespace) -> None:
    """List sections, optionally filtered or scoped to children."""
    if args.children_of:
        sections = client.get_section_children(int(args.children_of))
        parent_path = client.get_section_path(int(args.children_of))
        print(f"Children of: {parent_path}\n")
    elif args.search:
        sections = client.search_sections(args.search)
        print(f"Sections matching '{args.search}':\n")
    else:
        sections = client.get_sections()
        print("All sections (indented by depth):\n")

    if not sections:
        print("(none)")
        return

    if args.search or args.children_of:
        rows = []
        for s in sections:
            path = client.get_section_path(s["id"])
            rows.append([s["id"], s["name"], path])
        _print_table(rows, ["ID", "Name", "Path"])
    else:
        for s in sections:
            indent = "  " * s.get("depth", 0)
            print(f"{indent}[{s['id']}] {s['name']}")


def cmd_cases(client: TestrailClient, args: argparse.Namespace) -> None:
    """List cases in a section, optionally filtered by title."""
    section = _resolve_section(client, args.section)
    path = client.get_section_path(section["id"])
    print(f"Section: {path}  (id={section['id']})\n")

    if args.search:
        cases = client.find_cases_by_title(args.search, section_id=section["id"])
        print(f"Cases matching '{args.search}':\n")
    else:
        cases = client.get_cases(section_id=section["id"])

    if not cases:
        print("(no cases found)")
        return

    rows = [[f"C{c['id']}", c.get("title", ""), c.get("priority_id", ""), c.get("type_id", "")] for c in cases]
    _print_table(rows, ["ID", "Title", "Pri", "Type"])
    print(f"\nTotal: {len(cases)} case(s)")


def cmd_case(client: TestrailClient, args: argparse.Namespace) -> None:
    """Show full decoded details for a single case."""
    case_id = int(str(args.case_id).lstrip("cC"))
    summary = client.get_case_summary(case_id)

    print(f"\n{'=' * 60}")
    print(f"  {summary['id']}  —  {summary['title']}")
    print(f"{'=' * 60}")
    print(f"  Path:             {summary['section_path']}")
    print(f"  Type:             {summary['type']}")
    print(f"  Priority:         {summary['priority']}")
    print(f"  Template:         {summary['template']}")
    print(f"  Automated status: {summary['automated_status']}")
    print(f"  Automation type:  {summary['automation_type']}")
    if summary["cucumber_tags"]:
        print(f"  Cucumber tags:    {summary['cucumber_tags']}")
    if summary["api_version"]:
        print(f"  API version:      {summary['api_version']}")
    if summary["api_regression"] is not None:
        print(f"  API regression:   {summary['api_regression']}")
    if summary["refs"]:
        print(f"  Refs:             {summary['refs']}")

    if summary["preconditions"]:
        print(f"\n  Preconditions:\n    {summary['preconditions'].strip()}")

    if summary["steps"]:
        print(f"\n  Steps ({len(summary['steps'])}):")
        for i, step in enumerate(summary["steps"], 1):
            wrapped_action = textwrap.fill(step["step"], width=72, subsequent_indent="       ")
            wrapped_expected = textwrap.fill(step["expected"], width=72, subsequent_indent="       ")
            print(f"    {i}. {wrapped_action}")
            if step["expected"]:
                print(f"       Expected: {wrapped_expected}")

    if summary["bdd_scenario"]:
        print(f"\n  BDD Scenario:\n")
        for line in summary["bdd_scenario"].splitlines():
            print(f"    {line}")

    print()


def cmd_find(client: TestrailClient, args: argparse.Namespace) -> None:
    """Search cases by title substring across the entire suite."""
    print(f"Searching for '{args.title}' across all cases…\n")
    cases = client.find_cases_by_title(args.title)

    if not cases:
        print("(no matches)")
        return

    rows = []
    by_id = {s["id"]: s for s in client._cached_sections()}
    for c in cases:
        section_id = c.get("section_id")
        path = client.get_section_path(section_id) if section_id else ""
        rows.append([f"C{c['id']}", c.get("title", ""), path])

    _print_table(rows, ["ID", "Title", "Section Path"])
    print(f"\nTotal: {len(cases)} match(es)")


def cmd_locate(client: TestrailClient, args: argparse.Namespace) -> None:
    """Show breadcrumb path for a case or section."""
    if args.section:
        section_id = int(args.section)
        path = client.get_section_path(section_id)
        section = client.get_section(section_id)
        ancestors = client.get_section_ancestors(section_id)
        children = client.get_section_children(section_id)

        print(f"\nSection [{section_id}] {section.get('name', '')}")
        print(f"Path: {path}")
        if ancestors:
            print(f"\nAncestors ({len(ancestors)}):")
            for a in ancestors:
                print(f"  [{a['id']}] {a['name']}")
        if children:
            print(f"\nDirect children ({len(children)}):")
            for ch in children:
                print(f"  [{ch['id']}] {ch['name']}")
        print()

    else:
        case_id = int(str(args.case_id).lstrip("cC"))
        loc = client.locate_case(case_id)
        print(f"\n{loc['case_id']}  —  {loc['title']}")
        print(f"Section [{loc['section_id']}]: {loc['path']}\n")


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python cli.py",
        description="TestRail CLI — bwp.testrail.io · Project 1 · Suite S2",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ── sections ─────────────────────────────────────────────────────────
    p_sec = sub.add_parser("sections", help="List or search sections")
    p_sec.add_argument("--search", metavar="QUERY", help="Filter sections by name (partial match)")
    p_sec.add_argument(
        "--children-of",
        metavar="SECTION_ID",
        help="List direct children of a section id",
    )

    # ── cases ─────────────────────────────────────────────────────────────
    p_cases = sub.add_parser("cases", help="List cases in a section")
    p_cases.add_argument("section", help="Section name or numeric id")
    p_cases.add_argument("--search", metavar="TITLE", help="Filter cases by title (partial match)")

    # ── case ──────────────────────────────────────────────────────────────
    p_case = sub.add_parser("case", help="Show full details for a single case")
    p_case.add_argument("case_id", help="Case id (numeric or with C prefix, e.g. 774 or C774)")

    # ── find ──────────────────────────────────────────────────────────────
    p_find = sub.add_parser("find", help="Search cases by title across the whole suite")
    p_find.add_argument("title", help="Title substring to search for")

    # ── locate ────────────────────────────────────────────────────────────
    p_loc = sub.add_parser("locate", help="Show the suite path for a case or section")
    p_loc.add_argument(
        "case_id",
        nargs="?",
        help="Case id (numeric or C-prefixed) to locate",
    )
    p_loc.add_argument(
        "--section",
        metavar="SECTION_ID",
        help="Show location info for a section id instead of a case",
    )

    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    try:
        client = TestrailClient()
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        sys.exit(1)

    dispatch = {
        "sections": cmd_sections,
        "cases":    cmd_cases,
        "case":     cmd_case,
        "find":     cmd_find,
        "locate":   cmd_locate,
    }
    dispatch[args.command](client, args)


if __name__ == "__main__":
    main()
