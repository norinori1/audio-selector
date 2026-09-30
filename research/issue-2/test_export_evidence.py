"""Regression checks: failure evidence must not invent checkpoint diagnoses."""
import unittest

from export_evidence import export_failure


class FailureEvidenceTests(unittest.TestCase):
    def test_network_failure_is_not_reported_as_checkpoint_mismatch(self):
        record = export_failure(dict(type="ConnectionError", message="Model download timed out"))
        self.assertEqual(record, dict(type="ConnectionError", summary="Model download timed out"))

    def test_dependency_failure_preserves_observed_diagnostic(self):
        record = export_failure(dict(type="ImportError", message="Cannot import torch\nDLL load failed"))
        self.assertEqual(record, dict(type="ImportError", summary="Cannot import torch",
                                     detail="DLL load failed"))

    def test_checkpoint_failure_keeps_actual_size_mismatch(self):
        record = export_failure(dict(type="RuntimeError", message=(
            "Error(s) in loading state_dict for CLAP:\n"
            "size mismatch for audio_projection.0.weight: [512, 768] vs [512, 1024]")))
        self.assertIn("[512, 768] vs [512, 1024]", record["detail"])
        self.assertNotIn("HTSAT-base", record["detail"])

    def test_large_diagnostic_is_bounded_and_marked(self):
        record = export_failure(dict(type="RuntimeError", message="Load failed\n" + "x" * 2000))
        self.assertEqual(len(record["detail"]), 1000)
        self.assertTrue(record["detail_truncated"])

    def test_exception_without_message_does_not_invent_a_cause(self):
        record = export_failure(dict(type="TimeoutError", message=""))
        self.assertEqual(record, dict(type="TimeoutError", summary=""))


if __name__ == "__main__":
    unittest.main()
