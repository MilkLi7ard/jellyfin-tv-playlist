#!/usr/bin/env python3
"""
Jellyfin Interleaved Show Playlist Builder
Creates a playlist that interleaves episodes across selected shows,
season by season, until all episodes are exhausted.
"""

import requests
import json
from itertools import zip_longest

# ─── CONFIG ────────────────────────────────────────────────────────────────────
JELLYFIN_URL = "http://localhost:8096"   # Change if using different port
API_KEY      = "YOUR_API_KEY_HERE"       # Jellyfin Dashboard → API Keys
USER_ID      = "YOUR_USER_ID_HERE"       # Jellyfin Dashboard → Users → click user → copy ID from URL
# ───────────────────────────────────────────────────────────────────────────────

HEADERS = {
    "X-Emby-Token": API_KEY,
    "Content-Type": "application/json",
    "Accept": "application/json",
}

def get(path, **params):
    r = requests.get(f"{JELLYFIN_URL}{path}", headers=HEADERS, params=params)
    r.raise_for_status()
    return r.json()

def post(path, body):
    r = requests.post(f"{JELLYFIN_URL}{path}", headers=HEADERS, json=body)
    r.raise_for_status()
    return r.json()

def post_empty(path, **params):
    r = requests.post(f"{JELLYFIN_URL}{path}", headers=HEADERS, params=params)
    r.raise_for_status()
    return r.json()

# 1. Fetch all TV series from both libraries
def get_all_series():
    data = get(
        "/Items",
        userId=USER_ID,
        IncludeItemTypes="Series",
        Recursive=True,
        Fields="Id,Name,Path",
        SortBy="SortName",
        SortOrder="Ascending",
        Limit=500,
    )
    return data.get("Items", [])

# 2. Get all episodes for a series, sorted by season + episode number
def get_episodes(series_id):
    data = get(
        "/Items",
        userId=USER_ID,
        ParentId=series_id,
        IncludeItemTypes="Episode",
        Recursive=True,
        Fields="Id,Name,ParentIndexNumber,IndexNumber,SeasonName",
        SortBy="ParentIndexNumber,IndexNumber",
        SortOrder="Ascending",
        Limit=2000,
    )
    episodes = data.get("Items", [])
    # Filter out specials (Season 0)
    return [e for e in episodes if e.get("ParentIndexNumber", 0) > 0]

# 3. Group episodes by season
def group_by_season(episodes):
    seasons = {}
    for ep in episodes:
        s = ep.get("ParentIndexNumber", 1)
        seasons.setdefault(s, []).append(ep)
    return dict(sorted(seasons.items()))

# 4. Interactive show picker
def pick_shows(all_series):
    print("\n📺 Available Shows:\n")
    for i, s in enumerate(all_series):
        print(f"  [{i+1:>3}] {s['Name']}")

    print("\nEnter show numbers separated by commas (e.g. 1,5,12):")
    raw = input("> ").strip()
    indices = [int(x.strip()) - 1 for x in raw.split(",") if x.strip().isdigit()]
    selected = [all_series[i] for i in indices if 0 <= i < len(all_series)]

    print(f"\n✅ Selected {len(selected)} show(s):")
    for s in selected:
        print(f"   • {s['Name']}")
    return selected

# 5. Build interleaved episode ID list
def build_interleaved_list(selected_shows):
    # Collect episodes per show
    show_seasons = {}
    for show in selected_shows:
        eps = get_episodes(show["Id"])
        show_seasons[show["Name"]] = group_by_season(eps)
        print(f"  📂 {show['Name']}: {len(eps)} episodes across {len(show_seasons[show['Name']])} season(s)")

    # Find the max number of seasons across all shows
    max_seasons = max(len(v) for v in show_seasons.values()) if show_seasons else 0

    ordered_ids = []

    for season_num in range(1, max_seasons + 1):
        # Gather this season's episode lists from each show (empty list if show lacks this season)
        season_episode_lists = []
        for show in selected_shows:
            show_name = show["Name"]
            seasons = show_seasons[show_name]
            season_eps = seasons.get(season_num, [])
            if season_eps:
                season_episode_lists.append(season_eps)

        if not season_episode_lists:
            continue

        # Interleave: one episode per show at a time, cycling through all shows
        for ep_tuple in zip_longest(*season_episode_lists):
            for ep in ep_tuple:
                if ep is not None:
                    ordered_ids.append(ep["Id"])

    return ordered_ids

# 6. Create the playlist and populate it
def create_playlist(name, episode_ids):
    print(f"\n🎬 Creating playlist '{name}' with {len(episode_ids)} episodes...")

    # Create empty playlist
    result = post("/Playlists", {
        "Name": name,
        "UserId": USER_ID,
        "MediaType": "Video",
        "Ids": [],
    })
    playlist_id = result["Id"]
    print(f"  ✅ Playlist created (ID: {playlist_id})")

    # Add episodes in batches of 100 (API limit)
    batch_size = 100
    for i in range(0, len(episode_ids), batch_size):
        batch = episode_ids[i:i + batch_size]
        ids_param = ",".join(batch)
        post_empty(f"/Playlists/{playlist_id}/Items", userId=USER_ID, ids=ids_param)
        print(f"  ➕ Added episodes {i+1}–{min(i+batch_size, len(episode_ids))}")

    print(f"\n🎉 Done! Open Jellyfin and find your playlist: '{name}'")
    return playlist_id

# ─── MAIN ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("🔌 Connecting to Jellyfin at", JELLYFIN_URL)
    all_series = get_all_series()
    print(f"   Found {len(all_series)} series across all libraries.")

    selected = pick_shows(all_series)
    if not selected:
        print("No shows selected. Exiting.")
        exit(1)

    default_name = " × ".join(s["Name"] for s in selected[:3])
    if len(selected) > 3:
        default_name += " × ..."
    print(f"\nPlaylist name? (default: '{default_name}')")
    name_input = input("> ").strip()
    playlist_name = name_input if name_input else default_name

    episode_ids = build_interleaved_list(selected)
    print(f"\n📋 Total interleaved episodes: {len(episode_ids)}")

    create_playlist(playlist_name, episode_ids)
