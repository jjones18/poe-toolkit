"""
Dust data fetching and calculations for Kalguur Dust tool.

Fetches unique item dust values and calculates efficiency metrics.
Data sources:
- Dust values: PoEDB unique item data
- Prices: poe.ninja via existing NinjaPriceFetcher
"""

import json
import os
import time
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple


class DustDataCache:
    """Manages caching of dust data to reduce API calls."""
    
    def __init__(self, cache_file: str = None, cache_duration_hours: int = 24):
        if cache_file is None:
            # Store in project root config area
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
            cache_file = os.path.join(project_root, "dust_cache.json")
        
        self.cache_file = cache_file
        self.cache_duration = timedelta(hours=cache_duration_hours)
    
    def load(self) -> Optional[dict]:
        """Load cached dust data if valid."""
        if not os.path.exists(self.cache_file):
            return None
        
        try:
            with open(self.cache_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            timestamp = datetime.fromisoformat(data.get('timestamp', '2000-01-01'))
            if datetime.now() - timestamp > self.cache_duration:
                print("Dust cache expired.")
                return None
            
            return data
        except (json.JSONDecodeError, KeyError, ValueError, OSError) as e:
            print(f"Error loading dust cache: {e}")
            return None
    
    def save(self, dust_data: dict):
        """Save dust data to cache."""
        data = {
            'timestamp': datetime.now().isoformat(),
            'dust_values': dust_data
        }
        try:
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
        except OSError as e:
            print(f"Error saving dust cache: {e}")


class DustCalculator:
    """
    Calculates Thaumaturgic Dust values for unique items.
    
    Dust formula (based on game mechanics):
    - Base dust depends on item type and tier
    - ilvl affects dust: higher ilvl = more dust (up to ilvl 84 cap)
    - Quality adds bonus: (1 + quality/100) multiplier for armor/weapons
    """
    
    # Item type categories that benefit from quality
    QUALITY_ITEM_TYPES = {
        'armour', 'weapon', 'body armour', 'helmet', 'gloves', 'boots', 
        'shield', 'bow', 'staff', 'wand', 'sword', 'axe', 'mace', 
        'dagger', 'claw', 'sceptre', 'quiver'
    }
    
    # Base dust values by unique item tier (approximated from game data)
    # These will be overridden by actual PoEDB data when available
    TIER_BASE_DUST = {
        1: 5,    # Common uniques
        2: 15,   # Uncommon uniques
        3: 50,   # Rare uniques
        4: 150,  # Very rare uniques
        5: 500,  # Ultra rare uniques
    }
    
    # ilvl multiplier curve (dust increases with ilvl up to 84)
    @staticmethod
    def get_ilvl_multiplier(ilvl: int) -> float:
        """Get dust multiplier based on item level."""
        if ilvl >= 84:
            return 1.0
        elif ilvl >= 75:
            return 0.85 + (ilvl - 75) * 0.0167  # Linear scale to 1.0 at 84
        elif ilvl >= 60:
            return 0.6 + (ilvl - 60) * 0.0167   # Linear scale to 0.85 at 75
        elif ilvl >= 1:
            return 0.2 + (ilvl - 1) * 0.0068    # Linear scale to 0.6 at 60
        return 0.2
    
    @staticmethod
    def get_quality_multiplier(quality: int, item_type: str) -> float:
        """Get dust multiplier based on quality."""
        # Only armor and weapons benefit from quality
        item_type_lower = item_type.lower()
        qualifies = any(qt in item_type_lower for qt in DustCalculator.QUALITY_ITEM_TYPES)
        
        if qualifies and quality > 0:
            return 1.0 + (quality / 100.0)
        return 1.0
    
    @staticmethod
    def calculate_dust(base_dust: int, ilvl: int = 84, quality: int = 0, 
                       item_type: str = "", corrupted: bool = False) -> int:
        """
        Calculate actual dust value for an item.
        
        Args:
            base_dust: Base dust value for this unique
            ilvl: Item level (capped at 84)
            quality: Item quality percentage
            item_type: Item type for quality bonus check
            corrupted: Whether item is corrupted (affects quality calculation)
        
        Returns:
            Calculated dust value
        """
        # Apply ilvl multiplier
        ilvl_mult = DustCalculator.get_ilvl_multiplier(min(ilvl, 84))
        
        # For non-corrupted items, assume we'll quality to 20
        # For corrupted items, use actual quality
        effective_quality = quality if corrupted else 20
        quality_mult = DustCalculator.get_quality_multiplier(effective_quality, item_type)
        
        return int(base_dust * ilvl_mult * quality_mult)


class DustDataFetcher:
    """
    Fetches and manages dust data for unique items.
    
    Strategy:
    1. Fetch ALL uniques from poe.ninja (same source we use for prices)
    2. Calculate dust value based on item type using known formulas
    3. Cache results
    """
    
    # poe.ninja unique item endpoints
    NINJA_BASE_URL = "https://poe.ninja/api/data"
    NINJA_UNIQUE_ENDPOINTS = {
        'UniqueWeapon': 'itemoverview?type=UniqueWeapon',
        'UniqueArmour': 'itemoverview?type=UniqueArmour',
        'UniqueAccessory': 'itemoverview?type=UniqueAccessory',
        'UniqueFlask': 'itemoverview?type=UniqueFlask',
        'UniqueJewel': 'itemoverview?type=UniqueJewel',
    }
    
    # Base dust values by item category (estimated from poedust.com data)
    # These are ilvl 84, quality 0 values
    BASE_DUST_BY_TYPE = {
        # Armour pieces - benefit from quality
        'Body Armour': 15,
        'Helmet': 10,
        'Gloves': 8,
        'Boots': 8,
        'Shield': 10,
        
        # Weapons - benefit from quality  
        'One Handed Sword': 8,
        'Two Handed Sword': 12,
        'One Handed Axe': 8,
        'Two Handed Axe': 12,
        'One Handed Mace': 8,
        'Two Handed Mace': 12,
        'Bow': 12,
        'Staff': 12,
        'Warstaff': 12,
        'Wand': 6,
        'Sceptre': 8,
        'Dagger': 6,
        'Rune Dagger': 6,
        'Claw': 6,
        
        # Accessories - no quality bonus
        'Amulet': 8,
        'Ring': 5,
        'Belt': 8,
        'Quiver': 8,
        
        # Flasks - no quality bonus for dust
        'Flask': 10,
        
        # Jewels
        'Jewel': 5,
        'Abyss Jewel': 5,
        'Cluster Jewel': 8,
    }
    
    def __init__(self, league: str, cache: DustDataCache = None):
        self.league = league
        self.cache = cache if cache else DustDataCache()
        self.dust_values: Dict[str, dict] = {}  # name -> {base_dust, item_type, tier}
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
    
    def fetch_dust_data(self) -> bool:
        """
        Load dust values from poedust cache file or cache.
        
        Returns:
            True if data was loaded successfully
        """
        # Try our cache first
        cached = self.cache.load()
        if cached and 'dust_values' in cached and len(cached['dust_values']) > 100:
            self.dust_values = cached['dust_values']
            print(f"[DustData] Loaded {len(self.dust_values)} dust values from cache.")
            return True
        
        # Try loading from poedust cache file (scraped data)
        print("[DustData] Loading dust values from poedust cache...")
        if self._load_poedust_cache():
            print(f"[DustData] SUCCESS: Loaded {len(self.dust_values)} items from poedust cache")
            self.cache.save(self.dust_values)
            return True
        
        # Fallback: try poe.ninja calculation
        print("[DustData] Poedust cache not found, trying poe.ninja...")
        if self._fetch_from_ninja():
            print(f"[DustData] SUCCESS: Loaded {len(self.dust_values)} items from poe.ninja")
            self.cache.save(self.dust_values)
            return True
        
        # Last resort: built-in estimates
        print("[DustData] WARNING: Using built-in estimates")
        self._load_builtin_estimates()
        print(f"[DustData] Loaded {len(self.dust_values)} built-in estimates")
        return len(self.dust_values) > 0
    
    def _load_poedust_cache(self) -> bool:
        """Load dust data from GitHub gist or local cache."""
        # Try fetching from GitHub gist first (most up-to-date)
        gist_url = "https://gist.githubusercontent.com/alserom/22bdd4106806cbd4f85a5cb8c4345c08/raw/poe-dust.csv"
        
        try:
            print(f"[DustData] Fetching from GitHub gist...")
            response = self.session.get(gist_url, timeout=30)
            
            if response.status_code == 200:
                import csv
                from io import StringIO
                
                reader = csv.DictReader(StringIO(response.text))
                for row in reader:
                    name = row.get('name', '')
                    if not name:
                        continue
                    
                    self.dust_values[name] = {
                        'base_dust': int(row.get('dustValIlvl84', 0) or 0),
                        'dust_ilvl84': int(row.get('dustValIlvl84', 0) or 0),
                        'dust_ilvl84_q20': int(row.get('dustValIlvl84Q20', 0) or 0),
                        'item_type': 'unknown',
                        'base_type': row.get('baseType', ''),
                    }
                
                if len(self.dust_values) > 100:
                    print(f"[DustData] Loaded {len(self.dust_values)} items from gist")
                    return True
        except Exception as e:
            print(f"[DustData] Gist fetch failed: {e}")
        
        # Fallback: try local cache file
        cache_paths = [
            os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'data', 'poedust_cache.json'),
            os.path.join(os.path.dirname(__file__), '..', '..', '..', 'data', 'poedust_cache.json'),
            'data/poedust_cache.json',
        ]
        
        for cache_path in cache_paths:
            try:
                abs_path = os.path.abspath(cache_path)
                if os.path.exists(abs_path):
                    print(f"[DustData] Found local cache at: {abs_path}")
                    with open(abs_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    
                    items = data.get('items', {})
                    for name, values in items.items():
                        self.dust_values[name] = {
                            'base_dust': values.get('dust_ilvl84', 0),
                            'dust_ilvl84': values.get('dust_ilvl84', 0),
                            'dust_ilvl84_q20': values.get('dust_ilvl84_q20', 0),
                            'item_type': 'unknown',
                            'base_type': '',
                        }
                    
                    return len(self.dust_values) > 50
            except Exception as e:
                print(f"[DustData] Error loading {cache_path}: {e}")
        
        return False
    
    def _fetch_from_ninja(self) -> bool:
        """Fetch all unique items from poe.ninja and calculate dust values."""
        ninja_endpoints = {
            'UniqueWeapon': 'itemoverview?type=UniqueWeapon',
            'UniqueArmour': 'itemoverview?type=UniqueArmour',
            'UniqueAccessory': 'itemoverview?type=UniqueAccessory',
            'UniqueFlask': 'itemoverview?type=UniqueFlask',
            'UniqueJewel': 'itemoverview?type=UniqueJewel',
        }
        
        total_items = 0
        base_url = "https://poe.ninja/api/data"
        
        for category, endpoint in ninja_endpoints.items():
            try:
                url = f"{base_url}/{endpoint}&league={self.league}"
                print(f"[DustData] Fetching {category}...")
                
                response = self.session.get(url, timeout=30)
                if response.status_code != 200:
                    print(f"[DustData] Failed {category}: HTTP {response.status_code}")
                    continue
                
                data = response.json()
                lines = data.get('lines', [])
                
                for item in lines:
                    name = item.get('name', '')
                    if not name:
                        continue
                    
                    base_type = item.get('baseType', '')
                    item_type = self._get_item_type(base_type, category)
                    base_dust = self.BASE_DUST_BY_TYPE.get(item_type, 5)
                    
                    # 6-link items give more dust
                    if item.get('links', 0) >= 6:
                        base_dust = int(base_dust * 1.5)
                    
                    has_quality = item_type in [
                        'Body Armour', 'Helmet', 'Gloves', 'Boots', 'Shield',
                        'One Handed Sword', 'Two Handed Sword', 'One Handed Axe', 
                        'Two Handed Axe', 'One Handed Mace', 'Two Handed Mace', 
                        'Bow', 'Staff', 'Warstaff', 'Wand', 'Sceptre', 'Dagger', 'Claw'
                    ]
                    
                    self.dust_values[name] = {
                        'base_dust': base_dust,
                        'dust_ilvl84': base_dust,
                        'dust_ilvl84_q20': int(base_dust * 1.2) if has_quality else base_dust,
                        'item_type': item_type,
                        'base_type': base_type,
                    }
                    total_items += 1
                
                print(f"[DustData] {category}: {len(lines)} items")
                
            except Exception as e:
                print(f"[DustData] Error {category}: {e}")
        
        return total_items > 100
    
    def _get_item_type(self, base_type: str, category: str) -> str:
        """Determine item type from base type string."""
        b = base_type.lower()
        
        # Armour
        if any(x in b for x in ['robe', 'vest', 'plate', 'coat', 'garb', 'regalia', 
                                'vestment', 'wrap', 'tunic', 'brigandine', 'doublet',
                                'hauberk', 'lamellar', 'chainmail', 'ringmail', 'silks']):
            return 'Body Armour'
        if any(x in b for x in ['helmet', 'hat', 'cap', 'mask', 'circlet', 'crown',
                                'hood', 'burgonet', 'bascinet', 'sallet', 'coif', 'cage']):
            return 'Helmet'
        if any(x in b for x in ['gloves', 'gauntlets', 'mitts', 'bracers']):
            return 'Gloves'
        if any(x in b for x in ['boots', 'greaves', 'slippers', 'shoes']):
            return 'Boots'
        if any(x in b for x in ['shield', 'buckler']):
            return 'Shield'
        
        # Weapons
        if category == 'UniqueWeapon':
            if 'bow' in b: return 'Bow'
            if 'staff' in b: return 'Staff'
            if 'wand' in b: return 'Wand'
            if 'sceptre' in b: return 'Sceptre'
            if 'dagger' in b or 'knife' in b: return 'Dagger'
            if 'claw' in b: return 'Claw'
            if 'sword' in b or 'rapier' in b or 'foil' in b:
                return 'Two Handed Sword' if 'zwei' in b or 'great' in b else 'One Handed Sword'
            if 'axe' in b:
                return 'Two Handed Axe' if 'labrys' in b or 'great' in b else 'One Handed Axe'
            if 'mace' in b or 'maul' in b or 'hammer' in b:
                return 'Two Handed Mace' if 'maul' in b else 'One Handed Mace'
        
        # Accessories
        if category == 'UniqueAccessory':
            if 'amulet' in b or 'talisman' in b: return 'Amulet'
            if 'ring' in b: return 'Ring'
            if 'belt' in b or 'sash' in b or 'stygian' in b: return 'Belt'
            if 'quiver' in b: return 'Quiver'
        
        if category == 'UniqueFlask': return 'Flask'
        if category == 'UniqueJewel':
            if 'cluster' in b: return 'Cluster Jewel'
            if 'abyss' in b: return 'Abyss Jewel'
            return 'Jewel'
        
        return 'Unknown'
    
    def _fetch_from_poedust(self) -> bool:
        """Try to fetch data from poedust.com or related sources."""
        # Try multiple potential data sources
        sources = [
            # PoEDB unique items export (if available)
            "https://poedb.tw/us/export/uniques.json",
            # Community data repos
            "https://raw.githubusercontent.com/ayberkgezer/poe-dust-api/main/data.json",
            "https://raw.githubusercontent.com/5k-mirrors/misc-poe-tools/master/data/dust.json",
        ]
        
        for url in sources:
            try:
                print(f"[DustData] Trying: {url}")
                response = self.session.get(url, timeout=15)
                
                if response.status_code == 200:
                    data = response.json()
                    self._parse_poedust_data(data)
                    if len(self.dust_values) > 50:
                        print(f"[DustData] SUCCESS from {url}: {len(self.dust_values)} items")
                        return True
            except Exception as e:
                print(f"[DustData] Failed {url}: {e}")
        
        return False
    
    def _parse_poedust_data(self, data: dict):
        """Parse data from poedust API format."""
        items = data if isinstance(data, list) else data.get('items', [])
        
        for item in items:
            name = item.get('name', '')
            if not name:
                continue
            
            self.dust_values[name] = {
                'base_dust': item.get('dust', item.get('baseDust', 0)),
                'dust_ilvl84': item.get('dustIlvl84', item.get('dust', 0)),
                'dust_ilvl84_q20': item.get('dustIlvl84Q20', item.get('dustQ20', 0)),
                'item_type': item.get('itemType', item.get('type', '')),
                'base_type': item.get('baseType', ''),
            }
    
    def _fetch_from_poedb(self) -> bool:
        """Try to fetch data from PoEDB."""
        try:
            # PoEDB doesn't have a public API, but we can try common endpoints
            # This is a placeholder for when/if PoEDB provides data
            response = self.session.get(
                "https://poedb.tw/us/Unique",
                timeout=30
            )
            
            if response.status_code == 200:
                # Would need HTML parsing here
                # For now, return False to use fallback
                pass
        except Exception as e:
            print(f"Failed to fetch from PoEDB: {e}")
        
        return False
    
    def _load_builtin_estimates(self):
        """Load built-in estimated dust values for common uniques."""
        # Comprehensive list of uniques with estimated dust values
        # Values are approximations - actual dust depends on ilvl and quality
        # Format: name -> (base_dust_ilvl84, item_type)
        builtin = {
            # === HELMETS ===
            "Goldrim": (5, "Helmet"),
            "Abyssus": (15, "Helmet"),
            "Alpha's Howl": (20, "Helmet"),
            "Devoto's Devotion": (18, "Helmet"),
            "Rat's Nest": (12, "Helmet"),
            "Starkonja's Head": (15, "Helmet"),
            "The Baron": (10, "Helmet"),
            "The Brine Crown": (8, "Helmet"),
            "Crown of the Inward Eye": (25, "Helmet"),
            "Fractal Thoughts": (20, "Helmet"),
            
            # === BODY ARMOUR ===
            "Tabula Rasa": (8, "Body Armour"),
            "Belly of the Beast": (20, "Body Armour"),
            "Carcass Jack": (22, "Body Armour"),
            "Cloak of Defiance": (15, "Body Armour"),
            "Death's Oath": (25, "Body Armour"),
            "Foulborn Death's Oath": (25, "Body Armour"),
            "Inpulsa's Broken Heart": (30, "Body Armour"),
            "Kaom's Heart": (50, "Body Armour"),
            "Loreweave": (35, "Body Armour"),
            "Queen of the Forest": (20, "Body Armour"),
            "Shavronne's Wrappings": (40, "Body Armour"),
            "Skin of the Loyal": (18, "Body Armour"),
            "The Restless Ward": (12, "Body Armour"),
            "Vis Mortis": (15, "Body Armour"),
            "Brass Dome": (25, "Body Armour"),
            
            # === GLOVES ===
            "Facebreaker": (12, "Gloves"),
            "Shadows and Dust": (8, "Gloves"),
            "Southbound": (6, "Gloves"),
            "Tombfist": (18, "Gloves"),
            "Shaper's Touch": (15, "Gloves"),
            "Command of the Pit": (10, "Gloves"),
            "Breathstealer": (12, "Gloves"),
            
            # === BOOTS ===
            "Wanderlust": (5, "Boots"),
            "Seven-League Step": (15, "Boots"),
            "Atziri's Step": (12, "Boots"),
            "Darkray Vectors": (10, "Boots"),
            "Death's Door": (35, "Boots"),
            "Kaom's Roots": (18, "Boots"),
            "Sin Trek": (8, "Boots"),
            "Bubonic Trail": (20, "Boots"),
            "Stormcharger": (5, "Boots"),
            "Wake of Destruction": (5, "Boots"),
            
            # === BELTS ===
            "Meginord's Girdle": (10, "Belt"),
            "Headhunter": (100, "Belt"),
            "Mageblood": (120, "Belt"),
            "Ryslatha's Coil": (25, "Belt"),
            "Soul Tether": (12, "Belt"),
            "String of Servitude": (8, "Belt"),
            "Cyclopean Coil": (15, "Belt"),
            "Darkness Enthroned": (18, "Belt"),
            "Immortal Flesh": (10, "Belt"),
            "Perseverance": (12, "Belt"),
            
            # === AMULETS ===
            "Carnage Heart": (15, "Amulet"),
            "Daresso's Salute": (8, "Amulet"),
            "Eye of Innocence": (10, "Amulet"),
            "Extractor Mentis": (8, "Amulet"),
            "Doedre's Tongue": (6, "Amulet"),
            "Bloodgrip": (8, "Amulet"),
            "Astramentis": (20, "Amulet"),
            "Atziri's Foible": (12, "Amulet"),
            "Badge of the Brotherhood": (35, "Amulet"),
            "Bisco's Collar": (15, "Amulet"),
            "Choir of the Storm": (25, "Amulet"),
            "Impresence": (20, "Amulet"),
            "Marylene's Fallacy": (6, "Amulet"),
            "Ngamahu's Sign": (8, "Amulet"),
            "Solstice Vigil": (30, "Amulet"),
            "The Aylardex": (10, "Amulet"),
            "The Halcyon": (12, "Amulet"),
            "Voll's Devotion": (25, "Amulet"),
            "Xoph's Blood": (35, "Amulet"),
            
            # === RINGS ===
            "Blackheart": (4, "Ring"),
            "Praxis": (5, "Ring"),
            "Le Heup of All": (8, "Ring"),
            "Berek's Grip": (15, "Ring"),
            "Berek's Pass": (15, "Ring"),
            "Berek's Respite": (15, "Ring"),
            "Call of the Brotherhood": (20, "Ring"),
            "Circle of Guilt": (18, "Ring"),
            "Essence Worm": (12, "Ring"),
            "Lori's Lantern": (5, "Ring"),
            "Mark of the Shaper": (25, "Ring"),
            "Ming's Heart": (15, "Ring"),
            "Mokou's Embrace": (8, "Ring"),
            "Pyre": (10, "Ring"),
            "Romira's Banquet": (8, "Ring"),
            "Sibyl's Lament": (6, "Ring"),
            "Snakepit": (8, "Ring"),
            "The Taming": (30, "Ring"),
            "Thief's Torment": (12, "Ring"),
            "Ventor's Gamble": (10, "Ring"),
            "Void Walker": (8, "Ring"),
            "Warden's Brand": (6, "Ring"),
            "The Warden's Brand": (6, "Ring"),
            
            # === WEAPONS (1H) ===
            "Lifesprig": (4, "Wand"),
            "Axiom Perpetuum": (6, "Sceptre"),
            "Brightbeak": (5, "Mace"),
            "Death's Hand": (15, "Mace"),
            "Doryani's Catalyst": (20, "Sceptre"),
            "Obliteration": (12, "Wand"),
            "Poet's Pen": (25, "Wand"),
            "Prismatic Eclipse": (10, "Sword"),
            "Razor of the Seventh Sun": (15, "Sword"),
            "The Princess": (8, "Sword"),
            "Void Battery": (30, "Wand"),
            "Arakaali's Fang": (25, "Dagger"),
            "Bino's Kitchen Knife": (18, "Dagger"),
            "Cold Iron Point": (15, "Dagger"),
            "Cybil's Paw": (10, "Claw"),
            "Hand of Wisdom and Action": (20, "Claw"),
            "Touch of Anguish": (18, "Claw"),
            "Advancing Fortress": (12, "Dagger"),
            
            # === WEAPONS (2H) ===
            "Disfavour": (40, "Axe"),
            "Hegemony's Era": (25, "Staff"),
            "Martyr of Innocence": (22, "Staff"),
            "Pledge of Hands": (35, "Staff"),
            "Starforge": (45, "Sword"),
            "The Harvest": (30, "Axe"),
            "Voidforge": (40, "Sword"),
            "Ngamahu's Flame": (25, "Axe"),
            "Oni-Goroshi": (20, "Sword"),
            "Atziri's Disfavour": (45, "Axe"),
            
            # === BOWS ===
            "Death's Opus": (20, "Bow"),
            "Lioneye's Glare": (18, "Bow"),
            "Reach of the Council": (22, "Bow"),
            "The Tempest": (12, "Bow"),
            "Voltaxic Rift": (20, "Bow"),
            "Windripper": (25, "Bow"),
            "Xoph's Nurture": (22, "Bow"),
            "Hopeshredder": (20, "Bow"),
            
            # === SHIELDS ===
            "Aegis Aurora": (35, "Shield"),
            "Atziri's Mirror": (20, "Shield"),
            "Lioneye's Remorse": (18, "Shield"),
            "Magna Eclipsis": (15, "Shield"),
            "Prism Guardian": (20, "Shield"),
            "Rise of the Phoenix": (15, "Shield"),
            "Saffel's Frame": (18, "Shield"),
            "The Surrender": (30, "Shield"),
            "Victario's Charity": (10, "Shield"),
            
            # === QUIVERS ===
            "Drillneck": (12, "Quiver"),
            "Hyrri's Bite": (8, "Quiver"),
            "Maloney's Mechanism": (20, "Quiver"),
            "Rigwald's Quills": (25, "Quiver"),
            "Soul Strike": (15, "Quiver"),
            
            # === FLASKS ===
            "Atziri's Promise": (15, "Flask"),
            "Bottled Faith": (50, "Flask"),
            "Cinderswallow Urn": (20, "Flask"),
            "Coralito's Signature": (12, "Flask"),
            "Dying Sun": (35, "Flask"),
            "Lion's Roar": (18, "Flask"),
            "Sin's Rebirth": (22, "Flask"),
            "Taste of Hate": (30, "Flask"),
            "The Wise Oak": (15, "Flask"),
            "Vessel of Vinktar": (25, "Flask"),
            "Witchfire Brew": (12, "Flask"),
            
            # === JEWELS ===
            "Abyss Jewel": (5, "Jewel"),
            "Brutal Restraint": (15, "Jewel"),
            "Elegant Hubris": (15, "Jewel"),
            "Glorious Vanity": (15, "Jewel"),
            "Lethal Pride": (15, "Jewel"),
            "Militant Faith": (15, "Jewel"),
            "Split Personality": (20, "Jewel"),
            "The Anima Stone": (25, "Jewel"),
            "Unnatural Instinct": (40, "Jewel"),
            "Watcher's Eye": (50, "Jewel"),
            "Thread of Hope": (20, "Jewel"),
            "Impossible Escape": (35, "Jewel"),
            
            # === INVITATIONS ===
            "Doryani's Invitation": (20, "Belt"),
            
            # === FOULBORN VARIANTS ===
            "Foulborn Esh's Mirror": (8, "Shield"),
            "Foulborn Xoph's Inception": (8, "Amulet"),
        }
        
        for name, (dust, item_type) in builtin.items():
            self.dust_values[name] = {
                'base_dust': dust,
                'dust_ilvl84': dust,
                'dust_ilvl84_q20': int(dust * 1.2) if item_type in ['Helmet', 'Body Armour', 'Gloves', 'Boots', 'Shield'] else dust,
                'item_type': item_type,
                'base_type': '',
            }
        
        print(f"[DustData] Loaded {len(self.dust_values)} built-in dust estimates.")
    
    def get_dust_info(self, item_name: str) -> Optional[dict]:
        """
        Get dust information for a specific item.
        
        Returns:
            Dict with dust values or None if not found
        """
        # Try exact match first
        if item_name in self.dust_values:
            return self.dust_values[item_name]
        
        # Try case-insensitive match
        item_lower = item_name.lower()
        for name, data in self.dust_values.items():
            if name.lower() == item_lower:
                return data
        
        return None
    
    def calculate_item_dust(self, item_name: str, ilvl: int = 84, 
                            quality: int = 0, corrupted: bool = False) -> Tuple[int, int]:
        """
        Calculate dust value for a specific item.
        
        Args:
            item_name: Name of the unique item
            ilvl: Item level
            quality: Current quality
            corrupted: Whether item is corrupted
        
        Returns:
            Tuple of (actual_dust, potential_dust_at_q20)
        """
        info = self.get_dust_info(item_name)
        if not info:
            return (0, 0)
        
        base = info.get('base_dust', 0)
        item_type = info.get('item_type', '')
        
        # Calculate actual dust (with current quality for corrupted, q20 for non-corrupted)
        if corrupted:
            actual = DustCalculator.calculate_dust(base, ilvl, quality, item_type, corrupted=True)
            potential = actual  # Can't improve corrupted items
        else:
            # Non-corrupted: assume we'll quality to 20
            actual = DustCalculator.calculate_dust(base, ilvl, 20, item_type, corrupted=False)
            potential = actual
        
        return (actual, potential)


class DustEfficiencyAnalyzer:
    """
    Analyzes dust efficiency by combining dust values with market prices.
    """
    
    def __init__(self, dust_fetcher: DustDataFetcher, price_fetcher):
        self.dust_fetcher = dust_fetcher
        self.price_fetcher = price_fetcher
    
    def get_efficiency(self, item_name: str, ilvl: int = 84,
                       quality: int = 0, corrupted: bool = False) -> dict:
        """
        Calculate dust efficiency for an item.
        
        Returns:
            Dict with dust values, price, and efficiency metrics
        """
        dust_actual, dust_potential = self.dust_fetcher.calculate_item_dust(
            item_name, ilvl, quality, corrupted
        )
        
        chaos_price = self.price_fetcher.get_price(item_name) if self.price_fetcher else 0
        
        # Calculate efficiency (dust per chaos)
        efficiency = dust_actual / chaos_price if chaos_price > 0 else float('inf')
        
        return {
            'item_name': item_name,
            'dust': dust_actual,
            'dust_potential': dust_potential,
            'chaos_price': chaos_price,
            'efficiency': efficiency,
            'ilvl': ilvl,
            'quality': quality,
            'corrupted': corrupted,
        }
    
    def get_all_efficiencies(self, min_efficiency: float = 1.0) -> List[dict]:
        """
        Get efficiency data for all known items.
        
        Args:
            min_efficiency: Minimum dust/chaos ratio to include
        
        Returns:
            List of efficiency dicts, sorted by efficiency descending
        """
        results = []
        
        for name in self.dust_fetcher.dust_values:
            info = self.get_efficiency(name)
            if info['efficiency'] >= min_efficiency:
                results.append(info)
        
        # Sort by efficiency (highest first)
        results.sort(key=lambda x: x['efficiency'], reverse=True)
        return results

