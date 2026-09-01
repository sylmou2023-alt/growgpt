"""
memory.py — Per-player memory and aggregate usage stats.

Backed by store.py, so a Render restart no longer forgets every player. Beyond
persistence this module now owns the intent statistics: brain.py already knows
which intent it matched, so recording it here at the source is both correct and
cheap. upgrader.py used to re-derive intents by grepping its own replies, which
was guesswork on top of data it already had.
"""
import time

from store import store

_PLAYER_KEY = "growgpt:player:%s"
_PLAYER_INDEX = "growgpt:players"
_INTENT_STATS = "growgpt:stats:intents"
_UNKNOWN_LOG = "growgpt:stats:unknown"

# Forget a player who has not shown up in 30 days. Keeps the free Upstash tier
# from filling with one-visit accounts.
_PLAYER_TTL = 30 * 24 * 3600

# How many unmatched messages to keep for the upgrade analysis.
_UNKNOWN_MAX = 300

# Bound on how many players all_interactions() will fetch, since each one is a
# separate Redis round trip.
_SCAN_LIMIT = 100


class MemoryStore:
    def get(self, player_id: str):
        return store.get_json(_PLAYER_KEY % player_id)

    def update(self, player_id: str, data: dict):
        record = self.get(player_id)
        if not record:
            record = {"first_seen": time.time(), "interaction_count": 0}
            store.sadd(_PLAYER_INDEX, player_id)

        record.update(data or {})
        record["last_seen"] = time.time()
        record["interaction_count"] = record.get("interaction_count", 0) + 1
        store.set_json(_PLAYER_KEY % player_id, record, ttl_seconds=_PLAYER_TTL)

        # Aggregate counters, incremented atomically so concurrent gunicorn
        # workers do not overwrite each other's totals.
        intent = data.get("last_intent") if data else None
        if intent:
            store.hincr(_INTENT_STATS, intent)
            if intent == "unknown":
                message = (data.get("last_message") or "").strip()
                if message:
                    store.push_capped(_UNKNOWN_LOG, message, _UNKNOWN_MAX)

    def total_players(self) -> int:
        return store.scard(_PLAYER_INDEX)

    def most_common_intents(self) -> dict:
        counts = store.hgetall(_INTENT_STATS)
        return dict(sorted(counts.items(), key=lambda kv: kv[1], reverse=True))

    def unknown_messages(self) -> list:
        """Messages the intent scorer failed to classify, newest last."""
        return store.list_all(_UNKNOWN_LOG)

    def all_interactions(self) -> list:
        """
        Per-player summary, capped at _SCAN_LIMIT players. Only the upgrade
        analysis calls this, and it is admin-triggered rather than on the chat
        path, so the round trips are acceptable.
        """
        result = []
        for pid in store.smembers(_PLAYER_INDEX)[:_SCAN_LIMIT]:
            data = self.get(pid)
            if not data:
                continue
            result.append({
                "player_id": pid,
                "interaction_count": data.get("interaction_count", 0),
                "last_intent": data.get("last_intent", "unknown"),
                "last_message": data.get("last_message", ""),
            })
        return result
