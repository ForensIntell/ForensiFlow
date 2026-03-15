"""
ForensiFlow Core Module

Contains modular components for task execution:
- modules: Individual execution modules (screenshot, decider, grounder, executor, etc.)
- scheduler: Orchestrates the execution flow
- scheduler_vt: Task scheduler with VisionTasker API integration
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
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    'TaskScheduler',
    'TaskSchedulerVT',
    'StepConfig'
]
