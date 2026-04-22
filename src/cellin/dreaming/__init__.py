"""Dream scheduling and consolidation for Cellin."""

from cellin.dreaming.benchmarks import DreamBenchmarkCase, seeded_dream_benchmark_cases
from cellin.dreaming.models import (
    DreamDiff,
    DreamEdgeChange,
    DreamMemoryChange,
    DreamRunResult,
)
from cellin.dreaming.scheduler import DeterministicDreamScheduler
from cellin.dreaming.service import DreamRunner
from cellin.dreaming.strategies import (
    AbstractionDreamStrategy,
    ContradictionRepairDreamStrategy,
    DecayArchivalDreamStrategy,
    DeduplicationDreamStrategy,
)

__all__ = [
    "AbstractionDreamStrategy",
    "ContradictionRepairDreamStrategy",
    "DecayArchivalDreamStrategy",
    "DeduplicationDreamStrategy",
    "DeterministicDreamScheduler",
    "DreamBenchmarkCase",
    "DreamDiff",
    "DreamEdgeChange",
    "DreamMemoryChange",
    "DreamRunResult",
    "DreamRunner",
    "seeded_dream_benchmark_cases",
]
