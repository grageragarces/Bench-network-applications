# Install

## The core

The core suite needs only `pydantic` and `numpy`, and the `reference` backend is
pure Python, so the whole benchmark suite runs — and tests in CI — with no
simulator installed at all.

```bash
pip install qnetbench
```

From a clone, for development:

```bash
git clone https://github.com/grageragarces/Bench-network-applications
cd Bench-network-applications
pip install -e ".[dev]"     # core + pytest, mypy, ruff
```

Python 3.10 or newer.

## Optional extras

| Extra | Install | Gives you |
|---|---|---|
| `sequence` | `pip install "qnetbench[sequence]"` | the SeQUeNCe backend |
| `netsquid` | see below | the NetSquid backend |
| `mqt` | `pip install "qnetbench[mqt]"` | loading Qiskit / MQT Bench circuits as DQC demand |
| `viz` | `pip install "qnetbench[viz]"` | `scripts/plot_curves.py`, the characterization figures |
| `docs` | `pip install "qnetbench[docs]"` | building this documentation site |
| `dev` | `pip install "qnetbench[dev]"` | pytest, mypy, ruff |

NetSquid ships from its own package index and requires a free registration at
[netsquid.org](https://netsquid.org):

```bash
pip install --extra-index-url https://pypi.netsquid.org "qnetbench[netsquid]"
```

## One virtualenv per simulator

!!! warning "SeQUeNCe and NetSquid cannot coexist"

    SeQUeNCe pins `numpy >= 2.3.5` and NetSquid pins `numpy < 2`. The two extras
    are mutually unsatisfiable in a single environment. This is inherent to the
    simulators, and it is precisely the fragmentation this suite exists to paper
    over.

Use a separate virtualenv per simulator:

```bash
python -m venv .venv      && .venv/bin/pip install -e ".[dev,sequence]"
python -m venv .venv-ns   && .venv-ns/bin/pip install --extra-index-url https://pypi.netsquid.org -e ".[dev,netsquid]"
```

Each environment runs the full reference test suite plus its own simulator's
tests, skipping the other's. Applications are unchanged across both — that is the
point of the [portable API](reference/api.md).

## Verify the install

```bash
qnetbench list          # 27 core protocols + 3 policies
qnetbench run qkd       # a full run and report on the reference backend
pytest                  # physics, app invariants, trace round-trip, policies, metrics
```

## Building these docs

```bash
pip install -e ".[docs]"
mkdocs serve            # live-reloading preview; open the URL it prints
mkdocs serve -o         # ... or have it open a browser for you
mkdocs build            # static site into site/
mkdocs gh-deploy        # publish to GitHub Pages (the gh-pages branch)
```

!!! note "The local URL is not `/`"

    `site_url` points at a GitHub Pages *project* site, so the dev server mounts
    under that same path: <http://127.0.0.1:8000/Bench-network-applications/>.
    `mkdocs serve` prints the full address on startup — follow that.

The build runs in strict mode, so a broken cross-reference or an unresolvable
docstring reference fails the build instead of shipping a dead link. The API
reference itself is generated from the package's own docstrings by
[mkdocstrings](https://mkdocstrings.github.io/), so it cannot drift from the code.
