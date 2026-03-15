"""
Execution Modules

Each module is responsible for a specific step in the task execution pipeline.
"""

# Lazy imports to avoid dependency issues
def __getattr__(name):
    if name == 'ScreenshotModule':
        from .screenshot import ScreenshotModule as _SM
        return _SM
    elif name == 'DeciderModule':
        from .decider import DeciderModule as _DM
        return _DM
    elif name == 'GrounderModule':
        from .grounder import GrounderModule as _GM
        return _GM
    elif name == 'ExecutorModule':
        from .executor import ExecutorModule as _EM
        return _EM
    elif name == 'VisualizerModule':
        from .visualizer import VisualizerModule as _VM
        return _VM
    elif name == 'StorageModule':
        from .storage import StorageModule as _STM
        return _STM
    elif name == 'PlannerModule':
        from .planner import PlannerModule as _PM
        return _PM
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    'ScreenshotModule',
    'DeciderModule',
    'GrounderModule',
    'ExecutorModule',
    'VisualizerModule',
    'StorageModule',
    'PlannerModule',
]
