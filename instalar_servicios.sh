#!/usr/bin/env bash
# instalar_servicios.sh — decisión 70 (EC2 compartida): los servicios de NFL como unidades de USUARIO de nflbot. SIN sudo.
#   bash ~/nfl_sim/instalar_servicios.sh venvs      crea ~/nfl_ev/venv y ~/nfl_sim/venv con las versiones fijadas (requirements-lock.txt)
#   bash ~/nfl_sim/instalar_servicios.sh unidades   copia las 4 unidades a ~/.config/systemd/user y las revisa (NO las arranca)
#   bash ~/nfl_sim/instalar_servicios.sh arrancar   las habilita y arranca (solo con los datos ya copiados y las viejas paradas)
#   bash ~/nfl_sim/instalar_servicios.sh prueba     prueba final del aviso v3 (solo mira; no cambia nada)
# Las unidades se editan en Git (~/nfl_sim/systemd/ y ~/nfl_ev/systemd/), nunca en ~/.config: allá se copian.
# Se puede correr otra vez sin daño.
set -uo pipefail
SIM="${NFL_SIM_DIR:-$HOME/nfl_sim}"
EV="${NFL_EV_DIR:-$HOME/nfl_ev}"
UD="$HOME/.config/systemd/user"
USUARIO="${NFL_USUARIO:-nflbot}"
S2=baad72c6a5dc0054a7de22a79c88616f                     # s2-v1 congelado (31A)
# Topes acordados (decisión 70): unidad → MemoryMax en bytes; slice del usuario: MemoryHigh 1,1G, MemoryMax 1,25G, 1 vCPU
declare -A TOPE=([nfl-ev-bot.service]=367001600 [nfl-sim-orden.service]=1073741824 [nfl-sim-semana.service]=1073741824)
# lo que el kernel debe tener en cada unidad activa: memory.max memory.high memory.swap.max cpu.weight
declare -A KERNEL=([nfl-ev-bot.service]="367001600 262144000 157286400 50" [nfl-sim-orden.service]="1073741824 max 0 20")
SLICE_HIGH=1181116006; SLICE_MAX=1342177280; SLICE_CPU=1s; SLICE_PESO=50
ARRANCAN="nfl-ev-bot.service nfl-sim-orden.service nfl-sim-semana.timer"

FALLOS=0
ok()   { echo "OK   $*"; }
mal()  { echo "MAL  $*"; FALLOS=$((FALLOS + 1)); }
alto() { echo "ALTO $*"; exit 1; }
md5()  { md5sum "$1" 2>/dev/null | cut -d' ' -f1; }

MODO="${1:-}"
case "$MODO" in venvs|unidades|arrancar|prueba) ;; *) sed -n '2,7p' "$0"; exit 1 ;; esac
[ "$(id -un)" = "$USUARIO" ] || alto "córrelo como $USUARIO (host «EC2 nfl»), no como $(id -un)."
[ -f "$SIM/semana.py" ] && [ -f "$EV/nfl_ev_bot.py" ] || alto "no encuentro $SIM/semana.py o $EV/nfl_ev_bot.py: primero clona los dos repositorios."
echo "== instalar_servicios.sh $MODO · $(date '+%d-%m-%Y %H:%M') · $(id -un) · nfl_sim $(git -C "$SIM" log -1 --format=%h 2>/dev/null) · nfl_ev $(git -C "$EV" log -1 --format=%h 2>/dev/null)"

user_ok() {   # el administrador de servicios del usuario responde (linger + sesión)
  [ -n "${XDG_RUNTIME_DIR:-}" ] || export XDG_RUNTIME_DIR="/run/user/$(id -u)"
  loginctl show-user "$(id -un)" -p Linger 2>/dev/null | grep -q '=yes' || alto "falta el linger de $(id -un) (paso B1: sudo loginctl enable-linger $(id -un))."
  systemctl --user show-environment >/dev/null 2>&1 || alto "systemctl --user no responde (entra de nuevo con «EC2 nfl» y repite)."
}

