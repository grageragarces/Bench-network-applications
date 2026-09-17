# `qnetbench.backends`

The reference execution engine, and the replay seam every simulator backend fills.

Narrative guide: [Backends](../guide/backends.md) and
[Extending the suite](../adopting.md#add-a-backend).

## The replay seam

A supply backend implements exactly one method, `_make_supply(node, peer)`,
returning the delivered-pair stream for an edge.

::: qnetbench.backends.replay

## The reference backend

::: qnetbench.backends.reference.backend
    options:
      heading_level: 3
      members: [ReferenceBackend]

## SeQUeNCe

::: qnetbench.backends.sequence.backend
    options:
      heading_level: 3
      members: [SequenceBackend]

## NetSquid

::: qnetbench.backends.netsquid.backend
    options:
      heading_level: 3
      members: [NetSquidBackend]
