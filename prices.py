"""
core/prices.py — Gestionnaire de prix en temps réel
Reçoit les prix de Roblox toutes les 5 min et fournit des conseils.
"""
import time
import random


# Prix par défaut (utilisés si Roblox n'a pas encore envoyé)
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

# Prix de base pour détecter si un prix est "haut" ou "bas"
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

# Coût de plantation estimé par plante
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


class PriceManager:
    def __init__(self):
        self._prices      = DEFAULT_PRICES.copy()
        self._last_update = None
        self._history     = []   # liste de snapshots {time, prices}

    def update(self, new_prices: dict):
        """Reçoit les nouveaux prix depuis Roblox."""
        # Garder l'historique (max 12 snapshots = 1h)
        if len(self._history) >= 12:
            self._history.pop(0)
        self._history.append({
            "time":   time.time(),
            "prices": self._prices.copy()
        })
        # Mettre à jour avec les nouveaux prix
        for plant, price in new_prices.items():
            self._prices[plant.lower()] = price
        self._last_update = time.time()

    def current(self) -> dict:
        return self._prices.copy()

    def best_to_sell(self) -> tuple:
        """Retourne (plante, prix) avec le meilleur ratio prix_actuel/prix_base."""
        if not self._prices:
            return ("tomato", 45)
        best = max(
            self._prices.items(),
            key=lambda kv: kv[1] / max(BASE_PRICES.get(kv[0], 1), 1)
        )
        return best

    def cheapest_to_plant(self) -> tuple:
        """Retourne la plante la moins chère à planter avec bon retour."""
        if not self._prices:
            return ("carrot", 5)
        # Score = prix vente / coût plantation
        scored = {
            plant: self._prices.get(plant, 0) / max(PLANT_COST.get(plant, 1), 1)
            for plant in PLANT_COST
        }
        best = max(scored, key=scored.get)
        return (best, PLANT_COST.get(best, 5))

    def market_mood(self, lang: str = "fr") -> str:
        """Retourne l'humeur générale du marché."""
        avg_ratio = sum(
            self._prices.get(p, 0) / max(BASE_PRICES.get(p, 1), 1)
            for p in BASE_PRICES
        ) / len(BASE_PRICES)

        if avg_ratio > 1.3:
            return "🔥 en feu" if lang == "fr" else "🔥 on fire"
        if avg_ratio > 1.0:
            return "📈 favorable" if lang == "fr" else "📈 favorable"
        if avg_ratio > 0.8:
            return "😐 stable" if lang == "fr" else "😐 stable"
        return "📉 calme" if lang == "fr" else "📉 slow"

    def get_advice(self, player: dict, lang: str = "fr") -> list:
        """Génère une liste de conseils marché personnalisés."""
        advice = []
        money  = player.get("money", 0)
        plants = player.get("plants", [])
        level  = player.get("level", 1)

        best_plant, best_price = self.best_to_sell()
        cheap_plant, _         = self.cheapest_to_plant()

        if lang == "fr":
            advice.append(f"🏆 Meilleure vente : {best_plant} à {best_price}💵")
            advice.append(f"🌱 Meilleur achat : {cheap_plant} (bon ratio coût/gain)")
            if money < 50:
                advice.append("💡 Budget serré : reste sur les plantes communes")
            elif money > 500:
                advice.append("💰 Tu peux investir dans des plantes rares !")
            # Plantes du joueur dans le top ?
            for p in plants:
                p_low = p.lower()
                if p_low == best_plant:
                    advice.append(f"✅ Tes {p} sont au TOP du marché — vends maintenant !")
                elif self._prices.get(p_low, 0) < BASE_PRICES.get(p_low, 999):
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
                p_low = p.lower()
                if p_low == best_plant:
                    advice.append(f"✅ Your {p} are TOP market — sell now!")
                elif self._prices.get(p_low, 0) < BASE_PRICES.get(p_low, 999):
                    advice.append(f"⚠️ {p} below average — wait a bit.")
            if level < 3:
                advice.append("⭐ Low level: prioritize quests to level up fast")

        return advice

    def freshness(self) -> str:
        """Indique la fraîcheur des données de prix."""
        if self._last_update is None:
            return "default"
        age = time.time() - self._last_update
        if age < 310:   # moins de 5 min + 10 sec de marge
            return "fresh"
        if age < 600:
            return "stale"
        return "old"
