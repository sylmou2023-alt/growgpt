"""
core/quests.py — Moteur de quêtes dynamiques
Génère, suggère et gère les quêtes en fonction du marché et du joueur.
"""
import time
import random


# =========================
# CATALOGUE DE QUÊTES
# Les valeurs {plant}, {amount}, {reward} sont remplies dynamiquement
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

RARE_PLANTS    = ["rose", "sunflower", "blueberry", "strawberry"]
COMMON_PLANTS  = ["carrot", "potato", "wheat", "corn"]


class QuestEngine:
    def __init__(self, prices):
        self.prices       = prices
        self._active      = {}     # player_id -> list of active quests
        self._market_quests = []   # quêtes basées sur le marché actuel

    def count_active(self) -> int:
        return sum(len(v) for v in self._active.values())

    def refresh_market_quests(self):
        """
        Appelé quand les prix changent.
        Génère des quêtes ciblant les plantes les plus rentables.
        """
        best_plant, best_price = self.prices.best_to_sell()
        self._market_quests = [
            self._build_quest("sell_plant",
                               plant=best_plant,
                               amount=5,
                               level=1),
            self._build_quest("sell_at_peak",
                               plant=best_plant,
                               amount=3,
                               level=5),
        ]

    def suggest(self, player: dict, lang: str = "fr") -> list:
        """Retourne les quêtes suggérées pour ce joueur."""
        level  = player.get("level", 1)
        money  = player.get("money", 0)
        plants = player.get("plants", [])

        suggested = []

        # Quête journalière toujours présente
        suggested.append(self._build_quest("daily_grind", plant="any", amount=1, level=level, lang=lang))

        # Quêtes selon niveau
        if level < 5:
            suggested.append(self._build_quest("sell_plant",
                                                plant=random.choice(COMMON_PLANTS),
                                                amount=5, level=level, lang=lang))
            suggested.append(self._build_quest("harvest_bulk",
                                                plant="any", amount=10, level=level, lang=lang))
        else:
            suggested.append(self._build_quest("plant_rare",
                                                plant=random.choice(RARE_PLANTS),
                                                amount=3, level=level, lang=lang))
            suggested.append(self._build_quest("earn_money",
                                                plant="any",
                                                amount=max(100, money // 2),
                                                level=level, lang=lang))

        # Quêtes marché si disponibles
        for mq in self._market_quests:
            mq_copy = dict(mq)
            mq_copy["lang"] = lang
            suggested.append(mq_copy)

        # Quête basée sur les plantes du joueur
        if plants:
            p = random.choice(plants)
            suggested.append(self._build_quest("sell_plant",
                                                plant=p, amount=8, level=level, lang=lang))

        return suggested[:4]  # max 4 suggestions

    def accept(self, player_id: str, quest_id: str, lang: str = "fr") -> dict:
        """Accepte une quête pour un joueur."""
        if player_id not in self._active:
            self._active[player_id] = []

        # Vérifier si déjà active
        for q in self._active[player_id]:
            if q["id"] == quest_id:
                msg = {
                    "fr": f"❌ Tu as déjà cette quête en cours !",
                    "en": f"❌ You already have this quest active!"
                }[lang]
                return {"ok": False, "message": msg}

        # Trouver la quête dans les suggestions
        quest = self._find_quest(quest_id, lang)
        if not quest:
            msg = {
                "fr": "❌ Quête introuvable. Vérifie l'ID.",
                "en": "❌ Quest not found. Check the ID."
            }[lang]
            return {"ok": False, "message": msg}

        quest["accepted_at"] = time.time()
        quest["progress"]    = 0
        self._active[player_id].append(quest)

        msg = {
            "fr": f"✅ Quête acceptée : {quest.get('title', quest_id)} ! Bonne chance 🌱",
            "en": f"✅ Quest accepted: {quest.get('title', quest_id)}! Good luck 🌱"
        }[lang]
        return {"ok": True, "message": msg, "quest": quest}

    def complete(self, player_id: str, quest_id: str, lang: str = "fr") -> dict:
        """Marque une quête comme complétée."""
        if player_id not in self._active:
            msg = {
                "fr": "❌ Aucune quête active trouvée.",
                "en": "❌ No active quest found."
            }[lang]
            return {"ok": False, "message": msg}

        for i, q in enumerate(self._active[player_id]):
            if q["id"] == quest_id:
                self._active[player_id].pop(i)
                msg = {
                    "fr": f"🎉 Quête terminée ! Tu reçois : {q.get('reward', '?')}",
                    "en": f"🎉 Quest complete! You receive: {q.get('reward', '?')}"
                }[lang]
                return {"ok": True, "message": msg, "reward": q.get("reward_data", {})}

        msg = {
            "fr": "❌ Quête non trouvée dans tes quêtes actives.",
            "en": "❌ Quest not found in your active quests."
        }[lang]
        return {"ok": False, "message": msg}

    def get_active(self, player_id: str) -> list:
        return self._active.get(player_id, [])

    # =========================
    # PRIVÉ
    # =========================
    def _build_quest(self, template_key: str, plant: str,
                      amount: int, level: int, lang: str = "fr") -> dict:
        tpl    = QUEST_TEMPLATES[template_key]
        reward = self._calc_reward(template_key, amount, level)
        xp     = self._calc_xp(template_key, level)

        # Formater les chaînes
        fmt = {
            "plant":  plant,
            "amount": amount,
            "reward": reward,
            "xp":     xp
        }

        quest_id = tpl["id"].format(**fmt)
        texts    = tpl[lang]

        return {
            "id":           quest_id,
            "title":        texts["title"].format(**fmt),
            "desc":         texts["desc"].format(**fmt),
            "reward":       texts["reward"].format(**fmt),
            "difficulty":   tpl["difficulty"],
            "target_plant": plant,
            "target_amount": amount,
            "reward_data":  {"coins": reward, "xp": xp}
        }

    def _find_quest(self, quest_id: str, lang: str) -> dict | None:
        """Reconstruit une quête à partir de son ID (best-effort)."""
        # On parcourt tous les templates pour trouver un match
        for key in QUEST_TEMPLATES:
            for plant in COMMON_PLANTS + RARE_PLANTS + ["any"]:
                for amount in [1, 3, 5, 8, 10, 15, 20, 50, 100]:
                    q = self._build_quest(key, plant, amount, 1, lang)
                    if q["id"] == quest_id:
                        return q
        return None

    def _calc_reward(self, template_key: str, amount: int, level: int) -> int:
        base = {"easy": 50, "medium": 150, "hard": 300}
        diff = QUEST_TEMPLATES[template_key]["difficulty"]
        return int(base[diff] * (1 + level * 0.1) * (1 + amount * 0.05))

    def _calc_xp(self, template_key: str, level: int) -> int:
        base = {"easy": 20, "medium": 50, "hard": 100}
        diff = QUEST_TEMPLATES[template_key]["difficulty"]
        return int(base[diff] * (1 + level * 0.05))
