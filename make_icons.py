#!/usr/bin/env python3
"""Render the static result icons into icons/ with iconkit.js. Rerun after changing a colour:
/usr/bin/python3 -B make_icons.py
"""
import json
import os
import subprocess
import sys
import tempfile

import ctl

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "icons")
ICONKIT = os.path.join(HERE, "iconkit.js")

GREY = "#4B5563"  # neutral: withdrawn controls and requirements
SLATE = "#334155"
# One fixed colour per family, each palette colour used 2-3 times (20 families, 9 colours).
# Slate is left out: next to withdrawn grey it would read as withdrawn.
FAMILY_COLORS = {
    "AC": "#1D4ED8", "PM": "#1D4ED8",               # blue
    "IR": "#B91C1C", "PT": "#B91C1C",               # red
    "AU": "#0F766E", "PE": "#0F766E", "SA": "#0F766E",  # teal
    "IA": "#7E22CE", "PL": "#7E22CE",               # purple
    "CM": "#B45309", "MA": "#B45309",               # amber
    "SI": "#BE185D", "AT": "#BE185D",               # pink
    "SC": "#4338CA", "CP": "#4338CA",               # indigo
    "CA": "#15803D", "PS": "#15803D",               # green
    "RA": "#C2410C", "SR": "#C2410C", "MP": "#C2410C",  # orange
}
# CSF hue convention for ID/PR/DE/RS/RC; teal for GV.
CSF_COLORS = {"GV": "#0F766E", "ID": "#1D4ED8", "PR": "#7E22CE", "DE": "#B45309", "RS": "#B91C1C", "RC": "#15803D"}
# Shared message icons (conventions doc).
MESSAGES = {
    ctl.HINT: ("#1D4ED8", "lightbulb.fill"),
    ctl.WARNING: ("#B45309", "exclamationmark.triangle.fill"),
    ctl.ERROR: ("#B91C1C", "xmark.octagon.fill"),
    ctl.NONE: ("#4B5563", "magnifyingglass"),
}


def jobs(out_dir=OUT):
    """iconkit jobs for every static icon; the file names match ctl.icon()."""
    out = []

    def add(name, **look):
        out.append(dict(out=os.path.join(out_dir, name + ".png"), **look))

    for code in sorted(FAMILY_COLORS):
        add(code.lower(), bg=FAMILY_COLORS[code], text=code)
        add(code.lower() + "-wd", bg=GREY, text=code)
    for generic in ("53", "171"):  # an index family with no 800-53 code (none today)
        add(generic, bg=SLATE, text=generic)
        add(generic + "-wd", bg=GREY, text=generic)
    for fn, color in CSF_COLORS.items():
        add("csf-" + fn.lower(), bg=color, text=fn)
    add("cis", bg=SLATE, text="CIS")
    for name, (bg, symbol) in MESSAGES.items():
        add(name, bg=bg, symbol=symbol)
    return out


def main():
    todo = jobs()
    os.makedirs(OUT, exist_ok=True)
    fd, spec = tempfile.mkstemp(suffix=".json")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(todo, f)
        res = subprocess.run(["/usr/bin/osascript", "-l", "JavaScript", ICONKIT, spec],
                             capture_output=True, text=True, timeout=60)
    finally:
        os.remove(spec)
    sys.stderr.write(res.stderr)
    done = res.stdout.strip()
    print("Rendered %s icons into %s" % (done or "0/%d" % len(todo), OUT))
    return 0 if res.returncode == 0 and done == "%d/%d" % (len(todo), len(todo)) else 1


if __name__ == "__main__":
    sys.exit(main())
