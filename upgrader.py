"""
upgrader.py — Turns real usage into a reviewable improvement.

Flow:
  1. log_interaction()  records each exchange (persisted, capped)
  2. propose_upgrade()  reads the stats, writes keywords_extra.json on a new
                        branch and opens a pull request
  3. you review it, move words into the right intent, merge — Render redeploys

Two things changed from the original design.

The analysis used to guess each player's intent by searching for words inside
GrowGPT's own reply, even though brain.py had already computed the intent and
stored it. It now reads those real numbers from MemoryStore.

More importantly, the pull request used to add a file under upgrades/ that
nothing in the codebase imported. Merging it changed no behaviour whatsoever;
the keywords still had to be copied into brain.py by hand. The PR now targets
keywords_extra.json, which brain.py actually loads at import, so a merged and
triaged suggestion takes effect on the next deploy with no code editing.
"""
import base64
import json
import os
import time
import urllib.error
import urllib.request

from store import store

_LOG_KEY = "growgpt:logs"
_LOG_MAX = 500

# GitHub is called from a request handler, so it must not hang indefinitely.
_HTTP_TIMEOUT = 15.0

KEYWORDS_FILE = "keywords_extra.json"

# Words too common to be useful signal about what the bot failed to understand.
STOPWORDS = {
    "je", "tu", "il", "elle", "on", "le", "la", "les", "de", "du", "un", "une",
    "des", "mon", "ma", "mes", "que", "qui", "quoi", "pour", "avec", "dans",
    "i", "you", "he", "she", "the", "a", "an", "is", "are", "to", "of", "do",
    "does", "and", "for", "with", "this", "that", "what", "how", "can",
}


