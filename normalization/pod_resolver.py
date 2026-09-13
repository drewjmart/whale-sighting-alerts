"""
Species classification + orca pod normalization.

Free text is messy: sources describe sightings informally ("J & L pods,
Whidbey Island", "Bigg's transients southbound"). This module turns that
into structured categories with an explicit UNKNOWN/unresolved bucket --
per the acceptance criteria, silent misclassification is worse than an
honest "we don't know."

Reference basis for the pod lookup table: Center for Whale Research and
Orca Conservancy pod ID conventions (J/K/L pods = Southern Resident orcas;
Bigg's/Transient = the other common West Coast orca ecotype). No API for
either -- this is a static table, not a live lookup.
"""

from __future__ import annotations

import re

# ── Species classification ──────────────────────────────────────────────
# Keys are lowercased. Covers Acartia's confirmed live 'type' values
# (Orca, Southern Resident Orca, Humpback, Gray Whale, Dall's Porpoise,
# Harbor Porpoise, Unspecified -- seen in a real API response) plus common
# free-text variants from Orca Network-style reports.

_SPECIES_MAP = {
    "orca": "orca",
    "southern resident orca": "orca",
    "transient orca": "orca",
    "biggs orca": "orca",
    "bigg's orca": "orca",
    "killer whale": "orca",
    "humpback": "humpback",
    "humpback whale": "humpback",
    "gray whale": "gray_whale",
    "grey whale": "gray_whale",
    "dall's porpoise": "porpoise",
    "dalls porpoise": "porpoise",
    "harbor porpoise": "porpoise",
    "porpoise": "porpoise",
    "dolphin": "dolphin",
    "unspecified": "unknown",
    "": "unknown",
}

VALID_SPECIES = {"orca", "humpback", "gray_whale", "porpoise", "dolphin", "unknown"}

# Display names (2026-09-08): VALID_SPECIES are internal/storage codes
# (snake_case, matched against free text) -- every user-facing surface
# (checkboxes, tables, map popups, KPI tiles) should show these instead,
# so "gray_whale" never appears in the UI. One dict, reused everywhere via
# species_display_name()/the "friendly_species" Jinja filter (dashboard/app.py)
# rather than each template inventing its own title-casing.
SPECIES_DISPLAY_NAMES: dict[str, str] = {
    "orca": "Orca",
    "humpback": "Humpback",
    "gray_whale": "Gray whale",
    "porpoise": "Porpoise",
    "dolphin": "Dolphin",
    "unknown": "Unidentified species",
}


def normalize_species(species_raw: str | None) -> str:
    """Map a source's free-text/enum species value to one of VALID_SPECIES.
    Unrecognized input maps to 'unknown' rather than guessing."""
    if not species_raw:
        return "unknown"
    key = species_raw.strip().lower()
    return _SPECIES_MAP.get(key, "unknown")


def species_display_name(species: str | None) -> str:
    """Friendly label for a species code. Falls back to a title-cased,
    underscore-stripped version of whatever was passed rather than
    KeyError-ing -- defensive only; every real value should be in
    SPECIES_DISPLAY_NAMES since it's a closed set (VALID_SPECIES)."""
    if not species:
        return ""
    return SPECIES_DISPLAY_NAMES.get(species, species.replace("_", " ").title())


# ── Orca pod resolution ──────────────────────────────────────────────────
# Checked independently; ALL matching patterns contribute to the result (a
# report can legitimately mention more than one pod).
#
# Single-letter mentions ("J pod", "K-pod", "Lpods") are each their own
# pattern. But free text commonly shares one "pod(s)" across a list of
# letters -- the spec's own example is "J & L pods, Whidbey Island", where
# "L" isn't immediately followed by "pod" at all; "pods" only appears once,
# after "L". _POD_LIST_PATTERN below handles that: it matches a short run
# of J/K/L letters joined by ",", "&", "/", or "and", immediately followed
# by "pod(s)", and every letter in the run counts as a match.

_POD_SINGLE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bj\s*-?\s*pods?\b", re.IGNORECASE), "J"),
    (re.compile(r"\bk\s*-?\s*pods?\b", re.IGNORECASE), "K"),
    (re.compile(r"\bl\s*-?\s*pods?\b", re.IGNORECASE), "L"),
]

_POD_LIST_PATTERN = re.compile(
    r"\b(?:[jkl]\s*(?:[,/&]|and)?\s*){2,3}pods?\b", re.IGNORECASE
)

_ECOTYPE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bbigg'?s\b", re.IGNORECASE), "BIGGS_TRANSIENT"),
    (re.compile(r"\btransients?\b", re.IGNORECASE), "BIGGS_TRANSIENT"),
    (re.compile(r"\bsrkw\b", re.IGNORECASE), "SRKW_UNSPECIFIED"),
    (re.compile(r"\bsouthern\s+resident", re.IGNORECASE), "SRKW_UNSPECIFIED"),
]

# Stable output order regardless of match order in the text.
_POD_CODE_ORDER = ["J", "K", "L", "BIGGS_TRANSIENT", "SRKW_UNSPECIFIED"]

# Display names (2026-09-08) -- same rationale as SPECIES_DISPLAY_NAMES:
# pod_code is a storage code ("BIGGS_TRANSIENT", "UNKNOWN"), not something
# to show verbatim outside the map legend (which already spells these out
# in context, e.g. "Orca -- Bigg's/Transient"). This is the shorter form
# for a table cell or popup line, where "Orca -- " would be redundant.
POD_DISPLAY_NAMES: dict[str, str] = {
    "J": "J pod",
    "K": "K pod",
    "L": "L pod",
    "BIGGS_TRANSIENT": "Bigg's/Transient",
    "SRKW_UNSPECIFIED": "Southern Resident (pod unconfirmed)",
    "UNKNOWN": "Pod unresolved",
}


def pod_code_display(pod_code: str | None) -> str:
    """Friendly label for a (possibly comma-joined, e.g. "J,L") pod_code
    value. Empty string for no pod code -- callers decide whether that
    means "not orca" or "orca, unresolved" (UNKNOWN is a stored value in
    its own right and is handled above, distinct from None/empty)."""
    if not pod_code:
        return ""
    return ", ".join(POD_DISPLAY_NAMES.get(code, code) for code in pod_code.split(","))


def resolve_pod(species: str, text: str | None) -> str | None:
    """Resolve orca pod code(s) from free text. Returns None for non-orca
    species (pod ID is orca-specific per the spec's scope). For orca
    records, returns a comma-joined code string (e.g. "J,L") if multiple
    pods are mentioned, a single code if one is, or "UNKNOWN" if the text
    doesn't resolve to anything recognized -- never silently guesses.
    """
    if species != "orca":
        return None

    text = text or ""
    matched: set[str] = {code for pattern, code in _ECOTYPE_PATTERNS if pattern.search(text)}
    matched |= {code for pattern, code in _POD_SINGLE_PATTERNS if pattern.search(text)}

    for list_match in _POD_LIST_PATTERN.finditer(text):
        matched |= {letter.upper() for letter in re.findall(r"[jklJKL]", list_match.group())}

    if not matched:
        return "UNKNOWN"

    ordered = [code for code in _POD_CODE_ORDER if code in matched]
    return ",".join(ordered)


def normalize_sighting(species_raw: str | None, text: str | None) -> dict[str, str | None]:
    """Convenience wrapper: classify species and resolve pod in one call."""
    species = normalize_species(species_raw)
    pod_code = resolve_pod(species, text)
    return {"species": species, "pod_code": pod_code}