viejas_ok() {   # las unidades VIEJAS del sistema (usuario ubuntu): paradas y que no vuelvan al reiniciar
  VIEJAS_MAL=""
  local u e
  for u in nfl-ev-bot.service nfl-sim-orden.service nfl-sim-semana.timer nfl-sim-semana.service; do
    systemctl is-active --quiet "$u" 2>/dev/null && VIEJAS_MAL="$VIEJAS_MAL $u activa;"
    e="$(systemctl is-enabled "$u" 2>/dev/null)"
    case "$e" in enabled|enabled-runtime|alias|linked|linked-runtime) VIEJAS_MAL="$VIEJAS_MAL $u habilitada (volvería al reiniciar);" ;; esac
  done
  [ -z "$VIEJAS_MAL" ]
}

# ------------------------------------------------------------------------------------------ venvs
venv_de() {   # carpeta, módulos a importar
  local d="$1" mods="$2" lock="$1/requirements-lock.txt" fz
  [ -f "$lock" ] || alto "falta $lock"
  if [ ! -x "$d/venv/bin/python" ]; then
    python3 -m venv "$d/venv" || alto "no pude crear $d/venv (¿falta el paquete python3-venv? eso lo instala el administrador)."
  fi
  fz() { "$d/venv/bin/pip" freeze --disable-pip-version-check 2>/dev/null | sort -f; }
  if diff -q <(fz) <(grep -Ev '^\s*(#|$)' "$lock" | sort -f) >/dev/null; then
    ok "$(basename "$d")/venv ya tenía las versiones fijadas"
  else
    echo "...  instalando $(grep -Ecv '^\s*(#|$)' "$lock") paquetes en $(basename "$d")/venv (unos minutos, con prioridad baja)"
    nice -n 10 "$d/venv/bin/pip" install -q --disable-pip-version-check --no-cache-dir -r "$lock" || alto "pip falló en $d/venv"
    diff -q <(fz) <(grep -Ev '^\s*(#|$)' "$lock" | sort -f) >/dev/null || mal "$(basename "$d")/venv no quedó igual al lock: $(diff <(fz) <(grep -Ev '^\s*(#|$)' "$lock" | sort -f) | grep -c '^[<>]') diferencias"
  fi
  "$d/venv/bin/python" -c "import $mods" 2>/dev/null && ok "$(basename "$d")/venv: Python $("$d/venv/bin/python" -c 'import sys;print(sys.version.split()[0])') · importa $mods" \
    || mal "$(basename "$d")/venv no importa $mods"
}
if [ "$MODO" = venvs ]; then
  PYV="$(python3 -c 'import sys;print("%d.%d" % sys.version_info[:2])')"
  [ "$PYV" = 3.12 ] && ok "python3 del sistema: $PYV (el de siempre)" || echo "AVISO python3 es $PYV y el motor se probó con 3.12"
  venv_de "$EV" "polars, nflreadpy, openpyxl, requests"
  venv_de "$SIM" "numpy, polars, numba, nflreadpy, google.auth, matplotlib, requests"
  [ "$FALLOS" = 0 ] && echo "== LISTO venvs" || { echo "== $FALLOS problema(s): pégale esta salida a Claude"; exit 1; }
  exit 0
fi

# ------------------------------------------------------------------------------------------ unidades
if [ "$MODO" = unidades ]; then
  user_ok
  mkdir -p "$UD"
  for f in "$EV/systemd/nfl-ev-bot.service" "$SIM/systemd/nfl-sim-orden.service" "$SIM/systemd/nfl-sim-semana.service" "$SIM/systemd/nfl-sim-semana.timer"; do
    [ -f "$f" ] || alto "falta $f (¿git pull?)"
    install -m 644 "$f" "$UD/$(basename "$f")"
  done
  systemctl --user daemon-reload
  for u in nfl-ev-bot.service nfl-sim-orden.service nfl-sim-semana.service nfl-sim-semana.timer; do
    v="$(systemd-analyze --user verify "$UD/$u" 2>&1 | grep -v 'system bus' | head -n 2)"
    [ -z "$v" ] && ok "$u copiada y revisada ($(systemctl --user is-enabled "$u" 2>/dev/null))" || mal "$u: $v"
  done
  # entrar con «EC2 nfl» directo en la carpeta del motor (solo sesiones interactivas)
  grep -q 'cd ~/nfl_sim' "$HOME/.bashrc" 2>/dev/null || echo '[ -d ~/nfl_sim ] && cd ~/nfl_sim   # decisión 70: «EC2 nfl» entra en el motor' >> "$HOME/.bashrc"
  ok "«EC2 nfl» entra directo en ~/nfl_sim"
  [ "$FALLOS" = 0 ] && echo "== LISTO unidades (no arrancan todavía: eso es «arrancar», con los datos ya copiados)" || { echo "== $FALLOS problema(s)"; exit 1; }
  exit 0
