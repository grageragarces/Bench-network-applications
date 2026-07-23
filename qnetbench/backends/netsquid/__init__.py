"""The NetSquid backend (hybrid entanglement-supply model).

Importing this package requires the optional ``netsquid`` dependency.
"""

from qnetbench.backends.netsquid.backend import BACKEND_NAME, NetSquidBackend
from qnetbench.backends.netsquid.supply import generate_supply

__all__ = ["BACKEND_NAME", "NetSquidBackend", "generate_supply"]
