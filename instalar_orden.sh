#!/usr/bin/env bash
# instalar_orden.sh — servicio de órdenes por Telegram del motor (una sola vez, con sudo).
#   Crea /etc/systemd/system/nfl-sim-orden.service: corre orden.py como ubuntu, siempre activo, con los mismos
#   límites que el motor (Nice=10, CPUWeight=20 < 50 del bot, MemoryMax=1536M para la corrida que lance, sin swap).
#   No toca nfl-ev-bot ni el temporizador. Se puede correr otra vez (reescribe el archivo y reinicia el servicio).
#   Uso:  sudo bash /home/ubuntu/nfl_sim/instalar_orden.sh
#   Deshacer:  sudo systemctl disable --now nfl-sim-orden && sudo rm /etc/systemd/system/nfl-sim-orden.service && sudo systemctl daemon-reload
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "Correr con: sudo bash $0"; exit 1; }
U=ubuntu
D=/home/$U/nfl_sim
[ -x "$D/venv/bin/python" ] && [ -f "$D/orden.py" ] && [ -f "$D/semana.py" ] || { echo "ALTO: falta orden.py, semana.py o el venv en $D"; exit 1; }
[ -s "$D/credenciales/telegram_motor.token" ] || { echo "ALTO: falta el token del bot del motor. Primero: bash $D/cargar_token.sh"; exit 1; }
install -d -o $U -g $U "$D/salidas/semana"
touch "$D/salidas/semana/orden.log" && chown $U:$U "$D/salidas/semana/orden.log"

cat > /etc/systemd/system/nfl-sim-orden.service <<EOF
[Unit]
Description=Motor nfl_sim: ordenes por Telegram (bot del motor; responde solo al chat de Ozz)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$U
Group=$U
WorkingDirectory=$D
ExecStart=$D/venv/bin/python -u $D/orden.py
Restart=always
RestartSec=30
Nice=10
CPUWeight=20
MemoryMax=1536M
MemorySwapMax=0
StandardOutput=append:$D/salidas/semana/orden.log
StandardError=append:$D/salidas/semana/orden.log

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable nfl-sim-orden.service >/dev/null 2>&1
systemctl restart nfl-sim-orden.service
sleep 5
echo
echo "OK  servicio de órdenes: $(systemctl is-active nfl-sim-orden)"
tail -n 2 "$D/salidas/semana/orden.log" || true
echo "OK  bot nfl-ev-bot: $(systemctl is-active nfl-ev-bot)"
echo "OK  temporizador del motor: $(systemctl is-active nfl-sim-semana.timer)"
echo "== LISTO. En Telegram, al bot nuevo: /ayuda"
