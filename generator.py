#!/usr/bin/env python3
"""APTRON IPTV Engine: refresh public Indonesian channel playlists."""
from __future__ import annotations

import concurrent.futures
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

API = "https://iptv-org.github.io/api"
COUNTRY = os.getenv("COUNTRY_CODE", "ID").upper()
TIMEOUT = int(os.getenv("CHECK_TIMEOUT", "10"))
WORKERS = int(os.getenv("CHECK_WORKERS", "16"))
CHECK_STREAMS = os.getenv("CHECK_STREAMS", "true").lower() == "true"
ROOT = Path(__file__).resolve().parent
PLAYLIST_DIR = ROOT / "playlists"
REPORT_DIR = ROOT / "reports"
HEADERS = {"User-Agent": "APTRON-IPTV-Engine/1.0", "Accept": "*/*"}

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
    req = Request(f"{API}/{name}.json", headers=HEADERS)
    with urlopen(req, timeout=45) as response:
        return json.loads(response.read().decode("utf-8"))

def clean(value) -> str:
    return re.sub(r'[\r\n,"]', " ", str(value or "")).strip()

def quality_score(value: str) -> int:
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

def fetch_sample(url: str, headers: dict, limit: int = 65536):
    request = Request(url, headers=headers)
    with urlopen(request, timeout=TIMEOUT) as response:
        return response.status, response.headers.get("Content-Type", "").lower(), response.read(limit)

def validate_hls(url: str, headers: dict) -> dict:
    """Check an HLS manifest and one media segment; this is not a full playback test."""
    from urllib.parse import urljoin

    result = {"status": "not_hls", "detail": "Stream is not an HLS playlist"}
    manifest_headers = dict(headers)
    manifest_headers.pop("Range", None)
    try:
        status, content_type, body = fetch_sample(url, manifest_headers, 65536)
        text = body.decode("utf-8", errors="replace")
        if not text.lstrip().startswith("#EXTM3U"):
            return result

        playlist_url = url
        # For a master playlist, probe the highest-bandwidth variant.
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        variants = []
        for index, line in enumerate(lines[:-1]):
            if line.startswith("#EXT-X-STREAM-INF:"):
                match = re.search(r"BANDWIDTH=(\d+)", line)
                bandwidth = int(match.group(1)) if match else 0
                variants.append((bandwidth, urljoin(url, lines[index + 1])))
        if variants:
            _, playlist_url = max(variants, key=lambda item: item[0])
            _, _, body = fetch_sample(playlist_url, manifest_headers, 65536)
            text = body.decode("utf-8", errors="replace")
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            if not text.lstrip().startswith("#EXTM3U"):
                return {"status": "failed", "detail": "Variant URL did not return an HLS playlist"}

        segment_url = next(
            (urljoin(playlist_url, line) for line in lines
             if not line.startswith("#") and line.lower().split("?")[0].endswith((".ts", ".m4s", ".mp4", ".aac"))),
            None
        )
        if not segment_url:
            return {"status": "inconclusive", "detail": "No media segment URI found in sampled playlist"}

        segment_headers = dict(headers)
        segment_headers["Range"] = "bytes=0-2047"
        seg_status, seg_type, segment = fetch_sample(segment_url, segment_headers, 2048)
        if 200 <= seg_status < 300 and segment and not segment.lstrip().lower().startswith((b"<html", b"<!doctype")):
            return {"status": "segment_ok", "detail": f"Manifest and sample segment reachable (HTTP {seg_status})"}
        return {"status": "failed", "detail": f"Media segment returned HTTP {seg_status} or invalid content"}
    except Exception as exc:
        return {"status": "failed", "detail": str(exc)[:180]}

