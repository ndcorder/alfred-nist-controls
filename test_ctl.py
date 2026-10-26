"""Run: /usr/bin/python3 -B -m unittest test_ctl  (from this folder)"""
import io
import json
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import build_index
import ctl
import make_icons
import sp171


def control(cid, title="T", statement="", guidance="", withdrawn=None, **xw):
    c = {"id": cid, "title": title, "statement": statement, "guidance": guidance,
         "baselines": "", "withdrawn": withdrawn, "url": ""}
    c.update(xw)
    return c


CONTROLS = [
    control("AC-2", "Account Management"),
    control("AC-2(1)", "Account Management | Automated System Account Management"),
    control("AC-2(10)", "Account Management | Shared Account Credential Change", withdrawn=["AC-2"]),
    control("AC-11", "Device Lock", statement="Prevent access by initiating a device lock"),
    control("IA-2(1)", "Identification and Authentication | Multi-factor Authentication"),
]


def ids(hits):
    return [c["id"] for c in hits]


class ControlIdQueries(unittest.TestCase):
    # Questionnaires and auditors mix NIST's zero-padded IDs (AC-02(01)) with
    # the short form (AC-2(1)), so every spelling must land on the same control.
    def test_spellings_of_an_enhancement_find_it(self):
        for q in ("ac-2(1)", "AC-02(01)", "ac-2.1", "ac2 1", "ac 2(1)"):
            self.assertEqual(ids(ctl.search(CONTROLS, q)), ["AC-2(1)"], q)

    def test_half_typed_ids_keep_showing_the_control(self):
        # Results must not jump to unrelated text hits mid-keystroke.
        self.assertEqual(ids(ctl.search(CONTROLS, "ac-2(")), ["AC-2", "AC-2(1)", "AC-2(10)"])
        self.assertEqual(ids(ctl.search(CONTROLS, "ia-")), ["IA-2(1)"])

    def test_family_query_is_not_truncated(self):
        family = [control("AC-%d" % n) for n in range(1, 200)]
        self.assertEqual(len(ctl.search(family, "ac")), 199)

    def test_base_control_includes_its_enhancements(self):
        self.assertEqual(ids(ctl.search(CONTROLS, "ac-2")), ["AC-2", "AC-2(1)", "AC-2(10)"])

    def test_number_match_is_exact_not_prefix(self):
        # "ac-1" must not return AC-11.
        self.assertEqual(ids(ctl.search(CONTROLS, "ac-1")), [])

    def test_family_lists_whole_family(self):
        self.assertEqual(ids(ctl.search(CONTROLS, "ia")), ["IA-2(1)"])


class TextQueries(unittest.TestCase):
    def test_title_hits_rank_above_body_hits(self):
        cs = [control("XX-1", statement="uses lock screens"), control("XX-2", "Device Lock")]
        self.assertEqual(ids(ctl.search(cs, "lock")), ["XX-2", "XX-1"])

    def test_words_match_word_starts_not_substrings(self):
        cs = [control("XX-1", statement="block traffic"), control("XX-2", statement="session locks")]
        self.assertEqual(ids(ctl.search(cs, "lock")), ["XX-2"])

    def test_all_words_must_match(self):
        self.assertEqual(ids(ctl.search(CONTROLS, "multi-factor device")), [])


class StatementRendering(unittest.TestCase):
    # The copied statement is pasted into questionnaires, so ODPs must read the
    # way NIST prints them, not as raw OSCAL insert tags.
    def test_assignment_param(self):
        params = {"p1": {"id": "p1", "label": "frequency"}}
        self.assertEqual(build_index.fill("Review {{ insert: param, p1 }};", params),
                         "Review [Assignment: organization-defined frequency];")

    def test_label_already_prefixed_is_not_doubled(self):
        params = {"p1": {"id": "p1", "label": "organization-defined personnel or roles"}}
        self.assertEqual(build_index.fill("{{ insert: param, p1 }}", params),
                         "[Assignment: organization-defined personnel or roles]")

    def test_selection_param(self):
        params = {"p1": {"id": "p1", "select": {"how-many": "one-or-more", "choice": ["a", "b"]}}}
        self.assertEqual(build_index.fill("{{ insert: param, p1 }}", params),
                         "[Selection (one or more): a; b]")

    def test_withdrawn_link_uses_short_label(self):
        self.assertEqual(build_index.oscal_to_label("#ac-2.1_smt.k"), "AC-2(1)")


