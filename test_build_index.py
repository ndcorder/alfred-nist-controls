"""Run: /usr/bin/python3 -B -m unittest test_build_index  (from this folder). No network."""
import contextlib
import io
import json
import os
import plistlib
import tempfile
import unittest
import zipfile
from unittest import mock
from xml.sax.saxutils import escape

import build_index as b
import ctl

HERE = os.path.dirname(os.path.abspath(__file__))


def make_xlsx(sheets):
    """Minimal xlsx with shared strings: {sheet name: [[cell, ...], ...]}."""
    strings = []

    def sid(v):
        if v not in strings:
            strings.append(v)
        return strings.index(v)

    def col(i):
        s = ""
        i += 1
        while i:
            i, r = divmod(i - 1, 26)
            s = chr(65 + r) + s
        return s

    sheet_xml = []
    for rows in sheets.values():
        out = []
        for r, row in enumerate(rows, 1):
            cells = ""
            for c, v in enumerate(row):
                if v == "":
                    continue
                ref = "%s%d" % (col(c), r)
                cells += '<c r="%s" t="s"><v>%d</v></c>' % (ref, sid(v))
            out.append('<row r="%d">%s</row>' % (r, cells))
        sheet_xml.append(out)
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    rns = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/workbook.xml", '<workbook %s %s><sheets>%s</sheets></workbook>' % (ns, rns, "".join(
            '<sheet name="%s" sheetId="%d" r:id="rId%d"/>' % (escape(n), i, i) for i, n in enumerate(sheets, 1))))
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">%s'
                   '</Relationships>' % "".join('<Relationship Id="rId%d" Target="worksheets/sheet%d.xml"/>' % (i, i)
                                                for i in range(1, len(sheets) + 1)))
        for i, rows in enumerate(sheet_xml, 1):
            z.writestr("xl/worksheets/sheet%d.xml" % i, '<worksheet %s><sheetData>%s</sheetData></worksheet>'
                       % (ns, "".join(rows)))
        z.writestr("xl/sharedStrings.xml", '<sst %s>%s</sst>' % (ns, "".join(
            '<si><t xml:space="preserve">%s</t></si>' % escape(s) for s in strings)))
    return buf.getvalue()


def csf_sheet(n_subcats=60, refs_per=10):
    """A 'CSF 2.0' sheet shaped like NIST's export, with n_subcats * refs_per 800-53 pairs."""
    rows = [["", "The NIST Cybersecurity Framework 2.0", "", "", ""],
            ["Function", "Category", "Subcategory", "Implementation Examples", "Informative References"]]
    for i in range(n_subcats):
        refs = ["SP 800-53 Rev 5.1.1: XX-01", "CIS Controls v8.1: 1.1"]
        refs += ["SP 800-53 Rev 5.2.0: AC-%02d" % (j + 1) for j in range(refs_per)]
        rows.append(["", "", "PR.AA-%02d: Subcategory %d" % (i + 1, i), "Ex1: example", "\n".join(refs)])
    return rows


class Xlsx(unittest.TestCase):
    def test_reads_shared_strings_and_column_positions(self):
        data = make_xlsx({"S": [["a", "", "c"], ["", "b"]]})
        self.assertEqual(b.read_xlsx(data), {"S": [["a", "", "c"], ["", "b"]]})

    def test_not_an_xlsx_fails_loudly(self):
        # The CSF endpoint returning an HTML error page must not become an empty crosswalk.
        with self.assertRaises(b.BuildError):
            b.read_xlsx(b"<html>Service unavailable</html>")


