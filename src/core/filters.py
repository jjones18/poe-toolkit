"""
Filtering rules engine for item evaluation.
"""

from typing import List, Dict, Any


class FilterRule:
    """Base class for filter rules."""
    
    def check(self, item: Dict[str, Any], context: Dict[str, Any]) -> bool:
        return True


class ValueRule(FilterRule):
    """Filter by minimum profit value."""
    
    def __init__(self, min_profit: float):
        self.min_profit = min_profit

    def check(self, item: Dict[str, Any], context: Dict[str, Any]) -> bool:
        profit = context.get('profit', 0)
        return profit >= self.min_profit


class EncounterRule(FilterRule):
    """Filter by encounter type."""
    
    def __init__(self, excluded_types: List[str] = None, included_types: List[str] = None):
        self.excluded_types = set(excluded_types) if excluded_types else set()
        self.included_types = set(included_types) if included_types else set()

    def check(self, item: Dict[str, Any], context: Dict[str, Any]) -> bool:
        enc_type = item.get('type')
        if enc_type in self.excluded_types:
            return False
        if self.included_types and enc_type not in self.included_types:
            return False
        return True


class MonsterLifeRule(FilterRule):
    """Filter by monster life percentage."""
    
    def __init__(self, excluded_pcts: List[int] = None, included_pcts: List[int] = None):
        self.excluded_pcts = set(excluded_pcts) if excluded_pcts else set()
        self.included_pcts = set(included_pcts) if included_pcts else set()

    def check(self, item: Dict[str, Any], context: Dict[str, Any]) -> bool:
        life_pct = item.get('monster_life_pct', 0)
        if life_pct in self.excluded_pcts:
            return False
        if self.included_pcts and life_pct not in self.included_pcts:
            return False
        return True


class RewardRule(FilterRule):
    """Filter by reward type."""
    
    def __init__(self, excluded_rewards: List[str] = None, included_rewards: List[str] = None):
        self.excluded_rewards = set(excluded_rewards) if excluded_rewards else set()
        self.included_rewards = set(included_rewards) if included_rewards else set()

    def check(self, item: Dict[str, Any], context: Dict[str, Any]) -> bool:
        rew_name = item.get('reward')
        if rew_name in self.excluded_rewards:
            return False
        if self.included_rewards and rew_name not in self.included_rewards:
            return False
        return True


class TierRule(FilterRule):
    """Override rule for always highlighting specific tiers."""
    
    def __init__(self, always_highlight_tiers: List[int]):
        self.always_highlight_tiers = always_highlight_tiers

    def check(self, item: Dict[str, Any], context: Dict[str, Any]) -> bool:
        return item.get('monster_life_pct', 0) in self.always_highlight_tiers


class FilteringRuleEngine:
    """Engine for evaluating items against multiple filter rules."""
    
    def __init__(self):
        self.rules = []
        self.overrides = []

    def add_rule(self, rule: FilterRule):
        self.rules.append(rule)

    def add_override(self, rule: FilterRule):
        self.overrides.append(rule)

    def evaluate(self, item: Dict[str, Any], price_fetcher) -> bool:
        """Determines if an item should be highlighted."""
        # Calculate value
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

        # Check overrides first
        for rule in self.overrides:
            if rule.check(item, context):
                return True

        # Check standard rules
        for rule in self.rules:
            if not rule.check(item, context):
                return False

        return True