def index(controls, csf=None, cis=None):
    return {"version": "5.2.0", "controls": controls, "csf": csf or {}, "cis": cis}


MAPPED = [
    control("AC-2", "Account Management", r171=["03.01.01"], r2=["3.1.1"], csf=["PR.AA-01", "PR.AA-05"],
            cis=["5.1", "6.1"]),
    control("AC-3", "Access Enforcement", r171=["03.01.02"], csf=["PR.AA-05"], cis=["6.8"]),
    control("IA-2(1)", "Identification and Authentication | MFA", csf=["PR.AA-03"], cis=["6.3", "6.30"]),
    control("RA-4", "Risk Assessment Update", withdrawn=["RA-3"], csf=["PR.AA-05"]),
    control("IA-5", "Authenticator Management", cis=["6.10"]),
]
CSF = {"PR.AA-01": "Identities are managed", "PR.AA-03": "Users are authenticated",
       "PR.AA-05": "Access permissions are managed", "PR.AA-06": "Physical access is managed"}
CIS = {"5.1": "Account inventory", "6.1": "Access granting", "6.3": "Require MFA for external apps",
       "6.8": "RBAC", "6.10": "Not a real safeguard (tests 6.1 vs 6.10)", "6.30": "Fake"}


def uids(items):
    return [i.get("uid") for i in items if i.get("uid")]


class ReverseLookups(unittest.TestCase):
    # Questionnaires (HECVAT, CAIQ) cite CSF and CIS IDs; the user needs the
    # 800-53 controls behind them without leaving Alfred.
    def setUp(self):
        self.data = index(MAPPED, CSF, CIS)

    def test_csf_subcategory_lists_its_controls_in_any_spelling(self):
        for q in ("PR.AA-05", "pr.aa-5", "pr.aa-05 "):
            items = ctl.respond(self.data, q)
            self.assertIn("Access permissions are managed", items[0]["title"], q)
            self.assertEqual(uids(items), ["AC-2", "AC-3", "RA-4"], q)  # withdrawn last

    def test_csf_category_lists_every_subcategory(self):
        self.assertEqual(uids(ctl.respond(self.data, "pr.aa")), ["AC-2", "AC-3", "IA-2(1)", "RA-4"])

    def test_half_typed_csf_id_shows_category_not_nothing(self):
        self.assertEqual(uids(ctl.respond(self.data, "pr.aa-0")), uids(ctl.respond(self.data, "pr.aa")))

    def test_csf_subcategory_without_controls_says_so(self):
        items = ctl.respond(self.data, "pr.aa-06")
        self.assertEqual(uids(items), [])
        self.assertIn("No SP 800-53 controls", items[-1]["title"])

    def test_unknown_csf_id_is_a_message_not_a_crash(self):
        items = ctl.respond(self.data, "pr.zz-99")
        self.assertEqual(len(items), 1)
        self.assertFalse(items[0]["valid"])

    def test_cis_safeguard_match_is_exact(self):
        # "cis 6.1" must not pull in 6.10 (or 6.3 must not pull in 6.30).
        self.assertEqual(uids(ctl.respond(self.data, "cis 6.1")), ["AC-2"])
        self.assertEqual(uids(ctl.respond(self.data, "cis 6.3")), ["IA-2(1)"])
        self.assertIn("Require MFA", ctl.respond(self.data, "cis6.3")[0]["title"])

    def test_cis_control_lists_all_its_safeguards(self):
        self.assertEqual(uids(ctl.respond(self.data, "cis 6")), ["AC-2", "AC-3", "IA-2(1)", "IA-5"])

    def test_cis_not_indexed_explains_instead_of_failing(self):
        # CIS is optional (the user downloads the licensed file himself).
        for q in ("cis 6.3", "cis"):
            items = ctl.respond(index(MAPPED, CSF, None), q)
            self.assertEqual(len(items), 1)
            self.assertIn("not indexed", items[0]["title"])
            self.assertFalse(items[0]["valid"])

    def test_control_ids_still_win_over_reverse_lookups(self):
        self.assertEqual(uids(ctl.respond(self.data, "ac-2")), ["AC-2"])


