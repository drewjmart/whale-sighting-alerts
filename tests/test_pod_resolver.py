from normalization.pod_resolver import normalize_species, resolve_pod, normalize_sighting


# ── Species classification ──────────────────────────────────────────────

def test_normalize_species_known_values():
    # Real values confirmed from a live Acartia API response.
    assert normalize_species("Orca") == "orca"
    assert normalize_species("Southern Resident Orca") == "orca"
    assert normalize_species("Humpback") == "humpback"
    assert normalize_species("Gray Whale") == "gray_whale"
    assert normalize_species("Dall's Porpoise") == "porpoise"
    assert normalize_species("Harbor Porpoise") == "porpoise"


def test_normalize_species_unknown_and_empty_never_crash():
    assert normalize_species("Unspecified") == "unknown"
    assert normalize_species("") == "unknown"
    assert normalize_species(None) == "unknown"
    assert normalize_species("Some Totally New Species") == "unknown"


def test_normalize_species_case_insensitive():
    assert normalize_species("HUMPBACK") == "humpback"
    assert normalize_species("  orca  ") == "orca"


# ── Pod resolution ───────────────────────────────────────────────────────

def test_resolve_pod_none_for_non_orca_species():
    # Pod ID is orca-specific -- even if the text mentions "J pod" by
    # mistake, a non-orca species record must not get a pod code.
    assert resolve_pod("humpback", "J pod nearby") is None
    assert resolve_pod("gray_whale", "") is None


def test_resolve_pod_j_k_l():
    assert resolve_pod("orca", "J pod headed north") == "J"
    assert resolve_pod("orca", "K-pod spotted off Alki") == "K"
    assert resolve_pod("orca", "Lpod southbound") == "L"  # tight spacing variant


def test_resolve_pod_biggs_transient_variants():
    assert resolve_pod("orca", "Bigg's transients southbound") == "BIGGS_TRANSIENT"
    assert resolve_pod("orca", "Biggs orcas, fast-moving") == "BIGGS_TRANSIENT"
    assert resolve_pod("orca", "transient orcas near Duwamish Head") == "BIGGS_TRANSIENT"


def test_resolve_pod_srkw_unspecified():
    assert resolve_pod("orca", "SRKW spotted, pod not yet confirmed") == "SRKW_UNSPECIFIED"
    assert resolve_pod("orca", "Southern resident orcas offshore") == "SRKW_UNSPECIFIED"


def test_resolve_pod_multiple_pods_comma_joined_stable_order():
    # "L and J pods" mentioned out of order -> output is still J,L (stable order).
    assert resolve_pod("orca", "L and J pods traveling together") == "J,L"


def test_resolve_pod_shared_suffix_list_spec_example():
    # The spec's own "known nuance" example: "L" isn't directly followed by
    # "pod" here -- "pods" is only spelled once, shared across the list.
    assert resolve_pod("orca", "J & L pods, Whidbey Island") == "J,L"


def test_resolve_pod_unresolved_text_is_explicit_unknown_not_silent():
    # Acceptance criteria: no silent misclassification -- an orca record
    # with no recognizable pod mention must resolve to the explicit
    # "UNKNOWN" bucket, not None and not a guess.
    assert resolve_pod("orca", "orca spotted, no other details") == "UNKNOWN"
    assert resolve_pod("orca", "") == "UNKNOWN"
    assert resolve_pod("orca", None) == "UNKNOWN"


def test_normalize_sighting_combines_both():
    result = normalize_sighting("Orca", "[Orca Network] J pod, northbound (Susan Berta)")
    assert result == {"species": "orca", "pod_code": "J"}

    result = normalize_sighting("Humpback", "feeding near Elliott Bay")
    assert result == {"species": "humpback", "pod_code": None}
