#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
orden.py — Órdenes por Telegram para el motor nfl_sim (bot NUEVO, solo del motor; el bot nfl-ev-bot no se toca: 3B).

Escucha con long polling los mensajes del bot del motor y responde SOLO al chat de Ozz (el chat_id de
~/nfl_ev/config.ini, que se lee sin escribir). Una orden a la vez; semana.py tiene además su propio candado.

  /correr  → proyecta ahora los juegos de la semana que no empezaron y actualiza la hoja (semana.py correr --tipo telegram)
  /hoja    → rehace las pestañas desde el registro, sin simular (semana.py hoja)
  /retro   → rehace la retrospectiva de los juegos ya jugados (semana.py retro)
  /estado  → qué toca y cuándo (semana.py estado)
  /qb      → QB titular de cada juego por fuente (nflverse, ESPN, Sleeper), consenso y confiabilidad (semana.py qb)
  /ayuda   → esta lista

Las corridas pedidas por Telegram se registran (tipo "telegram") y actualizan la hoja, pero NO son la proyección
que cuenta para 31A ni para el CLV de 29A: esa sigue siendo la automática (T−85; si no, sábado; si no, miércoles).

El token vive en credenciales/telegram_motor.token (600, fuera de Git). Nunca se imprime: los errores de red se
registran solo por su tipo, porque el texto de una excepción puede traer la URL con el token.
Lo arranca el servicio nfl-sim-orden (instalar_orden.sh).
"""
import configparser
import re
import datetime as dt
import subprocess
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

VERSION = "orden-v2 (2-oct-2026)"   # v2: /qb muestra el consenso de fuentes (semana.py qb, decisión 32)
BASE = Path(__file__).resolve().parent
TOKEN = BASE / "credenciales" / "telegram_motor.token"
CONFIG_BOT = Path.home() / "nfl_ev" / "config.ini"
OFFSET = BASE / "salidas" / "semana" / "orden_offset.txt"
PY = BASE / "venv" / "bin" / "python"
CARACAS = ZoneInfo("America/Caracas")
DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
LIMITE_S = 900                        # una corrida nunca debería pasar de ~2 min; tope de seguridad
ORDENES = {
    "/correr": (["correr", "--tipo", "telegram"], "Proyecto los juegos de la semana que no empezaron y actualizo la hoja (≈1 min)."),
    "/hoja": (["hoja"], "Rehago las pestañas desde el registro, sin simular (segundos)."),
    "/retro": (["retro"], "Rehago la retrospectiva de los juegos ya jugados (≈1 min)."),
    "/estado": (["estado"], None),
    "/qb": (["qb"], None),
}
AYUDA = ("Motor nfl_sim · órdenes:\n"
         "/correr — proyecta ahora y actualiza la hoja\n"
         "/hoja — rehace las pestañas (sin simular)\n"
         "/retro — rehace la retrospectiva\n"
         "/estado — qué toca y cuándo\n"
         "/qb — QB de cada juego por fuente y su confiabilidad\n"
         "/ayuda — esta lista\n"
         "Las corridas pedidas aquí se registran pero no cuentan para 31A ni para el CLV.")


def log(msg):
    print(f"[{dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M:%S} UTC] {msg}", flush=True)


def leer_token():
    t = TOKEN.read_text(encoding="utf-8").strip()
    if ":" not in t:
        raise SystemExit("El archivo del token no tiene el formato de un token de Telegram")
    return t


def leer_chat():
    cfg = configparser.ConfigParser()
    cfg.read(CONFIG_BOT)
    return str(cfg["telegram"]["chat_id"]).strip()


class Telegram:
    def __init__(self, token):
        import requests
        self.r = requests.Session()
        self.url = f"https://api.telegram.org/bot{token}"

    def llamar(self, metodo, espera=30, **datos):
        """espera = tope de la conexión HTTP (no confundir con el 'timeout' de getUpdates, que va en datos)."""
        try:
            resp = self.r.post(f"{self.url}/{metodo}", data=datos, timeout=espera)
            return resp.json()
        except Exception as e:  # noqa: BLE001 — nunca se imprime el texto: puede traer la URL con el token
            log(f"Telegram {metodo}: error de red ({type(e).__name__})")
            return {"ok": False}

    def enviar(self, chat, texto):
        for i in range(0, max(len(texto), 1), 3900):          # Telegram admite ~4096 caracteres por mensaje
            self.llamar("sendMessage", chat_id=chat, text=texto[i:i + 3900], disable_web_page_preview="true")


def correr_semana(args):
    """Corre semana.py con esos argumentos y devuelve (código, últimas líneas útiles de su salida)."""
    try:
        p = subprocess.run([str(PY), "-u", str(BASE / "semana.py"), *args], cwd=BASE, capture_output=True,
                           text=True, timeout=LIMITE_S)
        salida = (p.stdout or "") + (p.stderr or "")
        codigo = p.returncode
    except subprocess.TimeoutExpired:
        return 1, f"Se pasó de {LIMITE_S // 60} min y la detuve."
    lineas = [re.sub(r"^\[[^\]]*UTC\] ", "", x) for x in salida.splitlines() if x.strip()]   # sin la hora del log
    if codigo != 0:
        lineas = [x for x in lineas if "Error" in x or "error" in x or "Traceback" in x or x.startswith("  ")][-8:] or lineas[-8:]
    return codigo, "\n".join(lineas if args and args[0] in ("qb", "estado") else lineas[-15:])


def main():
    tg = Telegram(leer_token())
    chat = leer_chat()
    yo = tg.llamar("getMe")
    if not yo.get("ok"):
        log("El token del bot del motor no responde (getMe). Revisa credenciales/telegram_motor.token.")
        time.sleep(60)
        raise SystemExit(1)
    log(f"{VERSION}: escuchando como @{yo['result'].get('username')} (solo el chat autorizado)")
    try:
        offset = int(OFFSET.read_text().strip())
    except Exception:  # noqa: BLE001
        offset = 0
    while True:
        r = tg.llamar("getUpdates", espera=70, offset=offset, timeout=50)
        if not r.get("ok"):
            time.sleep(10)
            continue
        for u in r.get("result", []):
            offset = u["update_id"] + 1
            OFFSET.parent.mkdir(parents=True, exist_ok=True)
            OFFSET.write_text(str(offset))
            msg = u.get("message") or {}
            if str((msg.get("chat") or {}).get("id")) != chat:
                if msg:
                    log(f"mensaje ignorado de un chat no autorizado ({(msg.get('chat') or {}).get('id')})")
                continue
            texto = (msg.get("text") or "").strip().split()[0].split("@")[0].lower() if msg.get("text") else ""
            if not texto:
                continue
            log(f"orden: {texto}")
            if texto in ("/ayuda", "/start", "/help"):
                tg.enviar(chat, AYUDA)
            elif texto in ORDENES:
                args, aviso = ORDENES[texto]
                if aviso:
                    tg.enviar(chat, aviso)
                t0 = time.time()
                codigo, salida = correr_semana(args)
                estado = "listo" if codigo == 0 else "falló"
                tg.enviar(chat, salida if (texto in ("/qb", "/estado") and codigo == 0) else f"{texto} {estado} en {time.time() - t0:.0f} s.\n{salida}")
                log(f"orden {texto}: {estado} ({codigo})")
            else:
                tg.enviar(chat, "No conozco esa orden.\n" + AYUDA)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