class CsfCrosswalk(unittest.TestCase):
    def test_pairs_come_only_from_the_5_2_0_lines(self):
        subcats, pairs, _ = b.parse_csf(b.read_xlsx(make_xlsx({"CSF 2.0": csf_sheet()})))
        self.assertEqual(len(pairs), 600)
        self.assertIn(("PR.AA-01", "AC-1"), pairs)  # zero-padded AC-01 -> index form AC-1
        self.assertNotIn("XX-1", {c for _, c in pairs})  # Rev 5.1.1 lines ignored
        self.assertEqual(subcats["PR.AA-01"], "Subcategory 0")

    def test_family_only_reference_is_skipped_not_linked(self):
        rows = csf_sheet()
        rows[2][4] += "\nSP 800-53 Rev 5.2.0: IR"
        _, pairs, family_only = b.parse_csf(b.read_xlsx(make_xlsx({"CSF 2.0": rows})))
        self.assertEqual(family_only, ["PR.AA-01 -> IR"])
        self.assertNotIn("IR", {c for _, c in pairs})

    def test_malformed_csf_sheet_fails_loudly(self):
        # Each of these would silently empty the CSF crosswalk if accepted.
        cases = {
            "renamed sheet": {"Core": csf_sheet()},
            "renamed column": {"CSF 2.0": [r[:4] + [r[4]] for r in csf_sheet()[:1]]
                               + [["Function", "Category", "Subcategory", "Examples", "References"]]
                               + csf_sheet()[2:]},
            "too few pairs": {"CSF 2.0": csf_sheet(n_subcats=10)},
        }
        for name, sheets in cases.items():
            with self.assertRaises(b.BuildError, msg=name):
                b.parse_csf(b.read_xlsx(make_xlsx(sheets)))

    def test_new_800_53_release_label_is_reported(self):
        rows = [r[:4] + [r[4].replace("Rev 5.2.0", "Rev 5.3.0")] for r in csf_sheet()]
        with self.assertRaises(b.BuildError) as cm:
            b.parse_csf(b.read_xlsx(make_xlsx({"CSF 2.0": rows})))
        self.assertIn("SP 800-53 Rev 5.3.0", str(cm.exception))


def cis_sheet(n=120):
    rows = [["CIS Control", "CIS Safeguard", "Asset Type", "Security Function", "Title", "Description",
             "IG1", "IG2", "IG3", "Relationship", "Control Identifier", "Control or Control Enhancement Name"],
            ["6", "", "", "", "Access Control Management", "", "", "", "", "", "", ""]]
    for i in range(n):
        sg = "6.%d" % (i % 12 + 1)
        rows.append(["6", sg, "Users", "Protect", "Safeguard " + sg, "", "x", "x", "x", "Subset",
                     "AC-%d" % (i + 1), "Name"])
    rows.append(["6", "6.5", "Users", "Protect", "Safeguard 6.5", "", "", "", "", "", "", ""])  # unmapped
    return rows


class CisCrosswalk(unittest.TestCase):
    def test_missing_file_is_skipped_with_a_note(self):
        # CIS is licensed: the user downloads it himself, so absence is normal.
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertIsNone(b.load_cis("/nonexistent/cis.xlsx"))
        self.assertIn("skipping CIS", out.getvalue())

    def test_local_file_is_parsed(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "cis.xlsx")
            with open(path, "wb") as f:
                f.write(make_xlsx({"Introduction": [["About"]], "All CIS Controls & Safeguards": cis_sheet()}))
            titles, pairs = b.load_cis(path)
        self.assertEqual(titles["6.10"], "Safeguard 6.10")
        self.assertIn(("6.1", "AC-1"), pairs)
        self.assertEqual(len(pairs), 120)

    def test_safeguard_ids_read_as_numbers_fail_loudly(self):
        # 6.10 stored as a number reads back as 6.1 and would merge two safeguards.
        rows = cis_sheet()
        for r in rows[2:-1]:
            if r[1] == "6.10":
                r[1] = "6.1"  # what a numeric cell 6.10 reads back as
        with self.assertRaises(b.BuildError):
            b.parse_cis(b.read_xlsx(make_xlsx({"Map": rows})))

    def test_sheet_without_expected_columns_fails_loudly(self):
        with self.assertRaises(b.BuildError):
            b.parse_cis(b.read_xlsx(make_xlsx({"Map": [["Safeguard", "NIST"]]})))


