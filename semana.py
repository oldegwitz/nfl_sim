#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
semana.py — Corrida semanal del motor nfl_sim s2-v1 en MODO REGISTRO (31A, 29A, 30A; sección 6b)

Qué hace en cada corrida
  1. Refresca de nflverse el calendario (QB titulares, líneas de consenso) y la jugada por jugada de 2026.
  2. Usa el modelo CONGELADO s2-v1: importa las funciones de sprint2.py (verifica su md5) y solo agrega datos
     (jugadas 2026 de las semanas ya jugadas). Ningún parámetro se toca (31A).
  3. Proyecta los juegos (10.000 simulaciones cada uno, todos en paralelo): spread, total y moneyline.
  4. Lee del bot (~/nfl_ev/lineas_log.csv, solo lectura) la última línea de Pinnacle (≤ 3 h) y de BetOnline (≤ 12 h).
  5. Filtro de alucinación (spread > 3,5 contra Pinnacle o, sin Pinnacle, contra nflverse; total > 5,0 contra el
     consenso de nflverse) y revisión de sesgo de la semana (1,0 spread / 1,5 total).
  6. Selecciones de 29A (moneyline ≥ 3 pp sobre Pinnacle sin vig; spread ≥ 53 % de cubrir la línea de Pinnacle)
     con su estado, y patas Wong de BetOnline para teaser de 6 pts (H26/H28: underdog +1,5 a +2,5, total < 50).
     SIN DINERO por el motor: las selecciones no están validadas (H29).
  7. Guarda todo en salidas/semana/proyecciones_2026.csv (nada se recalcula después), escribe la pestaña
     "Semana N" de la hoja de Google (una por semana, con colores) y manda un resumen por Telegram.
  8. Cuando nflverse publica un resultado, completa solo las columnas de cierre de esa semana (marcador, error
     del modelo contra el del cierre, si cubrió el lado del modelo, total real, pata Wong +6) y la fila resumen.
  La hoja es de solo lectura: Ozz no escribe nada (sin columnas manuales desde v4). El QB titular sale del consenso
  de nflverse, ESPN y Sleeper (v5); si no hay acuerdo, el juego va en rojo como "QB dudoso".

Cuándo corre (modo 'auto', lo llama el temporizador de systemd cada 5 min; si no toca nada, sale sin escribir)
  · miércoles y sábado 10:15 (Caracas): todos los juegos de la semana que no empezaron;
  · T−85 min de cada grupo de inicio (calculado del calendario: cubre el cambio de hora, sábados, playoffs);
  · cuando aparece un resultado nuevo en nflverse: reescribe la pestaña de esa semana (sin simular).
  Corre desde la semana 4 (la 4 es informativa); la confirmación 31A y el CLV de 29A cuentan desde la semana 5.

Retrospectiva (modo 'retro'): proyecta con s2-v1 los juegos de 2026 ya jugados que no tienen proyección previa
  (semanas 1-3 y el jueves de la 4) con lo que el modelo sabía antes de cada juego: jugadas de semanas anteriores y
  el QB que salió de titular. Se guarda APARTE (salidas/semana/retro_2026.csv) y se muestra en gris: no cuenta para
  31A ni para el CLV.

Uso
  venv/bin/python semana.py auto                          (lo usa el temporizador)
  venv/bin/python semana.py estado                        (qué toca y cuándo; no corre nada)
  venv/bin/python semana.py correr [--semana N] [--juegos ID,ID] [--tipo manual]
  venv/bin/python semana.py retro                         (retrospectiva de los juegos jugados y sus pestañas)
  venv/bin/python semana.py hoja [--semana N]             (rehace las pestañas desde el registro, sin simular)
  venv/bin/python semana.py qb                            (QB de cada juego por fuente y confiabilidad de cada fuente)
  venv/bin/python semana.py hoja-prueba                   (prueba la hoja: conexión, y crea y borra una pestaña de prueba)
Opciones de prueba: --ahora 2026-10-07T14:20:00Z · --sin-telegram · --sin-hoja · --bot-dir RUTA · --n-sims N

