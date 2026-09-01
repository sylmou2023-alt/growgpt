"""
prices.py — Live market prices.

Roblox POSTs the real prices here every 5 minutes; everything else in GrowGPT
reads them from this module. The numbers are now persisted through store.py,
because keeping them in a process dict meant they reverted to the hardcoded
defaults on every Render restart while the bot went on quoting them as fact.
"""
import time

from store import store
from text_utils import normalize_lang

# Seeds used only until Roblox sends the first real update. freshness() reports
# "default" while these are in play so callers can warn the player.
DEFAULT_PRICES = {
    "carrot":     15,
    "tomato":     45,
    "corn":       30,
    "wheat":      20,
    "strawberry": 60,
    "blueberry":  75,
    "pumpkin":    55,
    "potato":     18,
    "rose":       90,
    "sunflower":  80,
}

# Reference prices, used to judge whether a live price is high or low.
BASE_PRICES = {
    "carrot":     10,
    "tomato":     35,
    "corn":       25,
    "wheat":      15,
    "strawberry": 50,
    "blueberry":  60,
    "pumpkin":    45,
    "potato":     12,
    "rose":       70,
    "sunflower":  65,
}

# Estimated planting cost per crop.
PLANT_COST = {
    "carrot":     5,
    "tomato":     15,
    "corn":       10,
    "wheat":      8,
    "strawberry": 20,
    "blueberry":  25,
    "pumpkin":    18,
    "potato":     6,
    "rose":       35,
    "sunflower":  30,
}

_STORE_KEY = "growgpt:prices"

# Prices change every 5 minutes, so a few seconds of in-process caching costs
# nothing in accuracy and saves a network round trip on every chat message.
_CACHE_TTL = 5.0

# Roblox is expected every 5 min; allow some slack before calling data stale.
_FRESH_WINDOW = 330
_STALE_WINDOW = 900


