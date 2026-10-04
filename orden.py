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
  /piloto [variante] → piloto del agente Gemini con los criterios P1-P4 (semana.py gemini-piloto); variante opcional:
             g1 (por omisión), g1-low, g1-texto o g1-high. Tipo 'prueba': no cuenta para el piso de 35A.
  Parlays (v4, decisión 42; parlay.py, descriptivo, no cuenta para nada):
  foto del boleto → Gemini la lee y el bot repite lo que entendió; /si la guarda, /no la descarta
  /parlays → la lista · /parlay [N] → estado juego a juego (el último si no se dice N)
  /jugadas EQUIPO → últimas 10 jugadas de ese juego · /borrar_parlay N → lo saca de la lista
  /ayuda   → esta lista

Las corridas pedidas por Telegram se registran (tipo "telegram") y actualizan la hoja, pero NO son la proyección
que cuenta para 31A ni para el CLV de 29A: esa sigue siendo la automática (T−85; si no, sábado; si no, miércoles).

El token vive en credenciales/telegram_motor.token (600, fuera de Git). Nunca se imprime: los errores de red se
registran solo por su tipo, porque el texto de una excepción puede traer la URL con el token (también la de las fotos).
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

VERSION = "orden-v4 (4-oct-2026)"   # v2: /qb · v3: /piloto · v4: parlays (foto del boleto, /parlays, /parlay, /jugadas)
BASE = Path(__file__).resolve().parent
TOKEN = BASE / "credenciales" / "telegram_motor.token"
CONFIG_BOT = Path.home() / "nfl_ev" / "config.ini"
OFFSET = BASE / "salidas" / "semana" / "orden_offset.txt"
ENTRADA_FOTOS = BASE / "salidas" / "parlays" / "entrada"
PY = BASE / "venv" / "bin" / "python"
CARACAS = ZoneInfo("America/Caracas")
DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
LIMITE_S = 900                        # una corrida nunca debería pasar de ~2 min; tope de seguridad
LIMITE_PARLAY_S = 180                 # parlay.py: lectura de la foto (≤ 70 s) o consultas a ESPN
FOTO_MAX_BYTES = 15 * 1024 * 1024
ORDENES = {
    "/correr": (["correr", "--tipo", "telegram"], "Proyecto los juegos de la semana que no empezaron y actualizo la hoja (≈1 min)."),
    "/hoja": (["hoja"], "Rehago las pestañas desde el registro, sin simular (segundos)."),
    "/retro": (["retro"], "Rehago la retrospectiva de los juegos ya jugados (≈1 min)."),
    "/estado": (["estado"], None),
    "/qb": (["qb"], None),
    "/piloto": (["gemini-piloto"], "Piloto de Gemini: una consulta por juego pendiente, en paralelo (≈1-2 min). No cuenta para el piso."),
}
VARIANTES = ("g1", "g1-low", "g1-texto", "g1-high")
SALIDA_COMPLETA = ("/qb", "/estado", "/piloto")
# v4: órdenes de parlay.py → (argumentos, ¿lleva número?, ¿lleva equipo?)
ORDENES_PARLAY = {
    "/parlays": (["lista"], False, False),
    "/parlay": (["estado"], True, False),
    "/jugadas": (["jugadas"], False, True),
    "/si": (["si"], False, False),
    "/no": (["no"], False, False),
    "/borrar_parlay": (["borrar"], True, False),
}
AYUDA = ("Motor nfl_sim · órdenes:\n"
         "/correr — proyecta ahora y actualiza la hoja\n"
         "/hoja — rehace las pestañas (sin simular)\n"
         "/retro — rehace la retrospectiva\n"
         "/estado — qué toca y cuándo\n"
         "/qb — QB de cada juego por fuente y su confiabilidad\n"
         "/piloto — piloto del agente Gemini (P1-P4); /piloto g1-low para otra variante\n"
         "Parlays: mándame la foto del boleto de BetOnline; /si lo guarda, /no lo descarta\n"
         "/parlays — tus parlays · /parlay N — cómo va, juego a juego (sin N: el último)\n"
         "/jugadas BUF — últimas 10 jugadas de ese juego · /borrar_parlay N\n"
         "/ayuda — esta lista\n"
         "Las corridas pedidas aquí se registran pero no cuentan para 31A ni para el CLV. Los parlays son por diversión: el motor no apuesta.")


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
        self.url_archivos = f"https://api.telegram.org/file/bot{token}"

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

    def bajar_archivo(self, file_id, destino):
        """Baja una foto que mandó Ozz (getFile + descarga). Devuelve True/False; nunca registra la URL (lleva el token)."""
        r = self.llamar("getFile", file_id=file_id)
        ruta = ((r or {}).get("result") or {}).get("file_path") if r.get("ok") else None
        if not ruta:
            return False
        try:
            resp = self.r.get(f"{self.url_archivos}/{ruta}", timeout=60)
            if resp.status_code != 200 or not resp.content or len(resp.content) > FOTO_MAX_BYTES:
                log(f"foto: descarga rechazada (HTTP {resp.status_code}, {len(resp.content or b'')} bytes)")
                return False
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_bytes(resp.content)
            return True
        except Exception as e:  # noqa: BLE001
            log(f"foto: error de red al bajarla ({type(e).__name__})")
            return False


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
    return codigo, "\n".join(lineas if args and args[0] in ("qb", "estado", "gemini-piloto") else lineas[-15:])