class Crosswalk(unittest.TestCase):
    def test_subtitle_shows_first_mapped_id_and_count(self):
        sub = ctl.item(MAPPED[0])["subtitle"]
        self.assertIn("171 03.01.01", sub)
        self.assertIn("CSF PR.AA-01 +1", sub)
        self.assertIn("CIS 5.1 +1", sub)

    def test_full_crosswalk_labels_r2_as_unofficial(self):
        # R2 IDs are borrowed through R3; copying them unlabelled would overstate NIST's mapping.
        text = ctl.item(MAPPED[0])["mods"]["ctrl"]["arg"]
        self.assertIn("SP 800-171 R3: 03.01.01", text)
        self.assertIn("SP 800-171 R2 (via R3, not an official NIST mapping): 3.1.1", text)
        self.assertIn("CSF 2.0: PR.AA-01, PR.AA-05", text)
        self.assertIn("CIS v8.1: 5.1, 6.1", text)
        self.assertIn("CSF 2.0: PR.AA-01", ctl.item(MAPPED[0])["text"]["largetype"])
        self.assertIn("R2 via R3 1", ctl.item(MAPPED[0])["mods"]["ctrl"]["subtitle"])

    def test_control_without_mappings_disables_crosswalk_copy(self):
        mods = ctl.item(control("AC-99"))["mods"]
        self.assertFalse(mods["ctrl"]["valid"])
        self.assertEqual(ctl.item(control("AC-99"))["subtitle"], "[no baseline] ")

    def test_index_without_crosswalk_fields_still_works(self):
        # An index built by v1 has no r171/csf/cis keys.
        self.assertEqual(ctl.respond({"version": "5.2.0", "controls": CONTROLS}, "ac-11")[0]["uid"], "AC-11")
        self.assertEqual(len(ctl.respond({"version": "5.2.0", "controls": CONTROLS}, "pr.aa-05")), 1)


HERE = os.path.dirname(os.path.abspath(__file__))


def icon_of(it):
    return it["icon"]["path"]


def job_for(path):
    return next(j for j in make_icons.jobs() if j["out"] == os.path.join(HERE, path))


def contrast_with_white(hex_color):
    def lin(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return 1.05 / (0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b) + 0.05)


