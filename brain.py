"""
brain.py — GrowGPT's intent engine.

Understands the player without any external API: keyword scoring picks an
intent, then a response template is filled with live market data.

Matching runs on normalised words (no accents, no plurals) on both sides, so
"plantes" now reaches the same intent as "planter" — the previous exact-string
comparison understood one and not the other.
"""
import json
import os
import random

from text_utils import (
    DEFAULT_LANG,
    close_enough,
    normalize_lang,
    normalize_phrase,
    normalize_token,
    tokenize,
)


# =========================
# INTENTIONS & MOTS-CLÉS
# Chaque intention a un score calculé selon les mots présents
# =========================
INTENTS = {
    "plant_advice": {
        "fr": ["planter", "quoi planter", "cultiver", "meilleure plante", "plante", "graine",
                "semer", "que planter", "plante rentable", "rapide", "culture"],
        "en": ["plant", "what to plant", "grow", "best plant", "seed", "sow",
                "farming", "crop", "what should i plant", "fast plant"]
    },
    "sell_advice": {
        "fr": ["vendre", "vente", "prix", "marché", "argent", "profit", "rentable",
                "combien", "valeur", "vaut", "bénéfice", "revendre"],
        "en": ["sell", "sale", "price", "market", "money", "profit", "worth",
                "how much", "value", "revenue", "income"]
    },
    "quest": {
        "fr": ["quête", "mission", "objectif", "défi", "tâche", "quoi faire",
                "qu'est-ce que je dois faire", "challenge", "but"],
        "en": ["quest", "mission", "objective", "challenge", "task", "what to do",
                "what should i do", "goal"]
    },
    "mutation": {
        "fr": ["mutation", "mutations", "muter", "mutant", "évoluer", "mutation rare",
                "plante mutée", "comment avoir une mutation", "avoir des mutations",
                "comment muter", "plante mute"],
        "en": ["mutation", "mutations", "mutate", "mutant", "evolve", "rare mutation",
                "mutated plant", "how to get mutation", "how to mutate"]
    },
    "level": {
        "fr": ["niveau", "xp", "expérience", "progresser", "monter", "avancer",
                "level", "comment progresser", "grandir"],
        "en": ["level", "xp", "experience", "progress", "level up", "advance",
                "how to progress", "grow faster"]
    },
    "help": {
        "fr": ["aide", "aider", "help", "que fais-tu", "qui es-tu", "tu fais quoi",
                "comment ça marche", "c'est quoi", "explique"],
        "en": ["help", "what do you do", "who are you", "how does it work",
                "what is this", "explain", "what can you do"]
    },
    "greeting": {
        "fr": ["bonjour", "salut", "coucou", "hey", "bonsoir", "yo", "allô",
                "ça va", "comment tu vas", "hello"],
        "en": ["hello", "hi", "hey", "good morning", "good evening", "yo",
                "sup", "howdy", "greetings", "what's up"]
    },
    "thanks": {
        "fr": ["merci", "thanks", "super", "cool", "parfait", "nickel", "top",
                "génial", "excellent", "bravo"],
        "en": ["thanks", "thank you", "great", "cool", "perfect", "awesome",
                "nice", "excellent", "brilliant", "cheers"]
    }
}


def _load_extra_keywords() -> dict:
    """
    Keywords learned from real usage, read from keywords_extra.json.

    upgrader.py opens a pull request against that file; loading it here is what
    makes merging the PR mean anything — before, the suggestions landed in a
    file nothing imported. Only keys naming a known intent are honoured, so the
    upgrader's `pending_review` bucket stays inert until a human triages it.
    A missing or malformed file is not an error: the bot falls back to its
    built-in keywords.
    """
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "keywords_extra.json")
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        intent: [str(w) for w in words]
        for intent, words in data.items()
        if intent in INTENTS and isinstance(words, list)
    }


EXTRA_KEYWORDS = _load_extra_keywords()