class SelfUpgrader:
    def __init__(self, memory):
        self.memory = memory

    # =========================
    # LOGGING
    # =========================
    def log_interaction(self, player_id: str, message: str, response: str):
        store.push_capped(_LOG_KEY, {
            "player_id": player_id,
            "message": message,
            "response": response,
            "time": time.time(),
        }, _LOG_MAX)

    # =========================
    # ANALYSIS
    # =========================
    def _analyze_logs(self) -> dict:
        logs = store.list_all(_LOG_KEY)
        unknown = self.memory.unknown_messages()

        return {
            "total_interactions":  len(logs),
            "unknown_count":       len(unknown),
            "unknown_messages":    unknown[-10:],
            "intent_distribution": self.memory.most_common_intents(),
            "suggested_keywords":  self._extract_keywords(unknown),
            "timestamp":           time.strftime("%Y-%m-%d %H:%M:%S"),
        }

    def _extract_keywords(self, messages: list) -> dict:
        """Most frequent meaningful words among messages we failed to classify."""
        counts = {}
        for msg in messages:
            for word in str(msg).lower().split():
                w = word.strip(".,!?;:\"'()")
                if len(w) > 3 and w not in STOPWORDS:
                    counts[w] = counts.get(w, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:15])

    # =========================
    # PROPOSAL
    # =========================
    def propose_upgrade(self) -> dict:
        analysis = self._analyze_logs()

        if not analysis["suggested_keywords"]:
            return {
                "ok": False,
                "reason": "Nothing to suggest yet: no unclassified messages recorded.",
                "analysis": analysis,
            }

        pr_url = self._push_to_github(analysis)
        return {
            "ok": bool(pr_url),
            "pr_url": pr_url,
            "analysis": analysis,
            "message": (
                "PR opened: %s — move each word into the right intent, then merge." % pr_url
                if pr_url else
                "Analysis done but the GitHub push failed. "
                "Check GITHUB_TOKEN, GITHUB_OWNER and GITHUB_REPO."
            ),
        }

    def _build_keywords_file(self, existing: dict, analysis: dict) -> str:
        """
        Merge new candidates into the existing file.

        Words land in `pending_review`, never straight into an intent: only a
        human knows whether "arroser" belongs to plant_advice or to a topic the
        bot does not cover at all. brain.py ignores `pending_review`, so merging
        this PR is always safe, and moving a word into an intent list is the
        one manual step that actually enables it.
        """
        merged = dict(existing) if isinstance(existing, dict) else {}
        merged.setdefault("_readme", (
            "Move a word from pending_review into one of the intent lists below "
            "to teach GrowGPT. Keys starting with _ and pending_review are ignored "
            "at runtime."
        ))
        merged["_generated"] = analysis["timestamp"]

        for intent in ("plant_advice", "sell_advice", "quest", "mutation",
                       "level", "help", "greeting", "thanks"):
            merged.setdefault(intent, [])

        already = {
            w.lower()
            for key, value in merged.items()
            if isinstance(value, list)
            for w in value
        }

        pending = merged.get("pending_review")
        pending = dict(pending) if isinstance(pending, dict) else {}
        for word, count in analysis["suggested_keywords"].items():
            if word not in already:
                pending[word] = count
        merged["pending_review"] = pending

        return json.dumps(merged, indent=2, ensure_ascii=False, sort_keys=True)

    # =========================
    # GITHUB
    # =========================
    def _push_to_github(self, analysis: dict):
        token = os.environ.get("GITHUB_TOKEN")
        owner = os.environ.get("GITHUB_OWNER")
        repo = os.environ.get("GITHUB_REPO")
        base_branch = os.environ.get("GITHUB_BASE_BRANCH", "main")

        if not all([token, owner, repo]):
            return None

        headers = {
            "Authorization": "token %s" % token,
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "growgpt-self-upgrader",
        }
        base_url = "https://api.github.com/repos/%s/%s" % (owner, repo)
        branch = "growgpt-upgrade-%d" % int(time.time())

        try:
            ref = self._gh("GET", "%s/git/ref/heads/%s" % (base_url, base_branch), headers)
            sha = ref["object"]["sha"]

            self._gh("POST", "%s/git/refs" % base_url, headers, {
                "ref": "refs/heads/%s" % branch,
                "sha": sha,
            })

            # Read the current file so repeated runs accumulate instead of
            # overwriting, and so we can supply the blob sha GitHub requires
            # when updating an existing path.
            current = self._gh(
                "GET",
                "%s/contents/%s?ref=%s" % (base_url, KEYWORDS_FILE, base_branch),
                headers,
                allow_missing=True,
            )
            existing = {}
            file_sha = None
            if current:
                file_sha = current.get("sha")
                try:
                    existing = json.loads(
                        base64.b64decode(current.get("content", "")).decode("utf-8"))
                except (ValueError, TypeError):
                    existing = {}

            content = self._build_keywords_file(existing, analysis)
            payload = {
                "message": "GrowGPT: %d keyword suggestions from real usage" % len(
                    analysis["suggested_keywords"]),
                "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
                "branch": branch,
            }
            if file_sha:
                payload["sha"] = file_sha
            self._gh("PUT", "%s/contents/%s" % (base_url, KEYWORDS_FILE), headers, payload)

            pr = self._gh("POST", "%s/pulls" % base_url, headers, {
                "title": "GrowGPT: %d new keyword suggestions" % len(
                    analysis["suggested_keywords"]),
                "body": self._pr_body(analysis),
                "head": branch,
                "base": base_branch,
            })
            return pr.get("html_url")

        except (urllib.error.URLError, OSError, ValueError, KeyError) as exc:
            print("[SelfUpgrader] GitHub error: %s" % exc, flush=True)
            return None

    def _pr_body(self, analysis: dict) -> str:
        keywords = analysis["suggested_keywords"]
        lines = [
            "## GrowGPT self-upgrade",
            "",
            "Generated %s from %d logged interactions, %d of which the intent "
            "scorer could not classify." % (
                analysis["timestamp"], analysis["total_interactions"],
                analysis["unknown_count"]),
            "",
            "### Candidate keywords",
            "",
        ]
        lines += ["- `%s` — seen %dx" % (w, c) for w, c in keywords.items()]
        lines += ["", "### Sample messages that were not understood", ""]
        lines += ["- _%s_" % m for m in analysis["unknown_messages"][:5]]
        lines += [
            "",
            "---",
            "",
            "These land in `pending_review`, which is ignored at runtime, so "
            "merging as-is changes nothing. To actually teach the bot a word, "
            "move it from `pending_review` into the matching intent list in "
            "`%s` before merging." % KEYWORDS_FILE,
        ]
        return "\n".join(lines)

    def _gh(self, method: str, url: str, headers: dict,
            payload: dict = None, allow_missing: bool = False):
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if allow_missing and exc.code == 404:
                return None
            raise
