import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pytest

from edgelab.registry import Registry

# test_selftest.py exercises the LEGACY evaluator + Linux process sandbox (needs the Unix-only `resource` module,
# `unshare` and uid switching). The new Edge Lab pipeline does not use it, so it is skipped on Windows.
collect_ignore = ["test_selftest.py"] if sys.platform == "win32" else []


@pytest.fixture
def reg(tmp_path):
    return Registry(tmp_path / "reg.sqlite")
