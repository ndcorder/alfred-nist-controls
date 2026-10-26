"""Run: /usr/bin/python3 -B -m unittest test_sp171  (from this folder)"""
import unittest

import sp171


def r3(rid, title="T", statement="S", sources=(), withdrawn=None):
    return {"id": rid, "rev": "R3", "title": title, "statement": statement, "guidance": "",
            "sources": list(sources), "via": None, "withdrawn": withdrawn, "url": "r3:" + rid}


def r2(rid, statement="S", via=(), sources=(), r3_id=None):
    return {"id": rid, "rev": "R2", "title": statement, "statement": statement, "guidance": "",
            "sources": list(sources), "via": list(via), "withdrawn": None, "r3": r3_id, "url": "r2:" + rid}


REQS = [
    r2("3.1.1", "Limit system access to authorized users.", via=["03.01.01"], sources=["AC-2", "AC-3"],
       r3_id="03.01.01"),
    r3("03.01.01", "Account Management", sources=["AC-2", "AC-2(3)"]),
    r2("3.1.10", "Use session lock.", via=["03.01.10"], sources=["AC-11"], r3_id="03.01.10"),
    r3("03.01.10", "Device Lock", sources=["AC-11"]),
    r2("3.5.6", "Disable identifiers after inactivity.", r3_id="03.05.06"),
    r3("03.05.06", "Withdrawn", statement="", withdrawn=[]),
    r2("3.12.4", "Develop system security plans.", via=["03.15.02"], sources=["PL-2"], r3_id="03.12.04"),
    r3("03.12.04", "Withdrawn", statement="", withdrawn=[{"rel": "incorporated into", "id": "03.15.02"}]),
]


def ids(hits):
    return [(r["id"], r["rev"]) for r in hits]


class RequirementIds(unittest.TestCase):
    # CMMC paperwork cites R2 (3.1.1); NIST's R3 uses zero-padded 03.01.01.
    # Either spelling must show both revisions side by side.
    def test_both_spellings_find_both_revisions(self):
        for q in ("3.1.1", "03.01.01", "3 1 1", " 3.1.1 "):
            self.assertEqual(ids(sp171.search(REQS, q)), [("3.1.1", "R2"), ("03.01.01", "R3")], q)

    def test_number_match_is_exact_not_prefix(self):
        # 3.1.1 must not also return 3.1.10.
        self.assertNotIn(("3.1.10", "R2"), ids(sp171.search(REQS, "3.1.1")))
        self.assertEqual(ids(sp171.search(REQS, "3.1.10")), [("3.1.10", "R2"), ("03.01.10", "R3")])

    def test_family_query_lists_the_family_in_both_spellings(self):
        family = [("3.1.1", "R2"), ("03.01.01", "R3"), ("3.1.10", "R2"), ("03.01.10", "R3")]
        for q in ("3.1", "03.01", "3.1.", "03.01.0"):  # the last two are half-typed
            self.assertEqual(ids(sp171.search(REQS, q)), family, q)

    def test_parse_id(self):
        self.assertEqual(sp171.parse_id("03.12.04"), (12, 4))
        self.assertEqual(sp171.parse_id("3"), (None, None))
        self.assertIsNone(sp171.parse_id("3des"))
        self.assertIsNone(sp171.parse_id("ac-2"))

    def test_words_fall_back_to_text_search(self):
        self.assertEqual(ids(sp171.search(REQS, "session lock")), [("3.1.10", "R2")])
        self.assertEqual(ids(sp171.search(REQS, "device")), [("03.01.10", "R3")])


class ViaR3Labelling(unittest.TestCase):
    # R2 sources are borrowed from R3. Wherever they show or get copied, they must
    # say so, or they read as an official NIST R2 mapping.
    def test_r2_subtitle_and_copy_say_via_r3(self):
        it = sp171.item(REQS[0])
        self.assertEqual(it["subtitle"], "800-53 via R3 03.01.01: AC-2, AC-3")
        self.assertEqual(it["mods"]["alt"]["arg"], "AC-2, AC-3 (via R3 03.01.01; not an official NIST mapping)")
        self.assertIn("(R2)", it["title"])

    def test_r3_sources_are_shown_as_nists_own(self):
        it = sp171.item(REQS[1])
        self.assertEqual(it["subtitle"], "800-53: AC-2, AC-2(3)")
        self.assertNotIn("via", it["mods"]["alt"]["arg"])
        self.assertEqual(it["title"], "03.01.01 (R3)  Account Management")

    def test_r2_bridged_through_withdrawn_r3_names_the_live_target(self):
        # 3.12.4 -> 03.12.04 (withdrawn) -> 03.15.02: the label must name 03.15.02.
        self.assertEqual(sp171.item(REQS[6])["subtitle"], "800-53 via R3 03.15.02: PL-2")

    def test_r2_without_r3_counterpart_shows_none_not_a_guess(self):
        it = sp171.item(REQS[4])
        self.assertIn("none", it["subtitle"])
        self.assertIn("03.05.06 withdrawn", it["subtitle"])
        self.assertFalse(it["mods"]["alt"]["valid"])

    def test_withdrawn_r3_shows_where_it_went(self):
        it = sp171.item(REQS[7])
        self.assertEqual(it["subtitle"], "Withdrawn in R3 → incorporated into 03.15.02")
        self.assertFalse(it["mods"]["alt"]["valid"])
        self.assertEqual(sp171.item(REQS[5])["subtitle"], "Withdrawn in R3 → no replacement listed")

    def test_copy_has_id_title_and_statement(self):
        self.assertEqual(sp171.item(REQS[1])["arg"], "03.01.01 Account Management\n\nS")
        # R2 has no titles: do not paste the requirement twice.
        self.assertEqual(sp171.item(REQS[0])["arg"], "3.1.1 Limit system access to authorized users.")

    def test_cmd_opens_the_revision_specific_page(self):
        self.assertEqual(sp171.item(REQS[0])["mods"]["cmd"]["arg"], "r2:3.1.1")
        self.assertEqual(sp171.item(REQS[1])["mods"]["cmd"]["arg"], "r3:03.01.01")


class Respond(unittest.TestCase):
    def test_withdrawn_sort_last(self):
        items = sp171.respond({"r171": REQS}, "3.12.4")
        self.assertEqual([i["uid"] for i in items], ["171-R2-3.12.4", "171-R3-03.12.04"])
        items = sp171.respond({"r171": REQS}, "3.5.6")
        self.assertEqual(items[-1]["uid"], "171-R3-03.05.06")

    def test_old_index_without_171_data_explains(self):
        items = sp171.respond({"version": "5.2.0", "controls": []}, "3.1.1")
        self.assertEqual(len(items), 1)
        self.assertFalse(items[0]["valid"])

    def test_no_match_is_valid_json_item(self):
        items = sp171.respond({"r171": REQS}, "zzzz")
        self.assertEqual(len(items), 1)
        self.assertFalse(items[0]["valid"])


if __name__ == "__main__":
    unittest.main()
