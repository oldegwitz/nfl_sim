#!/usr/bin/env bash
# pico_memoria.sh — decisión 70: lo llama nfl-sim-semana.service al terminar cada corrida (ExecStopPost=-, así que si falla
#   no afecta a la corrida). Anota en salidas/semana/semana.log el pico de memoria de la corrida tal como lo cuenta su tope
#   (cgroup: el motor, el tablero, el clima y todo lo que lance), solo en las corridas reales (≥ 300 MiB) o si terminó mal
#   (por ejemplo «oom-kill»). Sirve para medir con datos de la EC2 si el tope de 1 GB alcanza. No toca nada más.
R="${NFL_CGROUP_RAIZ:-/sys/fs/cgroup}"
cg="$(sed -n 's/^0:://p' /proc/self/cgroup)"
[ -n "${NFL_CGROUP_RAIZ:-}" ] && cg=""
pk="$(cat "$R$cg/memory.peak" 2>/dev/null)" || exit 0
mx="$(cat "$R$cg/memory.max" 2>/dev/null)"
[ -n "$pk" ] || exit 0
mb=$(( pk / 1048576 ))
res="${SERVICE_RESULT:-desconocido}"
[ "$mb" -ge 300 ] || [ "$res" != success ] || exit 0
case "$mx" in ''|max) tope="sin tope" ;; *) tope="tope $(( mx / 1048576 )) MiB" ;; esac
echo "[$(date -u '+%Y-%m-%d %H:%M:%S UTC')] unidad nfl-sim-semana: pico de memoria $mb MiB ($tope) · resultado $res" \
  >> "$HOME/nfl_sim/salidas/semana/semana.log"
