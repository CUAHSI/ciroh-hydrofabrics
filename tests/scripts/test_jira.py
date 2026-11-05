"""Offline tests for scripts/jira.py: no network, no credentials.

Run with `python3 -m unittest discover -s tests/scripts -v` (or pytest).
"""

import importlib.util
import pathlib
import unittest

# Load scripts/jira.py by path under a distinct name, so it never collides
# with a `jira` package installed in the environment.
_PATH = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "jira.py"
_SPEC = importlib.util.spec_from_file_location("jira_script", _PATH)
jira = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(jira)


def text(value, marks=None):
    node = {"type": "text", "text": value}
    if marks:
        node["marks"] = [{"type": m} for m in marks]
    return node


def para(*nodes):
    return {"type": "paragraph", "content": list(nodes)}


def bullets(*items):
    return {"type": "bulletList", "content": [{"type": "listItem", "content": list(i)} for i in items]}


def doc(*blocks):
    return {"type": "doc", "version": 1, "content": list(blocks)}


def blocks_link(link_id, other, side):
    """A Blocks link as it appears in an item's issuelinks."""
    return {
        "id": link_id,
        "type": {"name": "Blocks", "inward": "is blocked by", "outward": "blocks"},
        side: {"key": other, "fields": {"summary": f"Item {other}", "status": {"name": "To Do"}}},
    }


class AdfToText(unittest.TestCase):
    def test_paragraphs_headings_and_breaks(self):
        body = doc(
            {"type": "heading", "attrs": {"level": 2}, "content": [text("Outcome")]},
            para(text("First line"), {"type": "hardBreak"}, text("second line")),
            para(text("Run "), text("dvc repro", ["code"]), text(" then "), text("check", ["strong"])),
        )
        self.assertEqual(
            jira.adf_to_text(body),
            "## Outcome\n\nFirst line\nsecond line\n\nRun `dvc repro` then check",
        )

    def test_nested_and_numbered_lists(self):
        body = doc(
            bullets(
                [para(text("Epic A"))],
                [para(text("Epic B")), bullets([para(text("Story B1"))])],
            ),
            {"type": "orderedList", "attrs": {"order": 3},
             "content": [{"type": "listItem", "content": [para(text("third"))]}]},
        )
        self.assertEqual(jira.adf_to_text(body), "- Epic A\n- Epic B\n  - Story B1\n\n3. third")

    def test_mentions_cards_and_empty(self):
        body = doc(para(
            {"type": "mention", "attrs": {"text": "@Tony"}},
            text(" see "),
            {"type": "inlineCard", "attrs": {"url": "https://example.org/x"}},
        ))
        self.assertEqual(jira.adf_to_text(body), "@Tony see https://example.org/x")
        self.assertEqual(jira.adf_to_text(None), "")


class TextToAdf(unittest.TestCase):
    def test_blocks_lists_and_line_breaks(self):
        adf = jira.text_to_adf("Merged in #43.\nChecks passed.\n\n- one\n- two\n\n1. first\n2. second\n")
        kinds = [b["type"] for b in adf["content"]]
        self.assertEqual(kinds, ["paragraph", "bulletList", "orderedList"])
        self.assertEqual(adf["content"][0]["content"][1], {"type": "hardBreak"})

    def test_round_trip(self):
        source = "Resolution.\nSecond line.\n\n- Epic A\n- Epic B\n\n1. first\n2. second"
        self.assertEqual(jira.adf_to_text(jira.text_to_adf(source)), source)


class Links(unittest.TestCase):
    def test_direction_from_the_viewed_item(self):
        links = [blocks_link("11", "CAM-2", "outwardIssue"), blocks_link("12", "CAM-3", "inwardIssue")]
        lines = jira.link_lines(links)
        self.assertTrue(lines[0].startswith("blocks CAM-2 "))
        self.assertTrue(lines[1].startswith("is blocked by CAM-3 "))
        self.assertIn("[link 12]", lines[1])

    def test_blockers_of_only_counts_inward_blocks(self):
        relates = {"id": "13", "type": {"name": "Relates", "inward": "relates to", "outward": "relates to"},
                   "inwardIssue": {"key": "CAM-4"}}
        links = [blocks_link("11", "CAM-2", "outwardIssue"), blocks_link("12", "CAM-3", "inwardIssue"), relates]
        self.assertEqual(jira.blockers_of(links), {"CAM-3": "12"})


class Conflicts(unittest.TestCase):
    def test_blocker_due_after_blocked_start(self):
        dates = {"CAM-1": (None, "2027-02-12"), "CAM-2": ("2027-02-01", None), "CAM-3": ("2027-02-12", None)}
        conflicts = jira.find_conflicts(dates, [("CAM-1", "CAM-2"), ("CAM-1", "CAM-3")])
        # Due on the blocked item's start date is allowed ("on or before").
        self.assertEqual(conflicts, ["CAM-1 (due 2027-02-12) blocks CAM-2 (starts 2027-02-01)"])

    def test_missing_dates_are_not_conflicts(self):
        self.assertEqual(jira.find_conflicts({"CAM-1": (None, None)}, [("CAM-1", "CAM-2")]), [])


class LastSetter(unittest.TestCase):
    def test_latest_change_to_the_field_wins(self):
        histories = [
            {"author": {"accountId": "a"}, "created": "2026-10-01", "items": [{"fieldId": "duedate"}]},
            {"author": {"accountId": "b"}, "created": "2026-10-02", "items": [{"fieldId": "customfield_10504"}]},
            {"author": {"accountId": "c"}, "created": "2026-10-03", "items": [{"fieldId": "duedate"}]},
        ]
        self.assertEqual(jira.last_setter(histories, "duedate")[0]["accountId"], "c")
        self.assertEqual(jira.last_setter(histories, jira.START_FIELD)[0]["accountId"], "b")
        self.assertIsNone(jira.last_setter(histories, "summary"))


class PickUser(unittest.TestCase):
    PEOPLE = [
        {"accountId": "1", "displayName": "Irene Garousi-Nejad", "accountType": "atlassian", "active": True},
        {"accountId": "2", "displayName": "Irene Smith", "accountType": "atlassian", "active": True},
        {"accountId": "3", "displayName": "Automation", "accountType": "app", "active": True},
    ]

    def test_exact_name_wins_over_partial_matches(self):
        self.assertEqual(jira.pick_user(self.PEOPLE, "irene garousi-nejad")["accountId"], "1")

    def test_ambiguous_and_missing(self):
        with self.assertRaises(jira.JiraError):
            jira.pick_user(self.PEOPLE, "Irene")
        with self.assertRaises(jira.JiraError):
            jira.pick_user(self.PEOPLE[2:], "Automation")


class Arguments(unittest.TestCase):
    def test_keys_dates_and_link_ids_are_validated(self):
        parser = jira.build_parser()
        args = parser.parse_args(["set-dates", "cam-1593", "2027-01-04", "2027-02-12"])
        self.assertEqual(args.key, "CAM-1593")
        for bad in (["show", "CAM-1593/../x"], ["set-dates", "CAM-1", "2027-1-4", "2027-02-12"],
                    ["unlink", "12a"]):
            with self.assertRaises(SystemExit):
                parser.parse_args(bad)


if __name__ == "__main__":
    unittest.main()
