#!/usr/bin/env python3
"""
jira.py

Jira helpers for the CAM project, covering what `acli` cannot do (or does
awkwardly): read a work item as plain text, show link direction, set start
and due dates, move an item to another Epic, assign other people, create and
delete Blocks links, post comments, and list the Objectives' Epics with
schedule conflicts.

Every write prints the HTTP status, then reads the item back to verify it.
Credentials come only from ~/.jira/netrc (see the Credentials section of
docs/agents/issue-tracker.md); the token is never printed.

Usage: python3 scripts/jira.py --help, or python3 scripts/jira.py <command> --help.
Standard library only.
"""

import argparse
import base64
import datetime
import json
import netrc
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

HOST = "cuahsi.atlassian.net"
BASE_URL = f"https://{HOST}"
NETRC_PATH = os.path.expanduser("~/.jira/netrc")
START_FIELD = "customfield_10504"  # CAM's "Start date" (not "Target start")
OBJECTIVES = ("CAM-969", "CAM-1551", "CAM-974")
SHOW_FIELDS = [
    "summary", "issuetype", "status", "parent", "assignee", START_FIELD,
    "duedate", "labels", "issuelinks", "description",
]


class JiraError(Exception):
    """A failed Jira request, or a write that did not verify."""

    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


# --------------------------------------------------------------------------
# HTTP: one authenticated JSON request at a time.
# --------------------------------------------------------------------------

def _auth_header():
    """Build a Basic auth header from the netrc file without exposing it."""
    try:
        creds = netrc.netrc(NETRC_PATH).authenticators(HOST)
    except (OSError, netrc.NetrcParseError) as exc:
        raise JiraError(
            f"cannot read credentials from {NETRC_PATH} ({exc.__class__.__name__}); "
            "see the Credentials section of docs/agents/issue-tracker.md"
        ) from None
    if not creds:
        raise JiraError(f"no 'machine {HOST}' entry in {NETRC_PATH}")
    login, _, password = creds
    token = base64.b64encode(f"{login}:{password}".encode()).decode()
    return f"Basic {token}"


def _error_text(raw):
    """Pull Jira's error messages out of an error response body."""
    try:
        data = json.loads(raw)
    except ValueError:
        return raw.decode(errors="replace")[:300]
    messages = list(data.get("errorMessages", []))
    messages += [f"{field}: {msg}" for field, msg in data.get("errors", {}).items()]
    return "; ".join(messages) or str(data)[:300]


