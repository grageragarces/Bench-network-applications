"""The benchmark catalog: a curated core plus 50+ parameterized instances."""

from __future__ import annotations

import pytest

from qnetbench.apps import available_apps, catalog_apps, get_app
from qnetbench.harness.runner import run_once
from qnetbench.metrics import compute_report
from qnetbench.topology import LinkModel, line2

PERFECT = line2(link=LinkModel(link_fidelity=1.0, fidelity_std=0.0))

# One representative catalog entry per DQC circuit family (small size for speed).
_FAMILY_SAMPLES = ["dqc_ghz5", "dqc_qft5", "dqc_random5", "dqc_graph5", "dqc_iqp5", "dqc_hea5"]


def test_catalog_has_at_least_fifty() -> None:
    assert len(catalog_apps()) >= 50


def test_core_is_a_subset_of_the_catalog() -> None:
    assert set(available_apps()) <= set(catalog_apps())
    assert len(available_apps()) < len(catalog_apps())  # the catalog genuinely extends the core


def test_get_app_resolves_non_core_catalog_entries() -> None:
    non_core = set(catalog_apps()) - set(available_apps())
    assert non_core
    name = sorted(non_core)[0]
    assert get_app(name).name == name


def test_get_app_rejects_unknown() -> None:
    with pytest.raises(KeyError, match="list --all"):
        get_app("does_not_exist")


@pytest.mark.parametrize("app", _FAMILY_SAMPLES)
def test_catalog_dqc_families_verify_noiseless(app: str) -> None:
    # Every DQC circuit is a mirror circuit, so a noiseless run returns |0…0>.
    assert compute_report(run_once(app, seed=0, topology=PERFECT)).app_utility == 1.0
