# Curated public source registry

This registry is an optional extension point for sources that are not present in the iptv-org API. It is intentionally empty by default.

An entry is accepted only when all of these conditions are met:

- `access` is exactly `public`.
- `authorization` is exactly `approved` after repository-owner review.
- A public HTTP(S) stream URL is supplied.
- `source_url` is an HTTPS provenance page.
- Channel identity, source name, review date and review notes are present.

Example:

```json
{
  "schema_version": 1,
  "streams": [
    {
      "channel_id": "ExampleChannel.id",
      "channel_name": "Example Channel",
      "stream_url": "https://stream.example.org/live/index.m3u8",
      "title": "Official live stream",
      "quality": "1080p",
      "categories": ["news"],
      "source_name": "Example broadcaster",
      "source_url": "https://www.example.org/watch-live",
      "access": "public",
      "authorization": "approved",
      "reviewed_at": "2026-11-10",
      "review_notes": "Official broadcaster page identifies this public live feed."
    }
  ]
}
```

Do not add leaked feeds, credentialed endpoints, DRM-protected feeds, paywalled streams, geo-restricted endpoints, or URLs whose redistribution/use permission is unclear. Public reachability alone does not establish permission. Review each entry manually before setting `authorization` to `approved`.
