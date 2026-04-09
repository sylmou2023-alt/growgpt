"""
core/upgrader.py — Auto-amélioration de GrowGPT
Analyse les interactions et pousse des suggestions d'upgrade sur GitHub via PR.

Flux :
  1. log_interaction()      → enregistre chaque échange
  2. propose_upgrade()      → analyse les logs, génère du code amélioré,
                               crée une branche GitHub + PR
  3. Tu reviews la PR sur GitHub et tu merges si OK → Render redéploie
"""
import os
import json
import time
import base64
import urllib.request
import urllib.error


class SelfUpgrader:
    def __init__(self, memory):
        self.memory = memory
        self._logs  = []          # buffer d'interactions brutes

    # =========================
    # LOG
    # =========================
    def log_interaction(self, player_id: str, message: str, response: str):
        self._logs.append({
            "player_id": player_id,
            "message":   message,
            "response":  response,
            "time":      time.time()
        })
        # Garde les 500 derniers logs en mémoire
        if len(self._logs) > 500:
            self._logs.pop(0)

    # =========================
    # ANALYSE & PROPOSITION
    # =========================
    def propose_upgrade(self) -> dict:
        """
        Analyse les logs et génère un fichier d'upgrade.
        Pousse le résultat sur une branche GitHub et crée une PR.
        """
        if not self._logs:
            return {"ok": False, "reason": "No logs to analyze yet."}

        analysis = self._analyze_logs()
        patch    = self._generate_patch(analysis)

        # Écriture locale du patch (pour référence)
        patch_path = "upgrades/latest_upgrade.py"
        os.makedirs("upgrades", exist_ok=True)
        with open(patch_path, "w", encoding="utf-8") as f:
            f.write(patch)

        # Push sur GitHub
        pr_url = self._push_to_github(patch, analysis)

        return {
            "ok":      bool(pr_url),
            "pr_url":  pr_url,
            "analysis": analysis,
            "message": (
                f"✅ PR créée : {pr_url}\nReview et merge pour déployer."
                if pr_url else
                "⚠️ Patch généré localement mais GitHub push a échoué.\n"
                "Vérifie GITHUB_TOKEN, GITHUB_OWNER et GITHUB_REPO."
            )
        }

    # =========================
    # ANALYSE INTERNE
    # =========================
    def _analyze_logs(self) -> dict:
        """Identifie les faiblesses à partir des logs."""
        unknown_msgs   = [l["message"] for l in self._logs
                           if "Hmm" in l["response"] or "préciser" in l["response"]
                              or "rephrase" in l["response"].lower()]
        intent_counts  = {}
        for l in self._logs:
            # Essaie de deviner l'intent depuis la réponse
            resp = l["response"].lower()
            if "plante" in resp or "plant" in resp:
                intent_counts["plant_advice"] = intent_counts.get("plant_advice", 0) + 1
            elif "vend" in resp or "sell" in resp or "prix" in resp or "price" in resp:
                intent_counts["sell_advice"]  = intent_counts.get("sell_advice", 0) + 1
            elif "quête" in resp or "quest" in resp:
                intent_counts["quest"]        = intent_counts.get("quest", 0) + 1
            else:
                intent_counts["unknown"]      = intent_counts.get("unknown", 0) + 1

        # Extraire des mots-clés des messages inconnus
        new_keywords = self._extract_keywords(unknown_msgs)

        return {
            "total_interactions":  len(self._logs),
            "unknown_messages":    unknown_msgs[:10],
            "intent_distribution": intent_counts,
            "suggested_keywords":  new_keywords,
            "timestamp":           time.strftime("%Y-%m-%d %H:%M:%S")
        }

    def _extract_keywords(self, messages: list) -> dict:
        """
        Extrait les mots fréquents dans les messages non compris
        pour suggérer de nouveaux mots-clés.
        """
        STOPWORDS = {"je", "tu", "il", "le", "la", "les", "de", "du", "un", "une",
                      "i", "the", "a", "an", "is", "are", "to", "of", "do", "you"}
        counts = {}
        for msg in messages:
            for word in msg.lower().split():
                w = word.strip(".,!?;:")
                if len(w) > 3 and w not in STOPWORDS:
                    counts[w] = counts.get(w, 0) + 1
        # Retourne les 10 plus fréquents
        return dict(sorted(counts.items(), key=lambda x: x[1], reverse=True)[:10])

    # =========================
    # GÉNÉRATION DU PATCH
    # =========================
    def _generate_patch(self, analysis: dict) -> str:
        """
        Génère un fichier Python contenant les nouveaux mots-clés suggérés.
        Ce fichier est ensuite reviewé et mergé manuellement.
        """
        keywords = analysis.get("suggested_keywords", {})
        unknown  = analysis.get("unknown_messages", [])
        timestamp = analysis.get("timestamp", "")

        lines = [
            "# ==============================================",
            f"# AUTO-UPGRADE SUGGESTION — {timestamp}",
            "# Généré par GrowGPT SelfUpgrader",
            "# À REVIEWER AVANT DE MERGER",
            "# ==============================================",
            "",
            "# Basé sur l'analyse de :",
            f"#   - {analysis.get('total_interactions', 0)} interactions",
            f"#   - {len(unknown)} messages non compris",
            "",
            "# Ajoute ces mots-clés dans core/brain.py > INTENTS",
            "# en les classant dans la bonne intention.",
            "",
            "SUGGESTED_NEW_KEYWORDS = {",
        ]

        for word, count in keywords.items():
            lines.append(f'    "{word}": {count},  # vu {count}x dans les messages non compris')

        lines += [
            "}",
            "",
            "# Exemples de messages non compris :",
        ]
        for msg in unknown[:5]:
            lines.append(f'# - "{msg}"')

        lines += [
            "",
            "# ==============================================",
            "# INSTRUCTIONS :",
            "# 1. Regarde les mots-clés ci-dessus",
            "# 2. Identifie leur intention (plant_advice, sell_advice, etc.)",
            "# 3. Ajoute-les dans INTENTS dans core/brain.py",
            "# 4. Merge cette PR pour déployer l'amélioration",
            "# ==============================================",
        ]

        return "\n".join(lines)

    # =========================
    # GITHUB
    # =========================
    def _push_to_github(self, content: str, analysis: dict) -> str | None:
        """
        Crée une branche 'growgpt-upgrade-{timestamp}' sur GitHub,
        commit le patch, et ouvre une Pull Request.
        Retourne l'URL de la PR ou None en cas d'échec.
        """
        token = os.environ.get("GITHUB_TOKEN")
        owner = os.environ.get("GITHUB_OWNER")
        repo  = os.environ.get("GITHUB_REPO")

        if not all([token, owner, repo]):
            return None

        headers = {
            "Authorization": f"token {token}",
            "Accept":        "application/vnd.github.v3+json",
            "Content-Type":  "application/json"
        }
        base_url    = f"https://api.github.com/repos/{owner}/{repo}"
        branch_name = f"growgpt-upgrade-{int(time.time())}"

        try:
            # 1. Récupérer le SHA du dernier commit sur main
            sha = self._gh_get(f"{base_url}/git/ref/heads/main", headers)["object"]["sha"]

            # 2. Créer la nouvelle branche
            self._gh_post(f"{base_url}/git/refs", headers, {
                "ref": f"refs/heads/{branch_name}",
                "sha": sha
            })

            # 3. Créer le fichier sur la nouvelle branche
            file_content = base64.b64encode(content.encode()).decode()
            file_path    = f"upgrades/upgrade_{int(time.time())}.py"
            self._gh_put(f"{base_url}/contents/{file_path}", headers, {
                "message": f"🤖 GrowGPT self-upgrade suggestion [{analysis['timestamp']}]",
                "content": file_content,
                "branch":  branch_name
            })

            # 4. Ouvrir la Pull Request
            unknown_count = len(analysis.get("unknown_messages", []))
            total         = analysis.get("total_interactions", 0)
            pr_body = (
                f"## 🤖 GrowGPT Auto-Upgrade\n\n"
                f"**Généré le :** {analysis['timestamp']}\n"
                f"**Interactions analysées :** {total}\n"
                f"**Messages non compris :** {unknown_count}\n\n"
                f"### Mots-clés suggérés\n"
                + "\n".join(f"- `{k}` ({v}x)" for k, v in
                             analysis.get("suggested_keywords", {}).items())
                + "\n\n### Messages non compris (exemples)\n"
                + "\n".join(f"- _{m}_" for m in
                             analysis.get("unknown_messages", [])[:5])
                + "\n\n---\n"
                  "**⚠️ À vérifier avant de merger !**\n"
                  "Ajoute les mots-clés pertinents dans `core/brain.py`."
            )

            pr_data = self._gh_post(f"{base_url}/pulls", headers, {
                "title": f"🌱 GrowGPT Upgrade — {unknown_count} messages améliorés",
                "body":  pr_body,
                "head":  branch_name,
                "base":  "main"
            })
            return pr_data.get("html_url")

        except Exception as e:
            print(f"[SelfUpgrader] GitHub error: {e}")
            return None

    # =========================
    # HELPERS HTTP
    # =========================
    def _gh_get(self, url: str, headers: dict) -> dict:
        req  = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())

    def _gh_post(self, url: str, headers: dict, body: dict) -> dict:
        data = json.dumps(body).encode()
        req  = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())

    def _gh_put(self, url: str, headers: dict, body: dict) -> dict:
        data = json.dumps(body).encode()
        req  = urllib.request.Request(url, data=data, headers=headers, method="PUT")
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