Solo lee ~/nfl_ev (líneas del bot y config.ini para Telegram); escribe solo en ~/nfl_sim y en la hoja.
"""
import argparse
import configparser
import csv
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

VERSION_SEMANA = "semana-v5 (2-oct-2026)"
# v3: la pestaña semanal no combina celdas a través del borde de las columnas inmovilizadas A-B (Sheets lo
#     rechazaba con 400 en la primera corrida real); el error de Sheets ahora trae el mensaje de Google;
#     'hoja-prueba' crea y borra una pestaña de prueba con el mismo formato que las semanales.
# v4 (pedido de Ozz, 2-oct): sin columnas manuales (QB y OK); columnas de cierre y fila resumen que se llenan
#     solas con los resultados de nflverse; modo 'retro' (semanas ya jugadas, en gris, aparte del registro);
#     modo 'hoja' (rehace las pestañas sin simular). La proyección hacia adelante es idéntica a v3.
# v5 (decisiones 32 y 35A, 2-oct): QB titular por consenso de nflverse, ESPN y Sleeper (disponibilidad según el
#     reporte oficial, Sleeper y el roster); sin acuerdo → "QB dudoso" (rojo, selecciones excluidas); registro de
#     cada voto y confiabilidad de cada fuente contra el QB que jugó; modo 'qb'; agente Gemini en sombra (solo con
#     credenciales/gemini.key; nunca vota). Con las tres fuentes de acuerdo con nflverse, la proyección es la de v4.
BASE = Path(__file__).resolve().parent
DATOS = BASE / "datos"
SAL = BASE / "salidas" / "semana"
REGISTRO = SAL / "proyecciones_2026.csv"
RETRO = SAL / "retro_2026.csv"                     # retrospectiva: no cuenta para 31A ni para el CLV
ESTADO = SAL / "estado.json"
MAX_EDAD_CAL_H = 1.0                                 # el calendario (resultados y QB) se refresca cada hora
CONFIG = BASE / "semana.ini"
MD5_SPRINT2 = "baad72c6a5dc0054a7de22a79c88616f"     # s2-v1 congelado (31A)
CARACAS = ZoneInfo("America/Caracas")
NUEVA_YORK = ZoneInfo("America/New_York")
TEMPORADA = 2026
SEMANA_AUTO = 4                    # corre desde la semana 4 (informativa)
SEMANA_31A = 5                     # 31A y 29A cuentan desde la semana 5
N_SIMS = 10_000
SEMILLA_PROD = 20261008
URL_GAMES = "https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv"
URL_PBP = "https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{}.parquet"
URL_ROSTER = "https://github.com/nflverse/nflverse-data/releases/download/rosters/roster_{}.csv"
MIN_T85 = 85                       # 30A: señal a T−85 (v4: sin reajustes manuales)
HORA_FIJA = (10, 15)               # miércoles y sábado 10:15 Caracas
MAX_EDAD_PIN_H = 3.0               # 29A/7B: línea de Pinnacle de ≤ 3 h
MAX_EDAD_BO_H = 12.0               # BetOnline para las patas Wong: la última foto de ≤ 12 h (se muestra su edad)
FILTRO_SPREAD, FILTRO_TOTAL = 3.5, 5.0
SESGO_SPREAD, SESGO_TOTAL = 1.0, 1.5
UMBRAL_ML, UMBRAL_SP = 0.03, 0.53  # 29A
WONG_LINEAS, WONG_TOTAL_MAX = (1.5, 2.0, 2.5), 50.0   # H26/H28
FILAS_MAX = 40                     # filas por pestaña semanal (encabezado en la 4, juegos desde la 5)

CAMPOS = ["corrida_utc", "tipo", "version", "game_id", "semana", "game_type", "inicio_utc", "local", "visita",
          "qb_local_id", "qb_visita_id", "qb_local_fuente", "qb_visita_fuente", "margen", "mediana", "total",
          "p_local", "p_empate", "de_margen", "localia", "ajuste_qb_local_pts", "ajuste_qb_visita_pts",
          "pin_ts", "pin_horas", "pin_hcp_local", "pin_cuota_sp_local", "pin_cuota_sp_visit", "pin_ml_local",
          "pin_ml_visit", "pin_p_ml_local", "pin_p_sp_local", "bo_ts", "bo_horas", "bo_hcp_local", "bo_ml_local",
          "bo_ml_visit", "nfl_spread_line", "nfl_total_line", "ref_spread", "spread_modelo", "spread_ref",
          "dif_spread", "dif_total", "marcado_spread", "marcado_total", "sesgo_spread_semana", "sesgo_total_semana",
          "bandera_sesgo", "p_cubre_local", "p_push", "sel_ml", "sel_ml_ventaja", "sel_sp", "sel_sp_prob",
          "sel_estado", "wong", "wong_linea"]


def log(msg):
    print(f"[{dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC] {msg}", flush=True)


def iso(t):
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def t_utc(txt):
    if not txt:
        return None
    try:
        return dt.datetime.fromisoformat(str(txt).replace("Z", "+00:00")).astimezone(dt.timezone.utc)
    except ValueError:
        return None


def md5(ruta):
    h = hashlib.md5()
    with open(ruta, "rb") as fh:
        for trozo in iter(lambda: fh.read(1 << 20), b""):
            h.update(trozo)
    return h.hexdigest()


DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def fecha_cc(t, con_dia_mes=True):
    c = t.astimezone(CARACAS)
    return f"{DIAS[c.weekday()]} {c.day:02d}-{MESES[c.month - 1]} {c:%H:%M}" if con_dia_mes else f"{DIAS[c.weekday()]} {c:%H:%M}"


# --------------------------------------------------------------------------------------
# Datos (refresco)
# --------------------------------------------------------------------------------------
def bajar(url, destino, minimo, max_edad_h):
    """Descarga si falta o si tiene más de max_edad_h horas. Si la descarga falla, sigue con la copia previa."""
    import requests
    if destino.exists() and destino.stat().st_size >= minimo and (time.time() - destino.stat().st_mtime) < max_edad_h * 3600:
        return True
    tmp = destino.with_suffix(destino.suffix + ".parcial")
    for intento in range(1, 4):
        try:
            with requests.get(url, stream=True, timeout=60) as r:
                r.raise_for_status()
                with open(tmp, "wb") as f:
                    for trozo in r.iter_content(1 << 20):
                        f.write(trozo)
            if tmp.stat().st_size < minimo:
                raise IOError(f"archivo incompleto ({tmp.stat().st_size} bytes)")
            tmp.replace(destino)
            return True
        except Exception as e:  # noqa: BLE001
            log(f"descarga de {destino.name}, intento {intento}: {type(e).__name__}")
            time.sleep(5 * intento)
    if destino.exists():
        log(f"AVISO: uso la copia anterior de {destino.name}")
        return True
    return False


def inicio_utc(gameday, gametime):
    """Fecha y hora de nflverse (hora del Este de EE. UU.) → UTC."""
    if not gameday or not gametime:
        return None
    h, m = (int(x) for x in str(gametime).split(":")[:2])
    y, mo, d = (int(x) for x in str(gameday).split("-"))
    return dt.datetime(y, mo, d, h, m, tzinfo=NUEVA_YORK).astimezone(dt.timezone.utc)


def calendario(max_edad_h=6.0):
    import polars as pl
    DATOS.mkdir(parents=True, exist_ok=True)
    if not bajar(URL_GAMES, DATOS / "games.csv", 500_000, max_edad_h):
        raise SystemExit("No hay calendario de nflverse")
    g = pl.read_csv(DATOS / "games.csv", infer_schema_length=20000)
    g26 = g.filter(pl.col("season") == TEMPORADA)
    ini = [inicio_utc(a, b) for a, b in zip(g26["gameday"].to_list(), g26["gametime"].to_list())]
    g26 = g26.with_columns(pl.Series("inicio", ini, dtype=pl.Datetime(time_zone="UTC")))
    return g, g26


# --------------------------------------------------------------------------------------
# Estado (qué corrió) y registro
# --------------------------------------------------------------------------------------
def leer_estado():
    try:
        e = json.loads(ESTADO.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        e = {}
    e.setdefault("fijas", {}); e.setdefault("grupos", {}); e.setdefault("resultados", [])
    e.pop("hash_ajustes", None)                      # v4: ya no hay ajustes manuales
    return e


def guardar_estado(e):
    SAL.mkdir(parents=True, exist_ok=True)
    tmp = ESTADO.with_suffix(".tmp")
    tmp.write_text(json.dumps(e, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(ESTADO)


def leer_registro(ruta=REGISTRO):
    import polars as pl
    if not ruta.exists():
        return pl.DataFrame({c: [] for c in CAMPOS}, schema={c: pl.Utf8 for c in CAMPOS})
    return pl.read_csv(ruta, infer_schema_length=0)              # todo como texto


def anexar_registro(filas):
    SAL.mkdir(parents=True, exist_ok=True)
    nuevo = not REGISTRO.exists()
    with open(REGISTRO, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CAMPOS)
        if nuevo:
            w.writeheader()
        for f in filas:
            w.writerow({k: ("" if f.get(k) is None else f.get(k)) for k in CAMPOS})


def guardar_retro(filas):
    """La retrospectiva se reescribe entera (es determinista: misma semilla y mismos datos → mismos números)."""
    SAL.mkdir(parents=True, exist_ok=True)
    tmp = RETRO.with_suffix(".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CAMPOS)
        w.writeheader()
        for f in filas:
            w.writerow({k: ("" if f.get(k) is None else f.get(k)) for k in CAMPOS})
    tmp.replace(RETRO)


# --------------------------------------------------------------------------------------
# Qué toca ahora
# --------------------------------------------------------------------------------------
def semana_actual(g26, ahora):
    import polars as pl
    pend = g26.filter(pl.col("result").is_null() & (pl.col("inicio") > ahora))
    return int(pend["week"].min()) if pend.height else None


def resultados_nuevos(g26, estado):
    """Juegos de 2026 con resultado en nflverse que todavía no se escribieron en la hoja: {semana: [game_id]}."""
    import polars as pl
    vistos = set(estado.get("resultados", []))
    hechos = g26.filter(pl.col("result").is_not_null() & ~pl.col("game_id").is_in(list(vistos)))
    out = {}
    for gid, sem in zip(hechos["game_id"].to_list(), hechos["week"].to_list()):
        out.setdefault(int(sem), []).append(gid)
    return out


def tareas(g26, ahora, estado):
    """Lista de (tipo, clave, [game_id]) que corresponde correr ahora."""
    import polars as pl
    out = []
    sem = semana_actual(g26, ahora)
    if sem is None or sem < SEMANA_AUTO:
        return out, sem
    loc = ahora.astimezone(CARACAS)
    pend_sem = g26.filter((pl.col("week") == sem) & (pl.col("inicio") > ahora))
    for dia, nombre in ((2, "miercoles"), (5, "sabado")):
        clave = f"{nombre}-{loc.date().isoformat()}"
        if loc.weekday() == dia and (loc.hour, loc.minute) >= HORA_FIJA and clave not in estado["fijas"] and pend_sem.height:
            out.append((nombre, clave, pend_sem["game_id"].to_list()))
    futuros = g26.filter((pl.col("week") >= SEMANA_AUTO) & (pl.col("inicio") > ahora) & pl.col("inicio").is_not_null())
    for (ini,), grupo in futuros.group_by(["inicio"], maintain_order=True):
        clave = iso(ini)
        if ahora >= ini - dt.timedelta(minutes=MIN_T85) and clave not in estado["grupos"]:
            out.append(("t85", clave, grupo["game_id"].to_list()))
    return out, sem


# --------------------------------------------------------------------------------------
# Hoja de Google (cuenta de servicio; REST de Sheets v4). Una pestaña "Semana N" por semana.
# --------------------------------------------------------------------------------------
class Hoja:
    def __init__(self, credenciales, hoja_id):
        from google.oauth2 import service_account
        from google.auth.transport.requests import AuthorizedSession
        cred = service_account.Credentials.from_service_account_file(
            str(credenciales), scopes=["https://www.googleapis.com/auth/spreadsheets"])
        self.s = AuthorizedSession(cred)
        self.url = f"https://sheets.googleapis.com/v4/spreadsheets/{hoja_id}"

    def _ok(self, r):
        if r.status_code >= 300:
            try:
                msg = str(r.json().get("error", {}).get("message", ""))
            except ValueError:
                msg = ""
            raise RuntimeError(f"Sheets respondió {r.status_code}" + (f": {msg[:240]}" if msg else ""))
        return r.json() if r.content else {}

    def pestanas(self):
        d = self._ok(self.s.get(self.url, params={"fields": "sheets.properties"}, timeout=30))
        return {p["properties"]["title"]: p["properties"]["sheetId"] for p in d.get("sheets", [])}

    def leer(self, rango):
        from urllib.parse import quote
        return self._ok(self.s.get(f"{self.url}/values/{quote(rango)}", timeout=30)).get("values", [])

    def escribir(self, rango, filas):
        from urllib.parse import quote
        return self._ok(self.s.put(f"{self.url}/values/{quote(rango)}", params={"valueInputOption": "RAW"},
                                   json={"values": filas}, timeout=30))

    def lote(self, pedidos):
        return self._ok(self.s.post(f"{self.url}:batchUpdate", json={"requests": pedidos}, timeout=60))


def abrir_hoja(args):
    if args.sin_hoja or not CONFIG.exists():
        return None
    cfg = configparser.ConfigParser()
    cfg.read(CONFIG)
    try:
        cred = (BASE / cfg["google"]["credenciales"]).resolve()
        hoja_id = cfg["google"]["hoja_id"].strip()
    except KeyError:
        return None
    if not cred.exists() or not hoja_id:
        return None
    try:
        return Hoja(cred, hoja_id)
    except Exception as e:  # noqa: BLE001
        log(f"Hoja: no pude abrir la cuenta de servicio ({type(e).__name__})")
        return None


def pestana(sem):
    return f"Semana {sem}"


# Columnas de la pestaña semanal (v4: todo lo escribe la EC2; la hoja es de solo lectura)
#   A-M proyección · N-R cierre (se llenan solas con el resultado) · S-U datos de control (gris chico)
ENCAB = ["Inicio (Caracas)", "Juego", "Línea mercado", "Línea modelo", "Modelo vs mercado", "Total consenso",
         "Total modelo", "Gana (modelo)", "Gana (Pinnacle)", "Señal ML", "Señal spread", "Pata Wong (BetOnline)",
         "Revisar / estado", "Resultado", "Error modelo / cierre", "Lado del modelo", "Total real", "Pata Wong +6",
         "QB usados", "Corrida", "game_id"]
NCOL = len(ENCAB)                                   # 21 (A-U)
COL_ID = "U"
COLORES = {"verde": "#D9EAD3", "azul": "#9FC5E8", "rojo": "#F4CCCC", "cierre": "#D0E0E3", "resumen": "#F3F3F3",
           "encab": "#1F3864", "gris": "#999999", "gris_texto": "#808080", "blanco": "#FFFFFF",
           "cubrio": "#B7E1CD", "no_cubrio": "#F4C7C3"}
LEYENDA = ["Colores", "",
           "Verde: candidata del modelo (sin validar, H29: el cierre le gana por 0,4 pts). Solo registro o monto mínimo.",
           "", "", "",
           "Azul: pata Wong para teaser de 6 pts (underdog +1,5 a +2,5, total < 50). Lo único con valor medido (H28).",
           "", "",
           "Rojo: el modelo y el mercado difieren mucho. En ese juego no se usa el modelo.",
           "", "", "",
           "Cierre (se llena solo al terminar el juego): verde = cubrió, rojo = no cubrió. Error = puntos de diferencia con el resultado.",
           "", "", "", "",
           "Gris en cursiva: proyección retro, hecha después del juego. No cuenta para 31A ni para el CLV."]


def _rgb(h):
    h = h.lstrip("#")
    return {"red": int(h[0:2], 16) / 255, "green": int(h[2:4], 16) / 255, "blue": int(h[4:6], 16) / 255}


def _rango(sid, f0, f1, c0, c1):
    return {"sheetId": sid, "startRowIndex": f0, "endRowIndex": f1, "startColumnIndex": c0, "endColumnIndex": c1}


TITULO_PRUEBA, SID_PRUEBA = "Prueba (se borra sola)", 1999     # pestaña temporal de 'hoja-prueba'


def crear_pestana(hoja, sem, titulo=None, sid=None):
    """Crea la pestaña 'Semana N' (primera a la izquierda) con encabezado, leyenda, fila resumen y formatos.
    Columnas A-B inmovilizadas (inicio y juego): ninguna celda combinada cruza ese borde, porque Sheets
    rechaza toda la tanda con 400 ("no puedes combinar columnas inmovilizadas con columnas móviles")."""
    sid = 1000 + sem if sid is None else sid
    t = titulo or pestana(sem)
    F = FILAS_MAX
    fondo = lambda r, color: {"repeatCell": {"range": r, "cell": {"userEnteredFormat": {"backgroundColorStyle": {"rgbColor": _rgb(color)}}},  # noqa: E731
                                             "fields": "userEnteredFormat.backgroundColorStyle"}}
    regla = lambda rangos, formula, fmt, idx: {"addConditionalFormatRule": {"index": idx, "rule": {  # noqa: E731
        "ranges": rangos, "booleanRule": {"condition": {"type": "CUSTOM_FORMULA", "values": [{"userEnteredValue": formula}]}, "format": fmt}}}}
    fmt_fondo = lambda color, negrita=False: {"backgroundColorStyle": {"rgbColor": _rgb(color)}, "textFormat": {"bold": negrita}}  # noqa: E731
    ancho = lambda c0, c1, px: {"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": c0, "endIndex": c1},  # noqa: E731
                                                              "properties": {"pixelSize": px}, "fields": "pixelSize"}}
    combinar = lambda c0, c1, f=0: {"mergeCells": {"range": _rango(sid, f, f + 1, c0, c1), "mergeType": "MERGE_ALL"}}  # noqa: E731
    pedidos = [
        {"addSheet": {"properties": {"sheetId": sid, "title": t, "index": 0,
                                     "gridProperties": {"rowCount": F, "columnCount": NCOL, "frozenRowCount": 4, "frozenColumnCount": 2}}}},
        # fila 1: A-B "Semana N · NFL 2026" | C-U detalle de la corrida
        combinar(0, 2, 0), combinar(2, NCOL, 0),
        # fila 2 (leyenda): A-B | C-F verde | G-I azul | J-M rojo | N-R cierre | S-U gris  (ninguna cruza el borde B|C)
        combinar(0, 2, 1), combinar(2, 6, 1), combinar(6, 9, 1), combinar(9, 13, 1), combinar(13, 18, 1), combinar(18, NCOL, 1),
        # fila 3 (resumen de la semana): A-B rótulo | C-U texto
        combinar(0, 2, 2), combinar(2, NCOL, 2),
        {"repeatCell": {"range": _rango(sid, 0, 1, 0, 2), "cell": {"userEnteredFormat": {"textFormat": {"bold": True, "fontSize": 13}}},
                        "fields": "userEnteredFormat.textFormat"}},
        {"repeatCell": {"range": _rango(sid, 0, 1, 2, NCOL), "cell": {"userEnteredFormat": {"textFormat": {
            "fontSize": 9, "foregroundColorStyle": {"rgbColor": _rgb(COLORES["gris"])}}, "verticalAlignment": "MIDDLE"}},
            "fields": "userEnteredFormat.textFormat,userEnteredFormat.verticalAlignment"}},
        {"repeatCell": {"range": _rango(sid, 1, 3, 0, 2), "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                        "fields": "userEnteredFormat.textFormat"}},
        fondo(_rango(sid, 1, 2, 2, 6), COLORES["verde"]), fondo(_rango(sid, 1, 2, 6, 9), COLORES["azul"]),
        fondo(_rango(sid, 1, 2, 9, 13), COLORES["rojo"]), fondo(_rango(sid, 1, 2, 13, 18), COLORES["cierre"]),
        fondo(_rango(sid, 1, 2, 18, NCOL), COLORES["resumen"]),
        {"repeatCell": {"range": _rango(sid, 1, 2, 18, NCOL), "cell": {"userEnteredFormat": {"textFormat": {
            "italic": True, "foregroundColorStyle": {"rgbColor": _rgb(COLORES["gris_texto"])}}}}, "fields": "userEnteredFormat.textFormat"}},
        {"repeatCell": {"range": _rango(sid, 1, 3, 0, NCOL), "cell": {"userEnteredFormat": {"wrapStrategy": "WRAP", "verticalAlignment": "MIDDLE"}},
                        "fields": "userEnteredFormat.wrapStrategy,userEnteredFormat.verticalAlignment"}},
        {"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "ROWS", "startIndex": 1, "endIndex": 2},
                                       "properties": {"pixelSize": 72}, "fields": "pixelSize"}},
        fondo(_rango(sid, 2, 3, 0, NCOL), COLORES["resumen"]),
        {"repeatCell": {"range": _rango(sid, 3, 4, 0, NCOL), "cell": {"userEnteredFormat": {
            "textFormat": {"bold": True, "foregroundColorStyle": {"rgbColor": _rgb(COLORES["blanco"])}},
            "backgroundColorStyle": {"rgbColor": _rgb(COLORES["encab"])}, "wrapStrategy": "WRAP", "verticalAlignment": "MIDDLE"}},
            "fields": "userEnteredFormat.textFormat,userEnteredFormat.backgroundColorStyle,userEnteredFormat.wrapStrategy,userEnteredFormat.verticalAlignment"}},
        {"repeatCell": {"range": _rango(sid, 4, F, 18, NCOL), "cell": {"userEnteredFormat": {"textFormat": {
            "fontSize": 8, "foregroundColorStyle": {"rgbColor": _rgb(COLORES["gris"])}}}}, "fields": "userEnteredFormat.textFormat"}},
        ancho(0, 1, 110), ancho(1, 2, 95), ancho(2, 3, 115), ancho(3, 4, 95), ancho(4, 5, 110), ancho(5, 7, 75),
        ancho(7, 9, 85), ancho(9, 11, 125), ancho(11, 12, 140), ancho(12, 13, 220), ancho(13, 14, 125), ancho(14, 15, 105),
        ancho(15, 16, 120), ancho(16, 17, 85), ancho(17, 18, 130), ancho(18, 19, 210), ancho(19, 20, 115), ancho(20, 21, 125),
        # colores de las filas (el orden importa: en cada celda manda la primera regla que se cumple)
        regla([_rango(sid, 4, F, 11, 12)], "=LEN($L5)>0", fmt_fondo(COLORES["azul"], True), 0),
        regla([_rango(sid, 4, F, 0, 13)], '=LEFT($T5,5)="retro"',
              {"textFormat": {"italic": True, "foregroundColorStyle": {"rgbColor": _rgb(COLORES["gris_texto"])}}}, 1),
        regla([_rango(sid, 4, F, 0, 13)], '=LEFT($M5,7)="REVISAR"', fmt_fondo(COLORES["rojo"]), 2),
        regla([_rango(sid, 4, F, 9, 11)], '=AND(LEN(J5)>0,LEFT($M5,9)="candidata")', fmt_fondo(COLORES["verde"], True), 3),
        regla([_rango(sid, 4, F, 15, 16)], '=LEFT($P5,6)="cubrió"', fmt_fondo(COLORES["cubrio"]), 4),
        regla([_rango(sid, 4, F, 15, 16)], '=LEFT($P5,2)="no"', fmt_fondo(COLORES["no_cubrio"]), 5),
        regla([_rango(sid, 4, F, 17, 18)], '=LEFT($R5,6)="cubrió"', fmt_fondo(COLORES["cubrio"]), 6),
        regla([_rango(sid, 4, F, 17, 18)], '=LEFT($R5,2)="no"', fmt_fondo(COLORES["no_cubrio"]), 7),
    ]
    hoja.lote(pedidos)
    hoja.escribir(f"'{t}'!A2", [LEYENDA])
    hoja.escribir(f"'{t}'!A4", [ENCAB])
    return sid


def asegurar_pestana(hoja, sem):
    """La pestaña de la semana con el diseño v4. Si existe con otro diseño (versión anterior), la borra y la rehace:
    todo lo que muestra sale del registro, de la retrospectiva y de nflverse (no hay nada escrito a mano)."""
    t = pestana(sem)
    ps = hoja.pestanas()
    if t in ps:
        enc = hoja.leer(f"'{t}'!A4:{COL_ID}4")
        if enc and list(enc[0]) == ENCAB:
            return False
        hoja.lote([{"deleteSheet": {"sheetId": ps[t]}}])
    crear_pestana(hoja, sem)
    return True


# --------------------------------------------------------------------------------------
# Textos cortos para la hoja ("libreta de muñeca")
# --------------------------------------------------------------------------------------
def _num(x):
    if x in (None, ""):
        return None
    try:
        return float(x)
    except ValueError:
        return None


def linea_txt(local, visita, hcp_local):
    """Hándicap del local → 'DAL -9.5' (el favorito con su línea) o 'PK'."""
    h = _num(hcp_local)
    if h is None:
        return ""
    if abs(h) < 0.05:
        return "PK"
    return f"{local} {h:.1f}" if h < 0 else f"{visita} {-h:.1f}"


def dif_txt(local, visita, spread_modelo, spread_ref):
    """A favor de quién está el modelo frente al mercado, en puntos: 'TB +8.5'."""
    a, b = _num(spread_modelo), _num(spread_ref)
    if a is None or b is None:
        return ""
    d = a - b
    if abs(d) < 0.05:
        return "igual"
    return f"{visita} +{d:.1f}" if d > 0 else f"{local} +{-d:.1f}"


def gana_txt(local, visita, p_local):
    p = _num(p_local)
    if p is None:
        return ""
    return f"{local} {100 * p:.0f} %" if p >= 0.5 else f"{visita} {100 * (1 - p):.0f} %"


def senal_ml_txt(f):
    if not f.get("sel_ml"):
        return ""
    eq = f["local"] if f["sel_ml"] == "local" else f["visita"]
    return f"{eq} ML (+{100 * float(f['sel_ml_ventaja']):.0f} pp)"


def senal_sp_txt(f):
    if not f.get("sel_sp"):
        return ""
    h = float(f["pin_hcp_local"])
    eq, lin = (f["local"], h) if f["sel_sp"] == "local" else (f["visita"], -h)
    return f"{eq} {lin:+.1f} ({100 * float(f['sel_sp_prob']):.0f} %)"


def wong_txt(f):
    if not f.get("wong"):
        return ""
    eq = f["local"] if f["wong"] == "local" else f["visita"]
    lin = float(f["wong_linea"])
    if f.get("tipo") == "retro":
        return f"{eq} +{lin:.1f} → +{lin + 6:.1f} (cierre)"
    edad = _num(f.get("bo_horas"))
    return f"{eq} +{lin:.1f} → +{lin + 6:.1f}" + (f" (hace {edad:.0f} h)" if edad is not None and edad >= 1 else "")


def _difieren(f):
    partes = []
    if f.get("marcado_spread") in (1, "1"):
        partes.append(f"spread {abs(float(f['dif_spread'])):.1f} pts")
    if f.get("marcado_total") in (1, "1"):
        partes.append(f"total {abs(float(f['dif_total'])):.1f} pts")
    return ", ".join(partes)


def estado_txt(f):
    d = _difieren(f)
    if f.get("tipo") == "retro":                       # nunca en rojo: la fila retro va en gris
        return "retro: hecha después del juego" + (f" · modelo y mercado difieren ({d})" if d else "")
    dq = [str(f.get(k))[len("dudoso: "):] for k in ("qb_visita_fuente", "qb_local_fuente")
          if str(f.get(k) or "").startswith("dudoso")]
    if dq:
        return "REVISAR: QB dudoso (" + " | ".join(dq) + ")" + (f" · modelo y mercado difieren ({d})" if d else "")
    if d:
        return "REVISAR: modelo y mercado difieren (" + d + ")"
    return f.get("sel_estado") or ""


# --------------------------------------------------------------------------------------
# Cierre de cada juego (se llena solo con el resultado de nflverse)
# --------------------------------------------------------------------------------------
def resultado_txt(g):
    """'PIT 24 - 27 CLE' (visitante primero, como en 'Juego')."""
    if g.get("result") is None or g.get("home_score") is None:
        return ""
    return f"{g['away_team']} {int(g['away_score'])} - {int(g['home_score'])} {g['home_team']}"


def cierre_de(g, u):
    """Métricas de cierre de un juego con resultado. g: fila de nflverse; u: proyección (registro o retro) o None.
    Referencia = cierre de nflverse (spread_line: margen esperado del local; total_line), como en 31A."""
    res, sp, tl, tot = _num(g.get("result")), _num(g.get("spread_line")), _num(g.get("total_line")), _num(g.get("total"))
    if res is None:
        return None
    c = dict(resultado=resultado_txt(g), err_m=None, err_c=None, lado=None, cubrio=None, gan_m=None, gan_c=None,
             dif_tot=None, tot_txt="", wong=None, wong_txt="")
    if tot is not None:
        c["tot_txt"] = f"{tot:.0f}" + ("" if tl is None else (" · over" if tot > tl else " · under" if tot < tl else " · push"))
    if sp is not None:
        c["err_c"] = abs(sp - res)
        if abs(sp) > 1e-9 and res != 0:
            c["gan_c"] = (sp > 0) == (res > 0)
    if u is None:
        return c
    m = _num(u.get("margen")); t = _num(u.get("total")); p = _num(u.get("p_local"))
    loc, vis = u.get("local"), u.get("visita")
    if m is not None:
        c["err_m"] = abs(m - res)
        if sp is not None:
            d = m - sp                                  # > 0: el modelo ve al local mejor que el mercado
            if abs(d) >= 1.0 and res != sp:
                lado = loc if d > 0 else vis
                c["lado"] = lado
                c["cubrio"] = (d > 0) == (res > sp)
    if p is not None and res != 0 and abs(p - 0.5) > 1e-9:
        c["gan_m"] = (p > 0.5) == (res > 0)
    if t is not None and tl is not None:
        c["dif_tot"] = t - tl
    if u.get("wong"):
        lin = _num(u.get("wong_linea"))
        if lin is not None:
            margen_lado = res if u["wong"] == "local" else -res
            x = margen_lado + lin + 6
            eq = loc if u["wong"] == "local" else vis
            c["wong"] = None if x == 0 else x > 0
            c["wong_txt"] = ("push" if x == 0 else "cubrió" if x > 0 else "no cubrió") + f" · {eq} +{lin + 6:.1f}"
    return c


def columnas_cierre(c):
    """[Resultado, Error modelo / cierre, Lado del modelo, Total real, Pata Wong +6] para la fila."""
    if c is None:
        return [""] * 5
    err = "" if c["err_m"] is None or c["err_c"] is None else f"{c['err_m']:.1f} / {c['err_c']:.1f}"
    if c["lado"] is None:
        lado = "—" if c["err_m"] is not None else ""
    else:
        lado = ("cubrió · " if c["cubrio"] else "no cubrió · ") + c["lado"]
    return [c["resultado"], err, lado, c["tot_txt"], c["wong_txt"]]


def resumen_txt(cierres, n_juegos):
    """Fila 3 de la pestaña: cómo le fue al modelo contra el cierre en los juegos ya jugados de la semana."""
    cc = [c for c in cierres if c is not None]
    if not cc:
        return f"Sin juegos cerrados todavía (0 de {n_juegos})."
    partes = [f"Cerrados {len(cc)} de {n_juegos}"]
    em = [c["err_m"] for c in cc if c["err_m"] is not None and c["err_c"] is not None]
    ec = [c["err_c"] for c in cc if c["err_m"] is not None and c["err_c"] is not None]
    if em:
        partes.append(f"error del margen: modelo {sum(em) / len(em):.2f}, cierre {sum(ec) / len(ec):.2f} pts")
    gm = [c["gan_m"] for c in cc if c["gan_m"] is not None]
    gc = [c["gan_c"] for c in cc if c["gan_c"] is not None]
    if gm or gc:
        partes.append(f"ganador acertado: modelo {sum(gm)} de {len(gm)}, cierre {sum(gc)} de {len(gc)}")
    ld = [c["cubrio"] for c in cc if c["lado"] is not None]
    if ld:
        partes.append(f"lado del modelo (si difiere ≥ 1 pt) cubrió {sum(ld)} de {len(ld)}")
    dt_ = [c["dif_tot"] for c in cc if c["dif_tot"] is not None]
    if dt_:
        partes.append(f"total del modelo vs cierre {sum(dt_) / len(dt_):+.1f}")
    w = [c["wong"] for c in cc if c["wong_txt"] and c["wong"] is not None]
    if w:
        partes.append(f"patas Wong +6: {sum(w)} de {len(w)}")
    return " · ".join(partes) + ". Error = puntos de diferencia con el resultado; la vara es el cierre de nflverse."


# --------------------------------------------------------------------------------------
# Probabilidades sin vig (método de potencia) y líneas del bot
# --------------------------------------------------------------------------------------
def decimal(americana):
    a = float(americana)
    return 1 + (a / 100 if a > 0 else 100 / -a)


def sin_vig_potencia(c1, c2):
    """Probabilidad justa del lado 1 con el método de potencia (la referencia del proyecto)."""
    try:
        p = [1 / decimal(c1), 1 / decimal(c2)]
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    lo, hi = 0.5, 3.0
    for _ in range(80):
        k = (lo + hi) / 2
        if p[0] ** k + p[1] ** k > 1:
            lo = k
        else:
            hi = k
    k = (lo + hi) / 2
    return p[0] ** k / (p[0] ** k + p[1] ** k)


def lineas_bot(bot_dir, casa, ids, ahora, max_horas):
    """Última foto de una casa del bot de ≤ max_horas para cada juego: {game_id: dict}."""
    import polars as pl
    ruta = Path(bot_dir) / "lineas_log.csv"
    if not ruta.exists():
        log(f"AVISO: no encuentro {ruta}; sin líneas del bot")
        return {}
    lg = pl.read_csv(ruta, infer_schema_length=0).filter((pl.col("fuente") == casa) & pl.col("game_id").is_in(ids))
    out = {}
    for gid, grupo in lg.group_by("game_id"):
        mejor = None
        for f in grupo.iter_rows(named=True):
            ts = t_utc(f["ts_utc"])
            if ts is None or ts > ahora or (ahora - ts).total_seconds() > max_horas * 3600:
                continue
            if mejor is None or ts > mejor[0]:
                mejor = (ts, f)
        if mejor:
            ts, f = mejor
            d = dict(ts=iso(ts), horas=round((ahora - ts).total_seconds() / 3600, 2))
            for k in ("hcp_local", "cuota_sp_local", "cuota_sp_visit", "ml_local", "ml_visit"):
                d[k] = _num(f.get(k))
            out[gid[0] if isinstance(gid, tuple) else gid] = d
    return out


# --------------------------------------------------------------------------------------
# QB titular por consenso de fuentes (decisión 32, registrada en el documento antes de usarse)
#   Votan 3 fuentes: nflverse (games.csv), ESPN (tabla de profundidad, consultada en la corrida) y Sleeper (una vez
#   al día como máximo, como pide su documentación). Cada fuente vota por su QB mejor ubicado que esté DISPONIBLE:
#   no está Out/Doubtful en el reporte oficial (nflverse), ni Out/IR/PUP/suspendido/Doubtful en Sleeper, ni en
#   reserva/cortado/práctica en el roster de nflverse. 2 o más votos iguales → ese QB; si no → "QB dudoso": se usa
#   el de nflverse para proyectar, pero el juego va en rojo y sus selecciones quedan excluidas.
#   Cada voto se guarda (salidas/semana/fuentes_qb.csv) y, con el QB que efectivamente jugó (nflverse después del
#   juego), se mide cuántas veces acertó cada fuente: el registro semana a semana de confiabilidad.
#   El agente Gemini (35A) vota en SOMBRA: se registra y se mide, pero no entra al consenso.
# --------------------------------------------------------------------------------------
URL_INJ = "https://github.com/nflverse/nflverse-data/releases/download/injuries/injuries_{}.csv"
URL_SLEEPER = "https://api.sleeper.app/v1/players/nfl"
URL_ESPN_EQUIPOS = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams"
URL_ESPN_PROF = "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/seasons/{}/teams/{}/depthcharts"
ESPN_ABREV = {"LA": "LAR", "WAS": "WSH"}                     # nflverse → ESPN (el resto coincide)
SLEEPER_ABREV = {"LA": "LAR"}                                 # nflverse → Sleeper
DE_OTRAS = {"LAR": "LA", "WSH": "WAS"}                        # respuestas con otras abreviaturas → nflverse
FUENTES_QB = SAL / "fuentes_qb.csv"
CAMPOS_QB = ["corrida_utc", "tipo", "game_id", "semana", "equipo", "fuente", "qb_id", "qb_nombre", "nota"]
FUENTES_VOTAN = ("nflverse", "espn", "sleeper")
NO_DISP_REPORTE = {"out", "doubtful"}
NO_DISP_SLEEPER = {"out", "ir", "pup", "sus", "suspended", "doubtful", "nfi", "cov", "dnr"}
NO_DISP_ROSTER = {"RES", "CUT", "DEV", "RET"}
TIPOS_QUE_CUENTAN = ("t85", "sabado", "miercoles")


def _texto(x):
    return "" if x is None else str(x).strip()


def _norm(nombre):
    """Nombre comparable: minúsculas, sin sufijos (Jr., III) ni signos."""
    n = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b\.?", "", _texto(nombre).lower())
    return re.sub(r"[^a-z]", "", n)


class FuentesQB:
    """Carga una vez por corrida las fuentes del QB titular. Si una fuente falla, se abstiene (nunca detiene la corrida)."""

    def __init__(self, sem):
        import polars as pl
        self.sem = sem
        self.avisos = []
        self.roster, self.por_espn, self.por_sleeper, self.nombre = {}, {}, {}, {}
        if bajar(URL_ROSTER.format(TEMPORADA), DATOS / f"roster_{TEMPORADA}.csv", 100_000, 12.0):
            try:
                r = pl.read_csv(DATOS / f"roster_{TEMPORADA}.csv", infer_schema_length=0).filter(pl.col("position") == "QB")
                for f in r.iter_rows(named=True):
                    gid = _texto(f.get("gsis_id"))
                    if not gid:
                        continue
                    self.roster[gid] = f
                    self.nombre[gid] = _texto(f.get("full_name"))
                    if _texto(f.get("espn_id")):
                        self.por_espn[_texto(f["espn_id"])] = gid
                    if _texto(f.get("sleeper_id")):
                        self.por_sleeper[_texto(f["sleeper_id"])] = gid
            except Exception as e:  # noqa: BLE001
                self.avisos.append(f"roster: {type(e).__name__}")
        self.reporte = {}                                    # gsis → estado del reporte oficial de la semana
        if bajar(URL_INJ.format(TEMPORADA), DATOS / f"injuries_{TEMPORADA}.csv", 1000, 6.0):
            try:
                inj = pl.read_csv(DATOS / f"injuries_{TEMPORADA}.csv", infer_schema_length=0)
                inj = inj.filter(pl.col("week") == str(sem))
                for f in inj.iter_rows(named=True):
                    self.reporte[_texto(f.get("gsis_id"))] = _texto(f.get("report_status")).lower()
            except Exception as e:  # noqa: BLE001
                self.avisos.append(f"reporte de lesiones: {type(e).__name__}")
        self.sleeper_eq, self.sleeper_iny = {}, {}           # equipo → [(orden, gsis)] · gsis → estado de lesión
        if bajar(URL_SLEEPER, DATOS / "sleeper_jugadores.json", 1_000_000, 24.0):
            try:
                d = json.loads((DATOS / "sleeper_jugadores.json").read_text(encoding="utf-8"))
                for pid, j in d.items():
                    if j.get("position") != "QB" or not j.get("team"):
                        continue
                    gid = self.por_sleeper.get(str(pid)) or _texto(j.get("gsis_id"))
                    if not gid:
                        continue
                    self.nombre.setdefault(gid, _texto(j.get("full_name")))
                    self.sleeper_iny[gid] = _texto(j.get("injury_status")).lower()
                    if j.get("depth_chart_order") is not None:
                        self.sleeper_eq.setdefault(j["team"], []).append((int(j["depth_chart_order"]), gid))
            except Exception as e:  # noqa: BLE001
                self.avisos.append(f"Sleeper: {type(e).__name__}")
        self.espn_ids = {}
        if bajar(URL_ESPN_EQUIPOS, DATOS / "espn_equipos.json", 5_000, 24 * 30):
            try:
                d = json.loads((DATOS / "espn_equipos.json").read_text(encoding="utf-8"))
                for t in d["sports"][0]["leagues"][0]["teams"]:
                    self.espn_ids[t["team"]["abbreviation"]] = t["team"]["id"]
            except Exception as e:  # noqa: BLE001
                self.avisos.append(f"ESPN equipos: {type(e).__name__}")
        self._espn_cache = {}

    def disponible(self, gid):
        if not gid:
            return False
        if self.reporte.get(gid, "") in NO_DISP_REPORTE:
            return False
        if self.sleeper_iny.get(gid, "") in NO_DISP_SLEEPER:
            return False
        st = _texto((self.roster.get(gid) or {}).get("status"))
        return st not in NO_DISP_ROSTER

    def candidatos_espn(self, equipo):
        """QB de la tabla de profundidad de ESPN en orden (gsis), consultada en el momento."""
        import requests
        if equipo in self._espn_cache:
            return self._espn_cache[equipo]
        out = []
        tid = self.espn_ids.get(ESPN_ABREV.get(equipo, equipo))
        if tid:
            try:
                d = requests.get(URL_ESPN_PROF.format(TEMPORADA, tid), timeout=20).json()
                for it in d.get("items", []):
                    qb = (it.get("positions") or {}).get("qb")
                    if not qb:
                        continue
                    for a in sorted(qb.get("athletes", []), key=lambda a: a.get("rank", 99)):
                        espn_id = str(a.get("athlete", {}).get("$ref", "")).split("/athletes/")[-1].split("?")[0]
                        gid = self.por_espn.get(espn_id)
                        if gid and gid not in out:
                            out.append(gid)
                    break
            except Exception as e:  # noqa: BLE001
                self.avisos.append(f"ESPN {equipo}: {type(e).__name__}")
        self._espn_cache[equipo] = out
        return out

    def candidatos_sleeper(self, equipo):
        return [g for _, g in sorted(self.sleeper_eq.get(SLEEPER_ABREV.get(equipo, equipo), []))]

    def votar(self, equipo, qb_nflverse):
        """{fuente: gsis o ''} y el resultado del consenso: (gsis_usado, estado, detalle)."""
        votos = {"nflverse": qb_nflverse if self.disponible(qb_nflverse) else ""}
        primero = {"nflverse": qb_nflverse or ""}
        for fuente, cands in (("espn", self.candidatos_espn(equipo)), ("sleeper", self.candidatos_sleeper(equipo))):
            votos[fuente] = next((g for g in cands if self.disponible(g)), "")
            primero[fuente] = cands[0] if cands else ""
        cuenta = {}
        for f in FUENTES_VOTAN:
            if votos[f]:
                cuenta[votos[f]] = cuenta.get(votos[f], 0) + 1
        validas = sum(1 for f in FUENTES_VOTAN if votos[f])
        top = max(cuenta.items(), key=lambda kv: kv[1]) if cuenta else (None, 0)
        nom = lambda g: self.nombre.get(g, g) or "—"  # noqa: E731

        def dijo(f):                                   # qué dijo cada fuente, en palabras
            if votos[f]:
                return nom(votos[f])
            return f"{nom(primero[f])} no disponible" if primero[f] else "sin dato"
        if top[1] >= 2:
            disiden = [f"{f}: {dijo(f)}" for f in FUENTES_VOTAN if votos[f] != top[0]]
            estado = f"{top[1]}/{validas}"
            return votos, top[0], estado, estado + ("" if not disiden else " · difiere " + ", ".join(disiden))
        detalle = " · ".join(f"{f} {dijo(f)}" for f in FUENTES_VOTAN)
        return votos, (qb_nflverse or votos["espn"] or votos["sleeper"]), "dudoso", "dudoso: " + detalle


def anexar_fuentes(filas):
    SAL.mkdir(parents=True, exist_ok=True)
    nuevo = not FUENTES_QB.exists()
    with open(FUENTES_QB, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CAMPOS_QB)
        if nuevo:
            w.writeheader()
        for f in filas:
            w.writerow({k: ("" if f.get(k) is None else f.get(k)) for k in CAMPOS_QB})


def confiabilidad_qb(g26, semana=None):
    """Aciertos de cada fuente contra el QB que jugó (nflverse después del juego), con el voto de la corrida que cuenta
    (la última antes del inicio entre T−85, sábado y miércoles; si no hubo, la última). {fuente: (aciertos, total)}."""
    import polars as pl
    if not FUENTES_QB.exists():
        return {}
    reg = pl.read_csv(FUENTES_QB, infer_schema_length=0)
    if semana is not None:
        reg = reg.filter(pl.col("semana") == str(semana))
    hechos = g26.filter(pl.col("result").is_not_null())
    real, inicio = {}, {}
    for r in hechos.iter_rows(named=True):
        real[(r["game_id"], r["home_team"])] = _texto(r.get("home_qb_id"))
        real[(r["game_id"], r["away_team"])] = _texto(r.get("away_qb_id"))
        inicio[r["game_id"]] = r["inicio"]
    elegido = {}                                       # (game, equipo, fuente) → (prioridad, corrida, qb)
    for f in reg.iter_rows(named=True):
        k = (f["game_id"], f["equipo"])
        if k not in real or not real[k]:
            continue
        t = t_utc(f["corrida_utc"])
        if t is None or (inicio.get(f["game_id"]) and t >= inicio[f["game_id"]]):
            continue
        prio = (1 if f["tipo"] in TIPOS_QUE_CUENTAN else 0, t)
        kk = (f["game_id"], f["equipo"], f["fuente"])
        if kk not in elegido or prio > elegido[kk][0]:
            elegido[kk] = (prio, _texto(f["qb_id"]))
    out = {}
    for (gid, eq, fuente), (_, qb) in elegido.items():
        a, n = out.get(fuente, (0, 0))
        out[fuente] = (a + int(qb == real[(gid, eq)]), n + 1)
    return out


def confiabilidad_txt(c):
    if not c:
        return ""
    orden = ["consenso", "nflverse", "espn", "sleeper", "gemini"]
    nombres = {"consenso": "consenso", "nflverse": "nflverse", "espn": "ESPN", "sleeper": "Sleeper", "gemini": "Gemini (sombra)"}
    return "QB acertado por fuente: " + " · ".join(f"{nombres[f]} {c[f][0]}/{c[f][1]}" for f in orden if f in c)


# --------------------------------------------------------------------------------------
# Agente Gemini en sombra (35A): solo corre si existe credenciales/gemini.key; nunca vota
# --------------------------------------------------------------------------------------
GEMINI_LLAVE = BASE / "credenciales" / "gemini.key"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta"
GEMINI_MODELO_DEF = "gemini-3.5-flash-lite"
GEMINI_MAX_DIA = 20
GEMINI_ESPERA_S = 90


def _gemini_cfg():
    cfg = configparser.ConfigParser()
    if CONFIG.exists():
        cfg.read(CONFIG)
    sec = cfg["gemini"] if cfg.has_section("gemini") else {}
    return (str(sec.get("modelo", GEMINI_MODELO_DEF)).strip() or GEMINI_MODELO_DEF,
            int(str(sec.get("max_llamadas_dia", GEMINI_MAX_DIA)).strip() or GEMINI_MAX_DIA))


def _textos_y_urls(obj, textos, urls):
    """Recorre la respuesta (cualquier versión de la API) y junta los textos y las URL citadas."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("text", "output_text") and isinstance(v, str):
                textos.append(v)
            elif k in ("uri", "url") and isinstance(v, str) and v.startswith("http"):
                urls.append(v)
            else:
                _textos_y_urls(v, textos, urls)
    elif isinstance(obj, list):
        for v in obj:
            _textos_y_urls(v, textos, urls)