class Icons(unittest.TestCase):
    # The family monogram + colour lets the user scan a mixed result list by family, and grey
    # flags withdrawn items before he reads the subtitle. A missing file shows as a blank icon.
    @classmethod
    def setUpClass(cls):
        cls.data = ctl.load_index()

    def assertRendered(self, it):
        self.assertTrue(os.path.isfile(os.path.join(HERE, icon_of(it))), icon_of(it))

    def test_every_800_53_family_in_the_index_has_its_own_icon(self):
        for c in self.data["controls"]:
            code = c["id"].split("-")[0]
            self.assertEqual(ctl.FAMILIES.get(code), c["family"], c["id"])  # titles sp171 relies on
            it = ctl.item(c)
            self.assertRendered(it)
            self.assertIn(icon_of(it), ("icons/%s.png" % code.lower(), "icons/%s-wd.png" % code.lower()))

    def test_every_800_171_family_in_the_index_maps_to_an_800_53_family(self):
        # A NIST rename or a new 171-only family would fall back to the generic icon; catch it here.
        for r in self.data["r171"]:
            code = sp171.family_code(r["family"])
            self.assertIn(code, ctl.FAMILIES, "%s %s: %r" % (r["rev"], r["id"], r["family"]))
            self.assertRendered(sp171.item(r))

    def test_withdrawn_items_are_grey_live_items_have_the_family_colour(self):
        live, gone = ctl.item(control("AC-2")), ctl.item(control("AC-2(10)", withdrawn=["AC-2"]))
        self.assertEqual(icon_of(live), "icons/ac.png")
        self.assertEqual(icon_of(gone), "icons/ac-wd.png")
        self.assertEqual(job_for(icon_of(live))["bg"], make_icons.FAMILY_COLORS["AC"])
        self.assertEqual(job_for(icon_of(gone)), dict(job_for(icon_of(live)), out=job_for(icon_of(gone))["out"],
                                                      bg=make_icons.GREY))  # same monogram, grey
        r3 = {"id": "03.01.13", "rev": "R3", "title": "Withdrawn", "statement": "", "family": "Access Control",
              "sources": [], "via": None, "withdrawn": [{"rel": "addressed by", "id": "03.13.08"}], "url": ""}
        self.assertEqual(icon_of(sp171.item(r3)), "icons/ac-wd.png")

    def test_171_items_reuse_the_800_53_family_icon(self):
        def req(rev, family):
            return {"id": "3.1.1", "rev": rev, "title": "T", "statement": "S", "family": family,
                    "sources": [], "via": [], "withdrawn": None, "url": ""}
        cases = [("Access Control", "AC-2"), ("Incident response", "IR-4"),  # R2 spells it lower-case
                 ("Physical Protection", "PE-3"), ("Security Assessment", "CA-2"),
                 ("Security Assessment and Monitoring", "CA-2"), ("Supply Chain Risk Management", "SR-3")]
        for family, cid in cases:
            for rev in ("R2", "R3"):
                self.assertEqual(icon_of(sp171.item(req(rev, family))), icon_of(ctl.item(control(cid))),
                                 "%s %s" % (rev, family))

    def test_171_only_family_gets_a_generic_171_icon_not_a_wrong_family(self):
        r = {"id": "03.18.01", "rev": "R3", "title": "T", "statement": "S", "family": "Something New",
             "sources": ["AC-2"], "via": None, "withdrawn": None, "url": ""}
        self.assertEqual(icon_of(sp171.item(r)), "icons/171.png")
        self.assertEqual(icon_of(sp171.item(dict(r, withdrawn=[]))), "icons/171-wd.png")

    def test_csf_header_shows_its_function_and_cis_header_shows_cis(self):
        data = index(MAPPED + [control("SI-4", csf=["DE.CM-01"])], dict(CSF, **{"DE.CM-01": "Networks monitored"}),
                     CIS)
        for q, want in (("pr.aa-05", "icons/csf-pr.png"), ("pr.aa", "icons/csf-pr.png"),
                        ("de.cm-01", "icons/csf-de.png"), ("cis 6.3", "icons/cis.png"), ("cis 6", "icons/cis.png")):
            items = ctl.respond(data, q)
            self.assertEqual(icon_of(items[0]), want, q)
            self.assertRendered(items[0])
            self.assertEqual(icon_of(items[1]), "icons/%s.png" % items[1]["uid"].split("-")[0].lower(), q)
        self.assertEqual(job_for("icons/cis.png")["bg"], "#334155")
        self.assertEqual(job_for("icons/csf-de.png")["text"], "DE")

    def test_messages_use_the_shared_message_icons(self):
        data = index(MAPPED, CSF, CIS)
        cases = [(ctl.respond(data, ""), "hint"), (ctl.respond(data, "cis"), "hint"),
                 (ctl.respond(data, "zzzz"), "none"), (ctl.respond(data, "pr.zz-99"), "none"),
                 (ctl.respond(index(MAPPED, CSF, None), "cis 6"), "warning"),
                 (ctl.respond({"version": "5.2.0", "controls": CONTROLS}, "pr.aa-05"), "warning"),
                 (sp171.respond({"r171": []}, "3.1.1"), "warning"), (sp171.respond({"r171": [1]}, ""), "hint")]
        for items, kind in cases:
            self.assertEqual(icon_of(items[-1]), "icons/%s.png" % kind, items[-1]["title"])
        for mod in (ctl, sp171):
            out = io.StringIO()
            with mock.patch.object(ctl, "load_index", side_effect=OSError("gone")), \
                    mock.patch.object(sys, "argv", ["x", "ac-2"]), mock.patch.object(sys, "stdout", out):
                mod.main()
            self.assertEqual(icon_of(json.loads(out.getvalue())["items"][0]), "icons/error.png")

    def test_icons_folder_matches_make_icons_exactly(self):
        # No icon referenced but not rendered, and no stale file left from an old colour scheme.
        names = sorted(os.path.basename(j["out"]) for j in make_icons.jobs())
        self.assertEqual(sorted(os.listdir(os.path.join(HERE, "icons"))), names)

    def test_family_colours_stay_distinct_from_grey_and_legible(self):
        colors = make_icons.FAMILY_COLORS
        self.assertEqual(set(colors), set(ctl.FAMILIES))
        self.assertFalse({make_icons.GREY, make_icons.SLATE} & set(colors.values()))  # would read as withdrawn
        self.assertLessEqual(max(list(colors.values()).count(v) for v in colors.values()), 3)
        for j in make_icons.jobs():
            self.assertGreaterEqual(contrast_with_white(j["bg"]), 4.5, j["out"])  # WCAG AA for white text


