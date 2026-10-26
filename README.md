# NIST Controls for Alfred

Look up NIST SP 800-53 Rev 5 controls and SP 800-171 requirements from Alfred, with crosswalks between them and to the NIST Cybersecurity Framework (CSF) 2.0.

It is made for filling in security questionnaires and reading audit paperwork: type the ID in whatever spelling the document uses (`AC-02(01)`, `ac-2.1`, `3.1.1`, `03.01.01`, `PR.AA-05`) and copy the control text, its discussion or its crosswalk. Everything is local; the index ships with the workflow.

## Usage

Type `ctl` for SP 800-53 Rev 5. Query by control ID (`ac-2`, `AC-02(01)`, `ia-2.1`), by family (`ac`) or by words (`multi-factor`). A CSF 2.0 ID (`pr.aa-05`, or `pr.aa` for a whole category) or a CIS safeguard (`cis 6.3`, or `cis 6`) lists the 800-53 controls mapped to it.

| Key | Action |
|---|---|
| ↩ | Copy ID, title and statement |
| ⌘ ↩ | Open the control on NIST CPRT |
| ⌥ ↩ | Copy the discussion (guidance) |
| ⌃ ↩ | Copy the crosswalk: 800-171 R3, R2 via R3, CSF 2.0, CIS v8.1 if installed |
| ⌘ L | Show statement and crosswalk in large type |

The subtitle shows the baselines (L, M, H for Low, Moderate, High, P for Privacy), then the first mapped 800-171 R3 requirement, CSF subcategory and CIS safeguard, with +N for more.

Type `171` for SP 800-171. Query by requirement ID (`3.1.1`, `03.01.01`), by family (`3.1`, `03.01`) or by words. Rev 2 and Rev 3 are shown side by side, because CMMC Level 2 still uses Rev 2.

| Key | Action |
|---|---|
| ↩ | Copy ID, title and statement |
| ⌘ ↩ | Open the requirement on NIST CPRT |
| ⌥ ↩ | Copy the list of 800-53 source controls |

The subtitle shows the 800-53 source controls. For Rev 3 these are NIST's own. For Rev 2 see "Rev 2 via R3" below.

Each result has a monogram icon for its 800-53 family; 800-171 requirements use the matching 800-53 family, so Access Control looks the same under both keywords. Withdrawn items are grey and listed last.

### Rev 2 via R3

NIST publishes no mapping from SP 800-171 Rev 2 to SP 800-53 Rev 5. The workflow gives each Rev 2 requirement the 800-53 sources of the Rev 3 requirement with the same number (3.1.1 uses 03.01.01). Where that Rev 3 requirement was withdrawn, it follows NIST's "incorporated into" or "addressed by" link to the live requirement, so 3.12.4 uses 03.15.02. This bridge is not an official NIST mapping, and the workflow labels it "via R3" wherever it is shown or copied.

## Configuration

Open the workflow in Alfred Preferences and click Configure Workflow.

| Setting | Default | Meaning |
|---|---|---|
| CIS xlsx path | empty | Optional. Path to your own copy of the CIS v8.1 to SP 800-53 mapping (see below) |

### Adding the CIS crosswalk

The CIS Controls v8.1 mapping to SP 800-53 Rev 5 is published by the Center for Internet Security under CC BY-NC-ND 4.0, which does not allow redistribution of derived data. It is therefore not part of this repository or of the release package. To use the `cis` lookups and the CIS column of the crosswalk:

1. Download "CIS Controls v8.1 Mapping to NIST SP 800-53 Rev 5" (xlsx) from CIS yourself: https://www.cisecurity.org/controls. Use it within the CIS licence terms.
2. Enter its path as CIS xlsx path in Configure Workflow.
3. In the workflow folder, run `/usr/bin/python3 build_index.py`.

The build writes the CIS crosswalk to `cis.json` next to `controls.json`, and the workflow merges it when it is present. `controls.json` never contains CIS data. `cis.json` is ignored by git and left out of the release package; do not commit, upload or share it. You can also pass the path for one build with `CIS_XLSX=/path/to/file.xlsx /usr/bin/python3 build_index.py`.

## Data sources

`controls.json` is built by `build_index.py` from these public NIST sources:

| Data | Source |
|---|---|
| SP 800-53 Rev 5.2.0 controls and baselines | NIST OSCAL content, https://github.com/usnistgov/oscal-content |
| SP 800-171 Rev 3 requirements and their 800-53 sources | NIST OSCAL content, same repository |
| SP 800-171 Rev 2 requirements | NIST CSRC, security requirements CSV |
| CSF 2.0 to SP 800-53 Rev 5.2.0 | CSF 2.0 Reference Tool, informative references export, NIST CSRC |

NIST SP 800-53 and SP 800-171 are works of the US Government and are not subject to copyright protection in the United States. The CSF 2.0 informative references are user-generated content that NIST hosts; NIST states they are not an official NIST publication. Check the NIST originals before you rely on a mapping.

To pick up a new NIST release, run `/usr/bin/python3 build_index.py`. It checks each source against expected sizes and stops without changing anything if a source has changed shape.

## Requirements

- macOS with Alfred 5 and the Powerpack
- `/usr/bin/python3` (installed with the Xcode Command Line Tools)

Lookups need no network. Only `build_index.py` downloads from NIST.

## Icons

Icons are drawn by `iconkit.js`, a small JavaScript for Automation script that uses AppKit, so there is nothing to install. They are pre-rendered into `icons/`; run `/usr/bin/python3 -B make_icons.py` to regenerate them after a colour change.

## Install

Download the latest `.alfredworkflow` from Releases and open it.

To work on it, clone the repository and symlink it into Alfred's workflows folder:

```sh
git clone https://github.com/ndcorder/alfred-nist-controls.git
ln -s "$PWD/alfred-nist-controls" "<Alfred preferences>/Alfred.alfredpreferences/workflows/alfred-nist-controls"
```

Your Configure Workflow values are saved in `prefs.plist` in the workflow folder, which is ignored by git.

## Development

```sh
/usr/bin/python3 -B -m unittest test_ctl test_sp171 test_build_index
```

Tests use made-up data and temporary folders only; they never download anything or run osascript. One test builds an index with a fake CIS file and fails if any CIS data ends up in `controls.json`; another checks the committed `controls.json`.

## Licence

The code is MIT. See [LICENSE](LICENSE). The NIST data in `controls.json` is described under Data sources. CIS data is not included.