def _json_en_texto(txt):
    """Primer arreglo JSON que aparezca en el texto (el modelo a veces lo envuelve en ```json)."""
    i = txt.find("[")
    while i != -1:
        for j in range(len(txt), i, -1):
            if txt[j - 1] == "]":
                try:
                    v = json.loads(txt[i:j])
                    if isinstance(v, list):
                        return v
                except ValueError:
                    continue
        i = txt.find("[", i + 1)
    return []


def gemini_qb(juegos, fuentes, ahora, estado):
    """Pregunta a Gemini (con búsqueda de Google) el QB titular de cada equipo de esos juegos.
    Devuelve {equipo: (gsis, nombre, url)}; {} si no hay llave, si se pasó el tope del día o si falla."""
    import requests
    if not GEMINI_LLAVE.exists():
        return {}
    modelo, tope = _gemini_cfg()
    hoy = ahora.astimezone(CARACAS).date().isoformat()
    usado = estado.setdefault("gemini", {})
    if usado.get(hoy, 0) >= tope:
        log(f"Gemini: tope de {tope} consultas del día alcanzado; no consulto")
        return {}
    usado[hoy] = usado.get(hoy, 0) + 1
    for k in [k for k in usado if k != hoy]:
        usado.pop(k)
    llave = GEMINI_LLAVE.read_text(encoding="utf-8").strip()
    lista = "; ".join(f"{v} at {l} ({fecha_cc(ini)} Caracas time)" for v, l, ini in juegos)
    pregunta = ("For each NFL team in these games, who will start at quarterback? Prefer the official inactive list, "
                "the team's announcement or reliable beat reporters from the last 48 hours. Games: " + lista +
                '. Answer ONLY a JSON array like [{"team": "SEA", "qb": "Full Name", "source": "https://..."}], one object per team, '
                "using these exact team abbreviations.")
    cab = {"x-goog-api-key": llave, "Content-Type": "application/json"}
    intentos = [(f"{GEMINI_URL}/interactions", {"model": modelo, "input": pregunta, "tools": [{"type": "google_search"}]}),
                (f"{GEMINI_URL}/models/{modelo}:generateContent",
                 {"contents": [{"parts": [{"text": pregunta}]}], "tools": [{"google_search": {}}]})]
    for url, cuerpo in intentos:
        try:
            r = requests.post(url, headers=cab, json=cuerpo, timeout=GEMINI_ESPERA_S)
        except Exception as e:  # noqa: BLE001 — sin el texto (no debe salir nada de la llave)
            log(f"Gemini: error de red ({type(e).__name__})")
            return {}
        if r.status_code in (400, 404) and "interactions" in url:
            continue                                   # esa versión de la API no está: prueba generateContent
        if r.status_code >= 300:
            log(f"Gemini: respondió {r.status_code}")
            return {}
        textos, urls = [], []
        _textos_y_urls(r.json(), textos, urls)
        lista_json = _json_en_texto("\n".join(textos))
        out = {}
        por_nombre = {_norm(n): g for g, n in fuentes.nombre.items() if n}
        for x in lista_json:
            if not isinstance(x, dict):
                continue
            eq, nom = _texto(x.get("team")).upper(), _texto(x.get("qb"))
            eq = DE_OTRAS.get(eq, eq)
            gid = por_nombre.get(_norm(nom), "")
            out[eq] = (gid, nom, _texto(x.get("source")) or (urls[0] if urls else ""))
        log(f"Gemini ({modelo}): {len(out)} equipos respondidos, {len(set(urls))} fuentes citadas")
        return out
    return {}


