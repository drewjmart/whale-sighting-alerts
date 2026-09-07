"""
Shared color palette for the map, its legend, and every chart -- one
source of truth so "consistent color scheme across the map legend and
all charts" (the actual requirement) doesn't drift between files.

Uses the dataviz skill's validated default categorical palette unchanged
(8 hues, fixed order -- see palette.md): assigned in that fixed order to
the 8 most meaningful categories (the 4 orca pod codes people actually
track, then the 4 non-orca species with real data). The two "unresolved"
orca-pod buckets (SRKW_UNSPECIFIED, UNKNOWN) share a single muted gray
rather than a validated hue -- deliberately: they represent an
unconfirmed identification, and looking visually recessive/neutral
matches that meaning instead of competing for attention with confirmed
categories. Same principle the code already uses elsewhere (an explicit
UNKNOWN bucket, never a silent guess) applied to color.

Light-mode hexes only for now -- this dashboard is a local dev tool
without a theme toggle; the dark-mode steps are documented in
palette.md if that changes later.
"""

from __future__ import annotations

MUTED = "#898781"  # "unresolved" -- shared by SRKW_UNSPECIFIED and UNKNOWN pod codes

POD_COLORS: dict[str, str] = {
    "J": "#2a78d6",                 # slot 1: blue
    "K": "#eb6834",                 # slot 2: orange
    "L": "#1baf7a",                 # slot 3: aqua
    "BIGGS_TRANSIENT": "#eda100",   # slot 4: yellow
    "SRKW_UNSPECIFIED": MUTED,
    "UNKNOWN": MUTED,
}

SPECIES_COLORS: dict[str, str] = {
    "humpback": "#e87ba4",     # slot 5: magenta
    "gray_whale": "#008300",   # slot 6: green
    "porpoise": "#4a3aa7",     # slot 7: violet
    "dolphin": "#e34948",      # slot 8: red (no real records yet, but reserved)
    "unknown": "#e34948",      # shares slot 8 -- "unidentified species" and "dolphin" don't
                                # co-occur in practice, and both are low-confidence/rare buckets
    "orca": MUTED,              # never actually rendered -- orca markers use POD_COLORS instead;
                                 # kept here only so a lookup never KeyErrors on an unexpected value
}

# Chart chrome, from the dataviz skill's reference palette (light mode).
INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRIDLINE = "#e1e0d9"
SURFACE = "#fcfcfb"
PAGE = "#f9f9f7"


def color_for_species_or_pod(species: str, pod_code: str | None) -> str:
    """The one function everything (map markers, legends, charts) should
    call for a color -- orca uses its pod code (first pod if multiple are
    comma-joined), everything else uses its species color."""
    if species == "orca" and pod_code:
        first_pod = pod_code.split(",")[0]
        return POD_COLORS.get(first_pod, MUTED)
    return SPECIES_COLORS.get(species, MUTED)
