import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pytest
from edgelab.registry import Registry


@pytest.fixture
def reg(tmp_path):
    return Registry(tmp_path / "reg.sqlite")
