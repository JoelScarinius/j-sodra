# Player Analysis — To Do

## xAssist per key pass (for assist map arrow sizing)

**What:** Size each arrow in the assist map by the xA value of that pass, the
same way shot map arrows are sized by xG.

**Why it's not done yet:** xAssist does not exist as a field in the raw event
data (`cache/events/match_*.json`). The pass event only carries location and
recipient — it has no xA attached to it. xA does exist in the aggregated
advanced stats (`average.xgAssist`, `total.xgAssist` in
`player_<id>_advancedstats_comp810.json`), but only as a season total, not
per pass.

**How to implement it:** Each key-pass/assist event has a `relatedEventId`
field that points to the shot that immediately followed it. To get xA per
pass:

1. In `load_player_key_passes` (metrics.py), after collecting a key-pass row,
   look up the related event by `relatedEventId` within the same match file.
2. Read `shot.xg` from that related shot event — this is the xG of the
   chance created, which is equivalent to xA for that pass.
3. Store it as a new `xa` column in the returned DataFrame.

Then in `build_player_assist_map` (plots.py), scale arrow width or marker
size by `xa` the same way `_size(df)` uses `xg` in the shot map.

**Caveat:** `relatedEventId` is not always present (e.g. second assists link
to the direct assist, not the shot), so fall back to a fixed size when `xa`
is missing.
