"""engine/scheduler.py — APEX 8.0 Engine Dependency Scheduler.

Replaces sequential engine execution with a dependency graph.
Independent engines run concurrently; dependent engines wait for
their inputs. Never duplicates calculations.

Dependency graph:
    LAYER 0 (parallel, no deps):
        market_state, gamma, flow_snapshot, vix

    LAYER 1 (parallel, depends on L0):
        dealer_positioning, options_chain, volatility,
        rotation, market_drivers, auction_intelligence

    LAYER 2 (parallel, depends on L1):
        flow_intelligence_2, strike_magnets, playbook

    LAYER 3 (depends on all):
        institutional_intelligence

    LAYER 4 (depends on L3):
        execution_intelligence, story, trade_coach

Total wall time ≈ max(L0) + max(L1) + max(L2) + L3 + max(L4)
vs. previous sequential = sum(all engines)
"""
from __future__ import annotations

import time
import threading
from concurrent.futures import Future, ThreadPoolExecutor, as_completed, wait, FIRST_EXCEPTION
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from .logging import apex_logger, engine_timer


class EngineNode:
    """A single engine in the dependency graph."""

    def __init__(
        self,
        name:   str,
        fn:     Callable[..., Any],
        deps:   Optional[List[str]] = None,
        timeout: float = 3.0,
    ):
        self.name    = name
        self.fn      = fn
        self.deps    = deps or []
        self.timeout = timeout
        self.future: Optional[Future] = None
        self.result: Any = None
        self.error:  Optional[str] = None
        self.elapsed_ms: float = 0.0

    def is_ready(self, completed: Set[str]) -> bool:
        return all(d in completed for d in self.deps)


class EngineScheduler:
    """Topological dependency scheduler for APEX engines.

    Usage:
        sched = EngineScheduler(max_workers=12)
        sched.register("market_state",  build_market_state,  deps=[])
        sched.register("dealer",        build_dealer,         deps=["market_state", "gamma"])
        sched.register("institutional", build_institutional,  deps=["dealer", "flow", "auction"])
        results = sched.run(timeout=8.0)
    """

    def __init__(self, max_workers: int = 12):
        self._nodes: Dict[str, EngineNode] = {}
        self._max_workers = max_workers

    def register(
        self,
        name:    str,
        fn:      Callable[..., Any],
        deps:    Optional[List[str]] = None,
        timeout: float = 3.0,
    ) -> "EngineScheduler":
        self._nodes[name] = EngineNode(name, fn, deps, timeout)
        return self

    def run(self, timeout: float = 8.0) -> Dict[str, Any]:
        """Execute all engines respecting dependency order.

        Returns dict {engine_name: result_or_None}.
        Engines that fail or time out return None — the scheduler
        never lets one failure cascade to dependents; they receive
        whatever is available.
        """
        results: Dict[str, Any]   = {}
        errors:  Dict[str, str]   = {}
        completed: Set[str]       = set()
        pending:   Set[str]       = set(self._nodes)
        wall_start = time.monotonic()

        with ThreadPoolExecutor(max_workers=self._max_workers, thread_name_prefix="apex-sched") as pool:
            futures: Dict[Future, str] = {}

            def submit_ready() -> None:
                for name in list(pending):
                    node = self._nodes[name]
                    if node.is_ready(completed) and node.future is None:
                        node.future = pool.submit(self._run_node, node, results)
                        futures[node.future] = name

            submit_ready()

            deadline = wall_start + timeout
            while pending:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    # Time's up — cancel what's still pending, collect what's done
                    for name in pending:
                        errors[name] = "SCHEDULER_TIMEOUT"
                    break

                done, _ = wait(futures.keys(), timeout=min(remaining, 0.1), return_when=FIRST_EXCEPTION)
                for fut in done:
                    name = futures.pop(fut)
                    node = self._nodes[name]
                    pending.discard(name)
                    completed.add(name)
                    if fut.exception():
                        errors[name]   = str(fut.exception())
                        results[name]  = None
                    else:
                        results[name]  = node.result
                    submit_ready()

        # Fill in any engines that never ran (unresolvable deps)
        for name in pending:
            if name not in results:
                results[name] = None
                errors[name]  = errors.get(name, "NOT_RUN")

        wall_ms = round((time.monotonic() - wall_start) * 1000, 1)
        results["__meta__"] = {
            "wall_ms":  wall_ms,
            "errors":   errors,
            "completed": list(completed),
            "engines":  len(self._nodes),
        }
        return results

    def _run_node(self, node: EngineNode, upstream: Dict[str, Any]) -> Any:
        t0 = time.monotonic()
        try:
            # Call the engine function; pass upstream results as kwargs if accepted
            result = node.fn(upstream)
            node.result     = result
            node.elapsed_ms = round((time.monotonic() - t0) * 1000, 1)
            apex_logger.debug(f"[SCHED] {node.name} OK {node.elapsed_ms}ms")
            return result
        except Exception as exc:
            node.error      = str(exc)
            node.elapsed_ms = round((time.monotonic() - t0) * 1000, 1)
            apex_logger.warning(f"[SCHED] {node.name} FAILED {node.elapsed_ms}ms: {exc}")
            node.result = None
            raise
