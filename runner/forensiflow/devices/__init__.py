"""
Device Modules

Device abstraction layer for Android and Harmony OS.
"""

from .android import AndroidDevice

# HarmonyDevice 是可选的，需要 hmdriver2
try:
    from .harmony import HarmonyDevice
    _harmony_available = True
except ImportError:
    HarmonyDevice = None
    _harmony_available = False

__all__ = ['AndroidDevice', 'HarmonyDevice']
