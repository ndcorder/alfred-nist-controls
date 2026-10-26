#!/usr/bin/env python3
"""Alfred Script Filter: search NIST SP 800-171 R2 and R3 requirements by ID or text.

R3 800-53 sources are NIST's own (OSCAL). R2 has no official 800-53 Rev 5 mapping,
so it shows the sources of its R3 counterpart, always labelled "via R3".
"""
import json
import re
import sys

import ctl

# 3.1.1 | 03.01.01 | 3 1 1 | 3.1 | 03.01 | 3 | half-typed 3.1. / 03.01.0
REQ_ID = re.compile(r"^0?3(?:[\s.]+0?(\d{1,2})(?:[\s.]+0?(\d{1,2}))?)?[\s.]*$")
UNOFFICIAL = "not an official NIST mapping"
# 800-171 family titles that differ from the 800-53 family titles (case is ignored).
FAMILY_ALIASES = {
    "physical protection": "PE",  # 800-53: Physical and Environmental Protection
    "security assessment": "CA",  # R2; 800-53: Assessment, Authorization, and Monitoring
    "security assessment and monitoring": "CA",  # R3
}
FAMILY_CODES = dict({t.lower(): code for code, t in ctl.FAMILIES.items()}, **FAMILY_ALIASES)


def family_code(title):
    """800-53 family code for an 800-171 family title, or None for a 171-only family."""
    return FAMILY_CODES.get((title or "").strip().lower())


def parse_id(query):
    """Return (family, number) for an ID-shaped query (None = any), else None."""
    m = REQ_ID.match(query.strip().lower())
    if not m:
        return None
    family, number = (int(g) if g and int(g) else None for g in m.groups())
    return family, number if family else None


def numbers(req_id):
    """'3.1.1' and '03.01.01' -> (3, 1, 1), so both revisions compare equal."""
    return tuple(int(x) for x in req_id.split("."))


def search(reqs, query):
    ident = parse_id(query)
    if ident:
        family, number = ident
        hits = [r for r in reqs
                if (family is None or numbers(r["id"])[1] == family)
                and (number is None or numbers(r["id"])[2] == number)]
        if hits:
            return hits
    return ctl.text_search(reqs, query)


def sources_text(r):
    """The 800-53 source list as copied by ⌥↩, with its provenance."""
    if not r["sources"]:
        return ""
    if r["rev"] == "R2":
        return "%s (via R3 %s; %s)" % (", ".join(r["sources"]), ", ".join(r["via"]), UNOFFICIAL)
    return ", ".join(r["sources"])


def subtitle(r):
    if r["withdrawn"] is not None:
        moves = "; ".join("%s %s" % (w["rel"], w["id"]) for w in r["withdrawn"])
        return "Withdrawn in R3 → " + (moves or "no replacement listed")
    if r["rev"] == "R3":
        return "800-53: " + (", ".join(r["sources"]) or "none listed by NIST")
    if r["via"]:
        return "800-53 via R3 %s: %s" % (", ".join(r["via"]), ", ".join(r["sources"]) or "none listed")
    # The same-numbered R3 requirement was withdrawn without a replacement.
    return "800-53 via R3: none (R3 %s withdrawn, no replacement listed)" % r.get("r3", r["id"])


def item(r):
    sub = subtitle(r)
    if r["withdrawn"] is not None:
        full = "%s %s" % (r["id"], sub)
    elif r["title"] == r["statement"]:  # R2 requirements have no titles
        full = "%s %s" % (r["id"], r["statement"])
    else:
        full = "%s %s\n\n%s" % (r["id"], r["title"], r["statement"])
    src = sources_text(r)
    return {
        "uid": "171-%s-%s" % (r["rev"], r["id"]),
        "title": "%s (%s)  %s" % (r["id"], r["rev"], r["title"]),
        "subtitle": sub,
        # Same monogram as the 800-53 family, so Access Control looks alike in ctl and 171.
        "icon": ctl.family_icon(family_code(r.get("family")), r["withdrawn"] is not None, generic="171"),
        "arg": full,
        "autocomplete": r["id"],
        "text": {"copy": full, "largetype": "%s\n\n%s" % (full, sub)},
        "mods": {
            "cmd": {"arg": r["url"], "subtitle": "Open %s (%s) on NIST CPRT" % (r["id"], r["rev"])},
            "alt": {"arg": src or full, "valid": bool(src), "subtitle": "Copy 800-53 sources: " + (src or "none")},
        },
    }


def respond(data, query):
    reqs = data.get("r171")
    if not reqs:
        return [ctl.note("Index has no SP 800-171 data", ctl.REBUILD, ctl.WARNING)]
    if not query.strip():
        return [ctl.note("Search NIST SP 800-171 R2 + R3",
                         "Requirement ID (3.1.1, 03.01.01, 3.1) or words (multifactor)", ctl.HINT)]
    hits = sorted(search(reqs, query), key=lambda r: r["withdrawn"] is not None)
    return [item(r) for r in hits] or [ctl.note("No SP 800-171 requirements match '%s'" % query)]


def main():
    query = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        items = respond(ctl.load_index(), query)
    except (OSError, ValueError, KeyError) as e:
        items = [ctl.note("Index is missing or unreadable", "%s (%s: %s)" % (ctl.REBUILD, type(e).__name__, e),
                          ctl.ERROR)]
    json.dump({"items": items, "skipknowledge": True}, sys.stdout)


if __name__ == "__main__":
    main()
