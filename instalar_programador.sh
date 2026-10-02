#!/usr/bin/env bash
# instalar_programador.sh — 23A: temporizador de systemd para la corrida semanal del motor (una sola vez, con sudo).
#   Crea 2 archivos de sistema (cambio acordado en 23A) y los activa:
#     /etc/systemd/system/nfl-sim-semana.service  → corre "semana.py auto" como ubuntu, Nice=10, CPUWeight=20
#                                                    (el bot tiene 50), MemoryMax=1536M, sin swap
#     /etc/systemd/system/nfl-sim-semana.timer    → lo dispara cada 5 min; si no toca nada, sale sin escribir
#   No toca el servicio nfl-ev-bot. Se puede correr otra vez (reescribe los dos archivos).
#   Uso:  sudo bash /home/ubuntu/nfl_sim/instalar_programador.sh
#   Deshacer:  sudo systemctl disable --now nfl-sim-semana.timer && sudo rm /etc/systemd/system/nfl-sim-semana.{service,timer} && sudo systemctl daemon-reload
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "Correr con: sudo bash $0"; exit 1; }
U=ubuntu
D=/home/$U/nfl_sim
[ -x "$D/venv/bin/python" ] && [ -f "$D/semana.py" ] || { echo "ALTO: falta $D/semana.py o el venv"; exit 1; }
install -d -o $U -g $U "$D/salidas/semana"
touch "$D/salidas/semana/semana.log" && chown $U:$U "$D/salidas/semana/semana.log"

cat > /etc/systemd/system/nfl-sim-semana.service <<EOF
[Unit]
Description=Motor nfl_sim s2-v1: corrida semanal en modo registro (31A)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=$U
Group=$U
WorkingDirectory=$D
ExecStart=$D/venv/bin/python -u $D/semana.py auto
Nice=10
CPUWeight=20
MemoryMax=1536M
MemorySwapMax=0
TimeoutStartSec=900
StandardOutput=append:$D/salidas/semana/semana.log
StandardError=append:$D/salidas/semana/semana.log
EOF

cat > /etc/systemd/system/nfl-sim-semana.timer <<EOF
[Unit]
Description=Cada 5 min: ¿toca correr el motor? (miércoles y sábado 10:15 Caracas, T-85 de cada grupo, reajustes)

[Timer]
OnCalendar=*:0/5
AccuracySec=20s
Persistent=false

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now nfl-sim-semana.timer
echo
echo "OK  temporizador activo: $(systemctl is-active nfl-sim-semana.timer)"
systemctl list-timers nfl-sim-semana.timer --no-pager | head -3
echo "OK  bot nfl-ev-bot: $(systemctl is-active nfl-ev-bot)"
echo "== LISTO"
