#!/usr/bin/env python3
"""APTRON IPTV Engine 2.0: public-source discovery, validation and playlist generation."""
from __future__ import annotations

import concurrent.futures
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from aptron.history import analyze_history, read_json
from aptron.probes import check_stream

API = "https://iptv-org.github.io/api"
COUNTRY = os.getenv("COUNTRY_CODE", "ID").upper()
TIMEOUT = max(3, int(os.getenv("CHECK_TIMEOUT", "10")))
WORKERS = max(1, min(32, int(os.getenv("CHECK_WORKERS", "16"))))
CHECK_STREAMS = os.getenv("CHECK_STREAMS", "true").lower() == "true"
RETRIES = max(0, min(3, int(os.getenv("CHECK_RETRIES", "1"))))
RETRY_BACKOFF = max(0.0, float(os.getenv("RETRY_BACKOFF", "1")))
ENABLE_MEDIA_PROBE = os.getenv("ENABLE_MEDIA_PROBE", "true").lower() == "true"
MEDIA_PROBE_LIMIT = max(0, min(60, int(os.getenv("MEDIA_PROBE_LIMIT", "30"))))
ROOT = Path(__file__).resolve().parent
PLAYLIST_DIR = ROOT / "playlists"
REPORT_DIR = ROOT / "reports"
HEALTH_PATH = REPORT_DIR / "health.json"
HISTORY_PATH = REPORT_DIR / "history.json"
HEADERS = {"User-Agent": "APTRON-IPTV-Engine/2.0", "Accept": "*/*"}

CATEGORY_NAMES = {
    "animation": "Animasi", "auto": "Otomotif", "business": "Bisnis",
    "classic": "Klasik", "comedy": "Komedi", "cooking": "Memasak",
    "culture": "Budaya", "documentary": "Dokumenter", "education": "Edukasi",
    "entertainment": "Hiburan", "family": "Keluarga", "general": "Umum",
    "kids": "Anak", "legislative": "Pemerintahan", "lifestyle": "Gaya Hidup",
    "movies": "Film", "music": "Musik", "news": "Berita", "outdoor": "Outdoor",
    "religious": "Religi", "series": "Serial", "science": "Sains",
    "shop": "Belanja", "sports": "Olahraga", "travel": "Wisata", "weather": "Cuaca",
}


def get_json(name: str):
    from urllib.request import Request, urlopen
    req = Request(f"{API}/{name}.json", headers=HEADERS)
    with urlopen(req, timeout=45) as response:
        return json.loads(response.read().decode("utf-8"))


def clean(value) -> str:
    return re.sub(r'[\r\n,"]', " ", str(value or "")).strip()


def declared_quality(value: str) -> int:
    """Parse source metadata only; this is never treated as measured resolution."""
    text = str(value or "").lower()
    match = re.search(r"(\d{3,4})\s*[pi]?", text)
    if match:
        return int(match.group(1))
    if "uhd" in text or "4k" in text:
        return 2160
    if "fhd" in text or "full hd" in text:
        return 1080
    if "hd" in text:
        return 720
    return 0


def category_group(channel: dict) -> str:
    cats = channel.get("categories") or []
    if not cats:
        return "Indonesia | Umum"
    label = CATEGORY_NAMES.get(str(cats[0]).lower(), str(cats[0]).title())
    return f"Indonesia | {label}"


def extinf(channel: dict, stream: dict, logos: dict) -> str:
    channel_id = clean(channel.get("id"))
    name = clean(channel.get("name") or channel_id)
    logo = logos.get(channel_id, "")
    attrs = [f'tvg-id="{channel_id}"', f'tvg-name="{name}"',
             f'group-title="{category_group(channel)}"']
    if logo.startswith(("https://", "http://")):
        attrs.append(f'tvg-logo="{clean(logo)}"')
    title = clean(stream.get("title"))
    quality = clean(stream.get("quality") or title)
    display = f"{name} ({quality})" if quality else name
    return f"#EXTINF:-1 {' '.join(attrs)},{display}\n{stream['url']}"


