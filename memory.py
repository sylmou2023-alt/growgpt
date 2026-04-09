"""
core/memory.py — Mémoire des joueurs
Stocke les interactions pour personnaliser les réponses.
"""
import time


class MemoryStore:
    def __init__(self):
        self._store = {}   # player_id -> dict

    def get(self, player_id: str) -> dict | None:
        return self._store.get(player_id)

    def update(self, player_id: str, data: dict):
        if player_id not in self._store:
            self._store[player_id] = {"first_seen": time.time(), "interaction_count": 0}
        self._store[player_id].update(data)
        self._store[player_id]["last_seen"]         = time.time()
        self._store[player_id]["interaction_count"] = \
            self._store[player_id].get("interaction_count", 0) + 1

    def total_players(self) -> int:
        return len(self._store)

    def all_interactions(self) -> list:
        """Retourne toutes les interactions pour l'analyse d'upgrade."""
        result = []
        for pid, data in self._store.items():
            result.append({
                "player_id":         pid,
                "interaction_count": data.get("interaction_count", 0),
                "last_intent":       data.get("last_intent", "unknown"),
                "last_message":      data.get("last_message", ""),
            })
        return result

    def most_common_intents(self) -> dict:
        """Compte les intentions les plus fréquentes."""
        counts = {}
        for data in self._store.values():
            intent = data.get("last_intent", "unknown")
            counts[intent] = counts.get(intent, 0) + 1
        return dict(sorted(counts.items(), key=lambda x: x[1], reverse=True))

    def unknown_messages(self) -> list:
        """Messages qui n'ont pas été compris (intent=unknown)."""
        return [
            data.get("last_message", "")
            for data in self._store.values()
            if data.get("last_intent") == "unknown"
        ]
