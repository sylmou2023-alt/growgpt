"""
test_growgpt.py — Plain-python checks, no test framework needed.

Run with:  python test_growgpt.py

Each case pins down a bug that was actually reachable in production, so a
failure here means a real regression rather than a style preference.
"""
import os
import sys

# Secrets have to exist before app.py is imported, since the module builds its
# startup report at import time.
os.environ.setdefault("ROBLOX_SECRET", "test_roblox_secret")
os.environ.setdefault("ADMIN_SECRET", "test_admin_secret")
# Force the in-memory fallback: these tests must not need a network.
os.environ.pop("UPSTASH_REDIS_REST_URL", None)
os.environ.pop("UPSTASH_REDIS_REST_TOKEN", None)

import app as growgpt_app
from brain import detect_language, score_intent
from text_utils import normalize_lang

PASSED = []
FAILED = []


def check(name, condition, detail=""):
    (PASSED if condition else FAILED).append((name, detail))
    print("%s %s%s" % ("  ok  " if condition else " FAIL ", name,
                       ("  -> " + detail) if detail and not condition else ""))


client = growgpt_app.app.test_client()


def post(path, payload):
    return client.post(path, json=payload)


print("\n=== Language handling ===")
# A short English message carries no French or English marker words, so
# detection ties. It used to resolve to French and answer English players in
# French; the caller's declared language now settles it.
check("short english message honours lang=en",
      detect_language("price?", default="en") == "en",
      detect_language("price?", default="en"))
check("short english message still respects lang=fr",
      detect_language("price?", default="fr") == "fr")
check("clear french overrides a wrong declared lang",
      detect_language("je veux vendre mes carottes", default="en") == "fr")
check("clear english overrides a wrong declared lang",
      detect_language("what should i do with the tomato", default="fr") == "en")
check("unknown language code does not crash",
      normalize_lang("es") == "fr" and normalize_lang("en-US") == "en")

print("\n=== Intent matching ===")
check("plural is understood", score_intent("plantes") == "plant_advice",
      score_intent("plantes"))
check("singular still understood", score_intent("planter") == "plant_advice")
check("accents are optional", score_intent("quete") == "quest",
      score_intent("quete"))
check("typo tolerated", score_intent("mutaton") == "mutation",
      score_intent("mutaton"))
check("gibberish stays unknown", score_intent("azerty qwerty") == "unknown",
      score_intent("azerty qwerty"))

print("\n=== Auth ===")
check("wrong roblox secret rejected",
      post("/update_prices", {"secret": "nope", "prices": {"carrot": 1}}).status_code == 401)
check("published default secret rejected",
      post("/update_prices", {"secret": "change_me", "prices": {"carrot": 1}}).status_code == 401)
check("wrong admin secret rejected",
      post("/trigger_upgrade", {"secret": "admin_secret"}).status_code == 401)
check("correct secret accepted",
      post("/update_prices", {"secret": os.environ["ROBLOX_SECRET"],
                              "prices": {"carrot": 12}}).status_code == 200)
check("malformed body is a 400, not a 500",
      post("/update_prices", {"secret": os.environ["ROBLOX_SECRET"]}).status_code == 400)

print("\n=== Prices ===")
growgpt_app.prices.update({"banana": 40})
best_plant, _ = growgpt_app.prices.best_to_sell()
# An unknown crop used to be divided by a default base of 1, scoring 40.0 and
# beating rose at 90 forever.
check("unknown crop does not hijack best_to_sell",
      best_plant != "banana", "best_to_sell returned %s" % best_plant)
growgpt_app.prices.update({"rose": 200})
check("a genuinely high price does win",
      growgpt_app.prices.best_to_sell()[0] == "rose",
      growgpt_app.prices.best_to_sell()[0])
check("garbage price is ignored, not stored",
      growgpt_app.prices.update({"carrot": "abc"}) is None
      and growgpt_app.prices.current()["carrot"] != "abc")
check("freshness reports live data after an update",
      growgpt_app.prices.freshness() == "fresh",
      growgpt_app.prices.freshness())
check("no freshness warning while data is live",
      growgpt_app.prices.freshness_warning("fr") == "")