fi

# ------------------------------------------------------------------------------------------ arrancar
if [ "$MODO" = arrancar ]; then
  user_ok
  for f in "$EV/config.ini" "$EV/lineas_log.csv" "$SIM/semana.ini" "$SIM/credenciales/telegram_motor.token" \
           "$SIM/salidas/semana/estado.json" "$SIM/salidas/semana/proyecciones_2026.csv"; do
    [ -s "$f" ] || alto "falta ${f#$HOME/}: primero el paso B3 (copiar los datos con migrar_datos.sh)."
  done
  ok "datos y secretos en su lugar"
  viejas_ok || alto "$VIEJAS_MAL (dos bots leerían el mismo Telegram). Con «EC2 admin»: sudo systemctl disable --now nfl-sim-semana.timer nfl-sim-orden.service nfl-ev-bot.service"
  ok "las unidades viejas del sistema están paradas y deshabilitadas"
  [ "$(md5 "$SIM/sprint2.py")" = "$S2" ] || alto "sprint2.py no es s2-v1."
  ok "s2-v1 intacto ($S2)"
  [ -x "$SIM/venv/bin/python" ] && [ -x "$EV/venv/bin/python" ] || alto "faltan los venvs: bash ~/nfl_sim/instalar_servicios.sh venvs"
  for u in nfl-ev-bot.service nfl-sim-orden.service nfl-sim-semana.service nfl-sim-semana.timer; do
    cmp -s "$UD/$u" "$( [ "$u" = nfl-ev-bot.service ] && echo "$EV" || echo "$SIM")/systemd/$u" || alto "$u en ~/.config no es la de Git: bash ~/nfl_sim/instalar_servicios.sh unidades"
  done
  systemctl --user enable --now $ARRANCAN >/dev/null 2>&1 || alto "no pude arrancar: $(systemctl --user --failed --no-legend | head -n 3)"
  echo "...  espero 12 s a que arranquen"
  sleep 12
  for u in $ARRANCAN; do
    [ "$(systemctl --user is-active "$u")" = active ] && ok "$u: activa y habilitada ($(systemctl --user is-enabled "$u"))" || mal "$u: $(systemctl --user is-active "$u")"
  done
  ok "bot de órdenes: $(grep -a 'escuchando' "$SIM/salidas/semana/orden.log" 2>/dev/null | tail -n 1 | sed 's/.*\] //' | cut -c1-80)"
  ok "próxima revisión del motor: $(systemctl --user list-timers nfl-sim-semana.timer --no-legend 2>/dev/null | awk '{print $2, $3}')"
  [ "$FALLOS" = 0 ] && echo "== LISTO arrancar. Sigue la prueba final: bash ~/nfl_sim/instalar_servicios.sh prueba" || { echo "== $FALLOS problema(s): pégale esta salida a Claude"; exit 1; }
  exit 0
fi