class MakeIcons(unittest.TestCase):
    def setUp(self):
        self.out = tempfile.mkdtemp()
        self.patch = mock.patch.object(make_icons, "OUT", self.out)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        shutil.rmtree(self.out)

    def run_main(self, stdout):
        seen = {}

        def fake_run(argv, **kw):
            with open(argv[-1]) as f:
                seen["jobs"], seen["spec"] = json.load(f), argv[-1]
            return subprocess.CompletedProcess(argv, 0, stdout(len(seen["jobs"])), "")
        with mock.patch.object(make_icons.subprocess, "run", side_effect=fake_run) as run, \
                mock.patch.object(sys, "stdout", io.StringIO()):
            code = make_icons.main()
        return code, run, seen

    def test_renders_every_icon_in_one_osascript_call(self):
        code, run, seen = self.run_main(lambda n: "%d/%d\n" % (n, n))
        self.assertEqual(code, 0)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args[0][0][:4], ["/usr/bin/osascript", "-l", "JavaScript", make_icons.ICONKIT])
        self.assertEqual(len(seen["jobs"]), len(make_icons.jobs()))
        self.assertFalse(os.path.exists(seen["spec"]))  # temp job file cleaned up

    def test_partial_render_fails_loudly(self):
        # iconkit skips a bad job (e.g. unknown SF Symbol) and reports n-1/n; that must not pass as done.
        code, _, _ = self.run_main(lambda n: "%d/%d\n" % (n - 1, n))
        self.assertEqual(code, 1)


class PlistWiring(unittest.TestCase):
    # A modifier the script emits but the plist does not connect silently does nothing in Alfred.
    MODS = {"cmd": 1048576, "alt": 524288, "ctrl": 262144, "shift": 131072}

    def wired(self, keyword):
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "info.plist"), "rb") as f:
            p = plistlib.load(f)
        sf = next(o for o in p["objects"] if o["config"].get("keyword") == keyword)
        conns = p["connections"][sf["uid"]]
        dests = [c["destinationuid"] for c in conns]
        self.assertEqual(len(dests), len(set(dests)), "each modifier needs its own destination")
        return sf, {c["modifiers"] for c in conns}

    def test_ctl_modifiers_are_connected(self):
        sf, mods = self.wired("ctl")
        self.assertIn("ctl.py", sf["config"]["script"])
        emitted = ctl.item(MAPPED[0])["mods"]
        self.assertEqual({self.MODS[k] for k in emitted} | {0}, mods)

    def test_171_modifiers_are_connected(self):
        import sp171
        sf, mods = self.wired("171")
        self.assertIn("sp171.py", sf["config"]["script"])
        r = {"id": "03.01.01", "rev": "R3", "title": "T", "statement": "S", "guidance": "", "sources": ["AC-2"],
             "via": None, "withdrawn": None, "url": "u"}
        self.assertEqual({self.MODS[k] for k in sp171.item(r)["mods"]} | {0}, mods)


if __name__ == "__main__":
    unittest.main()