def request(method, path, body=None):
    """Send one REST call. Return (HTTP status, parsed JSON body or None)."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE_URL + path, data=data, method=method)
    req.add_header("Authorization", _auth_header())
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read()
            status = resp.status
    except urllib.error.HTTPError as exc:
        raise JiraError(
            f"{method} {path} -> HTTP {exc.code}: {_error_text(exc.read())}", exc.code
        ) from None
    except urllib.error.URLError as exc:
        raise JiraError(f"{method} {path} -> {exc.reason}") from None
    return status, (json.loads(raw) if raw.strip() else None)


def get_issue(key, fields):
    """Fetch selected fields of one work item."""
    _, data = request("GET", f"/rest/api/3/issue/{key}?fields={','.join(fields)}")
    return data


def get_myself():
    """Return the account of the credentials in the netrc file."""
    return request("GET", "/rest/api/3/myself")[1]


def search(jql, fields):
    """Run a JQL search, following pagination, and return every issue."""
    issues, token = [], None
    while True:
        body = {"jql": jql, "fields": fields, "maxResults": 100}
        if token:
            body["nextPageToken"] = token
        _, data = request("POST", "/rest/api/3/search/jql", body)
        issues += data.get("issues", [])
        token = data.get("nextPageToken")
        if not token:
            return issues


def get_changelog(key):
    """Return every changelog history of a work item, oldest first."""
    histories, start = [], 0
    while True:
        _, data = request(
            "GET", f"/rest/api/3/issue/{key}/changelog?startAt={start}&maxResults=100"
        )
        values = data.get("values", [])
        histories += values
        start += len(values)
        if data.get("isLast", True) or not values:
            return histories


def get_comments(key):
    """Return every comment on a work item, oldest first."""
    comments, start = [], 0
    while True:
        _, data = request(
            "GET",
            f"/rest/api/3/issue/{key}/comment?startAt={start}&maxResults=100&orderBy=created",
        )
        values = data.get("comments", [])
        comments += values
        start += len(values)
        if start >= data.get("total", 0) or not values:
            return comments


# --------------------------------------------------------------------------
# Atlassian Document Format (ADF) <-> plain text.
# --------------------------------------------------------------------------

def _inline_text(nodes):
    """Flatten inline ADF nodes (text, breaks, mentions, cards) to a string."""
    parts = []
    for node in nodes or []:
        kind = node.get("type")
        attrs = node.get("attrs", {})
        if kind == "text":
            text = node.get("text", "")
            if any(m.get("type") == "code" for m in node.get("marks", [])):
                text = f"`{text}`"
            parts.append(text)
        elif kind == "hardBreak":
            parts.append("\n")
        elif kind == "mention":
            parts.append(attrs.get("text", "@?"))
        elif kind == "emoji":
            parts.append(attrs.get("text") or attrs.get("shortName", ""))
        elif kind in ("inlineCard", "blockCard"):
            parts.append(attrs.get("url", ""))
        else:
            parts.append(_inline_text(node.get("content")))
    return "".join(parts)


def _render_blocks(nodes, indent):
    """Render block ADF nodes as lines. Top-level blocks end with a blank line."""
    lines = []
    gap = [] if indent else [""]
    for node in nodes or []:
        kind = node.get("type")
        content = node.get("content")
        if kind in ("paragraph", "codeBlock"):
            lines += [indent + line for line in _inline_text(content).split("\n")] + gap
        elif kind == "heading":
            level = node.get("attrs", {}).get("level", 1)
            lines += [indent + "#" * level + " " + _inline_text(content)] + gap
        elif kind in ("bulletList", "orderedList"):
            number = node.get("attrs", {}).get("order", 1)
            for item in content or []:
                marker = "- " if kind == "bulletList" else f"{number}. "
                number += 1
                item_lines = [l for l in _render_blocks(item.get("content"), indent + "  ") if l.strip()]
                if item_lines:
                    item_lines[0] = indent + marker + item_lines[0][len(indent) + 2:]
                lines += item_lines
            lines += gap
        elif kind == "rule":
            lines += [indent + "---"] + gap
        elif kind == "table":
            for row in content or []:
                cells = [" ".join(_render_blocks(c.get("content"), "")).strip() for c in row.get("content", [])]
                lines.append(indent + " | ".join(cells))
            lines += gap
        elif content:
            # blockquote, panel, expand, and anything newer: keep the children.
            lines += _render_blocks(content, indent)
    return lines


def adf_to_text(doc):
    """Render an ADF document (a description or comment body) as plain text."""
    if not doc:
        return ""
    text = "\n".join(_render_blocks(doc.get("content"), "")).strip()
    return re.sub(r"\n{3,}", "\n\n", text)


def text_to_adf(text):
    """Build an ADF document from plain text.

    Blank lines separate blocks. A block whose lines all start with "- "
    becomes a bullet list, one whose lines all start with "1. ", "2. ", ...
    becomes a numbered list; any other block is a paragraph that keeps its
    line breaks.
    """
    def paragraph(line_list):
        content = []
        for i, line in enumerate(line_list):
            if i:
                content.append({"type": "hardBreak"})
            if line:
                content.append({"type": "text", "text": line})
        return {"type": "paragraph", "content": content}

    blocks = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = block.split("\n")
        if all(line.startswith("- ") for line in lines):
            items = [{"type": "listItem", "content": [paragraph([l[2:]])]} for l in lines]
            blocks.append({"type": "bulletList", "content": items})
        elif all(re.match(r"\d+\. ", line) for line in lines):
            items = [{"type": "listItem", "content": [paragraph([l.split(". ", 1)[1]])]} for l in lines]
            blocks.append({"type": "orderedList", "content": items})
        else:
            blocks.append(paragraph(lines))
    return {"type": "doc", "version": 1, "content": blocks}


# --------------------------------------------------------------------------
# Links, dates, and people: pure helpers used by the commands.
# --------------------------------------------------------------------------

def link_lines(issuelinks):
    """Describe each link from the viewed item's side, e.g. "blocks CAM-1".

    On the viewed item, an outwardIssue entry reads "<item> <outward verb>
    <other>" ("blocks"); an inwardIssue entry reads "<item> <inward verb>
    <other>" ("is blocked by").
    """
    lines = []
    for link in issuelinks or []:
        if "outwardIssue" in link:
            verb, other = link["type"]["outward"], link["outwardIssue"]
        else:
            verb, other = link["type"]["inward"], link["inwardIssue"]
        fields = other.get("fields", {})
        status = fields.get("status", {}).get("name", "?")
        lines.append(f"{verb} {other['key']}  {fields.get('summary', '')} ({status})  [link {link['id']}]")
    return lines


def blockers_of(issuelinks):
    """Return {blocker key: link id} for the Blocks links blocking an item."""
    return {
        link["inwardIssue"]["key"]: link["id"]
        for link in issuelinks or []
        if link["type"]["name"] == "Blocks" and "inwardIssue" in link
    }


def find_conflicts(dates, blocks):
    """List Blocks links whose blocker is due after the blocked item starts.

    dates maps key -> (start, due) as ISO strings or None; blocks is a list of
    (blocker, blocked) pairs. ISO dates compare correctly as strings.
    """
    conflicts = []
    for blocker, blocked in blocks:
        due = dates.get(blocker, (None, None))[1]
        start = dates.get(blocked, (None, None))[0]
        if due and start and due > start:
            conflicts.append(f"{blocker} (due {due}) blocks {blocked} (starts {start})")
    return conflicts


def last_setter(histories, field_id):
    """Return (author, created) of the latest change to a field, or None."""
    found = None
    for history in histories:
        for item in history.get("items", []):
            if item.get("fieldId") == field_id or item.get("field") == field_id:
                found = (history.get("author", {}), history.get("created", ""))
    return found


def pick_user(users, query):
    """Choose one active person from a user search, or explain why not."""
    people = [u for u in users if u.get("active", True) and u.get("accountType") == "atlassian"]
    exact = [u for u in people if u.get("displayName", "").lower() == query.lower()]
    if len(exact) == 1:
        return exact[0]
    if len(people) == 1:
        return people[0]
    if not people:
        raise JiraError(f"no assignable person matches '{query}'")
    names = ", ".join(sorted(u.get("displayName", "?") for u in people))
    raise JiraError(f"'{query}' matches several people ({names}); use the full display name")


def _person(user):
    return (user or {}).get("displayName", "-")


# --------------------------------------------------------------------------
# Commands. Reads print plain text; writes print the HTTP status and verify.
# --------------------------------------------------------------------------

def cmd_show(args):
    """Print a work item as plain text, optionally with its comments."""
    fields = get_issue(args.key, SHOW_FIELDS)["fields"]
    parent = fields.get("parent")
    print(f"{args.key}  {fields.get('summary', '')}")
    print(f"Type: {fields['issuetype']['name']} | Status: {fields['status']['name']} | "
          f"Assignee: {_person(fields.get('assignee'))}")
    if parent:
        print(f"Parent: {parent['key']}  {parent['fields'].get('summary', '')}")
    print(f"Start: {fields.get(START_FIELD) or '-'} | Due: {fields.get('duedate') or '-'}")
    print(f"Labels: {', '.join(fields.get('labels', [])) or '-'}")
    links = link_lines(fields.get("issuelinks"))
    print("Links:" + ("" if links else " -"))
    for line in links:
        print(f"  {line}")
    print("\nDescription:")
    print(adf_to_text(fields.get("description")) or "-")
    if args.comments:
        comments = get_comments(args.key)
        print(f"\nComments ({len(comments)}):")
        for c in comments:
            created = c.get("created", "")[:16].replace("T", " ")
            print(f"\n--- {created} {_person(c.get('author'))} (comment {c['id']})")
            print(adf_to_text(c.get("body")))


def cmd_links(args):
    """Print an item's links with direction and link IDs."""
    lines = link_lines(get_issue(args.key, ["issuelinks"])["fields"].get("issuelinks"))
    for line in lines or ["no links"]:
        print(line)