# ------------------------------------------------------------------------------------------ prueba (solo mira)
user_ok
UIDN="$(id -u)"
echo "-- 1. usuario"
G="$(id -nG)"
echo " $G " | grep -Eq ' (sudo|admin|adm|wheel|docker|lxd|systemd-journal) ' && mal "grupos con poderes: $G" || ok "$(id -un) (uid $UIDN), grupos: $G (sin sudo ni docker)"
hm="$(stat -c '%a' "$HOME")"
case "$hm" in 700|750) ok "~ en $hm (nadie más entra)" ;; *) mal "~ en $hm (debe ser 750)" ;; esac
viejas_ok && ok "unidades viejas del sistema paradas y deshabilitadas" || mal "unidades viejas:$VIEJAS_MAL"
echo "-- 2. servicios como $(id -un) y con su tope (lo que aplica el kernel, no solo lo escrito)"
CTRL="$(cat "/sys/fs/cgroup/user.slice/user-$UIDN.slice/user@$UIDN.service/cgroup.controllers" 2>/dev/null)"
echo " $CTRL " | grep -q ' memory ' && echo " $CTRL " | grep -q ' cpu ' && ok "controladores delegados al usuario: $CTRL" || mal "controladores delegados: «$CTRL» (faltan memory o cpu: los topes de las unidades no se aplicarían)"
for u in nfl-ev-bot.service nfl-sim-orden.service; do
  pid="$(systemctl --user show "$u" -p MainPID --value)"
  dueno="$(ps -o user= -p "$pid" 2>/dev/null | tr -d ' ')"
  [ "$(systemctl --user is-active "$u")" = active ] && [ "$dueno" = "$(id -un)" ] && ok "$u activa, proceso $pid de $dueno" || mal "$u: $(systemctl --user is-active "$u") · dueño «$dueno»"
  cg="$(systemctl --user show "$u" -p ControlGroup --value)"
  if [ -n "$cg" ] && [ -r "/sys/fs/cgroup$cg/memory.max" ]; then
    k="$(cat "/sys/fs/cgroup$cg/memory.max" "/sys/fs/cgroup$cg/memory.high" "/sys/fs/cgroup$cg/memory.swap.max" "/sys/fs/cgroup$cg/cpu.weight" 2>/dev/null | tr '\n' ' ' | sed 's/ $//')"
    [ "$k" = "${KERNEL[$u]}" ] && ok "$u en el kernel: max $(( ${TOPE[$u]} / 1048576 )) MiB · high/swap/peso «$(echo "$k" | cut -d' ' -f2-)»" \
      || mal "$u en el kernel: «$k» (esperado «${KERNEL[$u]}»: memory.max memory.high memory.swap.max cpu.weight)"
  else
    mal "$u: no encuentro su cgroup ($cg): el tope no se puede comprobar"
  fi
done
[ "$(systemctl --user show nfl-sim-semana.service -p MemoryMax --value)" = "${TOPE[nfl-sim-semana.service]}" ] && ok "nfl-sim-semana.service: MemoryMax $(( ${TOPE[nfl-sim-semana.service]} / 1048576 )) MiB (se aplica en cada corrida; el pico queda en semana.log)" \
  || mal "nfl-sim-semana.service: MemoryMax «$(systemctl --user show nfl-sim-semana.service -p MemoryMax --value)»"
[ "$(systemctl --user is-active nfl-sim-semana.timer)" = active ] && ok "nfl-sim-semana.timer activo · próxima $(systemctl --user list-timers nfl-sim-semana.timer --no-legend | awk '{print $2, $3}')" || mal "nfl-sim-semana.timer no está activo"
ult="$(systemctl --user show nfl-sim-semana.service -p ExecMainExitTimestamp --value)"
r="$(systemctl --user show nfl-sim-semana.service -p Result --value)"
if [ -z "$ult" ] || [ "$ult" = n/a ]; then echo "AVISO el motor todavía no corrió como $(id -un) (el temporizador lo lanza cada 5 min; repite la prueba después)"
elif [ "$r" = success ]; then ok "última corrida del motor: $ult · $r"
else mal "última corrida del motor: $ult · $r (mira el final de salidas/semana/semana.log)"; fi
SL="user-$UIDN.slice"
h="$(systemctl show "$SL" -p MemoryHigh --value)"; m="$(systemctl show "$SL" -p MemoryMax --value)"; c="$(systemctl show "$SL" -p CPUQuotaPerSecUSec --value)"; w="$(systemctl show "$SL" -p CPUWeight --value)"
kh="$(cat "/sys/fs/cgroup/user.slice/$SL/memory.high" 2>/dev/null)"; km="$(cat "/sys/fs/cgroup/user.slice/$SL/memory.max" 2>/dev/null)"
[ "$h" = "$SLICE_HIGH" ] && [ "$m" = "$SLICE_MAX" ] && [ "$c" = "$SLICE_CPU" ] && [ "$w" = "$SLICE_PESO" ] && [ "$kh" = "$SLICE_HIGH" ] && [ "$km" = "$SLICE_MAX" ] \
  && ok "tope de todo NFL ($SL, en el kernel): MemoryHigh $((h / 1048576)) MiB · MemoryMax $((m / 1048576)) MiB · CPU $c por segundo (1 vCPU) · peso $w" \
  || mal "$SL: MemoryHigh «$h»/«$kh» MemoryMax «$m»/«$km» CPU «$c» peso «$w» (esperado $SLICE_HIGH / $SLICE_MAX / $SLICE_CPU / $SLICE_PESO)"
