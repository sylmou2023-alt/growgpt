"""
quests.py — Dynamic quest engine.

Quests are generated from the live market and the player's own state, then
persisted through store.py so accepting a quest survives a Render restart.

The accept path used to be broken in a way that was invisible until you tried
it: _find_quest rebuilt every template against a hardcoded list of plants and
amounts and compared IDs until one matched. Any quest whose plant was not in
COMMON_PLANTS or RARE_PLANTS — tomato and pumpkin among them, both sold in the
game — or whose amount was computed rather than picked from a fixed list, could
be suggested to the player but never accepted. Suggested quests are now written
to a catalog as a recipe, and accept() looks the recipe up.
"""
import random
import time

from store import store
from text_utils import normalize_lang

# =========================
# QUEST CATALOGUE
# {plant}, {amount}, {reward}, {xp} are filled in at build time.
# =========================
QUEST_TEMPLATES = {
    "sell_plant": {
        "id":          "sell_{plant}_{amount}",
        "fr": {
            "title":   "Vendeur de {plant}",
            "desc":    "Vends {amount} {plant} au marché.",
            "reward":  "💵 {reward} pièces + ⭐ {xp} XP"
        },
        "en": {
            "title":   "{plant} Seller",
            "desc":    "Sell {amount} {plant} at the market.",
            "reward":  "💵 {reward} coins + ⭐ {xp} XP"
        },
        "difficulty": "easy"
    },
    "harvest_bulk": {
        "id":          "harvest_{amount}",
        "fr": {
            "title":   "Grande Récolte",
            "desc":    "Récolte {amount} plantes en une seule session.",
            "reward":  "💵 {reward} pièces + ⭐ {xp} XP"
        },
        "en": {
            "title":   "Big Harvest",
            "desc":    "Harvest {amount} plants in one session.",
            "reward":  "💵 {reward} coins + ⭐ {xp} XP"
        },
        "difficulty": "medium"
    },
    "plant_rare": {
        "id":          "plant_rare_{amount}",
        "fr": {
            "title":   "Jardinier Exotique",
            "desc":    "Plante {amount} plantes rares.",
            "reward":  "💵 {reward} pièces + ⭐ {xp} XP + 🧬 bonus mutation"
        },
        "en": {
            "title":   "Exotic Gardener",
            "desc":    "Plant {amount} rare plants.",
            "reward":  "💵 {reward} coins + ⭐ {xp} XP + 🧬 mutation bonus"
        },
        "difficulty": "hard"
    },
    "earn_money": {
        "id":          "earn_{amount}_coins",
        "fr": {
            "title":   "Magnat du Jardin",
            "desc":    "Gagne {amount} pièces en vendant.",
            "reward":  "💵 {reward} pièces + ⭐ {xp} XP"
        },
        "en": {
            "title":   "Garden Tycoon",
            "desc":    "Earn {amount} coins by selling.",
            "reward":  "💵 {reward} coins + ⭐ {xp} XP"
        },
        "difficulty": "medium"
    },
    "sell_at_peak": {
        "id":          "sell_peak_{plant}",
        "fr": {
            "title":   "Timing Parfait",
            "desc":    "Vends {amount} {plant} quand son prix est au maximum.",
            "reward":  "💵 {reward} pièces + ⭐ {xp} XP + 🌟 titre 'Trader'"
        },
        "en": {
            "title":   "Perfect Timing",
            "desc":    "Sell {amount} {plant} when its price is at maximum.",
            "reward":  "💵 {reward} coins + ⭐ {xp} XP + 🌟 title 'Trader'"
        },
        "difficulty": "hard"
    },
    "daily_grind": {
        "id":          "daily_login",
        "fr": {
            "title":   "Agriculteur Assidu",
            "desc":    "Connecte-toi et plante au moins une fois aujourd'hui.",
            "reward":  "💵 {reward} pièces + ⭐ {xp} XP"
        },
        "en": {
            "title":   "Dedicated Farmer",
            "desc":    "Log in and plant at least once today.",
            "reward":  "💵 {reward} coins + ⭐ {xp} XP"
        },
        "difficulty": "easy"
    }
}

RARE_PLANTS   = ["rose", "sunflower", "blueberry", "strawberry"]
COMMON_PLANTS = ["carrot", "potato", "wheat", "corn"]

