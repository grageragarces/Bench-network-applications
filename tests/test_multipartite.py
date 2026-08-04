"""Quantum secret sharing and conference key agreement (multipartite protocols)."""

from __future__ import annotations

import pytest

from qnetbench.harness.runner import run_once
from qnetbench.metrics import compute_report
from qnetbench.topology import LinkModel, star

_PL = LinkModel(link_fidelity=1.0, fidelity_std=0.0)
PERFECT_SS = star("dealer", ["player1", "player2"], link=_PL)
PERFECT_CK = star("hub", ["leaf1", "leaf2", "leaf3"], link=_PL)
PERFECT_TSS = star("dealer", ["player1", "player2", "player3", "player4"], link=_PL)


def _report(app: str, seed: int, topo):
    return compute_report(run_once(app, seed=seed, topology=topo))


# --- (n,n) quantum secret sharing ---------------------------------------------


@pytest.mark.parametrize("seed", range(6))
def test_secret_sharing_reconstructs_noiseless(seed: int) -> None:
    assert _report("secret_sharing", seed, PERFECT_SS).app_utility == 1.0


def test_secret_sharing_is_three_party() -> None:
    assert len(_report("secret_sharing", 0, PERFECT_SS).roles) == 3


def test_secret_sharing_degrades_with_fidelity() -> None:
    def mean(fidelity: float) -> float:
        link = LinkModel(link_fidelity=fidelity, fidelity_std=0.0)
        topo = star("dealer", ["player1", "player2"], link=link)
        return sum(_report("secret_sharing", s, topo).app_utility for s in range(6)) / 6

    assert mean(1.0) >= mean(0.9) >= mean(0.8)


# --- conference key agreement (4-party) ---------------------------------------


@pytest.mark.parametrize("seed", range(6))
def test_conference_key_agrees_noiseless(seed: int) -> None:
    assert _report("conference_key", seed, PERFECT_CK).app_utility == 1.0


def test_conference_key_is_four_party() -> None:
    assert len(_report("conference_key", 0, PERFECT_CK).roles) == 4  # highest party count


def test_conference_key_demand_is_three_pairs_per_round() -> None:
    from qnetbench.trace.events import EntanglementRequested

    events = run_once("conference_key", seed=0, topology=PERFECT_CK, cfg={"rounds": 10})
    assert sum(1 for e in events if isinstance(e, EntanglementRequested)) == 30


# --- ((3,5)) threshold quantum secret sharing (five-qubit code) ----------------


@pytest.mark.parametrize("seed", range(6))
def test_threshold_secret_sharing_reconstructs_noiseless(seed: int) -> None:
    # A random authorized 3-subset reconstructs every round -> utility 1.0.
    assert _report("threshold_secret_sharing", seed, PERFECT_TSS).app_utility == 1.0


def test_threshold_secret_sharing_is_five_party() -> None:
    assert len(_report("threshold_secret_sharing", 0, PERFECT_TSS).roles) == 5


def test_threshold_secret_sharing_distributes_four_shares_per_round() -> None:
    from qnetbench.trace.events import QubitSent

    events = run_once("threshold_secret_sharing", seed=0, topology=PERFECT_TSS, cfg={"rounds": 10})
    assert sum(1 for e in events if isinstance(e, QubitSent)) == 40  # 4 shares x 10 rounds


def test_threshold_secret_sharing_degrades_with_fidelity() -> None:
    def mean(fidelity: float) -> float:
        link = LinkModel(link_fidelity=fidelity, fidelity_std=0.0)
        topo = star("dealer", ["player1", "player2", "player3", "player4"], link=link)
        return sum(_report("threshold_secret_sharing", s, topo).app_utility for s in range(6)) / 6

    assert mean(1.0) >= mean(0.9) >= mean(0.8)


def test_five_qubit_code_constants_are_self_consistent() -> None:
    """The embedded encoder + reconstruction table must satisfy the code's guarantees:
    every 3-subset recovers both secrets, and any 2 qubits are independent of the secret."""
    import itertools

    import numpy as np

    from qnetbench.apps.threshold_secret_sharing import _ENCODER, _RECON

    N = 5
    H = np.array([[1, 1], [1, -1]], dtype=complex) / np.sqrt(2)
    X = np.array([[0, 1], [1, 0]], dtype=complex)
    Z = np.array([[1, 0], [0, -1]], dtype=complex)
    Y = np.array([[0, -1j], [1j, 0]], dtype=complex)
    CN = np.eye(4, dtype=complex)[[0, 1, 3, 2]].reshape(2, 2, 2, 2)

    def apply(psi, gate):
        p = psi.reshape([2] * N)
        if gate[0] == "H":
            p = np.moveaxis(np.tensordot(H, p, axes=([1], [gate[1]])), 0, gate[1])
        elif gate[0] in ("X", "Z"):
            m = X if gate[0] == "X" else Z
            p = np.moveaxis(np.tensordot(m, p, axes=([1], [gate[1]])), 0, gate[1])
        else:
            c, t = gate[1], gate[2]
            p = np.moveaxis(np.tensordot(CN, p, axes=([2, 3], [c, t])), [0, 1], [c, t])
        return p.reshape(-1)

    def encode(secret: int):
        psi = np.zeros(2**N, dtype=complex)
        psi[0] = 1.0
        for g in _ENCODER:
            psi = apply(psi, g)
        if secret:
            for q in range(N):
                psi = apply(psi, ("X", q))
        return psi

    states = {0: encode(0), 1: encode(1)}

    # projector onto measurement outcome bit `b` for a single-qubit Pauli on qubit q
    def project(psi, q, pauli, bit):
        M = {"X": X, "Y": Y, "Z": Z}[pauli]
        eigval = 1 - 2 * bit  # bit 0 -> +1, bit 1 -> -1
        proj = (np.eye(2, dtype=complex) + eigval * M) / 2
        v = np.moveaxis(np.tensordot(proj, psi.reshape([2] * N), axes=([1], [q])), 0, q).reshape(-1)
        return v

    # every authorized 3-subset reconstructs both secrets deterministically
    assert len(_RECON) == 10
    for subset, (bases, flip) in _RECON.items():
        for secret in (0, 1):
            psi = states[secret]
            # the joint Pauli is deterministic on the codeword: measuring qubit-by-qubit,
            # the total parity is fixed. Check the surviving branch reproduces `secret`.
            recovered_parity = None
            for bits in itertools.product((0, 1), repeat=3):
                v = psi
                for q, pauli, b in zip(subset, bases, bits, strict=True):
                    v = project(v, q, pauli, b)
                if np.linalg.norm(v) > 1e-9:  # this outcome branch is possible
                    parity = bits[0] ^ bits[1] ^ bits[2]
                    if recovered_parity is None:
                        recovered_parity = parity
                    assert recovered_parity == parity  # deterministic
            assert (recovered_parity ^ flip) == secret

    # security: any 1 or 2 qubits carry a reduced state independent of the secret
    def reduced(psi, keep):
        p = psi.reshape([2] * N)
        comp = [q for q in range(N) if q not in keep]
        return np.tensordot(p, p.conj(), axes=(comp, comp))

    for size in (1, 2):
        for keep in itertools.combinations(range(N), size):
            r0 = reduced(states[0], list(keep))
            r1 = reduced(states[1], list(keep))
            assert np.allclose(r0, r1, atol=1e-9)
