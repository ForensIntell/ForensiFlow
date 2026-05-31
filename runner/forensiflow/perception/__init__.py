"""ForensiFlow visual perception package.

This package owns the visual UI perception backend used by the replay runner.
The backend is kept local so runtime behavior remains identical while the
public ForensiFlow code stops depending on an external visual backend path.
"""

from pathlib import Path


VISUAL_BACKEND_ROOT = Path(__file__).resolve().parent / "_visual_backend"

__all__ = ["VISUAL_BACKEND_ROOT"]
