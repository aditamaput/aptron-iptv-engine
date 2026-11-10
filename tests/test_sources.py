import json
import tempfile
import unittest
from pathlib import Path

from aptron.sources import load_approved_sources


class SourceRegistryTests(unittest.TestCase):
    def test_only_reviewed_public_sources_are_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "registry.json"
            path.write_text(json.dumps({
                "schema_version": 1,
                "streams": [
                    {
                        "channel_id": "Example.id",
                        "channel_name": "Example",
                        "stream_url": "https://cdn.example.test/live.m3u8",
                        "source_name": "Official broadcaster",
                        "source_url": "https://example.test/watch",
                        "access": "public",
                        "authorization": "approved",
                        "reviewed_at": "2026-11-10",
                        "review_notes": "Official public live page",
                    },
                    {
                        "channel_id": "Bad.id",
                        "channel_name": "Bad",
                        "stream_url": "https://bad.example.test/live.m3u8",
                        "source_name": "Unknown",
                        "source_url": "https://bad.example.test",
                        "access": "public",
                        "authorization": "pending",
                        "reviewed_at": "2026-11-10",
                        "review_notes": "Not reviewed",
                    },
                ]
            }), encoding="utf-8")
            accepted, rejected = load_approved_sources(path)
            self.assertEqual(len(accepted), 1)
            self.assertEqual(accepted[0][1]["_source_name"], "Official broadcaster")
            self.assertEqual(rejected[0]["reason"], "not_owner_approved_public_source")


if __name__ == "__main__":
    unittest.main()
