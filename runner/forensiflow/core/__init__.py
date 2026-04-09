"""
ForensiFlow Core Module

Contains modular components for task execution:
- modules: Individual execution modules (screenshot, decider, grounder, executor, etc.)
- scheduler: Orchestrates the execution flow
- scheduler_vt: Task scheduler with ForensiVision API integration
- scheduler_llm: LLM-based task scheduler
- forensic_planner: Forensic task planning module
"""

# Lazy imports to avoid dependency issues
def __getattr__(name):
    if name == 'TaskScheduler':
        from .scheduler import TaskScheduler as _TS
        return _TS
    elif name == 'StepConfig':
        from .scheduler import StepConfig as _SC
        return _SC
    elif name == 'TaskSchedulerVT':
        from .scheduler_vt import TaskSchedulerVT as _TSVT
        return _TSVT
    elif name == 'LLMTaskScheduler':
        from .scheduler_llm import LLMTaskScheduler as _LLM
        return _LLM
    elif name == 'ForensicPlanner':
        from .forensic_planner import ForensicPlanner as _FP
        return _FP
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    'TaskScheduler',
    'TaskSchedulerVT',
    'LLMTaskScheduler',
    'ForensicPlanner',
    'StepConfig'
]
