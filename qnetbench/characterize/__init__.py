"""qnetbench.characterize — demand-signature extraction (Deliverable 2).

`characterize_trace` reads single-trace dimensions (burstiness, classical coupling,
deadline-criticality, staleness intolerance, multipartiteness); `characterize_curves`
sweeps fidelity and pair-age; `characterize_app` combines them into a per-app
signature and `render_table` prints the cross-application comparison.
"""

from qnetbench.characterize.curves import (
    CharacterizationCurves,
    Curve,
    characterize_curves,
    fidelity_curve,
    staleness_curve,
)
from qnetbench.characterize.report import (
    AppSignature,
    characterize_app,
    render_table,
)
from qnetbench.characterize.signature import TraceSignature, characterize_trace

__all__ = [
    "AppSignature",
    "CharacterizationCurves",
    "Curve",
    "TraceSignature",
    "characterize_app",
    "characterize_curves",
    "characterize_trace",
    "fidelity_curve",
    "render_table",
    "staleness_curve",
]
