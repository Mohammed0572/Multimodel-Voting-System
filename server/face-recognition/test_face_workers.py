"""Process failures must never become successful identity checks."""
import os
from concurrent.futures import TimeoutError
from concurrent.futures.process import BrokenProcessPool
from unittest.mock import MagicMock

import numpy as np
import pytest

from face_workers import FaceWorkers


def test_native_workers_start_and_recover_after_a_process_crash():
    workers = FaceWorkers(workers=2, timeout=20)
    image = np.zeros((240, 320, 3), dtype=np.uint8)
    try:
        workers.start()
        assert workers.analyze([image, image]) == [None, None]
        # Kill only a process owned by this isolated test pool.
        with pytest.raises(BrokenProcessPool):
            workers._pool.submit(os._exit, 1).result(timeout=10)
        with pytest.raises(RuntimeError, match="worker stopped"):
            workers.analyze([image])
        assert workers._pool is None
        workers.start()
        assert workers.analyze([image]) == [None]
    finally:
        workers.close()


def test_slow_batch_is_bounded_and_does_not_create_more_workers(monkeypatch):
    workers = FaceWorkers(workers=2, timeout=5)
    pool = MagicMock()
    pool.map.side_effect = TimeoutError()
    workers._pool = pool
    with pytest.raises(RuntimeError, match="time budget"):
        workers.analyze([np.zeros((240, 320, 3), dtype=np.uint8)])
    assert workers._pool is pool
    assert pool.map.call_args.kwargs["timeout"] == 5
    pool.shutdown.assert_not_called()


def test_api_lifespan_warms_and_releases_native_workers(monkeypatch, tmp_path):
    import main
    from fastapi.testclient import TestClient
    workers = FaceWorkers(workers=2, timeout=20)
    monkeypatch.setattr(main, "_face_workers", workers)
    monkeypatch.setattr(main, "DB_PATH", str(tmp_path / "face-smoke.sqlite"))
    with TestClient(main.app) as client:
        assert client.get("/health").status_code == 200
        assert workers._pool is not None
        assert workers.analyze([np.zeros((240, 320, 3), dtype=np.uint8)]) == [None]
    assert workers._pool is None

