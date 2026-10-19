# Héberger ton propre Mistral gratuitement (Oracle Cloud)

Schéma : **Roblox / site web → GrowGPT (Render, HTTPS) → Mistral 7B (ton serveur Oracle)**.
Roblox ne parle qu'à Render ; c'est Render qui interroge ton modèle.

## 1. Créer le serveur (une seule fois)
1. Inscris-toi sur **cloud.oracle.com** (offre *Free Tier*). La carte bancaire sert uniquement à vérifier ton identité ; tant que tu choisis des ressources marquées *Always Free*, rien n'est prélevé.
2. *Compute > Instances > Create instance* :
   - Image : **Ubuntu 22.04** (ou 24.04)
   - Shape : **VM.Standard.A1.Flex** (Ampere), **4 OCPU, 24 Go** de mémoire
   - Télécharge la clé SSH proposée (fichier `.key`)
   - Si Oracle répond « Out of capacity », réessaie plus tard ou change de zone (*Availability Domain*).
3. Dans *Networking > Virtual Cloud Network > Security List*, ajoute une règle d'entrée : source `0.0.0.0/0`, TCP, port **8080**.

## 2. Installer le modèle
Depuis ton PC (PowerShell) :
```
ssh -i chemin\vers\cle.key ubuntu@IP_DU_SERVEUR
```
Puis sur le serveur :
```
curl -O https://raw.githubusercontent.com/sylmou2023-alt/growgpt/main/serveur-ia/installer.sh
CLE_API="choisis_un_long_mot_de_passe" bash installer.sh
```
Le script compile llama.cpp, télécharge Mistral 7B (~4 Go) et le lance au démarrage du serveur.

## 3. Relier à GrowGPT
Dans Render, variables d'environnement :
| Variable | Valeur |
|---|---|
| `LLM_BASE_URL` | `http://IP_DU_SERVEUR:8080/v1` |
| `LLM_API_KEY`  | le mot de passe choisi |
| `LLM_TIMEOUT`  | `40` |

## À savoir
- Sans carte graphique, une réponse prend environ 5 à 25 s. Pour plus de vitesse, relance l'installation avec un modèle plus petit :
  `MODELE="bartowski/Qwen2.5-3B-Instruct-GGUF:Q4_K_M" CLE_API="..." bash installer.sh`
- Si le serveur Oracle ne répond pas, GrowGPT repasse automatiquement sur ses réponses par mots-clés.
- La liaison Render → Oracle est en HTTP simple : utilise un mot de passe qui ne sert nulle part ailleurs.
