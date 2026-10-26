#!/usr/bin/env python3
"""Build controls.json (NIST SP 800-53 Rev 5, SP 800-171 R2 + R3, CSF 2.0 crosswalk) and,
if you have the CIS file, cis.json.

Fetched (official NIST):
  SP 800-53 catalog + baselines     OSCAL JSON (usnistgov/oscal-content)
  SP 800-171 R3 + its 800-53 sources OSCAL JSON (back-matter references)
  SP 800-171 R2 text                CSRC CSV. NIST publishes no R2 -> 800-53 Rev 5
                                    mapping, so R2 borrows R3's sources by sort-ID
                                    (3.1.1 -> 03.01.01). Shown as "via R3".
  CSF 2.0 -> SP 800-53 Rev 5.2.0    CSF 2.0 Reference Tool xlsx export
Local only, never fetched or redistributed: the CIS Controls v8.1 -> SP 800-53 xlsx that
you download from CIS yourself (CC BY-NC-ND 4.0). Its path comes from $CIS_XLSX, else from
the CIS_XLSX value saved by Configure Workflow in prefs.plist. The CIS crosswalk goes to
cis.json only, never into controls.json: controls.json is published, cis.json is gitignored
and left out of the release package.

Run again to pick up a new release: /usr/bin/python3 build_index.py
"""
import csv
import io
import json
import os
import plistlib
import re
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

BASE = "https://raw.githubusercontent.com/usnistgov/oscal-content/main/nist.gov/SP800-53/rev5/json"
CATALOG = BASE + "/NIST_SP-800-53_rev5_catalog.json"
BASELINES = {
    "L": BASE + "/NIST_SP-800-53_rev5_LOW-baseline_profile.json",
    "M": BASE + "/NIST_SP-800-53_rev5_MODERATE-baseline_profile.json",
    "H": BASE + "/NIST_SP-800-53_rev5_HIGH-baseline_profile.json",
    "P": BASE + "/NIST_SP-800-53_rev5_PRIVACY-baseline_profile.json",
}
R3_CATALOG = ("https://raw.githubusercontent.com/usnistgov/oscal-content/main/nist.gov/SP800-171/rev3/json"
              "/NIST_SP800-171_rev3_catalog.json")
R2_CSV = "https://csrc.nist.gov/files/pubs/sp/800/171/r2/upd1/final/docs/sp800-171r2-security-reqs.csv"
CSF_XLSX = "https://csrc.nist.gov/extensions/nudp/services/json/csf/download?olirids=all"
CPRT = "https://csrc.nist.gov/projects/cprt/catalog#/cprt/framework/version/%s/home?element=%s"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "controls.json")
CIS_OUT = os.path.join(HERE, "cis.json")  # licensed data: gitignored, never packaged
PREFS = os.path.join(HERE, "prefs.plist")  # Configure Workflow values
INSERT = re.compile(r"\{\{\s*insert:\s*param,\s*([\w.-]+)\s*\}\}")

# Sanity bounds: a source outside them has changed shape, so stop before writing.
MIN_80053_CONTROLS = 1000
R3_TOTAL, R3_LIVE, MIN_R3_PAIRS = (120, 140), (90, 105), 140  # 130 / 97 / 157 in R3 1.1.0
R2_TOTAL = 110
MIN_CSF_PAIRS = 500  # 740 in the Oct 2026 export
MIN_CIS_PAIRS = 100
MAX_UNRESOLVED = 10
CSF_REF = "SP 800-53 Rev 5.2.0:"


class BuildError(Exception):
    """A source no longer looks the way this script expects."""


def fetch_bytes(url):
    # csrc.nist.gov answers 403 to urllib's default User-Agent.
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (build_index.py; alfred-nist-controls)"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read()
    except urllib.error.URLError as e:
        raise BuildError("download failed: %s (%s)" % (url, e))


def fetch(url):
    return json.loads(fetch_bytes(url))


def label(obj, cls=None):
    for p in obj.get("props", []):
        if p["name"] == "label" and p.get("class") == cls:
            return p["value"]
    return ""