def correr_parlay(args):
    """Corre parlay.py: su salida estándar es el mensaje para Ozz; los avisos técnicos (stderr) van al log."""
    try:
        p = subprocess.run([str(PY), "-u", str(BASE / "parlay.py"), *args], cwd=BASE, capture_output=True,
                           text=True, timeout=LIMITE_PARLAY_S)
    except subprocess.TimeoutExpired:
        return 1, f"Se pasó de {LIMITE_PARLAY_S // 60} min y la detuve. Prueba de nuevo en un rato."
    for x in (p.stderr or "").splitlines()[-20:]:
        if x.strip():
            log(f"parlay.py: {x[:300]}")
    texto = (p.stdout or "").strip()
    if p.returncode != 0 and not texto:
        texto = "parlay.py falló; el detalle quedó en salidas/semana/orden.log."
    return p.returncode, texto


def foto_del_mensaje(msg):
    """file_id de la foto más grande, o de un documento de imagen (foto enviada «como archivo»)."""
    fotos = msg.get("photo") or []
    if fotos:
        return max(fotos, key=lambda f: f.get("file_size") or (f.get("width", 0) * f.get("height", 0))).get("file_id")
    doc = msg.get("document") or {}
    if str(doc.get("mime_type", "")).startswith("image/"):
        return doc.get("file_id")
    return None


def atender_foto(tg, chat, msg):
    file_id = foto_del_mensaje(msg)
    if not file_id:
        return False
    log("orden: foto de boleto")
    tg.enviar(chat, "Leyendo el boleto (≈10-30 s)…")
    destino = ENTRADA_FOTOS / f"{dt.datetime.now(dt.timezone.utc):%Y%m%d_%H%M%S}_{msg.get('message_id', 0)}.img"
    if not tg.bajar_archivo(file_id, destino):
        tg.enviar(chat, "No pude bajar la foto de Telegram. Mándala otra vez.")
        return True
    codigo, texto = correr_parlay(["foto", str(destino)])
    try:
        destino.unlink()                               # parlay.py guarda su propia copia en salidas/parlays/fotos
    except OSError:
        pass
    tg.enviar(chat, texto)
    log(f"orden foto: {'listo' if codigo == 0 else 'falló'} ({codigo})")
    return True


def atender_parlay(tg, chat, texto, partes):
    args, con_numero, con_equipo = ORDENES_PARLAY[texto]
    resto = partes[1:2]
    if con_numero:
        if resto and resto[0].isdigit():
            args = args + [resto[0]]
        elif texto == "/borrar_parlay":
            tg.enviar(chat, "Dime cuál: /borrar_parlay 3")
            return
    if con_equipo:
        if not resto or not re.fullmatch(r"[A-Za-z]{2,3}", resto[0]):
            tg.enviar(chat, "Dime el equipo con su abreviatura: /jugadas BUF")
            return
        args = args + [resto[0].upper()]
    codigo, salida = correr_parlay(args)
    tg.enviar(chat, salida)
    log(f"orden {texto}: {'listo' if codigo == 0 else 'falló'} ({codigo})")


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
            try:
                if atender_foto(tg, chat, msg):
                    continue
            except Exception as e:  # noqa: BLE001 — una foto rara no tumba el servicio
                log(f"foto: error ({type(e).__name__})")
                tg.enviar(chat, "Algo falló con la foto. Mándala otra vez.")
                continue
            partes = (msg.get("text") or "").strip().split()
            texto = partes[0].split("@")[0].lower() if partes else ""
            extra = [x.lower() for x in partes[1:2]]
            if not texto:
                if msg.get("document") or msg.get("sticker") or msg.get("video"):
                    tg.enviar(chat, "Para un boleto, mándame la foto (imagen JPG o PNG). /ayuda muestra las órdenes.")
                continue
            log(f"orden: {texto}")
            if texto in ("/ayuda", "/start", "/help"):
                tg.enviar(chat, AYUDA)
            elif texto in ORDENES_PARLAY:
                atender_parlay(tg, chat, texto, partes)
            elif texto == "/piloto" and extra and extra[0] not in VARIANTES:
                tg.enviar(chat, f"Variante desconocida: {extra[0]}. Usa una de: {', '.join(VARIANTES)}.")
            elif texto in ORDENES:
                args, aviso = ORDENES[texto]
                if texto == "/piloto" and extra:
                    args = args + ["--variante", extra[0]]
                if aviso:
                    tg.enviar(chat, aviso)
                t0 = time.time()
                codigo, salida = correr_semana(args)
                estado = "listo" if codigo == 0 else "falló"
                tg.enviar(chat, salida if (texto in SALIDA_COMPLETA and codigo == 0) else f"{texto} {estado} en {time.time() - t0:.0f} s.\n{salida}")
                log(f"orden {texto}: {estado} ({codigo})")
            else:
                tg.enviar(chat, "No conozco esa orden.\n" + AYUDA)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
