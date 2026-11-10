"""Network and HLS probes for APTRON IPTV Engine.

Only probes publicly reachable HTTP(S) resources. No authentication, DRM,
paywall, geo-restriction, or access-control bypass is attempted.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

USER_AGENT = "APTRON-IPTV-Engine/2.0"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _classify_http(code: int) -> str:
    if 200 <= code < 300:
        return "online"
    if code in (401, 403):
        return "restricted"
    if code == 404 or code == 410:
        return "offline"
    if code == 429:
        return "rate_limited"
    if 500 <= code <= 599:
        return "server_error"
    return "http_error"


def _request_sample(url: str, headers: dict, timeout: int, limit: int = 65536):
    request = Request(url, headers=headers)
    with urlopen(request, timeout=timeout) as response:
        return (
            response.status,
            response.headers.get("Content-Type", "").lower(),
            response.read(limit),
            response.geturl(),
        )


def _network_error(exc: Exception) -> tuple[str, str]:
    reason = getattr(exc, "reason", exc)
    message = str(reason)[:240]
    lowered = message.lower()
    if "name or service not known" in lowered or "no address associated" in lowered or "temporary failure in name resolution" in lowered:
        return "dns_error", message
    if "timed out" in lowered or "timeout" in lowered:
        return "timeout", message
    if "ssl" in lowered or "tls" in lowered or "certificate" in lowered:
        return "tls_error", message
    if "refused" in lowered:
        return "connection_refused", message
    return "network_error", message


def _parse_hls_attributes(value: str) -> dict:
    result = {}
    for key, raw in re.findall(r'([A-Z0-9-]+)=("[^"]*"|[^,]*)', value):
        result[key] = raw.strip('"')
    return result


def validate_hls(url: str, headers: dict, timeout: int = 10) -> dict:
    """Validate an HLS manifest, selected variant (if master), and one media segment."""
    result = {
        "status": "not_hls",
        "detail": "No HLS manifest detected",
        "manifest_url": url,
        "variant_count": 0,
        "selected_bandwidth": None,
        "declared_resolution": None,
        "segment_url": None,
        "segment_http_status": None,
        "segment_bytes": 0,
    }
    manifest_headers = {k: v for k, v in headers.items() if k.lower() != "range"}
    try:
        status, content_type, body, final_url = _request_sample(url, manifest_headers, timeout)
        text = body.decode("utf-8", errors="replace")
        if not text.lstrip().startswith("#EXTM3U"):
            return result
        result["manifest_url"] = final_url
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        variants = []
        pending_attrs = None
        for line in lines:
            if line.startswith("#EXT-X-STREAM-INF:"):
                pending_attrs = _parse_hls_attributes(line.split(":", 1)[1])
            elif pending_attrs is not None and not line.startswith("#"):
                bandwidth = int(pending_attrs.get("BANDWIDTH", "0") or 0)
                resolution = pending_attrs.get("RESOLUTION")
                variants.append((bandwidth, urljoin(final_url, line), resolution))
                pending_attrs = None
        result["variant_count"] = len(variants)
        media_url = final_url
        if variants:
            bandwidth, media_url, resolution = max(variants, key=lambda item: item[0])
            result["selected_bandwidth"] = bandwidth or None
            result["declared_resolution"] = resolution
            _, _, body, media_url = _request_sample(media_url, manifest_headers, timeout)
            text = body.decode("utf-8", errors="replace")
            if not text.lstrip().startswith("#EXTM3U"):
                return {**result, "status": "failed", "detail": "Selected variant did not return an HLS manifest"}
            lines = [line.strip() for line in text.splitlines() if line.strip()]

        segment_uri = None
        for line in lines:
            if line.startswith("#EXT-X-MAP:"):
                attrs = _parse_hls_attributes(line.split(":", 1)[1])
                if attrs.get("URI"):
                    segment_uri = attrs["URI"]
                    break
            if not line.startswith("#") and urlparse(line).path.lower().endswith((".ts", ".m4s", ".mp4", ".aac", ".mpg", ".mpeg")):
                segment_uri = line
                break
        if not segment_uri:
            return {**result, "status": "inconclusive", "detail": "No media segment URI found in sampled playlist"}

        segment_url = urljoin(media_url, segment_uri)
        segment_headers = dict(headers)
        segment_headers["Range"] = "bytes=0-2047"
        seg_status, _, segment, _ = _request_sample(segment_url, segment_headers, timeout, 2048)
        result.update({
            "segment_url": segment_url,
            "segment_http_status": seg_status,
            "segment_bytes": len(segment),
        })
        if 200 <= seg_status < 300 and segment and not segment.lstrip().lower().startswith((b"<html", b"<!doctype")):
            return {**result, "status": "segment_ok", "detail": f"Manifest and sample segment reachable (HTTP {seg_status})"}
        return {**result, "status": "failed", "detail": f"Sample segment returned HTTP {seg_status} or invalid content"}
    except HTTPError as exc:
        return {**result, "status": "failed", "detail": f"HTTP {exc.code} while validating HLS"}
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        kind, message = _network_error(exc)
        return {**result, "status": "failed", "error_kind": kind, "detail": message}


def probe_video(url: str, timeout: int = 12) -> dict:
    """Optionally inspect actual video dimensions with ffprobe; never trusts title metadata."""
    executable = shutil.which("ffprobe")
    if not executable:
        return {"status": "unavailable", "detail": "ffprobe is not installed"}
    command = [
        executable, "-v", "error", "-read_intervals", "%+5",
        "-select_streams", "v:0", "-show_entries",
        "stream=codec_name,width,height,bit_rate", "-of", "json", url,
    ]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
        if completed.returncode != 0:
            return {"status": "failed", "detail": (completed.stderr or "ffprobe failed")[:240]}
        payload = json.loads(completed.stdout or "{}")
        streams = payload.get("streams") or []
        if not streams:
            return {"status": "no_video", "detail": "No video stream detected"}
        stream = streams[0]
        width, height = stream.get("width"), stream.get("height")
        if not isinstance(width, int) or not isinstance(height, int):
            return {"status": "inconclusive", "detail": "Video dimensions unavailable"}
        return {
            "status": "verified",
            "width": width,
            "height": height,
            "codec": stream.get("codec_name"),
            "bitrate": int(stream["bit_rate"]) if str(stream.get("bit_rate", "")).isdigit() else None,
            "detail": f"Video stream reports {width}x{height}",
        }
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "detail": f"ffprobe exceeded {timeout}s"}
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {"status": "failed", "detail": str(exc)[:240]}


def check_stream(stream: dict, timeout: int = 10, retries: int = 1, retry_backoff: float = 1.0,
                 enable_media_probe: bool = False) -> dict:
    url = str(stream.get("url", "")).strip()
    parsed = urlparse(url)
    result = {
        "url": url, "status": "invalid", "http_reachable": False,
        "http_status": None, "error_kind": None, "detail": "",
        "checked_at": utc_now(), "attempts": 0,
        "hls_status": "not_checked", "hls_detail": "Not checked",
        "video_probe": {"status": "not_checked", "detail": "Media probe disabled"},
    }
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        result["detail"] = "URL is not a valid HTTP(S) endpoint"
        return result

    headers = {"User-Agent": str(stream.get("user_agent") or USER_AGENT), "Accept": "*/*", "Range": "bytes=0-4095"}
    if stream.get("referrer"):
        headers["Referer"] = str(stream["referrer"])

    for attempt in range(max(0, retries) + 1):
        result["attempts"] = attempt + 1
        try:
            status, content_type, sample, final_url = _request_sample(url, headers, timeout, 4096)
            result.update({"http_status": status, "final_url": final_url, "content_type": content_type})
            state = _classify_http(status)
            result["status"] = state
            result["http_reachable"] = state == "online"
            if state != "online":
                result["detail"] = f"HTTP {status}"
                if state in ("rate_limited", "server_error") and attempt < retries:
                    time.sleep(retry_backoff * (2 ** attempt))
                    continue
                return result
            prefix = sample.lstrip()[:120].lower()
            if b"<html" in prefix or b"<!doctype html" in prefix:
                result.update({"status": "unplayable", "detail": "Server returned HTML, not media"})
                return result
            result["detail"] = f"HTTP {status}; {content_type or 'content type unknown'}"
            is_hls = b"#EXTM3U" in sample[:512] or "mpegurl" in content_type
            if is_hls:
                hls = validate_hls(final_url, headers, timeout)
                result.update({f"hls_{key}" if key not in ("status", "detail") else key: value for key, value in hls.items()})
                result["hls_status"] = hls["status"]
                result["hls_detail"] = hls["detail"]
                if enable_media_probe and hls["status"] == "segment_ok":
                    result["video_probe"] = probe_video(final_url, timeout=max(timeout, 12))
            else:
                result["hls_status"] = "not_hls"
                result["hls_detail"] = "No HLS manifest detected"
            return result
        except HTTPError as exc:
            result.update({"http_status": exc.code, "status": _classify_http(exc.code),
                           "detail": f"HTTP {exc.code}"})
            if result["status"] in ("rate_limited", "server_error") and attempt < retries:
                time.sleep(retry_backoff * (2 ** attempt))
                continue
            return result
        except (URLError, TimeoutError, OSError) as exc:
            kind, message = _network_error(exc)
            result.update({"status": "unreachable", "error_kind": kind, "detail": message})
            if attempt < retries and kind in ("dns_error", "timeout", "connection_refused", "network_error"):
                time.sleep(retry_backoff * (2 ** attempt))
                continue
            return result
    return result