def r3_req(rid, title, sources=(), withdrawn=None):
    return {"id": rid, "rev": "R3", "title": title, "statement": "", "guidance": "",
            "sources": list(sources), "via": None, "withdrawn": withdrawn, "url": ""}


class R2Bridge(unittest.TestCase):
    R3 = [
        r3_req("03.01.01", "Account Management", ["AC-2", "AC-2(3)"]),
        r3_req("03.12.04", "Withdrawn", withdrawn=[{"rel": "incorporated into", "id": "03.15.02"}]),
        r3_req("03.15.02", "System Security Plan", ["PL-2"]),
        r3_req("03.05.06", "Withdrawn", withdrawn=[]),
    ]

    def bridge(self, sort):
        return b.bridge_r2([{"id": "r2", "rev": "R2", "sort": sort}], self.R3)[0]

    def test_same_sort_id_borrows_r3_sources(self):
        r = self.bridge("03.01.01")
        self.assertEqual((r["via"], r["sources"]), (["03.01.01"], ["AC-2", "AC-2(3)"]))

    def test_withdrawn_r3_counterpart_is_followed_to_live_target(self):
        # 3.12.4 -> 03.12.04 (withdrawn, incorporated into 03.15.02).
        r = self.bridge("03.12.04")
        self.assertEqual((r["via"], r["sources"], r["r3"]), (["03.15.02"], ["PL-2"], "03.12.04"))

    def test_withdrawn_without_replacement_gives_no_sources(self):
        r = self.bridge("03.05.06")
        self.assertEqual((r["via"], r["sources"]), ([], []))

    def test_missing_r3_counterpart_does_not_crash(self):
        r = self.bridge("03.99.99")
        self.assertEqual((r["via"], r["sources"]), ([], []))

    def test_link_cycle_terminates(self):
        r3 = [r3_req("03.01.01", "W", withdrawn=[{"rel": "x", "id": "03.01.02"}]),
              r3_req("03.01.02", "W", withdrawn=[{"rel": "x", "id": "03.01.01"}])]
        self.assertEqual(b.bridge_r2([{"id": "3.1.1", "rev": "R2", "sort": "03.01.01"}], r3)[0]["via"], [])


class R3Catalog(unittest.TestCase):
    CATALOG = {
        "groups": [{"id": "f", "title": "Access Control", "controls": [
            {"id": "SP_800_171_03.01.01", "class": "requirement", "title": "Account Management",
             "props": [{"name": "sort-id", "value": "03.01.01"}],
             "params": [{"id": "A.03.01.01.ODP.01", "label": "time period"}],
             "links": [{"href": "#u1", "rel": "reference"}, {"href": "#u2", "rel": "reference"},
                       {"href": "#u3", "rel": "reference"}],
             "parts": [{"name": "statement", "parts": [
                 {"name": "item", "props": [{"name": "label", "value": "SR-03.01.01.a"}],
                  "prose": "Disable after {{ insert: param, A.03.01.01.ODP.01 }}:",
                  "parts": [{"name": "item", "props": [{"name": "label", "value": "SR-03.01.01.a.01"}],
                             "prose": "Expired accounts."}]}]},
                 {"name": "guidance", "prose": "See [](#/cprt/x?element=03.01.02)03.01.02."}]},
            {"id": "SP_800_171_03.01.13", "class": "requirement", "title": "03.01.13",
             "props": [{"name": "sort-id", "value": "03.01.13"}, {"name": "status", "value": "withdrawn"}],
             "links": [{"href": "03.13.08", "rel": "addressed_by"}]},
        ]}],
        "back-matter": {"resources": [{"uuid": "u1", "title": "AC-02"}, {"uuid": "u2", "title": "AC-02(03)"},
                                      {"uuid": "u3", "title": "SP 800-113"}]},
    }

    def test_sources_are_control_references_only(self):
        reqs = b.parse_r3(self.CATALOG)
        self.assertEqual(reqs[0]["sources"], ["AC-2", "AC-2(3)"])  # "SP 800-113" is a document, not a control

    def test_statement_reads_like_the_publication(self):
        req = b.parse_r3(self.CATALOG)[0]
        self.assertEqual(req["statement"],
                         "a. Disable after [Assignment: organization-defined time period]:\n  1. Expired accounts.")
        self.assertEqual(req["guidance"], "See 03.01.02.")  # CPRT link markup stripped
        self.assertTrue(req["url"].endswith("SP_800_171_3_0_0/home?element=03.01.01"))

    def test_withdrawn_keeps_its_destination(self):
        req = b.parse_r3(self.CATALOG)[1]
        self.assertEqual(req["withdrawn"], [{"rel": "addressed by", "id": "03.13.08"}])
        self.assertEqual(req["sources"], [])

    def test_catalog_far_from_expected_size_fails_loudly(self):
        with self.assertRaises(b.BuildError):
            b.check_r3(b.parse_r3(self.CATALOG))


