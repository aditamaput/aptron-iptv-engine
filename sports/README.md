# Football broadcaster research catalogue

This directory records **official football broadcast-rights partners by competition and territory**. It is a research/discovery layer, not a playable IPTV playlist.

## Why rights are stored per competition

A broadcaster may hold Premier League rights but not UEFA Champions League rights in the same country. Rights also vary by season, territory, linear TV channel, and streaming service. Therefore, do not assume that a brand carries every competition or that a platform name is itself a linear TV channel.

## Current initial coverage

- Premier League: rights period 2025/26–2027/28, based on the Premier League's official announcement.
- UEFA Champions League: 2026/27, based on UEFA's official broadcaster directory.
- AFC competitions: selected 2025–2028 regional agreements (ESPN in Latin America/Caribbean; Sport 24 in-flight/on-ship).
- CAF AFCON 2027 qualifiers: matchday-specific regional and FTA broadcaster evidence; final tournament rights are tracked separately because CAF opened a media-rights tender.
- CAF Champions League 2025/26 final: one-off final distribution, not a full-season rights assumption.
- Concacaf club competitions: United States rights for 2027–2030.
- English Football League: official international partner directory.
- J.LEAGUE 2026/27: official international YouTube (up to four J1 matches per matchweek in eligible territories), plus selected territory partners.
- Roshn Saudi Pro League 2026/27: 45 international partners across 180+ territories; regional partner groups and the league's new 16-market direct-to-consumer model are separately qualified.
- A-League Men and Ninja A-League 2026/27: detailed official overseas directory, including SPOTV SEA in Indonesia and eligible-market official YouTube coverage.
- MLS 2026: Apple TV lists every match live; this is a paid streaming service, not a public IPTV feed.
- Coverage includes selected territories across Asia-Pacific, Europe, Africa/MENA, and the Americas. It is a starting index, not yet an exhaustive list of every country or domestic competition.

## Files

- [broadcasters.json](./broadcasters.json): machine-readable rights-partner catalogue.

## Rules before adding a stream

1. Confirm the exact linear channel or official streaming service and the specific competition/season.
2. Confirm that the feed is an official public stream or that its use/distribution is authorized.
3. Do not infer that a rights-holder brand provides a free public HLS endpoint.
4. Never bypass DRM, login, paywalls, or geo-restrictions.
5. Keep metadata quality separate from measured resolution and stream health.
6. Add a playable URL only after provenance, access conditions, and technical validation are documented.

## Official sources

- Premier League broadcast deals 2025–2028: https://www.premierleague.com/en/news/3703577/premier-league-broadcast-deals-for-2025-2028
- UEFA Champions League 2026/27 broadcast partners: https://www.uefa.com/news/0253-0d82037aaedd-f371c464f919-1000--where-to-watch-the-games/
- AFC and ESPN 2025–2028: https://www.the-afc.com/en/more/afc_news.html/news/afc-and-espn-renew-media-rights-agreement-in-latin-america-and-the-caribbean
- AFC and Sport 24 through 2028: https://www.the-afc.com/en/more/afc_news.html/news/afc-renews-broadcast-deal-with-sport-24-until-2028
- CAF AFCON 2027 qualifiers where to watch: https://www.cafonline.com/afcon2025/news/totalenergies-caf-africa-cup-of-nations-pamoja-2027-where-to-watch-matchday-1-of-the-qualifiers/
- CAF Champions League 2025/26 final broadcasters: https://www.cafonline.com/en/caf-champions-league/news/over-100-territories-to-broadcast-the-totalenergies-caf-champions-league-202526-finale-in-rabat-on-sunday-including-japan-and-china/
- Concacaf U.S. rights: https://www.concacaf.com/news/cbs-sports-secures-exclusive-u-s-english-language-rights-for-champions-cup-beginning-in-february
- EFL broadcast partners: https://www.efl.com/how-to-watch/broadcast-partners/
- J.LEAGUE rights directory: https://www.jleague.jp/corporate/activities/various_rights/
- J.LEAGUE overseas 2026/27 announcement: https://www.jleague.jp/corporate/en/pressrelease/article/16008
- Saudi Pro League where to watch: https://www.spl.com.sa/en/news/where-to-watch
- Saudi Pro League 16-market distribution model: https://www.spl.com.sa/en/news/spl-opens-new-route-to-international-fans-with-innovative-distribution-model
- A-Leagues international broadcast partners: https://aleagues.com.au/more/where-to-watch-aleagues-overseas/
- MLS how to watch: https://www.mlssoccer.com/how-to-watch/
- FIFA World Cup 2026 broadcast-partner information: https://www.fifa.com/en/ar/mens/worldcup/canadamexicousa2026/articles/where-to-watch-the-schedule-reveal-live-matches
