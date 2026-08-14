import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from anywhere_claude_mem.worker import (
    WorkerClient,
    WorkerHTTPError,
    _port_from_worker_files,
    worker_port,
)


class WorkerPortTests(unittest.TestCase):
    def _dir_with_worker_pid(self, port: int) -> Path:
        directory = Path(tempfile.mkdtemp())
        (directory / "worker.pid").write_text(json.dumps({"pid": 123, "port": port}))
        return directory

    def test_port_from_worker_pid(self):
        directory = self._dir_with_worker_pid(37777)
        with patch("anywhere_claude_mem.worker.worker_data_dir", return_value=directory):
            self.assertEqual(_port_from_worker_files(), 37777)

    def test_port_from_supervisor_json(self):
        directory = Path(tempfile.mkdtemp())
        (directory / "supervisor.json").write_text(
            json.dumps({"status": "running", "port": 37781})
        )
        with patch("anywhere_claude_mem.worker.worker_data_dir", return_value=directory):
            self.assertEqual(_port_from_worker_files(), 37781)

    def test_worker_pid_takes_precedence(self):
        directory = Path(tempfile.mkdtemp())
        (directory / "worker.pid").write_text(json.dumps({"pid": 1, "port": 37710}))
        (directory / "supervisor.json").write_text(json.dumps({"port": 37799}))
        with patch("anywhere_claude_mem.worker.worker_data_dir", return_value=directory):
            self.assertEqual(_port_from_worker_files(), 37710)

    def test_missing_or_invalid_files_return_none(self):
        directory = Path(tempfile.mkdtemp())
        (directory / "worker.pid").write_text("not json")
        with patch("anywhere_claude_mem.worker.worker_data_dir", return_value=directory):
            self.assertIsNone(_port_from_worker_files())

    def test_empty_dir_returns_none(self):
        directory = Path(tempfile.mkdtemp())
        with patch("anywhere_claude_mem.worker.worker_data_dir", return_value=directory):
            self.assertIsNone(_port_from_worker_files())

    def test_worker_port_prefers_recorded_over_uid(self):
        # Windows lacks os.getuid, so stub the whole module attribute.
        fake_os = types.SimpleNamespace(environ={}, getuid=lambda: 5)
        with patch("anywhere_claude_mem.worker._port_from_worker_files", return_value=37777), patch(
            "anywhere_claude_mem.worker._probe_health_port", return_value=None
        ), patch("anywhere_claude_mem.worker.os", fake_os), patch(
            "anywhere_claude_mem.worker.settings", return_value={}
        ):
            self.assertEqual(worker_port(), 37777)


class WorkerDeleteTests(unittest.TestCase):
    def test_delete_returns_false_on_404(self):
        client = WorkerClient("http://127.0.0.1:1")
        with patch.object(
            client, "request", side_effect=WorkerHTTPError(404, "worker returned HTTP 404")
        ):
            self.assertFalse(client.delete("observations", 42))

    def test_delete_reraises_on_other_errors(self):
        client = WorkerClient("http://127.0.0.1:1")
        with patch.object(
            client, "request", side_effect=WorkerHTTPError(500, "worker returned HTTP 500")
        ):
            with self.assertRaises(WorkerHTTPError):
                client.delete("observations", 42)

    def test_delete_unknown_kind_raises_value_error(self):
        client = WorkerClient("http://127.0.0.1:1")
        with self.assertRaises(ValueError):
            client.delete("nope", 1)


if __name__ == "__main__":
    unittest.main()
