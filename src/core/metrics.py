"""Lightweight in-process metrics for instrumentation.

The project does not depend on a metrics backend yet, so we keep simple
counters that can be scraped/logged by external processes. All operations are
thread-safe and support label dictionaries for basic cardinality control.
"""
from __future__ import annotations

from collections import Counter
from threading import Lock
from typing import Dict, Iterable, Mapping, Tuple


_metric_lock = Lock()
_metric_store: Counter[Tuple[str, Tuple[Tuple[str, str], ...]]] = Counter()


def _labels_to_key(labels: Mapping[str, str] | None) -> Tuple[Tuple[str, str], ...]:
    if not labels:
        return tuple()
    return tuple(sorted((str(k), str(v)) for k, v in labels.items()))


def increment_metric(name: str, *, labels: Mapping[str, str] | None = None, value: int = 1) -> None:
    """Increment a counter metric.

    Args:
        name: Metric name (snake_case is preferred).
        labels: Optional mapping to distinguish metric contexts.
        value: Value to increment by (defaults to 1).
    """
    key = (name, _labels_to_key(labels))
    with _metric_lock:
        _metric_store[key] += value


def get_metrics_snapshot() -> Dict[str, int]:
    """Return a flattened view of the metrics store for exporting/logging."""
    with _metric_lock:
        snapshot = dict(_metric_store)

    formatted = {}
    for (name, labels), value in snapshot.items():
        if labels:
            label_repr = ",".join(f"{k}={v}" for k, v in labels)
            formatted[f"{name}|{label_repr}"] = value
        else:
            formatted[name] = value
    return formatted
