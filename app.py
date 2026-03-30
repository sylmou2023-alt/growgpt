from flask import Flask, request, jsonify
import random

app = Flask(__name__)

memory = {}

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


def generate_response(intent, player):
    level = player.get("level", 1)
    money = player.get("money", 0)
    plants = player.get("plants", [])

    if intent == "plant":
        if money < 100:
            return "Plante des carottes 🥕, c’est le meilleur choix pour démarrer."

        if "tomato" in plants:
            return "Continue avec les tomates 🍅, elles sont rentables."

        return random.choice([
            "Teste des plantes rapides pour gagner vite.",
            "Essaie une plante rare si tu peux.",
            "Optimise ton espace de culture 🌱"
        ])

    if intent == "money":
        if level < 5:
            return "Monte de niveau avant de chercher à gagner beaucoup."

        return "Investis dans des plantes rares pour gagner plus 💰"

    if intent == "mutation":
        return random.choice([
            "Les mutations sont aléatoires, plante souvent 🌿",
            "Certaines plantes mutent plus que d'autres 👀",
            "Essaie de planter en masse pour augmenter tes chances"
        ])

    if intent == "help":
        return "Je suis GrowGPT 🌱, je peux t’aider à optimiser ton jardin !"

    return random.choice([
        "Hmm… intéressant 🤔",
        "Peux-tu préciser ?",
        "Je réfléchis encore à ça 🌱"
    ])


@app.route("/growgpt", methods=["POST"])
def growgpt():
    data = request.json
    player_id = data.get("player_id")
    message = data.get("message")
    player = data.get("player")

    intent = analyze_message(message)
    response = generate_response(intent, player)

    # mémoire simple
    memory[player_id] = {
        "last_intent": intent,
        "last_message": message
    }

    return jsonify({"response": response})


app.run(host="0.0.0.0", port=3000)
