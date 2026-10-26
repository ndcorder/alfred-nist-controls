#!/usr/bin/env python3
"""Alfred Script Filter: search NIST SP 800-53 Rev 5 controls by ID or text.

Also reverse lookups: a CSF 2.0 ID (pr.aa-05, pr.aa) or a CIS safeguard (cis 6.3,
cis 6) lists the 800-53 controls mapped to it. The CIS crosswalk is licensed, so it is
not in controls.json: build_index.py writes it to a local cis.json, merged here when present.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
INDEX = os.path.join(HERE, "controls.json")
CIS_INDEX = os.path.join(HERE, "cis.json")  # optional, built locally from your own CIS download
MAX_TEXT_RESULTS = 50  # ID queries are uncapped so a whole family (AC = 150+) shows
# ac | ac2 | ac-02 | ac-2(1) | ac-2.1 | ac 2 1, plus half-typed ac- / ac-2( / ac-2.
CONTROL_ID = re.compile(r"^([a-z]{2})(?:[\s-]*0*(\d{1,2})(?:[\s.(]*0*(\d{1,2})\)?)?)?[\s.(-]*$")
# pr.aa-05 | PR.AA-5 | pr.aa (whole category) | half-typed pr.aa-0
CSF_ID = re.compile(r"^(gv|id|pr|de|rs|rc)\.([a-z]{2})(?:-0*(\d{1,2}))?[\s-]*$")
# cis 6.3 | cis6.3 | cis 6 (whole control) | cis 6. | cis
CIS_ID = re.compile(r"^cis(?:[\s:-]*(\d{1,2})(?:\.(\d{1,2})?)?)?\s*$")
REBUILD = "Run build_index.py in the workflow folder"

# SP 800-53 Rev 5 families. Their codes name the icons; sp171 maps 800-171 family titles onto them.
FAMILIES = {
    "AC": "Access Control", "AT": "Awareness and Training", "AU": "Audit and Accountability",
    "CA": "Assessment, Authorization, and Monitoring", "CM": "Configuration Management",
    "CP": "Contingency Planning", "IA": "Identification and Authentication", "IR": "Incident Response",
    "MA": "Maintenance", "MP": "Media Protection", "PE": "Physical and Environmental Protection",
    "PL": "Planning", "PM": "Program Management", "PS": "Personnel Security",
    "PT": "Personally Identifiable Information Processing and Transparency", "RA": "Risk Assessment",
    "SA": "System and Services Acquisition", "SC": "System and Communications Protection",
    "SI": "System and Information Integrity", "SR": "Supply Chain Risk Management",
}
# Static icons in icons/, rendered by make_icons.py. Lower-case names: disks are case-insensitive.
HINT, WARNING, ERROR, NONE = "hint", "warning", "error", "none"


def icon(name):
    return {"path": "icons/%s.png" % name}


def family_icon(code, withdrawn, generic="53"):
    """Family monogram icon; grey when withdrawn. Unknown families get a generic '53' or '171' icon."""
    name = code.lower() if code in FAMILIES else generic
    return icon(name + "-wd" if withdrawn else name)


def parse_id(query):
    """Return (family, number, enhancement) for an ID-shaped query, else None."""
    m = CONTROL_ID.match(query.strip().lower())
    return m.groups() if m else None


def id_matches(control_id, family, number, enh):
    m = re.match(r"^([A-Z]{2})-(\d+)(?:\((\d+)\))?$", control_id)
    if not m or m.group(1).lower() != family:
        return False
    if number and m.group(2) != number:
        return False
    return not enh or m.group(3) == enh


def text_search(items, query):
    """Word-prefix match, so "lock" finds "locks" but not "block". Title hits first."""
    words = [re.compile(r"\b" + re.escape(w), re.I) for w in query.split()]
    title_hits, text_hits = [], []
    for c in items:
        if all(w.search(c["title"]) for w in words):
            title_hits.append(c)
        elif all(w.search(c["title"]) or w.search(c["statement"]) or w.search(c["guidance"]) for w in words):
            text_hits.append(c)
    return (title_hits + text_hits)[:MAX_TEXT_RESULTS]


def search(controls, query):
    ident = parse_id(query)
    if ident:
        hits = [c for c in controls if id_matches(c["id"], *ident)]
        if hits:
            return hits
    return text_search(controls, query)


def parse_csf(query):
    """'pr.aa-5' -> ('PR.AA-05', True); 'pr.aa' or 'pr.aa-0' -> ('PR.AA', False); else None."""
    m = CSF_ID.match(query.strip().lower())
    if not m:
        return None
    cat = ("%s.%s" % (m.group(1), m.group(2))).upper()
    if m.group(3) and int(m.group(3)):
        return "%s-%02d" % (cat, int(m.group(3))), True
    return cat, False


def parse_cis(query):
    """'cis 6.3' -> ('6.3', True); 'cis 6' -> ('6', False); 'cis' -> ('', False); else None."""
    m = CIS_ID.match(query.strip().lower())
    if not m:
        return None
    control, safeguard = m.groups()
    if control and safeguard:
        return "%d.%d" % (int(control), int(safeguard)), True
    return (str(int(control)) if control else ""), False


def note(title, subtitle="", kind=NONE):
    return {"title": title, "subtitle": subtitle, "valid": False, "icon": icon(kind)}


def live_first(hits):
    # Live controls first; withdrawn ones are mostly noise.
    return sorted(hits, key=lambda c: c["withdrawn"] is not None)


def csf_lookup(data, query):
    parsed = parse_csf(query)
    if parsed is None:
        return None
    if "csf" not in data:
        return [note("Index has no CSF 2.0 crosswalk", REBUILD, WARNING)]
    key, exact = parsed
    match = (lambda s: s == key) if exact else (lambda s: s.startswith(key + "-"))
    subs = sorted(s for s in data["csf"] if match(s))
    if not subs:
        return [note("No CSF 2.0 subcategory %s" % key, "Try a category (pr.aa) or a subcategory (pr.aa-05)")]
    hits = live_first([c for c in data["controls"] if any(match(s) for s in c.get("csf", []))])
    csf_icon = "csf-" + key[:2].lower()  # the CSF function: gv id pr de rs rc
    if exact:
        text = data["csf"][key]
        head = {"title": "%s  %s" % (key, text), "valid": False, "icon": icon(csf_icon),
                "subtitle": "CSF 2.0 → %d SP 800-53 controls (NIST informative references)" % len(hits),
                "text": {"copy": "%s %s" % (key, text), "largetype": "%s %s" % (key, text)}}
    else:
        head = note("%s  %d subcategories" % (key, len(subs)),
                    "CSF 2.0 → %d SP 800-53 controls: %s" % (len(hits), ", ".join(subs)), csf_icon)
    return [head] + ([item(c) for c in hits] or [note("No SP 800-53 controls mapped to %s" % key)])


def cis_lookup(data, query):
    parsed = parse_cis(query)
    if parsed is None:
        return None
    if not data.get("cis"):
        return [note("CIS v8.1 crosswalk not indexed",
                     "Download the CIS v8.1 → 800-53 xlsx yourself, set CIS_XLSX, rebuild (see readme)", WARNING)]
    key, exact = parsed
    if not key:
        return [note("Type a CIS safeguard: cis 6.3, or a control: cis 6",
                     "%d CIS v8.1 safeguards indexed" % len(data["cis"]), HINT)]
    match = (lambda s: s == key) if exact else (lambda s: s.split(".")[0] == key)
    sgs = sorted((s for s in data["cis"] if match(s)), key=lambda s: tuple(int(x) for x in s.split(".")))
    if not sgs:
        return [note("No CIS v8.1 safeguard %s" % key)]
    hits = live_first([c for c in data["controls"] if any(match(s) for s in c.get("cis", []))])
    if exact:
        head = note("CIS %s  %s" % (key, data["cis"][key]),
                    "CIS v8.1 → %d SP 800-53 controls (CIS mapping)" % len(hits), "cis")
    else:
        head = note("CIS %s  %d safeguards" % (key, len(sgs)),
                    "CIS v8.1 → %d SP 800-53 controls: %s" % (len(hits), ", ".join(sgs)), "cis")
    return [head] + ([item(c) for c in hits] or [note("No SP 800-53 controls mapped to CIS %s" % key)])


def brief(ids):
    """['A', 'B', 'C'] -> 'A +2', so the subtitle stays readable."""
    return ids[0] + (" +%d" % (len(ids) - 1) if len(ids) > 1 else "")


def crosswalk_lines(c):
    lines = []
    if c.get("r171"):
        lines.append("SP 800-171 R3: " + ", ".join(c["r171"]))
    if c.get("r2"):
        lines.append("SP 800-171 R2 (via R3, not an official NIST mapping): " + ", ".join(c["r2"]))
    if c.get("csf"):
        lines.append("CSF 2.0: " + ", ".join(c["csf"]))
    if c.get("cis"):
        lines.append("CIS v8.1: " + ", ".join(c["cis"]))
    return lines


def item(c):
    tags = [" ".join(c["baselines"]) or "no baseline"]
    tags += ["%s %s" % (name, brief(c[key])) for name, key in (("171", "r171"), ("CSF", "csf"), ("CIS", "cis"))
             if c.get(key)]
    first_line = c["statement"].split("\n", 1)[0]
    if c["withdrawn"] is not None:
        subtitle = "Withdrawn → " + (", ".join(c["withdrawn"]) or "no replacement")
    else:
        subtitle = "[%s] %s" % (" · ".join(tags), first_line)
    full = "%s %s\n\n%s" % (c["id"], c["title"], c["statement"])
    xw = crosswalk_lines(c)
    crosswalk = "%s %s\n%s" % (c["id"], c["title"], "\n".join(xw)) if xw else ""
    counts = " · ".join("%s %d" % (n, len(c[k])) for n, k in
                        (("171 R3", "r171"), ("R2 via R3", "r2"), ("CSF", "csf"), ("CIS", "cis")) if c.get(k))
    return {
        "uid": c["id"],
        "title": "%s  %s" % (c["id"], c["title"]),
        "subtitle": subtitle,
        "icon": family_icon(c["id"].split("-")[0], c["withdrawn"] is not None),
        "arg": full,
        "autocomplete": c["id"],
        "text": {"copy": full, "largetype": full + ("\n\n" + "\n".join(xw) if xw else "")},
        "mods": {
            "cmd": {"arg": c["url"], "subtitle": "Open %s on NIST CPRT" % c["id"]},
            "alt": {
                "arg": c["guidance"] or full,
                "valid": bool(c["guidance"]),
                "subtitle": "Copy discussion: " + (c["guidance"][:120] or "none"),
            },
            "ctrl": {
                "arg": crosswalk or full,
                "valid": bool(crosswalk),
                "subtitle": "Copy crosswalk: " + (counts or "no mappings"),
            },
        },
    }


def respond(data, query):
    if not query.strip():
        return [{
            "title": "Search NIST SP 800-53 Rev %s" % data["version"],
            "subtitle": "Control ID (ac-2, ia-2(1)), words (device lock), CSF ID (pr.aa-05) or cis 6.3",
            "valid": False,
            "icon": icon(HINT),
        }]
    for lookup in (cis_lookup, csf_lookup):
        items = lookup(data, query)
        if items is not None:
            return items
    hits = live_first(search(data["controls"], query))
    return [item(c) for c in hits] or [note("No controls match '%s'" % query)]


def load_index(path=INDEX, cis_path=CIS_INDEX):
    with open(path) as f:
        data = json.load(f)
    if os.path.isfile(cis_path):
        with open(cis_path) as f:
            cis = json.load(f)
        data["cis"] = cis["safeguards"]
        for c in data["controls"]:
            c["cis"] = cis["controls"].get(c["id"], [])
    return data


def main():
    query = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        items = respond(load_index(), query)
    except (OSError, ValueError, KeyError) as e:
        items = [note("Index is missing or unreadable", "%s (%s: %s)" % (REBUILD, type(e).__name__, e), ERROR)]
    json.dump({"items": items, "skipknowledge": True}, sys.stdout)


if __name__ == "__main__":
    main()
