import os
import sys
import sysconfig
from collections.abc import Callable


def assert_free_threaded_runtime() -> None:
    """Check free-threaded E2E processes after framework imports."""
    if not os.environ.get("UV_PYTHON", "").endswith("t"):
        return

    assert sysconfig.get_config_var("Py_GIL_DISABLED"), "E2E requires a free-threaded build"
    assert os.environ.get("PYTHON_GIL") == "0", "E2E requires PYTHON_GIL=0"
    # Older Python versions do not expose this private runtime check.
    is_gil_enabled: Callable[[], bool] = getattr(sys, "_is_gil_enabled", lambda: True)
    assert not is_gil_enabled(), "E2E imports enabled the GIL"
