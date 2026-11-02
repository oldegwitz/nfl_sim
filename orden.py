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
  v4.4 (decisiones 63, 65 y 65.1; semana.py v9):
  /vigia [EQUIPO] → simula como /correr el próximo grupo de juegos (o el próximo juego de ese equipo) y consulta a los dos
             vigías: Gemini y Claude (semana.py vigia-manual). No cuenta; registros aparte. Tope 10 por día.
  /autopsia [N] → por qué perdieron los favoritos del cierre de la semana N (o la más reciente) (semana.py autopsia)
  /briefing → analista de los juegos que faltan de la semana (semana.py briefing). Tope 3 por día.
  Las tres no corren si en ≤ 12 min toca una corrida automática (la que cuenta).
  v4.5 (decisión 68; semana.py v9.3):
  /briefing [EQUIPO] → briefing nuevo: portada, 2 imágenes y el texto de cada partido, y la matriz (con EQUIPO, solo ese
             partido: /briefing KC). El tope de 3 por día cuenta solo si consulta a Opus.
  /matriz  → matriz de decisión con los precios de ahora (semana.py matriz; solo lee, segundos). Tampoco corre si en
             ≤ 12 min toca una automática.
  /presupuesto [N] → presupuesto semanal de la matriz en USD (D7); sin N muestra el vigente.
  Parlays (v4, decisión 42; parlay.py, descriptivo, no cuenta para nada):
  «Parlay» (v4.2, también «Teaser» o «Boleto») → el bot pregunta el nombre y el formato (botones PDF, Texto, Imagen) y
             espera ese formato: otro tipo de archivo se rechaza y sigue esperando; /cancelar sale. Se olvida a los 15 min.
  boleto como foto, PDF o texto directo (v4.1; texto pegado o escrito, solo o con /cargar) → igual, sin nombre (al guardarlo
             se llama «Parlay N»)
  Gemini lo lee y el bot repite lo que entendió (puede traer varios boletos: Nombre 1, Nombre 2…); /si guarda, /no descarta
  /parlay  → (v4.3, 42i) sin nada: empieza a cargar uno nuevo, igual que «Parlay»
  /parlays → los de esta semana NFL (v4.3, 42j: cada semana empieza otra vez en «Parlay 1»)
  /parlay N o NOMBRE (o S.N: semana S, número N) → estado juego a juego y por qué falló cada pata perdida
  /historico [SEMANA] → (v4.3) semanas anteriores por fecha; con semana, cada parlay con sus razones
  /jugadas EQUIPO → últimas 10 jugadas de ese juego · /borrar_parlay N o NOMBRE → lo saca de la lista
  /ayuda   → esta lista
  v4.3: menú de órdenes de Telegram (setMyCommands) y, cada 30 min (y 1 min después de /si o /borrar_parlay), lanza
  «parlay.py auto» como proceso aparte (uno a la vez, máximo 15 min): resultados, por qué falló y la hoja de parlays
  (42k). Su salida va a salidas/parlays/auto.log. No hace falta un temporizador nuevo de systemd.

Las corridas pedidas por Telegram se registran (tipo "telegram") y actualizan la hoja, pero NO son la proyección
que cuenta para 31A ni para el CLV de 29A: esa sigue siendo la automática (T−85; si no, sábado; si no, miércoles).

