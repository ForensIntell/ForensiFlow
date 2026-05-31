"""Preferred visual scheduler import path.

The implementation remains in ``scheduler_vt`` for backward compatibility with
existing scripts. New code should import ``TaskSchedulerVisual`` from this
module while the legacy ``TaskSchedulerVT`` name continues to work.
"""

from .scheduler_vt import StepConfig, TaskSchedulerVT


TaskSchedulerVisual = TaskSchedulerVT


__all__ = ["StepConfig", "TaskSchedulerVisual", "TaskSchedulerVT"]
