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

Cuándo corre (modo 'auto', lo llama el temporizador de systemd cada 5 min; si no toca nada, sale sin escribir)
  · miércoles y sábado 10:15 (Caracas): todos los juegos de la semana que no empezaron;
  · T−85 min de cada grupo de inicio (calculado del calendario: cubre el cambio de hora, sábados, playoffs);
  · desde T−90 hasta el inicio: si Ozz cambió un QB en las columnas amarillas, vuelve a correr ese grupo.
  Corre desde la semana 4 (la 4 es informativa); la confirmación 31A y el CLV de 29A cuentan desde la semana 5.

Uso
  venv/bin/python semana.py auto                          (lo usa el temporizador)
  venv/bin/python semana.py estado                        (qué toca y cuándo; no corre nada)
  venv/bin/python semana.py correr [--semana N] [--juegos ID,ID] [--tipo manual]
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
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

VERSION_SEMANA = "semana-v3 (2-oct-2026)"
# v3: la pestaña semanal no combina celdas a través del borde de las columnas inmovilizadas A-B (Sheets lo
#     rechazaba con 400 en la primera corrida real); el error de Sheets ahora trae el mensaje de Google;
#     'hoja-prueba' crea y borra una pestaña de prueba con el mismo formato que las semanales.
BASE = Path(__file__).resolve().parent
DATOS = BASE / "datos"
SAL = BASE / "salidas" / "semana"
REGISTRO = SAL / "proyecciones_2026.csv"
ESTADO = SAL / "estado.json"
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
MIN_T85, MIN_REAJUSTE = 85, 90     # 30A: señal a T−85; reajustes desde T−90 hasta el inicio
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
        return json.loads(ESTADO.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"fijas": {}, "grupos": {}, "hash_ajustes": {}}


