#!/usr/bin/env bash
# actualizar.sh — decisión 70: el código llega a la EC2 SOLO con git pull desde GitHub. SIN sudo, como nflbot («EC2 nfl»).
#   bash ~/nfl_sim/actualizar.sh            trae lo nuevo del motor (oldegwitz/nfl_sim), lo prueba y reinicia el bot de órdenes
#   bash ~/nfl_sim/actualizar.sh nfl_ev     lo mismo para el laboratorio viejo (oldegwitz/nfl_ev) y el bot nfl-ev-bot
# Cómo: git fetch · muestra los commits que llegan · PRUEBA el código nuevo en una carpeta aparte (git worktree), sin tocar
#   el que está corriendo: s2-v1 intacto, compila, importa, bola.py y briefing.py prueba · solo si todo pasa, con el candado
#   del motor (espera hasta 15 min si está corriendo), git merge --ff-only · reinstala unidades si cambiaron · reinicia.
# Si se corta la conexión del teléfono a mitad, sigue solo hasta el final (ignora el corte) y deja todo en salidas/actualizar.log.
# Nunca hace commits en la EC2; para si alguien editó código aquí o si el cambio trae paquetes nuevos (eso se hace con Claude).
set -uo pipefail
trap '' HUP                                  # un corte de Termius no deja la actualización a medias
QUE="${1:-nfl_sim}"
case "$QUE" in nfl_sim|nfl_ev) ;; *) sed -n '2,4p' "$0"; exit 1 ;; esac
SIM="${NFL_SIM_DIR:-$HOME/nfl_sim}"
D="$( [ "$QUE" = nfl_sim ] && echo "$SIM" || echo "${NFL_EV_DIR:-$HOME/nfl_ev}")"
USUARIO="${NFL_USUARIO:-nflbot}"
S2=baad72c6a5dc0054a7de22a79c88616f
CAND="$SIM/salidas/semana/.candado"
LOG="$SIM/salidas/actualizar.log"
SERVICIO="$( [ "$QUE" = nfl_sim ] && echo nfl-sim-orden.service || echo nfl-ev-bot.service)"
SIN_SERVICIOS="${NFL_SIN_SERVICIOS:-}"          # solo para la réplica de prueba (sin systemd)
WT=""

mkdir -p "$(dirname "$LOG")" "$(dirname "$CAND")"
di()   { echo "$*"; echo "[$(date -u '+%Y-%m-%d %H:%M:%S UTC')] $QUE · $*" >> "$LOG" 2>/dev/null; }
ok()   { di "OK   $*"; }
alto() { di "ALTO $*"; di "No se cambió nada."; exit 1; }
md5()  { md5sum "$1" 2>/dev/null | cut -d' ' -f1; }
limpiar() { [ -n "$WT" ] && git -C "$D" worktree remove --force "$WT" >/dev/null 2>&1; [ -n "$WT" ] && rm -rf "$WT"; }
trap limpiar EXIT

di "== actualizar.sh $QUE · $(date '+%d-%m-%Y %H:%M')"
[ "$(id -un)" = "$USUARIO" ] || alto "córrelo como $USUARIO (host «EC2 nfl»)."
cd "$D" 2>/dev/null && git rev-parse --git-dir >/dev/null 2>&1 || alto "$D no es un clon de Git."
git worktree prune 2>/dev/null
[ -z "$(git status --porcelain --untracked-files=no)" ] || alto "hay código editado en la EC2 ($(git status --porcelain --untracked-files=no | awk '{print $2}' | tr '\n' ' ')). En la EC2 no se edita código: pégale esto a Claude."
git fetch -q origin || alto "no pude leer GitHub (llave de despliegue o red)."
NUEVOS="$(git rev-list --count HEAD..origin/main)"
if [ "$NUEVOS" = 0 ]; then ok "ya está al día: $(git log -1 --format='%h %s' | cut -c1-90)"; exit 0; fi
git merge-base --is-ancestor HEAD origin/main || alto "GitHub no sigue la historia de la EC2 (main reescrito). Pégale esto a Claude."
ANTES="$(git rev-parse HEAD)"; DESTINO="$(git rev-parse origin/main)"
di "Llegan $NUEVOS commit(s):"
git log --format='  %h %s' "$ANTES..$DESTINO" | cut -c1-120 | while IFS= read -r l; do di "$l"; done
CAMBIOS="$(git diff --name-only "$ANTES" "$DESTINO")"
echo "$CAMBIOS" | grep -qx 'requirements-lock.txt' && alto "el cambio trae paquetes nuevos (requirements-lock.txt): esa actualización se hace paso a paso con Claude."
# un archivo NUEVO en Git que ya existe aquí como dato ignorado se pisaría sin aviso
for f in $(git diff --name-only --diff-filter=A "$ANTES" "$DESTINO"); do
  [ -e "$f" ] && alto "el commit nuevo versiona $f, que aquí ya existe como dato (se pisaría). Pégale esto a Claude."