# --------------------------------------------------------------------------------------
# Corrida (hacia adelante y retrospectiva)
# --------------------------------------------------------------------------------------
def preparar_contexto(g_all, g26):
    """Carga el modelo CONGELADO s2-v1 (verifica el md5 de sprint2.py) y las calificaciones de equipos y QB.
    Solo agrega datos: jugadas 2026 de las semanas ya jugadas (31A). Ningún parámetro se toca."""
    import polars as pl
    if md5(BASE / "sprint2.py") != MD5_SPRINT2:
        raise SystemExit("sprint2.py no es el s2-v1 congelado (md5 distinto): no corro (31A)")
    sys.path.insert(0, str(BASE))
    import sprint2 as s2
    s2.TEMP_EQUIPOS = list(range(2019, TEMPORADA + 1))        # solo se agregan datos (31A)

    def _descargar(url, destino, minimo_bytes):
        """Reemplaza la descarga de sprint2.py (pide ≥ 5 MB por archivo y no refresca): la temporada en curso
        pesa menos al principio y se refresca cada 6 h; las cerradas no se vuelven a bajar. No toca el modelo."""
        en_curso = str(TEMPORADA) in destino.name
        if not bajar(url, destino, min(minimo_bytes, 500_000), 6.0 if en_curso else 1e9):
            raise SystemExit(f"No se pudo descargar {destino.name}")
    s2.descargar = _descargar
    _descargar(URL_PBP.format(TEMPORADA), DATOS / f"pbp_{TEMPORADA}.parquet", 500_000)
    bajar(URL_ROSTER.format(TEMPORADA), DATOS / f"roster_{TEMPORADA}.csv", 100_000, 24.0)
    roster = None
    try:
        roster = pl.read_csv(DATOS / f"roster_{TEMPORADA}.csv", infer_schema_length=0).filter(pl.col("position") == "QB")
    except Exception:  # noqa: BLE001
        log("AVISO: sin roster 2026 (solo afecta los nombres de QB que muestra la hoja)")
    t0 = time.time()
    games, pbp = s2.preparar_datos()
    M = s2.construir_modelo(pbp, games)
    pp = pbp.filter(pl.col("play_type").is_in(["pass", "run"]) & pl.col("down").is_not_null()
                    & pl.col("epa").is_not_null() & pl.col("posteam").is_not_null())
    mu_pool = (float(pp.filter(pl.col("play_type") == "pass")["epa"].mean()), float(pp.filter(pl.col("play_type") == "run")["epa"].mean()))
    del pbp, pp
    EQ = s2.preparar_equipos(s2.cargar_equipos(g_all))
    log(f"modelo s2-v1 listo en {time.time() - t0:.0f} s · {len(EQ['qidx'])} QB · pico {s2.pico_mb():.0f} MB")
    return dict(s2=s2, M=M, EQ=EQ, mu_pool=mu_pool, hfa=s2.localia(g_all, TEMPORADA), nombres_qb=nombres_de_qb(g26, roster))


