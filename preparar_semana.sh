#!/usr/bin/env bash
# preparar_semana.sh — deja lista la corrida semanal del motor (31A) en ~/nfl_sim. SIN sudo.
#   1) verifica que sprint2.py sea el s2-v1 congelado y que estén semana.py y el instalador del programador;
#   2) instala google-auth en el venv de nfl_sim (solo ese venv; para escribir en la hoja);
#   3) crea credenciales/ (700), salidas/semana/ y semana.ini (600) con el id de la hoja;
#   4) registra el código nuevo en el Git local (credenciales y .ini quedan fuera por la lista blanca);
#   5) si ya está la credencial de Google, muestra el correo de la cuenta de servicio (nunca la llave).
# Se puede correr otra vez sin daño.   Uso:  bash ~/nfl_sim/preparar_semana.sh
set -uo pipefail
SIM="$HOME/nfl_sim"
MD5_S2="baad72c6a5dc0054a7de22a79c88616f"
HOJA_ID="1ymNMFm5CV3TI0wISRmkLjSq8AKsCnCl5IzGuyrJeu_8"
ok()   { echo "OK    $*"; }
alto() { echo; echo "ALTO: $*"; echo "No se cambió nada más. Pégale esta salida a Claude."; exit 1; }

echo "== 1. Revisión"
[ -x "$SIM/venv/bin/python" ] || alto "no encuentro $SIM/venv"
for f in sprint2.py semana.py instalar_programador.sh; do [ -f "$SIM/$f" ] || alto "falta $SIM/$f"; done
[ "$(md5sum "$SIM/sprint2.py" | cut -d' ' -f1)" = "$MD5_S2" ] || alto "sprint2.py no es el s2-v1 congelado (md5 distinto)"
ok "sprint2.py = s2-v1 congelado ($MD5_S2)"
ok "semana.py $(md5sum "$SIM/semana.py" | cut -d' ' -f1)"
ok "bot nfl-ev-bot: $(systemctl is-active nfl-ev-bot 2>/dev/null || echo desconocido)"

echo
echo "== 2. google-auth en el venv de nfl_sim"
if "$SIM/venv/bin/python" -c "import google.auth" 2>/dev/null; then
  ok "ya estaba: google-auth $("$SIM/venv/bin/python" -c 'import google.auth; print(google.auth.__version__)')"
else
  nice -n 10 "$SIM/venv/bin/pip" install -q --disable-pip-version-check "google-auth==2.59.1" || alto "falló pip install google-auth"
  ok "instalado google-auth $("$SIM/venv/bin/python" -c 'import google.auth; print(google.auth.__version__)')"
fi
grep -q '^google-auth==' "$SIM/requirements.txt" 2>/dev/null || echo "google-auth==2.59.1" >> "$SIM/requirements.txt"
"$SIM/venv/bin/pip" freeze --disable-pip-version-check | sort > "$SIM/requirements-lock.txt"
ok "requirements.txt y requirements-lock.txt al día"

echo
echo "== 3. Carpetas y configuración"
mkdir -p "$SIM/credenciales" "$SIM/salidas/semana"
chmod 700 "$SIM/credenciales"
if [ ! -f "$SIM/semana.ini" ]; then
  printf '%s\n' "[google]" "credenciales = credenciales/google_sa.json" "hoja_id = $HOJA_ID" > "$SIM/semana.ini"
fi
chmod 600 "$SIM/semana.ini"
ok "credenciales/ (700), salidas/semana/, semana.ini (600)"

echo
echo "== 4. Git local (solo código)"
cd "$SIM" || alto "no puedo entrar a $SIM"
git add semana.py preparar_semana.sh instalar_programador.sh requirements.txt requirements-lock.txt 2>/dev/null
if git diff --cached --name-only | grep -Eiq '\.(json|ini|pem|key|env|csv|parquet|log)$'; then
  git reset -q
  alto "Git iba a incluir un archivo que no debe entrar; no registré nada"
fi
if git diff --cached --quiet; then ok "Git: nada nuevo"; else git commit -q -m "Corrida semanal (31A): semana.py e instaladores" && ok "Git: $(git log --oneline -1)"; fi
git check-ignore -q semana.ini && ok "semana.ini fuera de Git: sí" || alto "semana.ini no quedó fuera de Git"

echo
echo "== 5. Cuenta de servicio de Google"
if [ -f "$SIM/credenciales/google_sa.json" ]; then
  chmod 600 "$SIM/credenciales/google_sa.json"
  CORREO=$("$SIM/venv/bin/python" -c "import json;print(json.load(open('$SIM/credenciales/google_sa.json'))['client_email'])" 2>/dev/null) || alto "credenciales/google_sa.json no es una llave JSON de cuenta de servicio"
  ok "credencial presente (600). Comparte la hoja con este correo, como Editor: $CORREO"
else
  echo "PENDIENTE  falta credenciales/google_sa.json (pasos en el chat). La corrida funciona igual sin hoja (Telegram + registro)."
fi
echo
echo "== LISTO"