cur="$(cat "/sys/fs/cgroup/user.slice/$SL/memory.current" 2>/dev/null || echo 0)"; pk="$(cat "/sys/fs/cgroup/user.slice/$SL/memory.peak" 2>/dev/null || echo 0)"
ok "memoria de NFL ahora $((cur / 1048576)) MiB · pico desde que arrancó $((pk / 1048576)) MiB"
up="$(grep -a 'pico de memoria' "$SIM/salidas/semana/semana.log" 2>/dev/null | tail -n 1 | sed 's/^\[[^]]*\] //')"
[ -n "$up" ] && ok "última corrida real: $up" || echo "AVISO todavía no hay una corrida real del motor como $(id -un) (al terminar, su pico queda en semana.log)"
echo "-- 3. aislamiento"
for d in /home/ubuntu /home/bnbot /home/traccar; do
  if [ ! -e "$d" ]; then ok "$d no existe"
  elif ls "$d" >/dev/null 2>&1 || [ -x "$d" ]; then mal "$(id -un) puede entrar o leer $d ($(stat -c '%a' "$d"))"
  else ok "$(id -un) no puede entrar a $d"; fi
done
curl -s -m 4 -o /dev/null -X PUT -H "X-aws-ec2-metadata-token-ttl-seconds: 60" http://169.254.169.254/latest/api/token; e=$?
[ "$e" = 7 ] && ok "servicio de metadatos (IPv4) bloqueado: rechazado" || mal "servicio de metadatos (IPv4): curl salió con $e (7 = bloqueado)"
curl -s -g -m 4 -o /dev/null -X PUT -H "X-aws-ec2-metadata-token-ttl-seconds: 60" "http://[fd00:ec2::254]/latest/api/token"; e=$?
[ "$e" != 0 ] && ok "servicio de metadatos (IPv6): no responde (curl $e)" || mal "servicio de metadatos (IPv6) RESPONDE a $(id -un)"
echo "-- 4. Git y secretos"
for r in "$SIM" "$EV"; do
  n="$(basename "$r")"
  sucio="$(git -C "$r" status --porcelain 2>/dev/null)"
  [ -z "$sucio" ] && ok "$n: Git limpio (nada de datos ni secretos a la vista de Git)" || mal "$n: Git ve $(echo "$sucio" | wc -l) archivo(s): $(echo "$sucio" | awk '{print $2}' | head -n 5 | tr '\n' ' ')"
  url="$(git -C "$r" remote get-url origin 2>/dev/null)"
  [ "$url" = "github-$n:oldegwitz/$n.git" ] && ok "$n: origen $url" || mal "$n: origen «$url»"
  if git -C "$r" fetch -q origin 2>/dev/null; then
    [ "$(git -C "$r" rev-parse HEAD)" = "$(git -C "$r" rev-parse origin/main)" ] && ok "$n: igual a GitHub ($(git -C "$r" log -1 --format=%h))" || mal "$n: distinto de GitHub (local $(git -C "$r" log -1 --format=%h), GitHub $(git -C "$r" log -1 --format=%h origin/main))"
  else
    mal "$n: no pude leer GitHub con la llave de despliegue"
  fi
  p="$(git -C "$r" push --dry-run origin HEAD:main 2>&1)"
  echo "$p" | grep -qi "read only\|read-only" && ok "$n: la llave de despliegue es de solo lectura" || mal "$n: la llave de despliegue NO parece de solo lectura: $(echo "$p" | tail -n 1 | cut -c1-120)"
done
for f in semana.ini credenciales/gemini.key credenciales/anthropic.key credenciales/google_sa.json credenciales/telegram_motor.token \
         salidas/semana/estado.json salidas/semana/proyecciones_2026.csv datos/games.csv respaldos venv; do
  [ -e "$SIM/$f" ] || continue
  git -C "$SIM" check-ignore -q "$f" && ok "nfl_sim/$f fuera de Git ($(git -C "$SIM" check-ignore -v "$f" | cut -f1 | sed 's/.*gitignore://'))" || mal "nfl_sim/$f NO está ignorado"
