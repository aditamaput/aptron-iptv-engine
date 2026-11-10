import json
import tempfile
import unittest
from pathlib import Path

from aptron.history import analyze_history


class HistoryTests(unittest.TestCase):
    def test_records_recovery_failure_and_reliability(self):
        with tempfile.TemporaryDirectory() as tmp:
            history = Path(tmp) / "history.json"
            previous = {
                "generated_at": "2026-11-09T00:00:00+00:00",
                "streams": [
                    {"url": "https://a.test/live.m3u8", "channel": "A",
                     "status": "unreachable", "hls_status": "failed"},
                    {"url": "https://b.test/live.m3u8", "channel": "B",
                     "status": "online", "hls_status": "segment_ok"},
                ],
            }
            current = [
                {"url": "https://a.test/live.m3u8", "channel": "A",
                 "status": "online", "hls_status": "segment_ok"},
                {"url": "https://b.test/live.m3u8", "channel": "B",
                 "status": "offline", "hls_status": "not_checked"},
            ]
            transitions = analyze_history(
                current, previous, history, "2026-11-10T00:00:00+00:00"
            )
            self.assertEqual(len(transitions["recovered_http"]), 1)
            self.assertEqual(len(transitions["new_http_failures"]), 1)
            self.assertEqual(current[0]["reliability_score"], 50.0)
            saved = json.loads(history.read_text(encoding="utf-8"))
            self.assertEqual(len(saved["snapshots"]), 2)


if __name__ == "__main__":
    unittest.main()