_ACTIVE_KEY = "growgpt:quests:active:%s"
_RECIPE_KEY = "growgpt:quests:recipe:%s"
_MARKET_KEY = "growgpt:quests:market"
_STATS_KEY = "growgpt:stats:quests"

# A suggested quest stays acceptable for a day. Long enough that a player can
# think about it, short enough that the free Upstash tier stays tidy.
_RECIPE_TTL = 24 * 3600

# Market quests are rebuilt on every price update, so a short cache is safe.
_MARKET_CACHE_TTL = 10.0

_MAX_ACTIVE_PER_PLAYER = 10


class QuestEngine:
    def __init__(self, prices):
        self.prices = prices

    # =========================
    # STATS
    # =========================
    def count_active(self) -> int:
        """
        Read from a counter rather than summing every player's list: with
        Redis that would be one round trip per player on a status check.
        """
        return max(0, store.hgetall(_STATS_KEY).get("active", 0))

    # =========================
    # MARKET QUESTS
    # =========================
    def refresh_market_quests(self):
        """
        Called whenever Roblox sends new prices. Stores recipes, not rendered
        text: the old version built these with the default French strings and
        then merely stamped a "lang" field on the copy, so English players were
        served French market quests.
        """
        best_plant, _ = self.prices.best_to_sell()
        recipes = [
            {"template": "sell_plant", "plant": best_plant, "amount": 5, "level": 1},
            {"template": "sell_at_peak", "plant": best_plant, "amount": 3, "level": 5},
        ]
        for recipe in recipes:
            self._register(recipe)
        store.set_json(_MARKET_KEY, recipes)

    def _market_recipes(self) -> list:
        recipes = store.get_json(_MARKET_KEY, cache_ttl=_MARKET_CACHE_TTL)
        return recipes if isinstance(recipes, list) else []

    # =========================
    # SUGGESTION
    # =========================
    def suggest(self, player: dict, lang: str = "fr") -> list:
        """Up to four quests tailored to this player and the current market."""
        lang = normalize_lang(lang)
        player = player or {}
        level = player.get("level", 1) or 1
        money = player.get("money", 0) or 0
        plants = player.get("plants", []) or []

        recipes = [{"template": "daily_grind", "plant": "any", "amount": 1, "level": level}]

        # A quest about a crop the player actually holds is the most relevant
        # one, so it goes in before the generic pool rather than last where the
        # four-item cap used to discard it.
        if plants:
            recipes.append({
                "template": "sell_plant",
                "plant": str(random.choice(plants)).lower(),
                "amount": 8,
                "level": level,
            })

        if level < 5:
            recipes.append({
                "template": "sell_plant",
                "plant": random.choice(COMMON_PLANTS),
                "amount": 5,
                "level": level,
            })
            recipes.append({
                "template": "harvest_bulk", "plant": "any", "amount": 10, "level": level,
            })
        else:
            recipes.append({
                "template": "plant_rare",
                "plant": random.choice(RARE_PLANTS),
                "amount": 3,
                "level": level,
            })
            recipes.append({
                "template": "earn_money",
                "plant": "any",
                "amount": max(100, int(money) // 2),
                "level": level,
            })

        recipes.extend(self._market_recipes())

        suggested = []
        seen = set()
        for recipe in recipes[:8]:
            quest = self._build_quest(recipe, lang)
            if quest["id"] in seen:
                continue
            seen.add(quest["id"])
            # Register before returning: whatever we offer must be acceptable.
            self._register(recipe)
            suggested.append(quest)
            if len(suggested) == 4:
                break
        return suggested

    def hint_plant(self, player: dict) -> str:
        """
        A plant name suitable for conversational filler, with no side effects.

        brain.py needs one crop name to drop into a reply template. It used to
        call suggest() for that, which now writes a catalog entry per suggested
        quest — four Redis writes on every single chat message, for one string.
        """
        plants = (player or {}).get("plants") or []
        if plants:
            return str(plants[0]).lower()
        best_plant, _ = self.prices.best_to_sell()
        return best_plant

    # =========================
    # ACCEPT / COMPLETE
    # =========================
    def accept(self, player_id: str, quest_id: str, lang: str = "fr") -> dict:
        lang = normalize_lang(lang)
        active = self.get_active(player_id)

        for q in active:
            if q.get("id") == quest_id:
                return {"ok": False, "message": (
                    "❌ Tu as déjà cette quête en cours !" if lang == "fr"
                    else "❌ You already have this quest active!")}

        if len(active) >= _MAX_ACTIVE_PER_PLAYER:
            return {"ok": False, "message": (
                "❌ Trop de quêtes en cours, termines-en une d'abord." if lang == "fr"
                else "❌ Too many active quests, finish one first.")}

        recipe = store.get_json(_RECIPE_KEY % quest_id)
        if not recipe:
            return {"ok": False, "message": (
                "❌ Quête introuvable ou expirée. Redemande la liste des quêtes."
                if lang == "fr" else
                "❌ Quest not found or expired. Ask for the quest list again.")}

        quest = self._build_quest(recipe, lang)
        quest["accepted_at"] = time.time()
        quest["progress"] = 0

        active.append(quest)
        store.set_json(_ACTIVE_KEY % player_id, active)
        store.hincr(_STATS_KEY, "active", 1)

        title = quest.get("title", quest_id)
        return {"ok": True, "quest": quest, "message": (
            "✅ Quête acceptée : %s ! Bonne chance 🌱" % title if lang == "fr"
            else "✅ Quest accepted: %s! Good luck 🌱" % title)}

    def complete(self, player_id: str, quest_id: str, lang: str = "fr") -> dict:
        lang = normalize_lang(lang)
        active = self.get_active(player_id)

        for i, q in enumerate(active):
            if q.get("id") == quest_id:
                active.pop(i)
                store.set_json(_ACTIVE_KEY % player_id, active)
                store.hincr(_STATS_KEY, "active", -1)
                reward = q.get("reward", "?")
                return {"ok": True, "reward": q.get("reward_data", {}), "message": (
                    "🎉 Quête terminée ! Tu reçois : %s" % reward if lang == "fr"
                    else "🎉 Quest complete! You receive: %s" % reward)}

        return {"ok": False, "message": (
            "❌ Quête non trouvée dans tes quêtes actives." if lang == "fr"
            else "❌ Quest not found in your active quests.")}

    def get_active(self, player_id: str) -> list:
        active = store.get_json(_ACTIVE_KEY % player_id)
        return active if isinstance(active, list) else []

    # =========================
    # INTERNALS
    # =========================
    def _register(self, recipe: dict):
        """Make a suggested quest acceptable by storing how to rebuild it."""
        quest_id = self._quest_id(recipe)
        store.set_json(_RECIPE_KEY % quest_id, recipe, ttl_seconds=_RECIPE_TTL)

    def _quest_id(self, recipe: dict) -> str:
        tpl = QUEST_TEMPLATES[recipe["template"]]
        return tpl["id"].format(plant=recipe["plant"], amount=recipe["amount"])

    def _build_quest(self, recipe: dict, lang: str = "fr") -> dict:
        lang = normalize_lang(lang)
        template_key = recipe["template"]
        plant = recipe["plant"]
        amount = recipe["amount"]
        level = recipe.get("level", 1)

        tpl = QUEST_TEMPLATES[template_key]
        reward = self._calc_reward(template_key, amount, level)
        xp = self._calc_xp(template_key, level)
        fmt = {"plant": plant, "amount": amount, "reward": reward, "xp": xp}
        texts = tpl[lang]

        return {
            "id":            tpl["id"].format(**fmt),
            "title":         texts["title"].format(**fmt),
            "desc":          texts["desc"].format(**fmt),
            "reward":        texts["reward"].format(**fmt),
            "difficulty":    tpl["difficulty"],
            "target_plant":  plant,
            "target_amount": amount,
            "reward_data":   {"coins": reward, "xp": xp},
        }

    def _calc_reward(self, template_key: str, amount: int, level: int) -> int:
        base = {"easy": 50, "medium": 150, "hard": 300}
        diff = QUEST_TEMPLATES[template_key]["difficulty"]
        # earn_money measures {amount} in coins, not in items, so a rich player
        # asking for quests produced amounts in the thousands and the old
        # unbounded `amount * 0.05` term paid out tens of thousands of coins for
        # one quest. Cap the size bonus at 3x whatever the difficulty is worth.
        size_bonus = min(1 + amount * 0.05, 3.0)
        return int(base[diff] * (1 + level * 0.1) * size_bonus)

    def _calc_xp(self, template_key: str, level: int) -> int:
        base = {"easy": 20, "medium": 50, "hard": 100}
        diff = QUEST_TEMPLATES[template_key]["difficulty"]
        return int(base[diff] * (1 + level * 0.05))
