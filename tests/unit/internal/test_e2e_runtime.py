from types import SimpleNamespace

import pytest

from tests.e2e import runtime


@pytest.mark.parametrize(
    ("free_threaded_build", "gil_environment", "gil_enabled", "message"),
    [
        (False, "0", False, "free-threaded build"),
        (True, "1", False, "PYTHON_GIL=0"),
        (True, "0", True, "imports enabled the GIL"),
    ],
)
def test_free_threaded_e2e_rejects_invalid_runtime(
    monkeypatch: pytest.MonkeyPatch,
    *,
    free_threaded_build: bool,
    gil_environment: str,
    gil_enabled: bool,
    message: str,
) -> None:
    monkeypatch.setenv("UV_PYTHON", "3.15t")
    monkeypatch.setenv("PYTHON_GIL", gil_environment)
    monkeypatch.setattr(
        runtime,
        "sysconfig",
        SimpleNamespace(get_config_var=lambda _name: free_threaded_build),
    )
    monkeypatch.setattr(
        runtime,
        "sys",
        SimpleNamespace(_is_gil_enabled=lambda: gil_enabled),
    )

    with pytest.raises(AssertionError, match=message):
        runtime.assert_free_threaded_runtime()


def test_free_threaded_e2e_accepts_disabled_gil(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UV_PYTHON", "3.15t")
    monkeypatch.setenv("PYTHON_GIL", "0")
    monkeypatch.setattr(runtime, "sysconfig", SimpleNamespace(get_config_var=lambda _name: True))
    monkeypatch.setattr(
        runtime,
        "sys",
        SimpleNamespace(_is_gil_enabled=lambda: False),
    )

    runtime.assert_free_threaded_runtime()


def test_standard_e2e_does_not_require_disabled_gil(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UV_PYTHON", "3.15")
    monkeypatch.delenv("PYTHON_GIL", raising=False)

    runtime.assert_free_threaded_runtime()