def guardar_estado(e):
    SAL.mkdir(parents=True, exist_ok=True)
    tmp = ESTADO.with_suffix(".tmp")
    tmp.write_text(json.dumps(e, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(ESTADO)


def leer_registro():
    import polars as pl
    if not REGISTRO.exists():
        return pl.DataFrame({c: [] for c in CAMPOS}, schema={c: pl.Utf8 for c in CAMPOS})
    return pl.read_csv(REGISTRO, infer_schema_length=0)          # todo como texto


def anexar_registro(filas):
    SAL.mkdir(parents=True, exist_ok=True)
    nuevo = not REGISTRO.exists()
    with open(REGISTRO, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CAMPOS)
        if nuevo:
            w.writeheader()
        for f in filas:
            w.writerow({k: ("" if f.get(k) is None else f.get(k)) for k in CAMPOS})


# --------------------------------------------------------------------------------------
# Qué toca ahora
# --------------------------------------------------------------------------------------
def semana_actual(g26, ahora):
    import polars as pl
    pend = g26.filter(pl.col("result").is_null() & (pl.col("inicio") > ahora))
    return int(pend["week"].min()) if pend.height else None


def grupos_en_ventana(g26, ahora, estado):
    """Grupos ya corridos a T−85 cuyo inicio está a menos de 90 min: {clave: (semana, [game_id])}."""
    import polars as pl
    fut = g26.filter((pl.col("inicio") > ahora) & (pl.col("inicio") <= ahora + dt.timedelta(minutes=MIN_REAJUSTE)))
    out = {}
    for (ini,), gr in fut.group_by(["inicio"], maintain_order=True):
        if iso(ini) in estado["grupos"]:
            out[iso(ini)] = (int(gr["week"][0]), gr["game_id"].to_list())
    return out


def tareas(g26, ahora, estado, ajustes_hash=None):
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
        elif clave in estado["grupos"] and ajustes_hash is not None and ahora >= ini - dt.timedelta(minutes=MIN_REAJUSTE):
            h = ajustes_hash(grupo["game_id"].to_list())
            previo = estado["hash_ajustes"].get(clave)
            if previo is not None and h != previo:
                out.append(("reajuste", clave, grupo["game_id"].to_list()))
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


# Columnas de la pestaña semanal (A-M y Q-R las escribe la EC2; N-P son de Ozz; S es la clave del juego)
ENCAB = ["Inicio (Caracas)", "Juego", "Línea Pinnacle", "Línea modelo", "Modelo vs mercado", "Total consenso",
         "Total modelo", "Gana (modelo)", "Gana (Pinnacle)", "Señal ML", "Señal spread", "Pata Wong (BetOnline)",
         "Revisar / estado", "QB local (si cambió)", "QB visita (si cambió)", "OK", "QB usados", "Corrida", "game_id"]
COLORES = {"verde": "#D9EAD3", "verde_fuerte": "#93C47D", "azul": "#9FC5E8", "rojo": "#F4CCCC",
           "amarillo": "#FFFF00", "encab": "#1F3864", "gris": "#999999", "blanco": "#FFFFFF"}


def _rgb(h):
    h = h.lstrip("#")
    return {"red": int(h[0:2], 16) / 255, "green": int(h[2:4], 16) / 255, "blue": int(h[4:6], 16) / 255}


def _rango(sid, f0, f1, c0, c1):
    return {"sheetId": sid, "startRowIndex": f0, "endRowIndex": f1, "startColumnIndex": c0, "endColumnIndex": c1}


TITULO_PRUEBA, SID_PRUEBA = "Prueba (se borra sola)", 1999     # pestaña temporal de 'hoja-prueba'


def crear_pestana(hoja, sem, titulo=None, sid=None):
    """Crea la pestaña 'Semana N' (primera a la izquierda) con encabezado, leyenda de colores y formatos.
    Columnas A-B inmovilizadas (inicio y juego): ninguna celda combinada cruza ese borde, porque Sheets
    rechaza toda la tanda con 400 ("no puedes combinar columnas inmovilizadas con columnas móviles")."""
    sid = 1000 + sem if sid is None else sid
    t = titulo or pestana(sem)
    fondo = lambda r, color: {"repeatCell": {"range": r, "cell": {"userEnteredFormat": {"backgroundColorStyle": {"rgbColor": _rgb(color)}}},  # noqa: E731
                                             "fields": "userEnteredFormat.backgroundColorStyle"}}
    regla = lambda rangos, formula, color, negrita=False, idx=0: {"addConditionalFormatRule": {"index": idx, "rule": {  # noqa: E731
        "ranges": rangos, "booleanRule": {"condition": {"type": "CUSTOM_FORMULA", "values": [{"userEnteredValue": formula}]},
                                          "format": {"backgroundColorStyle": {"rgbColor": _rgb(color)}, "textFormat": {"bold": negrita}}}}}}
    ancho = lambda c0, c1, px: {"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": c0, "endIndex": c1},  # noqa: E731
                                                              "properties": {"pixelSize": px}, "fields": "pixelSize"}}
    juegos = _rango(sid, 4, FILAS_MAX, 0, 13)
    combinar = lambda c0, c1, f=0: {"mergeCells": {"range": _rango(sid, f, f + 1, c0, c1), "mergeType": "MERGE_ALL"}}  # noqa: E731
    pedidos = [
        {"addSheet": {"properties": {"sheetId": sid, "title": t, "index": 0,
                                     "gridProperties": {"rowCount": FILAS_MAX, "columnCount": 19, "frozenRowCount": 4, "frozenColumnCount": 2}}}},
        # fila 1: A-B (inmovilizadas) "Semana N · NFL 2026" | C-S detalle de la corrida
        combinar(0, 2, 0), combinar(2, 19, 0),
        # fila 2: A-B rótulo | C-F verde | G-J azul | K-N rojo | O-S amarillo  (ninguna cruza el borde B|C)
        combinar(0, 2, 1), combinar(2, 6, 1), combinar(6, 10, 1), combinar(10, 14, 1), combinar(14, 19, 1),
        {"repeatCell": {"range": _rango(sid, 0, 1, 0, 2), "cell": {"userEnteredFormat": {"textFormat": {"bold": True, "fontSize": 13}}},
                        "fields": "userEnteredFormat.textFormat"}},
        {"repeatCell": {"range": _rango(sid, 0, 1, 2, 19), "cell": {"userEnteredFormat": {"textFormat": {
            "fontSize": 9, "foregroundColorStyle": {"rgbColor": _rgb(COLORES["gris"])}}, "verticalAlignment": "MIDDLE"}},
            "fields": "userEnteredFormat.textFormat,userEnteredFormat.verticalAlignment"}},
        {"repeatCell": {"range": _rango(sid, 1, 2, 0, 2), "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                        "fields": "userEnteredFormat.textFormat"}},
        fondo(_rango(sid, 1, 2, 2, 6), COLORES["verde"]), fondo(_rango(sid, 1, 2, 6, 10), COLORES["azul"]),
        fondo(_rango(sid, 1, 2, 10, 14), COLORES["rojo"]), fondo(_rango(sid, 1, 2, 14, 19), COLORES["amarillo"]),
        {"repeatCell": {"range": _rango(sid, 1, 2, 0, 19), "cell": {"userEnteredFormat": {"wrapStrategy": "WRAP", "verticalAlignment": "MIDDLE"}},
                        "fields": "userEnteredFormat.wrapStrategy,userEnteredFormat.verticalAlignment"}},
        {"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "ROWS", "startIndex": 1, "endIndex": 2},
                                       "properties": {"pixelSize": 64}, "fields": "pixelSize"}},
        {"repeatCell": {"range": _rango(sid, 3, 4, 0, 19), "cell": {"userEnteredFormat": {
            "textFormat": {"bold": True, "foregroundColorStyle": {"rgbColor": _rgb(COLORES["blanco"])}},
            "backgroundColorStyle": {"rgbColor": _rgb(COLORES["encab"])}, "wrapStrategy": "WRAP", "verticalAlignment": "MIDDLE"}},
            "fields": "userEnteredFormat.textFormat,userEnteredFormat.backgroundColorStyle,userEnteredFormat.wrapStrategy,userEnteredFormat.verticalAlignment"}},
        fondo(_rango(sid, 4, FILAS_MAX, 13, 16), COLORES["amarillo"]),
        {"repeatCell": {"range": _rango(sid, 4, FILAS_MAX, 16, 19), "cell": {"userEnteredFormat": {"textFormat": {
            "fontSize": 8, "foregroundColorStyle": {"rgbColor": _rgb(COLORES["gris"])}}}}, "fields": "userEnteredFormat.textFormat"}},
        ancho(0, 1, 110), ancho(1, 2, 95), ancho(2, 4, 100), ancho(4, 5, 110), ancho(5, 7, 80), ancho(7, 9, 95),
        ancho(9, 11, 135), ancho(11, 12, 140), ancho(12, 13, 230), ancho(13, 15, 125), ancho(15, 16, 45), ancho(16, 17, 230),
        ancho(17, 18, 120), ancho(18, 19, 130),
        # colores de las filas de juegos (el orden importa: la primera regla que se cumple manda)
        regla([_rango(sid, 4, FILAS_MAX, 11, 12)], "=LEN($L5)>0", COLORES["azul"], True, 0),
        regla([juegos], '=LEFT($M5,7)="REVISAR"', COLORES["rojo"], False, 1),
        regla([_rango(sid, 4, FILAS_MAX, 9, 11)], '=AND(LEN(J5)>0,LEFT($M5,9)="candidata",UPPER($P5)="OK")', COLORES["verde_fuerte"], True, 2),
        regla([_rango(sid, 4, FILAS_MAX, 9, 11)], '=AND(LEN(J5)>0,LEFT($M5,9)="candidata")', COLORES["verde"], True, 3),
    ]
    hoja.lote(pedidos)
    hoja.escribir(f"'{t}'!A2", [["Colores", "",
                                 "Verde: candidata del modelo (sin validar, H29: el cierre le gana por 0,4 pts). Verde fuerte = con tu OK. Solo monto mínimo.",
                                 "", "", "",
                                 "Azul: pata Wong para teaser de 6 pts (underdog +1,5 a +2,5 en BetOnline, total < 50). Es lo único con valor medido (H28).",
                                 "", "", "",
                                 "Rojo: el modelo y el mercado difieren mucho. En ese juego no se usa el modelo.",
                                 "", "", "",
                                 "Amarillo: lo editas tú. QB si el titular cambió (nombre como en nflverse). OK cuando revisaste el juego."]])
    hoja.escribir(f"'{t}'!A4", [ENCAB])
    return sid


def leer_ajustes(hoja, semanas):
    """{game_id: dict(qb_local, qb_visita, ok)} desde las columnas amarillas de las pestañas de esas semanas."""
    if hoja is None:
        return {}
    existentes = hoja.pestanas()
    out = {}
    for sem in sorted(set(semanas)):
        if pestana(sem) not in existentes:
            continue
        filas = hoja.leer(f"'{pestana(sem)}'!N5:S{FILAS_MAX}")
        for f in filas:
            f = list(f) + [""] * (6 - len(f))
            if f[5].strip():
                out[f[5].strip()] = dict(qb_local=f[0].strip(), qb_visita=f[1].strip(), ok=f[2].strip().upper() == "OK")
    return out


def hash_ajustes_de(ajustes, ids):
    txt = "|".join(f"{i}:{ajustes.get(i, {}).get('qb_local', '')}:{ajustes.get(i, {}).get('qb_visita', '')}" for i in sorted(ids))
    return hashlib.md5(txt.encode("utf-8")).hexdigest()


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
    edad = _num(f.get("bo_horas"))
    return f"{eq} +{lin:.1f} → +{lin + 6:.1f}" + (f" (hace {edad:.0f} h)" if edad is not None and edad >= 1 else "")


def estado_txt(f):
    if f.get("marcado_spread") in (1, "1") or f.get("marcado_total") in (1, "1"):
        partes = []
        if f.get("marcado_spread") in (1, "1"):
            partes.append(f"spread {abs(float(f['dif_spread'])):.1f} pts")
        if f.get("marcado_total") in (1, "1"):
            partes.append(f"total {abs(float(f['dif_total'])):.1f} pts")
        return "REVISAR: modelo y mercado difieren (" + ", ".join(partes) + ")"
    return f.get("sel_estado") or ""


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


def qb_por_nombre(roster, equipo, nombre):
    """gsis_id del QB por nombre (ajuste de Ozz). Prefiere el del equipo; sin coincidencia → None."""
    import polars as pl
    if roster is None or not nombre:
        return None
    r = roster.filter(pl.col("full_name").str.to_lowercase() == nombre.strip().lower())
    if r.height == 0:
        return None
    r2 = r.filter(pl.col("team") == equipo)
    return (r2 if r2.height else r)["gsis_id"][0]


# --------------------------------------------------------------------------------------
# Corrida
# --------------------------------------------------------------------------------------
def correr(tareas_a_correr, g_all, g26, args, ahora, ajustes):
    import numpy as np
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
        log("AVISO: sin roster 2026 (los ajustes de QB por nombre no se podrán leer)")
    t0 = time.time()
    games, pbp = s2.preparar_datos()
    M = s2.construir_modelo(pbp, games)
    pp = pbp.filter(pl.col("play_type").is_in(["pass", "run"]) & pl.col("down").is_not_null()
                    & pl.col("epa").is_not_null() & pl.col("posteam").is_not_null())
    mu_pool = (float(pp.filter(pl.col("play_type") == "pass")["epa"].mean()), float(pp.filter(pl.col("play_type") == "run")["epa"].mean()))
    del pbp, pp
    EQ = s2.preparar_equipos(s2.cargar_equipos(g_all))
    log(f"modelo s2-v1 listo en {time.time() - t0:.0f} s · {len(EQ['qidx'])} QB · pico {s2.pico_mb():.0f} MB")
    nombres_qb = {}
    for a, b in zip(g26["home_qb_id"].fill_null("").to_list() + g26["away_qb_id"].fill_null("").to_list(),
                    g26["home_qb_name"].fill_null("").to_list() + g26["away_qb_name"].fill_null("").to_list()):
        if a:
            nombres_qb[a] = b
    if roster is not None:
        for a, b in zip(roster["gsis_id"].to_list(), roster["full_name"].to_list()):
            nombres_qb.setdefault(a, b)
    hfa = s2.localia(g_all, TEMPORADA)
    resumenes = []
    for tipo, clave, ids in tareas_a_correr:
        jg = (g26.filter(pl.col("game_id").is_in(ids) & (pl.col("inicio") > ahora))
              .with_columns(pl.col("home_team").replace(s2.EQUIV), pl.col("away_team").replace(s2.EQUIV))
              .sort(["week", "inicio", "game_id"]))
        if jg.height == 0:
            continue
        # QB: el de nflverse, salvo ajuste de Ozz en la hoja
        qbl, qbv, fl, fv, avisos = [], [], [], [], []
        for gid, loc_, vis, ql, qv in zip(jg["game_id"].to_list(), jg["home_team"].to_list(), jg["away_team"].to_list(),
                                          jg["home_qb_id"].fill_null("").to_list(), jg["away_qb_id"].fill_null("").to_list()):
            a = ajustes.get(gid, {})
            for nombre, equipo, base_id, lista, fuentes in ((a.get("qb_local"), loc_, ql, qbl, fl), (a.get("qb_visita"), vis, qv, qbv, fv)):
                q = qb_por_nombre(roster, equipo, nombre) if nombre else None
                if nombre and not q:
                    avisos.append(f"{gid}: no encontré al QB «{nombre}» de {equipo}; uso el de nflverse")
                lista.append(q or base_id)
                fuentes.append("ajuste" if q else "nflverse")
        filas = []
        jg = jg.with_columns(pl.Series("qbl", qbl), pl.Series("qbv", qbv), pl.Series("fl", fl), pl.Series("fv", fv))
        for sem, gs in jg.group_by("week", maintain_order=True):
            sem = int(sem[0] if isinstance(sem, tuple) else sem)
            R = s2.calificar(EQ, TEMPORADA * s2.W_TEMP + sem, TEMPORADA)
            F = s2.fuerza_partidos(EQ, R, gs["home_team"].to_list(), gs["away_team"].to_list(), gs["qbl"].to_list(),
                                   gs["qbv"].to_list(), (gs["location"] == "Neutral").to_numpy(), hfa, mu_pool)
            ng = gs.height
            rep = np.repeat(np.arange(ng), args.n_sims)
            po = np.repeat((gs["game_type"] != "REG").to_numpy(), args.n_sims)
            r = s2.simular(M, ng * args.n_sims, po, np.random.default_rng(SEMILLA_PROD + TEMPORADA * 100 + sem),
                           fuerza=dict(dp=F["dp"][rep], dr=F["dr"][rep]))
            mg = r["margen"].reshape(ng, args.n_sims); tt = r["total"].reshape(ng, args.n_sims)
            pin = lineas_bot(args.bot_dir, "pinnacle", gs["game_id"].to_list(), ahora, MAX_EDAD_PIN_H)
            bo = lineas_bot(args.bot_dir, "betonlineag", gs["game_id"].to_list(), ahora, MAX_EDAD_BO_H)
            for i in range(ng):          # solo arma la fila de salida de cada juego (la simulación ya corrió en paralelo)
                gid = gs["game_id"][i]
                m = mg[i]
                pw, pt_, pe = float((m > 0).mean()), float((m < 0).mean()), float((m == 0).mean())
                f = dict(corrida_utc=iso(ahora), tipo=tipo, version="s2-v1", game_id=gid, semana=sem,
                         game_type=gs["game_type"][i], inicio_utc=iso(gs["inicio"][i]), local=gs["home_team"][i],
                         visita=gs["away_team"][i], qb_local_id=gs["qbl"][i], qb_visita_id=gs["qbv"][i],
                         qb_local_fuente=gs["fl"][i], qb_visita_fuente=gs["fv"][i], margen=round(float(m.mean()), 3),
                         mediana=float(np.median(m)), total=round(float(tt[i].mean()), 3),
                         p_local=round(pw / max(pw + pt_, 1e-9), 4), p_empate=round(pe, 4), de_margen=round(float(m.std()), 3),
                         localia=round(hfa, 3), ajuste_qb_local_pts=round(float(F["adj"][i, 0]) * s2.RESP["a_p"], 2),
                         ajuste_qb_visita_pts=round(float(F["adj"][i, 1]) * s2.RESP["a_p"], 2))
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
                nsp = gs["spread_line"][i]; ntl = gs["total_line"][i]
                f["nfl_spread_line"] = nsp; f["nfl_total_line"] = ntl
                f["spread_modelo"] = round(-f["margen"], 2)                       # convención de la casa: local −3,5 = favorito
                if f.get("pin_hcp_local") is not None:
                    f["ref_spread"] = "pinnacle"; f["spread_ref"] = f["pin_hcp_local"]
                elif nsp is not None:
                    f["ref_spread"] = "nflverse"; f["spread_ref"] = -float(nsp)
                if f.get("spread_ref") is not None:
                    f["dif_spread"] = round(f["spread_modelo"] - f["spread_ref"], 2)
                    f["marcado_spread"] = int(abs(f["dif_spread"]) > FILTRO_SPREAD)
                if ntl is not None:
                    f["dif_total"] = round(f["total"] - float(ntl), 2)
                    f["marcado_total"] = int(abs(f["dif_total"]) > FILTRO_TOTAL)
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
                # pata Wong (H26/H28): underdog de BetOnline a +1,5/+2/+2,5 y total < 50 (no depende del modelo)
                if f.get("bo_hcp_local") is not None and ntl is not None and float(ntl) < WONG_TOTAL_MAX:
                    hb = float(f["bo_hcp_local"])
                    lado, lin = ("local", hb) if hb > 0 else ("visita", -hb)
                    if any(abs(lin - w) < 1e-6 for w in WONG_LINEAS):
                        f["wong"] = lado; f["wong_linea"] = lin
                filas.append(f)
        # revisión de sesgo de la semana: última proyección de cada juego de la semana (registro + esta corrida)
        reg = leer_registro()
        for sem in sorted({f["semana"] for f in filas}):
            ult = {}
            for rr in reg.filter(pl.col("semana") == str(sem)).iter_rows(named=True):
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
        for f in filas:
            if f.get("sel_ml") or f.get("sel_sp"):
                if f.get("marcado_spread") or f.get("marcado_total"):
                    f["sel_estado"] = "excluida: filtro"
                elif f.get("bandera_sesgo"):
                    f["sel_estado"] = "excluida: sesgo de la semana"
                else:
                    f["sel_estado"] = "candidata"
            elif f.get("pin_hcp_local") is None:
                f["sel_estado"] = "sin Pinnacle de 3 h"
        anexar_registro(filas)
        resumenes.append((tipo, clave, filas, avisos))
        log(f"{tipo} {clave}: {len(filas)} juegos proyectados")
    return resumenes, nombres_qb


# --------------------------------------------------------------------------------------
# Salidas: hoja y Telegram
# --------------------------------------------------------------------------------------
def actualizar_hoja(hoja, g26, semana, nombres_qb, ahora):
    """Pestaña 'Semana N': una fila fija por juego (por hora de inicio). Reescribe A-M y Q-R con la última
    corrida de cada juego; nunca toca N-P (lo de Ozz)."""
    import polars as pl
    if hoja is None or semana is None:
        return
    t = pestana(semana)
    if t not in hoja.pestanas():
        crear_pestana(hoja, semana)
    jg = g26.filter(pl.col("week") == semana).sort(["inicio", "game_id"])
    claves = [r[0] if r else "" for r in hoja.leer(f"'{t}'!S5:S{FILAS_MAX}")]
    while claves and not claves[-1]:
        claves.pop()
    for gid in jg["game_id"].to_list():                 # juegos nuevos al final; nunca se reordena
        if gid not in claves:
            claves.append(gid)
    claves = claves[:FILAS_MAX - 4]
    info = {r["game_id"]: r for r in jg.iter_rows(named=True)}
    ult = {}
    for rr in leer_registro().filter(pl.col("semana") == str(semana)).iter_rows(named=True):
        ult[rr["game_id"]] = rr
    bloque, cola = [], []
    for gid in claves:
        g = info.get(gid)
        u = ult.get(gid)
        if g is None:
            bloque.append([""] * 13); cola.append(["", "", gid]); continue
        loc, vis = g["home_team"], g["away_team"]
        base = [fecha_cc(g["inicio"]), f"{vis} @ {loc}"]
        if not u:
            bloque.append(base + [linea_txt(loc, vis, -g["spread_line"] if g["spread_line"] is not None else None) + " (nflverse)"]
                          + [""] * 10)
            cola.append(["", "", gid]); continue
        ref = linea_txt(loc, vis, u["spread_ref"]) + (" (nflverse)" if u["ref_spread"] == "nflverse" else "")
        bloque.append(base + [ref, linea_txt(loc, vis, u["spread_modelo"]), dif_txt(loc, vis, u["spread_modelo"], u["spread_ref"]),
                              f"{float(u['nfl_total_line']):.1f}" if u["nfl_total_line"] else "", f"{float(u['total']):.1f}",
                              gana_txt(loc, vis, u["p_local"]), gana_txt(loc, vis, u["pin_p_ml_local"]),
                              senal_ml_txt(u), senal_sp_txt(u), wong_txt(u), estado_txt(u)])
        qb = (nombres_qb.get(u["qb_local_id"], u["qb_local_id"]) + (" (ajuste)" if u["qb_local_fuente"] == "ajuste" else "") + " / "
              + nombres_qb.get(u["qb_visita_id"], u["qb_visita_id"]) + (" (ajuste)" if u["qb_visita_fuente"] == "ajuste" else ""))
        cola.append([qb, f"{u['tipo']} {fecha_cc(t_utc(u['corrida_utc']), False)}", gid])
    n = len(claves)
    if n:
        hoja.escribir(f"'{t}'!A5:M{4 + n}", [["" if c is None else c for c in f] for f in bloque])
        hoja.escribir(f"'{t}'!Q5:S{4 + n}", [["" if c is None else c for c in f] for f in cola])
    hoja.escribir(f"'{t}'!A1:C1", [[f"Semana {semana} · NFL {TEMPORADA}", "",
                                    f"motor s2-v1 en modo registro (sin validar) · actualizado {fecha_cc(ahora)} (Caracas) · "
                                    f"líneas en convención de la casa: DAL -3.5 = DAL favorito por 3,5"
                                    + (" · semana informativa, fuera de 31A" if semana < SEMANA_31A else "")]])


def texto_telegram(resumenes):
    lin = []
    for tipo, clave, filas, avisos in resumenes:
        nombre = {"miercoles": "Miércoles 10:15", "sabado": "Sábado 10:15", "t85": "T−85", "reajuste": "Reajuste (cambio de QB)",
                  "manual": "Manual"}.get(tipo, tipo)
        sems = sorted({f["semana"] for f in filas})
        lin.append(f"MOTOR s2-v1 · {nombre} · semana {', '.join(map(str, sems))} · {len(filas)} juegos · sin validar (H29)")
        for f in filas:
            marca = "🔴 " if (f.get("marcado_spread") or f.get("marcado_total")) else ("🟢 " if f.get("sel_estado") == "candidata" else "")
            extra = [x for x in (senal_ml_txt(f), senal_sp_txt(f)) if x]
            w = wong_txt(f)
            lin.append(f"{marca}{f['visita']} @ {f['local']}: mercado {linea_txt(f['local'], f['visita'], f.get('spread_ref')) or '—'}"
                       f"{'*' if f.get('ref_spread') == 'nflverse' else ''} · modelo {linea_txt(f['local'], f['visita'], f['spread_modelo'])}"
                       f" · total {f['total']:.1f} (cons. {f.get('nfl_total_line')})"
                       + (f" · {'; '.join(extra)} [{f.get('sel_estado')}]" if extra else "")
                       + (f" · 🔵 Wong {w}" if w else ""))
        bs = [f for f in filas if f.get("bandera_sesgo")]
        if bs:
            lin.append(f"⚠️ Revisión de sesgo de la semana: spread {bs[0].get('sesgo_spread_semana')} / total {bs[0].get('sesgo_total_semana')}")
        lin += [f"Aviso: {a}" for a in avisos]
        lin.append("* = consenso de nflverse (no hay Pinnacle de ≤ 3 h). 🔴 revisar (modelo y mercado muy distintos) · 🟢 candidata del modelo · 🔵 pata Wong.")
        lin.append("")
    return "\n".join(lin).strip()


# --------------------------------------------------------------------------------------
# Principal
# --------------------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("modo", choices=["auto", "estado", "correr", "hoja-prueba"])
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
    g_all, g26 = calendario(6.0)
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

    ajustes, hoja_ok = {}, False

    def cargar_ajustes(semanas):
        nonlocal hoja_ok
        if hoja is None:
            return
        try:
            ajustes.update(leer_ajustes(hoja, semanas))
            hoja_ok = True
        except Exception as e:  # noqa: BLE001
            log(f"Hoja: no pude leer los ajustes ({type(e).__name__}); sigo sin ajustes")

    def fn_hash(ids):
        return hash_ajustes_de(ajustes, ids)

    def semanas_de(ids):
        return set(g26.filter(g26["game_id"].is_in(ids))["week"].to_list())

    if args.modo in ("auto", "estado"):
        lista, sem = tareas(g26, ahora, estado, None)
        ventana = grupos_en_ventana(g26, ahora, estado)
        # la hoja se lee solo si hay algo que correr o un grupo en la ventana de reajuste (T−90 al inicio)
        if lista or ventana or args.modo == "estado":
            sems = {s for _, (s, _) in ventana.items()} | {s for _, _, ids in lista for s in semanas_de(ids)} | ({sem} if sem else set())
            cargar_ajustes(sems)
            if hoja_ok:
                lista, sem = tareas(g26, ahora, estado, fn_hash)
        if args.modo == "estado":
            import polars as pl
            print(f"{VERSION_SEMANA} · ahora {fecha_cc(ahora)} Caracas · semana actual {sem}")
            n_reg = sum(1 for _ in open(REGISTRO)) - 1 if REGISTRO.exists() else 0
            print(f"Hoja: {'conectada' if hoja_ok else 'no configurada o sin acceso'} · registro: {n_reg} filas")
            print("Toca ahora:", [(t, c, len(i)) for t, c, i in lista] or "nada")
            if sem is not None:
                fut = g26.filter((pl.col("week") == sem) & (pl.col("inicio") > ahora)).sort("inicio")
                for (ini,), gr in fut.group_by(["inicio"], maintain_order=True):
                    print(f"  grupo {fecha_cc(ini)} Caracas: {gr.height} juegos · T−85 a las "
                          f"{(ini - dt.timedelta(minutes=MIN_T85)).astimezone(CARACAS).strftime('%H:%M')}"
                          f"{' (ya corrió)' if iso(ini) in estado['grupos'] else ''}")
            return
        if not lista:
            return                                         # nada que hacer: sale sin escribir en el log
    else:
        import polars as pl
        sem = args.semana or semana_actual(g26, ahora)
        ids = args.juegos.split(",") if args.juegos else g26.filter((pl.col("week") == sem) & (pl.col("inicio") > ahora))["game_id"].to_list()
        cargar_ajustes(semanas_de(ids) | {sem})
        lista = [(args.tipo, f"{args.tipo}-{iso(ahora)}", ids)]

    log(f"{VERSION_SEMANA}: corre {[(t, c, len(i)) for t, c, i in lista]}")
    g_all, g26 = calendario(1.0)                     # calendario fresco (QB titulares y líneas) antes de proyectar
    resumenes, nombres_qb = correr(lista, g_all, g26, args, ahora, ajustes)
    for tipo, clave, ids in lista:
        if tipo in ("miercoles", "sabado"):
            estado["fijas"][clave] = iso(ahora)
        elif tipo in ("t85", "reajuste"):
            estado["grupos"][clave] = iso(ahora)
            if hoja_ok:
                estado["hash_ajustes"][clave] = fn_hash(ids)
    guardar_estado(estado)
    if hoja is not None:
        sems = sorted({f["semana"] for _, _, filas, _ in resumenes for f in filas})
        for s_ in sems:
            try:
                actualizar_hoja(hoja, g26, s_, nombres_qb, ahora)
                log(f"hoja: pestaña {pestana(s_)} actualizada")
            except Exception as e:  # noqa: BLE001
                log(f"Hoja: error al escribir la pestaña {pestana(s_)} ({type(e).__name__}: {str(e)[:300]})")
    if resumenes and not args.sin_telegram:
        sys.path.insert(0, str(BASE))
        import sprint2 as s2
        s2.telegram(texto_telegram(resumenes))
    log("== LISTO")


if __name__ == "__main__":
    main()
