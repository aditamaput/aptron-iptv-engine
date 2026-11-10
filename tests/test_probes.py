import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from aptron.probes import _classify_http, _network_error, _parse_hls_attributes, _retry_delay, validate_hls


class ProbeHelpersTests(unittest.TestCase):
    def test_http_classification_is_explicit(self):
        self.assertEqual(_classify_http(206), "online")
        self.assertEqual(_classify_http(403), "restricted")
        self.assertEqual(_classify_http(404), "offline")
        self.assertEqual(_classify_http(429), "rate_limited")
        self.assertEqual(_classify_http(503), "server_error")

    def test_retry_after_is_respected_and_bounded(self):\n        exc = HTTPError("https://example.test", 429, "rate limited", {"Retry-After": "45"}, None)\n        self.assertEqual(_retry_delay(exc, 1), 30.0)\n        exc = HTTPError("https://example.test", 429, "rate limited", {"Retry-After": "3"}, None)\n        self.assertEqual(_retry_delay(exc, 1), 3.0)\n\n    def test_network_error_classification(self):
        self.assertEqual(_network_error(OSError("Name or service not known"))[0], "dns_error")
        self.assertEqual(_network_error(TimeoutError("timed out"))[0], "timeout")
        self.assertEqual(_network_error(ConnectionRefusedError("connection refused"))[0], "connection_refused")

    def test_hls_attribute_parser(self):
        attrs = _parse_hls_attributes('BANDWIDTH=2500000,RESOLUTION=1920x1080,CODECS="avc1.4d401f,mp4a.40.2"')
        self.assertEqual(attrs["BANDWIDTH"], "2500000")
        self.assertEqual(attrs["RESOLUTION"], "1920x1080")
        self.assertEqual(attrs["CODECS"], "avc1.4d401f,mp4a.40.2")

    @patch("aptron.probes._request_sample")
    def test_master_playlist_selects_highest_bandwidth_and_checks_segment(self, request):
        request.side_effect = [
            (200, "application/vnd.apple.mpegurl",
             b"#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1000000,RESOLUTION=640x360\nlow/index.m3u8\n#EXT-X-STREAM-INF:BANDWIDTH=3000000,RESOLUTION=1920x1080\nhigh/index.m3u8\n",
             "https://example.test/master.m3u8"),
            (200, "application/vnd.apple.mpegurl",
             b"#EXTM3U\n#EXTINF:6,\nseg-001.ts\n#EXT-X-ENDLIST\n",
             "https://example.test/high/index.m3u8"),
            (206, "video/mp2t", b"\x47" * 188, "https://example.test/high/seg-001.ts"),
        ]
        result = validate_hls("https://example.test/master.m3u8", {"User-Agent": "test"})
        self.assertEqual(result["status"], "segment_ok")
        self.assertEqual(result["variant_count"], 2)
        self.assertEqual(result["selected_bandwidth"], 3000000)
        self.assertEqual(result["declared_resolution"], "1920x1080")
        self.assertTrue(result["segment_url"].endswith("seg-001.ts"))


if __name__ == "__main__":
    unittest.main()