# Keywords normalised once at import, exactly as player input will be. Both
# sides must go through the same folding or the comparison silently misses.
_NORMALIZED_INTENTS = {
    intent: (
        {normalize_phrase(kw) for kws in langs.values() for kw in kws}
        | {normalize_phrase(kw) for kw in EXTRA_KEYWORDS.get(intent, [])}
    )
    for intent, langs in INTENTS.items()
}

# Single words only, used for the fuzzy pass. Multi-word keywords are excluded:
# edit distance across a bigram matches far too loosely.
_FUZZY_KEYWORDS = {
    intent: [kw for kw in kws if " " not in kw]
    for intent, kws in _NORMALIZED_INTENTS.items()
}

_FR_MARKERS = {normalize_token(w) for w in [
    "le", "la", "les", "de", "du", "un", "une", "je", "tu", "il",
    "nous", "vous", "est", "sont", "quoi", "que", "qui", "ça", "mes", "mon",
]}
_EN_MARKERS = {normalize_token(w) for w in [
    "the", "an", "is", "are", "you", "he", "she", "we",
    "they", "what", "how", "does", "can", "should", "it", "my", "me",
]}
# Words the two lists would otherwise share after folding tell us nothing.
_FR_MARKERS -= _EN_MARKERS & _FR_MARKERS
_EN_MARKERS -= _EN_MARKERS & _FR_MARKERS


def detect_language(message: str, default: str = DEFAULT_LANG) -> str:
    """
    Guess the language, falling back to `default` when the evidence is thin.

    The old version returned French on a tie, which meant every short English
    message ("price?", "hello", "sell my carrots") was answered in French — a
    tie is exactly what a short message produces. Returning the caller's
    declared language instead lets Roblox settle it, since the game knows the
    player's locale and we do not.
    """
    words = set(tokenize(message))
    fr_score = len(words & _FR_MARKERS)
    en_score = len(words & _EN_MARKERS)
    if en_score > fr_score:
        return "en"
    if fr_score > en_score:
        return "fr"
    return normalize_lang(default)


def score_intent(message: str) -> str:
    """
    Score every intent against the message and return the strongest.

    Bigrams count double: "quoi planter" is far better evidence than "plante"
    appearing on its own.
    """
    tokens = set(tokenize(message))
    if not tokens:
        return "unknown"

    scores = {
        intent: sum(2 if " " in kw else 1 for kw in kws if kw in tokens)
        for intent, kws in _NORMALIZED_INTENTS.items()
    }

    best = max(scores, key=lambda k: scores[k])
    if scores[best] > 0:
        return best

    # Nothing matched exactly. Retry allowing one typo per word before giving
    # up, so "planté", "mutaton" or "vendr" still land somewhere sensible.
    single_tokens = [t for t in tokens if " " not in t]
    fuzzy = {
        intent: sum(
            1 for token in single_tokens
            if any(close_enough(token, kw) for kw in kws)
        )
        for intent, kws in _FUZZY_KEYWORDS.items()
    }
    best_fuzzy = max(fuzzy, key=lambda k: fuzzy[k])
    return best_fuzzy if fuzzy[best_fuzzy] > 0 else "unknown"


