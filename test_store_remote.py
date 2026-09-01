"""
test_store_remote.py — Exercise the Upstash REST path without an account.

test_growgpt.py only ever runs store.py in its in-memory fallback, which means
the entire Redis code path would otherwise be discovered in production. This
spins up a local HTTP server speaking the subset of the Upstash REST protocol
that store.py uses, points a Store at it, and checks the wire format, the JSON
round trip, the counters, the capped list and the circuit breaker.

Run with:  python test_store_remote.py
"""
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

PASSED = []
FAILED = []


def check(name, condition, detail=""):
    (PASSED if condition else FAILED).append((name, detail))
    print("%s %s%s" % ("  ok  " if condition else " FAIL ", name,
                       ("  -> " + detail) if detail and not condition else ""))


class FakeRedis:
    """Just enough Redis to serve store.py."""

    def __init__(self):
        self.values = {}
        self.sets = {}
        self.hashes = {}
        self.lists = {}
        self.expiry = {}
        self.seen_commands = []
        self.auth_headers = []

    def run(self, args):
        self.seen_commands.append(args)
        cmd = args[0].upper()

        if cmd == "SET":
            self.values[args[1]] = args[2]
            if len(args) >= 5 and args[3].upper() == "EX":
                self.expiry[args[1]] = int(args[4])
            return "OK"
        if cmd == "GET":
            return self.values.get(args[1])
        if cmd == "DEL":
            return int(self.values.pop(args[1], None) is not None)
        if cmd == "SADD":
            bucket = self.sets.setdefault(args[1], set())
            added = args[2] not in bucket
            bucket.add(args[2])
            return int(added)
        if cmd == "SCARD":
            return len(self.sets.get(args[1], ()))
        if cmd == "SMEMBERS":
            return sorted(self.sets.get(args[1], ()))
        if cmd == "HINCRBY":
            bucket = self.hashes.setdefault(args[1], {})
            bucket[args[2]] = bucket.get(args[2], 0) + int(args[3])
            return bucket[args[2]]
        if cmd == "HGETALL":
            flat = []
            for field, value in self.hashes.get(args[1], {}).items():
                flat += [field, str(value)]
            return flat
        if cmd == "RPUSH":
            self.lists.setdefault(args[1], []).append(args[2])
            return len(self.lists[args[1]])
        if cmd == "LTRIM":
            bucket = self.lists.setdefault(args[1], [])
            start = int(args[2])
            self.lists[args[1]] = bucket[start:] if start < 0 else bucket[start:]
            return "OK"
        if cmd == "LRANGE":
            return list(self.lists.get(args[1], []))
        raise AssertionError("unsupported command reached the server: %r" % (args,))


FAKE = FakeRedis()
FAIL_MODE = {"on": False}


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if FAIL_MODE["on"]:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"{}")
            return

        FAKE.auth_headers.append(self.headers.get("Authorization"))
        length = int(self.headers.get("Content-Length", 0))
        args = json.loads(self.rfile.read(length).decode("utf-8"))
        try:
            result = FAKE.run(args)
            payload = {"result": result}
        except AssertionError as exc:
            payload = {"error": str(exc)}

        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


server = HTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
PORT = server.server_address[1]

import os
os.environ["UPSTASH_REDIS_REST_URL"] = "http://127.0.0.1:%d" % PORT
os.environ["UPSTASH_REDIS_REST_TOKEN"] = "fake_token"

from store import Store

s = Store()

print("\n=== Transport ===")
check("store reports upstash mode", s.backend() == "upstash", s.backend())
s.set_json("k", {"hello": "wörld", "n": 3})
check("bearer token is sent",
      FAKE.auth_headers and FAKE.auth_headers[-1] == "Bearer fake_token",
      str(FAKE.auth_headers[-1:]))
check("command is sent as a JSON array",
      FAKE.seen_commands[-1][0] == "SET", str(FAKE.seen_commands[-1][:1]))

print("\n=== JSON round trip ===")
check("value survives the round trip", s.get_json("k") == {"hello": "wörld", "n": 3},
      repr(s.get_json("k")))
check("non-ascii is preserved", s.get_json("k")["hello"] == "wörld")
check("missing key returns the default",
      s.get_json("absent", default="fallback") == "fallback")

