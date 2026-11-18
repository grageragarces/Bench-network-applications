"""Links of equal fidelity and different noise, in qnetbench's engine against native NetSquid.

`native_netsquid.py` (section B) shows that the kind of noise on a link moves results at equal
fidelity, using protocols written directly on NetSquid. The engine used to build every pair as a
Werner state, so it could produce only the first of those columns. With `LinkModel.noise` it builds
any Bell-diagonal pair, so this runs the same three quantities through the engine with Werner,
dephased and bit-flipped links and sets them beside the native values. Amplitude damping is not
Bell-diagonal, so it stays native only.

The engine runs here with the same settings `native_netsquid.py` gives it: 32 seeds of 256 rounds,
1 ms classical delay and generation time, no memory noise.

    .venv/bin/python scripts/paper/link_noise.py
"""

from __future__ import annotations

import math
import multiprocessing
import re
import statistics
from pathlib import Path

from qnetbench.apps import get_app
from qnetbench.backends.reference import ReferenceBackend
from qnetbench.characterize.provenance import write_atomic
from qnetbench.tenancy import ExecutionModel, TenantSpec, application_utility, run_tenants
from qnetbench.topology import LinkModel, default_topology
from qnetbench.trace.events import AppOutcomeEvent

DATA = Path(__file__).parent / "data"
OUT = DATA / "link_noise.txt"
SEEDS = 32
SHOTS = 256
DELAY = 1e-3
FIDELITIES = (0.85, 0.95)
KINDS = ("teleport", "swap", "qber")
NOISES = ("depolarizing", "dephasing", "bit_flip")
LABEL = {"teleport": "teleport", "swap": "swap", "qber": "BBM92 QBER"}


def _cell(args: tuple[str, float, str, int]) -> tuple[tuple[str, float, str, int], float]:
    kind, fidelity, noise, seed = args
    link = LinkModel(DELAY, fidelity, 0.0, noise)  # type: ignore[arg-type]
    if kind == "teleport":
        run = run_tenants(
            [TenantSpec("t", "teleportation", {"rounds": SHOTS})],
            seed=seed,
            link=link,
            model=ExecutionModel(arrivals="closed_loop"),
        )
        return args, application_utility(run.traces["t"])
    if kind == "qber":
        run = run_tenants(
            [TenantSpec("t", "qkd", {"rounds": SHOTS})],
            seed=seed,
            link=link,
            model=ExecutionModel(arrivals="closed_loop", aging="none"),
        )
        outcome = next(e for e in run.traces["t"] if isinstance(e, AppOutcomeEvent))
        return args, float(outcome.payload["qber"])
    app = get_app("entanglement_swap")
    roles = app.roles()
    backend = ReferenceBackend(default_topology(roles, link=link), seed=seed)
    return args, application_utility(backend.run(app, {"rounds": SHOTS}, {r: r for r in roles}))


def _native() -> dict[tuple[str, float], dict[str, float]]:
    """Section B of native_netsquid.txt: Werner, dephased and amplitude columns."""
    text = (DATA / "native_netsquid.txt").read_text()
    section = text.split("B. Links of equal fidelity", 1)[1].split("\nC. ", 1)[0]
    rows: dict[tuple[str, float], dict[str, float]] = {}
    for line in section.splitlines():
        m = re.match(
            r"\s+(teleport|swap|BBM92 QBER)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)", line
        )
        if m:
            name, f, werner, dephased, amplitude = m.groups()
            rows[(name, float(f))] = {
                "werner": float(werner),
                "dephased": float(dephased),
                "amplitude": float(amplitude),
            }
    return rows


def main() -> None:
    work = [(k, f, n, s) for k in KINDS for f in FIDELITIES for n in NOISES for s in range(SEEDS)]
    with multiprocessing.Pool() as pool:
        results = dict(pool.map(_cell, work, chunksize=8))
    native = _native()

    def summary(kind: str, f: float, noise: str) -> tuple[float, float]:
        values = [results[(kind, f, noise, s)] for s in range(SEEDS)]
        return statistics.fmean(values), statistics.stdev(values) / math.sqrt(SEEDS)

    lines = [
        "Links of equal fidelity and different noise. qnetbench's engine, 32 seeds of 256 rounds,",
        "against native NetSquid (native_netsquid.txt, section B). No memory noise.",
        "",
        f"   {'quantity':12}{'F':>6}{'engine Werner':>17}{'native':>9}{'engine dephased':>19}"
        f"{'native':>9}{'engine bit flip':>19}{'native amplitude':>18}",
    ]
    worst = 0.0
    for kind in KINDS:
        for f in FIDELITIES:
            name = LABEL[kind]
            werner, werner_se = summary(kind, f, "depolarizing")
            dephased, dephased_se = summary(kind, f, "dephasing")
            flipped, flipped_se = summary(kind, f, "bit_flip")
            ref = native[(name, f)]
            for value, se, target in (
                (werner, werner_se, ref["werner"]),
                (dephased, dephased_se, ref["dephased"]),
            ):
                if se > 0:
                    worst = max(worst, abs(value - target) / se)
            lines.append(
                f"   {name:12}{f:>6.2f}{werner:>10.4f} ± {werner_se:.4f}{ref['werner']:>9.4f}"
                f"{dephased:>12.4f} ± {dephased_se:.4f}{ref['dephased']:>9.4f}"
                f"{flipped:>12.4f} ± {flipped_se:.4f}{ref['amplitude']:>18.4f}"
            )
    lines += [
        "",
        "Largest gap between engine and native, Werner and dephased columns: "
        f"{worst:.1f} engine s.e.",
        "The native values carry their own sampling error, about 0.004 for swap and QBER.",
        "Bit flip has no native column. Amplitude damping is not Bell-diagonal, so the engine has",
        "no column for it.",
    ]
    text = "\n".join(lines) + "\n"
    write_atomic(OUT, text)
    print(text)


if __name__ == "__main__":
    main()
