from pathlib import Path

import pytest

from tests_support import REPO_ROOT, SCRIPT_DIR


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def script_dir() -> Path:
    return SCRIPT_DIR
