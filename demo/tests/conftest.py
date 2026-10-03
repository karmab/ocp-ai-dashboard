import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SEED_DIR = Path(__file__).parent.parent / "seed"


@pytest.fixture()
def demo_data_dir(tmp_path):
    """Copy seed data into a temp directory so tests don't mutate originals."""
    for f in SEED_DIR.glob("*.json"):
        shutil.copy(f, tmp_path / f.name)
    return tmp_path


@pytest.fixture()
def demo_client(demo_data_dir, monkeypatch):
    """FastAPI TestClient with GRID_DEMO_MODE enabled and isolated data."""
    monkeypatch.setenv("GRID_DEMO_MODE", "true")
    monkeypatch.setenv("GRID_DATA_DIR", str(demo_data_dir))
    monkeypatch.setenv("GRID_KEYS_DIR", str(demo_data_dir))

    import importlib
    import app as app_module
    importlib.reload(app_module)

    from demo import generators
    generators.clear_scenario()

    yield TestClient(app_module.app)

    generators.clear_scenario()


@pytest.fixture()
def seed_clusters():
    """Return the raw seed clusters data for assertions."""
    with open(SEED_DIR / "clusters.json") as f:
        return json.load(f)


@pytest.fixture()
def seed_spreads():
    """Return the raw seed spreads data for assertions."""
    with open(SEED_DIR / "spreads.json") as f:
        return json.load(f)


@pytest.fixture()
def seed_models():
    """Return the raw seed models data for assertions."""
    with open(SEED_DIR / "models.json") as f:
        return json.load(f)


@pytest.fixture()
def seed_apps():
    """Return the raw seed apps data for assertions."""
    with open(SEED_DIR / "apps.json") as f:
        return json.load(f)
