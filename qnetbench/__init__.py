"""qnetbench — a benchmark suite and workload-characterization framework for
quantum-network applications."""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _version

try:
    # Single-sourced from the installed distribution metadata, so it cannot drift
    # from pyproject.toml. The characterization run manifest records this value,
    # which makes a stale literal here a provenance defect rather than a cosmetic
    # one.
    __version__ = _version("qnetbench")
except PackageNotFoundError:  # running from a source tree without an install
    __version__ = "0.0.0+unknown"
