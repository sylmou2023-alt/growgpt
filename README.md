# 🌱 GrowGPT

Assistant conversationnel pour une version Roblox de *Grow a Garden*. Il répond
aux joueurs, leur donne des conseils basés sur les **vrais prix du marché**
envoyés par le jeu, propose des quêtes, et sait ouvrir une PR GitHub avec des
suggestions d'amélioration tirées de l'usage réel.

Pas d'appel à une API d'IA : la compréhension du langage est un scoring de
mots-clés local (`brain.py`), donc zéro coût et zéro latence externe.

---

## Structure

```
growgpt/
├── app.py                  ← Point d'entrée Flask (routes, auth)
├── store.py                ← Persistance (Upstash Redis, repli mémoire)
├── brain.py                ← Détection d'intention + génération de réponse
├── prices.py               ← Prix du marché + fraîcheur des données
├── quests.py               ← Moteur de quêtes
├── memory.py               ← Mémoire joueurs + statistiques d'intentions
├── upgrader.py             ← Auto-amélioration via PR GitHub
├── text_utils.py           ← Normalisation langue / mots
├── keywords_extra.json     ← Mots-clés appris, chargés par brain.py
├── GrowGPT_PriceSync.lua   ← Script à coller dans Roblox
├── test_growgpt.py         ← Tests fonctionnels
├── test_store_remote.py    ← Tests du protocole Redis (faux serveur local)
├── Procfile
└── requirements.txt
```

---

## Déploiement sur Render

**Start command :**

```bash
gunicorn app:app --workers 1 --threads 8 --timeout 30 --bind 0.0.0.0:$PORT
```

Un seul worker suffit sur le free tier (0,1 CPU) et les threads absorbent les
requêtes simultanées. Avec Redis configuré, plusieurs workers deviennent
possibles ; sans Redis ils se contrediraient, chacun ayant ses propres prix.

### Variables d'environnement

| Variable                   | Obligatoire | Rôle |
|----------------------------|-------------|------|
| `ROBLOX_SECRET`            | **oui**     | Secret partagé Roblox ↔ GrowGPT pour `/update_prices` |
| `ADMIN_SECRET`             | **oui**     | Protège `/trigger_upgrade` |
| `UPSTASH_REDIS_REST_URL`   | recommandé  | Persistance des prix, joueurs et quêtes |
| `UPSTASH_REDIS_REST_TOKEN` | recommandé  | Token REST Upstash |
| `GITHUB_TOKEN`             | non         | PAT (scope `repo`) pour l'auto-upgrade |
| `GITHUB_OWNER`             | non         | Ton pseudo GitHub |
| `GITHUB_REPO`              | non         | Nom du repo |
| `GITHUB_BASE_BRANCH`       | non         | Branche cible des PR (défaut `main`) |

⚠️ **`ROBLOX_SECRET` et `ADMIN_SECRET` n'ont pas de valeur par défaut.** Si
elles ne sont pas définies, les endpoints qu'elles protègent répondent `503` au
lieu d'accepter n'importe qui. Vérifie `/status` après un déploiement.

### Persistance : pourquoi c'est nécessaire

Sans Redis, tout l'état vit dans la mémoire du process. Render éteint un service
free tier après ~15 min sans trafic, et chaque déploiement le redémarre. À
chaque réveil, les prix retombaient sur les valeurs par défaut du code — et le
bot les annonçait comme s'ils étaient réels.

L'app **fonctionne sans Redis** (repli mémoire automatique), mais elle oublie
tout à chaque redémarrage. `/status` indique le mode actif dans `storage`.

**Mise en place d'Upstash (gratuit, permanent) :**

1. Crée un compte sur [upstash.com](https://upstash.com) → *Create Database* → Redis.
2. Choisis la région la plus proche de ton service Render.
3. Dans l'onglet **REST API** de la base, copie `UPSTASH_REDIS_REST_URL` et
   `UPSTASH_REDIS_REST_TOKEN`.
4. Colle-les dans Render → *Environment* → *Add Environment Variable*.
5. Redéploie. `/status` doit afficher `"storage": "upstash"`.

---

## Endpoints

### `GET /status`
Diagnostic. Les deux champs qui comptent :

- `prices_freshness` — `fresh` / `stale` / `old` / `default`. Si c'est
  `default`, le bot n'a jamais reçu de prix et donne des estimations.
- `storage` — `upstash` ou `memory`. Si c'est `memory`, tout sera perdu au
  prochain redémarrage.

### `POST /growgpt` — Chat principal
```json
{
  "player_id": "123456",
  "message":   "quoi planter ?",
  "player":    { "name": "Syl", "level": 3, "money": 250, "plants": ["tomato"] },
  "lang":      "fr"
}
```
`lang` est respecté : la détection automatique ne l'écrase que si le message
indique clairement l'autre langue. Un code inconnu (`"es"`, `"en-US"`) est
ramené proprement sur `fr` ou `en` au lieu de provoquer une erreur.

### `POST /update_prices` — Appelé par Roblox toutes les 5 min
```json
{
  "secret": "TON_ROBLOX_SECRET",
  "prices": { "carrot": 12, "tomato": 45 }
}
```
Les entrées non numériques ou négatives sont ignorées silencieusement plutôt que
d'empoisonner la table pour tous les joueurs.

### Autres routes

- `POST /quests` — quêtes suggérées et actives
- `POST /quests/create` — accepter une quête (`quest_id`)
- `POST /quests/complete` — terminer une quête
- `POST /market_advice` — conseils marché + prix bruts + fraîcheur
- `POST /trigger_upgrade` — analyse et ouvre une PR (secret admin)

---

## Auto-amélioration

`/trigger_upgrade` analyse les messages que le bot n'a pas compris, en extrait
les mots fréquents, et ouvre une PR sur `keywords_extra.json`.

Les candidats arrivent dans `pending_review`, que `brain.py` **ignore**. Merger
la PR telle quelle ne change donc rien. Pour apprendre un mot au bot, déplace-le
de `pending_review` vers la bonne intention (`plant_advice`, `sell_advice`,
`quest`, `mutation`, `level`, `help`, `greeting`, `thanks`) avant de merger. Au
redéploiement, `brain.py` le charge automatiquement — aucun code à toucher.

---

## Côté Roblox

Dans `GrowGPT_PriceSync.lua`, renseigne :

- `GROWGPT_URL` — l'URL de ton service Render (elle est encore sur le
  placeholder `https://TON-APP.onrender.com`)
- `SECRET` — la même valeur que `ROBLOX_SECRET` sur Render

Le POST toutes les 5 minutes a un effet secondaire utile : tant qu'il y a des
joueurs, il empêche Render d'endormir le service.

---

## Tests

```bash
python test_growgpt.py && python test_store_remote.py
```

`test_growgpt.py` couvre le comportement de l'app en repli mémoire.
`test_store_remote.py` lance un faux serveur Upstash en local pour exercer tout
le chemin Redis — protocole, cache, compteurs, coupe-circuit, et la persistance
des prix et des quêtes à travers un redémarrage simulé. Aucun compte requis.
