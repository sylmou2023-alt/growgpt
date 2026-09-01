"""
store.py — Persistence layer for GrowGPT.

Every piece of live state (market prices, player memory, active quests) used
to sit in a plain process dict. On Render that meant two separate problems:

  1. Any restart wiped it. The free tier spins the service down after ~15 min
     without traffic, and every deploy restarts it. Prices silently fell back
     to the hardcoded defaults, so the bot kept quoting invented numbers as if
     they were live.
  2. Gunicorn workers do not share memory. Roblox POSTs fresh prices to one
     worker; the player's next question is answered by another worker that
     never saw them.

State now lives in Upstash Redis, reached through its REST API. REST is a
deliberate choice: no new pip dependency (urllib is already used by
upgrader.py), no connection pool to manage, and identical behaviour no matter
how many workers gunicorn spawns.

If the Upstash variables are unset or the service is unreachable, everything
falls back to a process-local structure. The app then behaves exactly as it did
before rather than erroring out, so it stays deployable while the Redis account
is being created. Call backend() to see which mode is live.

Environment variables:
    UPSTASH_REDIS_REST_URL      e.g. https://eu1-xxx-12345.upstash.io
    UPSTASH_REDIS_REST_TOKEN    REST token from the Upstash console
"""
import os
import json
import time
import urllib.request
import urllib.error

# Upstash sits on the critical path of a player's question, so the timeout is
# deliberately short: answering from slightly stale data beats making the
# player wait on a slow network hop.
_TIMEOUT = 3.0

# Circuit breaker. After this many consecutive failures we stop calling Upstash
# for _BREAKER_COOLDOWN seconds and serve from the fallback, so an Upstash
# outage degrades the bot instead of adding 3s to every single request.
_BREAKER_THRESHOLD = 3
_BREAKER_COOLDOWN = 60.0


