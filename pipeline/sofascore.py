"""SofaScore player data fetcher.

Uses curl_cffi to impersonate Chrome's TLS fingerprint, which is required to
bypass SofaScore's JA3/JA4 fingerprint-based blocking of server-side clients.

All results are cached in cache/sofascore/ so API calls are made only once per
player. The cache is a flat JSON file per player: sofascore_{ss_id}.json.

The mapping from Wyscout player IDs to SofaScore IDs is stored in
cache/sofascore/wyscout_to_sofascore.json.

Usage
-----
    from pipeline.sofascore import fetch_player, get_player_photo_b64

    profile = fetch_player(wyscout_id=1060411, name="Anmar Kiwarkis")
    # Returns dict with: ss_id, name, height, foot, shirt_number,
    #                    date_of_birth, nationality, position, photo_url

    photo_b64 = get_player_photo_b64(wyscout_id=1060411, name="Anmar Kiwarkis")
    # Returns "data:image/webp;base64,..." or None
"""

from __future__ import annotations

import base64
import json
import time
from pathlib import Path

_CACHE_DIR = Path(__file__).resolve().parents[1] / "cache" / "sofascore"
_MAPPING_FILE = _CACHE_DIR / "wyscout_to_sofascore.json"
_BASE = "https://api.sofascore.com/api/v1"
_HEADERS = {"Referer": "https://www.sofascore.com/", "Accept-Language": "en-US,en;q=0.9"}


def _session():
    """Return a curl_cffi session that impersonates Chrome."""
    try:
        from curl_cffi import requests as cf
    except ImportError as exc:
        raise ImportError(
            "curl_cffi is required for SofaScore fetching. "
            "Install it with: pip install curl-cffi"
        ) from exc
    s = cf.Session(impersonate="chrome120")
    s.headers.update(_HEADERS)
    return s


def _load_mapping() -> dict[int, int]:
    """Load the Wyscout ID → SofaScore ID mapping from cache."""
    if _MAPPING_FILE.exists():
        return {int(k): int(v) for k, v in json.loads(_MAPPING_FILE.read_text()).items()}
    return {}


def _save_mapping(mapping: dict[int, int]) -> None:
    _MAPPING_FILE.parent.mkdir(parents=True, exist_ok=True)
    _MAPPING_FILE.write_text(json.dumps({str(k): v for k, v in mapping.items()}, indent=2))


def _profile_path(ss_id: int) -> Path:
    return _CACHE_DIR / f"sofascore_{ss_id}.json"


def _search_ss_id(session, name: str) -> int | None:
    """Search SofaScore for a player by name and return their SS ID."""
    try:
        r = session.get(f"{_BASE}/search/all", params={"q": name}, timeout=10)
        r.raise_for_status()
        results = r.json().get("results", [])
        for res in results:
            if res.get("type") == "player":
                return int(res["entity"]["id"])
    except Exception as exc:
        print(f"  [sofascore] Search failed for '{name}': {exc}")
    return None


def _fetch_profile(session, ss_id: int) -> dict:
    """Fetch and return the raw player profile dict from SofaScore."""
    try:
        r = session.get(f"{_BASE}/player/{ss_id}", timeout=10)
        r.raise_for_status()
        return r.json().get("player", {})
    except Exception as exc:
        print(f"  [sofascore] Profile fetch failed for SS ID {ss_id}: {exc}")
        return {}


def _fetch_photo_bytes(session, ss_id: int) -> bytes | None:
    """Fetch raw photo bytes for a player. Returns None on failure."""
    try:
        r = session.get(f"{_BASE}/player/{ss_id}/image", timeout=10)
        if r.ok and len(r.content) > 1000:   # <1 KB = generic placeholder
            return r.content
    except Exception:
        pass
    return None


def _parse_profile(raw: dict, ss_id: int) -> dict:
    """Normalise a raw SofaScore player dict into our standard schema."""
    country = raw.get("country") or {}
    team = raw.get("team") or {}
    return {
        "ss_id":        ss_id,
        "name":         raw.get("name"),
        "short_name":   raw.get("shortName"),
        "height":       raw.get("height"),           # cm or None
        "foot":         raw.get("preferredFoot"),    # "Right" / "Left" / "Both" or None
        "shirt_number": raw.get("shirtNumber") or raw.get("jerseyNumber"),
        "date_of_birth": raw.get("dateOfBirth", "")[:10] or None,  # "YYYY-MM-DD"
        "nationality":  country.get("name"),
        "nationality_alpha2": country.get("alpha2"),
        "position":     raw.get("position"),
        "position_detailed": (raw.get("positionsDetailed") or [None])[0],
        "team_id":      team.get("id"),
        "team_name":    team.get("name"),
        "photo_content_type": None,   # filled in by fetch_player when photo is retrieved
        "photo_b64":    None,         # filled in by fetch_player when photo is retrieved
        "team_logo_b64": None,        # filled in by fetch_player when logo is retrieved
    }


def _team_logo_path(team_id: int) -> Path:
    return _CACHE_DIR / f"sofascore_team_{team_id}.json"


def _fetch_team_logo_bytes(session, team_id: int) -> bytes | None:
    """Fetch raw logo bytes for a team. Returns None on failure."""
    try:
        r = session.get(f"{_BASE}/team/{team_id}/image", timeout=10)
        if r.ok and len(r.content) > 500:
            return r.content
    except Exception:
        pass
    return None