# =========================
# RÉPONSES
# =========================
RESPONSES = {
    "plant_advice": {
        "fr": {
            "low_money": [
                "💡 Commence par les {cheap_plant} — peu cher, pousse vite, idéal pour démarrer.",
                "🥕 Avec peu d'argent, misez sur les {cheap_plant}. Rentable et rapide !",
                "🌱 Les {cheap_plant} sont parfaites pour toi maintenant. Économiques et efficaces."
            ],
            "good_money": [
                "💰 Tu as de quoi investir ! Les {best_plant} sont au top du marché ({best_price} 💵).",
                "🌟 Fonce sur les {best_plant} — le meilleur ratio gain/temps en ce moment.",
                "📈 Le marché favorise les {best_plant} ({best_price} 💵). C'est le bon moment."
            ],
            "has_plant": [
                "🍅 Tes {current_plant} valent {current_price} 💵 en ce moment — continue !",
                "👀 Garde tes {current_plant}, le prix est bon ({current_price} 💵)."
            ],
            "default": [
                "🌿 Regarde les prix du marché avant de planter — envoie /market_advice !",
                "🤔 Dis-moi ton budget et tes plantes actuelles pour un meilleur conseil."
            ]
        },
        "en": {
            "low_money": [
                "💡 Start with {cheap_plant} — cheap, fast, perfect for beginners.",
                "🥕 Low budget? Go for {cheap_plant}. Quick profit!",
                "🌱 {cheap_plant} is your best bet right now. Affordable and efficient."
            ],
            "good_money": [
                "💰 You've got funds! {best_plant} is ruling the market ({best_price} 💵).",
                "🌟 Go all in on {best_plant} — best gain/time ratio right now.",
                "📈 Market loves {best_plant} ({best_price} 💵). Perfect timing."
            ],
            "has_plant": [
                "🍅 Your {current_plant} is worth {current_price} 💵 right now — keep going!",
                "👀 Hold your {current_plant}, the price is great ({current_price} 💵)."
            ],
            "default": [
                "🌿 Check market prices before planting — call /market_advice!",
                "🤔 Tell me your budget and current plants for a better tip."
            ]
        }
    },
    "sell_advice": {
        "fr": {
            "high_price": [
                "🔥 VENDEZ {best_plant} maintenant ! Prix au max : {best_price} 💵 !",
                "📊 Le {best_plant} flambe à {best_price} 💵 — c'est le moment de vendre !",
                "💸 Ne ratez pas ça : {best_plant} à {best_price} 💵. Vendez vite !"
            ],
            "low_price": [
                "⏳ Attendez un peu — les prix sont bas. Le {best_plant} est à {best_price} 💵.",
                "😴 Mauvais moment pour vendre. Revenez dans 5-10 min.",
                "📉 Marché calme. Gardez vos plantes et repassez plus tard."
            ],
            "default": [
                "💰 Les meilleurs prix maintenant : {price_summary}",
                "📈 Conseil du marché : {price_summary}"
            ]
        },
        "en": {
            "high_price": [
                "🔥 SELL {best_plant} NOW! Price is at max: {best_price} 💵!",
                "📊 {best_plant} is surging at {best_price} 💵 — time to sell!",
                "💸 Don't miss it: {best_plant} at {best_price} 💵. Sell fast!"
            ],
            "low_price": [
                "⏳ Wait a bit — prices are low. {best_plant} is at {best_price} 💵.",
                "😴 Bad time to sell. Check back in 5-10 min.",
                "📉 Quiet market. Keep your plants and come back later."
            ],
            "default": [
                "💰 Best prices right now: {price_summary}",
                "📈 Market tip: {price_summary}"
            ]
        }
    },
    "mutation": {
        "fr": [
            "🧬 Les mutations sont aléatoires mais favorisées par la densité de plantation.",
            "🌿 Plante en masse pour multiplier tes chances de mutation !",
            "✨ Certaines plantes mutent plus facilement que d'autres — les {mutation_plant} par exemple.",
            "🔬 Astuce : les plantes en bonne santé et bien arrosées mutent plus souvent."
        ],
        "en": [
            "🧬 Mutations are random but favored by high planting density.",
            "🌿 Plant in bulk to multiply your mutation chances!",
            "✨ Some plants mutate more easily — like {mutation_plant} for example.",
            "🔬 Tip: healthy, well-watered plants mutate more often."
        ]
    },
    "level": {
        "fr": [
            "⭐ Pour monter vite : vends souvent, complète des quêtes et plante en continu.",
            "📈 Les quêtes donnent le plus d'XP ! Tape /quests pour voir celles disponibles.",
            "🚀 Niveau {level} ? Concentre-toi sur les plantes à {xp_advice}.",
            "💡 Astuce de progression : diversifie tes cultures pour plus d'XP."
        ],
        "en": [
            "⭐ To level up fast: sell often, complete quests, and keep planting.",
            "📈 Quests give the most XP! Type /quests to see available ones.",
            "🚀 Level {level}? Focus on {xp_advice} plants.",
            "💡 Progression tip: diversify your crops for more XP."
        ]
    },
    "quest": {
        "fr": [
            "🎯 Je t'ai trouvé des quêtes adaptées à ton niveau ! Tape /quests pour les voir.",
            "📋 Tu as des missions disponibles — vérifie avec /quests.",
            "🏆 Les quêtes du moment : vends {quest_plant}, récolte {quest_amount} plantes.",
            "⚔️ Défi du jour : {daily_challenge}. Vas-y, tu peux le faire !"
        ],
        "en": [
            "🎯 I found quests suited to your level! Type /quests to see them.",
            "📋 You have missions available — check with /quests.",
            "🏆 Current quests: sell {quest_plant}, harvest {quest_amount} plants.",
            "⚔️ Daily challenge: {daily_challenge}. Go for it!"
        ]
    },
    "help": {
        "fr": [
            "🌱 Je suis GrowGPT, ton assistant jardinage IA !\n\n"
            "Je peux :\n"
            "• 🌿 Conseiller quoi planter selon le marché\n"
            "• 💰 Te dire quand vendre au meilleur prix\n"
            "• 🎯 Créer et suggérer des quêtes\n"
            "• 🧬 T'aider sur les mutations\n"
            "• ⭐ T'aider à progresser\n\n"
            "Pose-moi n'importe quelle question !"
        ],
        "en": [
            "🌱 I'm GrowGPT, your AI gardening assistant!\n\n"
            "I can:\n"
            "• 🌿 Advise what to plant based on the market\n"
            "• 💰 Tell you when to sell at the best price\n"
            "• 🎯 Create and suggest quests\n"
            "• 🧬 Help you with mutations\n"
            "• ⭐ Help you progress\n\n"
            "Ask me anything!"
        ]
    },
    "greeting": {
        "fr": [
            "👋 Salut {name} ! Prêt à cultiver ? Dis-moi ce dont tu as besoin 🌱",
            "🌿 Hey {name} ! Le jardin t'attend. Qu'est-ce que je peux faire pour toi ?",
            "🌱 Bonjour {name} ! Le marché est {market_mood} aujourd'hui. Comment je t'aide ?"
        ],
        "en": [
            "👋 Hey {name}! Ready to grow? Tell me what you need 🌱",
            "🌿 Hi {name}! The garden awaits. What can I do for you?",
            "🌱 Hello {name}! The market is {market_mood} today. How can I help?"
        ]
    },
    "thanks": {
        "fr": [
            "😊 Avec plaisir ! N'hésite pas si tu as d'autres questions.",
            "🌱 De rien ! Bonne récolte {name} !",
            "✅ Content d'avoir pu t'aider. À bientôt sur le marché !"
        ],
        "en": [
            "😊 You're welcome! Don't hesitate if you have more questions.",
            "🌱 No problem! Happy farming {name}!",
            "✅ Glad I could help. See you on the market!"
        ]
    },
    "unknown": {
        "fr": [
            "🤔 Hmm, je n'ai pas bien compris. Tu parles de plantes, de ventes ou de quêtes ?",
            "🌱 Peux-tu reformuler ? Je peux t'aider sur le marché, les quêtes ou les plantes.",
            "❓ Je suis spécialisé jardinage ! Pose-moi une question sur les plantes ou le marché.",
            "😅 Pas sûr de comprendre... Tu veux un conseil plante ou marché ?"
        ],
        "en": [
            "🤔 Hmm, I didn't quite understand. Are you asking about plants, sales or quests?",
            "🌱 Can you rephrase? I can help with market, quests or plants.",
            "❓ I'm a gardening specialist! Ask me about plants or the market.",
            "😅 Not sure I follow... Want a plant or market tip?"
        ]
    }
}


