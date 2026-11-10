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
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

USER_AGENT = "APTRON-IPTV-Engine/2.0"


def utc_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _classify_http(code: int) -> str:
    if 200 <= code < 300:
        return "online"
    if code in (401, 403):
        return "restricted"
    if code in (404, 410):
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
    if any(token in lowered for token in (
        "name or service not known", "no address associated",
        "temporary failure in name resolution", "nodename nor servname",
    )):
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
        "init_segment_status": None,
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
                variants.append((bandwidth, urljoin(final_url, line), pending_attrs.get("RESOLUTION")))
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

        init_uri = None
        segment_uri = None
        for line in lines:
            if line.startswith("#EXT-X-MAP:"):
                init_uri = _parse_hls_attributes(line.split(":", 1)[1]).get("URI")
            elif not line.startswith("#") and urlparse(line).path.lower().endswith(
                (".ts", ".m4s", ".mp4", ".aac", ".mpg", ".mpeg", ".cmfv", ".cmfa")
            ):
                segment_uri = line
                break
        if not segment_uri:
            return {**result, "status": "inconclusive", "detail": "No media segment URI found in sampled playlist"}

        segment_headers = dict(headers)
        segment_headers["Range"] = "bytes=0-2047"
        if init_uri:
            init_url = urljoin(media_url, init_uri)
            init_status, _, init_body, _ = _request_sample(init_url, segment_headers, timeout, 2048)
            result["init_segment_status"] = init_status
            if not (200 <= init_status < 300 and init_body):
                return {**result, "status": "failed", "detail": f"fMP4 init segment returned HTTP {init_status}"}

        segment_url = urljoin(media_url, segment_uri)
        seg_status, _, segment, _ = _request_sample(segment_url, segment_headers, timeout, 2048)
        result.update({
            "segment_url": segment_url,
            "segment_http_status": seg_status,
            "segment_bytes": len(segment),
        })
        if 200 <= seg_status < 300 and segment and not segment.lstrip().lower().startswith((b"<html", b"<!doctype")):
            return {**result, "status": "segment_ok", "detail": f"Manifest and sample media segment reachable (HTTP {seg_status})"}
        return {**result, "status": "failed", "detail": f"Sample media segment returned HTTP {seg_status} or invalid content"}
    except HTTPError as exc:
        return {**result, "status": "failed", "detail": f"HTTP {exc.code} while validating HLS"}
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        kind, message = _network_error(exc)
        return {**result, "status": "failed", "error_kind": kind, "detail": message}


def probe_video(url: str, timeout: int = 12, headers: dict | None = None) -> dict:
    """Inspect bitstream dimensions with ffprobe; source title metadata is not used."""
    import shutil
    executable = shutil.which("ffprobe")
    if not executable:
        return {"status": "unavailable", "detail": "ffprobe is not installed"}
    command = [executable, "-v", "error", "-read_intervals", "%+5",
               "-select_streams", "v:0", "-show_entries",
               "stream=codec_name,width,height,bit_rate", "-of", "json"]
    if headers:
        if headers.get("User-Agent"):
            command.extend(["-user_agent", headers["User-Agent"]])
        custom = "".join(f"{key}: {value}\\r\\n" for key, value in headers.items()
                         if key.lower() not in ("user-agent", "range"))
        if custom:
            command.extend(["-headers", custom])
    command.append(url)
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
            "status": "verified", "width": width, "height": height,
            "codec": stream.get("codec_name"),
            "bitrate": int(stream["bit_rate"]) if str(stream.get("bit_rate", "")).isdigit() else None,
            "detail": f"Video bitstream reports {width}x{height}",
        }
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "detail": f"ffprobe exceeded {timeout}s"}
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {"status": "failed", "detail": str(exc)[:240]}


def probe_playback(url: str, timeout: int = 15, headers: dict | None = None) -> dict:
    """Decode a short sample with ffmpeg; this is a smoke test, not an uptime guarantee."""
    executable = shutil.which("ffmpeg")
    if not executable:
        return {"status": "unavailable", "detail": "ffmpeg is not installed"}
    command = [executable, "-nostdin", "-v", "error"]
    if headers:
        if headers.get("User-Agent"):
            command.extend(["-user_agent", headers["User-Agent"]])
        custom = "".join(f"{key}: {value}\\r\\n" for key, value in headers.items()
                         if key.lower() not in ("user-agent", "range"))
        if custom:
            command.extend(["-headers", custom])
    command.extend(["-i", url, "-t", "5", "-map", "0:v:0", "-frames:v", "30", "-f", "null", "-"])
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
        if completed.returncode == 0:
            return {"status": "verified", "detail": "Up to 30 video frames decoded successfully"}
        return {"status": "failed", "detail": (completed.stderr or "ffmpeg decode failed")[-240:]}
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "detail": f"ffmpeg exceeded {timeout}s"}
    except OSError as exc:
        return {"status": "failed", "detail": str(exc)[:240]}


def check_stream(stream: dict, timeout: int = 10, retries: int = 1, retry_backoff: float = 1.0,
                 enable_media_probe: bool = False, enable_playback_probe: bool = False) -> dict:
    url = str(stream.get("url", "")).strip()
    parsed = urlparse(url)
    result = {
        "url": url, "status": "invalid", "http_reachable": False,
        "http_status": None, "error_kind": None, "detail": "",
        "checked_at": utc_now(), "attempts": 0,
        "hls_status": "not_checked", "hls_detail": "Not checked",
        "video_probe": {"status": "not_checked", "detail": "Media probe disabled"},
        "playback_probe": {"status": "not_checked", "detail": "Playback probe disabled"},
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
                for key, value in hls.items():
                    if key not in ("status", "detail"):
                        result[f"hls_{key}"] = value
                result["hls_status"] = hls["status"]
                result["hls_detail"] = hls["detail"]
                if enable_media_probe and hls["status"] == "segment_ok":
                    probe_headers = {k: v for k, v in headers.items() if k.lower() != "range"}
                    result["video_probe"] = probe_video(final_url, timeout=max(timeout, 12), headers=probe_headers)
                if enable_playback_probe and hls["status"] == "segment_ok":
                    probe_headers = {k: v for k, v in headers.items() if k.lower() != "range"}
                    result["playback_probe"] = probe_playback(final_url, timeout=max(timeout, 15), headers=probe_headers)
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