def nombres_de_qb(g26, roster=None):
    nombres = {}
    for a, b in zip(g26["home_qb_id"].fill_null("").to_list() + g26["away_qb_id"].fill_null("").to_list(),
                    g26["home_qb_name"].fill_null("").to_list() + g26["away_qb_name"].fill_null("").to_list()):
        if a:
            nombres[a] = b
    if roster is not None:
        for a, b in zip(roster["gsis_id"].to_list(), roster["full_name"].to_list()):
            nombres.setdefault(a, b)
    return nombres


def juegos_con_qb(ctx, g26, filtro):
    """Juegos a simular, con nombres de equipo normalizados y el QB titular de nflverse (v4: sin ajustes manuales).
    En juegos ya jugados, nflverse trae el QB que efectivamente salió de titular."""
    import polars as pl
    s2 = ctx["s2"]
    return (g26.filter(filtro)
            .with_columns(pl.col("home_team").replace(s2.EQUIV), pl.col("away_team").replace(s2.EQUIV))
            .sort(["week", "inicio", "game_id"])
            .with_columns(pl.col("home_qb_id").fill_null("").alias("qbl"), pl.col("away_qb_id").fill_null("").alias("qbv"),
                          pl.lit("nflverse").alias("fl"), pl.lit("nflverse").alias("fv")))


