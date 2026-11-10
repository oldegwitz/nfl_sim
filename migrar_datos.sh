#!/usr/bin/env bash
# migrar_datos.sh — decisión 70, paso B3: copia los DATOS y los SECRETOS de NFL de /home/ubuntu a /home/nflbot.
#   Lo corre el administrador («EC2 admin»), con las unidades viejas YA paradas y deshabilitadas, desde una copia de root
#   (así nflbot no puede cambiarlo mientras corre):
#     sudo install -o root -g root -m 700 /home/nflbot/nfl_sim/migrar_datos.sh /root/migrar_datos.sh && sudo bash /root/migrar_datos.sh
#   · El código NO se copia: llega con git clone/pull. Antes de copiar revisa que el código de /home/ubuntu sea el que
#     subió a GitHub (v9.4 a909269 y el legado edf285d); si no, se perdería algo y para.
#   · Copia todo lo demás (datos/, salidas/, respaldos/, credenciales/, semana.ini, config.ini, historico/, lineas_log.csv…)
#     sin venv/, .git/ ni __pycache__/, con dueño nflbot y los permisos de origen; los secretos quedan en 600 sí o sí.
#   · Nunca pisa un archivo que ya esté en /home/nflbot (se puede correr otra vez sin daño).
#   · Verifica con md5 cada archivo copiado y muestra solo nombres y cantidades, nunca el contenido de un secreto.
#   · /home/ubuntu queda intacto (vuelta atrás: ver registro_70_migracion.md).
set -uo pipefail
VIEJO="${NFL_VIEJO:-/home/ubuntu}"
NUEVO="${NFL_NUEVO:-/home/nflbot}"
USUARIO="${NFL_USUARIO:-nflbot}"
S2=baad72c6a5dc0054a7de22a79c88616f
# el código que tenía la EC2 antes de la migración (lo que subió el bundle de A2): v9.4 y el legado congelado
declare -A BASE=([nfl_sim]=a9092699c466e045ce1c30591e182dc5865639da [nfl_ev]=edf285dc8530e24510900a088aaa9e94424b0459)

ok()   { echo "OK   $*"; }
alto() { echo "ALTO $*"; echo "No se copió nada más. Pégale esta salida a Claude."; exit 1; }
como() { runuser -u "$USUARIO" -- "$@"; }      # lo que se hace DENTRO de /home/nflbot va como nflbot, no como root
md5()  { md5sum "$1" 2>/dev/null | cut -d' ' -f1; }

echo "== migrar_datos.sh · $(date '+%d-%m-%Y %H:%M') · de $VIEJO a $NUEVO"
[ "$(id -u)" -eq 0 ] || alto "córrelo con sudo:  sudo bash $0"
id "$USUARIO" >/dev/null 2>&1 || alto "no existe el usuario $USUARIO (paso B1)."
command -v rsync >/dev/null || alto "falta rsync en la EC2."
for p in nfl_ev nfl_sim; do
  [ -d "$VIEJO/$p" ] || alto "no encuentro $VIEJO/$p"
  [ -d "$NUEVO/$p/.git" ] || alto "no encuentro el clon $NUEVO/$p (paso B2)."
done

# 1. nada corriendo: ni las unidades viejas ni las nuevas
if [ -z "${NFL_PRUEBA:-}" ]; then
  for u in nfl-ev-bot.service nfl-sim-orden.service nfl-sim-semana.timer nfl-sim-semana.service; do
    systemctl is-active --quiet "$u" && alto "la unidad vieja $u sigue activa: sudo systemctl disable --now nfl-sim-semana.timer nfl-sim-orden.service nfl-ev-bot.service"
    case "$(systemctl is-enabled "$u" 2>/dev/null)" in
      enabled|enabled-runtime|alias|linked|linked-runtime) alto "la unidad vieja $u sigue habilitada (volvería al reiniciar): sudo systemctl disable nfl-sim-semana.timer nfl-sim-orden.service nfl-ev-bot.service" ;;
    esac
  done
  ok "unidades viejas paradas y deshabilitadas ($(systemctl is-enabled nfl-ev-bot.service nfl-sim-orden.service nfl-sim-semana.timer 2>/dev/null | tr '\n' ' '))"
  NU="$(id -u "$USUARIO")"
  if [ -S "/run/user/$NU/bus" ]; then
    act="$(como env XDG_RUNTIME_DIR="/run/user/$NU" systemctl --user is-active nfl-ev-bot.service nfl-sim-orden.service nfl-sim-semana.timer 2>/dev/null | grep -c '^active')"
    [ "$act" = 0 ] || alto "hay $act unidad(es) NUEVAS de $USUARIO activas: no copio encima de servicios corriendo."
  fi
  ok "unidades nuevas de $USUARIO paradas"
  pgrep -f "$VIEJO/nfl_(sim|ev)/" >/dev/null && alto "hay procesos de NFL corriendo desde $VIEJO: $(pgrep -af "$VIEJO/nfl_(sim|ev)/" | cut -c1-80 | head -n 3)"
  ok "ningún proceso de NFL corriendo"
