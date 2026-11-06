# Paper reproduction code

Everything that produces a table or a figure in the qnetbench TQE paper, plus the
generated data those tables and figures are drawn from. The LaTeX source for the
manuscript itself is not part of this repository; this directory is.

Run everything from the repository root, in an environment with the package
installed (`pip install -e ".[viz]"`). No simulator is required — all of it runs
on the reference backend.

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

The checked-in `data/` outputs are the exact ones the paper's tables and figures
were built from.