print("\n=== TTL ===")
s.set_json("with_ttl", [1, 2], ttl_seconds=60)
check("ttl is passed as EX",
      FAKE.expiry.get("with_ttl") == 60, str(FAKE.expiry))

print("\n=== Sets ===")
s.sadd("players", "p1")
s.sadd("players", "p2")
s.sadd("players", "p1")
check("set counts distinct members", s.scard("players") == 2, str(s.scard("players")))
check("smembers returns them", sorted(s.smembers("players")) == ["p1", "p2"],
      str(s.smembers("players")))

print("\n=== Hash counters ===")
s.hincr("stats", "quest", 1)
s.hincr("stats", "quest", 4)
s.hincr("stats", "plant_advice", 2)
got = s.hgetall("stats")
check("counters accumulate server-side", got.get("quest") == 5, str(got))
check("hgetall decodes the flat array", got.get("plant_advice") == 2, str(got))
check("hgetall values are ints", all(isinstance(v, int) for v in got.values()), str(got))

print("\n=== Capped list ===")
for i in range(10):
    s.push_capped("log", {"i": i}, maxlen=5)
entries = s.list_all("log")
check("list is trimmed to maxlen", len(entries) == 5, str(len(entries)))
check("list keeps the newest entries",
      [e["i"] for e in entries] == [5, 6, 7, 8, 9], str([e["i"] for e in entries]))

print("\n=== Cache ===")
before = len(FAKE.seen_commands)
s.get_json("k", cache_ttl=30)
s.get_json("k", cache_ttl=30)
s.get_json("k", cache_ttl=30)
check("cached reads skip the network",
      len(FAKE.seen_commands) - before == 1,
      "%d commands issued" % (len(FAKE.seen_commands) - before))
s.set_json("k", {"changed": True})
check("a write invalidates the cache",
      s.get_json("k", cache_ttl=30) == {"changed": True}, repr(s.get_json("k")))

print("\n=== Survives a restart (the whole point) ===")
# prices.py and quests.py talk to the module-level singleton, which picked up
# the fake server because the environment was set before store was imported.
os.environ["ROBLOX_SECRET"] = "test_secret"
from prices import PriceManager
from quests import QuestEngine

first_boot = PriceManager()
first_boot.update({"carrot": 999})
check("price is readable in the same process",
      first_boot.current().get("carrot") == 999,
      str(first_boot.current().get("carrot")))

# A Render restart is exactly this: brand new objects, same Redis.
after_restart = PriceManager()
check("price survives a restart",
      after_restart.current().get("carrot") == 999,
      str(after_restart.current().get("carrot")))
check("freshness survives a restart too",
      after_restart.freshness() == "fresh", after_restart.freshness())

quests_before = QuestEngine(after_restart)
quests_before.refresh_market_quests()
offered = quests_before.suggest({"level": 2, "money": 50}, "fr")
accepted = quests_before.accept("restart_player", offered[0]["id"], "fr")
check("quest accepted before restart", accepted.get("ok") is True, str(accepted))

quests_after = QuestEngine(PriceManager())
still_active = quests_after.get_active("restart_player")
check("active quest survives a restart",
      len(still_active) == 1 and still_active[0]["id"] == offered[0]["id"],
      str(still_active))

print("\n=== Circuit breaker ===")
FAIL_MODE["on"] = True
for _ in range(4):
    s.get_json("k")
check("breaker opens after repeated failures",
      s.backend().startswith("memory"), s.backend())
check("reads still work from the fallback while the breaker is open",
      s.get_json("k") == {"changed": True}, repr(s.get_json("k")))
before = len(FAKE.seen_commands)
FAIL_MODE["on"] = False
s.get_json("k")
check("breaker stays open during cooldown, no network hit",
      len(FAKE.seen_commands) == before,
      "%d extra commands" % (len(FAKE.seen_commands) - before))
check("an error is reported for diagnostics", bool(s.last_error()), str(s.last_error()))

print("\n=== Unserialisable value ===")
check("a bad value is refused, not raised",
      s.set_json("bad", {1, 2, 3}) is False)

server.shutdown()
print("\n" + "=" * 50)
print("%d passed, %d failed" % (len(PASSED), len(FAILED)))
if FAILED:
    print("\nFailures:")
    for name, detail in FAILED:
        print("  - %s  %s" % (name, detail))
sys.exit(1 if FAILED else 0)
