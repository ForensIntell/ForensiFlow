"""
ForensiFlow Core Module

Contains modular components for task execution:
- modules: Individual execution modules (screenshot, decider, grounder, executor, etc.)
- scheduler_vt: Legacy-compatible visual scheduler entry point
- scheduler_visual: Preferred visual scheduler alias for the migrated perception stack
- codex_agent_scheduler: Codex-backed mobile agent used by the current new-scheduler path
- forensic_planner: Forensic task planning module
"""

# Lazy imports to avoid dependency issues
def __getattr__(name):
    if name == 'TaskSchedulerVT':
        from .scheduler_vt import TaskSchedulerVT as _TSVT
        return _TSVT
    elif name == 'TaskSchedulerVisual':
        from .scheduler_visual import TaskSchedulerVisual as _TSV
        return _TSV
    elif name == 'CodexAgentScheduler':
        from .codex_agent_scheduler import CodexAgentScheduler as _CAS
        return _CAS
    elif name == 'PageAgentMobileScheduler':
        from .codex_agent_scheduler import PageAgentMobileScheduler as _PAMS
        return _PAMS
    elif name == 'ForensicPlanner':
        from .forensic_planner import ForensicPlanner as _FP
        return _FP
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    'TaskSchedulerVT',
    'TaskSchedulerVisual',
    'CodexAgentScheduler',
    'PageAgentMobileScheduler',
    'ForensicPlanner',
]
