from flask import Flask, request, jsonify
from flask_cors import CORS
import random
import os
import time

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# =========================
# CONFIG
# =========================
SERVER_STATUS = "online"  # online / starting / maintenance
START_TIME = time.time()

memory = {}

# =========================
# ROUTE HOME (évite 404)
# =========================
@app.route("/")
def home():
    return "GrowGPT est en ligne 🌱"

# =========================
# STATUS (pour Roblox)
# =========================
@app.route("/status")
def status():
    uptime = int(time.time() - START_TIME)

    return jsonify({
        "status": SERVER_STATUS,
        "uptime": uptime
    })

# =========================
# ANALYSE MESSAGE
# =========================
def analyze_message(message):
    message = message.lower()

    if "planter" in message or "quoi" in message:
        return "plant"

    if "argent" in message or "money" in message:
        return "money"

    if "mutation" in message:
        return "mutation"

    if "aide" in message:
        return "help"

    return "unknown"

# =========================
# GENERATE RESPONSE
# =========================
def generate_response(intent, player, player_id):
    level = player.get("level", 1)
    money = player.get("money", 0)
    plants = player.get("plants", [])

    # mémoire
    last = memory.get(player_id)

    if last and last["intent"] == intent:
        return "Tu reviens encore sur ça 😏 laisse-moi affiner..."

    if intent == "plant":
        if money < 100:
            return "Plante des carottes 🥕, parfait pour débuter."

        if "tomato" in plants:
            return "Les tomates 🍅 sont un excellent choix actuellement."

        return random.choice([
            "Teste une plante rapide 🌱",
            "Essaie une plante rare 👀",
            "Optimise ton espace de culture"
        ])

    if intent == "money":
        if level < 5:
            return "Monte de niveau avant de chercher à optimiser 💡"

        return "Investis dans des plantes rares pour plus de profit 💰"

    if intent == "mutation":
        return random.choice([
            "Les mutations sont aléatoires 🌿",
            "Plante en masse pour augmenter tes chances",
            "Certaines plantes mutent plus souvent 👀"
        ])

    if intent == "help":
        return "Je suis GrowGPT 🌱 ton assistant jardin !"

    return random.choice([
        "Hmm… intéressant 🤔",
        "Peux-tu préciser ?",
        "Je réfléchis encore 🌱"
    ])

# =========================
# API PRINCIPALE
# =========================
@app.route("/growgpt", methods=["POST"])
def growgpt():
    global SERVER_STATUS

    if SERVER_STATUS != "online":
        return jsonify({
            "error": "Serveur indisponible",
            "status": SERVER_STATUS
        })

    data = request.json
    player_id = data.get("player_id", "unknown")
    message = data.get("message", "")
    player = data.get("player", {})

    intent = analyze_message(message)
    response = generate_response(intent, player, player_id)

    # sauvegarde mémoire
    memory[player_id] = {
        "intent": intent,
        "last_message": message
    }

    return jsonify({
        "response": response,
        "status": SERVER_STATUS
    })

# =========================
# LANCEMENT
# =========================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    app.run(host="0.0.0.0", port=port)
