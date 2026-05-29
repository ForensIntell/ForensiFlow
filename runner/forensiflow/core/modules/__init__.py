"""
Execution Modules

Small helpers used by the legacy VisionTasker scheduler.
"""

# Lazy imports to avoid dependency issues
def __getattr__(name):
    if name == 'ScreenshotModule':
        from .screenshot import ScreenshotModule as _SM
        return _SM
    elif name == 'ExecutorModule':
        from .executor import ExecutorModule as _EM
        return _EM
    elif name == 'VisualizerModule':
        from .visualizer import VisualizerModule as _VM
        return _VM
    elif name == 'StorageModule':
        from .storage import StorageModule as _STM
        return _STM
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    'ScreenshotModule',
    'ExecutorModule',
    'VisualizerModule',
    'StorageModule',
]
