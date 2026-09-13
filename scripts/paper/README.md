# Paper reproduction code

Everything that produces a table or a figure in the qnetbench TQE paper, plus the
generated data those tables and figures are drawn from. The LaTeX source for the
manuscript itself is not part of this repository; this directory is.

Run everything from the repository root, in an environment with the package
installed (`pip install -e ".[viz]"`). No simulator is required — all of it runs
on the reference backend.

## Demand signatures (Table II, Figure 1)

    qnetbench characterize --out scripts/paper/data/ > scripts/paper/data/table.txt
    python scripts/paper/plot.py scripts/paper/data/ --out curves.pdf

`data/table.txt` is the rendered signature table; `data/<app>.json` holds each
application's signature plus its raw fidelity- and staleness-sweep curves, with a
per-point standard deviation across the eight seeds.

## Ranking-inversion sensitivity sweeps (Table V, Section VIII-C)

    python scripts/paper/capacity_sweep.py   > scripts/paper/data/capacity_sweep.txt
    python scripts/paper/coherence_sweep.py  > scripts/paper/data/coherence_sweep.txt
    python scripts/paper/mix_variants.py     > scripts/paper/data/mix_variants.txt

Each sweeps one axis around the paper's operating point (capacity 110 pairs/s,
link fidelity 0.99, coherence time 0.25 s) and reports the winning policy per
workload mix at every point. The contention model is fully deterministic, so
these reproduce exactly rather than up to a seed.

The checked-in `data/` outputs are the exact ones the paper's tables and figures
were built from.