def prop(obj, name):
    return next((p["value"] for p in obj.get("props", []) if p["name"] == name), "")


def render_param(param, params):
    if "select" in param:
        sel = param["select"]
        how = " (one or more)" if sel.get("how-many") == "one-or-more" else ""
        choices = "; ".join(fill(c, params) for c in sel.get("choice", []))
        return "[Selection%s: %s]" % (how, choices)
    text = param.get("label", param["id"])
    if not text.startswith("organization-defined"):
        text = "organization-defined " + text
    return "[Assignment: %s]" % text


def fill(prose, params):
    def sub(m):
        p = params.get(m.group(1))
        return render_param(p, params) if p else m.group(0)

    return INSERT.sub(sub, prose)


def render_parts(part, params, depth=0, labeler=label):
    lines = []
    text = " ".join(x for x in (labeler(part), fill(part.get("prose", ""), params)) if x)
    if text:
        lines.append("  " * depth + text)
    for child in part.get("parts", []):
        lines.extend(render_parts(child, params, depth + (1 if text else 0), labeler))
    return lines


def oscal_to_label(href):
    """'#ac-2.1_smt.k' -> 'AC-2(1)'"""
    cid = href.lstrip("#").split("_")[0]
    return re.sub(r"\.(\d+)$", r"(\1)", cid).upper()


CONTROL_REF = re.compile(r"^([A-Z]{2})-0*(\d+)(?:\(0*(\d+)\))?$")


def short_id(ref):
    """'AC-02(03)' or 'AC-2(3)' -> 'AC-2(3)'; family-only or other text -> None."""
    m = CONTROL_REF.match(ref.strip().upper())
    if not m:
        return None
    return "%s-%s%s" % (m.group(1), m.group(2), "(%s)" % m.group(3) if m.group(3) else "")


def walk(controls, parent=None):
    for c in controls:
        yield c, parent
        yield from walk(c.get("controls", []), c)


def collect_params(groups):
    params = {}
    for group in groups:
        for c, _ in walk(group.get("controls", [])):
            for p in c.get("params", []):
                params[p["id"]] = p
    return params


# ---------- xlsx (stdlib only) ----------

M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
REL_ID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


def col_index(ref):
    """'C12' -> 2"""
    n = 0
    for ch in ref:
        if not ch.isalpha():
            break
        n = n * 26 + ord(ch.upper()) - 64
    return n - 1


def _text(el):
    """Text of a shared string or inline string, ignoring phonetic runs."""
    parts = [el.find(M + "t")] + [r.find(M + "t") for r in el.findall(M + "r")]
    return "".join(t.text or "" for t in parts if t is not None)


def _cell(c, shared):
    t = c.get("t")
    if t == "inlineStr":
        inline = c.find(M + "is")
        return _text(inline) if inline is not None else ""
    v = c.find(M + "v")
    if v is None or v.text is None:
        return ""
    return shared[int(v.text)] if t == "s" else v.text


