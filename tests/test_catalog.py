"""The benchmark catalog: a curated core plus 50+ parameterized instances."""

from __future__ import annotations

import pytest

from qnetbench.apps import available_apps, catalog_apps, get_app
from qnetbench.harness.runner import run_once
from qnetbench.metrics import compute_report
from qnetbench.topology import LinkModel, Topology, line2, star

_PERFECT = LinkModel(link_fidelity=1.0, fidelity_std=0.0)


def _perfect_topology(app: str) -> Topology:
    """A noiseless topology matching an app's role structure."""
    roles = get_app(app).roles()
    if len(roles) == 2:
        return line2(roles[0], roles[1], link=_PERFECT)
    return star(roles[0], list(roles[1:]), link=_PERFECT)


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


@pytest.mark.parametrize("app", catalog_apps())
def test_every_catalog_entry_runs(app: str) -> None:
    """Run every catalog entry (all 50+) noiselessly — the full-catalog CI coverage.
    DQC entries are mirror circuits, so they must return exactly |0…0>; every entry
    must produce demand (a delivered pair or a transmitted qubit)."""
    report = compute_report(run_once(app, seed=0, topology=_perfect_topology(app)))
    if app.startswith("dqc_"):
        assert report.app_utility == 1.0  # U;U† returns every qubit to |0>
    assert report.n_delivered > 0 or report.qubits_sent > 0
