"""Small, bounded stream-health history and transition analysis."""
from __future__ import annotations

import json
from pathlib import Path

HISTORY_LIMIT = 14


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return default


def snapshot_from_report(report: dict) -> dict:
    streams = {}
    for item in report.get("streams", []):
        url = item.get("url")
        if url:
            streams[url] = {
                "channel": item.get("channel"),
                "status": item.get("status"),
                "hls_status": item.get("hls_status", "not_checked"),
                "error_kind": item.get("error_kind"),
            }
    return {"generated_at": report.get("generated_at"), "streams": streams}


def analyze_history(current_streams: list, previous_report: dict, history_path: Path, generated_at: str):
    history_doc = read_json(history_path, {"schema_version": 1, "snapshots": []})
    snapshots = history_doc.get("snapshots", []) if isinstance(history_doc, dict) else []
    if not snapshots and previous_report.get("streams"):
        previous = snapshot_from_report(previous_report)
        if previous.get("generated_at"):
            snapshots = [previous]

    current = {}
    transitions = {"recovered_http": [], "new_http_failures": [], "hls_regressions": [], "hls_recoveries": []}
    for item in current_streams:
        url = item.get("url")
        if not url:
            continue
        state = {
            "channel": item.get("channel"),
            "status": item.get("status"),
            "hls_status": item.get("hls_status", "not_checked"),
            "error_kind": item.get("error_kind"),
        }
        current[url] = state
        prior = next((snap.get("streams", {}).get(url) for snap in reversed(snapshots)
                      if url in snap.get("streams", {})), None)
        if prior:
            label = item.get("channel") or url
            if prior.get("status") != "online" and state["status"] == "online":
                transitions["recovered_http"].append({"channel": label, "url": url})
            if prior.get("status") == "online" and state["status"] != "online":
                transitions["new_http_failures"].append({"channel": label, "url": url, "status": state["status"]})
            if prior.get("hls_status") == "segment_ok" and state["hls_status"] not in ("segment_ok", "not_hls"):
                transitions["hls_regressions"].append({"channel": label, "url": url, "hls_status": state["hls_status"]})
            if prior.get("hls_status") != "segment_ok" and state["hls_status"] == "segment_ok":
                transitions["hls_recoveries"].append({"channel": label, "url": url})

        past = [snap.get("streams", {}).get(url) for snap in snapshots if url in snap.get("streams", {})]
        observations = past[-(HISTORY_LIMIT - 1):] + [state]
        successes = sum(1 for old in observations if old.get("status") == "online" and old.get("hls_status") == "segment_ok")
        score = round(100 * successes / len(observations), 1) if observations else 0.0
        consecutive_failures = 0
        for old in reversed(observations):
            if old.get("status") == "online" and old.get("hls_status") == "segment_ok":
                break
            consecutive_failures += 1
        item["history_observations"] = len(observations)
        item["reliability_score"] = score
        item["consecutive_failed_checks"] = consecutive_failures

    new_snapshot = {"generated_at": generated_at, "streams": current}
    snapshots = (snapshots + [new_snapshot])[-HISTORY_LIMIT:]
    output = {"schema_version": 1, "retention": HISTORY_LIMIT, "snapshots": snapshots}
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    return transitions