class GrowBrain:
    def __init__(self, memory, prices, quests):
        self.memory = memory
        self.prices = prices
        self.quests = quests

    def respond(self, player_id: str, message: str, player: dict, lang: str = "fr") -> str:
        # The language Roblox declares is the starting point; detection only
        # overrides it when the message clearly says otherwise. The old code
        # discarded the caller's value outright and trusted a detector that
        # answers "fr" whenever it is unsure.
        lang = detect_language(message, default=normalize_lang(lang))

        intent = score_intent(message)

        # Player context
        player = player or {}
        level  = player.get("level", 1) or 1
        money  = player.get("money", 0) or 0
        plants = player.get("plants", []) or []
        name   = player.get("name", "Farmer")

        # Historique mémoire
        history = self.memory.get(player_id) or {}

        # Anti-spam : même intention répétée
        if history.get("last_intent") == intent and intent not in ("greeting", "thanks", "help"):
            prefix = {
                "fr": "🔄 On en a déjà parlé, mais voici une autre perspective :\n",
                "en": "🔄 We talked about this, but here's another angle:\n"
            }[lang]
        else:
            prefix = ""

        response = self._build_response(intent, lang, player, level, money, plants, name)
        self.memory.update(player_id, {"last_intent": intent, "last_message": message})

        return prefix + response

    def _build_response(self, intent: str, lang: str,
                         player: dict, level: int, money: int,
                         plants: list, name: str) -> str:

        current_prices = self.prices.current()
        best_plant, best_price = self.prices.best_to_sell()
        cheap_plant, cheap_price = self.prices.cheapest_to_plant()
        market_mood = self.prices.market_mood(lang)

        # Construire le résumé des prix
        price_summary = ", ".join(
            f"{p}: {v}💵" for p, v in list(current_prices.items())[:3]
        ) if current_prices else ("aucun prix dispo" if lang == "fr" else "no prices available")

        # Quest filler. hint_plant() is deliberately side-effect free: calling
        # suggest() here would write a catalog entry per suggested quest on
        # every single chat message, just to obtain one crop name.
        quest_plant = self.quests.hint_plant(player)
        quest_amount = 10
        daily_challenge = (
            "Vends 5 plantes rares en 10 min" if lang == "fr"
            else "Sell 5 rare plants in 10 min"
        )

        # Resolve the player's current crop. Roblox sends display casing, the
        # price table is keyed lowercase.
        current_plant = str(plants[0]).lower() if plants else best_plant
        current_price = current_prices.get(current_plant, best_price)

        # XP advice selon level
        xp_advice = (
            ("communes" if lang == "fr" else "common")
            if level < 5 else
            ("rares" if lang == "fr" else "rare")
        )

        # Mutation plant
        mutation_plant = "tomate" if lang == "fr" else "tomato"

        # Sélection du sous-type de réponse
        if intent == "plant_advice":
            pool_key = (
                "low_money" if money < 100
                else "has_plant" if plants
                else "good_money"
            )
            pool = RESPONSES["plant_advice"][lang].get(pool_key,
                   RESPONSES["plant_advice"][lang]["default"])

        elif intent == "sell_advice":
            pool_key = "high_price" if best_price > 50 else "low_price"
            pool = RESPONSES["sell_advice"][lang].get(pool_key,
                   RESPONSES["sell_advice"][lang]["default"])

        elif intent in RESPONSES:
            pool = RESPONSES[intent][lang] if isinstance(RESPONSES[intent], dict) else RESPONSES[intent]
            if isinstance(pool, dict):
                pool = pool.get("default", ["..."])
        else:
            pool = RESPONSES["unknown"][lang]

        template = random.choice(pool)

        # Any reply that quotes a number has to say when that number is not
        # actually live, otherwise stale or fallback prices are indistinguishable
        # from real ones — which is the exact failure this project cares about.
        caveat = (
            self.prices.freshness_warning(lang)
            if intent in ("plant_advice", "sell_advice") else ""
        )

        filled = template.format(
            name=name,
            level=level,
            money=money,
            best_plant=best_plant,
            best_price=best_price,
            cheap_plant=cheap_plant,
            cheap_price=cheap_price,
            current_plant=current_plant,
            current_price=current_price,
            price_summary=price_summary,
            market_mood=market_mood,
            quest_plant=quest_plant,
            quest_amount=quest_amount,
            daily_challenge=daily_challenge,
            xp_advice=xp_advice,
            mutation_plant=mutation_plant,
        )
        return filled + caveat
