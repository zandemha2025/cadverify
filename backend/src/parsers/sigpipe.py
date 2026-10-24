"""Keep SIGPIPE ignored after gmsh starts.

gmsh's first ``initialize()`` in a process sets SIGPIPE back to its default
action, which terminates the process, whatever ``interruptible`` says. Python
ignores SIGPIPE so that a write to a closed socket or pipe raises
BrokenPipeError. Once gmsh has run, the same write kills the whole process with
no traceback (exit status 141): a browser that hangs up during a download, or a
Redis or Postgres connection the server closed. The backend suite on CI died
that way partway through.

Every ``gmsh.initialize`` in ``src`` calls :func:`ignore_sigpipe` right after it
(``tests/test_sigpipe_after_gmsh.py`` pins that). It goes through libc's
``signal()``, which changes the process-wide action from any thread; Python's
``signal.signal`` works only on the main thread, and meshing runs in worker
threads.
"""
from __future__ import annotations

import ctypes
import signal

_SIG_IGN = 1  # (sighandler_t) 1
_libc_signal = None


def ignore_sigpipe() -> None:
    """Set SIGPIPE's action back to ignore. A no-op where there is no SIGPIPE."""
    global _libc_signal
    sigpipe = getattr(signal, "SIGPIPE", None)
    if sigpipe is None:
        return
    try:
        if _libc_signal is None:
            fn = ctypes.CDLL(None, use_errno=True).signal
            fn.argtypes = [ctypes.c_int, ctypes.c_void_p]
            fn.restype = ctypes.c_void_p
            _libc_signal = fn
        _libc_signal(int(sigpipe), _SIG_IGN)
    except (OSError, AttributeError):
        # No C library signal() to call: nothing that gmsh could have changed here.
        pass
