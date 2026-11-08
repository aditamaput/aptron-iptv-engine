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
    "entertainment": "Hiburan", "family": "Keluarga", " general": "Umum",
    "general": "Umum", "kids": "Anak", "legislative": "Pemerintahan",
    "lifestyle": "Gaya Hidup", "movies": "Film", "music": "Musik",
    "news": "Berita", "outdoor": "Outdoor", "religious": "Religi",
    "religious": "Religi", "series": "Serial", "science": "Sains",
    "shop": "Belanja", "sports": "Olahraga", "travel": "Wisata",
    "weather": "Cuaca",
}

def get_json(name: str):
    req = Request(f"{API}/{name}.json", headers=HEADERS)
    with urlopen(req, timeout=45) as response:
        return json.loads(response.read().decode("utf-8"))

def clean(value) -> str:
    return re.sub(r'[\\r\\n,"]', " ", str(value or "")).strip()

def quality_score(value: str) -> int:
    text = str(value or "").lower()
    match = re.search(r"(\\d{3,4})\\s*[pi]?", text)
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
        # Detect HTML error/login pages masquerading as stream responses.
        prefix = sample.lstrip()[:100].lower()
        if b"<html" in prefix or b"<!doctype html" in prefix:
            result["status"] = "unplayable"
            result["detail"] = "Server returned HTML, not media"
            return result
        result["status"] = "online"
        result["detail"] = f"HTTP {status}; {content_type or 'content type unknown'}"
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
    q = clean(stream.get("quality") or title)
    display = f"{name} ({q})" if q else name
    return f"#EXTINF:-1 {' '.join(attrs)},{display}\\n{stream['url']}"

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
        cid, url = stream.get("channel"), str(stream.get("url") or "").strip()
        if cid not in channels or not url or url in seen:
            continue
        if urlparse(url).scheme not in ("http", "https"):
            continue
        # Ignore explicitly blocked feeds; preserve geo-blocked labels in the report.
        seen.add(url)
        candidates.append((channels[cid], stream))

    print(f"{len(channels)} Indonesian channel records; {len(candidates)} unique stream URLs.")
    health = {}
    if CHECK_STREAMS and candidates:
        with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = {pool.submit(check_stream, s): s for _, s in candidates}
            for future in concurrent.futures.as_completed(futures):
                item = future.result()
                health[item["url"]] = item
                print(f"[{item['status']}] {item['url'][:110]}")

    rows = []
    for channel, stream in candidates:
        q = quality_score(stream.get("quality") or stream.get("title"))
        state = health.get(stream["url"], {"status": "not_checked"})
        rows.append({
            "channel": channel, "stream": stream, "quality": q,
            "health": state, "group": category_group(channel)
        })

    # Highest declared quality first within each channel; keep all source options.
    rows.sort(key=lambda r: (r["group"], clean(r["channel"].get("name")).casefold(),
                             -r["quality"], r["stream"].get("url", "")))

    def write_playlist(filename: str, selected: list):
        lines = ["#EXTM3U"]
        lines.extend(extinf(r["channel"], r["stream"], logos) for r in selected)
        (PLAYLIST_DIR / filename).write_text("\\n".join(lines) + "\\n", encoding="utf-8")

    online = [r for r in rows if r["health"]["status"] == "online"] if CHECK_STREAMS else rows
    hd = [r for r in rows if r["quality"] >= 720]
    online_hd = [r for r in online if r["quality"] >= 720]

    write_playlist("indonesia-all.m3u", rows)
    write_playlist("indonesia-hd.m3u", hd)
    write_playlist("indonesia-online.m3u", online)
    write_playlist("indonesia-online-hd.m3u", online_hd)

    counts = Counter(r["health"]["status"] for r in rows)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "country": COUNTRY,
        "source": "https://github.com/iptv-org/api",
        "channels_with_streams": len({r["channel"]["id"] for r in rows}),
        "candidate_streams": len(rows),
        "declared_hd_streams_720p_plus": len(hd),
        "http_reachable_streams": counts.get("online", 0),
        "health_counts": dict(counts),
        "notes": [
            "Quality is based on source metadata/title, not a measured bitrate or decoded resolution.",
            "HTTP reachability does not guarantee playback; HLS segments, DRM, geo restrictions and app compatibility are not fully tested.",
            "Only publicly listed HTTP(S) feeds are collected. DRM, paywall, login and access-control bypass are not attempted."
        ],
        "streams": [{
            "channel": r["channel"].get("name"),
            "channel_id": r["channel"].get("id"),
            "title": r["stream"].get("title"),
            "quality": r["stream"].get("quality"),
            "url": r["stream"].get("url"),
            "labels": r["stream"].get("labels") or [],
            "status": r["health"]["status"],
            "detail": r["health"].get("detail", "")
        } for r in rows]
    }
    (REPORT_DIR / "health.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Generated {len(rows)} candidates; {len(hd)} declared HD+; "
          f"{len(online)} HTTP reachable.")
    print("Playlists:", PLAYLIST_DIR.resolve())

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        raise