class R2Csv(unittest.TestCase):
    HEAD = "﻿Family,Basic/Derived Security Requirement,Identifier,Sort-As, Security Requirement,Discussion\n"

    def test_parses_nist_csv_with_bom_and_padded_header(self):
        rows = "".join('Access Control,Basic,3.1.%d,03.01.%02d,"Req %d","Disc"\n' % (i, i, i) for i in range(1, 111))
        reqs = b.parse_r2((self.HEAD + rows).encode("utf-8").decode("utf-8-sig"))
        self.assertEqual(reqs[0]["id"], "3.1.1")
        self.assertEqual(reqs[0]["statement"], "Req 1")
        self.assertTrue(reqs[0]["url"].endswith("SP_800_171_2_0_0/home?element=3.1.1"))

    def test_wrong_requirement_count_fails_loudly(self):
        with self.assertRaises(b.BuildError):
            b.parse_r2(self.HEAD.lstrip("﻿") + 'Access Control,Basic,3.1.1,03.01.01,"Req","Disc"\n')

    def test_changed_columns_fail_loudly(self):
        with self.assertRaises(b.BuildError):
            b.parse_r2("Family,ID,Text\nAC,3.1.1,x\n")


class Merge(unittest.TestCase):
    def test_crosswalk_ids_land_on_controls_and_unknowns_are_reported(self):
        controls = [{"id": "AC-2"}, {"id": "IA-5"}]
        r171 = [{"id": "03.01.01", "rev": "R3", "sources": ["AC-2", "ZZ-9"]},
                {"id": "3.1.1", "rev": "R2", "sources": ["AC-2"]}]
        unresolved = b.merge_crosswalks(controls, r171, [("PR.AA-05", "AC-2"), ("PR.AA-01", "AC-2")])
        self.assertEqual(controls[0], {"id": "AC-2", "r171": ["03.01.01"], "r2": ["3.1.1"],
                                       "csf": ["PR.AA-01", "PR.AA-05"]})  # no "cis": it is licensed
        self.assertEqual(unresolved, ["r171 03.01.01 -> ZZ-9"])

    def test_cis_index_is_separate_and_numerically_sorted(self):
        controls = [{"id": "AC-2"}, {"id": "IA-5"}]
        data, unresolved = b.cis_index(controls, {"6.2": "A", "6.10": "B"},
                                       [("6.10", "IA-5"), ("6.2", "IA-5"), ("6.2", "ZZ-9")])
        self.assertEqual(data, {"safeguards": {"6.2": "A", "6.10": "B"}, "controls": {"IA-5": ["6.2", "6.10"]}})
        self.assertEqual(unresolved, ["cis 6.2 -> ZZ-9"])
        self.assertEqual(controls, [{"id": "AC-2"}, {"id": "IA-5"}])  # controls untouched

    def test_short_id(self):
        self.assertEqual(b.short_id("AC-02(03)"), "AC-2(3)")
        self.assertEqual(b.short_id("SC-10"), "SC-10")
        self.assertEqual(b.short_id("cm-8(1)"), "CM-8(1)")
        self.assertIsNone(b.short_id("IR"))
        self.assertIsNone(b.short_id("SP 800-113"))