def cmd_set_dates(args):
    """Set start and due dates together, guarding dates a person set."""
    if args.start > args.due:
        raise JiraError(f"start {args.start} is after due {args.due}")
    fields = get_issue(args.key, [START_FIELD, "duedate", "creator"])["fields"]
    wanted = {START_FIELD: args.start, "duedate": args.due}
    if all(fields.get(f) == v for f, v in wanted.items()):
        print(f"{args.key} already starts {args.start} and is due {args.due}; nothing to do")
        return
    if not args.force:
        # Refuse to overwrite a date someone else set; the caller must check
        # with the user and rerun with --force.
        me = get_myself()["accountId"]
        histories = get_changelog(args.key)
        others = []
        for field, label in ((START_FIELD, "start"), ("duedate", "due")):
            current = fields.get(field)
            if not current or current == wanted[field]:
                continue
            # No changelog entry means the date was set when the item was created.
            author, when = last_setter(histories, field) or (fields.get("creator"), "creation")
            if (author or {}).get("accountId") != me:
                others.append(f"{label} {current} was set by {_person(author)} ({when[:10]})")
        if others:
            raise JiraError("; ".join(others) + ". Check with the user, then rerun with --force")
    status, _ = request("PUT", f"/rest/api/3/issue/{args.key}", {"fields": wanted})
    print(f"PUT {args.key} dates -> HTTP {status}")
    after = get_issue(args.key, [START_FIELD, "duedate"])["fields"]
    if after.get(START_FIELD) != args.start or after.get("duedate") != args.due:
        raise JiraError(f"read-back shows start {after.get(START_FIELD)}, due {after.get('duedate')}")
    print(f"{args.key} starts {args.start}, due {args.due} (verified)")