def simular_semana(ctx, gs, sem, n_sims):
    """Las n_sims simulaciones de todos los juegos de una semana, en paralelo (misma semilla que v2 y v3)."""
    import numpy as np
    s2, EQ = ctx["s2"], ctx["EQ"]
    R = s2.calificar(EQ, TEMPORADA * s2.W_TEMP + sem, TEMPORADA)
    F = s2.fuerza_partidos(EQ, R, gs["home_team"].to_list(), gs["away_team"].to_list(), gs["qbl"].to_list(),
                           gs["qbv"].to_list(), (gs["location"] == "Neutral").to_numpy(), ctx["hfa"], ctx["mu_pool"])
    ng = gs.height
    rep = np.repeat(np.arange(ng), n_sims)
    po = np.repeat((gs["game_type"] != "REG").to_numpy(), n_sims)
    r = s2.simular(ctx["M"], ng * n_sims, po, np.random.default_rng(SEMILLA_PROD + TEMPORADA * 100 + sem),
                   fuerza=dict(dp=F["dp"][rep], dr=F["dr"][rep]))
    return r["margen"].reshape(ng, n_sims), r["total"].reshape(ng, n_sims), F


def fila_base(ctx, gs, i, m, t_i, F, sem, tipo, ahora):
    """Campos del registro que salen de la simulación (iguales para la corrida hacia adelante y la retro)."""
    import numpy as np
    s2 = ctx["s2"]
    pw, pt_, pe = float((m > 0).mean()), float((m < 0).mean()), float((m == 0).mean())
    f = dict(corrida_utc=iso(ahora), tipo=tipo, version="s2-v1", game_id=gs["game_id"][i], semana=sem,
             game_type=gs["game_type"][i], inicio_utc=iso(gs["inicio"][i]), local=gs["home_team"][i],
             visita=gs["away_team"][i], qb_local_id=gs["qbl"][i], qb_visita_id=gs["qbv"][i],
             qb_local_fuente=gs["fl"][i], qb_visita_fuente=gs["fv"][i], margen=round(float(m.mean()), 3),
             mediana=float(np.median(m)), total=round(float(t_i.mean()), 3),
             p_local=round(pw / max(pw + pt_, 1e-9), 4), p_empate=round(pe, 4), de_margen=round(float(m.std()), 3),
             localia=round(ctx["hfa"], 3), ajuste_qb_local_pts=round(float(F["adj"][i, 0]) * s2.RESP["a_p"], 2),
             ajuste_qb_visita_pts=round(float(F["adj"][i, 1]) * s2.RESP["a_p"], 2))
    f["nfl_spread_line"] = gs["spread_line"][i]; f["nfl_total_line"] = gs["total_line"][i]
    f["spread_modelo"] = round(-f["margen"], 2)                       # convención de la casa: local −3,5 = favorito
    return f


def marcar(f):
    """Filtro de alucinación: spread contra la referencia (Pinnacle o nflverse) y total contra nflverse."""
    ntl = f.get("nfl_total_line")
    if f.get("spread_ref") is not None:
        f["dif_spread"] = round(f["spread_modelo"] - f["spread_ref"], 2)
        f["marcado_spread"] = int(abs(f["dif_spread"]) > FILTRO_SPREAD)
    if ntl is not None:
        f["dif_total"] = round(f["total"] - float(ntl), 2)
        f["marcado_total"] = int(abs(f["dif_total"]) > FILTRO_TOTAL)


def pata_wong(f, hcp_local):
    """H26/H28: underdog a +1,5/+2/+2,5 y total de nflverse < 50 (no depende del modelo)."""
    ntl = f.get("nfl_total_line")
    if hcp_local is None or ntl is None or float(ntl) >= WONG_TOTAL_MAX:
        return
    hb = float(hcp_local)
    lado, lin = ("local", hb) if hb > 0 else ("visita", -hb)
    if any(abs(lin - w) < 1e-6 for w in WONG_LINEAS):
        f["wong"] = lado; f["wong_linea"] = lin


def sesgo_semanal(filas, previas):
    """Revisión de sesgo: media con signo de (modelo − línea) sobre la última proyección de cada juego de la semana."""
    import numpy as np
    for sem in sorted({f["semana"] for f in filas}):
        ult = {}
        for rr in previas:
            if str(rr.get("semana")) == str(sem):
                ult[rr["game_id"]] = (rr.get("dif_spread"), rr.get("dif_total"))
        for f in filas:
            if f["semana"] == sem:
                ult[f["game_id"]] = (f.get("dif_spread"), f.get("dif_total"))
        ds = [float(a) for a, _ in ult.values() if a not in (None, "")]
        dtt = [float(b) for _, b in ult.values() if b not in (None, "")]
        ss = round(float(np.mean(ds)), 2) if ds else None
        st = round(float(np.mean(dtt)), 2) if dtt else None
        bandera = int((ss is not None and abs(ss) > SESGO_SPREAD) or (st is not None and abs(st) > SESGO_TOTAL))
        for f in filas:
            if f["semana"] == sem:
                f["sesgo_spread_semana"] = ss; f["sesgo_total_semana"] = st; f["bandera_sesgo"] = bandera


def consenso_semana(gs, sem, tipo, ahora, estado):
    """QB por consenso para los juegos de una semana (v5). Reemplaza qbl/qbv por el QB elegido, deja el estado del
    consenso en fl/fv y registra cada voto (y el del agente en sombra en las corridas T−85)."""
    import polars as pl
    fq = FuentesQB(sem)
    for a in fq.avisos:
        log(f"AVISO fuentes del QB: {a}")
    qbl, qbv, fl, fv, votos_log = [], [], [], [], []
    for r in gs.iter_rows(named=True):
        for eq, base, lq, lf in ((r["home_team"], r["qbl"], qbl, fl), (r["away_team"], r["qbv"], qbv, fv)):
            votos, usado, est, det = fq.votar(eq, base)
            lq.append(usado or ""); lf.append(det)
            for fuente in FUENTES_VOTAN:
                votos_log.append(dict(corrida_utc=iso(ahora), tipo=tipo, game_id=r["game_id"], semana=sem, equipo=eq,
                                      fuente=fuente, qb_id=votos[fuente], qb_nombre=fq.nombre.get(votos[fuente], "")))
            votos_log.append(dict(corrida_utc=iso(ahora), tipo=tipo, game_id=r["game_id"], semana=sem, equipo=eq,
                                  fuente="consenso", qb_id=usado or "", qb_nombre=fq.nombre.get(usado, ""), nota=det))
    if tipo == "t85" and estado is not None:
        juegos = list(zip(gs["away_team"].to_list(), gs["home_team"].to_list(), gs["inicio"].to_list()))
        for eq, (gid_qb, nom, url) in gemini_qb(juegos, fq, ahora, estado).items():
            fila = next((r for r in gs.iter_rows(named=True) if eq in (r["home_team"], r["away_team"])), None)
            if fila:
                votos_log.append(dict(corrida_utc=iso(ahora), tipo=tipo, game_id=fila["game_id"], semana=sem, equipo=eq,
                                      fuente="gemini", qb_id=gid_qb, qb_nombre=nom, nota=url[:200]))
    anexar_fuentes(votos_log)
    return gs.with_columns(pl.Series("qbl", qbl), pl.Series("qbv", qbv), pl.Series("fl", fl), pl.Series("fv", fv))


def es_dudoso(f):
    return any(str(f.get(k) or "").startswith("dudoso") for k in ("qb_local_fuente", "qb_visita_fuente"))


