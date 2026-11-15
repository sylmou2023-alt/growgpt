#!/usr/bin/env bash
# ============================================================
# installer.sh — Installe Mistral 7B sur un serveur Oracle Cloud "Always Free"
# (Ubuntu, processeur Ampere ARM, 4 cœurs, 24 Go)
#
# Utilisation, une fois connectée au serveur en SSH :
#   CLE_API="un_mot_de_passe_long_et_secret" bash installer.sh
# ============================================================
set -euo pipefail

CLE_API="${CLE_API:?Donne une clé : CLE_API=\"...\" bash installer.sh}"
MODELE="${MODELE:-bartowski/Mistral-7B-Instruct-v0.3-GGUF:Q4_K_M}"
PORT="${PORT:-8080}"

echo "== 1/4 Paquets nécessaires"
sudo apt-get update -y
sudo DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a apt-get install -y build-essential cmake git libssl-dev iptables-persistent

echo "== 2/4 Compilation de llama.cpp (quelques minutes)"
if [ ! -d "$HOME/llama.cpp" ]; then
  git clone --depth 1 https://github.com/ggml-org/llama.cpp "$HOME/llama.cpp"
fi
cd "$HOME/llama.cpp"
rm -f build/CMakeCache.txt
cmake -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j"$(nproc)" --target llama-server

echo "== 3/4 Service qui démarre tout seul (et télécharge le modèle au 1er lancement)"
sudo tee /etc/systemd/system/growgpt-ia.service >/dev/null <<SERVICE
[Unit]
Description=GrowGPT IA (llama.cpp + Mistral)
After=network-online.target
Wants=network-online.target

[Service]
User=$USER
Environment=LLAMA_CACHE=$HOME/modeles
ExecStart=$HOME/llama.cpp/build/bin/llama-server -hf $MODELE --host 0.0.0.0 --port $PORT --api-key $CLE_API -c 4096 -t $(nproc) --parallel 2
Restart=always

[Install]
WantedBy=multi-user.target
SERVICE
sudo systemctl daemon-reload
sudo systemctl enable --now growgpt-ia

echo "== 4/4 Ouverture du port $PORT dans le pare-feu du serveur"
# La règle doit passer AVANT la ligne REJECT de l'image Oracle, sinon elle ne sert à rien
if ! sudo iptables -C INPUT -m state --state NEW -p tcp --dport "$PORT" -j ACCEPT 2>/dev/null; then
  LIGNE_REJECT=$(sudo iptables -L INPUT --line-numbers -n | awk '$2 == "REJECT" {print $1; exit}')
  sudo iptables -I INPUT "${LIGNE_REJECT:-1}" -m state --state NEW -p tcp --dport "$PORT" -j ACCEPT
fi
sudo netfilter-persistent save

IP=$(curl -s https://ifconfig.me || echo "TON_IP")
echo
echo "Terminé ! Le modèle (~4 Go) se télécharge maintenant : suis-le avec"
echo "   journalctl -u growgpt-ia -f"
echo
echo "N'oublie pas d'ouvrir aussi le port $PORT dans la console Oracle (Security List)."
echo "Puis, dans Render, ajoute :"
echo "   LLM_BASE_URL = http://$IP:$PORT/v1"
echo "   LLM_API_KEY  = $CLE_API"
echo "   LLM_TIMEOUT  = 40"
