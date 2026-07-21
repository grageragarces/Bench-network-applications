"""Read and write traces as JSONL. One event per line."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import TextIO

from pydantic import TypeAdapter

from qnetbench.trace.events import Event

_ADAPTER: TypeAdapter[Event] = TypeAdapter(Event)


class TraceWriter:
    """Append events to a JSONL stream. Usable as a context manager."""

    def __init__(self, stream: TextIO) -> None:
        self._stream = stream

    def write(self, event: Event) -> None:
        self._stream.write(_ADAPTER.dump_json(event).decode("utf-8"))
        self._stream.write("\n")

    def __enter__(self) -> TraceWriter:
        return self

    def __exit__(self, *exc: object) -> None:
        self._stream.flush()


def write_trace(path: str | Path, events: Iterable[Event]) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        writer = TraceWriter(fh)
        for event in events:
            writer.write(event)


def read_trace(path: str | Path) -> Iterator[Event]:
    """Stream events back from a JSONL trace file."""
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield _ADAPTER.validate_json(line)


def parse_event(line: str) -> Event:
    return _ADAPTER.validate_json(line)