def correr(tareas_a_correr, g_all, g26, args, ahora, ctx=None, estado=None):
    """Corrida hacia adelante (la que cuenta para 31A y 29A): juegos que todavía no empiezan."""
    import polars as pl
    ctx = ctx or preparar_contexto(g_all, g26)
    resumenes = []
    for tipo, clave, ids in tareas_a_correr:
        jg = juegos_con_qb(ctx, g26, pl.col("game_id").is_in(ids) & (pl.col("inicio") > ahora))
        if jg.height == 0:
            continue
        filas = []
        for sem, gs in jg.group_by("week", maintain_order=True):
            sem = int(sem[0] if isinstance(sem, tuple) else sem)
            gs = consenso_semana(gs, sem, tipo, ahora, estado)
            mg, tt, F = simular_semana(ctx, gs, sem, args.n_sims)
            pin = lineas_bot(args.bot_dir, "pinnacle", gs["game_id"].to_list(), ahora, MAX_EDAD_PIN_H)
            bo = lineas_bot(args.bot_dir, "betonlineag", gs["game_id"].to_list(), ahora, MAX_EDAD_BO_H)
            for i in range(gs.height):     # solo arma la fila de salida de cada juego (la simulación ya corrió en paralelo)
                gid = gs["game_id"][i]
                m = mg[i]
                f = fila_base(ctx, gs, i, m, tt[i], F, sem, tipo, ahora)
                p = pin.get(gid)
                if p:
                    f.update(pin_ts=p["ts"], pin_horas=p["horas"], pin_hcp_local=p["hcp_local"], pin_cuota_sp_local=p["cuota_sp_local"],
                             pin_cuota_sp_visit=p["cuota_sp_visit"], pin_ml_local=p["ml_local"], pin_ml_visit=p["ml_visit"])
                    if p["ml_local"] is not None and p["ml_visit"] is not None:
                        f["pin_p_ml_local"] = round(sin_vig_potencia(p["ml_local"], p["ml_visit"]), 4)
                    if p["cuota_sp_local"] is not None and p["cuota_sp_visit"] is not None:
                        f["pin_p_sp_local"] = round(sin_vig_potencia(p["cuota_sp_local"], p["cuota_sp_visit"]), 4)
                b = bo.get(gid)
                if b:
                    f.update(bo_ts=b["ts"], bo_horas=b["horas"], bo_hcp_local=b["hcp_local"], bo_ml_local=b["ml_local"], bo_ml_visit=b["ml_visit"])
                nsp = f["nfl_spread_line"]
                if f.get("pin_hcp_local") is not None:
                    f["ref_spread"] = "pinnacle"; f["spread_ref"] = f["pin_hcp_local"]
                elif nsp is not None:
                    f["ref_spread"] = "nflverse"; f["spread_ref"] = -float(nsp)
                marcar(f)
                # selecciones de 29A (solo con Pinnacle de ≤ 3 h)
                if f.get("pin_hcp_local") is not None:
                    h = f["pin_hcp_local"]
                    cub, psh = float((m + h > 0).mean()), float((m + h == 0).mean())
                    f["p_cubre_local"] = round(cub / max(1 - psh, 1e-9), 4); f["p_push"] = round(psh, 4)
                    if f["p_cubre_local"] >= UMBRAL_SP:
                        f["sel_sp"] = "local"; f["sel_sp_prob"] = f["p_cubre_local"]
                    elif 1 - f["p_cubre_local"] >= UMBRAL_SP:
                        f["sel_sp"] = "visita"; f["sel_sp_prob"] = round(1 - f["p_cubre_local"], 4)
                if f.get("pin_p_ml_local") is not None:
                    v = f["p_local"] - f["pin_p_ml_local"]
                    if v >= UMBRAL_ML:
                        f["sel_ml"] = "local"; f["sel_ml_ventaja"] = round(v, 4)
                    elif -v >= UMBRAL_ML:
                        f["sel_ml"] = "visita"; f["sel_ml_ventaja"] = round(-v, 4)
                pata_wong(f, f.get("bo_hcp_local"))           # con la foto de BetOnline de ≤ 12 h
                filas.append(f)
        sesgo_semanal(filas, list(leer_registro().iter_rows(named=True)))
        for f in filas:
            if f.get("sel_ml") or f.get("sel_sp"):
                if es_dudoso(f):
                    f["sel_estado"] = "excluida: QB dudoso"
                elif f.get("marcado_spread") or f.get("marcado_total"):
                    f["sel_estado"] = "excluida: filtro"
                elif f.get("bandera_sesgo"):
                    f["sel_estado"] = "excluida: sesgo de la semana"
                else:
                    f["sel_estado"] = "candidata"
            elif f.get("pin_hcp_local") is None:
                f["sel_estado"] = "sin Pinnacle de 3 h"
        anexar_registro(filas)
        resumenes.append((tipo, clave, filas, []))
        log(f"{tipo} {clave}: {len(filas)} juegos proyectados")
    return resumenes, ctx["nombres_qb"]


def retro(g_all, g26, args, ahora, ctx=None):
    """Retrospectiva: juegos de 2026 ya jugados SIN proyección previa en el registro (semanas 1-3 y el jueves de la 4).
    Misma función del modelo, con lo que sabía antes de cada juego (calificar usa solo semanas anteriores) y el QB que
    salió de titular. Línea de referencia = cierre de nflverse. Se guarda aparte y NO cuenta para 31A ni para el CLV."""
    import polars as pl
    reg = leer_registro()
    con_previa = set()
    for rr in reg.iter_rows(named=True):
        a, b = t_utc(rr.get("corrida_utc")), t_utc(rr.get("inicio_utc"))
        if a and b and a < b:
            con_previa.add(rr["game_id"])
    ctx = ctx or preparar_contexto(g_all, g26)
    jg = juegos_con_qb(ctx, g26, pl.col("result").is_not_null() & ~pl.col("game_id").is_in(list(con_previa)))
    filas = []
    for sem, gs in jg.group_by("week", maintain_order=True):
        sem = int(sem[0] if isinstance(sem, tuple) else sem)
        mg, tt, F = simular_semana(ctx, gs, sem, args.n_sims)
        for i in range(gs.height):
            f = fila_base(ctx, gs, i, mg[i], tt[i], F, sem, "retro", ahora)
            nsp = f["nfl_spread_line"]
            if nsp is not None:
                f["ref_spread"] = "nflverse"; f["spread_ref"] = -float(nsp)
            marcar(f)
            pata_wong(f, None if nsp is None else -float(nsp))   # con la línea de cierre de consenso
            f["sel_estado"] = "retro"
            filas.append(f)
    sesgo_semanal(filas, [])
    guardar_retro(filas)
    log(f"retro: {len(filas)} juegos ya jugados proyectados (semanas {sorted({f['semana'] for f in filas})}); "
        f"guardados aparte en {RETRO.name}")
    return filas, ctx


# --------------------------------------------------------------------------------------
# Salidas: hoja y Telegram
# --------------------------------------------------------------------------------------
def ultimas_proyecciones(semana):
    """{game_id: fila}: la última proyección hacia adelante del registro; si no hay, la retrospectiva."""
    import polars as pl
    out = {}
    for rr in leer_registro(RETRO).filter(pl.col("semana") == str(semana)).iter_rows(named=True):
        out[rr["game_id"]] = rr
    for rr in leer_registro().filter(pl.col("semana") == str(semana)).iter_rows(named=True):
        out[rr["game_id"]] = rr                          # el registro (antes del juego) manda sobre la retro
    return out


def actualizar_hoja(hoja, g26, semana, nombres_qb, ahora):
    """Pestaña 'Semana N' completa: una fila fija por juego (por hora de inicio) con la última proyección, las
    columnas de cierre si ya hay resultado, y la fila resumen. Todo sale del registro, la retro y nflverse."""
    import polars as pl
    if hoja is None or semana is None:
        return
    t = pestana(semana)
    asegurar_pestana(hoja, semana)
    jg = g26.filter(pl.col("week") == semana).sort(["inicio", "game_id"])
    claves = [r[0] if r else "" for r in hoja.leer(f"'{t}'!{COL_ID}5:{COL_ID}{FILAS_MAX}")]
    while claves and not claves[-1]:
        claves.pop()
    for gid in jg["game_id"].to_list():                 # juegos nuevos al final; nunca se reordena
        if gid not in claves:
            claves.append(gid)
    claves = claves[:FILAS_MAX - 4]
    info = {r["game_id"]: r for r in jg.iter_rows(named=True)}
    ult = ultimas_proyecciones(semana)
    filas, cierres = [], []
    for gid in claves:
        g = info.get(gid)
        u = ult.get(gid)
        if g is None:
            filas.append([""] * (NCOL - 1) + [gid]); continue
        loc, vis = g["home_team"], g["away_team"]
        base = [fecha_cc(g["inicio"]), f"{vis} @ {loc}"]
        c = cierre_de(g, u)
        cierres.append(c)
        if not u:
            lin = linea_txt(loc, vis, -g["spread_line"] if g["spread_line"] is not None else None)
            filas.append(base + [lin + (" (nflverse)" if lin else "")] + [""] * 10 + columnas_cierre(c) + ["", "", gid])
            continue
        marca = {"nflverse": " (cierre)" if u.get("tipo") == "retro" else " (nflverse)"}.get(u.get("ref_spread"), "")
        ref = linea_txt(loc, vis, u["spread_ref"]) + marca
        tot_c = _num(u.get("nfl_total_line"))
        fila = base + [ref, linea_txt(loc, vis, u["spread_modelo"]), dif_txt(loc, vis, u["spread_modelo"], u["spread_ref"]),
                       "" if tot_c is None else f"{tot_c:.1f}", f"{float(u['total']):.1f}",
                       gana_txt(loc, vis, u["p_local"]), gana_txt(loc, vis, u.get("pin_p_ml_local")),
                       senal_ml_txt(u), senal_sp_txt(u), wong_txt(u), estado_txt(u)]
        qb = (nombres_qb.get(u["qb_visita_id"], u["qb_visita_id"]) + " @ " + nombres_qb.get(u["qb_local_id"], u["qb_local_id"]))
        filas.append(fila + columnas_cierre(c) + [qb, f"{u['tipo']} {fecha_cc(t_utc(u['corrida_utc']), False)}", gid])
    n = len(claves)
    if n:
        hoja.escribir(f"'{t}'!A5:{COL_ID}{4 + n}", [["" if x is None else x for x in f] for f in filas])
    nota = (" · semana retrospectiva: proyecciones hechas después de los juegos" if semana < SEMANA_AUTO
            else " · semana informativa, fuera de 31A" if semana < SEMANA_31A else "")
    hoja.escribir(f"'{t}'!A1:C1", [[f"Semana {semana} · NFL {TEMPORADA}", "",
                                    f"motor s2-v1 en modo registro (sin validar) · actualizado {fecha_cc(ahora)} (Caracas) · "
                                    f"líneas en convención de la casa: DAL -3.5 = DAL favorito por 3,5" + nota]])
    conf = confiabilidad_txt(confiabilidad_qb(g26, semana))
    hoja.escribir(f"'{t}'!A3:C3", [["Resumen", "", resumen_txt(cierres, jg.height) + (" " + conf + "." if conf else "")]])


def escribir_semanas(hoja, g26, semanas, nombres_qb, ahora, estado):
    """Reescribe las pestañas de esas semanas (de la más vieja a la más nueva, así la más nueva queda primera) y anota
    los resultados ya mostrados. Devuelve las semanas que fallaron."""
    import polars as pl
    fallas = []
    for s_ in sorted(set(semanas)):
        try:
            actualizar_hoja(hoja, g26, s_, nombres_qb, ahora)
            hechos = g26.filter((pl.col("week") == s_) & pl.col("result").is_not_null())["game_id"].to_list()
            estado["resultados"] = sorted(set(estado.get("resultados", [])) | set(hechos))
            log(f"hoja: pestaña {pestana(s_)} actualizada")
        except Exception as e:  # noqa: BLE001
            fallas.append(s_)
            log(f"Hoja: error al escribir la pestaña {pestana(s_)} ({type(e).__name__}: {str(e)[:300]})")
    return fallas
def texto_telegram(resumenes):
    lin = []
    for tipo, clave, filas, avisos in resumenes:
        nombre = {"miercoles": "Miércoles 10:15", "sabado": "Sábado 10:15", "t85": "T−85", "reajuste": "Reajuste (cambio de QB)",
                  "manual": "Manual"}.get(tipo, tipo)
        sems = sorted({f["semana"] for f in filas})
        lin.append(f"MOTOR s2-v1 · {nombre} · semana {', '.join(map(str, sems))} · {len(filas)} juegos · sin validar (H29)")
        for f in filas:
            marca = "🔴 " if (f.get("marcado_spread") or f.get("marcado_total") or es_dudoso(f)) else ("🟢 " if f.get("sel_estado") == "candidata" else "")
            extra = [x for x in (senal_ml_txt(f), senal_sp_txt(f)) if x]
            w = wong_txt(f)
            lin.append(f"{marca}{f['visita']} @ {f['local']}: mercado {linea_txt(f['local'], f['visita'], f.get('spread_ref')) or '—'}"
                       f"{'*' if f.get('ref_spread') == 'nflverse' else ''} · modelo {linea_txt(f['local'], f['visita'], f['spread_modelo'])}"
                       f" · total {f['total']:.1f} (cons. {f.get('nfl_total_line')})"
                       + (f" · {'; '.join(extra)} [{f.get('sel_estado')}]" if extra else "")
                       + (f" · 🔵 Wong {w}" if w else "")
                       + (" · QB dudoso" if es_dudoso(f) else ""))
        bs = [f for f in filas if f.get("bandera_sesgo")]
        if bs:
            lin.append(f"⚠️ Revisión de sesgo de la semana: spread {bs[0].get('sesgo_spread_semana')} / total {bs[0].get('sesgo_total_semana')}")
        lin += [f"Aviso: {a}" for a in avisos]
        lin.append("* = consenso de nflverse (no hay Pinnacle de ≤ 3 h). 🔴 revisar (modelo y mercado muy distintos, o QB dudoso) · 🟢 candidata del modelo · 🔵 pata Wong.")
        lin.append("")
    return "\n".join(lin).strip()