def fetch_team_logo_b64(team_id: int) -> str | None:
    """Fetch (and cache) a team's logo as a base64 data URI.

    Returns a ``data:image/png;base64,…`` string, or None if unavailable.
    The result is cached at ``cache/sofascore/sofascore_team_{team_id}.json``.
    """
    if team_id is None:
        return None
    cache_path = _team_logo_path(team_id)
    if cache_path.exists():
        stored = json.loads(cache_path.read_text(encoding="utf-8"))
        return stored.get("logo_b64")

    session = _session()
    logo_bytes = _fetch_team_logo_bytes(session, team_id)
    logo_b64 = None
    if logo_bytes:
        ct = "image/png"
        logo_b64 = f"data:{ct};base64,{base64.b64encode(logo_bytes).decode()}"

    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps({"team_id": team_id, "logo_b64": logo_b64}, indent=2),
        encoding="utf-8",
    )
    return logo_b64


def fetch_player(
    wyscout_id: int,
    name: str,
    *,
    force_refresh: bool = False,
    delay: float = 0.4,
) -> dict:
    """Fetch and cache a player's SofaScore profile.

    Parameters
    ----------
    wyscout_id:
        Wyscout player ID — used as the stable cache key.
    name:
        Player's display name — used for the SofaScore name search.
    force_refresh:
        When True, ignore the on-disk cache and re-fetch from the API.
    delay:
        Seconds to sleep after each API call (rate-limit courtesy).

    Returns
    -------
    dict  Normalised profile with keys: ss_id, name, height, foot,
          shirt_number, date_of_birth, nationality, position, photo_b64.
          Any field unavailable from SofaScore is None.
    """
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    mapping = _load_mapping()

    # 1. Resolve SS ID (cached or via search)
    ss_id = mapping.get(wyscout_id)
    session = None

    if ss_id is None or force_refresh:
        session = _session()
        ss_id = _search_ss_id(session, name)
        time.sleep(delay)
        if ss_id is None:
            print(f"  [sofascore] Could not find '{name}' — returning empty profile.")
            return {"ss_id": None, "name": name, "height": None, "foot": None,
                    "shirt_number": None, "date_of_birth": None, "nationality": None,
                    "nationality_alpha2": None, "position": None, "position_detailed": None,
                    "team_name": None, "photo_content_type": None, "photo_b64": None}
        mapping[wyscout_id] = ss_id
        _save_mapping(mapping)

    cache_path = _profile_path(ss_id)

    # 2. Load from disk cache if fresh
    if cache_path.exists() and not force_refresh:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        # If team_id is missing the cache is from before that field was added — re-fetch.
        if cached.get("team_id") is None:
            force_refresh = True  # fall through to API fetch below
        else:
            # Backfill team_logo if logo cache exists but wasn't written to player cache.
            if not cached.get("team_logo_b64"):
                logo_cache = _team_logo_path(cached["team_id"])
                if logo_cache.exists():
                    cached["team_logo_b64"] = json.loads(logo_cache.read_text())["logo_b64"]
                    cache_path.write_text(
                        json.dumps(cached, indent=2, ensure_ascii=False), encoding="utf-8"
                    )
            return cached

    # 3. Fetch from API
    if session is None:
        session = _session()

    raw = _fetch_profile(session, ss_id)
    time.sleep(delay)

    profile = _parse_profile(raw, ss_id)

    # 4. Fetch player photo
    photo_bytes = _fetch_photo_bytes(session, ss_id)
    time.sleep(delay)
    if photo_bytes:
        ct = "image/webp"
        profile["photo_content_type"] = ct
        profile["photo_b64"] = f"data:{ct};base64,{base64.b64encode(photo_bytes).decode()}"

    # 5. Fetch team logo (cached separately per team)
    team_id = profile.get("team_id")
    if team_id:
        logo_cache = _team_logo_path(team_id)
        if logo_cache.exists():
            profile["team_logo_b64"] = json.loads(logo_cache.read_text())["logo_b64"]
        else:
            logo_bytes = _fetch_team_logo_bytes(session, team_id)
            time.sleep(delay)
            logo_b64 = None
            if logo_bytes:
                logo_b64 = f"data:image/png;base64,{base64.b64encode(logo_bytes).decode()}"
            logo_cache.write_text(
                json.dumps({"team_id": team_id, "logo_b64": logo_b64}, indent=2),
                encoding="utf-8",
            )
            profile["team_logo_b64"] = logo_b64

    cache_path.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")
    return profile


def fetch_squad(
    players: list[dict[str, object]],
    *,
    force_refresh: bool = False,
    delay: float = 0.5,
) -> dict[int, dict]:
    """Fetch SofaScore profiles for a list of players.

    Parameters
    ----------
    players:
        List of dicts, each with keys ``wyscout_id`` (int) and ``name`` (str).
    force_refresh:
        Re-fetch even if already cached.
    delay:
        Per-request delay in seconds.

    Returns
    -------
    dict  Mapping wyscout_id → profile dict.
    """
    results: dict[int, dict] = {}
    for i, p in enumerate(players, 1):
        wy_id = int(p["wyscout_id"])
        name  = str(p["name"])
        print(f"  [{i}/{len(players)}] {name} (wyId={wy_id})")
        results[wy_id] = fetch_player(wy_id, name,
                                      force_refresh=force_refresh, delay=delay)
    return results


def get_player_photo_b64(wyscout_id: int, name: str) -> str | None:
    """Return a base64 data URI for the player's photo, or None if unavailable."""
    profile = fetch_player(wyscout_id, name)
    return profile.get("photo_b64")