class PriceManager:
    def __init__(self):
        # Seed the store on first boot so a cold instance has something to
        # serve, but never overwrite prices another worker already wrote.
        if store.get_json(_STORE_KEY) is None:
            store.set_json(_STORE_KEY, {
                "prices": DEFAULT_PRICES.copy(),
                "last_update": None,
                "history": [],
            })

    # =========================
    # STATE
    # =========================
    def _state(self) -> dict:
        state = store.get_json(_STORE_KEY, cache_ttl=_CACHE_TTL)
        if not isinstance(state, dict) or "prices" not in state:
            return {"prices": DEFAULT_PRICES.copy(), "last_update": None, "history": []}
        return state

    def update(self, new_prices: dict):
        """Apply a price update coming from Roblox."""
        state = self._state()
        prices = dict(state.get("prices") or {})
        history = list(state.get("history") or [])

        # Snapshot the prices being replaced, capped at 12 entries (~1 hour).
        history.append({"time": time.time(), "prices": prices.copy()})
        history = history[-12:]

        for plant, price in (new_prices or {}).items():
            # Roblox is the source of truth, but one malformed entry must not
            # poison the table for every player.
            try:
                value = float(price)
            except (TypeError, ValueError):
                continue
            if value < 0:
                continue
            key = str(plant).strip().lower()
            prices[key] = int(value) if value == int(value) else value

        store.set_json(_STORE_KEY, {
            "prices": prices,
            "last_update": time.time(),
            "history": history,
        })

    def current(self) -> dict:
        return dict(self._state().get("prices") or {})

    # =========================
    # ANALYSIS
    # =========================
    def _ratio(self, plant: str, price) -> float:
        """
        How good this price is versus its reference.

        A crop Roblox sends that we have no reference for gets a neutral 1.0.
        The previous code divided by a default base of 1, so an unknown crop
        priced at 40 scored 40.0 and beat every known crop forever — a brand
        new plant instantly became the permanent "best sale".
        """
        base = BASE_PRICES.get(plant)
        if not base or base <= 0:
            return 1.0
        try:
            return float(price) / float(base)
        except (TypeError, ValueError):
            return 0.0

    def best_to_sell(self) -> tuple:
        """The crop whose current price is highest relative to its reference."""
        prices = self.current()
        if not prices:
            return ("tomato", DEFAULT_PRICES["tomato"])
        # Ties break towards a crop we hold a reference for, then towards the
        # higher absolute price.
        best = max(
            prices.items(),
            key=lambda kv: (self._ratio(kv[0], kv[1]), kv[0] in BASE_PRICES, kv[1]),
        )
        return best

    def cheapest_to_plant(self) -> tuple:
        """Best sale-price-to-planting-cost ratio among crops we can cost."""
        prices = self.current()
        if not prices:
            return ("carrot", PLANT_COST["carrot"])
        scored = {
            plant: prices.get(plant, 0) / max(PLANT_COST.get(plant, 1), 1)
            for plant in PLANT_COST
        }
        best = max(scored, key=scored.get)
        return (best, PLANT_COST.get(best, 5))

    def market_mood(self, lang: str = "fr") -> str:
        lang = normalize_lang(lang)
        prices = self.current()
        avg_ratio = sum(
            self._ratio(p, prices.get(p, 0)) for p in BASE_PRICES
        ) / len(BASE_PRICES)

        if avg_ratio > 1.3:
            return "🔥 en feu" if lang == "fr" else "🔥 on fire"
        if avg_ratio > 1.0:
            return "📈 favorable"
        if avg_ratio > 0.8:
            return "😐 stable"
        return "📉 calme" if lang == "fr" else "📉 slow"

    # =========================
    # FRESHNESS
    # =========================
    def freshness(self) -> str:
        """'default' | 'fresh' | 'stale' | 'old' — how much to trust the data."""
        last = self._state().get("last_update")
        if not last:
            return "default"
        age = time.time() - last
        if age < _FRESH_WINDOW:
            return "fresh"
        if age < _STALE_WINDOW:
            return "stale"
        return "old"

    def age_seconds(self):
        last = self._state().get("last_update")
        return None if not last else int(time.time() - last)

    def freshness_warning(self, lang: str = "fr") -> str:
        """
        A player-facing caveat, empty when the data is trustworthy.

        This is the whole point of tracking freshness: without it the bot
        announced fallback prices with exactly the same confidence as live
        ones, which defeats the "real current prices" goal entirely.
        """
        lang = normalize_lang(lang)
        state = self.freshness()
        if state == "fresh":
            return ""
        if state == "default":
            if lang == "fr":
                return ("\n⚠️ Je n'ai pas encore reçu les prix du serveur, "
                        "ceux-ci sont indicatifs.")
            return "\n⚠️ I haven't received server prices yet, these are estimates."
        minutes = (self.age_seconds() or 0) // 60
        if lang == "fr":
            return "\n⚠️ Prix datant de %d min, ils ont pu bouger." % minutes
        return "\n⚠️ Prices are %d min old, they may have moved." % minutes

    # =========================
    # ADVICE
    # =========================
    def get_advice(self, player: dict, lang: str = "fr") -> list:
        """Personalised market tips for this player."""
        lang = normalize_lang(lang)
        player = player or {}
        advice = []
        money = player.get("money", 0) or 0
        plants = player.get("plants", []) or []
        level = player.get("level", 1) or 1

        prices = self.current()
        best_plant, best_price = self.best_to_sell()
        cheap_plant, _ = self.cheapest_to_plant()

        if lang == "fr":
            advice.append(f"🏆 Meilleure vente : {best_plant} à {best_price}💵")
            advice.append(f"🌱 Meilleur achat : {cheap_plant} (bon ratio coût/gain)")
            if money < 50:
                advice.append("💡 Budget serré : reste sur les plantes communes")
            elif money > 500:
                advice.append("💰 Tu peux investir dans des plantes rares !")
            for p in plants:
                p_low = str(p).lower()
                if p_low == best_plant:
                    advice.append(f"✅ Tes {p} sont au TOP du marché — vends maintenant !")
                elif self._ratio(p_low, prices.get(p_low, 0)) < 1.0:
                    advice.append(f"⚠️ {p} en dessous de la moyenne — attends un peu.")
            if level < 3:
                advice.append("⭐ Niveau bas : priorise les quêtes pour monter vite")
        else:
            advice.append(f"🏆 Best sell: {best_plant} at {best_price}💵")
            advice.append(f"🌱 Best buy: {cheap_plant} (good cost/profit ratio)")
            if money < 50:
                advice.append("💡 Tight budget: stick to common plants")
            elif money > 500:
                advice.append("💰 You can invest in rare plants!")
            for p in plants:
                p_low = str(p).lower()
                if p_low == best_plant:
                    advice.append(f"✅ Your {p} are TOP market — sell now!")
                elif self._ratio(p_low, prices.get(p_low, 0)) < 1.0:
                    advice.append(f"⚠️ {p} below average — wait a bit.")
            if level < 3:
                advice.append("⭐ Low level: prioritize quests to level up fast")

        warning = self.freshness_warning(lang).strip()
        if warning:
            advice.append(warning)

        return advice