def read_xlsx(data):
    """xlsx bytes -> {sheet name: [[cell text, ...], ...]}."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            shared = [_text(si) for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall(M + "si")]
        rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
        sheets = {}
        for s in ET.fromstring(z.read("xl/workbook.xml")).find(M + "sheets"):
            target = rels[s.get(REL_ID)]
            path = target.lstrip("/") if target.startswith("/") else "xl/" + target
            rows = []
            for row in ET.fromstring(z.read(path)).iter(M + "row"):
                cells = []
                for c in row.findall(M + "c"):
                    i = col_index(c.get("r")) if c.get("r") else len(cells)
                    cells.extend([""] * (i + 1 - len(cells)))
                    cells[i] = _cell(c, shared)
                rows.append(cells)
            sheets[s.get("name")] = rows
        return sheets
    except (zipfile.BadZipFile, KeyError, ET.ParseError, TypeError, AttributeError) as e:
        raise BuildError("not a readable xlsx (%s; %d bytes starting %r)" % (e, len(data), data[:40]))


def find_header(rows, *names):
    """Return (row index, {lowercase name: column}) of the first row holding every name."""
    want = [n.lower() for n in names]
    for i, row in enumerate(rows):
        cols = {v.strip().lower(): j for j, v in enumerate(row) if v.strip()}
        if all(n in cols for n in want):
            return i, {n: cols[n] for n in want}
    raise BuildError("no header row with columns %s" % ", ".join(repr(n) for n in names))


def cell(row, i):
    return row[i].strip() if i < len(row) else ""


# ---------- CSF 2.0 ----------

CSF_SUB = re.compile(r"^(GV|ID|PR|DE|RS|RC)\.[A-Z]{2}-\d{2}$")


def parse_csf(sheets):
    """-> ({subcategory: text}, [(subcategory, 800-53 id)], [family-only refs skipped])"""
    rows = sheets.get("CSF 2.0")
    if rows is None:
        raise BuildError("CSF export has no 'CSF 2.0' sheet (found: %s)" % ", ".join(sheets))
    start, col = find_header(rows, "Subcategory", "Informative References")
    subcats, pairs, family_only, prefixes = {}, set(), set(), set()
    for row in rows[start + 1:]:
        sid, _, text = cell(row, col["subcategory"]).partition(":")
        sid = sid.strip()
        if not CSF_SUB.match(sid):
            continue
        subcats[sid] = text.strip()
        for line in cell(row, col["informative references"]).splitlines():
            line = line.strip()
            if line.startswith("SP 800-53"):
                prefixes.add(line.split(":")[0])
            if not line.startswith(CSF_REF):
                continue
            ref = line[len(CSF_REF):].strip()
            cid = short_id(ref)
            if cid:
                pairs.add((sid, cid))
            else:
                family_only.add("%s -> %s" % (sid, ref))  # e.g. 'IR': no control to link to
    if len(pairs) < MIN_CSF_PAIRS:
        raise BuildError("CSF export has only %d '%s' pairs (expected >= %d). 800-53 prefixes seen: %s"
                         % (len(pairs), CSF_REF, MIN_CSF_PAIRS, ", ".join(sorted(prefixes)) or "none"))
    return subcats, sorted(pairs), sorted(family_only)


# ---------- CIS v8.1 (local file only) ----------

CIS_SG = re.compile(r"^\d{1,2}\.\d{1,2}$")


def cis_key(sg):
    return tuple(int(x) for x in sg.split("."))


def parse_cis(sheets):
    """-> ({safeguard: title}, [(safeguard, 800-53 id)])"""
    for name, rows in sheets.items():
        try:
            start, col = find_header(rows, "CIS Safeguard", "Title", "Control Identifier")
            break
        except BuildError:
            continue
    else:
        raise BuildError("CIS xlsx has no sheet with 'CIS Safeguard', 'Title' and 'Control Identifier' columns")
    titles, pairs = {}, set()
    for n, row in enumerate(rows[start + 1:], start + 2):
        sg, ref = cell(row, col["cis safeguard"]), cell(row, col["control identifier"])
        if not sg:
            continue  # control-level heading row
        if not CIS_SG.match(sg):
            raise BuildError("CIS sheet %r row %d: safeguard %r is not N.N" % (name, n, sg))
        title = cell(row, col["title"])
        if titles.setdefault(sg, title) != title:
            # 3.10 stored as a number reads back as 3.1 and collides with the real 3.1.
            raise BuildError("CIS safeguard %s has two titles (%r, %r): IDs were probably stored as numbers"
                             % (sg, titles[sg], title))
        cid = short_id(ref) if ref else None
        if cid:
            pairs.add((sg, cid))
    if len(pairs) < MIN_CIS_PAIRS:
        raise BuildError("CIS xlsx has only %d safeguard -> 800-53 pairs (expected >= %d)"
                         % (len(pairs), MIN_CIS_PAIRS))
    return titles, sorted(pairs, key=lambda p: (cis_key(p[0]), p[1]))


def cis_path(prefs=PREFS):
    """CIS xlsx path from $CIS_XLSX, else from Configure Workflow (prefs.plist), else ''."""
    path = os.environ.get("CIS_XLSX", "").strip()
    if not path and os.path.isfile(prefs):
        try:
            with open(prefs, "rb") as f:
                path = str(plistlib.load(f).get("CIS_XLSX", "")).strip()
        except (OSError, plistlib.InvalidFileException, AttributeError) as e:
            print("Note: could not read %s (%s)" % (prefs, e))
    return os.path.expanduser(path) if path else ""


def load_cis(path):
    """No file is normal (the user downloads it himself): skip with a note."""
    if not path:
        print("Note: CIS_XLSX is not set - skipping CIS. See README: Adding the CIS crosswalk.")
        return None
    if not os.path.isfile(path):
        print("Note: no CIS v8.1 mapping at %s - skipping CIS." % path)
        return None
    with open(path, "rb") as f:
        return parse_cis(read_xlsx(f.read()))


# ---------- SP 800-171 ----------

R3_DOC, R2_DOC = "SP_800_171_3_0_0", "SP_800_171_2_0_0"
CPRT_LINK = re.compile(r"\[\]\([^)]*\)\s*")
R3_ITEM = re.compile(r"^SR-\d{2}\.\d{2}\.\d{2}\.(?:.*\.)?([^.]+)$")
REQ_REF = re.compile(r"\d{2}\.\d{2}\.\d{2}")


def r3_label(part):
    """'SR-03.01.01.a' -> 'a.', 'SR-03.01.01.c.01' -> '1.' (as NIST prints them)."""
    m = R3_ITEM.match(label(part))
    if not m:
        return ""
    last = m.group(1)
    return (last.lstrip("0") or last) + "." if last.isdigit() else last + "."


def parse_r3(catalog):
    resources = {r["uuid"]: r.get("title", "") for r in catalog.get("back-matter", {}).get("resources", [])}
    params = collect_params(catalog["groups"])
    reqs = []
    for group in catalog["groups"]:
        for c, _ in walk(group.get("controls", [])):
            if c.get("class") != "requirement":
                continue
            rid = prop(c, "sort-id")
            links = c.get("links") or []
            withdrawn = None
            if prop(c, "status") == "withdrawn":
                withdrawn = [{"rel": l["rel"].replace("_", " "), "id": REQ_REF.search(l["href"]).group(0)}
                             for l in links if l.get("rel") != "reference" and REQ_REF.search(l.get("href", ""))]
            sources = []
            for l in links:
                if l.get("rel") == "reference":
                    cid = short_id(resources.get(l["href"].lstrip("#"), ""))
                    if cid and cid not in sources:
                        sources.append(cid)
            parts = {p["name"]: p for p in c.get("parts", []) or []}
            stmt = render_parts(parts["statement"], params, labeler=r3_label) if "statement" in parts else []
            reqs.append({
                "id": rid,
                "rev": "R3",
                "title": "Withdrawn" if withdrawn is not None else c["title"],
                "family": group["title"],
                "statement": CPRT_LINK.sub("", "\n".join(stmt)),
                "guidance": CPRT_LINK.sub("", fill(parts["guidance"].get("prose", ""), params))
                if "guidance" in parts else "",
                "sources": sources,
                "via": None,
                "withdrawn": withdrawn,
                "url": CPRT % (R3_DOC, rid),
            })
    return reqs


def check_r3(reqs):
    live = [r for r in reqs if r["withdrawn"] is None]
    pairs = sum(len(r["sources"]) for r in live)
    if not (R3_TOTAL[0] <= len(reqs) <= R3_TOTAL[1] and R3_LIVE[0] <= len(live) <= R3_LIVE[1]
            and pairs >= MIN_R3_PAIRS):
        raise BuildError("SP 800-171 R3 catalog looks wrong: %d requirements (expected %d-%d), %d live "
                         "(expected %d-%d), %d 800-53 source links (expected >= %d)"
                         % (len(reqs), R3_TOTAL[0], R3_TOTAL[1], len(live), R3_LIVE[0], R3_LIVE[1],
                            pairs, MIN_R3_PAIRS))


R2_COLUMNS = ("Family", "Basic/Derived Security Requirement", "Identifier", "Sort-As",
              "Security Requirement", "Discussion")


def parse_r2(text):
    reader = csv.DictReader(io.StringIO(text))
    headers = [h.strip() for h in reader.fieldnames or []]
    missing = [c for c in R2_COLUMNS if c not in headers]
    if missing:
        raise BuildError("SP 800-171 R2 CSV lacks columns %s (has: %s)" % (missing, headers))
    reqs = []
    for raw in reader:
        row = {(k or "").strip(): (v or "").strip() for k, v in raw.items()}
        if not row["Identifier"]:
            continue
        reqs.append({
            "id": row["Identifier"],
            "rev": "R2",
            "sort": row["Sort-As"],
            "title": row["Security Requirement"],  # R2 requirements have no titles
            "family": row["Family"],
            "statement": row["Security Requirement"],
            "guidance": row["Discussion"],
            "type": row["Basic/Derived Security Requirement"],
            "url": CPRT % (R2_DOC, row["Identifier"]),
        })
    if len(reqs) != R2_TOTAL:
        raise BuildError("SP 800-171 R2 CSV has %d requirements (expected %d)" % (len(reqs), R2_TOTAL))
    return reqs


def bridge_r2(r2, r3):
    """Give each R2 requirement the 800-53 sources of its R3 counterpart (same sort-ID).

    Not an official NIST mapping. When the R3 counterpart is withdrawn, follow its
    'incorporated into' / 'addressed by' links to the live R3 requirement(s), so
    3.12.4 lands on 03.15.02 and 3.1.13 on 03.13.08.
    """
    by_id = {r["id"]: r for r in r3}

    def live(rid, seen):
        r = by_id.get(rid)
        if r is None or rid in seen:
            return []
        if r["withdrawn"] is None:
            return [rid]
        seen.add(rid)
        out = []
        for w in r["withdrawn"]:
            out.extend(x for x in live(w["id"], seen) if x not in out)
        return out

    for req in r2:
        req["r3"] = req.pop("sort")  # the same-numbered R3 requirement
        req["via"] = live(req["r3"], set())
        req["sources"] = []
        for v in req["via"]:
            req["sources"].extend(s for s in by_id[v]["sources"] if s not in req["sources"])
        req["withdrawn"] = None
    return r2


def req_key(r):
    return tuple(int(x) for x in r["id"].split(".")), r["rev"]


# ---------- merge ----------

def merge_crosswalks(controls, r171, csf_pairs):
    """Attach the NIST crosswalks to each 800-53 control. Returns references to unknown controls.

    CIS is not merged here: it is licensed and lives in cis.json (see cis_index).
    """
    by_id = {c["id"]: c for c in controls}
    for c in controls:
        c.update({"r171": [], "r2": [], "csf": []})
    unresolved = []

    def add(cid, field, value):
        c = by_id.get(cid)
        if c is None:
            unresolved.append("%s %s -> %s" % (field, value, cid))
        elif value not in c[field]:
            c[field].append(value)

    for r in r171:
        for cid in r["sources"]:
            add(cid, "r171" if r["rev"] == "R3" else "r2", r["id"])
    for sid, cid in csf_pairs:
        add(cid, "csf", sid)
    for c in controls:
        c["csf"].sort()
    return unresolved


def cis_index(controls, titles, pairs):
    """-> (cis.json data, references to unknown controls). ctl.py merges it at load time."""
    known = {c["id"] for c in controls}
    mapped, unresolved = {}, []
    for sg, cid in pairs:
        if cid not in known:
            unresolved.append("cis %s -> %s" % (sg, cid))
        elif sg not in mapped.setdefault(cid, []):
            mapped[cid].append(sg)
    for sgs in mapped.values():
        sgs.sort(key=cis_key)
    return {"safeguards": titles, "controls": mapped}, unresolved


def write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, separators=(",", ":"))
    os.replace(tmp, path)  # Alfred may read the index while we write


def build_80053():
    catalog = fetch(CATALOG)["catalog"]
    version = catalog["metadata"]["version"]
    cprt = CPRT % ("SP_800_53_%s" % version.replace(".", "_"), "")

    baselines = {}
    for tag, url in BASELINES.items():
        for imp in fetch(url)["profile"]["imports"]:
            for inc in imp.get("include-controls", []):
                for cid in inc.get("with-ids", []):
                    baselines.setdefault(cid, []).append(tag)

    groups = catalog["groups"]
    params = collect_params(groups)
    out = []
    for group in groups:
        for c, parent in walk(group["controls"]):
            status = [p["value"] for p in c.get("props", []) if p["name"] == "status"]
            parts = {p["name"]: p for p in c.get("parts", [])}
            title = c["title"] if parent is None else "%s | %s" % (parent["title"], c["title"])
            out.append({
                "id": label(c),
                "title": title,
                "family": group["title"],
                "statement": "\n".join(render_parts(parts["statement"], params)) if "statement" in parts else "",
                "guidance": fill(parts["guidance"].get("prose", ""), params) if "guidance" in parts else "",
                "baselines": "".join(baselines.get(c["id"], [])),
                "withdrawn": [
                    oscal_to_label(l["href"])
                    for l in c.get("links", []) if l.get("rel") in ("incorporated-into", "moved-to")
                ] if "withdrawn" in status else None,
                "url": cprt + label(c, "zero-padded"),
            })
    if len(out) < MIN_80053_CONTROLS:
        raise BuildError("SP 800-53 catalog has only %d controls (expected >= %d)" % (len(out), MIN_80053_CONTROLS))
    return version, out


def main():
    version, controls = build_80053()

    r3 = parse_r3(fetch(R3_CATALOG)["catalog"])
    check_r3(r3)
    r2 = bridge_r2(parse_r2(fetch_bytes(R2_CSV).decode("utf-8-sig")), r3)
    r171 = sorted(r2 + r3, key=req_key)

    subcats, csf_pairs, family_only = parse_csf(read_xlsx(fetch_bytes(CSF_XLSX)))

    cis_file = cis_path()
    cis = load_cis(cis_file)

    unresolved = merge_crosswalks(controls, r171, csf_pairs)
    cis_data = None
    if cis:
        cis_data, cis_unresolved = cis_index(controls, *cis)
        unresolved += cis_unresolved
    if unresolved:
        print("Warning: %d mapped IDs are not in SP 800-53 %s: %s" % (len(unresolved), version, "; ".join(unresolved)))
    if len(unresolved) > MAX_UNRESOLVED:
        raise BuildError("too many unresolved 800-53 IDs (%d); a source probably targets another release"
                         % len(unresolved))

    write_json(OUT, {"version": version, "controls": controls, "r171": r171, "csf": subcats})
    if cis_data:
        write_json(CIS_OUT, cis_data)

    print("Wrote %s:" % OUT)
    print("  SP 800-53 Rev %s: %d controls" % (version, len(controls)))
    print("  SP 800-171 R3: %d requirements (%d live), %d 800-53 source links"
          % (len(r3), sum(r["withdrawn"] is None for r in r3), sum(len(r["sources"]) for r in r3)))
    print("  SP 800-171 R2: %d requirements, sources via R3 (%d without any)"
          % (len(r2), sum(not r["sources"] for r in r2)))
    print("  CSF 2.0: %d subcategories, %d subcategory -> control pairs; skipped family-only: %s"
          % (len(subcats), len(csf_pairs), ", ".join(family_only) or "none"))
    if cis_data:
        print("Wrote %s (local only, do not commit or share):" % CIS_OUT)
        print("  CIS v8.1: %d safeguards, %d pairs from %s" % (len(cis[0]), len(cis[1]), cis_file))
    else:
        print("  CIS v8.1: not rebuilt (%s)" % ("existing cis.json kept" if os.path.isfile(CIS_OUT) else "no cis.json"))


if __name__ == "__main__":
    try:
        main()
    except BuildError as e:
        sys.exit("build_index: %s\ncontrols.json and cis.json were not changed." % e)
