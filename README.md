# 🌱 GrowGPT — Documentation complète

## Structure des fichiers

```
growgpt/
├── app.py                    ← Point d'entrée Flask (routes)
├── requirements.txt
├── GrowGPT_PriceSync.lua     ← Script Roblox
├── core/
│   ├── brain.py              ← NLP + génération de réponses
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

1. Mets `GrowGPT_PriceSync.lua` dans **ServerScriptService**
2. Remplace `TON-APP.onrender.com` par ton URL Render
3. Remplace `TON_SECRET` par la valeur de `ROBLOX_SECRET`
4. Dans ton système de prix, appelle `syncPrices()` ou laisse le timer tourner
5. Pour le chat, appelle `AskGrowGPT(player.UserId, message, playerData)`
