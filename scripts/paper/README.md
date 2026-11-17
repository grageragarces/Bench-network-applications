# Paper reproduction code

Everything that produces a table or a figure in the qnetbench TQE paper, plus the
generated data those tables and figures are drawn from. The LaTeX source for the
manuscript itself is not part of this repository; this directory is.

Run everything from the repository root, in an environment with the package
installed (`pip install -e ".[viz]"`). Most of it runs on the reference backend with no simulator;
the scripts that need SeQUeNCe or NetSquid are marked in the last table.

## Demand signatures (Table 2, Figure 2)

    qnetbench characterize --out scripts/paper/data/
    python scripts/paper/plot.py scripts/paper/data/ --out curves.pdf

`data/<app>.json` holds each application's signature plus its raw fidelity- and
staleness-sweep curves, with a per-point standard deviation across the 32 seeds.
The run also writes three files of its own, so nothing downstream is hand-copied:

- `data/table.txt` — the rendered signature table;
- `data/table.tex` — the same table as a booktabs `tabular`, which the manuscript
  `\input{}`s, so Table 2 cannot drift from the data;
- `data/manifest.json` — which run produced this directory (id, git commit, dirty
  flag, seed count, app list, and whether it finished).

Do **not** redirect the table with `>`: the command writes it itself, atomically.
A `>` redirect truncates its target the moment the shell opens it, so an
interrupted run leaves an empty file where a reader expects a table.

Every per-app file is stamped with its run id, and `plot.py` refuses to draw from
a directory holding more than one run or an unfinished one. This is not
hypothetical — an earlier version of Table 2 and Figure 2 was built from a
directory holding two runs at once, because a second run was interrupted part way
through and silently overwrote only the first half of the files.

## Ranking-inversion sensitivity sweeps (Tables 4 and 5, Section VIII-C)

    python scripts/paper/capacity_sweep.py       > scripts/paper/data/capacity_sweep.txt
    python scripts/paper/coherence_sweep.py      > scripts/paper/data/coherence_sweep.txt
    python scripts/paper/mix_variants.py         > scripts/paper/data/mix_variants.txt
    python scripts/paper/burstiness_sweep.py     > scripts/paper/data/burstiness_sweep.txt
    python scripts/paper/tenant_independence.py  > scripts/paper/data/tenant_independence.txt

Each sweeps one axis around the paper's operating point (capacity 160 pairs/s
against 167 req/s of aggregate demand, link fidelity 0.99, coherence time
0.25 s) and reports the winning policy per workload mix at every point.

Two conventions matter for reading the output. A *winner* is the set of policies
tied for the top score, not an argmax: at several operating points two or three
policies score identically, and resolving that arbitrarily invents a
disagreement. And every point is replicated over 32 repeats, each giving every
tenant its own arrival pattern, because that pattern is read from a run of the
tenant's application and is the only stochastic ingredient in an otherwise
deterministic queueing model.
`tenant_independence.py` shows what the earlier, un-replicated model cost.

## The ranking-inversion figure (Figure 3)

    python scripts/paper/plot_inversion.py --out paper/figures/inversion.pdf

Contract satisfaction against capacity for all three policies on both mixes,
averaged over the same 32 repeats the sweeps use. Each policy keeps its colour,
dash pattern and marker in both panels, so the figure survives greyscale
printing and colour-vision deficiency; the palette is checked against the
adjacent-pair and normal-vision separation floors.

## Is a signature a property of the application? (Section VI-B)

    make -C paper invariance

Recomputes the single-trace signature axes on every backend and reports how far
apart they land. The answer is that classical coupling and multipartiteness are
invariant while burstiness is not, which is why the paper scopes the cv and Fano
columns to the reference backend. Needs both environments.

## Pairs per outcome vs fidelity threshold (Section VI)

    python scripts/paper/pairs_per_outcome.py > scripts/paper/data/pairs_per_outcome.txt

Sweeps the mirror-circuit families to vary how many pairs a single outcome
depends on, holding party count at two, and regresses the measured threshold
against that count.

## Reproducibility across environments (Section IV)

    # in each environment, against the same code:
    python scripts/paper/reproducibility.py generate OUT_DIR
    # then, anywhere:
    python scripts/paper/reproducibility.py compare BASELINE_DIR OTHER_DIR ... \
        > scripts/paper/data/reproducibility/summary.txt

Runs every core application over 16 seeds and compares the traces across environments,
separating identical files from the same events with rounding-level float differences.
The committed summary compares macOS against Linux, ARM against x86, Python 3.10 against
3.12, and numpy 1.26, 2.2 and 2.5. `qnetbench corpus --check` is the quick version, which
CI runs on Linux, macOS and Windows.

