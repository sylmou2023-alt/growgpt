"""
core/llm.py — Connexion à un vrai modèle de langage (gratuit)
Par défaut : API Mistral (offre gratuite "Experiment").
Compatible avec toute API au format OpenAI (Groq, OpenRouter...) :
il suffit de changer LLM_BASE_URL et LLM_MODEL dans Render.
"""
import json
import os
import urllib.request
import urllib.error


class LLMClient:
    def __init__(self):
        self.api_key  = os.environ.get("LLM_API_KEY", "")
        self.base_url = os.environ.get("LLM_BASE_URL", "https://api.mistral.ai/v1").rstrip("/")
        self.model    = os.environ.get("LLM_MODEL", "mistral-small-latest")
        self.timeout  = float(os.environ.get("LLM_TIMEOUT", "10"))

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def chat(self, messages: list, max_tokens: int = 150) -> str | None:
        """Envoie la conversation au modèle. Retourne None en cas d'échec."""
        if not self.enabled:
            return None

        body = json.dumps({
            "model":       self.model,
            "messages":    messages,
            "max_tokens":  max_tokens,
            "temperature": 0.7,
        }).encode("utf-8")

        req = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=body,
            headers={
                "Content-Type":  "application/json",
                "Authorization": "Bearer " + self.api_key,
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            text = data["choices"][0]["message"]["content"].strip()
            return text or None
        except (urllib.error.URLError, TimeoutError, KeyError, IndexError, ValueError) as e:
            # Quota gratuit dépassé, API en panne... on retombe sur les réponses classiques
            print(f"[GrowGPT] LLM indisponible : {e}")
            return None