class CisPath(unittest.TestCase):
    # The build runs from a terminal, where Alfred's Configure Workflow values are not in the
    # environment, so it also reads them from prefs.plist.
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.prefs = os.path.join(self.dir.name, "prefs.plist")
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(self.dir.cleanup)
        os.environ.pop("CIS_XLSX", None)

    def write_prefs(self, value):
        with open(self.prefs, "wb") as f:
            plistlib.dump({"CIS_XLSX": value}, f)

    def test_environment_wins_over_configure_workflow(self):
        self.write_prefs("/prefs/cis.xlsx")
        os.environ["CIS_XLSX"] = "/env/cis.xlsx"
        self.assertEqual(b.cis_path(self.prefs), "/env/cis.xlsx")

    def test_configure_workflow_value_is_used_and_tilde_expanded(self):
        self.write_prefs("~/Downloads/cis.xlsx")
        self.assertEqual(b.cis_path(self.prefs), os.path.expanduser("~/Downloads/cis.xlsx"))

    def test_unset_means_no_cis(self):
        self.assertEqual(b.cis_path(self.prefs), "")  # no prefs.plist
        self.write_prefs("")
        self.assertEqual(b.cis_path(self.prefs), "")  # empty default from Configure Workflow
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertIsNone(b.load_cis(""))
        self.assertIn("CIS_XLSX is not set", out.getvalue())