El token vive en credenciales/telegram_motor.token (600, fuera de Git). Nunca se imprime: los errores de red se
registran solo por su tipo, porque el texto de una excepción puede traer la URL con el token (también la de las fotos).
Lo arranca el servicio nfl-sim-orden (instalar_orden.sh).
"""
import configparser
import json
import re
import unicodedata
import datetime as dt
import subprocess
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

VERSION = "orden-v4.5 (2-nov-2026)"  # v4.5: /briefing EQUIPO, /matriz, /presupuesto (68) · v2: /qb · v3: /piloto · v4: parlays · v4.1: PDF y texto · v4.2: «Parlay» con nombre y formato · v4.3: /parlay solo, /historico, menú, auto · v4.4: /vigia, /autopsia, /briefing
BASE = Path(__file__).resolve().parent
TOKEN = BASE / "credenciales" / "telegram_motor.token"
CONFIG_BOT = Path.home() / "nfl_ev" / "config.ini"
OFFSET = BASE / "salidas" / "semana" / "orden_offset.txt"
ENTRADA_FOTOS = BASE / "salidas" / "parlays" / "entrada"
PY = BASE / "venv" / "bin" / "python"
CARACAS = ZoneInfo("America/Caracas")
DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
LIMITE_S = 900                        # una corrida nunca debería pasar de ~2 min; tope de seguridad
LIMITE_PARLAY_S = 180                 # parlay.py: lectura del boleto (≤ 100 s) o consultas a ESPN
FOTO_MAX_BYTES = 15 * 1024 * 1024
FLUJO_MAX_S = 15 * 60                 # v4.2: el paso «Parlay» se olvida si pasan 15 min sin terminarlo
NOMBRE_MAX = 30
DISPARADORES = ("parlay", "teaser", "boleto", "nuevo parlay", "nuevo boleto")
FORMATOS = {"pdf": "pdf", "texto": "texto", "imagen": "imagen", "foto": "imagen", "captura": "imagen", "image": "imagen",
            "text": "texto"}
TECLADO_FORMATO = json.dumps({"keyboard": [[{"text": "PDF"}, {"text": "Texto"}, {"text": "Imagen"}], [{"text": "Cancelar"}]],
                              "resize_keyboard": True, "one_time_keyboard": True})
SIN_TECLADO = json.dumps({"remove_keyboard": True})
PIDE = {"pdf": "Mándame el PDF como archivo (📎 → Archivo).", "imagen": "Mándame la foto o la captura del boleto.",
        "texto": "Pega o escribe el boleto en un solo mensaje (por ejemplo: Parlay $10: BUF -7 -110, CHI ML -175)."}
ORDENES = {
    "/correr": (["correr", "--tipo", "telegram"], "Proyecto los juegos de la semana que no empezaron y actualizo la hoja (≈1 min)."),
    "/hoja": (["hoja"], "Rehago las pestañas desde el registro, sin simular (segundos)."),
    "/retro": (["retro"], "Rehago la retrospectiva de los juegos ya jugados (≈1 min)."),
    "/estado": (["estado"], None),
    "/qb": (["qb"], None),
    "/piloto": (["gemini-piloto"], "Piloto de Gemini: una consulta por juego pendiente, en paralelo (≈1-2 min). No cuenta para el piso."),
    "/vigia": (["vigia-manual"], "Simulo y consulto a los dos vigías (Gemini y Claude), hasta ~9 min. A pedido: no cuenta."),
    "/autopsia": (["autopsia"], "Autopsia de los favoritos que perdieron (≈1-3 min)."),
    "/briefing": (["briefing"], "Briefing de los juegos que faltan: imágenes, texto y matriz (≈1-2 min; con Opus, hasta ~12 min)."),
    "/matriz": (["matriz"], "Matriz de decisión con los precios de ahora (segundos)."),
    "/presupuesto": (["presupuesto"], None),
}
VARIANTES = ("g1", "g1-low", "g1-texto", "g1-high")
SALIDA_COMPLETA = ("/qb", "/estado", "/piloto", "/presupuesto")
# v4: órdenes de parlay.py → (argumentos, ¿lleva número?, ¿lleva equipo?)
ORDENES_PARLAY = {
    "/parlays": (["lista"], False, False),
    "/parlay": (["estado"], True, False),          # v4.3: sin nada empieza la carga (main); con algo, el estado
    "/historico": (["historico"], True, False),    # v4.3
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
         "/vigia — simula el próximo grupo y consulta a los vigías (Gemini y Claude); /vigia KC para un equipo. No cuenta\n"
         "/autopsia — por qué perdieron los favoritos de la semana más reciente; /autopsia 7 para otra\n"
         "/briefing — briefing de los juegos que faltan: imágenes, texto y matriz; /briefing KC para un partido\n"
         "/matriz — matriz de decisión con los precios de ahora (ML, spread y puntos comprados contra Pinnacle)\n"
         "/presupuesto — presupuesto semanal de la matriz; /presupuesto 66 para cambiarlo\n"
         "Parlays (cada semana NFL empieza otra vez en «Parlay 1»):\n"
         "/parlay — cargar uno nuevo: te pregunto el nombre y el formato (PDF, texto o imagen); /cancelar sale.\n"
         "   También escribiendo «Parlay», o mandando el boleto directo como foto, PDF o texto. /si lo guarda, /no lo descarta\n"
         "/parlays — los de esta semana · /parlay 2 o /parlay Domingo — cómo va, juego a juego, y por qué falló cada pata perdida\n"
         "/historico — semanas anteriores · /historico 4 — esa semana con sus razones (y /parlay 4.2 para uno de ellos)\n"
         "/jugadas BUF — últimas 10 jugadas de ese juego · /borrar_parlay 2 (o el nombre)\n"
         "/ayuda — esta lista\n"
         "La hoja «NFL Secret LAB — Mis parlays 2026» se llena sola cada media hora.\n"
         "Las corridas pedidas aquí se registran pero no cuentan para 31A ni para el CLV. Los parlays son por diversión: el motor no apuesta.")
# v4.3: menú de Telegram (botón «Menú» y lista al escribir «/»)
COMANDOS = [("parlay", "Cargar un boleto nuevo (o /parlay 2 para ver cómo va)"), ("parlays", "Tus parlays de esta semana"),
            ("historico", "Semanas anteriores (o /historico 4)"), ("jugadas", "Últimas jugadas de un juego: /jugadas BUF"),
            ("si", "Guardar el boleto que leí"), ("no", "Descartar el boleto que leí"), ("cancelar", "Salir de la carga del boleto"),
            ("borrar_parlay", "Sacar un parlay de la lista"), ("estado", "Motor: qué toca y cuándo"), ("qb", "Motor: QB de cada juego"),
            ("correr", "Motor: proyectar ahora (no cuenta)"), ("hoja", "Motor: rehacer la hoja"), ("retro", "Motor: rehacer la retrospectiva"),
            ("piloto", "Motor: piloto del agente Gemini"), ("vigia", "Motor: vigías a pedido (o /vigia KC); no cuenta"),
            ("autopsia", "Por qué perdieron los favoritos (o /autopsia 7)"), ("briefing", "Briefing y matriz (o /briefing KC)"),
            ("matriz", "Matriz de decisión con los precios de ahora"), ("presupuesto", "Presupuesto semanal (o /presupuesto 66)"),
            ("ayuda", "Todas las órdenes")]
AUTO_CADA_S = 30 * 60                 # v4.3: parlay.py auto cada 30 min
AUTO_PRIMERA_S = 120                  # la primera, 2 min después de arrancar el servicio
AUTO_PRONTO_S = 60                    # después de /si o /borrar_parlay
AUTO_MAX_S = 15 * 60                  # si tarda más, se detiene
AUTO_LOG = BASE / "salidas" / "parlays" / "auto.log"
AUTO_LOG_MAX = 1024 * 1024


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

    def enviar(self, chat, texto, teclado=None):
        """teclado (v4.2): reply_markup en JSON (botones o quitarlos); va solo en el último pedazo."""
        trozos = [texto[i:i + 3900] for i in range(0, max(len(texto), 1), 3900)]   # Telegram admite ~4096 caracteres por mensaje
        for k, t in enumerate(trozos):
            extra = {"reply_markup": teclado} if teclado and k == len(trozos) - 1 else {}
            self.llamar("sendMessage", chat_id=chat, text=t, disable_web_page_preview="true", **extra)

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


class Auto:
    """v4.3: lanza «parlay.py auto» como proceso aparte cada AUTO_CADA_S (uno a la vez; si pasa de AUTO_MAX_S se detiene).
    No bloquea el bot: tick() solo mira si terminó o si toca lanzar otro. La salida va a AUTO_LOG (se rota a 1 MB)."""

    def __init__(self, ahora=time.time):
        self.reloj = ahora
        self.p = None
        self.t0 = 0.0
        self.prox = self.reloj() + AUTO_PRIMERA_S

    def pronto(self, s=AUTO_PRONTO_S):
        self.prox = min(self.prox, self.reloj() + s)

    def tick(self):
        if self.p is not None:
            if self.p.poll() is None:
                if self.reloj() - self.t0 > AUTO_MAX_S:
                    self.p.kill()
                    self.p.wait()
                    log(f"parlay auto: pasó de {AUTO_MAX_S // 60} min y lo detuve")
                    self.p = None
                return
            if self.p.returncode != 0:
                log(f"parlay auto terminó con código {self.p.returncode} (detalle en salidas/parlays/auto.log)")
            self.p = None
        if self.reloj() < self.prox:
            return
        self.prox = self.reloj() + AUTO_CADA_S
        try:
            AUTO_LOG.parent.mkdir(parents=True, exist_ok=True)
            if AUTO_LOG.exists() and AUTO_LOG.stat().st_size > AUTO_LOG_MAX:
                AUTO_LOG.replace(AUTO_LOG.with_suffix(".log.1"))
            with open(AUTO_LOG, "a", encoding="utf-8") as fh:
                self.p = subprocess.Popen([str(PY), "-u", str(BASE / "parlay.py"), "auto"], cwd=BASE, stdout=fh,
                                          stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
            self.t0 = self.reloj()
        except Exception as e:  # noqa: BLE001 — nunca tumba el bot
            log(f"parlay auto: no pude lanzarlo ({type(e).__name__})")
            self.p = None


def poner_menu(tg):
    r = tg.llamar("setMyCommands", commands=json.dumps([{"command": c, "description": d} for c, d in COMANDOS], ensure_ascii=False))
    log("menú de órdenes de Telegram: " + ("listo" if r.get("ok") else "no se pudo (sigue sin menú)"))


def archivo_del_mensaje(msg):
    """(file_id, tamaño) de la foto más grande, o de un documento de imagen o PDF; None si no hay."""
    fotos = msg.get("photo") or []
    if fotos:
        f = max(fotos, key=lambda f: f.get("file_size") or (f.get("width", 0) * f.get("height", 0)))
        return f.get("file_id"), f.get("file_size") or 0
    doc = msg.get("document") or {}
    mime, nombre = str(doc.get("mime_type", "")).lower(), str(doc.get("file_name", "")).lower()
    if mime.startswith("image/") or mime == "application/pdf" or nombre.endswith((".pdf", ".jpg", ".jpeg", ".png", ".webp")):
        return doc.get("file_id"), doc.get("file_size") or 0
    return None


PARECE_BOLETO = re.compile(r"(?<![\d.])[+-]\d{3,4}(?!\d)|[+-]\d{1,2}(?:\.5|½)|\bML\b|\bmoneyline\b|\b(?:over|under)\s*\d|"
                           r"\bparlay\b|\bteaser\b|\bpick\b", re.IGNORECASE)


def leer_boleto(tg, chat, ruta, que, extra=()):
    """Pasa la entrada guardada a parlay.py (leer) y responde. La copia de entrada se borra: parlay.py guarda la suya.
    extra (v4.2): --nombre y --formato del paso «Parlay». Devuelve el código de parlay.py (3 = formato distinto)."""
    tg.enviar(chat, f"Leyendo {que} (≈10-40 s)…", teclado=SIN_TECLADO if extra else None)
    codigo, texto = correr_parlay(["leer", str(ruta), *extra])
    try:
        ruta.unlink()
    except OSError:
        pass
    tg.enviar(chat, texto)
    log(f"orden boleto ({que}): {'listo' if codigo == 0 else 'formato distinto' if codigo == 3 else 'falló'} ({codigo})")
    return codigo


def atender_archivo(tg, chat, msg, extra=()):
    """True si el mensaje traía un archivo (y se atendió). Con extra (v4.2) devuelve el código de parlay.py."""
    hallado = archivo_del_mensaje(msg)
    if not hallado:
        return False
    file_id, tam = hallado
    es_pdf = str((msg.get("document") or {}).get("mime_type", "")).lower() == "application/pdf" or \
        str((msg.get("document") or {}).get("file_name", "")).lower().endswith(".pdf")
    que = "el PDF del boleto" if es_pdf else "el boleto"
    log(f"orden: boleto ({'pdf' if es_pdf else 'imagen'})")
    if tam and tam > FOTO_MAX_BYTES:
        tg.enviar(chat, "El archivo pesa demasiado (más de 15 MB). Mándame una captura o el PDF de una sola página.")
        return 3 if extra else True
    destino = ENTRADA_FOTOS / f"{dt.datetime.now(dt.timezone.utc):%Y%m%d_%H%M%S}_{msg.get('message_id', 0)}.entrada"
    if not tg.bajar_archivo(file_id, destino):
        tg.enviar(chat, "No pude bajar el archivo de Telegram. Mándalo otra vez.")
        return 3 if extra else True
    codigo = leer_boleto(tg, chat, destino, que, extra)
    return codigo if extra else True


def atender_texto_boleto(tg, chat, msg, texto, extra=()):
    texto = (texto or "").strip()
    if len(texto) < 3:
        tg.enviar(chat, "Escribe o pega el boleto después de /cargar, por ejemplo:\n/cargar Parlay $10: BUF -7 -110, CHI ML -175, Over 44.5 NYG/ARI -110")
        return
    destino = ENTRADA_FOTOS / f"{dt.datetime.now(dt.timezone.utc):%Y%m%d_%H%M%S}_{msg.get('message_id', 0)}.entrada"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(texto[:8000], encoding="utf-8")
    log("orden: boleto (texto)")
    return leer_boleto(tg, chat, destino, "el texto del boleto", extra)


# ---------------------------------------------------------------- v4.2: paso «Parlay» (nombre → formato → boleto)
FLUJO = {}          # en memoria: un reinicio del servicio lo olvida (igual que pasar 15 min)


def _norm(x):
    x = unicodedata.normalize("NFKD", x or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9/ ]", " ", x)).strip()


def flujo_vigente():
    if FLUJO and time.time() - FLUJO.get("t", 0) > FLUJO_MAX_S:
        log("orden: el paso «Parlay» venció (15 min sin terminarlo)")
        FLUJO.clear()
    return FLUJO


def empezar_flujo(tg, chat):
    FLUJO.clear()
    FLUJO.update(paso="nombre", t=time.time())
    tg.enviar(chat, f"¿Cómo lo llamo? (por ejemplo: Domingo o Teaser NFC; máximo {NOMBRE_MAX} letras). /cancelar para salir.",
              teclado=SIN_TECLADO)


def tipo_del_mensaje(msg):
    """'pdf', 'imagen', 'texto', 'otro' (archivo de otro tipo, sticker…) o '' (nada)."""
    if msg.get("photo"):
        return "imagen"
    doc = msg.get("document")
    if doc:
        mime, nombre = str(doc.get("mime_type", "")).lower(), str(doc.get("file_name", "")).lower()
        if mime == "application/pdf" or nombre.endswith(".pdf"):
            return "pdf"
        if mime.startswith("image/") or nombre.endswith((".jpg", ".jpeg", ".png", ".webp")):
            return "imagen"
        return "otro"
    if (msg.get("text") or "").strip():
        return "texto"
    return "otro" if msg else ""


def atender_flujo(tg, chat, msg):
    """True si el mensaje era parte del paso «Parlay»; False para que main lo atienda como siempre (otras órdenes)."""
    f = flujo_vigente()
    if not f:
        return False
    crudo = (msg.get("text") or "").strip()
    n = _norm(crudo)
    if n in ("cancelar", "/cancelar") or n.split(" ")[0].split("@")[0] == "/cancelar":
        FLUJO.clear()
        tg.enviar(chat, "Cancelado. No leí nada.", teclado=SIN_TECLADO)
        log("orden: paso «Parlay» cancelado")
        return True
    if crudo.startswith("/"):
        return False                   # otra orden: se atiende como siempre y el paso sigue esperando
    f["t"] = time.time()
    tipo = tipo_del_mensaje(msg)
    if f["paso"] == "nombre":
        nombre = re.sub(r"\s+", " ", crudo).strip()
        if tipo != "texto" or not nombre:
            tg.enviar(chat, "Primero dime cómo lo llamo (o /cancelar).")
        elif len(nombre) > NOMBRE_MAX:
            tg.enviar(chat, f"Ese nombre es largo: máximo {NOMBRE_MAX} letras. ¿Cómo lo llamo?")
        elif nombre.isdigit():
            tg.enviar(chat, "Usa letras, no solo números (los números ya identifican a cada parlay). ¿Cómo lo llamo?")
        else:
            f.update(paso="formato", nombre=nombre)
            tg.enviar(chat, f"«{nombre}». ¿En qué formato lo mandas?", teclado=TECLADO_FORMATO)
        return True
    if f["paso"] == "formato":
        formato = FORMATOS.get(n) if tipo == "texto" else None
        if not formato:
            tg.enviar(chat, "Elige con los botones: PDF, Texto o Imagen (o Cancelar).", teclado=TECLADO_FORMATO)
            return True
        f.update(paso="archivo", formato=formato)
        tg.enviar(chat, PIDE[formato] + " /cancelar para salir.", teclado=SIN_TECLADO)
        return True
    formato = f["formato"]
    if tipo != formato or (formato == "texto" and len(crudo) < 3):
        llego = {"pdf": "un PDF", "imagen": "una imagen", "texto": "un texto", "otro": "otro tipo de archivo"}.get(tipo, "algo que no es un boleto")
        tg.enviar(chat, f"Elegiste {'PDF' if formato == 'pdf' else formato} y me llegó {llego}. {PIDE[formato]} O /cancelar para salir.")
        log(f"orden: paso «Parlay» rechazó {tipo or 'nada'} (esperaba {formato})")
        return True
    extra = ["--nombre", f["nombre"], "--formato", formato]
    log(f"orden: paso «Parlay» con {formato}")
    codigo = atender_texto_boleto(tg, chat, msg, crudo, extra) if formato == "texto" else atender_archivo(tg, chat, msg, extra)
    if codigo != 3:                    # 3 = parlay.py vio otro tipo por el contenido o falló la descarga: sigue esperando
        FLUJO.clear()
    return True


def atender_parlay(tg, chat, texto, partes):
    args, con_numero, con_equipo = ORDENES_PARLAY[texto]
    resto = partes[1:2]
    if con_numero:                     # v4.2: número o nombre (puede tener espacios: «Domingo 1»)
        cual = " ".join(partes[1:])[:60].strip()
        if cual:
            args = args + [cual]
        elif texto == "/borrar_parlay":
            tg.enviar(chat, "Dime cuál: /borrar_parlay Domingo (o el número)")
            return None
    if con_equipo:
        if not resto or not re.fullmatch(r"[A-Za-z]{2,3}", resto[0]):
            tg.enviar(chat, "Dime el equipo con su abreviatura: /jugadas BUF")
            return None
        args = args + [resto[0].upper()]
    codigo, salida = correr_parlay(args)
    tg.enviar(chat, salida)
    log(f"orden {texto}: {'listo' if codigo == 0 else 'falló'} ({codigo})")
    return codigo


def preparar_orden(texto, extra):
    """v4.4: (argumentos de semana.py, aviso) de una orden del motor, o (None, mensaje de error) si el argumento no sirve."""
    args, aviso = ORDENES[texto]
    if texto == "/piloto" and extra:
        if extra[0] not in VARIANTES:
            return None, f"Variante desconocida: {extra[0]}. Usa una de: {', '.join(VARIANTES)}."
        return args + ["--variante", extra[0]], aviso
    if texto == "/vigia" and extra:
        if not re.fullmatch(r"[a-z]{2,3}", extra[0]):
            return None, "Dime el equipo con su abreviatura: /vigia KC (o /vigia solo para el próximo grupo de juegos)."
        return args + ["--equipo", extra[0].upper()], aviso
    if texto == "/briefing" and extra:                 # v4.5 (68)
        if not re.fullmatch(r"[a-z]{2,3}", extra[0]):
            return None, "Dime el equipo con su abreviatura: /briefing KC (o /briefing solo para todos los partidos)."
        return args + ["--equipo", extra[0].upper()], "Briefing de ese partido: imágenes y texto (≈1-6 min)."
    if texto == "/presupuesto" and extra:              # v4.5 (68)
        v = extra[0].replace(",", ".").lstrip("$")
        if not re.fullmatch(r"\d{1,4}(\.\d{1,2})?", v) or not 1 <= float(v) <= 5000:
            return None, "Dime el monto en USD por semana con un número: /presupuesto 66 (entre 1 y 5000)."
        return args + ["--valor", v], aviso
    if texto == "/autopsia" and extra:
        if not re.fullmatch(r"\d{1,2}", extra[0]) or not 1 <= int(extra[0]) <= 22:
            return None, "Dime la semana con un número: /autopsia 7 (o /autopsia sola para la más reciente)."
        return args + ["--semana", extra[0]], aviso
    return args, aviso


def main():
    tg = Telegram(leer_token())
    chat = leer_chat()
    yo = tg.llamar("getMe")
    if not yo.get("ok"):
        log("El token del bot del motor no responde (getMe). Revisa credenciales/telegram_motor.token.")
        time.sleep(60)
        raise SystemExit(1)
    log(f"{VERSION}: escuchando como @{yo['result'].get('username')} (solo el chat autorizado)")
    poner_menu(tg)
    auto = Auto()
    try:
        offset = int(OFFSET.read_text().strip())
    except Exception:  # noqa: BLE001
        offset = 0
    while True:
        auto.tick()
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
            n = _norm(msg.get("text") or "")
            if n in DISPARADORES:      # v4.2: «Parlay» empieza (o reinicia) el paso guiado
                log("orden: paso «Parlay»")
                empezar_flujo(tg, chat)
                continue
            try:
                if atender_flujo(tg, chat, msg):
                    continue
            except Exception as e:  # noqa: BLE001 — un paso raro no tumba el servicio
                log(f"paso «Parlay»: error ({type(e).__name__})")
                FLUJO.clear()
                tg.enviar(chat, "Algo falló en el paso «Parlay». Escribe Parlay para empezar de nuevo.", teclado=SIN_TECLADO)
                continue
            if n in ("cancelar", "/cancelar") or n.split(" ")[0].split("@")[0] == "/cancelar":
                tg.enviar(chat, "No había nada en curso.", teclado=SIN_TECLADO)
                continue
            if n in FORMATOS:
                tg.enviar(chat, "El paso «Parlay» venció (15 min) o no había empezado. Escribe Parlay para empezar.", teclado=SIN_TECLADO)
                continue
            try:
                if atender_archivo(tg, chat, msg):
                    continue
            except Exception as e:  # noqa: BLE001 — un archivo raro no tumba el servicio
                log(f"archivo: error ({type(e).__name__})")
                tg.enviar(chat, "Algo falló con el archivo. Mándalo otra vez.")
                continue
            crudo = (msg.get("text") or "").strip()
            partes = crudo.split()
            texto = partes[0].split("@")[0].lower() if partes else ""
            extra = [x.lower() for x in partes[1:2]]
            if not texto:
                if msg.get("document") or msg.get("sticker") or msg.get("video"):
                    tg.enviar(chat, "Para un boleto, mándamelo como foto (JPG o PNG), PDF o texto. /ayuda muestra las órdenes.")
                continue
            if texto == "/cargar":
                try:
                    atender_texto_boleto(tg, chat, msg, crudo[len(partes[0]):])
                except Exception as e:  # noqa: BLE001
                    log(f"texto: error ({type(e).__name__})")
                    tg.enviar(chat, "Algo falló con el texto. Mándalo otra vez.")
                continue
            if not texto.startswith("/") and PARECE_BOLETO.search(crudo):
                try:
                    atender_texto_boleto(tg, chat, msg, crudo)
                except Exception as e:  # noqa: BLE001
                    log(f"texto: error ({type(e).__name__})")
                    tg.enviar(chat, "Algo falló con el texto. Mándalo otra vez.")
                continue
            log(f"orden: {texto}")
            if texto in ("/ayuda", "/start", "/help"):
                tg.enviar(chat, AYUDA)
            elif texto == "/parlay" and len(partes) == 1:     # v4.3 (42i): /parlay solo empieza la carga
                log("orden: paso «Parlay» (/parlay)")
                empezar_flujo(tg, chat)
            elif texto in ORDENES_PARLAY:
                codigo = atender_parlay(tg, chat, texto, partes)
                if codigo == 0 and texto in ("/si", "/borrar_parlay"):
                    auto.pronto()                              # la hoja de parlays se actualiza en ~1 min
            elif texto in ORDENES:
                args, aviso = preparar_orden(texto, extra)
                if args is None:
                    tg.enviar(chat, aviso)
                    continue
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
