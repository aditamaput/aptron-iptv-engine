# APTRON IPTV ENGINE 2.0

Automated discovery, layered stream validation, health history and M3U generation for publicly listed Indonesian television streams.

## What it does

- Pulls Indonesian channel, stream, logo and blocklist metadata from the public iptv-org API.
- Filters closed, NSFW and source-blocklisted channel IDs.
- Checks public HTTP(S) endpoints with bounded retries and classifies DNS, timeout, TLS, connection, HTTP restriction, rate-limit and server errors.
- Separates HTTP reachability from HLS manifest/variant and sample-segment validation.
- Stores per-stream HLS results, segment details, probe timestamps and attempt counts in `reports/health.json`.
- Retains a bounded 14-snapshot history in `reports/history.json` and reports recovered/newly failing endpoints.
- Optionally uses ffprobe to inspect actual video dimensions for a capped number of declared-HD candidates. Metadata claims are never treated as measured resolution.
- Optionally uses ffmpeg to decode up to 30 frames from a five-second sample for a capped number of candidates.
- Generates separate all-candidate, declared-HD, HTTP-reachable, HLS-validated, resolution-verified-HD, playback-sampled and stable-HLS playlists.
- Ranks multiple endpoints for each channel as primary and backups in the health report; this is playlist ordering, not automatic mid-stream failover.

## Playlist outputs

- [All candidates](https://raw.githubusercontent.com/aditamaput/aptron-iptv-engine/main/playlists/indonesia-all.m3u)
- [Declared HD candidates (metadata only)](https://raw.githubusercontent.com/aditamaput/aptron-iptv-engine/main/playlists/indonesia-hd.m3u)
- [HTTP reachable](https://raw.githubusercontent.com/aditamaput/aptron-iptv-engine/main/playlists/indonesia-online.m3u)
- [HTTP reachable + declared HD (metadata only)](https://raw.githubusercontent.com/aditamaput/aptron-iptv-engine/main/playlists/indonesia-online-hd.m3u)
- [HLS manifest and sample segment validated](https://raw.githubusercontent.com/aditamaput/aptron-iptv-engine/main/playlists/indonesia-hls-validated.m3u)
- [Resolution verified HD](https://raw.githubusercontent.com/aditamaput/aptron-iptv-engine/main/playlists/indonesia-hd-verified.m3u)
- [Playback sample verified](https://raw.githubusercontent.com/aditamaput/aptron-iptv-engine/main/playlists/indonesia-playback-verified.m3u)
- [Stable HLS candidates](https://raw.githubusercontent.com/aditamaput/aptron-iptv-engine/main/playlists/indonesia-stable.m3u)
- [Health report](https://raw.githubusercontent.com/aditamaput/aptron-iptv-engine/main/reports/health.json)

The stable playlist requires at least three observations, a current passing HLS sample and an 80% or better recent HLS success rate. Primary/backup ranks are included per channel in `health.json`; playlist ordering does not provide seamless mid-playback failover, which requires player or relay support.

## Configuration

Environment variables:

| Variable | Default | Meaning |
|---|---:|---|
| `COUNTRY_CODE` | `ID` | Two-letter country filter |
| `CHECK_STREAMS` | `true` | Enable endpoint checks |
| `CHECK_TIMEOUT` | `10` | Per-request timeout in seconds |
| `CHECK_WORKERS` | `16` | Concurrent probes (capped at 32) |
| `CHECK_RETRIES` | `1` | Bounded retries (capped at 3) |
| `RETRY_BACKOFF` | `1` | Exponential retry base delay |
| `ENABLE_MEDIA_PROBE` | `true` | Enable optional ffprobe dimension checks |
| `MEDIA_PROBE_LIMIT` | `30` | Maximum declared-HD candidates for ffprobe |
| `ENABLE_PLAYBACK_PROBE` | `true` | Enable optional five-second ffmpeg decode sampling |
| `PLAYBACK_PROBE_LIMIT` | `12` | Maximum candidates for playback sampling (capped at 20) |

## Run locally

Requires Python 3.10+; core engine and unit tests use the standard library.

```bash
python generator.py
python -m unittest discover -s tests -v
```

Disable network checks:

```bash
CHECK_STREAMS=false python generator.py
```

Disable optional media probing:

```bash
ENABLE_MEDIA_PROBE=false python generator.py
```

## Validation semantics

- `online` means the HTTP request returned 2xx; it is not proof of playable video.
- `segment_ok` means an HLS manifest (and selected variant when present) plus one sample segment were reachable. It is not continuous playback validation.
- `resolution_verified_hd` requires ffprobe to report a video height of at least 720 pixels. It is not a bitrate or quality guarantee.
- `playback_verified` means ffmpeg decoded up to 30 frames from a five-second sample. It is not a continuous-playback or uptime guarantee.
- Declared HD is retained as metadata only.
- HTTP 401/403 is classified as restricted, 404/410 as offline, 429 as rate-limited, and 5xx as server error. Transient network errors are retried a bounded number of times.
- Health history is limited to the latest 14 snapshots; reliability scores are based on observed HLS segment validation.
- HLS or media probes can fail due to transient conditions, unsupported formats, provider policy, or geographic restrictions.

## Source and access policy

Discovery uses the public [iptv-org API](https://github.com/iptv-org/api) and the optional owner-reviewed `sources/registry.json`. See [sources/README.md](sources/README.md) for the provenance and authorization schema. Registry entries are not treated as authorized merely because they are reachable. Only publicly listed HTTP(S) feeds are probed. The engine does not bypass DRM, paywalls, logins, geo-controls, signed access controls or other restrictions. Public reachability does not automatically grant redistribution rights; only use feeds you are authorized to access.

## Automation

- Daily refresh: 01:17 UTC (09:17 WIB / 10:17 WITA).
- CI: Python compilation and unit tests on branch pushes and pull requests.
- Refresh workflow runs are separate from unit-test CI.
- For isolated live staging, open Actions → Refresh Indonesia IPTV → Run workflow and select `feature/aptron-iptv-engine-2`. The workflow checks out and pushes only to the selected branch. Scheduled runs continue to target `main`.

## Global football channel research

The football broadcast-rights catalogue remains separate in `sports/`. A rights-holder listing is not a public stream URL or proof that a channel is free-to-air. Only add playable endpoints after checking provenance and authorized access.
