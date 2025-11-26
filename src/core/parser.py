"""
Item parsers for various POE item types.
"""

import re


class UltimatumParser:
    """
    Parses 'Inscribed Ultimatum' items from the PoE API.
    """

    RE_MONSTER_LIFE = re.compile(r"(\d+)% (?:more|increased) Monster Life")

    def parse_item(self, item_data: dict) -> dict:
        if "Ultimatum" not in item_data.get('typeLine', ''):
            return None

        result = {
            'sacrifice': None,
            'sacrifice_count': 1,
            'reward': None,
            'reward_count': 1,
            'type': 'Unknown',
            'monster_life_pct': 0,
            'original_item': item_data
        }

        properties = item_data.get('properties', [])
        for prop in properties:
            name = prop.get('name', '')
            values = prop.get('values', [])

            if name == 'Challenge':
                if values:
                    result['type'] = values[0][0]

            elif 'Requires Sacrifice' in name:
                if len(values) >= 1:
                    sac_name = values[0][0]
                    sac_qty = 1
                    
                    if len(values) >= 2:
                        qty_str = values[1][0]
                        if qty_str.startswith('x'):
                            try:
                                sac_qty = int(qty_str[1:])
                            except ValueError:
                                pass
                    
                    result['sacrifice'] = self._normalize_name(sac_name)
                    result['sacrifice_count'] = sac_qty

            elif 'Reward' in name:
                if values:
                    rew_text = values[0][0]
                    
                    if "Doubles sacrificed" in rew_text:
                        result['reward'] = result['sacrifice']
                        result['reward_count'] = result['sacrifice_count'] * 2
                    else:
                        rew_qty = 1
                        if len(values) >= 2:
                            qty_str = values[1][0]
                            if qty_str.startswith('x'):
                                try:
                                    rew_qty = int(qty_str[1:])
                                except ValueError:
                                    pass
                        
                        result['reward'] = self._normalize_name(rew_text)
                        result['reward_count'] = rew_qty

        explicit_mods = item_data.get('explicitMods', [])
        for mod in explicit_mods:
            life_match = self.RE_MONSTER_LIFE.search(mod)
            if life_match:
                result['monster_life_pct'] = int(life_match.group(1))
                break

        return result

    def _normalize_name(self, name: str) -> str:
        """Normalizes item names for price lookup."""
        if name.endswith(" Orbs"):
            return name[:-1]
        if name == "Stacked Decks":
            return "Stacked Deck"
        if name == "Vaal Orbs":
            return "Vaal Orb"
        return name

