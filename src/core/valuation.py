"""
Price fetching and caching from poe.ninja.
"""

import requests
import json
import time
import os
from datetime import datetime, timedelta


class PriceCache:
    """Manages price data caching to reduce API calls."""
    
    def __init__(self, cache_file='price_cache.json', cache_duration_hours=4):
        self.cache_file = cache_file
        self.cache_duration = timedelta(hours=cache_duration_hours)

    def load(self):
        if not os.path.exists(self.cache_file):
            return None
        
        try:
            with open(self.cache_file, 'r') as f:
                data = json.load(f)
                
            timestamp = datetime.fromisoformat(data['timestamp'])
            if datetime.now() - timestamp > self.cache_duration:
                print("Cache expired.")
                return None
            
            return data
        except (json.JSONDecodeError, KeyError, ValueError):
            return None

    def save(self, prices, categories):
        data = {
            'timestamp': datetime.now().isoformat(),
            'prices': prices,
            'categories': categories
        }
        with open(self.cache_file, 'w') as f:
            json.dump(data, f)


class NinjaPriceFetcher:
    """Fetches item prices from poe.ninja API."""
    
    BASE_URL = "https://poe.ninja/api/data"
    
    ENDPOINTS = {
        'Currency': 'currencyoverview?type=Currency',
        'Fragment': 'currencyoverview?type=Fragment',
        'DivinationCard': 'itemoverview?type=DivinationCard',
        'UniqueWeapon': 'itemoverview?type=UniqueWeapon',
        'UniqueArmour': 'itemoverview?type=UniqueArmour',
        'UniqueAccessory': 'itemoverview?type=UniqueAccessory',
        'UniqueFlask': 'itemoverview?type=UniqueFlask',
        'UniqueJewel': 'itemoverview?type=UniqueJewel',
        'Invitation': 'itemoverview?type=Invitation', 
    }

    def __init__(self, league: str, cache: PriceCache = None):
        self.league = league
        self.cache = cache if cache else PriceCache()
        self.prices = {}
        self.categories = {}
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })

    def fetch_all_prices(self):
        """
        Fetches prices from all configured endpoints, using cache if available.
        """
        cached_data = self.cache.load()
        if cached_data and 'prices' in cached_data:
            print("Loaded prices from cache.")
            self.prices = cached_data['prices']
            self.categories = cached_data.get('categories', {})
            return

        print("Fetching fresh prices from poe.ninja...")
        all_prices = {}
        all_categories = {}
        
        for category, endpoint in self.ENDPOINTS.items():
            url = f"{self.BASE_URL}/{endpoint}&league={self.league}"
            try:
                time.sleep(1)
                
                response = self.session.get(url, verify=True)
                response.raise_for_status()
                data = response.json()
                
                lines = data.get('lines', [])
                
                for line in lines:
                    name = line.get('currencyTypeName') or line.get('name')
                    price = line.get('chaosEquivalent') or line.get('chaosValue')
                    
                    if name and price is not None:
                        all_prices[name] = price
                        all_categories[name] = category
                        
            except requests.exceptions.RequestException as e:
                print(f"Failed to fetch {category}: {e}")

        self.prices = all_prices
        self.categories = all_categories
        
        if self.prices.get('Chaos Orb', 0) == 0:
            self.prices['Chaos Orb'] = 1.0
            self.categories['Chaos Orb'] = 'Currency'
            
        self.cache.save(self.prices, self.categories)
        print(f"Fetched {len(self.prices)} prices.")

    def get_price(self, item_name: str) -> float:
        return self.prices.get(item_name, 0.0)

