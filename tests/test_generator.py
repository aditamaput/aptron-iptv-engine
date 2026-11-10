import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import generator


class GeneratorIntegrationTests(unittest.TestCase):
    def test_report_and_hls_playlists_are_separate_from_http_reachability(self):
        channel = {"id": "Demo.id", "name": "Demo TV", "country": "ID", "categories": ["news"]}
        streams = [
            {"channel": "Demo.id", "url": "https://demo.example/live.m3u8",
             "title": "Demo 1080p", "quality": "1080p", "labels": []},
            {"channel": "Demo.id", "url": "https://demo.example/backup.m3u8",
             "title": "Demo backup", "quality": None, "labels": []},
        ]
        def fake_probe(stream, *args, **kwargs):
            if stream["url"].endswith("live.m3u8"):
                return {
                    "url": stream["url"], "status": "online", "http_reachable": True,
                    "http_status": 206, "detail": "HTTP 206", "attempts": 1,
                    "hls_status": "segment_ok", "hls_detail": "sample segment ok",
                    "video_probe": {"status": "verified", "width": 1920, "height": 1080},
                    "playback_probe": {"status": "verified"},
                }
            return {
                "url": stream["url"], "status": "online", "http_reachable": True,
                "http_status": 200, "detail": "HTTP 200", "attempts": 1,
                "hls_status": "failed", "hls_detail": "segment unavailable",
                "video_probe": {"status": "not_checked"},
                "playback_probe": {"status": "not_checked"},
            }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(generator, "ROOT", root), \
                 patch.object(generator, "PLAYLIST_DIR", root / "playlists"), \
                 patch.object(generator, "REPORT_DIR", root / "reports"), \
                 patch.object(generator, "HEALTH_PATH", root / "reports" / "health.json"), \
                 patch.object(generator, "HISTORY_PATH", root / "reports" / "history.json"), \
                 patch.object(generator, "get_json", side_effect=[
                     [channel], streams, [], []
                 ]), \
                 patch.object(generator, "check_stream", side_effect=fake_probe), \
                 patch.object(generator, "CHECK_STREAMS", True), \
                 patch.object(generator, "ENABLE_MEDIA_PROBE", False), \
                 patch.object(generator, "ENABLE_PLAYBACK_PROBE", False):
                generator.main()

            report = json.loads((root / "reports" / "health.json").read_text(encoding="utf-8"))
            self.assertEqual(report["candidate_streams"], 2)
            self.assertEqual(report["http_reachable_streams"], 2)
            self.assertEqual(report["hls_segment_verified_streams"], 1)
            self.assertEqual(report["resolution_verified_hd_streams"], 1)
            self.assertEqual(report["stable_hls_streams"], 0)
            records = {item["url"]: item for item in report["streams"]}
            self.assertEqual(records["https://demo.example/live.m3u8"]["stream_role"], "primary")
            self.assertEqual(records["https://demo.example/backup.m3u8"]["stream_role"], "backup_1")
            self.assertEqual(len(report["transitions"]["recovered_http"]), 0)
            hls_playlist = (root / "playlists" / "indonesia-hls-validated.m3u").read_text(encoding="utf-8")
            online_playlist = (root / "playlists" / "indonesia-online.m3u").read_text(encoding="utf-8")
            hd_playlist = (root / "playlists" / "indonesia-hd-verified.m3u").read_text(encoding="utf-8")
            self.assertIn("live.m3u8", hls_playlist)
            self.assertNotIn("backup.m3u8", hls_playlist)
            self.assertIn("backup.m3u8", online_playlist)
            self.assertIn("live.m3u8", hd_playlist)


if __name__ == "__main__":
    unittest.main()