## The headline contention table (Table 4)

    qnetbench contention

Reproduces the table, including the separation and the count of disagreeing draws, and
reports the worst-served application beside it. A test pins these numbers.

## Replay outcome-preservation (Section VII)

    python scripts/paper/replay_equivalence.py > scripts/paper/data/replay_equivalence.txt

Runs each core application natively on the reference backend, records the
entanglement supply that run produced, and replays exactly that supply back
through the same engine. Isolates whether replay distorts the computation from
whether two backends supply different entanglement.

## The distillation-heavy mix (Section VIII-D)

    python scripts/paper/distillation_mix.py > scripts/paper/data/distillation_mix.txt

The negative result: the one mix whose tenants are rate-hungry rather than
fidelity- or deadline-bound, which a pass/fail contract model cannot express.
Replicated over the same 32 repeats as the other sweeps, so run rules R3 and R7
hold for it as they do for the rest of Section VIII.

## Concurrent execution, supplies and validation

These run applications concurrently on one shared link (`qnetbench.tenancy`), compare the
supplies at one link description, and check the engine against closed forms and against
protocols written directly on NetSquid and SeQUeNCe. Each writes its output into `data/`
under its own name. `.venv` is an environment with SeQUeNCe, `.venv-ns` one with NetSquid;
they need different numpy versions. Scripts that take a supply name write a partial result
per environment and are combined with `--merge`.

| Script | What it measures | Environment |
|---|---|---|
| `executed_contention.py` | The default mixes as real applications, from the queue model's assumptions to the execution model one assumption at a time; `--sweep` over capacity | `.venv` |
| `sensitivity_map.py` | Contract margin, deadline budget, capacity and link fidelity, on three metrics | `.venv` |
| `executed_memory.py` | Which applications lose utility while waiting, and whether the policy changes it | `.venv` |
| `coherence_sensitivity.py` | How those results move with the coherence time | `.venv` |
| `position_mix.py` | Position verification beside other tenants, by policy, contract, capacity and coherence time | `.venv` |
| `verifier_rounds.py` | The same, round by round, with one seed's full trace as CSV | `.venv` |
| `distillation_and_burstiness.py` | Distillation and burstiness with applications that block | `.venv` |
| `one_link_description.py` | Entanglement-based QKD on every supply at one link description | both, then `--merge` |
| `three_supplies.py` | The default mixes on every supply; `--sweep` for stored pairs on a free-running link | both |
| `position_supplies.py` | Position verification on every supply | both, then `--merge` |
| `timing_reaches_physics.py` | Which single applications respond to the timing of a supply | both, then `--merge` |
| `sequence_rate.py` | What sets SeQUeNCe's rate and burstiness | `.venv` |
| `cross_backend_seeds.py` | `cross_backend.py` over 32 seeds with no fidelity spread; its docstring has the per-seed commands | both |
| `analytic_validation.py` | Measured QBER, CHSH, teleportation, gates, swapping and distillation against closed forms | `.venv` |
| `analytic_outliers.py`, `swap_recheck.py` | The largest deviations again, on fresh seeds | `.venv` |
| `native_netsquid.py` | Teleportation, BBM92 and swapping written directly on NetSquid, against the engine | `.venv-ns` |
| `native_timing_ablation.py` | The same, with two protocol-timing details switched off | `.venv-ns` |
| `native_sequence.py` | The state SeQUeNCe stores for each delivered pair, against its fidelity label | `.venv` |
| `native_sequence_bbm92.py` | BBM92 written directly on SeQUeNCe, against the engine | `.venv` |
| `fidelity_age_policies.py`, `scheduler_comparison.py` | Ercetin and Gedik's schedulers, written outside the package, and run on the suite's workloads | `.venv` |
| `staleness_spread.py` | Spread of staleness half-lives, absolute and from each curve's floor | any |
| `contract_provenance.py` | Where each declared contract comes from, against the measured threshold | `.venv` |
| `worked_example.py` | One small application, evaluated alone and under three schedulers | `.venv` |
| `plot_grouped.py --out DIR` | The curves grouped by demand class, and `data/table-grouped.tex` in the same grouping | `.venv` |
| `plot_walkthrough.py --out DIR` | The diagram of one entanglement request | `.venv` |

`analytic_outliers.py`, `swap_recheck.py`, `staleness_spread.py` and `sequence_rate.py` print
their result; the committed copies in `data/` were saved from that output.

The checked-in `data/` outputs are the exact ones the paper's tables and figures
were built from.
