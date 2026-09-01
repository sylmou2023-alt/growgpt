"""
app.py — GrowGPT HTTP entry point (Flask).

Called by the Roblox game: prices in, advice and quests out.
"""
import hmac
import os
import sys
import time

from flask import Flask, jsonify, request
from flask_cors import CORS

from brain import GrowBrain
from memory import MemoryStore
from prices import PriceManager
from quests import QuestEngine
from store import store
from text_utils import normalize_lang
from upgrader import SelfUpgrader

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

START_TIME = time.time()
memory   = MemoryStore()
prices   = PriceManager()
quests   = QuestEngine(prices)
brain    = GrowBrain(memory, prices, quests)
upgrader = SelfUpgrader(memory)


# =========================
# AUTH
# =========================
def check_secret(provided, env_name: str):
    """
    Validate a shared secret against the environment.

    There is deliberately no fallback value. The previous code compared against
    the literal strings "change_me" and "admin_secret" when the variables were
    unset, so a public deployment that forgot to configure them accepted those
    published defaults from anyone — enough to inject fake prices for every
    player, or to trigger GitHub pull requests using the server's token.
    Missing configuration now fails closed and says so.
    """
    expected = os.environ.get(env_name)
    if not expected:
        return False, jsonify({
            "error": "Server misconfigured",
            "detail": "%s is not set on this deployment." % env_name,
        }), 503

    provided = provided if isinstance(provided, str) else ""
    # compare_digest keeps the comparison time-independent of how many
    # characters an attacker already guessed.
    if not hmac.compare_digest(provided, expected):
        return False, jsonify({"error": "Unauthorized"}), 401

    return True, None, None


def body() -> dict:
    """
    Request body as a dict, whatever the client sent.

    request.json raises on a missing or wrong Content-Type; Roblox HttpService
    is not always careful about that, and a malformed header should not turn
    into a 500.
    """
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def req_lang() -> str:
    return normalize_lang(body().get("lang"))


# =========================
# HOME / STATUS
# =========================
@app.route("/")
def home():
    return "GrowGPT est en ligne 🌱"


@app.route("/status")
def status():
    """
    Health and, more usefully, honesty about the data.

    `prices.freshness` and `storage` are the two things worth watching: they
    say whether the bot is quoting live numbers and whether anything it learns
    will survive the next restart.
    """
    return jsonify({
        "status":           "online",
        "uptime":           int(time.time() - START_TIME),
        "total_players":    memory.total_players(),
        "active_quests":    quests.count_active(),
        "prices_freshness": prices.freshness(),
        "prices_age_s":     prices.age_seconds(),
        "storage":          store.backend(),
        "storage_error":    store.last_error(),
        "secrets_configured": {
            "ROBLOX_SECRET": bool(os.environ.get("ROBLOX_SECRET")),
            "ADMIN_SECRET":  bool(os.environ.get("ADMIN_SECRET")),
        },
    })


# =========================
# MAIN CHAT
# =========================
@app.route("/growgpt", methods=["POST"])
def growgpt():
    data      = body()
    player_id = str(data.get("player_id", "unknown"))
    message   = data.get("message", "")
    player    = data.get("player") or {}
    lang      = normalize_lang(data.get("lang"))

    if not isinstance(message, str) or not message.strip():
        return jsonify({"response": "...", "status": "online"})

    response = brain.respond(player_id, message, player, lang)
    upgrader.log_interaction(player_id, message, response)

    return jsonify({"response": response, "status": "online"})


# =========================
# PRICE UPDATE (Roblox, every 5 min)
# =========================
@app.route("/update_prices", methods=["POST"])
def update_prices():
    """
    Body: {"secret": "...", "prices": {"carrot": 12, "tomato": 45, ...}}
    """
    data = body()
    ok, error_response, code = check_secret(data.get("secret"), "ROBLOX_SECRET")
    if not ok:
        return error_response, code

    new_prices = data.get("prices")
    if not isinstance(new_prices, dict) or not new_prices:
        return jsonify({"error": "Missing or invalid 'prices' object"}), 400

    prices.update(new_prices)
    quests.refresh_market_quests()

    return jsonify({
        "ok": True,
        "prices_received": len(new_prices),
        "persisted": store.is_persistent(),
    })


# =========================
# QUESTS
# =========================
@app.route("/quests", methods=["POST"])
def get_quests():
    data      = body()
    player_id = str(data.get("player_id", "unknown"))
    player    = data.get("player") or {}
    lang      = normalize_lang(data.get("lang"))

    return jsonify({
        "suggested": quests.suggest(player, lang),
        "active":    quests.get_active(player_id),
    })


@app.route("/quests/create", methods=["POST"])
def create_quest():
    data = body()
    return jsonify(quests.accept(
        str(data.get("player_id", "unknown")),
        str(data.get("quest_id", "")),
        normalize_lang(data.get("lang")),
    ))


@app.route("/quests/complete", methods=["POST"])
def complete_quest():
    data = body()
    return jsonify(quests.complete(
        str(data.get("player_id", "unknown")),
        str(data.get("quest_id", "")),
        normalize_lang(data.get("lang")),
    ))


# =========================
# MARKET ADVICE
# =========================
@app.route("/market_advice", methods=["POST"])
def market_advice():
    data = body()
    lang = normalize_lang(data.get("lang"))
    return jsonify({
        "advice":    prices.get_advice(data.get("player") or {}, lang),
        "prices":    prices.current(),
        "freshness": prices.freshness(),
    })


# =========================
# SELF-UPGRADE (admin only)
# =========================
@app.route("/trigger_upgrade", methods=["POST"])
def trigger_upgrade():
    """Analyse the logs and open a GitHub PR with suggested improvements."""
    ok, error_response, code = check_secret(body().get("secret"), "ADMIN_SECRET")
    if not ok:
        return error_response, code
    return jsonify(upgrader.propose_upgrade())


# =========================
# STARTUP CHECKS
# =========================
def startup_report():
    """
    Say plainly, in the Render logs, what is not configured. Silent degradation
    is what let this service run for weeks quoting default prices as live.
    """
    warnings = []
    for name in ("ROBLOX_SECRET", "ADMIN_SECRET"):
        if not os.environ.get(name):
            warnings.append("%s is not set — the endpoint it guards is disabled." % name)
    if not store.is_persistent():
        warnings.append(
            "No Redis configured (UPSTASH_REDIS_REST_URL / _TOKEN) — prices, "
            "player memory and quests reset on every restart."
        )
    for line in warnings:
        print("[growgpt] WARNING: %s" % line, file=sys.stderr, flush=True)
    if not warnings:
        print("[growgpt] configuration OK, storage=%s" % store.backend(),
              file=sys.stderr, flush=True)


startup_report()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 3000)))
