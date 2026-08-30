import unittest
import asyncio
import threading
import time
from pathlib import Path
from unittest.mock import patch

from pawchive_downloader.webui import DashboardState, _download_worker


class DashboardStateTests(unittest.TestCase):
    def test_live_counters_and_queue(self):
        state = DashboardState(Path("downloads"))
        state.begin(Path("downloads"))
        state.progress("total", 5)
        state.progress("downloaded", object())
        state.progress("failed", object())
        state.progress("skipped", object())
        snapshot = state.snapshot()
        self.assertEqual(snapshot["done"], 1)
        self.assertEqual(snapshot["failed"], 1)
        self.assertEqual(snapshot["skipped"], 1)
        self.assertEqual(snapshot["queued"], 2)

    def test_stop_state(self):
        state = DashboardState(Path("downloads"))
        state.begin(Path("downloads"))
        self.assertTrue(state.request_stop())
        self.assertTrue(state.snapshot()["stopping"])
        state.finish(stopped=True)
        snapshot = state.snapshot()
        self.assertFalse(snapshot["running"])
        self.assertTrue(snapshot["stopped"])

    def test_worker_task_is_cancelled(self):
        state = DashboardState(Path("downloads"))
        state.begin(Path("downloads"))

        async def fake_run(*_args, **_kwargs):
            await asyncio.sleep(30)

        with patch("pawchive_downloader.webui.run", fake_run):
            worker = threading.Thread(target=_download_worker, args=([], None, state))  # type: ignore[arg-type]
            worker.start()
            deadline = time.monotonic() + 2
            while state.task is None and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(state.request_stop())
            worker.join(timeout=2)

        self.assertFalse(worker.is_alive())
        self.assertTrue(state.snapshot()["stopped"])