def check_stream(stream: dict) -> dict:
    url = str(stream.get("url", "")).strip()
    parsed = urlparse(url)
    result = {"url": url, "status": "invalid", "http_status": None, "detail": ""}
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        result["detail"] = "URL bukan HTTP(S)"
        return result

    headers = dict(HEADERS)
    headers["Range"] = "bytes=0-4095"
    if stream.get("user_agent"):
        headers["User-Agent"] = str(stream["user_agent"])
    if stream.get("referrer"):
        headers["Referer"] = str(stream["referrer"])

    try:
        request = Request(url, headers=headers)
        with urlopen(request, timeout=TIMEOUT) as response:
            status = response.status
            sample = response.read(4096)
            content_type = response.headers.get("Content-Type", "").lower()
        result["http_status"] = status
        if not 200 <= status < 300:
            result["status"] = "offline"
            result["detail"] = f"HTTP {status}"
            return result
        prefix = sample.lstrip()[:100].lower()
        if b"<html" in prefix or b"<!doctype html" in prefix:
            result["status"] = "unplayable"
            result["detail"] = "Server returned HTML, not media"
            return result
        result["status"] = "online"
        result["detail"] = f"HTTP {status}; {content_type or 'content type unknown'}"
        if b"#EXTM3U" in sample[:512] or "mpegurl" in content_type:
            hls = validate_hls(url, headers)
            result["hls_status"] = hls["status"]
            result["hls_detail"] = hls["detail"]
        else:
            result["hls_status"] = "not_hls"
            result["hls_detail"] = "No HLS manifest detected"
    except HTTPError as exc:
        result["http_status"] = exc.code
        result["status"] = "offline"
        result["detail"] = f"HTTP {exc.code}"
    except (URLError, TimeoutError, OSError) as exc:
        result["status"] = "unreachable"
        result["detail"] = str(exc)[:180]
    return result

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

def main():
    PLAYLIST_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
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

    print(f"{len(channels)} Indonesian channel records; {len(candidates)} unique stream URLs.")
    health = {}
    if CHECK_STREAMS and candidates:
        with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = {pool.submit(check_stream, stream): stream for _, stream in candidates}
            for future in concurrent.futures.as_completed(futures):
                item = future.result()
                health[item["url"]] = item
                print(f"[{item['status']}] {item['url'][:110]}")

    rows = []
    for channel, stream in candidates:
        quality = quality_score(stream.get("quality") or stream.get("title"))
        state = health.get(stream["url"], {"status": "not_checked"})
        rows.append({
            "channel": channel, "stream": stream, "quality": quality,
            "health": state, "group": category_group(channel)
        })

    rows.sort(key=lambda row: (
        row["group"], clean(row["channel"].get("name")).casefold(),
        -row["quality"], row["stream"].get("url", "")
    ))

    def write_playlist(filename: str, selected: list):
        lines = ["#EXTM3U"]
        lines.extend(extinf(row["channel"], row["stream"], logos) for row in selected)
        (PLAYLIST_DIR / filename).write_text("\n".join(lines) + "\n", encoding="utf-8")

    online = [row for row in rows if row["health"]["status"] == "online"] if CHECK_STREAMS else rows
    hd = [row for row in rows if row["quality"] >= 720]
    online_hd = [row for row in online if row["quality"] >= 720]

    write_playlist("indonesia-all.m3u", rows)
    write_playlist("indonesia-hd.m3u", hd)
    write_playlist("indonesia-online.m3u", online)
    write_playlist("indonesia-online-hd.m3u", online_hd)

    counts = Counter(row["health"]["status"] for row in rows)
    hls_counts = Counter(row["health"].get("hls_status", "not_checked") for row in rows)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "country": COUNTRY,
        "source": "https://github.com/iptv-org/api",
        "channels_with_streams": len({row["channel"]["id"] for row in rows}),
        "candidate_streams": len(rows),
        "declared_hd_streams_720p_plus": len(hd),
        "http_reachable_streams": counts.get("online", 0),
        "health_counts": dict(counts),
        "hls_validation_counts": dict(hls_counts),
        "hls_segment_verified_streams": hls_counts.get("segment_ok", 0),
        "notes": [
            "HLS validation checks a manifest and one sample media segment; it is not a continuous playback or bitrate test.",
            "Quality is based on source metadata/title, not measured bitrate or decoded resolution.",
            "HTTP reachability does not guarantee playback; HLS segments, geo restrictions and app compatibility are not fully tested.",
            "Only publicly listed HTTP(S) feeds are collected. DRM, paywall, login and access-control bypass are not attempted."
        ],
        "streams": [{
            "channel": row["channel"].get("name"),
            "channel_id": row["channel"].get("id"),
            "title": row["stream"].get("title"),
            "quality": row["stream"].get("quality"),
            "url": row["stream"].get("url"),
            "labels": row["stream"].get("labels") or [],
            "status": row["health"]["status"],
            "detail": row["health"].get("detail", "")
        } for row in rows]
    }
    (REPORT_DIR / "health.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Generated {len(rows)} candidates; {len(hd)} declared HD+; {len(online)} HTTP reachable.")

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        raise
