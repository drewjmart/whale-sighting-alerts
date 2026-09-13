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

Dark-mode steps added 2026-09-08 (dashboard/templates/base.html's theme
toggle) -- pulled verbatim from the dataviz skill's reference palette
(references/palette.md), which pre-validated this exact 8-hue set for a
`#1a1a19` dark chart surface: "the same eight hues stepped for the dark
surface, not a separate palette." Contrast was re-verified for this
project specifically (WCAG relative-luminance contrast ratio, computed,
not eyeballed) against our actual dark surface -- every categorical/ink
color clears its threshold; see the item-3 commit message for the numbers.
"""

from __future__ import annotations

MUTED = "#898781"  # "unresolved" -- shared by SRKW_UNSPECIFIED and UNKNOWN pod codes; same in both modes

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

POD_COLORS_DARK: dict[str, str] = {
    "J": "#3987e5",
    "K": "#d95926",
    "L": "#199e70",
    "BIGGS_TRANSIENT": "#c98500",
    "SRKW_UNSPECIFIED": MUTED,
    "UNKNOWN": MUTED,
}

SPECIES_COLORS_DARK: dict[str, str] = {
    "humpback": "#d55181",
    "gray_whale": "#008300",   # same in both modes -- already clears 3:1 on both surfaces
    "porpoise": "#9085e9",
    "dolphin": "#e66767",
    "unknown": "#e66767",
    "orca": MUTED,
}

# Chart chrome, from the dataviz skill's reference palette.
INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRIDLINE = "#e1e0d9"
SURFACE = "#fcfcfb"
PAGE = "#f9f9f7"

INK_PRIMARY_DARK = "#ffffff"
INK_SECONDARY_DARK = "#c3c2b7"
INK_MUTED_DARK = "#898781"   # same in both modes
GRIDLINE_DARK = "#2c2c2a"
SURFACE_DARK = "#1a1a19"
PAGE_DARK = "#0d0d0d"


def pod_colors(theme: str = "light") -> dict[str, str]:
    return POD_COLORS_DARK if theme == "dark" else POD_COLORS


def species_colors(theme: str = "light") -> dict[str, str]:
    return SPECIES_COLORS_DARK if theme == "dark" else SPECIES_COLORS


def chart_chrome(theme: str = "light") -> dict[str, str]:
    """The ink/surface/gridline set a chart needs, bundled by theme --
    everything viz/correlations.py and viz/map.py's legend need to
    re-theme without importing every constant individually."""
    if theme == "dark":
        return dict(
            ink_primary=INK_PRIMARY_DARK, ink_secondary=INK_SECONDARY_DARK,
            ink_muted=INK_MUTED_DARK, gridline=GRIDLINE_DARK,
            surface=SURFACE_DARK, page=PAGE_DARK,
        )
    return dict(
        ink_primary=INK_PRIMARY, ink_secondary=INK_SECONDARY,
        ink_muted=INK_MUTED, gridline=GRIDLINE,
        surface=SURFACE, page=PAGE,
    )


def color_for_species_or_pod(species: str, pod_code: str | None, theme: str = "light") -> str:
    """The one function everything (map markers, legends, charts) should
    call for a color -- orca uses its pod code (first pod if multiple are
    comma-joined), everything else uses its species color."""
    pods, species_map = pod_colors(theme), species_colors(theme)
    if species == "orca" and pod_code:
        first_pod = pod_code.split(",")[0]
        return pods.get(first_pod, MUTED)
    return species_map.get(species, MUTED)
