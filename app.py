from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import time

from core.brain import GrowBrain
from core.prices import PriceManager
from core.quests import QuestEngine
from core.memory import MemoryStore
from core.upgrader import SelfUpgrader

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# =========================
# INIT MODULES
# =========================
START_TIME = time.time()
memory    = MemoryStore()
prices    = PriceManager()
quests    = QuestEngine(prices)
brain     = GrowBrain(memory, prices, quests)
upgrader  = SelfUpgrader(memory)

# =========================
# HOME
# =========================
@app.route("/")
def home():
    return "GrowGPT est en ligne 🌱"

# =========================
# STATUS
# =========================
@app.route("/status")
def status():
    uptime = int(time.time() - START_TIME)
    return jsonify({
        "status": "online",
        "uptime": uptime,
        "total_players": memory.total_players(),
        "active_quests": quests.count_active()
    })

# =========================
# CHAT PRINCIPAL
# =========================
@app.route("/growgpt", methods=["POST"])
def growgpt():
    data      = request.json or {}
    player_id = data.get("player_id", "unknown")
    message   = data.get("message", "")
    player    = data.get("player", {})
    lang      = data.get("lang", "fr")   # "fr" ou "en"

    if not message.strip():
        return jsonify({"response": "..." , "status": "online"})

    response = brain.respond(player_id, message, player, lang)
    upgrader.log_interaction(player_id, message, response)

    return jsonify({
        "response": response,
        "status": "online"
    })

# =========================
# MISE À JOUR PRIX (Roblox → toutes les 5 min)
# =========================
@app.route("/update_prices", methods=["POST"])
def update_prices():
    """
    Appelé par le script Lua Roblox toutes les 5 minutes.
    Body attendu :
    {
      "secret": "TON_SECRET",
      "prices": {
        "carrot": 12,
        "tomato": 45,
        "corn": 30,
        ...
      }
    }
    """
    data   = request.json or {}
    secret = data.get("secret", "")

    if secret != os.environ.get("ROBLOX_SECRET", "change_me"):
        return jsonify({"error": "Unauthorized"}), 401

    new_prices = data.get("prices", {})
    prices.update(new_prices)
    quests.refresh_market_quests()

    return jsonify({
        "ok": True,
        "prices_received": len(new_prices)
    })

# =========================
# QUÊTES DU JOUEUR
# =========================
@app.route("/quests", methods=["POST"])
def get_quests():
    """
    Retourne les quêtes suggérées pour un joueur.
    Body : { "player_id": "...", "player": {...} }
    """
    data      = request.json or {}
    player_id = data.get("player_id", "unknown")
    player    = data.get("player", {})
    lang      = data.get("lang", "fr")

    suggested = quests.suggest(player, lang)
    active    = quests.get_active(player_id)

    return jsonify({
        "suggested": suggested,
        "active": active
    })

# =========================
# CRÉER UNE QUÊTE
# =========================
@app.route("/quests/create", methods=["POST"])
def create_quest():
    """
    Crée une quête pour un joueur.
    Body : { "player_id": "...", "quest_id": "quest_sell_tomato" }
    """
    data      = request.json or {}
    player_id = data.get("player_id", "unknown")
    quest_id  = data.get("quest_id", "")
    lang      = data.get("lang", "fr")

    result = quests.accept(player_id, quest_id, lang)
    return jsonify(result)

# =========================
# COMPLÉTER UNE QUÊTE
# =========================
@app.route("/quests/complete", methods=["POST"])
def complete_quest():
    data      = request.json or {}
    player_id = data.get("player_id", "unknown")
    quest_id  = data.get("quest_id", "")
    lang      = data.get("lang", "fr")

    result = quests.complete(player_id, quest_id, lang)
    return jsonify(result)

# =========================
# CONSEIL MARCHÉ (quoi planter/vendre)
# =========================
@app.route("/market_advice", methods=["POST"])
def market_advice():
    data   = request.json or {}
    player = data.get("player", {})
    lang   = data.get("lang", "fr")

    advice = prices.get_advice(player, lang)
    return jsonify({"advice": advice, "prices": prices.current()})

# =========================
# AUTO-UPGRADE (webhook GitHub)
# =========================
@app.route("/trigger_upgrade", methods=["POST"])
def trigger_upgrade():
    """
    Analyse les logs et propose une PR d'amélioration sur GitHub.
    Protégé par secret admin.
    """
    data   = request.json or {}
    secret = data.get("secret", "")

    if secret != os.environ.get("ADMIN_SECRET", "admin_secret"):
        return jsonify({"error": "Unauthorized"}), 401

    result = upgrader.propose_upgrade()
    return jsonify(result)

# =========================
# LANCEMENT
# =========================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    app.run(host="0.0.0.0", port=port)