def cmd_set_parent(args):
    """Move a work item under another Epic."""
    status, _ = request("PUT", f"/rest/api/3/issue/{args.key}", {"fields": {"parent": {"key": args.epic}}})
    print(f"PUT {args.key} parent -> HTTP {status}")
    parent = get_issue(args.key, ["parent"])["fields"].get("parent") or {}
    if parent.get("key") != args.epic:
        raise JiraError(f"read-back shows parent {parent.get('key')}")
    print(f"{args.key} parent is {args.epic}  {parent['fields'].get('summary', '')} (verified)")


def cmd_assign(args):
    """Assign a work item to a person found by name, or to @me."""
    if args.who == "@me":
        user = get_myself()
    else:
        query = urllib.parse.urlencode({"issueKey": args.key, "query": args.who})
        _, users = request("GET", f"/rest/api/3/user/assignable/search?{query}")
        user = pick_user(users, args.who)
    status, _ = request("PUT", f"/rest/api/3/issue/{args.key}/assignee", {"accountId": user["accountId"]})
    print(f"PUT {args.key} assignee -> HTTP {status}")
    after = get_issue(args.key, ["assignee"])["fields"].get("assignee") or {}
    if after.get("accountId") != user["accountId"]:
        raise JiraError(f"read-back shows assignee {_person(after)}")
    print(f"{args.key} assigned to {_person(after)} (verified)")