def keys_in(obj):
    """Every dict key anywhere in a JSON value."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from keys_in(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from keys_in(v)


def oscal_control(cid, label, title, children=()):
    return {"id": cid, "title": title, "props": [{"name": "label", "value": label}],
            "parts": [{"name": "statement", "prose": title + " statement."}], "controls": list(children)}


CIS_TITLE = "Require MFA for Made-Up Test Applications"  # must never reach controls.json
SOURCES = {
    b.CATALOG: {"catalog": {"metadata": {"version": "5.2.0"}, "groups": [
        {"id": "ac", "title": "Access Control", "controls": [
            oscal_control("ac-2", "AC-2", "Account Management",
                          [oscal_control("ac-2.1", "AC-2(1)", "Automated System Account Management")])]},
        {"id": "ia", "title": "Identification and Authentication", "controls": [
            oscal_control("ia-5", "IA-5", "Authenticator Management")]}]}},
    b.R3_CATALOG: {"catalog": {"groups": [{"id": "f", "title": "Access Control", "controls": [
        {"id": "r", "class": "requirement", "title": "Account Management",
         "props": [{"name": "sort-id", "value": "03.01.01"}], "links": [{"href": "#u1", "rel": "reference"}],
         "parts": [{"name": "statement", "prose": "Manage accounts."}]}]}],
        "back-matter": {"resources": [{"uuid": "u1", "title": "AC-02"}]}}},
    b.R2_CSV: ("Family,Basic/Derived Security Requirement,Identifier,Sort-As,Security Requirement,Discussion\n"
               'Access Control,Basic,3.1.1,03.01.01,"Limit access.","Disc"\n').encode(),
    b.CSF_XLSX: make_xlsx({"CSF 2.0": [
        ["Function", "Category", "Subcategory", "Implementation Examples", "Informative References"],
        ["", "", "PR.AA-05: Access permissions are managed", "",
         "SP 800-53 Rev 5.2.0: AC-02\nCIS Controls v8.1: 6.3"]]}),
}
SOURCES.update({url: {"profile": {"imports": [{"include-controls": [{"with-ids": ["ac-2"]}]}]}}
                for url in b.BASELINES.values()})
CIS_XLSX = make_xlsx({"Mapping": [
    ["CIS Control", "CIS Safeguard", "Title", "Control Identifier"],
    ["6", "6.1", "Establish an Access Granting Process", "AC-02"],
    ["6", "6.3", CIS_TITLE, "IA-05"],
    ["6", "6.3", CIS_TITLE, "AC-02(01)"]]})


class CisStaysOutOfControlsJson(unittest.TestCase):
    # The CIS v8.1 mapping is CC BY-NC-ND 4.0. controls.json is committed and shipped in the
    # release, so a single CIS ID or title in it would redistribute CIS's work. The build must
    # put CIS into cis.json (gitignored, excluded from the package) and nowhere else.
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        d = self.dir.name
        self.out, self.cis_out = os.path.join(d, "controls.json"), os.path.join(d, "cis.json")
        self.xlsx = os.path.join(d, "mapping.xlsx")
        with open(self.xlsx, "wb") as f:
            f.write(CIS_XLSX)
        for p in (
            mock.patch.multiple(b, OUT=self.out, CIS_OUT=self.cis_out, PREFS=os.path.join(d, "prefs.plist"),
                                MIN_80053_CONTROLS=1, R3_TOTAL=(1, 1), R3_LIVE=(1, 1), MIN_R3_PAIRS=1,
                                R2_TOTAL=1, MIN_CSF_PAIRS=1, MIN_CIS_PAIRS=1),
            mock.patch.object(b, "fetch", side_effect=lambda url: SOURCES[url]),
            mock.patch.object(b, "fetch_bytes", side_effect=lambda url: SOURCES[url]),
            mock.patch.dict(os.environ, {"CIS_XLSX": self.xlsx}),
        ):
            p.start()
            self.addCleanup(p.stop)

    def build(self):
        with contextlib.redirect_stdout(io.StringIO()):
            b.main()
        with open(self.out) as f:
            return f.read()

    def test_build_with_cis_file_keeps_cis_out_of_controls_json(self):
        raw = self.build()
        data = json.loads(raw)
        self.assertNotIn("cis", set(keys_in(data)))
        self.assertNotIn(CIS_TITLE, raw)
        self.assertNotIn("Establish an Access Granting Process", raw)
        self.assertEqual(data["controls"][0]["csf"], ["PR.AA-05"])  # the NIST crosswalk is still there
        with open(self.cis_out) as f:
            self.assertEqual(json.load(f)["controls"], {"AC-2": ["6.1"], "AC-2(1)": ["6.3"], "IA-5": ["6.3"]})

    def test_local_cis_json_still_drives_the_cis_lookup(self):
        # With his own CIS download built into cis.json, the user keeps "cis 6.3" and the crosswalk.
        self.build()
        data = ctl.load_index(self.out, self.cis_out)
        self.assertEqual([i.get("uid") for i in ctl.respond(data, "cis 6.3")][1:], ["AC-2(1)", "IA-5"])
        self.assertIn("CIS v8.1: 6.1", ctl.item(data["controls"][0])["mods"]["ctrl"]["arg"])
        self.assertIn("not indexed", ctl.respond(ctl.load_index(self.out, self.cis_out + ".none"), "cis 6")[0]["title"])

    def test_build_without_cis_file_keeps_an_existing_cis_json(self):
        self.build()
        os.environ["CIS_XLSX"] = ""
        self.assertNotIn("cis", set(keys_in(json.loads(self.build()))))
        self.assertTrue(os.path.isfile(self.cis_out))


class PublishedFiles(unittest.TestCase):
    # Guards on what is committed and packaged, for the same licence reason.
    def test_committed_controls_json_has_no_cis_data(self):
        with open(os.path.join(HERE, "controls.json")) as f:
            data = json.load(f)
        self.assertFalse("cis" in set(keys_in(data)), "controls.json has a 'cis' key: rebuild it")
        self.assertGreater(len(data["controls"]), 1000)  # the real index, not a stub

    def test_cis_json_is_gitignored_and_left_out_of_the_release_zip(self):
        with open(os.path.join(HERE, ".gitignore")) as f:
            self.assertIn("cis.json", f.read().split())
        with open(os.path.join(HERE, ".github", "workflows", "ci.yml")) as f:
            zip_line = next(line for line in f if "zip -r" in line)
        self.assertIn("'cis.json'", zip_line)


if __name__ == "__main__":
    unittest.main()
