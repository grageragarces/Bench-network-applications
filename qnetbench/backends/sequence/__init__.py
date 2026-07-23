"""The SeQUeNCe backend (hybrid entanglement-supply model).

Importing this package requires the optional ``sequence`` dependency.
"""

from qnetbench.backends.replay import Supply
from qnetbench.backends.sequence.backend import BACKEND_NAME, SequenceBackend
from qnetbench.backends.sequence.supply import generate_supply

__all__ = ["BACKEND_NAME", "SequenceBackend", "Supply", "generate_supply"]