def cmd_block(args):
    """Create "BLOCKER blocks BLOCKED" and warn if the dates conflict."""
    if args.blocker == args.blocked:
        raise JiraError("an item cannot block itself")
    links = get_issue(args.blocked, ["issuelinks"])["fields"].get("issuelinks")
    if args.blocker in blockers_of(links):
        print(f"{args.blocker} already blocks {args.blocked} [link {blockers_of(links)[args.blocker]}]")
        return
    # Jira stores "<inwardIssue> <outward verb> <outwardIssue>": BLOCKER blocks BLOCKED.
    body = {
        "type": {"name": "Blocks"},
        "inwardIssue": {"key": args.blocker},
        "outwardIssue": {"key": args.blocked},
    }
    status, _ = request("POST", "/rest/api/3/issueLink", body)
    print(f"POST link -> HTTP {status}")
    blocked = get_issue(args.blocked, ["issuelinks", START_FIELD])["fields"]
    link_id = blockers_of(blocked.get("issuelinks")).get(args.blocker)
    if not link_id:
        raise JiraError(f"read-back shows no Blocks link from {args.blocker} to {args.blocked}")
    print(f"{args.blocker} blocks {args.blocked} [link {link_id}] (verified)")
    due = get_issue(args.blocker, ["duedate"])["fields"].get("duedate")
    for conflict in find_conflicts({args.blocker: (None, due), args.blocked: (blocked.get(START_FIELD), None)},
                                   [(args.blocker, args.blocked)]):
        print(f"warning: date conflict: {conflict}")


def cmd_unlink(args):
    """Delete one link by ID, then confirm it is gone."""
    _, link = request("GET", f"/rest/api/3/issueLink/{args.link_id}")
    described = f"{link['inwardIssue']['key']} {link['type']['outward']} {link['outwardIssue']['key']}"
    status, _ = request("DELETE", f"/rest/api/3/issueLink/{args.link_id}")
    print(f"DELETE link {args.link_id} -> HTTP {status}")
    try:
        request("GET", f"/rest/api/3/issueLink/{args.link_id}")
    except JiraError as exc:
        if exc.status == 404:
            print(f"deleted: {described} (verified)")
            return
        raise
    raise JiraError(f"link {args.link_id} still exists after DELETE")


def cmd_comment(args):
    """Post a plain-text file (or stdin with '-') as a comment."""
    if args.file == "-":
        text = sys.stdin.read()
    else:
        with open(args.file, encoding="utf-8") as handle:
            text = handle.read()
    if not text.strip():
        raise JiraError("comment text is empty")
    status, data = request("POST", f"/rest/api/3/issue/{args.key}/comment", {"body": text_to_adf(text)})
    print(f"POST {args.key} comment -> HTTP {status}")
    request("GET", f"/rest/api/3/issue/{args.key}/comment/{data['id']}")
    print(f"comment {data['id']} posted on {args.key} (verified)")


def cmd_epics(args):
    """List the Objectives' Epics in Rank order and report Blocks conflicts."""
    done = "" if args.all else " AND statusCategory != Done"
    jql = (f"parent in ({', '.join(OBJECTIVES)}) AND issuetype = Epic{done} "
           "ORDER BY cf[10116] ASC")
    epics = search(jql, ["summary", "status", "assignee", START_FIELD, "duedate", "issuelinks"])
    dates, blocks = {}, []
    print(f"{'KEY':<10} {'START':<10} {'DUE':<10} {'STATUS':<12} {'LEAD':<20} SUMMARY")
    for epic in epics:
        key, f = epic["key"], epic["fields"]
        dates[key] = (f.get(START_FIELD), f.get("duedate"))
        blocks += [(blocker, key) for blocker in blockers_of(f.get("issuelinks"))]
        print(f"{key:<10} {f.get(START_FIELD) or '-':<10} {f.get('duedate') or '-':<10} "
              f"{f['status']['name']:<12} {_person(f.get('assignee'))[:20]:<20} {f.get('summary', '')}")
    # Blockers outside the listed Epics (Stories, closed Epics) need their dates too.
    missing = sorted({blocker for blocker, _ in blocks} - set(dates))
    if missing:
        for issue in search(f"key in ({', '.join(missing)})", [START_FIELD, "duedate"]):
            dates[issue["key"]] = (issue["fields"].get(START_FIELD), issue["fields"].get("duedate"))
    undated = [key for key in dates if key not in missing and not all(dates[key])]
    conflicts = find_conflicts(dates, blocks)
    print(f"\nMissing a start or due date: {', '.join(undated) or 'none'}")
    print("Blocks conflicts (blocker due after the blocked item starts):" + ("" if conflicts else " none"))
    for conflict in conflicts:
        print(f"  {conflict}")


