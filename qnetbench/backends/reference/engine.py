"""A tiny cooperative discrete-event engine.

Each application role runs in its own OS thread, but only one thread is ever
active at a time — a "baton" is handed between the scheduler and exactly one
process. Blocking API calls (wait, recv, entanglement rendezvous) park the
process and yield the baton back to the scheduler, which advances simulated time
and resumes the next process. This gives applications plain sequential code
(matching the resolved blocking/generator model) while staying deterministic:
execution order is fixed by (time, sequence) and all randomness is seeded.
"""

from __future__ import annotations

import heapq
import itertools
import threading
from collections.abc import Callable


class Process:
    """A cooperatively-scheduled thread. Created via `Engine.spawn`."""

    def __init__(self, engine: Engine, fn: Callable[[], None], name: str) -> None:
        self._engine = engine
        self._fn = fn
        self.name = name
        self.finished = False
        self._sem = threading.Semaphore(0)
        self._thread = threading.Thread(target=self._run, name=name, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def _run(self) -> None:
        self._sem.acquire()  # wait for the first hand-off from the scheduler
        try:
            self._fn()
        finally:
            self.finished = True
            self._engine._yield_to_scheduler()

    def _resume(self) -> None:
        self._sem.release()

    def join(self) -> None:
        self._thread.join()


class Engine:
    def __init__(self) -> None:
        self.now: float = 0.0
        self._heap: list[tuple[float, int, Process]] = []
        self._seq = itertools.count()
        self._sched_sem = threading.Semaphore(0)
        self._procs: list[Process] = []
        self._current: Process | None = None

    # --- process lifecycle ---------------------------------------------------

    def spawn(self, fn: Callable[[], None], name: str) -> Process:
        proc = Process(self, fn, name)
        self._procs.append(proc)
        proc.start()
        return proc

    def schedule(self, proc: Process, delay: float) -> None:
        """Wake `proc` after `delay` simulated seconds."""
        heapq.heappush(self._heap, (self.now + max(delay, 0.0), next(self._seq), proc))

    @property
    def current(self) -> Process:
        assert self._current is not None, "no process is running"
        return self._current

    # --- baton hand-off (scheduler side) -------------------------------------

    def _switch_to(self, proc: Process) -> None:
        self._current = proc
        proc._resume()
        self._sched_sem.acquire()  # block until the process yields the baton back
        self._current = None

    def run(self) -> None:
        """Run until no events remain. Must be called on the main thread."""
        while self._heap:
            when, _, proc = heapq.heappop(self._heap)
            if proc.finished:
                continue
            self.now = max(self.now, when)
            self._switch_to(proc)

    # --- baton hand-off (process side) ---------------------------------------

    def _yield_to_scheduler(self) -> None:
        self._sched_sem.release()

    def wait(self, delay: float) -> None:
        """Block the current process for `delay` simulated seconds."""
        proc = self.current
        self.schedule(proc, delay)
        self._park(proc)

    def park(self) -> None:
        """Block the current process indefinitely; someone else must reschedule it."""
        self._park(self.current)

    def _park(self, proc: Process) -> None:
        self._yield_to_scheduler()
        proc._sem.acquire()  # sleep until the scheduler resumes us
