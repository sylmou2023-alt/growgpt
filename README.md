# 🌱 GrowGPT — Documentation complète

## Structure des fichiers

```
growgpt/
├── app.py                    ← Point d'entrée Flask (routes)
├── requirements.txt
├── roblox/
│   ├── GrowGPT.lua               ← ModuleScript (connexion + prix + filtre)
│   ├── GrowGPT_Chat.server.lua   ← Script : écoute "@growgpt" dans le chat
│   └── GrowGPT_Display.client.lua← LocalScript : affiche les réponses
├── core/
│   ├── brain.py              ← NLP + génération de réponses
│   ├── llm.py                ← Appel au modèle Mistral (gratuit)
│   ├── prices.py             ← Gestionnaire de prix en temps réel
│   ├── quests.py             ← Moteur de quêtes dynamiques
│   ├── memory.py             ← Mémoire des joueurs
│   └── upgrader.py           ← Auto-amélioration via GitHub PR
└── upgrades/                 ← Patches générés automatiquement
```

---

## Variables d'environnement (Render)

| Variable         | Description                              | Exemple             |
|------------------|------------------------------------------|---------------------|
| `ROBLOX_SECRET`  | Secret partagé Roblox ↔ GrowGPT         | `mon_secret_roblox` |
| `ADMIN_SECRET`   | Secret pour déclencher un auto-upgrade   | `admin_secret_xyz`  |
| `GITHUB_TOKEN`   | Personal Access Token GitHub (repo scope) | `ghp_xxxx`         |
| `GITHUB_OWNER`   | Ton pseudo GitHub                        | `TonPseudo`         |
| `GITHUB_REPO`    | Nom du repo                              | `growgpt`           |
| `LLM_API_KEY`    | Clé API Mistral (offre gratuite). Sans clé, GrowGPT garde ses réponses par mots-clés | `xxxx` |
| `LLM_BASE_URL`   | Optionnel : autre API au format OpenAI   | `https://api.mistral.ai/v1` |
| `LLM_MODEL`      | Optionnel : modèle utilisé               | `mistral-small-latest` |

---

## Endpoints API

### `POST /growgpt` — Chat principal
```json
{
  "player_id": "123456",
  "message":   "quoi planter ?",
  "lang":      "fr",
  "player": {
    "name":   "Farmer",
    "level":  5,
    "money":  200,
    "plants": ["carrot", "tomato"]
  }
}
```

### `POST /update_prices` — Envoi des prix depuis Roblox
```json
{
  "secret": "TON_ROBLOX_SECRET",
  "prices": {
    "carrot": 15,
    "tomato": 52,
    "rose":   95
  }
}
```

### `POST /quests` — Quêtes suggérées
```json
{
  "player_id": "123456",
  "player":    { "level": 3, "money": 150 },
  "lang":      "fr"
}
```

### `POST /quests/create` — Accepter une quête
```json
{
  "player_id": "123456",
  "quest_id":  "sell_tomato_5",
  "lang":      "fr"
}
```

### `POST /quests/complete` — Terminer une quête
```json
{
  "player_id": "123456",
  "quest_id":  "sell_tomato_5",
  "lang":      "fr"
}
```

### `POST /market_advice` — Conseil marché complet
```json
{
  "player": { "level": 5, "money": 300, "plants": ["tomato"] },
  "lang":   "fr"
}
```

### `POST /trigger_upgrade` — Déclencher un auto-upgrade
```json
{
  "secret": "TON_ADMIN_SECRET"
}
```
→ Crée automatiquement une branche + PR sur GitHub.  
→ Tu reviews, tu merges → Render redéploie.

---

## Flux auto-upgrade

```
Joueurs jouent
      ↓
Messages non compris accumulés
      ↓
Tu appelles /trigger_upgrade
      ↓
GrowGPT analyse les logs
      ↓
Génère un fichier de suggestions
      ↓
Push sur branche GitHub
      ↓
Ouvre une Pull Request
      ↓
Tu reviews la PR (mots-clés suggérés)
      ↓
Tu ajoutes les bons mots-clés dans core/brain.py
      ↓
Tu merges → Render redéploie automatiquement
```

---

## Script Roblox — Utilisation

1. Active **Game Settings > Security > Allow HTTP Requests**
2. Dans **ServerScriptService** : crée un ModuleScript `GrowGPT` (contenu de `roblox/GrowGPT.lua`) et un Script `GrowGPT_Chat` (contenu de `roblox/GrowGPT_Chat.server.lua`)
3. Dans **StarterPlayer > StarterPlayerScripts** : crée un LocalScript `GrowGPT_Display` (contenu de `roblox/GrowGPT_Display.client.lua`)
4. Dans le ModuleScript, remplace `TON-APP.onrender.com` par ton URL Render et `TON_SECRET` par la valeur de `ROBLOX_SECRET`
5. Remplace `GetCurrentPrices()` et `getPlayerData()` par ton vrai système de prix et de stats
6. En jeu, écris `@growgpt quoi planter ?` dans le chat

Toutes les réponses passent par le filtre de texte Roblox avant d'être affichées (obligatoire pour du texte généré).
