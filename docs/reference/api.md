# `qnetbench.api`

The portable API shim. This package and [`qnetbench.trace`](trace.md) are the two
frozen contracts of the suite — applications import from here and nowhere else, and
a backend is free to implement the surface however it likes.

Narrative guide: [Applications](../guide/applications.md) and
[Extending the suite](../adopting.md#add-an-application).

::: qnetbench.api

## Value types

::: qnetbench.api.types
    options:
      heading_level: 3

## The runtime surface

::: qnetbench.api.host
    options:
      heading_level: 3

## The application contract

::: qnetbench.api.application
    options:
      heading_level: 3
