# `qnetbench.apps`

The benchmark applications, the core/catalog split, and the registry that resolves
a benchmark by name.

Narrative guide: [Applications](../guide/applications.md).

::: qnetbench.apps

## Distributed quantum computing

The DQC application is the one that turns a circuit into demand; it is what the
generated catalog is built from.

::: qnetbench.apps.dqc
    options:
      heading_level: 3

## Contributed protocols

Catalog entries outside the core; see
[Applications](../guide/applications.md#contributed-protocols).

::: qnetbench.apps.tie_audit
    options:
      heading_level: 3
      members:
        - TieAudit
        - make_instance
        - draw_twirl
        - alice_phases
        - bob_basis_change
        - decode
        - confidence_interval

## Configuration helpers

::: qnetbench.apps.util
    options:
      heading_level: 3
