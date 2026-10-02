#!/usr/bin/env bash
# cargar_gemini.sh (v2) — activa el agente Gemini en SOMBRA (decisión 35A). SIN sudo.
#   · Pide la llave de la API de Gemini (Google AI Studio) sin mostrarla y sin dejarla en el historial.
#   · La guarda en ~/nfl_sim/credenciales/gemini.key (600; credenciales/ es 700 y queda fuera de Git).
#   · Agrega a semana.ini la sección [gemini] (modelo y tope de consultas por día) si no existe.
#   · La verifica con Google (lista de modelos) enviándola en un encabezado, nunca en la URL; muestra solo
#     si responde y si el modelo configurado está disponible.
# El agente corre solo en las corridas T−85, registra su respuesta y se mide; NO vota en el consenso.
# Para apagarlo: rm ~/nfl_sim/credenciales/gemini.key      Uso:  bash ~/nfl_sim/cargar_gemini.sh
set -uo pipefail
SIM="$HOME/nfl_sim"
F="$SIM/credenciales/gemini.key"
INI="$SIM/semana.ini"
[ -x "$SIM/venv/bin/python" ] || { echo "ALTO: no encuentro $SIM/venv"; exit 1; }
mkdir -p "$SIM/credenciales" && chmod 700 "$SIM/credenciales"
read -rs -p "Pega la llave de la API de Gemini (no se verá) y pulsa Enter: " K; echo
K="$(printf '%s' "$K" | tr -d '[:space:]' | tr -d "\"'")"
# v2: acepta también el formato nuevo de Google (p. ej. con punto: "AQ.…"); la prueba real es la verificación con Google
if [ -z "$K" ]; then
  echo "ALTO: no recibí nada. El pegado no llegó: en cmd usa clic derecho (o Ctrl+V) y luego Enter. No guardé nada."; exit 1
fi
if [ "${#K}" -lt 20 ] || [ "${#K}" -gt 200 ]; then
  echo "ALTO: recibí ${#K} caracteres; una llave tiene entre 20 y 200. Revisa que copiaste la llave completa. No guardé nada."; unset K; exit 1
fi
if ! [[ "$K" =~ ^[A-Za-z0-9._~+/=:-]+$ ]]; then
  echo "ALTO: lo que pegaste trae caracteres que no van en una llave (recibí ${#K} caracteres). Copia solo la llave. No guardé nada."; unset K; exit 1
fi
echo "OK    recibí una llave de ${#K} caracteres"
( umask 077; printf '%s\n' "$K" > "$F" ); chmod 600 "$F"; unset K
if [ -f "$INI" ] && ! grep -q '^\[gemini\]' "$INI"; then
  printf '\n[gemini]\nmodelo = gemini-3.5-flash-lite\nmax_llamadas_dia = 20\n' >> "$INI"
  echo "OK    semana.ini: agregada la sección [gemini] (modelo gemini-3.5-flash-lite, máximo 20 consultas por día)"
fi
"$SIM/venv/bin/python" - <<'PY'
import configparser, pathlib, requests
base = pathlib.Path.home() / "nfl_sim"
k = (base / "credenciales" / "gemini.key").read_text().strip()
cfg = configparser.ConfigParser(); cfg.read(base / "semana.ini")
modelo = cfg.get("gemini", "modelo", fallback="gemini-3.5-flash-lite").strip()
try:
    r = requests.get("https://generativelanguage.googleapis.com/v1beta/models", headers={"x-goog-api-key": k},
                     params={"pageSize": 200}, timeout=20)
    if r.status_code != 200:
        print(f"ALTO  llave guardada, pero Google respondió {r.status_code}: revisa que la copiaste completa y vuelve a correr este script.")
    else:
        nombres = [m.get("name", "").split("/")[-1] for m in r.json().get("models", [])]
        print(f"OK    llave guardada (600) y aceptada por Google ({len(nombres)} modelos visibles).")
        if modelo in nombres:
            print(f"OK    el modelo configurado ({modelo}) está disponible.")
        else:
            flash = [n for n in nombres if "flash" in n][:8]
            print(f"AVISO el modelo {modelo} no aparece en tu lista. Algunos disponibles: {', '.join(flash)}. "
                  "Cambia 'modelo' en ~/nfl_sim/semana.ini por uno de esos.")
except Exception as e:  # noqa: BLE001 — sin el texto del error
    print("AVISO llave guardada, pero no pude verificarla con Google (" + type(e).__name__ + ").")
PY
echo "Recuerda: en Google AI Studio / Cloud, pon un tope de gasto. El agente corre solo a T−85 y en sombra."
