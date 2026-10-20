#!/usr/bin/env bash
# cargar_anthropic.sh — guarda la llave de la API de Claude (decisión 65) sin mostrarla en pantalla.
# Uso: bash ~/nfl_sim/cargar_anthropic.sh
# La llave queda en ~/nfl_sim/credenciales/anthropic.key (600, fuera de Git). Se verifica pidiendo la lista de modelos
# a Anthropic (no gasta tokens). La llave nunca se imprime ni se escribe en un log. Se puede correr otra vez para cambiarla.
set -u
D="${NFL_SIM_DIR:-$HOME/nfl_sim}"
URL="${ANTHROPIC_PRUEBA_URL:-https://api.anthropic.com}"
cd "$D" || { echo "RESULTADO: NO CARGADA — no encuentro $D"; exit 1; }
umask 077
mkdir -p credenciales && chmod 700 credenciales
printf 'Pega la llave de Anthropic (no se va a ver nada al pegarla) y presiona Enter: '
IFS= read -rs LLAVE
echo
LLAVE=$(printf '%s' "$LLAVE" | sed 's/\x1b\[20[01]~//g' | tr -d '[:space:]')   # sin espacios ni marcas de pegado de Termius
case "$LLAVE" in
  sk-ant-*) ;;
  *) unset LLAVE; echo "RESULTADO: NO CARGADA — eso no parece una llave de Anthropic (empiezan con sk-ant-). No guardé nada."; exit 1 ;;
esac
printf '%s' "$LLAVE" > credenciales/anthropic.key.nueva
unset LLAVE
chmod 600 credenciales/anthropic.key.nueva
ANTHROPIC_PRUEBA_URL="$URL" venv/bin/python - <<'PY'
import os, sys
import requests
url = os.environ["ANTHROPIC_PRUEBA_URL"].rstrip("/") + "/v1/models"
llave = open("credenciales/anthropic.key.nueva", encoding="utf-8").read().strip()
try:
    r = requests.get(url, headers={"x-api-key": llave, "anthropic-version": "2023-06-01"}, params={"limit": 100}, timeout=(10, 30))
except Exception as e:  # noqa: BLE001 — solo el tipo, nunca la llave
    print(f"No pude conectar con Anthropic ({type(e).__name__}).")
    sys.exit(2)
if r.status_code != 200:
    try:
        err = (r.json() or {}).get("error") or {}
        msg = f"{err.get('type') or ''}: {err.get('message') or ''}".strip(": ")
    except Exception:  # noqa: BLE001
        msg = ""
    print(f"Anthropic respondió {r.status_code} {msg[:200]}".rstrip())
    sys.exit(1)
ids = [m.get("id", "") for m in (r.json() or {}).get("data", []) if isinstance(m, dict)]
def esta(x):
    return "disponible" if x in ids else "NO aparece en la lista"
print(f"OK: la llave funciona ({len(ids)} modelos visibles; claude-sonnet-5-5 {esta('claude-sonnet-5-5')}; "
      f"claude-opus-5-5 {esta('claude-opus-5-5')}; claude-haiku-5-5 {esta('claude-haiku-5-5')})")
PY
RC=$?
if [ $RC -ne 0 ]; then
  rm -f credenciales/anthropic.key.nueva
  echo "RESULTADO: NO CARGADA — no guardé nada. Revisa la llave en la Console y vuelve a correr el script."
  exit 1
fi
mv credenciales/anthropic.key.nueva credenciales/anthropic.key && chmod 600 credenciales/anthropic.key
if ! grep -q '^\[claude\]' semana.ini 2>/dev/null; then
  printf '\n[claude]\n# 65: tope diario de gasto de Claude en USD (además del tope mensual de la Console)\ntope_usd_dia = 2\n' >> semana.ini
fi
TOPE=$(awk -F= '/^\[claude\]/{c=1;next} /^\[/{c=0} c && $1 ~ /tope_usd_dia/ {gsub(/ /,"",$2); print $2}' semana.ini)
echo "RESULTADO: LLAVE CARGADA · credenciales/anthropic.key (permisos $(stat -c %a credenciales/anthropic.key)) · tope diario USD ${TOPE:-2} (semana.ini [claude])"