done
for f in config.ini lineas_log.csv historico venv; do
  [ -e "$EV/$f" ] || continue
  git -C "$EV" check-ignore -q "$f" && ok "nfl_ev/$f fuera de Git" || mal "nfl_ev/$f NO está ignorado"
done
nsec=0
for f in "$EV/config.ini" "$SIM/semana.ini" "$SIM"/credenciales/* "$SIM"/respaldos/*/semana.ini; do
  [ -e "$f" ] || continue
  pm="$(stat -c '%a %U' "$f")"
  if [ "$pm" = "600 $(id -un)" ]; then nsec=$((nsec + 1)); else mal "${f#$HOME/}: $pm (debe ser 600 $(id -un))"; fi
done
ok "$nsec secretos en 600 y de $(id -un) (config.ini, semana.ini y sus copias en respaldos/, credenciales/)"
[ "$(stat -c '%a' "$SIM/credenciales" 2>/dev/null)" = 700 ] && ok "credenciales/: 700" || mal "credenciales/: $(stat -c '%a' "$SIM/credenciales" 2>/dev/null)"
echo "-- 5. el motor y Telegram"
[ "$(md5 "$SIM/sprint2.py")" = "$S2" ] && ok "s2-v1 intacto ($S2)" || mal "sprint2.py no es s2-v1"
for i in 1 2 3 4 5 6; do
  est="$(cd "$SIM" && nice -n 10 venv/bin/python semana.py estado 2>&1)"
  echo "$est" | grep -q "Ya hay una corrida" || break
  sleep 15
done
echo "$est" | grep -q "Hoja: conectada" && ok "semana.py estado: $(echo "$est" | head -n 1 | cut -c1-90) · hoja conectada" || mal "semana.py estado: $(echo "$est" | grep -m1 -E 'Hoja|Error|Ya hay' | cut -c1-140)"
tg="$("$SIM/venv/bin/python" - "$EV/config.ini" "$SIM/credenciales/telegram_motor.token" 2>&1 <<'PY'
import configparser, sys, requests
c = configparser.ConfigParser(inline_comment_prefixes=("#", ";")); c.read(sys.argv[1])
toks = [("bot nfl-ev-bot", c.get("telegram", "token", fallback="").strip())]
try:
    toks.append(("bot del motor", open(sys.argv[2]).read().strip()))
except OSError:
    toks.append(("bot del motor", ""))
for nombre, tok in toks:
    if not tok:
        print(f"MAL  {nombre}: no encuentro su token"); continue
    try:
        r = requests.get(f"https://api.telegram.org/bot{tok}/getMe", timeout=20).json()
        print(("OK   " if r.get("ok") else "MAL  ") + f"{nombre}: " + ("@" + r["result"]["username"] if r.get("ok") else "Telegram no lo reconoce"))
    except Exception as e:  # noqa: BLE001
        print(f"MAL  {nombre}: sin respuesta de Telegram ({type(e).__name__})")
PY
)"
echo "$tg"
FALLOS=$((FALLOS + $(echo "$tg" | grep -c '^MAL')))
if journalctl --user -u nfl-ev-bot -n 200 --no-pager -q 2>/dev/null | grep -q .; then
  ok "bot nfl-ev-bot, última línea: $(journalctl --user -u nfl-ev-bot -n 1 --no-pager -q -o cat 2>/dev/null | cut -c1-90)"
else
  echo "AVISO el registro del bot nfl-ev-bot no se ve desde $(id -un) (con «EC2 admin»: sudo journalctl _UID=$UIDN -n 20)"
fi
echo "-- falta a mano: manda /estado al bot del motor en Telegram (debe responder) y entra con «EC2 nfl» (debe quedar en ~/nfl_sim)"
[ "$FALLOS" = 0 ] && echo "== PRUEBA FINAL: todo OK" || { echo "== PRUEBA FINAL: $FALLOS problema(s). Pégale esta salida a Claude."; exit 1; }
