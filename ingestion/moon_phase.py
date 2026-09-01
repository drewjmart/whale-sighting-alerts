"""
Moon phase -- EXPERIMENTAL, exploratory only.

Per the README feature hierarchy: no established research ties SRKW (or
any species tracked here) presence to lunar phase. This exists to test
that hypothesis honestly, not because it's a relied-upon predictor.
Every value this module produces is stored under the
`experimental_moon_phase` column (see storage/schema.sql) and must stay
labeled `experimental_` anywhere it appears -- schema, code, README,
analysis output -- never presented as validated.

Computed locally via `astral` (already a dependency, no network call, no
external data source, can't go stale or break).
"""

from __future__ import annotations

from datetime import date

from astral import moon

# astral.moon.phase() returns 0..27.99 (days since new moon).
PHASE_LABELS = [
    (7, "new_moon"),
    (14, "first_quarter"),
    (21, "full_moon"),
    (28, "last_quarter"),
]


def compute_experimental_moon_phase(for_date: date) -> float:
    """Raw 0-27.99 phase value for the given date. Always labeled
    `experimental_` downstream -- see module docstring."""
    return moon.phase(for_date)


def experimental_moon_phase_label(phase_value: float) -> str:
    """Coarse category for readability in analysis output. Still
    experimental -- a label doesn't make it a validated predictor."""
    for upper_bound, label in PHASE_LABELS:
        if phase_value < upper_bound:
            return label
    return "last_quarter"


if __name__ == "__main__":
    today = date.today()
    value = compute_experimental_moon_phase(today)
    print(f"experimental_moon_phase for {today}: {value:.2f} ({experimental_moon_phase_label(value)})")
