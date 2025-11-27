"""
Script to generate poedust_cache.json from scraped data.
Run this after scraping poedust.com to update the cache.
"""

import json
import os

# Scraped from poedust.com (abbreviated - full data is from Puppeteer scrape)
# This file will be updated with the full 1451 items
SAMPLE_DATA = [
    {"name": "Bloodseeker", "chaos": 10, "dust_ilvl84": 1213680, "dust_ilvl84_q20": 1456416},
    {"name": "Realmshaper", "chaos": 0, "dust_ilvl84": 2860, "dust_ilvl84_q20": 3432},
    {"name": "Ashcaller", "chaos": 0, "dust_ilvl84": 3460, "dust_ilvl84_q20": 4152},
    {"name": "Mortem Morsu", "chaos": 0, "dust_ilvl84": 5300, "dust_ilvl84_q20": 6360},
    {"name": "Tulfall", "chaos": 2, "dust_ilvl84": 72820, "dust_ilvl84_q20": 87384},
    {"name": "Lioneye's Vision", "chaos": 1, "dust_ilvl84": 19800, "dust_ilvl84_q20": 23760},
    {"name": "Soul Mantle", "chaos": 1, "dust_ilvl84": 10340, "dust_ilvl84_q20": 12408},
    {"name": "Greed's Embrace", "chaos": 2, "dust_ilvl84": 12700, "dust_ilvl84_q20": 15240},
    {"name": "Ventor's Gamble", "chaos": 10, "dust_ilvl84": 16580, "dust_ilvl84_q20": 19896},
    {"name": "Goldrim", "chaos": 1, "dust_ilvl84": 2660, "dust_ilvl84_q20": 3192},
    {"name": "Tabula Rasa", "chaos": 2, "dust_ilvl84": 4240, "dust_ilvl84_q20": 5088},
    {"name": "Wanderlust", "chaos": 1, "dust_ilvl84": 2120, "dust_ilvl84_q20": 2544},
    {"name": "Lifesprig", "chaos": 1, "dust_ilvl84": 2000, "dust_ilvl84_q20": 2400},
    {"name": "Axiom Perpetuum", "chaos": 1, "dust_ilvl84": 2600, "dust_ilvl84_q20": 3120},
    {"name": "Meginord's Girdle", "chaos": 1, "dust_ilvl84": 4380, "dust_ilvl84_q20": 5256},
    {"name": "Blackheart", "chaos": 1, "dust_ilvl84": 2060, "dust_ilvl84_q20": 2472},
    {"name": "Praxis", "chaos": 1, "dust_ilvl84": 3720, "dust_ilvl84_q20": 4464},
    {"name": "Le Heup of All", "chaos": 2, "dust_ilvl84": 4940, "dust_ilvl84_q20": 5928},
    {"name": "Berek's Grip", "chaos": 1, "dust_ilvl84": 4380, "dust_ilvl84_q20": 5256},
    {"name": "Berek's Pass", "chaos": 1, "dust_ilvl84": 4380, "dust_ilvl84_q20": 5256},
    {"name": "Berek's Respite", "chaos": 15, "dust_ilvl84": 7020, "dust_ilvl84_q20": 8424},
    {"name": "Foulborn Bramblejack", "chaos": 1, "dust_ilvl84": 2500, "dust_ilvl84_q20": 3000},
    {"name": "Foulborn Xoph's Inception", "chaos": 2, "dust_ilvl84": 21560, "dust_ilvl84_q20": 25872},
    {"name": "Death's Oath", "chaos": 20, "dust_ilvl84": 24280, "dust_ilvl84_q20": 29136},
    {"name": "The Warden's Brand", "chaos": 1, "dust_ilvl84": 4720, "dust_ilvl84_q20": 5664},
    # Add more items from the full scrape...
]

def generate_cache(items, output_path):
    """Generate the cache file from item data."""
    output = {
        'source': 'poedust.com',
        'scraped_date': '2025-01-26',
        'league': 'Standard',
        'item_count': len(items),
        'items': {}
    }
    
    for item in items:
        output['items'][item['name']] = {
            'dust_ilvl84': item['dust_ilvl84'],
            'dust_ilvl84_q20': item['dust_ilvl84_q20'],
            'chaos': item.get('chaos', 0)
        }
    
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2)
    
    print(f"Generated cache with {len(output['items'])} items: {output_path}")


if __name__ == '__main__':
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    output_path = os.path.join(project_root, 'data', 'poedust_cache.json')
    
    generate_cache(SAMPLE_DATA, output_path)