done

# 1. probar el código nuevo aparte (el que corre no se toca)
WT="$(mktemp -d "${TMPDIR:-/tmp}/actualizar_${QUE}_XXXXXX")"
git worktree add -q --detach "$WT" "$DESTINO" 2>/dev/null || { WT=""; alto "no pude preparar la carpeta de prueba (git worktree)."; }
PY="$D/venv/bin/python"
(cd "$WT" && nice -n 10 "$PY" -m py_compile ./*.py) 2>/dev/null || alto "el código nuevo no compila."
ok "el código nuevo ($(git log -1 --format=%h "$DESTINO")) compila"
if [ "$QUE" = nfl_sim ]; then
  [ "$(md5 "$WT/sprint2.py")" = "$S2" ] || alto "el código nuevo cambia sprint2.py (dejaría de ser s2-v1 y anularía 31A)."
  ok "s2-v1 intacto ($S2)"
  (cd "$WT" && nice -n 10 "$PY" -c "import semana, orden, parlay, clima, tablero, bola, briefing") >/dev/null 2>&1 || alto "algún módulo nuevo no importa."
  ok "importan semana, orden, parlay, clima, tablero, bola y briefing"
  (cd "$WT" && nice -n 10 "$PY" bola.py prueba 2>&1 | tail -n 1 | grep -q "RESULTADO: OK") || alto "bola.py prueba falló con el código nuevo."
  (cd "$WT" && nice -n 10 "$PY" briefing.py prueba 2>&1 | tail -n 1 | grep -q "RESULTADO: OK") || alto "briefing.py prueba falló con el código nuevo."
  ok "bola.py y briefing.py prueba"
fi
limpiar; WT=""

# 2. pasar al código nuevo (un instante, con el candado: ninguna corrida del motor a la mitad)
exec 9>"$CAND"
di "...  espero el candado del motor (si está corriendo, hasta 15 min)"
flock -w 900 9 || alto "el motor lleva más de 15 min corriendo: prueba más tarde."
trap '' INT TERM
[ "$(git rev-parse HEAD)" = "$ANTES" ] || { flock -u 9; alto "el código cambió mientras probaba: corre otra vez."; }
git merge -q --ff-only "$DESTINO" || { flock -u 9; alto "git merge --ff-only falló."; }
flock -u 9; exec 9>&-
ok "código en $(git log -1 --format=%h) ($(echo "$CAMBIOS" | wc -l) archivo(s) cambiados) · antes $(git rev-parse --short "$ANTES")"

# 3. servicios
if [ -n "$SIN_SERVICIOS" ]; then di "== LISTO (réplica: sin servicios)"; exit 0; fi
if echo "$CAMBIOS" | grep -q '^systemd/'; then
  bash "$SIM/instalar_servicios.sh" unidades 2>&1 | grep -E '^(OK|MAL|ALTO)' | while IFS= read -r l; do di "$l"; done
fi
systemctl --user restart "$SERVICIO"
sleep 8
if [ "$(systemctl --user is-active "$SERVICIO")" = active ]; then ok "$SERVICIO reiniciado y activo"
else di "MAL  $SERVICIO: $(systemctl --user is-active "$SERVICIO"). Vuelta atrás: cd $D && git reset --hard $(git rev-parse --short "$ANTES") && systemctl --user restart $SERVICIO"; fi
if [ "$QUE" = nfl_sim ]; then
  ok "bot de órdenes: $(grep -a 'escuchando' salidas/semana/orden.log 2>/dev/null | tail -n 1 | sed 's/.*\] //' | cut -c1-70)"
  ok "temporizador del motor: $(systemctl --user is-active nfl-sim-semana.timer)"
fi
di "== LISTO: $QUE en $(git log -1 --format='%h %s' | cut -c1-80)"