fi

# 2. el código de /home/ubuntu es exactamente el que subió a GitHub (commit BASE); si no, se perdería algo
g() { local p="$1"; shift; como git -C "$NUEVO/$p" "$@"; }
declare -A CODIGO      # archivos versionados en BASE: no se copian (los trae Git) ni se comparan con el clon
declare -A QUITADOS    # los que el commit de migración borró: tampoco vuelven
for p in nfl_ev nfl_sim; do
  g "$p" cat-file -e "${BASE[$p]}^{commit}" 2>/dev/null || alto "$p: el clon no tiene el commit ${BASE[$p]:0:7}"
  dif=""; n=0; lista=""
  while IFS= read -r f; do
    n=$((n + 1)); lista="$lista $f"
    [ -f "$VIEJO/$p/$f" ] || { dif="$dif $f(falta)"; continue; }
    [ "$(md5 "$VIEJO/$p/$f")" = "$(g "$p" show "${BASE[$p]}:$f" | md5sum | cut -d' ' -f1)" ] || dif="$dif $f"
  done < <(g "$p" ls-tree -r --name-only "${BASE[$p]}")
  [ -z "$dif" ] || alto "$p: el código de $VIEJO no es el de GitHub (${BASE[$p]:0:7}) en:$dif"
  # los que estaban sueltos en la EC2 y el commit de migración versionó (diag_gemini.py, estudio_sesgo.py): iguales al clon
  while IFS= read -r f; do
    case "$lista " in *" $f "*) continue ;; esac
    lista="$lista $f"
    [ -f "$VIEJO/$p/$f" ] || continue
    cmp -s "$VIEJO/$p/$f" "$NUEVO/$p/$f" || dif="$dif $f"
  done < <(g "$p" ls-files)
  [ -z "$dif" ] || alto "$p: la copia de la EC2 no es la que se versionó en:$dif"
  CODIGO[$p]="$lista "
  QUITADOS[$p]=" $(g "$p" diff --name-only --diff-filter=D "${BASE[$p]}" HEAD | tr '\n' ' ')"
  # código suelto en /home/ubuntu que no está en Git: se perdería
  sueltos="$(cd "$VIEJO/$p" && find . -maxdepth 1 -type f \( -name '*.py' -o -name '*.sh' \) -printf '%P\n' | while read -r f; do
    case "${CODIGO[$p]}" in *" $f "*) continue ;; esac; echo "$f"; done | tr '\n' ' ')"
  [ -z "$sueltos" ] || alto "$p: código en $VIEJO que no está en GitHub: $sueltos"
  ok "$p: el código de $VIEJO es el de GitHub ${BASE[$p]:0:7} ($n archivos) · el clon está en $(g "$p" log -1 --format=%h)"
done
[ "$(md5 "$NUEVO/nfl_sim/sprint2.py")" = "$S2" ] || alto "sprint2.py del clon no es s2-v1"
ok "s2-v1 intacto ($S2)"

enl="$(find "$VIEJO/nfl_ev" "$VIEJO/nfl_sim" \( -path '*/venv' -o -path '*/.git' \) -prune -o -type l -print | head -n 5)"
[ -z "$enl" ] && ok "sin enlaces simbólicos en los datos" || echo "AVISO enlaces simbólicos (se copian tal cual; Claude revisa si apuntan a $VIEJO): $(echo "$enl" | sed "s#$VIEJO/##g" | tr '\n' ' ')"

# 3. copia (sin código, sin venv ni .git; dueño nflbot; nunca pisa). Antes: ningún enlace simbólico en el destino
#    (rsync como root los seguiría y escribiría fuera de /home/nflbot)
enl="$(find "$NUEVO/nfl_ev" "$NUEVO/nfl_sim" -path '*/venv' -prune -o -type l -print | head -n 3)"
[ -z "$enl" ] || alto "hay enlaces simbólicos en $NUEVO: $enl"
for p in nfl_ev nfl_sim; do
  ex=(--exclude=/venv --exclude=/.git --exclude=__pycache__/)
  for f in ${CODIGO[$p]}; do ex+=("--exclude=/$f"); done
  rsync -a --ignore-existing --chown="$USUARIO:$USUARIO" "${ex[@]}" "$VIEJO/$p/" "$NUEVO/$p/" || alto "rsync falló en $p"
  ok "$p copiado: $(du -sh --exclude=venv --exclude=.git "$NUEVO/$p" | cut -f1)"
done