# --------------------------------------------------------------------------
# Command line.
# --------------------------------------------------------------------------

def issue_key(value):
    """argparse type: a Jira key such as CAM-1593."""
    value = value.upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9]+-\d+", value):
        raise argparse.ArgumentTypeError(f"not a Jira key: {value}")
    return value


def iso_date(value):
    """argparse type: a YYYY-MM-DD date."""
    try:
        datetime.date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a YYYY-MM-DD date: {value}") from None
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise argparse.ArgumentTypeError(f"not a YYYY-MM-DD date: {value}")
    return value


def link_id(value):
    """argparse type: a numeric link ID."""
    if not value.isdigit():
        raise argparse.ArgumentTypeError(f"not a link ID: {value}")
    return value


def build_parser():
    parser = argparse.ArgumentParser(
        prog="jira.py",
        description="Jira helpers for the CAM project. Writes print the HTTP status and verify "
                    "by reading back. Credentials: ~/.jira/netrc.",
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="<command>")

    def add(name, func, help_text):
        p = sub.add_parser(name, help=help_text, description=help_text)
        p.set_defaults(func=func)
        return p

    p = add("show", cmd_show, "Print a work item as plain text: fields, links with direction, description.")
    p.add_argument("key", type=issue_key)
    p.add_argument("--comments", action="store_true", help="also print every comment")

    p = add("links", cmd_links, "Print a work item's links with direction and link IDs.")
    p.add_argument("key", type=issue_key)

    p = add("set-dates", cmd_set_dates,
            "Set the start date (customfield_10504) and due date together. Refuses to overwrite "
            "a date another person set unless --force is given.")
    p.add_argument("key", type=issue_key)
    p.add_argument("start", type=iso_date, help="YYYY-MM-DD")
    p.add_argument("due", type=iso_date, help="YYYY-MM-DD")
    p.add_argument("--force", action="store_true", help="overwrite dates another person set")

    p = add("set-parent", cmd_set_parent, "Move a work item under another Epic.")
    p.add_argument("key", type=issue_key)
    p.add_argument("epic", type=issue_key)

    p = add("assign", cmd_assign, "Assign a work item to a person by display name (or part of it), or @me.")
    p.add_argument("key", type=issue_key)
    p.add_argument("who", help='display name, e.g. "Irene Garousi-Nejad", or @me')

    p = add("block", cmd_block,
            "Create a Blocks link: BLOCKER blocks BLOCKED (BLOCKED cannot start until BLOCKER is "
            "done). Warns if BLOCKER is due after BLOCKED starts.")
    p.add_argument("blocker", type=issue_key)
    p.add_argument("blocked", type=issue_key)

    p = add("unlink", cmd_unlink, "Delete a link by ID (shown by `links` and `show`).")
    p.add_argument("link_id", type=link_id)

    p = add("comment", cmd_comment,
            "Post a plain-text file as a comment. Blank lines separate paragraphs; lines starting "
            '"- " or "1. " form lists.')
    p.add_argument("key", type=issue_key)
    p.add_argument("file", help="path to a UTF-8 text file, or - for stdin")

    p = add("epics", cmd_epics,
            "List Epics under CAM-969, CAM-1551, and CAM-974 in Rank order with dates and leads, "
            "then report missing dates and Blocks conflicts.")
    p.add_argument("--all", action="store_true", help="include Done and Won't Do Epics")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except JiraError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
