#!/usr/bin/env bash
# actualizar.sh — decisión 70: el código llega a la EC2 SOLO con git pull desde GitHub. SIN sudo, como nflbot («EC2 nfl»).
#   bash ~/nfl_sim/actualizar.sh            trae lo nuevo del motor (oldegwitz/nfl_sim), lo prueba y reinicia el bot de órdenes
#   bash ~/nfl_sim/actualizar.sh nfl_ev     lo mismo para el laboratorio viejo (oldegwitz/nfl_ev) y el bot nfl-ev-bot
# Pasos: git fetch · muestra los commits que llegan · espera el candado del motor (hasta 15 min si está corriendo) ·
#   git merge --ff-only · si cambió requirements-lock.txt, pip install · pruebas (s2-v1 intacto, compila, importa,
#   bola.py y briefing.py prueba) · si una falla, vuelve sola al commit anterior · si cambiaron unidades, las reinstala ·
#   reinicia el servicio. Nunca hace commits en la EC2 y para si alguien editó código aquí.
set -uo pipefail
QUE="${1:-nfl_sim}"
case "$QUE" in nfl_sim|nfl_ev) ;; *) sed -n '2,4p' "$0"; exit 1 ;; esac
SIM="${NFL_SIM_DIR:-$HOME/nfl_sim}"
D="$( [ "$QUE" = nfl_sim ] && echo "$SIM" || echo "${NFL_EV_DIR:-$HOME/nfl_ev}")"
USUARIO="${NFL_USUARIO:-nflbot}"
S2=baad72c6a5dc0054a7de22a79c88616f
CAND="$SIM/salidas/semana/.candado"
SERVICIO="$( [ "$QUE" = nfl_sim ] && echo nfl-sim-orden.service || echo nfl-ev-bot.service)"
SIN_SERVICIOS="${NFL_SIN_SERVICIOS:-}"          # solo para la réplica de prueba (sin systemd)

ok()   { echo "OK   $*"; }
alto() { echo "ALTO $*"; echo "No se cambió nada."; exit 1; }
md5()  { md5sum "$1" 2>/dev/null | cut -d' ' -f1; }

echo "== actualizar.sh $QUE · $(date '+%d-%m-%Y %H:%M')"
[ "$(id -un)" = "$USUARIO" ] || alto "córrelo como $USUARIO (host «EC2 nfl»)."
cd "$D" 2>/dev/null && git rev-parse --git-dir >/dev/null 2>&1 || alto "$D no es un clon de Git."
[ -z "$(git status --porcelain --untracked-files=no)" ] || alto "hay código editado en la EC2 ($(git status --porcelain --untracked-files=no | awk '{print $2}' | tr '\n' ' ')). En la EC2 no se edita código: pégale esto a Claude."
git fetch -q origin || alto "no pude leer GitHub (llave de despliegue o red)."
NUEVOS="$(git rev-list --count HEAD..origin/main)"
if [ "$NUEVOS" = 0 ]; then ok "ya está al día: $(git log -1 --format='%h %s' | cut -c1-90)"; exit 0; fi
git merge-base --is-ancestor HEAD origin/main || alto "GitHub no sigue la historia de la EC2 (main reescrito). Pégale esto a Claude."
echo "Llegan $NUEVOS commit(s):"
git log --format='  %h %s' HEAD..origin/main | cut -c1-120
ANTES="$(git rev-parse HEAD)"

mkdir -p "$(dirname "$CAND")"
exec 9>"$CAND"
echo "...  espero el candado del motor (si está corriendo, hasta 15 min)"
flock -w 900 9 || alto "el motor lleva más de 15 min corriendo: prueba más tarde."
git merge -q --ff-only origin/main || { flock -u 9; alto "git merge --ff-only falló."; }
CAMBIOS="$(git diff --name-only "$ANTES" HEAD)"
ok "código en $(git log -1 --format=%h) ($(echo "$CAMBIOS" | wc -l) archivo(s) cambiados)"

LOCK_CAMBIO=0; echo "$CAMBIOS" | grep -qx requirements-lock.txt && LOCK_CAMBIO=1
volver() {
  git reset -q --hard "$ANTES"
  [ "$LOCK_CAMBIO" = 1 ] && nice -n 10 venv/bin/pip install -q --disable-pip-version-check --no-cache-dir -r requirements-lock.txt
  echo "VUELTA ATRÁS: quedó $(git log -1 --format='%h %s' | cut -c1-80). El servicio no se reinició."
}
falla() { echo "FALLÓ $*"; volver; flock -u 9; exit 1; }

if [ "$LOCK_CAMBIO" = 1 ]; then
  nice -n 10 venv/bin/pip install -q --disable-pip-version-check --no-cache-dir -r requirements-lock.txt || falla "pip install"
  ok "paquetes al día con requirements-lock.txt"
fi
nice -n 10 venv/bin/python -m py_compile ./*.py 2>/dev/null || falla "algún .py no compila"
ok "compila"
if [ "$QUE" = nfl_sim ]; then
  [ "$(md5 sprint2.py)" = "$S2" ] || falla "sprint2.py dejó de ser s2-v1 (anularía la confirmación 31A)"
  ok "s2-v1 intacto ($S2)"
  nice -n 10 venv/bin/python -c "import semana, orden, parlay, clima, tablero, bola, briefing" 2>/dev/null || falla "algún módulo no importa"
  ok "importan semana, orden, parlay, clima, tablero, bola y briefing"
  nice -n 10 venv/bin/python bola.py prueba 2>&1 | tail -n 1 | grep -q "RESULTADO: OK" || falla "bola.py prueba"
  nice -n 10 venv/bin/python briefing.py prueba 2>&1 | tail -n 1 | grep -q "RESULTADO: OK" || falla "briefing.py prueba"
  ok "bola.py y briefing.py prueba"
fi
flock -u 9
exec 9>&-

if [ -n "$SIN_SERVICIOS" ]; then echo "== LISTO (réplica: sin servicios)"; exit 0; fi
if echo "$CAMBIOS" | grep -q '^systemd/'; then
  bash "$SIM/instalar_servicios.sh" unidades | grep -E '^(OK|MAL|ALTO)' || true
fi
systemctl --user restart "$SERVICIO"
sleep 8
[ "$(systemctl --user is-active "$SERVICIO")" = active ] && ok "$SERVICIO reiniciado y activo" || echo "MAL  $SERVICIO: $(systemctl --user is-active "$SERVICIO") (pégale esto a Claude; vuelta atrás: cd $D && git reset --hard $ANTES)"
if [ "$QUE" = nfl_sim ]; then
  ok "bot de órdenes: $(grep -a 'escuchando' salidas/semana/orden.log 2>/dev/null | tail -n 1 | sed 's/.*\] //' | cut -c1-70)"
  ok "$(nice -n 10 venv/bin/python semana.py estado 2>&1 | head -n 1 | cut -c1-100)"
  ok "temporizador del motor: $(systemctl --user is-active nfl-sim-semana.timer)"
fi
echo "== LISTO: $QUE en $(git log -1 --format='%h %s' | cut -c1-80)"