class Store:
    def __init__(self):
        self._url = (os.environ.get("UPSTASH_REDIS_REST_URL") or "").rstrip("/")
        self._token = os.environ.get("UPSTASH_REDIS_REST_TOKEN") or ""
        self._remote = bool(self._url and self._token)

        # Fallbacks, one per Redis type we use.
        self._values = {}    # key -> python value
        self._sets = {}      # key -> set()
        self._hashes = {}    # key -> {field: int}
        self._lists = {}     # key -> [str]

        self._cache = {}     # key -> (expires_at, value)
        self._failures = 0
        self._blocked_until = 0.0
        self._last_error = None

    # =========================
    # DIAGNOSTICS
    # =========================
    def backend(self) -> str:
        """Which storage is actually serving reads right now."""
        if not self._remote:
            return "memory (UPSTASH_REDIS_REST_* not set)"
        if time.time() < self._blocked_until:
            return "memory (upstash unreachable, retrying shortly)"
        return "upstash"

    def is_persistent(self) -> bool:
        return self._remote and time.time() >= self._blocked_until

    def last_error(self):
        return self._last_error

    # =========================
    # KEY / VALUE
    # =========================
    def get_json(self, key: str, default=None, cache_ttl: float = 0.0):
        """
        Read a JSON value. cache_ttl keeps the result in process memory for
        that many seconds, sparing a network round trip on hot keys such as the
        price table that every chat message reads.
        """
        if cache_ttl > 0:
            cached = self._cache.get(key)
            if cached and cached[0] > time.time():
                return cached[1]

        raw = self._command("GET", key)
        if raw is None:
            value = self._values.get(key, default)
        else:
            try:
                value = json.loads(raw)
            except (ValueError, TypeError):
                value = default

        if cache_ttl > 0:
            self._cache[key] = (time.time() + cache_ttl, value)
        return value

    def set_json(self, key: str, value, ttl_seconds: int = 0) -> bool:
        """
        Write a JSON value. Always updates the local fallback too, so a Redis
        outage degrades to the old in-memory behaviour rather than dropping the
        write. Returns True when it actually reached Redis.
        """
        self._values[key] = value
        self._cache.pop(key, None)

        try:
            payload = json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            self._last_error = "not JSON-serialisable: %s" % exc
            return False

        if ttl_seconds > 0:
            return self._command("SET", key, payload, "EX", str(ttl_seconds)) is not None
        return self._command("SET", key, payload) is not None

    def delete(self, key: str):
        self._values.pop(key, None)
        self._cache.pop(key, None)
        self._command("DEL", key)

    # =========================
    # SET (used to count distinct players)
    # =========================
    def sadd(self, key: str, member: str):
        self._sets.setdefault(key, set()).add(member)
        self._command("SADD", key, member)

    def scard(self, key: str) -> int:
        result = self._command("SCARD", key)
        if result is None:
            return len(self._sets.get(key, ()))
        try:
            return int(result)
        except (TypeError, ValueError):
            return 0

    def smembers(self, key: str) -> list:
        result = self._command("SMEMBERS", key)
        if result is None:
            return sorted(self._sets.get(key, ()))
        return [str(m) for m in result] if isinstance(result, list) else []

    # =========================
    # HASH (used for intent counters)
    # =========================
    def hincr(self, key: str, field: str, amount: int = 1):
        """
        Atomic on Redis, which matters: several gunicorn workers increment the
        same counters and a read-modify-write would lose updates.
        """
        bucket = self._hashes.setdefault(key, {})
        bucket[field] = bucket.get(field, 0) + amount
        self._command("HINCRBY", key, field, str(amount))

    def hgetall(self, key: str) -> dict:
        result = self._command("HGETALL", key)
        if result is None:
            return dict(self._hashes.get(key, {}))
        # Upstash returns a flat [field, value, field, value, ...] array.
        if not isinstance(result, list):
            return {}
        out = {}
        for i in range(0, len(result) - 1, 2):
            try:
                out[str(result[i])] = int(result[i + 1])
            except (TypeError, ValueError):
                continue
        return out

    # =========================
    # LIST (used for the rolling interaction log)
    # =========================
    def push_capped(self, key: str, value, maxlen: int):
        """Append to a list and trim it to the most recent maxlen entries."""
        try:
            payload = json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError):
            return
        bucket = self._lists.setdefault(key, [])
        bucket.append(payload)
        del bucket[:-maxlen]

        if self._command("RPUSH", key, payload) is not None:
            self._command("LTRIM", key, str(-maxlen), "-1")

    def list_all(self, key: str) -> list:
        result = self._command("LRANGE", key, "0", "-1")
        raw = result if isinstance(result, list) else self._lists.get(key, [])
        out = []
        for item in raw:
            try:
                out.append(json.loads(item))
            except (ValueError, TypeError):
                continue
        return out

    # =========================
    # UPSTASH REST TRANSPORT
    # =========================
    def _command(self, *args):
        """
        Run one Redis command. Returns the raw result, or None when Redis is
        unavailable for any reason — callers read None as "use the fallback".
        This never raises: a storage problem must not take down a chat reply.
        """
        if not self._remote or time.time() < self._blocked_until:
            return None

        body = json.dumps([str(a) for a in args]).encode("utf-8")
        req = urllib.request.Request(
            self._url,
            data=body,
            headers={
                "Authorization": "Bearer " + self._token,
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError) as exc:
            self._record_failure(str(exc))
            return None

        if isinstance(payload, dict) and payload.get("error"):
            self._record_failure(str(payload["error"]))
            return None

        self._failures = 0
        self._last_error = None
        return payload.get("result") if isinstance(payload, dict) else None

    def _record_failure(self, message: str):
        self._failures += 1
        self._last_error = message
        if self._failures >= _BREAKER_THRESHOLD:
            self._blocked_until = time.time() + _BREAKER_COOLDOWN
            self._failures = 0


# Single shared instance. Each gunicorn worker gets its own object, which is
# fine: the state that matters lives in Redis, not in the instance.
store = Store()
