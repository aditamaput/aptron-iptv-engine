# APTRON IPTV ENGINE

Automatic discovery, stream reachability checks, HD prioritization and daily M3U generation for Indonesian TV channels.

## What it does

- Pulls channel, stream, logo and blocklist metadata from the public iptv-org API.
- Filters Indonesian channels (ISO country code `ID`), closed channels, NSFW entries and DMCA/NSFW blocklisted channel IDs.
- Checks public HTTP(S) stream URLs for basic reachability.
- Prioritizes streams declared as 720p, 1080p or 2160p.
- Publishes four playlists and a JSON health report.

## Permanent playlist URLs

After the first successful GitHub Actions run:

- All candidates: [indonesia-all.m3u](https://raw.githubusercontent.com/aditamaput/aptron-iptv-engine/main/playlists/indonesia-all.m3u)
- HD candidates: [indonesia-hd.m3u](https://raw.githubusercontent.com/aditamaput/aptron-iptv-engine/main/playlists/indonesia-hd.m3u)
- HTTP reachable: [indonesia-online.m3u](https://raw.githubusercontent.com/aditamaput/aptron-iptv-engine/main/playlists/indonesia-online.m3u)
- Reachable HD: [indonesia-online-hd.m3u](https://raw.githubusercontent.com/aditamaput/aptron-iptv-engine/main/playlists/indonesia-online-hd.m3u)
- Health report: [health.json](https://raw.githubusercontent.com/aditamaput/aptron-iptv-engine/main/reports/health.json)

Use `indonesia-online-hd.m3u` first. If a stream is missing because its server rejects automated probes, try `indonesia-hd.m3u`.

## Daily refresh

GitHub Actions runs at 01:17 UTC daily (09:17 WIB / 10:17 WITA), and can also be started manually from the Actions tab.

## Run locally

Requires Python 3.10+ and no third-party packages:

```bash
python generator.py
```

Disable stream probes:

```bash
CHECK_STREAMS=false python generator.py
```

## Important limitations

- The source API documents channel metadata, stream URLs, declared quality, headers, labels and EPG guide references. See [iptv-org/api](https://github.com/iptv-org/api).
- "HD" is based on the source's declared quality/title; the engine does not measure bitrate or decode video to certify actual resolution.
- HTTP 2xx is only a reachability signal. It does not guarantee all HLS segments work, that the stream is available in Indonesia, or that every IPTV app can play it.
- This engine collects publicly listed HTTP(S) feeds. It does not bypass DRM, paywalls, login, geo-controls or other access restrictions, and excludes IDs on the source's DMCA/NSFW blocklist.
- A daily schedule is not an uptime guarantee; GitHub Actions can delay scheduled runs. Playlist links remain stable, but contents update only after a successful run and commit.
- Only use streams you are authorized to access. Publicly reachable does not automatically mean licensed for every use.

## Data sources

- Channels: https://iptv-org.github.io/api/channels.json
- Streams: https://iptv-org.github.io/api/streams.json
- Logos: https://iptv-org.github.io/api/logos.json
- Blocklist: https://iptv-org.github.io/api/blocklist.json
