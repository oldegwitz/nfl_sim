#!/usr/bin/env bash
# cargar_token.sh — guarda el token del bot NUEVO del motor (el de las órdenes por Telegram). SIN sudo.
#   · Lo pide sin mostrarlo en pantalla y no queda en el historial de comandos.
#   · Revisa que tenga forma de token y que NO sea el del bot actual (nfl-ev-bot): dos programas no pueden leer el mismo bot.
#   · Lo guarda en ~/nfl_sim/credenciales/telegram_motor.token (600; credenciales/ es 700 y queda fuera de Git).
#   · Lo verifica con Telegram (getMe) y muestra solo el nombre del bot, nunca el token.
# Se puede correr otra vez para reemplazar el token.   Uso:  bash ~/nfl_sim/cargar_token.sh
set -uo pipefail
SIM="$HOME/nfl_sim"
F="$SIM/credenciales/telegram_motor.token"
[ -x "$SIM/venv/bin/python" ] || { echo "ALTO: no encuentro $SIM/venv"; exit 1; }
mkdir -p "$SIM/credenciales" && chmod 700 "$SIM/credenciales"
read -rs -p "Pega el token del bot NUEVO del motor (no se verá) y pulsa Enter: " T; echo
T="$(printf '%s' "$T" | tr -d '[:space:]')"
if ! [[ "$T" =~ ^[0-9]{6,}:[A-Za-z0-9_-]{30,}$ ]]; then
  echo "ALTO: eso no parece un token de Telegram (números, dos puntos y letras). No guardé nada."; unset T; exit 1
fi
VIEJO="$("$SIM/venv/bin/python" -c "import configparser,os;c=configparser.ConfigParser();c.read(os.path.expanduser('~/nfl_ev/config.ini'));print(c['telegram'].get('token','').strip() if c.has_section('telegram') else '')" 2>/dev/null)"
if [ -n "$VIEJO" ] && [ "$T" = "$VIEJO" ]; then
  echo "ALTO: ese es el token del bot actual (nfl-ev-bot). Crea un bot nuevo con @BotFather. No guardé nada."; unset T VIEJO; exit 1
fi
unset VIEJO
( umask 077; printf '%s\n' "$T" > "$F" ); chmod 600 "$F"; unset T
"$SIM/venv/bin/python" - <<'PY'
import pathlib, requests
t = (pathlib.Path.home() / "nfl_sim" / "credenciales" / "telegram_motor.token").read_text().strip()
try:
    r = requests.get(f"https://api.telegram.org/bot{t}/getMe", timeout=20).json()
    if r.get("ok"):
        print("OK    token guardado (600). Bot del motor: @" + r["result"]["username"])
    else:
        print("ALTO  token guardado, pero Telegram no lo reconoce: revisa que lo copiaste completo y vuelve a correr este script.")
except Exception as e:  # noqa: BLE001 — sin el texto: puede traer la URL con el token
    print("AVISO token guardado, pero no pude verificarlo con Telegram (" + type(e).__name__ + ").")
PY
echo "Siguiente: en Telegram abre el bot nuevo y envíale /start (una sola vez)."
