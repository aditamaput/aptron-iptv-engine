"""Curated additional source registry.

Registry entries are opt-in and must be reviewed by the repository owner.
This module does not scrape sites or bypass access controls.
"""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse


def load_approved_sources(path: Path, country: str = "ID") -> tuple[list[tuple[dict, dict]], list[dict]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return [], []
    except (OSError, ValueError) as exc:
        return [], [{"reason": "registry_read_error", "detail": str(exc)[:200]}]

    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        return [], [{"reason": "unsupported_registry_schema"}]

    accepted, rejected = [], []
    seen = set()
    for index, item in enumerate(payload.get("streams", [])):
        if not isinstance(item, dict):
            rejected.append({"index": index, "reason": "entry_not_object"})
            continue
        url = str(item.get("stream_url") or "").strip()
        source_url = str(item.get("source_url") or "").strip()
        channel_name = str(item.get("channel_name") or "").strip()
        channel_id = str(item.get("channel_id") or "").strip()
        source_name = str(item.get("source_name") or "").strip()
        if item.get("authorization") != "approved" or item.get("access") != "public":
            rejected.append({"index": index, "reason": "not_owner_approved_public_source"})
            continue
        if not channel_name or not channel_id or not source_name:
            rejected.append({"index": index, "reason": "missing_channel_or_source_identity"})
            continue
        if url in seen or urlparse(url).scheme not in ("http", "https") or not urlparse(url).netloc:
            rejected.append({"index": index, "reason": "invalid_or_duplicate_stream_url"})
            continue
        if urlparse(source_url).scheme != "https" or not urlparse(source_url).netloc:
            rejected.append({"index": index, "reason": "source_provenance_must_be_https"})
            continue
        if not item.get("reviewed_at") or not item.get("review_notes"):
            rejected.append({"index": index, "reason": "missing_review_evidence"})
            continue
        seen.add(url)
        channel = {
            "id": channel_id, "name": channel_name, "country": country,
            "categories": item.get("categories") or [],
        }
        stream = {
            "channel": channel_id, "url": url,
            "title": item.get("title") or channel_name,
            "quality": item.get("quality"),
            "labels": item.get("labels") or [],
            "_source_name": source_name,
            "_source_url": source_url,
        }
        accepted.append((channel, stream))
    return accepted, rejected