def texto_retro(filas, g26):
    """Resumen corto por Telegram de la retrospectiva (descriptivo; no cuenta para 31A ni para el CLV)."""
    info = {r["game_id"]: r for r in g26.iter_rows(named=True)}
    lin = [f"MOTOR s2-v1 · RETRO 2026 · {len(filas)} juegos ya jugados · proyección hecha después (no cuenta)"]
    for sem in sorted({f["semana"] for f in filas}):
        cc = [cierre_de(info[f["game_id"]], f) for f in filas if f["semana"] == sem and f["game_id"] in info]
        lin.append(f"Semana {sem}: " + resumen_txt(cc, len(cc)).split(". Error =")[0])
    lin.append("Detalle por juego en la hoja (pestañas en gris).")
    return "\n".join(lin)


def texto_qb(g26, ahora, semana=None):
    """QB titular de cada juego pendiente de la semana según cada fuente, el consenso y la confiabilidad acumulada."""
    import polars as pl
    sem = semana or semana_actual(g26, ahora)
    if sem is None:
        return "No hay juegos pendientes en el calendario."
    jg = g26.filter((pl.col("week") == sem) & (pl.col("inicio") > ahora)).sort(["inicio", "game_id"])
    fq = FuentesQB(sem)
    nom = lambda g: fq.nombre.get(g, g) or "—"  # noqa: E731
    lin = [f"QB titular · semana {sem} · visitante @ local · [acuerdo de nflverse, ESPN y Sleeper]"]
    dudas = []
    for r in jg.iter_rows(named=True):
        partes = []
        for eq, base in ((r["away_team"], _texto(r.get("away_qb_id"))), (r["home_team"], _texto(r.get("home_qb_id")))):
            votos, usado, est, det = fq.votar(eq, base)
            partes.append(f"{nom(usado)} [{est}]")
            if est == "dudoso" or "difiere" in det:
                dudas.append(f"  {eq}: {det}")
        lin.append(f"{fecha_cc(r['inicio'])} {r['away_team']} @ {r['home_team']}: {partes[0]} @ {partes[1]}")
    if dudas:
        lin.append("Desacuerdos:")
        lin += dudas
    lin += [f"Aviso: {a}" for a in fq.avisos]
    conf = confiabilidad_txt(confiabilidad_qb(g26))
    lin.append(conf + " (acumulado; mide contra el QB que jugó)" if conf else "Confiabilidad: todavía sin juegos cerrados con votos registrados.")
    return "\n".join(lin)


def leer_roster():
    import polars as pl
    try:
        return pl.read_csv(DATOS / f"roster_{TEMPORADA}.csv", infer_schema_length=0).filter(pl.col("position") == "QB")
    except Exception:  # noqa: BLE001
        return None


def semanas_con_datos(g26):
    """Semanas con algo que mostrar: proyecciones (registro o retro) o resultados."""
    import polars as pl
    sems = {int(s) for s in leer_registro()["semana"].to_list() if s} | {int(s) for s in leer_registro(RETRO)["semana"].to_list() if s}
    sems |= {int(w) for w in g26.filter(pl.col("result").is_not_null())["week"].unique().to_list()}
    return sorted(sems)


# --------------------------------------------------------------------------------------
# Principal
# --------------------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("modo", choices=["auto", "estado", "correr", "retro", "hoja", "qb", "hoja-prueba"])
    ap.add_argument("--semana", type=int)
    ap.add_argument("--juegos")
    ap.add_argument("--tipo", default="manual")
    ap.add_argument("--ahora")
    ap.add_argument("--sin-telegram", action="store_true")
    ap.add_argument("--sin-hoja", action="store_true")
    ap.add_argument("--bot-dir", default=str(Path.home() / "nfl_ev"))
    ap.add_argument("--n-sims", type=int, default=N_SIMS)
    args = ap.parse_args()
    if os.nice(0) < 10:
        os.nice(10 - os.nice(0))
    ahora = t_utc(args.ahora) if args.ahora else dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    SAL.mkdir(parents=True, exist_ok=True)
    candado = open(SAL / ".candado", "w")
    try:
        fcntl.flock(candado, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        if args.modo != "auto":
            print("Ya hay una corrida de semana.py en marcha.")
        return
    estado = leer_estado()
    g_all, g26 = calendario(MAX_EDAD_CAL_H)
    hoja = abrir_hoja(args)

    if args.modo == "hoja-prueba":
        if hoja is None:
            print("Hoja: no configurada (falta semana.ini o la credencial) o no se pudo abrir.")
            return
        try:
            ps = hoja.pestanas()
        except Exception as e:  # noqa: BLE001
            txt = str(e)
            if "403" in txt:
                print("Hoja: sin permiso (403). Comparte la hoja con el correo de la cuenta de servicio, como Editor.")
            elif "404" in txt:
                print("Hoja: no existe (404). Revisa hoja_id en semana.ini.")
            else:
                print(f"Hoja: no se pudo conectar ({type(e).__name__}). Revisa la llave JSON y que la API de Google Sheets esté habilitada.")
            return
        print(f"Hoja OK: pestañas {list(ps)}")
        # escritura real con el mismo formato que las pestañas semanales: crea una pestaña de prueba y la borra
        try:
            viejas = [i for nombre, i in ps.items() if nombre == TITULO_PRUEBA or i == SID_PRUEBA]
            if viejas:
                hoja.lote([{"deleteSheet": {"sheetId": i}} for i in viejas])
            crear_pestana(hoja, 0, TITULO_PRUEBA, SID_PRUEBA)
            hoja.escribir(f"'{TITULO_PRUEBA}'!A5:B5", [["dom 04-oct 13:00", "PRUEBA @ PRUEBA"]])
            hoja.lote([{"deleteSheet": {"sheetId": SID_PRUEBA}}])
        except Exception as e:  # noqa: BLE001
            print(f"Hoja: conecta, pero falló la pestaña de prueba ({type(e).__name__}: {str(e)[:300]})")
            return
        print("Hoja OK: pestaña de prueba con el formato semanal creada, escrita y borrada")
        return

    if args.modo == "estado":
        import polars as pl
        lista, sem = tareas(g26, ahora, estado)
        hoja_ok = False
        if hoja is not None:
            try:
                hoja.pestanas()
                hoja_ok = True
            except Exception:  # noqa: BLE001
                pass
        print(f"{VERSION_SEMANA} · ahora {fecha_cc(ahora)} Caracas · semana actual {sem}")
        n_reg = sum(1 for _ in open(REGISTRO)) - 1 if REGISTRO.exists() else 0
        n_ret = sum(1 for _ in open(RETRO)) - 1 if RETRO.exists() else 0
        print(f"Hoja: {'conectada' if hoja_ok else 'no configurada o sin acceso'} · registro: {n_reg} filas · retro: {n_ret} filas")
        print("Toca ahora:", [(t, c, len(i)) for t, c, i in lista] or "nada")
        nuevos = resultados_nuevos(g26, estado)
        print("Resultados por escribir en la hoja:", {s: len(v) for s, v in sorted(nuevos.items())} or "ninguno")
        if sem is not None:
            fut = g26.filter((pl.col("week") == sem) & (pl.col("inicio") > ahora)).sort("inicio")
            for (ini,), gr in fut.group_by(["inicio"], maintain_order=True):
                print(f"  grupo {fecha_cc(ini)} Caracas: {gr.height} juegos · T−85 a las "
                      f"{(ini - dt.timedelta(minutes=MIN_T85)).astimezone(CARACAS).strftime('%H:%M')}"
                      f"{' (ya corrió)' if iso(ini) in estado['grupos'] else ''}")
        return

    if args.modo == "qb":
        print(texto_qb(g26, ahora, args.semana))
        return

    if args.modo == "hoja":
        if hoja is None:
            print("Hoja: no configurada (falta semana.ini o la credencial) o no se pudo abrir.")
            return
        semanas = [args.semana] if args.semana else semanas_con_datos(g26)
        log(f"{VERSION_SEMANA}: rehago las pestañas {semanas} (sin simular)")
        escribir_semanas(hoja, g26, semanas, nombres_de_qb(g26, leer_roster()), ahora, estado)
        guardar_estado(estado)
        log("== LISTO")
        return

    if args.modo == "retro":
        log(f"{VERSION_SEMANA}: retrospectiva de los juegos de {TEMPORADA} ya jugados")
        filas, ctx = retro(g_all, g26, args, ahora)
        if hoja is not None and filas:
            escribir_semanas(hoja, g26, {f["semana"] for f in filas}, ctx["nombres_qb"], ahora, estado)
            guardar_estado(estado)
        if filas and not args.sin_telegram:
            ctx["s2"].telegram(texto_retro(filas, g26))
        log("== LISTO")
        return

    if args.modo == "auto":
        lista, sem = tareas(g26, ahora, estado)
        if not lista:
            nuevos = resultados_nuevos(g26, estado) if hoja is not None else {}
            falla = t_utc(estado.get("ultima_falla_hoja"))
            if nuevos and (falla is None or (ahora - falla).total_seconds() > 1800):
                # solo cierre de juegos: reescribe esas pestañas, sin simular (si la hoja falló, reintenta cada 30 min)
                log(f"{VERSION_SEMANA}: resultados nuevos en las semanas {sorted(nuevos)}")
                if escribir_semanas(hoja, g26, nuevos.keys(), nombres_de_qb(g26, leer_roster()), ahora, estado):
                    estado["ultima_falla_hoja"] = iso(ahora)
                else:
                    estado.pop("ultima_falla_hoja", None)
                guardar_estado(estado)
            return                                         # nada que hacer: sale sin escribir en el log
    else:
        import polars as pl
        sem = args.semana or semana_actual(g26, ahora)
        ids = args.juegos.split(",") if args.juegos else g26.filter((pl.col("week") == sem) & (pl.col("inicio") > ahora))["game_id"].to_list()
        lista = [(args.tipo, f"{args.tipo}-{iso(ahora)}", ids)]

    log(f"{VERSION_SEMANA}: corre {[(t, c, len(i)) for t, c, i in lista]}")
    g_all, g26 = calendario(0.25)                    # calendario fresco (QB titulares y líneas) antes de proyectar
    resumenes, nombres_qb = correr(lista, g_all, g26, args, ahora, estado=estado)
    for tipo, clave, ids in lista:
        if tipo in ("miercoles", "sabado"):
            estado["fijas"][clave] = iso(ahora)
        elif tipo == "t85":
            estado["grupos"][clave] = iso(ahora)
    guardar_estado(estado)
    if hoja is not None:
        sems = {f["semana"] for _, _, filas, _ in resumenes for f in filas} | set(resultados_nuevos(g26, estado).keys())
        escribir_semanas(hoja, g26, sems, nombres_qb, ahora, estado)
        guardar_estado(estado)
    if resumenes and not args.sin_telegram:
        sys.path.insert(0, str(BASE))
        import sprint2 as s2
        s2.telegram(texto_telegram(resumenes))
    log("== LISTO")


if __name__ == "__main__":
    main()