# 4. verificación byte a byte de TODO lo copiado (nombres y cantidades, nunca contenido)
for p in nfl_ev nfl_sim; do
  malos=0; n=0; faltan=0
  while IFS= read -r -d '' f; do
    r="${f#$VIEJO/$p/}"
    case "${CODIGO[$p]}" in *" $r "*) continue ;; esac
    n=$((n + 1))
    if [ ! -f "$NUEVO/$p/$r" ]; then faltan=$((faltan + 1)); echo "     falta: $p/$r"
    elif ! cmp -s "$f" "$NUEVO/$p/$r"; then malos=$((malos + 1)); echo "     distinto: $p/$r"; fi
  done < <(find "$VIEJO/$p" \( -path "$VIEJO/$p/venv" -o -path "$VIEJO/$p/.git" -o -name __pycache__ \) -prune -o -type f -print0)
  [ "$malos" = 0 ] && [ "$faltan" = 0 ] || alto "$p: $faltan faltan y $malos distintos de $n"
  ok "$p: $n archivos de datos idénticos byte a byte"
  for f in ${QUITADOS[$p]}; do [ -e "$NUEVO/$p/$f" ] && alto "$p/$f volvió (el commit de migración lo quitó)"; done
done
for f in nfl_sim/salidas/semana/proyecciones_2026.csv nfl_sim/salidas/semana/estado.json nfl_sim/salidas/semana/retro_2026.csv \
         nfl_sim/salidas/parlays/parlays_2026.json nfl_ev/lineas_log.csv; do
  [ -f "$VIEJO/$f" ] && ok "md5 $(md5 "$NUEVO/$f" | cut -c1-12) = $(md5 "$VIEJO/$f" | cut -c1-12)  $f"
done

# 5. secretos: 600 y de nflbot sí o sí (config.ini, semana.ini y sus copias en respaldos/, credenciales/ en 700)
sec=0
while IFS= read -r -d '' f; do
  r="${f#$NUEVO/}"
  [ -L "$f" ] && alto "$r es un enlace simbólico"
  a="$(stat -c '%a %U' "$f")"
  if [ "$a" != "600 $USUARIO" ]; then
    como chmod 600 "$f" || alto "no pude dejar $r en 600"
    echo "AVISO $r estaba en ${a%% *}: quedó en 600"
  fi
  sec=$((sec + 1))
done < <(find "$NUEVO/nfl_ev/config.ini" "$NUEVO/nfl_sim/semana.ini" "$NUEVO/nfl_sim/credenciales" "$NUEVO/nfl_sim/respaldos" \
         -type f \( -path '*/credenciales/*' -o -name '*.ini' -o -name '*.key' -o -name '*.token' -o -name 'google_sa*.json' \) -print0 2>/dev/null)
[ "$(stat -c '%a' "$NUEVO/nfl_sim/credenciales")" = 700 ] || como chmod 700 "$NUEVO/nfl_sim/credenciales"
[ "$sec" -ge 6 ] || alto "solo encontré $sec secretos (esperaba al menos config.ini, semana.ini y las 4 llaves)"
ok "$sec secretos en 600 y de $USUARIO · credenciales/ en 700"
otros="$(find "$NUEVO/nfl_ev" "$NUEVO/nfl_sim" -path '*/venv' -prune -o ! -user "$USUARIO" -print | head -n 3)"
[ -z "$otros" ] && ok "todo es de $USUARIO" || alto "archivos que no son de $USUARIO: $otros"

# 6. rutas fijas a /home/ubuntu: en los .ini se cambian; en el resto solo se cuentan (los registros no se tocan)
for f in "$NUEVO/nfl_sim/semana.ini" "$NUEVO/nfl_ev/config.ini"; do
  [ -f "$f" ] || continue
  c="$(grep -c "$VIEJO/" "$f")"
  if [ "$c" -gt 0 ]; then
    como sed -i "s#$VIEJO/#$NUEVO/#g" "$f" && como chmod 600 "$f" || alto "no pude cambiar las rutas de ${f#$NUEVO/}"
    ok "${f#$NUEVO/}: $c ruta(s) a $VIEJO cambiadas a $NUEVO"
  else
    ok "${f#$NUEVO/}: sin rutas fijas a $VIEJO"
  fi
done
cuentas="$(grep -rIl --exclude='*.log' --exclude-dir=venv --exclude-dir=.git --exclude-dir=respaldos "$VIEJO/" "$NUEVO/nfl_ev" "$NUEVO/nfl_sim" 2>/dev/null | sed "s#$NUEVO/##" | head -n 8 | tr '\n' ' ')"
[ -z "$cuentas" ] && ok "ningún otro archivo de datos nombra $VIEJO" || echo "AVISO estos archivos nombran $VIEJO (no se tocan; Claude revisa si importa): $cuentas"
echo "== LISTO datos. Sigue con «EC2 nfl»:  bash ~/nfl_sim/instalar_servicios.sh arrancar"
