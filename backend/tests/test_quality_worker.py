from contextlib import redirect_stdout
from io import StringIO
import json
import logging
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import warnings

from workers import quality_worker


class QualityWorkerTests(unittest.TestCase):
    def run_worker(self, metric, api, *, runtime=True):
        request = {"metric": metric, "reference": "reference.wav", "degraded": "degraded.wav"}
        modules = {
            "numpy": Mock(),
            "visqol": SimpleNamespace(VisqolApi=Mock(return_value=api)),
            "ai_edge_litert.interpreter": SimpleNamespace(Interpreter=Mock()) if runtime else None,
        }
        signal = SimpleNamespace(size=16000, min=lambda: -1, max=lambda: 1)
        output = StringIO()
        with patch.dict(sys.modules, modules), patch("sys.stdin", StringIO(json.dumps(request))), \
                patch.object(quality_worker, "read_pcm", return_value=signal), redirect_stdout(output):
            code = quality_worker.main()
        return code, output.getvalue()

    def test_speech_modes_preserve_path_order_and_extract_moslqo(self):
        for metric, use_lattice in (("ViSQOL", False), ("ViSQOL_LATTICE", True)):
            with self.subTest(metric=metric):
                api = Mock()
                api.measure.return_value = SimpleNamespace(moslqo=3.5)
                code, output = self.run_worker(metric, api, runtime=use_lattice)
                self.assertEqual(code, 0)
                self.assertEqual(json.loads(output), {"value": 3.5})
                api.create.assert_called_once_with(mode="speech", use_lattice_model=use_lattice)
                api.measure.assert_called_once_with("reference.wav", "degraded.wav")

    def test_missing_lattice_runtime_returns_unavailable(self):
        api = Mock()
        self.assertEqual(self.run_worker("ViSQOL_LATTICE", api, runtime=False), (3, ""))
        api.create.assert_not_called()
        api.measure.assert_not_called()

    def test_reported_lattice_fallback_returns_unavailable(self):
        def warn_fallback(**kwargs):
            warnings.warn("Falling back to polynomial mapping", stacklevel=2)

        def log_fallback(**kwargs):
            logging.getLogger("visqol").warning("Lattice unavailable")

        for report_fallback in (warn_fallback, log_fallback):
            with self.subTest(report=report_fallback.__name__):
                api = Mock()
                api.create.side_effect = report_fallback
                self.assertEqual(self.run_worker("ViSQOL_LATTICE", api), (3, ""))
                api.measure.assert_not_called()