def write_playlist(filename: str, selected: list) -> None:
    lines = ["#EXTM3U"]
    lines.extend(extinf(row["channel"], row["stream"], row.get("logos", {})) for row in selected)
    (PLAYLIST_DIR / filename).write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    PLAYLIST_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    previous_report = read_json(HEALTH_PATH, {})
    print("Downloading iptv-org public metadata...")
    channels_raw = get_json("channels")
    streams_raw = get_json("streams")
    logos_raw = get_json("logos")
    blocklist_raw = get_json("blocklist")

    blocked = {x.get("channel") for x in blocklist_raw
               if x.get("reason") in ("dmca", "nsfw")}
    channels = {
        c["id"]: c for c in channels_raw
        if c.get("id") and c.get("country") == COUNTRY
        and not c.get("is_nsfw", False) and c.get("id") not in blocked
        and not c.get("closed")
    }
    logos = {}
    for item in logos_raw:
        if item.get("channel") in channels and item.get("in_use") and item.get("url"):
            logos.setdefault(item["channel"], item["url"])

    candidates, seen = [], set()
    for stream in streams_raw:
        channel_id = stream.get("channel")
        url = str(stream.get("url") or "").strip()
        if channel_id not in channels or not url or url in seen:
            continue
        if urlparse(url).scheme not in ("http", "https"):
            continue
        seen.add(url)
        candidates.append((channels[channel_id], stream))

    candidates.sort(key=lambda pair: (
        clean(pair[0].get("name")).casefold(),
        -declared_quality(pair[1].get("quality") or pair[1].get("title")),
        pair[1].get("url", ""),
    ))
    print(f"{len(channels)} Indonesian channel records; {len(candidates)} unique public HTTP(S) stream URLs.")

    media_probe_urls = set()
    if ENABLE_MEDIA_PROBE and MEDIA_PROBE_LIMIT:
        for _, stream in candidates:
            q = declared_quality(stream.get("quality") or stream.get("title"))
            if q >= 720 and len(media_probe_urls) < MEDIA_PROBE_LIMIT:
                media_probe_urls.add(stream["url"])

    health = {}
    if CHECK_STREAMS and candidates:
        with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = {
                pool.submit(
                    check_stream, stream, TIMEOUT, RETRIES, RETRY_BACKOFF,
                    ENABLE_MEDIA_PROBE and stream.get("url") in media_probe_urls,
                ): stream
                for _, stream in candidates
            }
            for future in concurrent.futures.as_completed(futures):
                stream = futures[future]
                try:
                    item = future.result()
                except Exception as exc:
                    item = {
                        "url": stream.get("url"), "status": "probe_error",
                        "http_reachable": False, "http_status": None,
                        "error_kind": "worker_error", "detail": str(exc)[:240],
                        "hls_status": "not_checked", "hls_detail": "Probe worker failed",
                        "attempts": 0,
                    }
                health[item["url"]] = item
                print(f"[{item['status']}] {item['url'][:110]}")

    rows = []
    for channel, stream in candidates:
        quality = declared_quality(stream.get("quality") or stream.get("title"))
        state = health.get(stream["url"], {
            "url": stream["url"], "status": "not_checked",
            "http_reachable": False, "hls_status": "not_checked",
            "hls_detail": "Stream checks disabled",
        })
        rows.append({
            "channel": channel, "stream": stream, "declared_quality": quality,
            "health": state, "group": category_group(channel), "logos": logos,
        })

    generated_at = datetime.now(timezone.utc).isoformat()
    stream_records = []
    for row in rows:
        item = row["health"]
        video = item.get("video_probe") or {"status": "not_checked"}
        stream_records.append({
            "channel": row["channel"].get("name"),
            "channel_id": row["channel"].get("id"),
            "title": row["stream"].get("title"),
            "quality": row["stream"].get("quality"),
            "declared_quality": row["declared_quality"],
            "url": row["stream"].get("url"),
            "source": "iptv-org/api",
            "labels": row["stream"].get("labels") or [],
            "status": item.get("status", "not_checked"),
            "http_reachable": bool(item.get("http_reachable", False)),
            "http_status": item.get("http_status"),
            "error_kind": item.get("error_kind"),
            "detail": item.get("detail", ""),
            "checked_at": item.get("checked_at"),
            "attempts": item.get("attempts", 0),
            "hls_status": item.get("hls_status", "not_checked"),
            "hls_detail": item.get("hls_detail", ""),
            "hls_manifest_url": item.get("hls_manifest_url"),
            "hls_variant_count": item.get("hls_variant_count", 0),
            "hls_selected_bandwidth": item.get("hls_selected_bandwidth"),
            "hls_declared_resolution": item.get("hls_declared_resolution"),
            "hls_segment_url": item.get("hls_segment_url"),
            "hls_segment_http_status": item.get("hls_segment_http_status"),
            "hls_segment_bytes": item.get("hls_segment_bytes", 0),
            "video_probe": video,
        })

    transitions = analyze_history(stream_records, previous_report, HISTORY_PATH, generated_at)
    for row, record in zip(rows, stream_records):
        row["record"] = record

    def order_key(row):
        record = row["record"]
        return (
            row["group"],
            clean(row["channel"].get("name")).casefold(),
            -record.get("reliability_score", 0),
            -row["declared_quality"],
            row["stream"].get("url", ""),
        )

    rows.sort(key=order_key)
    all_rows = rows
    declared_hd = [row for row in rows if row["declared_quality"] >= 720]
    online = [row for row in rows if row["record"]["http_reachable"]]
    online_declared_hd = [row for row in online if row["declared_quality"] >= 720]
    hls_validated = [row for row in online if row["record"]["hls_status"] == "segment_ok"]
    hd_verified = [
        row for row in hls_validated
        if row["record"].get("video_probe", {}).get("status") == "verified"
        and row["record"]["video_probe"].get("height", 0) >= 720
    ]
    stable = [
        row for row in hls_validated
        if row["record"].get("consecutive_failed_checks", 0) == 0
        and row["record"].get("reliability_score", 0) >= 50
    ]

    write_playlist("indonesia-all.m3u", all_rows)
    write_playlist("indonesia-hd.m3u", declared_hd)
    write_playlist("indonesia-online.m3u", online)
    write_playlist("indonesia-online-hd.m3u", online_declared_hd)
    write_playlist("indonesia-hls-validated.m3u", hls_validated)
    write_playlist("indonesia-hd-verified.m3u", hd_verified)
    write_playlist("indonesia-stable.m3u", stable)

    counts = Counter(record["status"] for record in stream_records)
    hls_counts = Counter(record["hls_status"] for record in stream_records)
    video_counts = Counter(record.get("video_probe", {}).get("status", "not_checked") for record in stream_records)
    report = {
        "schema_version": 2,
        "generated_at": generated_at,
        "country": COUNTRY,
        "source": "https://github.com/iptv-org/api",
        "channels_with_streams": len({row["channel"]["id"] for row in rows}),
        "candidate_streams": len(rows),
        "declared_hd_streams_720p_plus": len(declared_hd),
        "http_reachable_streams": counts.get("online", 0),
        "health_counts": dict(counts),
        "hls_validation_counts": dict(hls_counts),
        "hls_segment_verified_streams": hls_counts.get("segment_ok", 0),
        "video_probe_counts": dict(video_counts),
        "resolution_verified_hd_streams": len(hd_verified),
        "stable_hls_streams": len(stable),
        "transitions": transitions,
        "playlists": {
            "all": "playlists/indonesia-all.m3u",
            "declared_hd": "playlists/indonesia-hd.m3u",
            "http_reachable": "playlists/indonesia-online.m3u",
            "http_reachable_declared_hd": "playlists/indonesia-online-hd.m3u",
            "hls_segment_validated": "playlists/indonesia-hls-validated.m3u",
            "resolution_verified_hd": "playlists/indonesia-hd-verified.m3u",
            "stable_hls": "playlists/indonesia-stable.m3u",
        },
        "notes": [
            "HTTP reachability is separate from HLS validation and playback.",
            "HLS validation checks a manifest/variant and one sample media segment; it is not continuous playback.",
            "Declared quality comes from source metadata/title and is not measured resolution.",
            "Resolution verified means ffprobe reported video dimensions; it does not certify sustained playback or visual quality.",
            "Only publicly listed HTTP(S) feeds are collected. DRM, paywall, login, geo-controls and access-control bypass are not attempted.",
            "Discovery currently uses the iptv-org public API; new providers require provenance and authorization review.",
        ],
        "streams": stream_records,
    }
    HEALTH_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"Generated {len(rows)} candidates; HTTP reachable={counts.get('online', 0)}; "
        f"HLS segment_ok={hls_counts.get('segment_ok', 0)}; verified HD={len(hd_verified)}."
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        raise
