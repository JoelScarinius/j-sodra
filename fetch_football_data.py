import os
import requests
import pandas as pd
from dotenv import load_dotenv

# Load credentials
load_dotenv()
CLIENTID = os.getenv("CLIENTID")
CLIENTSECRET = os.getenv("CLIENTSECRET")
AUTH = (CLIENTID, CLIENTSECRET)

BASE_URL = "https://apirest.wyscout.com/v3"

def fetch_api(endpoint, params=None):
    """Helper function to fetch data from the Wyscout API."""
    url = f"{BASE_URL}{endpoint}"
    response = requests.get(url, auth=AUTH, params=params)
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Error {response.status_code} fetching {url}: {response.text}")
        return None

def main():
    print("🚀 Starting Wyscout Data Extraction...")

    # =========================================================
    # 1. FIND JÖNKÖPING SÖDRA & THEIR MATCHES (INCLUDING FRIENDLIES)
    # =========================================================
    print("\n🔍 Searching for Jönköpings Södra...")
    # Using partial search for best matches
    teams_search = fetch_api("/search", {"query": "Jonkopings", "objType": "team"})
    
    jsodra_id = None
    if teams_search and isinstance(teams_search, list) and len(teams_search) > 0:
        team = teams_search[0]
        jsodra_id = team.get("wyId")
        print(f"✅ Found Team: {team.get('name')} (ID: {jsodra_id})")
    elif teams_search and isinstance(teams_search, dict) and "teams" in teams_search:
        # Fallback in case the API wraps it in an object
        team = teams_search["teams"][0]
        jsodra_id = team.get("wyId")
        print(f"✅ Found Team: {team.get('name')} (ID: {jsodra_id})")
    
    if jsodra_id:
        print(f"📅 Fetching matches for J-Södra...")
        # Get matches for the team. Wyscout usually records training/friendly matches here too!
        js_matches_data = fetch_api(f"/teams/{jsodra_id}/matches")
        
        js_matches = js_matches_data if isinstance(js_matches_data, list) else js_matches_data.get('matches', [])
        
        if js_matches:
            df_jsodra = pd.DataFrame(js_matches)
            df_jsodra.to_csv("jsodra_matches.csv", index=False)
            print(f"💾 Saved {len(df_jsodra)} J-Södra matches to 'jsodra_matches.csv'")
            
            # --- THE "COOL WAY" TO GET EVENTS ---
            # Let's extract all the events (passes, shots, fouls) for their MOST RECENT game!
            latest_match_id = df_jsodra.iloc[0].get("wyId") or df_jsodra.iloc[0].get("matchId")
            if latest_match_id:
                print(f"\n⚡ Fetching EVENT DATA for the latest Match (ID: {latest_match_id})")
                events_data = fetch_api(f"/matches/{latest_match_id}/events")
                
                events = events_data if isinstance(events_data, list) else events_data.get('events', [])
                if events:
                    df_events = pd.DataFrame(events)
                    # We normalize the data (flatten nested JSON) so it looks beautiful in Excel/CSV
                    df_events_normalized = pd.json_normalize(events)
                    event_filename = f"match_{latest_match_id}_events.csv"
                    df_events_normalized.to_csv(event_filename, index=False)
                    print(f"💾 Saved {len(events)} match events to '{event_filename}'")
                    print(f"   Now you can analyze every pass and timeline in Python/Excel!")

    # =========================================================
    # 2. GET SUPERETTAN & DIVISION 1 DATA
    # =========================================================
    print("\n🔍 Searching for Superettan and Division 1...")
    
    # Let's look up competitions in Sweden (Area ID for Sweden is often SWE or a specific wyId)
    # We can fetch via search to find the competition ID directly.
    competitions = ["Superettan", "Ettan"] # "Ettan Södra/Norra" is Div 1
    
    for comp_name in competitions:
        search_res = fetch_api("/search", {"query": comp_name, "objType": "competition"})
        
        comp_list = search_res if isinstance(search_res, list) else search_res.get('competitions', [])
        if comp_list:
            # Get the first matching competition
            comp_id = comp_list[0].get("wyId")
            print(f"✅ Found {comp_name} (ID: {comp_id})")
            
            # Fetch matches for this competition
            comp_matches_data = fetch_api(f"/competitions/{comp_id}/matches")
            comp_matches = comp_matches_data if isinstance(comp_matches_data, list) else comp_matches_data.get('matches', [])
            
            if comp_matches:
                df_comp = pd.DataFrame(comp_matches)
                filename = f"{comp_name.lower()}_matches.csv"
                df_comp.to_csv(filename, index=False)
                print(f"💾 Saved {len(df_comp)} {comp_name} matches to '{filename}'")

    print("\n🎉 All Done! Let the data analysis begin.")

if __name__ == "__main__":
    main()
