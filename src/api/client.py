"""
POE Stash API client.
"""

import requests
import time
from .auth import AuthProvider


class PoEClient:
    """Client for interacting with the Path of Exile stash API."""
    
    BASE_URL = "https://www.pathofexile.com"

    def __init__(self, auth_provider: AuthProvider, account_name: str, league: str):
        self.auth_provider = auth_provider
        self.account_name = account_name
        self.league = league
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })

    def get_stash_tab_list(self):
        """
        Fetches the list of stash tabs (metadata only).
        Returns the 'tabs' metadata list from tab 0.
        """
        data = self.get_stash_items(0)
        if data and 'tabs' in data:
            return data['tabs']
        return []

    def get_stash_items(self, tab_index: int):
        """
        Fetches items from a specific stash tab index.
        """
        url = f"{self.BASE_URL}/character-window/get-stash-items"
        params = {
            "accountName": self.account_name,
            "league": self.league,
            "tabIndex": tab_index,
            "tabs": 1 
        }
        
        headers = self.auth_provider.get_headers()
        
        try:
            response = self.session.get(url, params=params, headers=headers)
            
            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", 60))
                print(f"Rate limited! Waiting {retry_after}s...")
                time.sleep(retry_after)
                response = self.session.get(url, params=params, headers=headers)

            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Error fetching stash tab {tab_index}: {e}")
            return None

    def get_first_stash_tab(self):
        return self.get_stash_items(0)

