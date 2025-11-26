"""
Filtering rules engine for item evaluation.
"""

from typing import List, Dict, Any


class FilterRule:
    """Base class for filter rules."""
    
    def check(self, item: Dict[str, Any], context: Dict[str, Any]) -> bool:
        """
        Returns True if the item passes this specific rule.
        Context can contain pricing info, global config, etc.
        """
        return True


class ValueRule(FilterRule):
    """Filter by minimum profit value."""
    
    def __init__(self, min_profit: float):
        self.min_profit = min_profit

    def check(self, item: Dict[str, Any], context: Dict[str, Any]) -> bool:
        profit = context.get('profit', 0)
        return profit >= self.min_profit


class EncounterRule(FilterRule):
    """Handles encounter type exclusions only. Inclusions are handled as overrides."""
    
    def __init__(self, excluded_types: List[str] = None):
        self.excluded_types = set(excluded_types) if excluded_types else set()

    def check(self, item: Dict[str, Any], context: Dict[str, Any]) -> bool:
        enc_type = item.get('type')
        if enc_type in self.excluded_types:
            return False
        return True


class EncounterIncludeOverride(FilterRule):
    """Override rule: if encounter type is in included list, always highlight."""
    
    def __init__(self, included_types: List[str] = None):
        self.included_types = set(included_types) if included_types else set()

    def check(self, item: Dict[str, Any], context: Dict[str, Any]) -> bool:
        if not self.included_types:
            return False
        enc_type = item.get('type')
        return enc_type in self.included_types


class MonsterLifeRule(FilterRule):
    """Handles monster life exclusions only. Inclusions are handled as overrides."""
    
    def __init__(self, excluded_pcts: List[int] = None):
        self.excluded_pcts = set(excluded_pcts) if excluded_pcts else set()

    def check(self, item: Dict[str, Any], context: Dict[str, Any]) -> bool:
        life_pct = item.get('monster_life_pct', 0)
        if life_pct in self.excluded_pcts:
            return False
        return True


class MonsterLifeIncludeOverride(FilterRule):
    """Override rule: if monster life % is in included list, always highlight."""
    
    def __init__(self, included_pcts: List[int] = None):
        self.included_pcts = set(included_pcts) if included_pcts else set()

    def check(self, item: Dict[str, Any], context: Dict[str, Any]) -> bool:
        if not self.included_pcts:
            return False
        life_pct = item.get('monster_life_pct', 0)
        return life_pct in self.included_pcts


class RewardRule(FilterRule):
    """Handles reward exclusions only. Inclusions are handled as overrides."""
    
    def __init__(self, excluded_rewards: List[str] = None):
        self.excluded_rewards = set(excluded_rewards) if excluded_rewards else set()

    def check(self, item: Dict[str, Any], context: Dict[str, Any]) -> bool:
        rew_name = item.get('reward')
        if rew_name in self.excluded_rewards:
            return False
        return True


class RewardIncludeOverride(FilterRule):
    """Override rule: if reward is in included list, always highlight (bypass other filters)."""
    
    def __init__(self, included_rewards: List[str] = None):
        self.included_rewards = set(included_rewards) if included_rewards else set()

    def check(self, item: Dict[str, Any], context: Dict[str, Any]) -> bool:
        if not self.included_rewards:
            return False
        rew_name = item.get('reward')
        return rew_name in self.included_rewards


class TierRule(FilterRule):
    """Override rule for always highlighting specific tiers."""
    
    def __init__(self, always_highlight_tiers: List[int]):
        self.always_highlight_tiers = set(always_highlight_tiers)

    def check(self, item: Dict[str, Any], context: Dict[str, Any]) -> bool:
        return item.get('monster_life_pct', 0) in self.always_highlight_tiers


class GenericWhitelistBlacklistRule(FilterRule):
    """Generic rule that can whitelist or blacklist any field."""
    
    def __init__(self, field_extractor, whitelist: List[str] = None, blacklist: List[str] = None):
        self.field_extractor = field_extractor
        self.whitelist = set(whitelist) if whitelist else set()
        self.blacklist = set(blacklist) if blacklist else set()

    def check(self, item: Dict[str, Any], context: Dict[str, Any]) -> bool:
        val = self.field_extractor(item)
        
        # Blacklist: If match, FAIL
        if val in self.blacklist:
            return False
            
        # Whitelist: If whitelist exists AND val NOT in it, FAIL
        if self.whitelist and val not in self.whitelist:
            return False
            
        return True


class FilteringRuleEngine:
    """Engine for evaluating items against multiple filter rules."""
    
    def __init__(self):
        self.rules = []
        self.overrides = []  # Rules that if passed, immediately accept the item

    def add_rule(self, rule: FilterRule):
        self.rules.append(rule)

    def add_override(self, rule: FilterRule):
        self.overrides.append(rule)

    def evaluate(self, item: Dict[str, Any], price_fetcher) -> bool:
        """
        Determines if an item should be highlighted.
        Calculates profit first and adds to context.
        """
        # 1. Calculate Value
        sac_name = item.get('sacrifice')
        sac_qty = item.get('sacrifice_count', 1)
        rew_name = item.get('reward')
        rew_qty = item.get('reward_count', 1)
        
        sac_price = price_fetcher.get_price(sac_name) * sac_qty
        rew_price = price_fetcher.get_price(rew_name) * rew_qty
        
        profit = rew_price - sac_price
        
        context = {
            'profit': profit,
            'sac_price': sac_price,
            'rew_price': rew_price
        }

        # 2. Check Overrides first - if any override passes, accept immediately
        for rule in self.overrides:
            if rule.check(item, context):
                return True

        # 3. Check Standard Rules - all must pass
        for rule in self.rules:
            if not rule.check(item, context):
                return False

        return True