print("\n=== Chat ===")
for lang in ("fr", "en", "es", None, 123):
    r = post("/growgpt", {"player_id": "p1", "message": "quoi planter ?",
                          "player": {"level": 2, "money": 40, "plants": ["Tomato"]},
                          "lang": lang})
    check("chat survives lang=%r" % lang, r.status_code == 200, str(r.status_code))

r = post("/growgpt", {"player_id": "p1", "message": "", "player": {}})
check("empty message handled", r.status_code == 200)
r = post("/growgpt", {"player_id": "p1", "message": 12345, "player": {}})
check("non-string message handled", r.status_code == 200)

print("\n=== Quests ===")
# The market quest targets whatever is currently best to sell. rose was pushed
# to 200 above, and rose is in RARE_PLANTS, so use a crop that is in neither
# COMMON_PLANTS nor RARE_PLANTS to reproduce the original failure.
growgpt_app.prices.update({"tomato": 5000})
growgpt_app.quests.refresh_market_quests()
target, _ = growgpt_app.prices.best_to_sell()
check("market quest targets the hot crop", target == "tomato", target)

suggested = growgpt_app.quests.suggest(
    {"level": 9, "money": 4000, "plants": ["pumpkin"]}, "fr")
check("suggest returns quests", len(suggested) > 0, str(len(suggested)))

# Every suggested quest must be acceptable. The old brute-force lookup only
# recognised plants from two hardcoded lists and amounts from a fixed set, so
# tomato, pumpkin and any computed earn_money amount were suggested but could
# never be accepted.
unacceptable = []
for quest in suggested:
    result = growgpt_app.quests.accept("p_quest", quest["id"], "fr")
    if not result.get("ok"):
        unacceptable.append((quest["id"], result.get("message")))
check("every suggested quest can be accepted", not unacceptable, str(unacceptable))

check("earn_money reward stays sane",
      all(q["reward_data"]["coins"] < 5000 for q in suggested),
      str([(q["id"], q["reward_data"]["coins"]) for q in suggested]))

active = growgpt_app.quests.get_active("p_quest")
check("accepted quests are listed", len(active) == len(suggested),
      "%d active vs %d suggested" % (len(active), len(suggested)))

first_id = active[0]["id"]
check("duplicate accept refused",
      growgpt_app.quests.accept("p_quest", first_id, "fr")["ok"] is False)
check("complete works", growgpt_app.quests.complete("p_quest", first_id, "fr")["ok"] is True)
check("complete twice refused",
      growgpt_app.quests.complete("p_quest", first_id, "fr")["ok"] is False)
check("unknown quest id refused, no crash",
      growgpt_app.quests.accept("p_quest", "does_not_exist", "fr")["ok"] is False)

en_quests = growgpt_app.quests.suggest({"level": 2, "money": 10}, "en")
market_en = [q for q in en_quests if "Seller" in q["title"] or "Timing" in q["title"]]
check("english player gets english market quests",
      all("Vends" not in q["desc"] and "Récolte" not in q["desc"] for q in en_quests),
      str([q["desc"] for q in en_quests]))

print("\n=== Status ===")
status = client.get("/status").get_json()
check("status reports storage backend", "storage" in status, str(status))
check("status reports price freshness", status.get("prices_freshness") == "fresh",
      str(status.get("prices_freshness")))
check("status flags configured secrets",
      status["secrets_configured"]["ROBLOX_SECRET"] is True)

print("\n=== Persistence fallback ===")
from store import store as live_store
check("store reports memory mode without upstash",
      live_store.backend().startswith("memory"), live_store.backend())
live_store.set_json("test:key", {"a": 1})
check("write then read works in fallback",
      live_store.get_json("test:key") == {"a": 1})
live_store.hincr("test:hash", "field", 2)
live_store.hincr("test:hash", "field", 3)
check("counter accumulates in fallback",
      live_store.hgetall("test:hash").get("field") == 5,
      str(live_store.hgetall("test:hash")))

print("\n" + "=" * 50)
print("%d passed, %d failed" % (len(PASSED), len(FAILED)))
if FAILED:
    print("\nFailures:")
    for name, detail in FAILED:
        print("  - %s  %s" % (name, detail))
sys.exit(1 if FAILED else 0)
