#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
estudio_e1.py — Estudio e1 (decisión 47; registro claude/registro_47_gemini_2025.md, escrito antes de cualquier consulta)

El agente Gemini revisa la temporada 2025 de la NFL para GENERAR IDEAS para s3. No valida nada. No toca s2-v1
(no importa sprint2.py), ni semana.py, ni 31A, ni 29A, ni la hoja, ni 2026. Solo lee datos y escribe en
salidas/estudio_e1/.

Pasos
  1. lista     : una consulta por partido de 2025 (285). Por equipo, C1-C8 «como se sabía 90 minutos antes del inicio»,
                 cada una con fuente, fecha de la fuente y confianza. No se le dice el resultado ni la línea.
  2. análisis  : control de filtración (fechas de las fuentes; diferencia de diferencias contra nflverse; contagio) y
                 exactitud contra nflverse.
  3. análisis  : efecto contra el cierre en las categorías no filtradas (permutación, IC por remuestreo, BH sobre todas
                 las pruebas; q < 0,20 = idea para F0, no validación).
  4. autopsia  : las sorpresas (|resultado − spread de cierre| ≥ 13) y el mismo número de controles al azar (semilla
                 fija): «¿qué explica el resultado?», verificado contra la jugada por jugada de 2025.
  5. resumen   : resumen.txt, CSV y zip; por Telegram.

Uso (desde ~/nfl_sim; siempre con prioridad baja)
  nice -n 10 venv/bin/python estudio_e1.py estado      (cuánto va, cuánto costó; no consulta nada)
  nice -n 10 venv/bin/python estudio_e1.py prueba      (2 partidos de la semana 1: unas 4 consultas; se guarda aparte)
  nohup nice -n 10 venv/bin/python estudio_e1.py todo > salidas/estudio_e1/todo.log 2>&1 &
       (lista + autopsia con tope de 300 consultas por día; al llegar al tope espera al día siguiente; al final
        analiza y manda el resumen y el zip por Telegram)
  nice -n 10 venv/bin/python estudio_e1.py lista | autopsia | analisis
Opciones: --sin-telegram · --sin-espera (no espera al día siguiente) · --forzar (analiza aunque falten consultas) ·
          --max N (como mucho N consultas en esta corrida)
"""
import argparse
import csv
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import sys
import threading
import time
import zipfile
from pathlib import Path
from zoneinfo import ZoneInfo

os.environ.setdefault("POLARS_MAX_THREADS", "2")   # servidor compartido: pocos hilos

VERSION_E1 = "estudio-e1 v1 (8-oct-2026)"
BASE = Path(__file__).resolve().parent
DATOS = BASE / "datos"                                # datos del motor: solo lectura
SAL = BASE / "salidas" / "estudio_e1"
SAL_DATOS = SAL / "datos"                             # lo que este estudio baja (nunca escribe en datos/)
SAL_PRUEBA = SAL / "prueba"
ESTADO = SAL / "estado.json"
LLAMADAS = SAL / "llamadas.csv"
RESP_LISTA = SAL / "respuestas_lista.jsonl"
RESP_AUTOPSIA = SAL / "respuestas_autopsia.jsonl"
LLAVE = BASE / "credenciales" / "gemini.key"
CONFIG_BOT = Path.home() / "nfl_ev" / "config.ini"   # solo lectura (token de Telegram)
CARACAS = ZoneInfo("America/Caracas")
NUEVA_YORK = ZoneInfo("America/New_York")

TEMPORADA = 2025
TOPE_DIA = 300                                        # [estudio_e1] aparte de semana.py y de parlays
HILOS = 8
PLAZO_LLAMADA_S = 240                                 # por consulta (no hay reloj de T−85 aquí)
MAX_FALLAS_SEGUIDAS = 10                              # algo sistemático: se detiene y avisa
MAX_DIAS_ESPERA = 4
JUEGOS_PRUEBA = ("2025_01_DAL_PHI", "2025_01_KC_LAC")
UMBRAL_SORPRESA = 13.0
N_BOOT = N_PERM = 10_000
SEMILLA_CONTROL, SEMILLA_BOOT, SEMILLA_PERM = 47, 4720251, 4720252
FILTRO_FECHAS = 0.10
Q_IDEA = 0.20
MIN_GRUPO = 20
MINUTOS_ANTES = 90
UMBRAL_C2 = 2                                         # bandera C2: 2 o más titulares fuera (ver registro 47, «Definiciones»)
UMBRAL_TITULAR = 0.50

URL_GAMES = "https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv"
URL_PBP = "https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{}.parquet"
URL_INJ = "https://github.com/nflverse/nflverse-data/releases/download/injuries/injuries_{}.csv"
URL_SNAPS = "https://github.com/nflverse/nflverse-data/releases/download/snap_counts/snap_counts_{}.csv"
URL_ROSTER = "https://github.com/nflverse/nflverse-data/releases/download/rosters/roster_{}.csv"

# --- Gemini: el mismo cliente y la misma forma de pedido que g1 (semana.py v6.1+) -----------------------------------
GEMINI_URL = os.environ.get("E1_GEMINI_URL", "https://generativelanguage.googleapis.com/v1beta")   # la variable solo se usa en pruebas con API simulada
GEMINI_MODELO = "gemini-3.5-flash-lite"
GEMINI_MAX_TOKENS = 16384
GEMINI_MIME = "APPLICATION_JSON"
PRECIO_ENTRADA, PRECIO_SALIDA = 0.30e-6, 2.50e-6
PREFIJO_BUSQUEDA = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/"
VARIANTES = {"e1": {"nivel": "medium", "esquema": True},          # la registrada
             "e1-texto": {"nivel": "medium", "esquema": False}}   # solo si Google rechaza el esquema (400) en el 1.er intento
CONFIANZAS = ("high", "medium", "low")
MOTIVACION = ("none", "eliminated", "clinched", "resting_starters")
RAZONES = ("turnovers", "in_game_injury", "def_st_td", "weather", "coach_decision", "other", "no_clear_reason")

EQUIPOS = {"ARI": "Arizona Cardinals", "ATL": "Atlanta Falcons", "BAL": "Baltimore Ravens", "BUF": "Buffalo Bills",
           "CAR": "Carolina Panthers", "CHI": "Chicago Bears", "CIN": "Cincinnati Bengals", "CLE": "Cleveland Browns",
           "DAL": "Dallas Cowboys", "DEN": "Denver Broncos", "DET": "Detroit Lions", "GB": "Green Bay Packers",
           "HOU": "Houston Texans", "IND": "Indianapolis Colts", "JAX": "Jacksonville Jaguars", "KC": "Kansas City Chiefs",
           "LA": "Los Angeles Rams", "LAC": "Los Angeles Chargers", "LV": "Las Vegas Raiders", "MIA": "Miami Dolphins",
           "MIN": "Minnesota Vikings", "NE": "New England Patriots", "NO": "New Orleans Saints", "NYG": "New York Giants",
           "NYJ": "New York Jets", "PHI": "Philadelphia Eagles", "PIT": "Pittsburgh Steelers", "SEA": "Seattle Seahawks",
           "SF": "San Francisco 49ers", "TB": "Tampa Bay Buccaneers", "TEN": "Tennessee Titans", "WAS": "Washington Commanders"}
RONDAS = {"WC": "wild-card round", "DIV": "divisional round", "CON": "conference championship", "SB": "Super Bowl"}
# huso horario estándar de la sede de cada equipo (C4: viaje de costa a costa = 3 husos o más)
HUSO = {**{t: -5 for t in ("ATL", "BAL", "BUF", "CAR", "CIN", "CLE", "DET", "IND", "JAX", "MIA", "NE", "NYG", "NYJ",
                           "PHI", "PIT", "TB", "WAS")},
        **{t: -6 for t in ("CHI", "DAL", "GB", "HOU", "KC", "MIN", "NO", "TEN")},
        "DEN": -7, "ARI": -7, **{t: -8 for t in ("LA", "LAC", "LV", "SEA", "SF")}}
HUSO_ESTADIO = {"Levi's Stadium": -8, "Caesars Superdome": -6, "Mercedes-Benz Stadium": -5, "SoFi Stadium": -8,
                "Allegiant Stadium": -8, "State Farm Stadium": -7, "Hard Rock Stadium": -5, "Raymond James Stadium": -5}
GRUPO_POS = {**{p: "ol" for p in ("T", "G", "C", "OT", "OG", "OL")},
             **{p: "skill" for p in ("WR", "TE", "RB", "FB", "HB")},
             **{p: "def" for p in ("DE", "DT", "NT", "LB", "ILB", "OLB", "MLB", "CB", "S", "FS", "SS", "DB", "DL", "EDGE")}}
CATS_EQUIPO = ("C1", "C2", "C4", "C5", "C6", "C7", "C8")
CATS_VERIFICABLES = ("C1", "C2", "C3", "C4", "C8")
NOMBRE_CAT = {"C1": "QB", "C2": "Bajas", "C3": "Clima", "C4": "Viaje y descanso", "C5": "Enfermedad",
              "C6": "Vestuario", "C7": "Motivación", "C8": "Regreso"}
FECHA_CAT = {"C1": "qb", "C2": "inj", "C3": "weather", "C4": "travel", "C5": "illness", "C6": "turmoil",
             "C7": "motivation", "C8": "return"}

_CANDADO_HILOS = threading.Lock()


# --------------------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------------------
def log(msg):
    print(f"[{dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC] {msg}", flush=True)


def iso(t):
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _texto(x):
    return "" if x is None else str(x).strip()


def _norm(nombre):
    """Nombre comparable: minúsculas, sin sufijos (Jr., III) ni signos."""
    n = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b\.?", "", _texto(nombre).lower())
    return re.sub(r"[^a-z]", "", n)


def md5(ruta):
    h = hashlib.md5()
    with open(ruta, "rb") as fh:
        for trozo in iter(lambda: fh.read(1 << 20), b""):
            h.update(trozo)
    return h.hexdigest()


def _num(x):
    try:
        v = float(x)
        return None if v != v else v
    except (TypeError, ValueError):
        return None


def _bool(x):
    if isinstance(x, bool):
        return x
    t = _texto(x).lower()
    if t in ("true", "yes", "1"):
        return True
    if t in ("false", "no", "0"):
        return False
    return None


def _ent(x):
    try:
        v = int(float(x))
        return v if 0 <= v <= 30 else None
    except (TypeError, ValueError):
        return None


def _fecha(x):
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", _texto(x))
    if not m:
        return None
    try:
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def pct(a, b):
    return f"{100 * a / b:.0f} %" if b else "—"


def num(x, d=1):
    if x is None:
        return "—"
    return f"{x:+.{d}f}".replace(".", ",")


def guardar_json(ruta, obj):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_suffix(ruta.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(ruta)


def leer_estado():
    try:
        return json.loads(ESTADO.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def hoy_caracas():
    return dt.datetime.now(CARACAS).date().isoformat()


def bajar(url, destino, minimo):
    """Descarga si falta. Datos de una temporada ya terminada: no se refrescan."""
    import requests
    if destino.exists() and destino.stat().st_size >= minimo:
        return True
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_suffix(destino.suffix + ".parcial")
    for intento in range(1, 4):
        try:
            with requests.get(url, stream=True, timeout=60) as r:
                r.raise_for_status()
                with open(tmp, "wb") as f:
                    for trozo in r.iter_content(1 << 20):
                        f.write(trozo)
            if tmp.stat().st_size < minimo:
                raise IOError("archivo incompleto")
            tmp.replace(destino)
            return True
        except Exception as e:  # noqa: BLE001
            log(f"descarga de {destino.name}, intento {intento}: {type(e).__name__}")
            time.sleep(5 * intento)
    return False


def archivo_dato(nombre, url, minimo, del_motor=True):
    """El archivo del motor (datos/, solo lectura) si existe; si no, lo baja a salidas/estudio_e1/datos/."""
    if del_motor and (DATOS / nombre).exists() and (DATOS / nombre).stat().st_size >= minimo:
        return DATOS / nombre
    destino = SAL_DATOS / nombre
    return destino if bajar(url, destino, minimo) else None


def telegram(texto, archivo=None):
    """Igual que sprint2.telegram (sin importarlo). Nunca muestra el token."""
    import configparser
    import requests
    if not CONFIG_BOT.exists():
        log("Telegram: no encontré ~/nfl_ev/config.ini; se omite el envío")
        return False
    cfg = configparser.ConfigParser()
    cfg.read(CONFIG_BOT)
    try:
        token = cfg["telegram"]["token"].strip()
        chat = cfg["telegram"]["chat_id"].strip()
    except KeyError:
        log("Telegram: config.ini sin [telegram] token/chat_id; se omite")
        return False
    url = f"https://api.telegram.org/bot{token}"
    ok = True
    try:
        for i in range(0, len(texto), 3800):
            r = requests.post(url + "/sendMessage", data={"chat_id": chat, "text": texto[i:i + 3800]}, timeout=30)
            ok &= r.ok
        if archivo:
            with open(archivo, "rb") as fh:
                r = requests.post(url + "/sendDocument", data={"chat_id": chat},
                                  files={"document": (Path(archivo).name, fh)}, timeout=120)
                ok &= r.ok
    except Exception as e:  # noqa: BLE001
        log(f"Telegram: error al enviar ({type(e).__name__})")
        return False
    log("Telegram: enviado" if ok else "Telegram: la API respondió con error")
    return ok


# --------------------------------------------------------------------------------------
# Datos de nflverse 2025 (solo lectura)
# --------------------------------------------------------------------------------------
def inicio_utc(gameday, gametime):
    h, m = (int(x) for x in str(gametime).split(":")[:2])
    y, mo, d = (int(x) for x in str(gameday).split("-"))
    return dt.datetime(y, mo, d, h, m, tzinfo=NUEVA_YORK).astimezone(dt.timezone.utc)


class Datos:
    """Todo lo de nflverse que usa el estudio, cargado una vez."""

    def __init__(self, con_detalle=True):
        import polars as pl
        self.huellas = {}
        p = archivo_dato("games.csv", URL_GAMES, 500_000)
        if p is None:
            raise SystemExit("No hay calendario de nflverse (games.csv)")
        self.huellas["games.csv"] = md5(p)
        g = pl.read_csv(p, infer_schema_length=20000).filter(pl.col("season") == TEMPORADA)
        juegos = []
        for r in g.to_dicts():
            sl, res = _num(r.get("spread_line")), _num(r.get("result"))
            if sl is None or res is None or sl == 0:
                continue
            ini = inicio_utc(r["gameday"], r["gametime"])
            juegos.append(dict(game_id=r["game_id"], semana=int(r["week"]), game_type=r.get("game_type") or "REG",
                               gameday=r["gameday"], inicio=ini, visita=r["away_team"], local=r["home_team"],
                               pts_visita=int(r["away_score"]), pts_local=int(r["home_score"]), result=res,
                               spread_line=sl, location=r.get("location") or "", roof=r.get("roof") or "",
                               stadium=r.get("stadium") or "", rest_visita=_num(r.get("away_rest")),
                               rest_local=_num(r.get("home_rest"))))
        juegos.sort(key=lambda j: (j["inicio"], j["game_id"]))
        self.juegos = juegos
        self.por_id = {j["game_id"]: j for j in juegos}
        self.orden = {}                                   # equipo → [game_id] en orden
        for j in juegos:
            for eq in (j["visita"], j["local"]):
                self.orden.setdefault(eq, []).append(j["game_id"])
        if con_detalle:
            self._detalle()

    # ---------------- detalle para el análisis ----------------
    def _detalle(self):
        import polars as pl
        rutas = dict(pbp=archivo_dato(f"pbp_{TEMPORADA}.parquet", URL_PBP.format(TEMPORADA), 5_000_000),
                     pbp_prev=archivo_dato(f"pbp_{TEMPORADA - 1}.parquet", URL_PBP.format(TEMPORADA - 1), 5_000_000),
                     inj=archivo_dato(f"injuries_{TEMPORADA}.csv", URL_INJ.format(TEMPORADA), 100_000, del_motor=False),
                     snaps=archivo_dato(f"snap_counts_{TEMPORADA}.csv", URL_SNAPS.format(TEMPORADA), 500_000, del_motor=False),
                     roster=archivo_dato(f"roster_{TEMPORADA}.csv", URL_ROSTER.format(TEMPORADA), 100_000, del_motor=False))
        faltan = [k for k, v in rutas.items() if v is None and k != "pbp_prev"]
        if faltan:
            raise SystemExit(f"Faltan datos de nflverse: {', '.join(faltan)}")
        for k, v in rutas.items():
            if v is not None:
                self.huellas[v.name] = md5(v)
        # roster: QB de 2025 y nombres
        ro = pl.read_csv(rutas["roster"], infer_schema_length=0)
        self.nombre = {r["gsis_id"]: _texto(r["full_name"]) for r in ro.select("gsis_id", "full_name").to_dicts() if r["gsis_id"]}
        self.qbs = {r["gsis_id"] for r in ro.filter(pl.col("position") == "QB").select("gsis_id").to_dicts() if r["gsis_id"]}
        # jugada por jugada 2025
        cols = ["game_id", "play_id", "posteam", "defteam", "qb_dropback", "passer_player_id", "rusher_player_id",
                "passer_player_name", "rusher_player_name", "interception", "fumble_lost", "touchdown", "td_team",
                "return_touchdown", "desc", "weather", "wind", "roof"]
        esquema = pl.read_parquet_schema(rutas["pbp"])
        pbp = pl.read_parquet(rutas["pbp"], columns=[c for c in cols if c in esquema])
        self.qb_inicial, self.nombre_qb = self._primer_dropback(pbp, self.qbs)
        self.qb_prev_temporada = {}
        if rutas["pbp_prev"] is not None:
            pp = pl.read_parquet(rutas["pbp_prev"], columns=[c for c in ("game_id", "play_id", "posteam", "qb_dropback",
                                                                           "passer_player_id", "rusher_player_id",
                                                                           "passer_player_name", "rusher_player_name")
                                                               if c in pl.read_parquet_schema(rutas["pbp_prev"])])
            q_prev, n_prev = self._primer_dropback(pp, None)
            ultimo = {}
            for (gid, eq), qb in sorted(q_prev.items()):
                ultimo[eq] = qb                                 # game_id ordena por semana
            self.qb_prev_temporada = ultimo
            for k, v in n_prev.items():
                self.nombre_qb.setdefault(k, v)
        # clima, balones, TD de defensa o equipos especiales, lesiones mencionadas
        self.clima = {}
        cc = [c for c in ("roof", "wind", "weather") if c in pbp.columns]
        for r in pbp.group_by("game_id").agg([pl.col(c).drop_nulls().first() for c in cc]).to_dicts():
            self.clima[r["game_id"]] = r
        self.balones, self.td_def = {}, {}
        for r in pbp.filter(pl.col("posteam").is_not_null()).group_by("game_id", "posteam").agg(
                (pl.col("interception").fill_null(0) + pl.col("fumble_lost").fill_null(0)).sum().alias("to")).to_dicts():
            self.balones[(r["game_id"], r["posteam"])] = int(r["to"])
        td = pbp.filter((pl.col("touchdown") == 1) & pl.col("td_team").is_not_null())
        cond = pl.col("td_team") != pl.col("posteam")
        if "return_touchdown" in td.columns:
            cond = cond | (pl.col("return_touchdown") == 1)
        for r in td.filter(cond).group_by("game_id", "td_team").agg(pl.col("play_id").count().alias("n")).to_dicts():
            self.td_def[(r["game_id"], r["td_team"])] = int(r["n"])
        self.lesionados = {}                               # (game_id, equipo) → {abreviatura}
        patron = re.compile(r"\b([A-Z]{2,3})-\d+-([A-Za-z][A-Za-z'.\- ]*?) was injured")
        for r in pbp.filter(pl.col("desc").str.contains("was injured")).select("game_id", "desc").to_dicts():
            for eq, ab in patron.findall(r["desc"] or ""):
                self.lesionados.setdefault((r["game_id"], eq), set()).add(ab.strip())
        # reporte de lesiones (estado final del partido)
        inj = pl.read_csv(rutas["inj"], infer_schema_length=0)
        self.reporte = {}                                  # (equipo, semana) → [dict]
        for r in inj.to_dicts():
            try:
                sem = int(r["week"])
            except (TypeError, ValueError):
                continue
            self.reporte.setdefault((r["team"], sem), []).append(
                dict(gsis=_texto(r.get("gsis_id")), nombre=_texto(r.get("full_name")), pos=_texto(r.get("position")),
                     estado=_texto(r.get("report_status"))))
        # jugadas por jugador (snaps): participación por partido
        sn = pl.read_csv(rutas["snaps"], infer_schema_length=0)
        self.part = {}                                     # (equipo, nombre_norm) → {game_id: participación}
        self.nombre_snap = {}
        for r in sn.to_dicts():
            o, d = _num(r.get("offense_pct")) or 0.0, _num(r.get("defense_pct")) or 0.0
            if (_num(r.get("offense_snaps")) or 0) + (_num(r.get("defense_snaps")) or 0) <= 0:
                continue
            k = (r["team"], _norm(r["player"]))
            self.part.setdefault(k, {})[r["game_id"]] = max(o, d)
            self.nombre_snap[k] = _texto(r["player"])
        self.part_eq = {}                                  # equipo → {nombre_norm: {game_id: participación}}
        for (t, k), v in self.part.items():
            self.part_eq.setdefault(t, {})[k] = v

    @staticmethod
    def _primer_dropback(pbp, qbs):
        """43: el QB del primer dropback de cada equipo (passer; en un scramble, rusher), que figure como QB en el roster
        si hay roster. {(game_id, equipo): gsis}, {gsis: nombre abreviado}."""
        import polars as pl
        d = (pbp.filter((pl.col("qb_dropback") == 1) & pl.col("posteam").is_not_null())
             .with_columns(pl.coalesce([pl.col("passer_player_id"), pl.col("rusher_player_id")]).alias("qb"),
                           pl.coalesce([pl.col("passer_player_name"), pl.col("rusher_player_name")]).alias("qbn"))
             .filter(pl.col("qb").is_not_null()))
        if qbs:
            d2 = d.filter(pl.col("qb").is_in(list(qbs)))
            if d2.height:
                d = d2
        d = d.sort("game_id", "play_id").group_by("game_id", "posteam", maintain_order=True).agg(
            pl.col("qb").first(), pl.col("qbn").first())
        out, nom = {}, {}
        for r in d.to_dicts():
            out[(r["game_id"], r["posteam"])] = r["qb"]
            nom[r["qb"]] = r["qbn"]
        return out, nom

    # ---------------- utilidades por equipo ----------------
    def previo(self, gid, eq, n=1):
        """game_id de los n partidos anteriores del equipo (el más reciente primero)."""
        o = self.orden.get(eq, [])
        i = o.index(gid)
        return list(reversed(o[max(0, i - n):i]))

    def titular_antes(self, eq, clave, gid):
        """Titular = participación media ≥ 50 % en sus partidos de 2025 con el equipo ANTES de este; si no jugó antes
        con el equipo, su media de toda la temporada con el equipo (definición de rol, no de resultado)."""
        part = self.part.get((eq, clave))
        if not part:
            return False
        o = self.orden.get(eq, [])
        i = o.index(gid)
        antes = [part[x] for x in o[:i] if x in part]
        base = antes if antes else list(part.values())
        return sum(base) / len(base) >= UMBRAL_TITULAR

    def clave_jugador(self, eq, nombre):
        k = (eq, _norm(nombre))
        return k[1] if k in self.part else None


def es_internacional(j):
    return j["location"] == "Neutral" and j["game_type"] != "SB"


def huso_sede(j):
    if j["location"] == "Neutral":
        return None if es_internacional(j) else HUSO_ESTADIO.get(j["stadium"])
    return HUSO.get(j["local"])


def lado_favorito(j):
    return j["local"] if j["spread_line"] > 0 else j["visita"]


def residuo_favorito(j):
    s = 1.0 if j["spread_line"] > 0 else -1.0
    return s * (j["result"] - j["spread_line"])


def residuo_equipo(j, eq):
    r = j["result"] - j["spread_line"]
    return r if eq == j["local"] else -r


# --------------------------------------------------------------------------------------
# Banderas de nflverse (contraparte verificable; definiciones en el registro 47, «Definiciones operativas»)
# --------------------------------------------------------------------------------------
RE_LLUVIA = re.compile(r"(?<!chance of )\b(rain|snow|shower|sleet|drizzle|flurr)", re.I)


def banderas_nflverse(D):
    eqs, juego = {}, {}
    for j in D.juegos:
        gid = j["game_id"]
        c = D.clima.get(gid) or {}
        techo = _texto(c.get("roof")) or j["roof"]
        afuera = techo in ("outdoors", "open")
        viento = _num(c.get("wind"))
        lluvia = bool(RE_LLUVIA.search(_texto(c.get("weather"))))
        juego[gid] = dict(c3=int(afuera and ((viento or 0) >= 15 or lluvia)), c3_viento=viento, c3_lluvia_nieve=int(lluvia),
                          c3_techo=techo)
        for eq in (j["visita"], j["local"]):
            rival = j["local"] if eq == j["visita"] else j["visita"]
            f = {}
            # C1: QB distinto al del partido anterior, o el QB anterior en el reporte final (Questionable/Doubtful/Out)
            qb = D.qb_inicial.get((gid, eq))
            prev = D.previo(gid, eq)
            qb_prev = D.qb_inicial.get((prev[0], eq)) if prev else D.qb_prev_temporada.get(eq)
            rep = D.reporte.get((eq, j["semana"]), [])
            en_rep = bool(qb_prev) and any(x["gsis"] == qb_prev and x["estado"] in ("Questionable", "Doubtful", "Out") for x in rep)
            if qb and qb_prev:
                f["c1_cambio"] = int(qb != qb_prev)
                f["c1_reporte"] = int(en_rep)
                f["c1"] = int(qb != qb_prev or en_rep)
            else:
                f["c1_cambio"] = f["c1_reporte"] = f["c1"] = None
            f["qb_real"] = D.nombre.get(qb) or D.nombre_qb.get(qb, "") if qb else ""
            f["qb_real_id"] = qb or ""
            # C2: titulares (sin QB, K, P, LS) Out o Doubtful en el reporte final
            n = {"ol": 0, "skill": 0, "def": 0}
            nombres = []
            for x in rep:
                gr = GRUPO_POS.get(x["pos"])
                if x["estado"] not in ("Out", "Doubtful") or gr is None:
                    continue
                k = D.clave_jugador(eq, x["nombre"])
                if k and D.titular_antes(eq, k, gid):
                    n[gr] += 1
                    nombres.append(x["nombre"])
            f.update(c2_ol=n["ol"], c2_skill=n["skill"], c2_def=n["def"], c2_n=sum(n.values()),
                     c2=int(sum(n.values()) >= UMBRAL_C2), c2_nombres="; ".join(nombres)[:200])
            # C4: semana corta (≤ 5 días), costa a costa (visitante, ≥ 3 husos), internacional
            rest = j["rest_visita"] if eq == j["visita"] else j["rest_local"]
            corta = int(rest is not None and rest <= 5)
            intl = int(es_internacional(j))
            hs = huso_sede(j)
            costa = int(not intl and hs is not None and eq != (j["local"] if j["location"] != "Neutral" else None)
                        and abs(HUSO[eq] - hs) >= 3)
            f.update(c4_corta=corta, c4_costa=costa, c4_intl=intl, c4=int(corta or costa or intl))
            # C8: vuelve un titular (≥ 50 % de media en 2 o más partidos previos con el equipo) que faltó a los 2
            # partidos anteriores del equipo figurando Out o Doubtful en el reporte de ambos, y juega este
            prev2 = D.previo(gid, eq, 2)
            vuelven = []
            if len(prev2) == 2:
                o = D.orden[eq]
                previos_eq = o[:o.index(gid)]
                sems = [D.por_id[p]["semana"] for p in prev2]
                for k, part in D.part_eq.get(eq, {}).items():
                    if gid not in part or any(p in part for p in prev2):
                        continue
                    antes = [part[x] for x in previos_eq if x in part]
                    if len(antes) < 2 or sum(antes) / len(antes) < UMBRAL_TITULAR:
                        continue
                    if all(any(_norm(x["nombre"]) == k and x["estado"] in ("Out", "Doubtful") for x in D.reporte.get((eq, s), []))
                           for s in sems):
                        vuelven.append(D.nombre_snap.get((eq, k), k))
            f.update(c8=int(bool(vuelven)), c8_jugadores="; ".join(vuelven)[:200])
            f["rival"] = rival
            eqs[(gid, eq)] = f
    return eqs, juego


def verificacion_autopsia(D, j):
    """Balones, TD de defensa o equipos especiales y lesiones durante el partido, según la jugada por jugada."""
    gid = j["game_id"]
    r = j["result"] - j["spread_line"]
    if r > 0:
        mejor, peor = j["local"], j["visita"]
    elif r < 0:
        mejor, peor = j["visita"], j["local"]
    else:
        mejor = peor = None
    to = {eq: D.balones.get((gid, eq), 0) for eq in (j["visita"], j["local"])}
    tdd = {eq: D.td_def.get((gid, eq), 0) for eq in (j["visita"], j["local"])}

    def lesion(eq):
        """Titular del equipo que jugó menos del 50 % y figura como «was injured» en la jugada por jugada."""
        abrevs = D.lesionados.get((gid, eq), set())
        if not abrevs:
            return []
        out = []
        for k, part in D.part_eq.get(eq, {}).items():
            if gid not in part or part[gid] >= UMBRAL_TITULAR or not D.titular_antes(eq, k, gid):
                continue
            nom = D.nombre_snap.get((eq, k), "")
            partes = nom.split()
            if len(partes) < 2:
                continue
            ini, resto = _norm(partes[0]), _norm(" ".join(partes[1:]))
            for ab in abrevs:
                if "." not in ab:
                    continue
                pre, ape = ab.split(".", 1)
                if _norm(ape) == resto and ini.startswith(_norm(pre)):
                    out.append(nom)
                    break
        return out

    if mejor:
        dif_to = to[peor] - to[mejor]
        les = lesion(peor)
        v = dict(v_balones=int(dif_to >= 2), v_td_def=int(tdd[mejor] > 0), v_lesion=int(bool(les)))
    else:
        dif_to = abs(to[j["visita"]] - to[j["local"]])
        les = lesion(j["visita"]) + lesion(j["local"])
        v = dict(v_balones=int(dif_to >= 2), v_td_def=int(sum(tdd.values()) > 0), v_lesion=int(bool(les)))
    v.update(v_dif_balones=dif_to, v_lesionados="; ".join(les)[:200], mejor_que_linea=mejor or "push")
    return v


# --------------------------------------------------------------------------------------
# Gemini: pedidos
# --------------------------------------------------------------------------------------
SISTEMA_LISTA = """You are a careful NFL research assistant with Google Search. Rules:
1. Answer AS OF 90 MINUTES BEFORE KICKOFF of the game given. Use ONLY information published before kickoff.
   Never use or mention the final score, the result, or any post-game report or recap.
2. Always search before answering, using at most 8 Google searches in total. Prefer the official final injury
   report, team announcements, NFL.com, ESPN and team beat reporters.
3. Fill every field for both teams and for the weather, using the team codes given. If you cannot find information
   for a field, answer false / 0 / "none" and leave its source_url and source_date as empty strings.
4. Each *_url must be a page that appeared in your search results; never build or guess a URL. Each *_date is that
   page's publication date (YYYY-MM-DD).
5. *_conf: "high" if official or several reliable sources agree; "medium" if one reliable source; "low" if unclear,
   conflicting or not found."""

USUARIO_LISTA = """Assume the current time is {t_et} ET ({t_utc} UTC): 90 minutes before kickoff.
NFL {temporada} {fase}. Game: {visita_nombre} ({visita}) at {local_nombre} ({local}){sede}, kickoff {inicio_et} ET.
For EACH team, as known before kickoff:
- C1 QB: qb_expected = the expected starting quarterback (full name). qb_changed = is he different from the QB who
  started the team's previous game (for the team's first game of the season, its last game of the previous season)?
  qb_uncertain = was the expected starter or the previous starter listed questionable, doubtful or out, or called a
  game-time decision?
- C2 Injuries: how many regular starters, NOT counting the quarterback, kicker or punter, were ruled OUT or listed
  DOUBTFUL on the final injury report for this game, by group: out_ol (offensive line), out_skill (RB, WR, TE),
  out_def (defense)?
- C4 Travel and rest: short_week = the team's previous game was 5 or fewer days earlier; cross_country = the team
  travels across 3 or more time zones for this game; international = the game is played outside the United States.
- C5 Illness: illness = was an illness or virus affecting several players reported?
- C6 Turmoil: turmoil = was there a suspension, a public conflict, a firing, or a change of offensive or defensive
  play-caller that week?
- C7 Motivation: motivation = "eliminated" (already out of playoff contention), "clinched" (playoff seed already
  locked), "resting_starters" (announced it will rest starters) or "none".
- C8 Return: returning = is a key regular starter returning in this game after missing the team's previous 2 or more
  games? returning_player = his name, or "" if none.
For the GAME:
- C3 Weather: wind_15 = forecast wind of 15 mph or more at kickoff; snow_or_heavy_rain = forecast snow or heavy rain;
  indoors = played in a dome or with the roof closed."""

SISTEMA_AUTOPSIA = """You explain, with Google Search, why an NFL game ended the way it did relative to the closing
point spread. Rules:
1. Always search game recaps, box scores and team reports before answering, using at most 4 Google searches.
2. Mark a reason true only if a source you found supports it. main_reason is the single most important one; use
   "no_clear_reason" if nothing beyond normal game variance explains the result.
3. Each *_url must be a page that appeared in your search results; never build or guess a URL. Leave it as an empty
   string when the reason is false. source_url is your main source (a recap of this game) and source_date its
   publication date (YYYY-MM-DD).
4. other = one short line with any other reason (empty string if none)."""

USUARIO_AUTOPSIA = """NFL {temporada} {fase}: {visita_nombre} ({visita}) at {local_nombre} ({local}), played on {fecha}.
Final score: {visita} {pts_visita}, {local} {pts_local}. Closing point spread: {favorito} -{linea}.
The favorite {verbo} the spread by {dif} points.
What explains the result relative to the spread? For each reason say true or false:
turnovers; in_game_injury (an important player injured during the game; name him in injury_player);
def_st_td (a defensive or special-teams touchdown); weather (weather during the game); coach_decision (a coaching
decision); and other (one line). Then give main_reason."""

SIN_ESQUEMA = "\nAnswer ONLY with one JSON object, with exactly these keys and value types, and nothing else:\n{forma}"


def _tipo_simple(p):
    t = p.get("type")
    if "enum" in p:
        return "|".join(p["enum"])
    return {"boolean": "true|false", "integer": "integer", "string": "text"}.get(t, t)


def esquema_equipo(eq):
    s = {"type": "string"}
    conf = {"type": "string", "enum": list(CONFIANZAS)}
    b = {"type": "boolean"}
    i = {"type": "integer", "description": "0 if none"}
    props = {"team": {"type": "string", "enum": [eq]},
             "qb_expected": s, "qb_changed": b, "qb_uncertain": b, "qb_conf": conf, "qb_url": s, "qb_date": s,
             "out_ol": i, "out_skill": i, "out_def": i, "inj_conf": conf, "inj_url": s, "inj_date": s,
             "short_week": b, "cross_country": b, "international": b, "travel_conf": conf, "travel_url": s, "travel_date": s,
             "illness": b, "illness_conf": conf, "illness_url": s, "illness_date": s,
             "turmoil": b, "turmoil_conf": conf, "turmoil_url": s, "turmoil_date": s,
             "motivation": {"type": "string", "enum": list(MOTIVACION)}, "motivation_conf": conf, "motivation_url": s,
             "motivation_date": s,
             "returning": b, "returning_player": s, "return_conf": conf, "return_url": s, "return_date": s}
    return {"type": "object", "properties": props, "required": list(props)}


def esquema_clima():
    s = {"type": "string"}
    b = {"type": "boolean"}
    props = {"wind_15": b, "snow_or_heavy_rain": b, "indoors": b,
             "weather_conf": {"type": "string", "enum": list(CONFIANZAS)}, "weather_url": s, "weather_date": s}
    return {"type": "object", "properties": props, "required": list(props)}


def esquema_lista(visita, local):
    return {"type": "object",
            "properties": {"away": esquema_equipo(visita), "home": esquema_equipo(local), "weather": esquema_clima()},
            "required": ["away", "home", "weather"]}


def esquema_autopsia():
    s = {"type": "string"}
    b = {"type": "boolean"}
    props = {"turnovers": b, "turnovers_url": s, "in_game_injury": b, "injury_player": s, "injury_url": s,
             "def_st_td": b, "def_st_td_url": s, "weather": b, "weather_url": s, "coach_decision": b, "coach_url": s,
             "other": s, "other_url": s, "main_reason": {"type": "string", "enum": list(RAZONES)},
             "confidence": {"type": "string", "enum": list(CONFIANZAS)}, "source_url": s, "source_date": s}
    return {"type": "object", "properties": props, "required": list(props)}


def forma_texto(esq):
    """El esquema escrito como ejemplo JSON (variante sin esquema)."""
    def f(e):
        if e.get("type") == "object":
            return {k: f(v) for k, v in e["properties"].items()}
        return _tipo_simple(e)
    return json.dumps(f(esq), ensure_ascii=False)


def _fmt_et(t):
    e = t.astimezone(NUEVA_YORK)
    return (f"{['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][e.weekday()]} "
            f"{['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][e.month - 1]} "
            f"{e.day}, {e.year}, {(e.hour % 12) or 12}:{e.minute:02d} {'AM' if e.hour < 12 else 'PM'}")


def _fase(j):
    return (f"regular season, week {j['semana']}" if j["game_type"] == "REG"
            else f"postseason, {RONDAS.get(j['game_type'], j['game_type'])}")


def pregunta_lista(j, variante):
    t = j["inicio"] - dt.timedelta(minutes=MINUTOS_ANTES)
    sede = " (neutral site)" if j["location"] == "Neutral" else ""
    txt = USUARIO_LISTA.format(t_et=_fmt_et(t), t_utc=t.strftime("%Y-%m-%d %H:%M"), temporada=TEMPORADA, fase=_fase(j),
                               visita_nombre=EQUIPOS.get(j["visita"], j["visita"]), visita=j["visita"],
                               local_nombre=EQUIPOS.get(j["local"], j["local"]), local=j["local"], sede=sede,
                               inicio_et=_fmt_et(j["inicio"]))
    if not VARIANTES[variante]["esquema"]:
        txt += SIN_ESQUEMA.format(forma=forma_texto(esquema_lista(j["visita"], j["local"])))
    return txt


def pregunta_autopsia(j, variante):
    fav = lado_favorito(j)
    r = residuo_favorito(j)
    verbo = "beat" if r > 0 else "failed to cover" if r < 0 else "pushed"
    txt = USUARIO_AUTOPSIA.format(temporada=TEMPORADA, fase=_fase(j), visita_nombre=EQUIPOS.get(j["visita"], j["visita"]),
                                  visita=j["visita"], local_nombre=EQUIPOS.get(j["local"], j["local"]), local=j["local"],
                                  fecha=j["gameday"], pts_visita=j["pts_visita"], pts_local=j["pts_local"], favorito=fav,
                                  linea=f"{abs(j['spread_line']):g}", verbo=verbo, dif=f"{abs(r):g}")
    if not VARIANTES[variante]["esquema"]:
        txt += SIN_ESQUEMA.format(forma=forma_texto(esquema_autopsia()))
    return txt


def cuerpo(fase, j, variante):
    v = VARIANTES[variante]
    gc = {"thinkingConfig": {"thinkingLevel": v["nivel"]}, "maxOutputTokens": GEMINI_MAX_TOKENS}
    if fase == "lista":
        sistema, pregunta, esq = SISTEMA_LISTA, pregunta_lista(j, variante), esquema_lista(j["visita"], j["local"])
    else:
        sistema, pregunta, esq = SISTEMA_AUTOPSIA, pregunta_autopsia(j, variante), esquema_autopsia()
    if v["esquema"]:
        gc["responseFormat"] = {"text": {"mimeType": GEMINI_MIME, "schema": esq}}
    return {"systemInstruction": {"parts": [{"text": sistema}]},
            "contents": [{"role": "user", "parts": [{"text": pregunta}]}],
            "tools": [{"google_search": {}}],
            "generationConfig": gc}


def huella(variante):
    """Huella de toda la configuración e1 (lo que se envía y cómo se lee). Cambia → configuración nueva."""
    v = VARIANTES[variante]
    cfg = dict(modelo=GEMINI_MODELO, via="generateContent", variante=variante, nivel=v["nivel"], esquema=v["esquema"],
               mime=GEMINI_MIME if v["esquema"] else "", sistemas=[SISTEMA_LISTA, SISTEMA_AUTOPSIA],
               usuarios=[USUARIO_LISTA, USUARIO_AUTOPSIA], sin_esquema=SIN_ESQUEMA if not v["esquema"] else "",
               esquemas=[json.dumps(esquema_lista("AAA", "BBB"), sort_keys=True), json.dumps(esquema_autopsia(), sort_keys=True)],
               herramientas=["google_search"], max_tokens=GEMINI_MAX_TOKENS, minutos_antes=MINUTOS_ANTES)
    return hashlib.md5(json.dumps(cfg, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:8]


# --------------------------------------------------------------------------------------
# Gemini: respuesta
# --------------------------------------------------------------------------------------
def _objeto_json(txt):
    txt = (txt or "").strip()
    try:
        v = json.loads(txt)
        return v if isinstance(v, dict) else None
    except ValueError:
        pass
    i = txt.find("{")
    while i != -1:
        for k in range(len(txt), i, -1):
            if txt[k - 1] == "}":
                try:
                    v = json.loads(txt[i:k])
                    if isinstance(v, dict):
                        return v
                except ValueError:
                    continue
        i = txt.find("{", i + 1)
    return None


def _conf(x):
    t = _texto(x).lower()
    return t if t in CONFIANZAS else ""


def leer_equipo(x, eq):
    """Objeto de un equipo → campos planos con prefijo. None si no es de ese equipo o le faltan los valores."""
    if not isinstance(x, dict) or _texto(x.get("team")).upper().replace("LAR", "LA").replace("WSH", "WAS") != eq:
        return None
    out = dict(qb_expected=_texto(x.get("qb_expected"))[:60], qb_changed=_bool(x.get("qb_changed")),
               qb_uncertain=_bool(x.get("qb_uncertain")), out_ol=_ent(x.get("out_ol")), out_skill=_ent(x.get("out_skill")),
               out_def=_ent(x.get("out_def")), short_week=_bool(x.get("short_week")),
               cross_country=_bool(x.get("cross_country")), international=_bool(x.get("international")),
               illness=_bool(x.get("illness")), turmoil=_bool(x.get("turmoil")),
               motivation=_texto(x.get("motivation")).lower() if _texto(x.get("motivation")).lower() in MOTIVACION else None,
               returning=_bool(x.get("returning")), returning_player=_texto(x.get("returning_player"))[:60])
    for pre in ("qb", "inj", "travel", "illness", "turmoil", "motivation", "return"):
        out[f"{pre}_conf"] = _conf(x.get(f"{pre}_conf"))
        out[f"{pre}_url"] = _texto(x.get(f"{pre}_url"))[:300]
        out[f"{pre}_date"] = _texto(x.get(f"{pre}_date"))[:10]
    valores = ("qb_changed", "qb_uncertain", "out_ol", "out_skill", "out_def", "short_week", "cross_country",
               "international", "illness", "turmoil", "motivation", "returning")
    out["completo"] = int(all(out[k] is not None for k in valores))
    return out


def leer_clima(x):
    if not isinstance(x, dict):
        return None
    out = dict(wind_15=_bool(x.get("wind_15")), snow_or_heavy_rain=_bool(x.get("snow_or_heavy_rain")),
               indoors=_bool(x.get("indoors")), weather_conf=_conf(x.get("weather_conf")),
               weather_url=_texto(x.get("weather_url"))[:300], weather_date=_texto(x.get("weather_date"))[:10])
    out["completo"] = int(all(out[k] is not None for k in ("wind_15", "snow_or_heavy_rain", "indoors")))
    return out


def leer_autopsia(x):
    if not isinstance(x, dict):
        return None
    out = {k: _bool(x.get(k)) for k in ("turnovers", "in_game_injury", "def_st_td", "weather", "coach_decision")}
    for k in ("turnovers_url", "injury_url", "def_st_td_url", "weather_url", "coach_url", "other_url", "source_url"):
        out[k] = _texto(x.get(k))[:300]
    out["injury_player"] = _texto(x.get("injury_player"))[:60]
    out["other"] = _texto(x.get("other"))[:200]
    mr = _texto(x.get("main_reason")).lower()
    out["main_reason"] = mr if mr in RAZONES else None
    out["confidence"] = _conf(x.get("confidence"))
    out["source_date"] = _texto(x.get("source_date"))[:10]
    out["completo"] = int(all(out[k] is not None for k in ("turnovers", "in_game_injury", "def_st_td", "weather",
                                                          "coach_decision", "main_reason")))
    return out


def leer_respuesta(fase, datos, j):
    """De la respuesta de generateContent: tokens, costo, búsquedas y la respuesta validada."""
    u = datos.get("usageMetadata") or {}
    out = dict(model_version=_texto(datos.get("modelVersion")),
               tok_entrada=int(u.get("promptTokenCount") or 0), tok_herramienta=int(u.get("toolUsePromptTokenCount") or 0),
               tok_salida=int(u.get("candidatesTokenCount") or 0), tok_razonamiento=int(u.get("thoughtsTokenCount") or 0))
    out["costo_usd"] = round((out["tok_entrada"] + out["tok_herramienta"]) * PRECIO_ENTRADA
                             + (out["tok_salida"] + out["tok_razonamiento"]) * PRECIO_SALIDA, 6)
    cand = (datos.get("candidates") or [{}])[0] or {}
    out["fin"] = _texto(cand.get("finishReason"))
    gm = cand.get("groundingMetadata") or {}
    consultas = sorted({_texto(q) for q in (gm.get("webSearchQueries") or []) if _texto(q)})
    out["busquedas"] = len(consultas)
    partes = ((cand.get("content") or {}).get("parts")) or []
    texto = "".join(p.get("text", "") for p in partes if isinstance(p, dict) and not p.get("thought"))
    obj = _objeto_json(texto)
    out["texto"] = texto[:6000]
    urls = []
    if fase == "lista":
        a = leer_equipo((obj or {}).get("away"), j["visita"])
        h = leer_equipo((obj or {}).get("home"), j["local"])
        w = leer_clima((obj or {}).get("weather"))
        out["valores"] = {"away": a, "home": h, "weather": w}
        partes_ok = [x for x in (a, h, w) if x and x["completo"]]
        for x in (a, h, w):
            for k, v in (x or {}).items():
                if k.endswith("_url") and v:
                    urls.append(v)
        if obj is None:
            out["estado"], out["detalle"] = "respuesta inválida", ("sin texto" if not texto else "no es JSON: " + texto[:150])
        elif len(partes_ok) == 3:
            out["estado"], out["detalle"] = "ok", ""
        elif partes_ok:
            out["estado"], out["detalle"] = "parcial", f"{len(partes_ok)} de 3 partes completas"
        else:
            out["estado"], out["detalle"] = "respuesta inválida", "JSON sin partes válidas"
    else:
        x = leer_autopsia(obj)
        out["valores"] = x
        for k, v in (x or {}).items():
            if k.endswith("_url") and v:
                urls.append(v)
        if obj is None:
            out["estado"], out["detalle"] = "respuesta inválida", ("sin texto" if not texto else "no es JSON: " + texto[:150])
        elif x and x["completo"]:
            out["estado"], out["detalle"] = "ok", ""
        else:
            out["estado"], out["detalle"] = "parcial", "faltan razones"
    meta = bool(consultas or (gm.get("groundingChunks") or []) or gm.get("searchEntryPoint"))
    out["urls"] = len(urls)
    out["urls_busqueda"] = sum(1 for x in urls if x.startswith(PREFIJO_BUSQUEDA))
    out["evidencia_busqueda"] = "metadatos" if meta else "enlace" if out["urls_busqueda"] else "ninguna"
    return out


def llamar(llave, fase, j, variante):
    """Una consulta. Nunca lanza excepciones ni registra la llave."""
    import requests
    t0 = time.time()
    try:
        r = requests.post(f"{GEMINI_URL}/models/{GEMINI_MODELO}:generateContent",
                          headers={"x-goog-api-key": llave, "Content-Type": "application/json"},
                          json=cuerpo(fase, j, variante), timeout=(10.0, PLAZO_LLAMADA_S))
    except requests.exceptions.Timeout:
        return {"estado": "tiempo agotado", "latencia_s": round(time.time() - t0, 2)}
    except Exception as e:  # noqa: BLE001 — solo el tipo: el texto podría traer datos de la conexión
        return {"estado": "error de red", "detalle": type(e).__name__, "latencia_s": round(time.time() - t0, 2)}
    lat = round(time.time() - t0, 2)
    if r.status_code != 200:
        try:
            msg = _texto(((r.json() or {}).get("error") or {}).get("message"))
        except Exception:  # noqa: BLE001
            msg = ""
        return {"estado": "error HTTP", "http": r.status_code, "detalle": msg[:300], "latencia_s": lat}
    try:
        datos = r.json()
    except ValueError:
        return {"estado": "respuesta inválida", "http": 200, "detalle": "la respuesta no es JSON", "latencia_s": lat}
    return {**leer_respuesta(fase, datos, j), "http": 200, "latencia_s": lat}


# --------------------------------------------------------------------------------------
# Consultas con tope diario, registro y reanudación
# --------------------------------------------------------------------------------------
CAMPOS_LLAMADAS = ["corrida_utc", "fase", "game_id", "intento", "variante", "huella", "modelo", "model_version", "estado",
                   "http", "latencia_s", "tok_entrada", "tok_herramienta", "tok_salida", "tok_razonamiento", "costo_usd",
                   "busquedas", "urls", "urls_busqueda", "evidencia_busqueda", "fin", "detalle"]


class Tope:
    """Tope de consultas por día de Caracas, guardado en estado.json después de cada reserva."""

    def __init__(self, tope, maximo=None):
        self.tope, self.maximo, self.usadas_corrida = tope, maximo, 0
        self.lock = threading.Lock()

    def usadas_hoy(self):
        return int(leer_estado().get("tope", {}).get(hoy_caracas(), 0))

    def reservar(self):
        with self.lock:
            if self.maximo is not None and self.usadas_corrida >= self.maximo:
                return False
            e = leer_estado()
            t = e.setdefault("tope", {})
            hoy = hoy_caracas()
            for k in [k for k in t if k != hoy]:
                e.setdefault("historial_tope", {})[k] = t.pop(k)
            if t.get(hoy, 0) >= self.tope:
                return False
            t[hoy] = t.get(hoy, 0) + 1
            guardar_json(ESTADO, e)
            self.usadas_corrida += 1
            return True


def anexar_csv(ruta, campos, fila):
    with _CANDADO_HILOS:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        nuevo = not ruta.exists()
        with open(ruta, "a", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=campos)
            if nuevo:
                w.writeheader()
            w.writerow({k: ("" if fila.get(k) is None else fila.get(k)) for k in campos})


def anexar_jsonl(ruta, obj):
    with _CANDADO_HILOS:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        with open(ruta, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")


def leer_jsonl(ruta):
    out = {}
    if ruta.exists():
        for linea in ruta.read_text(encoding="utf-8").splitlines():
            try:
                x = json.loads(linea)
                out[x["game_id"]] = x                         # la última manda
            except Exception:  # noqa: BLE001
                continue
    return out


def intentos_previos(ruta_llamadas, fase):
    n = {}
    if ruta_llamadas.exists():
        with open(ruta_llamadas, encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if r.get("fase") == fase and r.get("http") not in ("401", "403"):   # la llave no es culpa del modelo
                    n[r["game_id"]] = n.get(r["game_id"], 0) + 1
    return n


class Consultor:
    def __init__(self, tope, ruta_llamadas):
        self.tope = tope
        self.ruta_llamadas = ruta_llamadas
        self.abortar = ""
        self.fallas_seguidas = 0
        self.lock = threading.Lock()

    def intento(self, llave, fase, j, variante, n):
        if self.abortar:
            return None
        if not self.tope.reservar():
            return {"estado": "tope"}
        x = llamar(llave, fase, j, variante)
        fila = {k: x.get(k) for k in CAMPOS_LLAMADAS if k in x}
        fila.update(corrida_utc=iso(dt.datetime.now(dt.timezone.utc)), fase=fase, game_id=j["game_id"], intento=n,
                    variante=variante, huella=huella(variante), modelo=GEMINI_MODELO)
        anexar_csv(self.ruta_llamadas, CAMPOS_LLAMADAS, fila)
        if x.get("http") in (401, 403):
            self.abortar = f"Google rechazó la llave (HTTP {x['http']})"
        return x

    def procesar(self, llave, fase, j, previos, ruta_resp):
        """1.er intento con e1; si falla, UN reintento (e1-texto si Google rechazó el esquema con 400; si no, e1)."""
        gid = j["game_id"]
        if previos >= 2:
            final = {"estado": "falló", "detalle": "dos intentos en corridas anteriores"}
            n_int, variante = previos, "e1"
        else:
            variante = "e1"
            n_int = previos + 1
            x = self.intento(llave, fase, j, variante, n_int)
            if x is None or x["estado"] == "tope":
                return x["estado"] if x else "detenido"
            if x.get("http") in (401, 403):
                return "detenido"                          # problema de la llave: el partido queda pendiente
            if x["estado"] != "ok" and n_int < 2 and not self.abortar:
                if x.get("http") == 400:
                    variante = "e1-texto"
                elif x.get("http") == 429 or (x.get("http") or 0) >= 500 or x["estado"] in ("tiempo agotado", "error de red"):
                    time.sleep(15)
                n_int += 1
                y = self.intento(llave, fase, j, variante, n_int)
                if y is None or y["estado"] == "tope":
                    return y["estado"] if y else "detenido"
                if y.get("http") in (401, 403):
                    return "detenido"
                x = y
            final = x
        estado = final["estado"] if final["estado"] in ("ok", "parcial") else "falló"
        with self.lock:
            self.fallas_seguidas = 0 if estado != "falló" else self.fallas_seguidas + 1
            if self.fallas_seguidas >= MAX_FALLAS_SEGUIDAS and not self.abortar:
                self.abortar = f"{MAX_FALLAS_SEGUIDAS} partidos seguidos sin respuesta válida"
        anexar_jsonl(ruta_resp, dict(game_id=gid, fase=fase, estado=estado, intentos=n_int, variante=variante,
                                     huella=huella(variante), detalle=final.get("detalle", ""),
                                     estado_api=final["estado"], http=final.get("http"),
                                     costo_usd=final.get("costo_usd"), evidencia_busqueda=final.get("evidencia_busqueda"),
                                     valores=final.get("valores"), texto=final.get("texto", ""),
                                     registrado_utc=iso(dt.datetime.now(dt.timezone.utc))))
        return estado

    def tanda(self, fase, juegos, ruta_resp):
        """Consulta los juegos pendientes (8 a la vez). Devuelve {estado: n}."""
        from concurrent.futures import ThreadPoolExecutor
        if not LLAVE.exists():
            raise SystemExit("No encuentro credenciales/gemini.key: el agente está apagado")
        previos = intentos_previos(self.ruta_llamadas, fase)
        llave = LLAVE.read_text(encoding="utf-8").strip()
        cuenta = {}
        try:
            with ThreadPoolExecutor(max_workers=HILOS) as ex:
                futs = [ex.submit(self.procesar, llave, fase, j, previos.get(j["game_id"], 0), ruta_resp) for j in juegos]
                for f in futs:
                    try:
                        e = f.result()
                    except Exception as ex_:  # noqa: BLE001
                        e = f"excepción {type(ex_).__name__}"
                    cuenta[e] = cuenta.get(e, 0) + 1
        finally:
            del llave
        return cuenta


def pendientes(fase, juegos, ruta_resp):
    hechos = leer_jsonl(ruta_resp)
    return [j for j in juegos if j["game_id"] not in hechos]


def muestra_autopsia(D):
    """Las sorpresas (|resultado − spread| ≥ 13) y el mismo número de controles al azar entre el resto (semilla 47)."""
    import numpy as np
    sorpresas = sorted([j for j in D.juegos if abs(j["result"] - j["spread_line"]) >= UMBRAL_SORPRESA], key=lambda j: j["game_id"])
    resto = sorted([j for j in D.juegos if abs(j["result"] - j["spread_line"]) < UMBRAL_SORPRESA], key=lambda j: j["game_id"])
    rng = np.random.default_rng(SEMILLA_CONTROL)
    idx = sorted(rng.choice(len(resto), size=min(len(sorpresas), len(resto)), replace=False).tolist())
    control = [resto[i] for i in idx]
    return sorpresas, control


# --------------------------------------------------------------------------------------
# Estadística (todo vectorizado con NumPy; semillas fijas)
# --------------------------------------------------------------------------------------
def bh(ps):
    """q de Benjamini-Hochberg para una lista de p (None se deja como None)."""
    idx = [i for i, p in enumerate(ps) if p is not None]
    m = len(idx)
    q = [None] * len(ps)
    if not m:
        return q
    orden = sorted(idx, key=lambda i: ps[i])
    previo = 1.0
    for rango in range(m, 0, -1):
        i = orden[rango - 1]
        previo = min(previo, ps[i] * m / rango)
        q[i] = previo
    return q


def filtracion_dif(unidades, n_boot=N_BOOT, semilla=SEMILLA_BOOT):
    """Diferencia de diferencias. unidades = [(game_id, no_cubrio 0/1, bandera_gemini 0/1, bandera_nflverse 0/1)].
    dif = P(bandera | no cubrió) − P(bandera | cubrió), para Gemini y para nflverse; filtración = Gemini − nflverse.
    IC 95 % por remuestreo de PARTIDOS (los dos equipos de un partido salen juntos)."""
    import numpy as np
    juegos = sorted({u[0] for u in unidades})
    pos = {g: i for i, g in enumerate(juegos)}
    G = len(juegos)
    m = np.zeros((6, G))
    for gid, nc, bg, bn in unidades:
        k = pos[gid]
        m[0, k] += nc * bg; m[1, k] += nc; m[2, k] += (1 - nc) * bg; m[3, k] += (1 - nc)
        m[4, k] += nc * bn; m[5, k] += (1 - nc) * bn

    def calc(s):
        with np.errstate(invalid="ignore", divide="ignore"):
            dg = s[0] / s[1] - s[2] / s[3]
            dn = s[4] / s[1] - s[5] / s[3]
        return dg, dn, dg - dn

    tot = m.sum(axis=1)
    dg, dn, d = calc(tot)
    if G < 2:
        return dict(n=len(unidades), juegos=G, dif_gemini=dg, dif_nflverse=dn, filtracion=d, ic=(None, None))
    rng = np.random.default_rng(semilla)
    W = rng.multinomial(G, np.full(G, 1.0 / G), size=n_boot).astype(float)
    S = W @ m.T                                     # n_boot × 6
    _, _, db = calc(S.T)
    db = db[np.isfinite(db)]
    lo, hi = (float(np.percentile(db, 2.5)), float(np.percentile(db, 97.5))) if db.size else (None, None)
    return dict(n=len(unidades), juegos=G, dif_gemini=float(dg), dif_nflverse=float(dn), filtracion=float(d), ic=(lo, hi))


def prueba_grupo(a, b, n=N_PERM, semilla_b=SEMILLA_BOOT, semilla_p=SEMILLA_PERM):
    """Diferencia de residuo medio (a − b): IC 95 % por remuestreo de partidos dentro de cada grupo y p bilateral por
    permutación de etiquetas."""
    import numpy as np
    a, b = np.asarray(a, float), np.asarray(b, float)
    obs = float(a.mean() - b.mean())
    rb = np.random.default_rng(semilla_b)
    ma = a[rb.integers(0, a.size, (n, a.size))].mean(axis=1)
    mb = b[rb.integers(0, b.size, (n, b.size))].mean(axis=1)
    lo, hi = np.percentile(ma - mb, [2.5, 97.5])
    rp = np.random.default_rng(semilla_p)
    todo = np.concatenate([a, b])
    perm = rp.permuted(np.tile(todo, (n, 1)), axis=1)
    dp = perm[:, :a.size].mean(axis=1) - perm[:, a.size:].mean(axis=1)
    p = float((1 + np.sum(np.abs(dp) >= abs(obs) - 1e-12)) / (n + 1))
    return dict(dif=obs, ic=(float(lo), float(hi)), p=p)


# --------------------------------------------------------------------------------------
# Análisis
# --------------------------------------------------------------------------------------
def banderas_gemini(v, eq_lado):
    """Banderas por equipo desde la respuesta de la lista. None = sin dato."""
    x = (v or {}).get(eq_lado)
    if not x:
        return {}
    def o(*vals):
        if any(val is None for val in vals):
            return None
        return int(any(vals))
    n_out = None if any(x.get(k) is None for k in ("out_ol", "out_skill", "out_def")) else x["out_ol"] + x["out_skill"] + x["out_def"]
    return {"C1": o(x.get("qb_changed"), x.get("qb_uncertain")),
            "C2": None if n_out is None else int(n_out >= UMBRAL_C2),
            "C4": o(x.get("short_week"), x.get("cross_country"), x.get("international")),
            "C5": o(x.get("illness")), "C6": o(x.get("turmoil")),
            "C7": None if x.get("motivation") is None else int(x["motivation"] != "none"),
            "C8": o(x.get("returning")), "n_out": n_out}


def bandera_clima_gemini(v):
    w = (v or {}).get("weather")
    if not w or any(w.get(k) is None for k in ("wind_15", "snow_or_heavy_rain", "indoors")):
        return None
    return int((w["wind_15"] or w["snow_or_heavy_rain"]) and not w["indoors"])


def coincide_qb(nombre_g, nombre_real):
    a, b = _norm(nombre_g), _norm(nombre_real)
    if not a or not b:
        return None
    if a == b:
        return 1
    pg, pr = nombre_g.split(), re.split(r"[ .]", _texto(nombre_real))
    return int(bool(pg and pr) and _norm(pg[-1]) == _norm(pr[-1]) and _norm(pg[0])[:1] == _norm(pr[0])[:1])


def analizar(D, resp_lista, resp_autopsia):
    """Pasos 2, 3 y 4. Devuelve (filas_lista, filas_autopsia, pruebas, estado_cat, exactitud, tasas, contagio)."""
    nv_eq, nv_juego = banderas_nflverse(D)
    filas, unidades = [], {c: [] for c in CATS_VERIFICABLES}
    fechas = {c: [0, 0, 0, 0] for c in NOMBRE_CAT}           # con fecha, después, mismo día, sin fecha
    juegos_ok = [j for j in D.juegos if (resp_lista.get(j["game_id"]) or {}).get("estado") in ("ok", "parcial")]
    por_juego = {}
    exact = {k: [0, 0] for k in ("qb_nombre", "C1", "C2", "C3", "c4_corta", "c4_costa", "c4_intl", "C8")}
    tasas = {c: [0, 0, 0] for c in CATS_VERIFICABLES}        # n, Gemini sí, nflverse sí
    for j in D.juegos:
        gid = j["game_id"]
        r = resp_lista.get(gid) or {}
        v = r.get("valores") if r.get("estado") in ("ok", "parcial") else None
        dia = j["inicio"].astimezone(NUEVA_YORK).date()
        # C3 (por partido)
        bg3 = bandera_clima_gemini(v)
        bn3 = nv_juego[gid]["c3"]
        rf = residuo_favorito(j)
        if bg3 is not None:
            exact["C3"][0] += 1; exact["C3"][1] += int(bg3 == bn3)
            tasas["C3"][0] += 1; tasas["C3"][1] += bg3; tasas["C3"][2] += bn3
            if rf != 0:
                unidades["C3"].append((gid, int(rf < 0), bg3, bn3))
        if v and v.get("weather"):
            fd = _fecha(v["weather"].get("weather_date"))
            _contar_fecha(fechas["C3"], fd, dia)
        pj = {"C3": bg3}
        for lado, eq in (("away", j["visita"]), ("home", j["local"])):
            bg = banderas_gemini(v, lado) if v else {}
            nv = nv_eq[(gid, eq)]
            x = (v or {}).get(lado) or {}
            re_ = residuo_equipo(j, eq)
            fila = dict(game_id=gid, semana=j["semana"], game_type=j["game_type"], equipo=eq, rival=nv["rival"],
                        favorito=int(eq == lado_favorito(j)), spread_equipo=(-j["spread_line"] if eq == j["local"] else j["spread_line"]),
                        margen=(j["result"] if eq == j["local"] else -j["result"]), residuo=re_,
                        no_cubrio=(None if re_ == 0 else int(re_ < 0)), gemini_estado=r.get("estado", "sin consulta"))
            for c in CATS_EQUIPO:
                fila[f"g_{c}"] = bg.get(c)
            fila["g_C3"] = bg3
            fila.update(g_qb=x.get("qb_expected", ""), g_n_out=bg.get("n_out"), g_motivacion=x.get("motivation"),
                        g_regresa=x.get("returning_player", ""))
            for c in ("C1", "C2", "C4", "C8"):
                fila[f"n_{c}"] = nv[c.lower()]
            fila["n_C3"] = bn3
            fila.update(n_qb=nv["qb_real"], n_c1_cambio=nv["c1_cambio"], n_c1_reporte=nv["c1_reporte"], n_c2_n=nv["c2_n"],
                        n_c2_nombres=nv["c2_nombres"], n_c4_corta=nv["c4_corta"], n_c4_costa=nv["c4_costa"],
                        n_c4_intl=nv["c4_intl"], n_c8_jugadores=nv["c8_jugadores"])
            for c in CATS_EQUIPO:
                pre = FECHA_CAT[c]
                fd = _fecha(x.get(f"{pre}_date")) if x else None
                fila[f"fecha_{c}"] = x.get(f"{pre}_date", "") if x else ""
                fila[f"despues_{c}"] = None if fd is None else int(fd > dia)
                if x:
                    _contar_fecha(fechas[c], fd, dia)
            filas.append(fila)
            pj[eq] = bg
            # filtración y exactitud
            if bg and re_ != 0:
                for c in ("C1", "C2", "C4", "C8"):
                    if bg.get(c) is not None and nv[c.lower()] is not None:
                        unidades[c].append((gid, int(re_ < 0), bg[c], nv[c.lower()]))
            if bg:
                for c in ("C1", "C2", "C8"):
                    if bg.get(c) is not None and nv[c.lower()] is not None:
                        exact[c][0] += 1; exact[c][1] += int(bg[c] == nv[c.lower()])
                        tasas[c][0] += 1; tasas[c][1] += bg[c]; tasas[c][2] += nv[c.lower()]
                if bg.get("C4") is not None:
                    tasas["C4"][0] += 1; tasas["C4"][1] += bg["C4"]; tasas["C4"][2] += nv["c4"]
                for kg, kn in (("short_week", "c4_corta"), ("cross_country", "c4_costa"), ("international", "c4_intl")):
                    if x.get(kg) is not None:
                        exact[kn][0] += 1; exact[kn][1] += int(int(x[kg]) == nv[kn])
                cq = coincide_qb(x.get("qb_expected", ""), nv["qb_real"])
                if cq is not None:
                    exact["qb_nombre"][0] += 1; exact["qb_nombre"][1] += cq
        por_juego[gid] = pj

    # --- paso 2: filtración ---
    pruebas = []
    estado_cat = {}
    for c in NOMBRE_CAT:
        con, desp, mismo, sin = fechas[c]
        filtrada_fechas = con > 0 and desp / con >= FILTRO_FECHAS
        fila = dict(prueba="filtración", categoria=c, nombre=NOMBRE_CAT[c], fuentes_con_fecha=con, despues=desp,
                    mismo_dia=mismo, sin_fecha=sin, pct_despues=(desp / con if con else None),
                    filtrada_fechas=int(filtrada_fechas))
        if c in CATS_VERIFICABLES and len(unidades[c]) >= 2:
            f = filtracion_dif(unidades[c])
            lo, hi = f["ic"]
            # decisión de Ozz (8-oct, antes de correr): filtrada solo si Gemini se pega al resultado (IC > 0); si el IC
            # queda por debajo de 0 es «desacuerdo»: Gemini no mide bien esa categoría (no se prueba) y no contagia
            fila.update(n=f["n"], juegos=f["juegos"], dif_gemini=f["dif_gemini"], dif_nflverse=f["dif_nflverse"],
                        efecto=f["filtracion"], ic_lo=lo, ic_hi=hi, filtrada_dif=int(lo is not None and lo > 0),
                        desacuerdo=int(hi is not None and hi < 0))
        else:
            fila.update(filtrada_dif=None, desacuerdo=None)
        estado_cat[c] = ("filtrada" if (filtrada_fechas or fila.get("filtrada_dif"))
                         else "desacuerdo" if fila.get("desacuerdo") else "no filtrada")
        pruebas.append(fila)
    contagio = any(estado_cat[c] == "filtrada" for c in CATS_VERIFICABLES)
    for c in ("C5", "C6", "C7"):
        if contagio and estado_cat[c] != "filtrada":
            estado_cat[c] = "filtrada (contagio)"
    for fila in pruebas:
        fila["estado"] = estado_cat[fila["categoria"]]

    # --- paso 3: efecto contra el cierre (Gemini, categorías no filtradas) ---
    efectos = []
    for c in ("C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8"):
        grupos = {"favorito": [], "perro": [], "los dos": [], "ninguno": [], "con bandera": []}
        for j in juegos_ok:
            gid = j["game_id"]
            pj = por_juego[gid]
            rf = residuo_favorito(j)
            if c == "C3":
                b = pj.get("C3")
                if b is None:
                    continue
                grupos["con bandera" if b else "ninguno"].append(rf)
                continue
            fav = lado_favorito(j)
            perro = j["visita"] if fav == j["local"] else j["local"]
            bf, bp = (pj.get(fav) or {}).get(c), (pj.get(perro) or {}).get(c)
            if bf is None or bp is None:
                continue
            grupos["los dos" if bf and bp else "favorito" if bf else "perro" if bp else "ninguno"].append(rf)
        comparar = ("con bandera",) if c == "C3" else ("favorito", "perro")
        for gname in comparar + (("los dos",) if c != "C3" else ()):
            a, b = grupos[gname], grupos["ninguno"]
            fila = dict(prueba="efecto", categoria=c, nombre=NOMBRE_CAT[c], grupo=gname, n=len(a), n_ninguno=len(b),
                        residuo_medio=(sum(a) / len(a) if a else None),
                        residuo_ninguno=(sum(b) / len(b) if b else None),
                        cubre=(sum(1 for x in a if x > 0) / sum(1 for x in a if x != 0) if any(x != 0 for x in a) else None),
                        cubre_ninguno=(sum(1 for x in b if x > 0) / sum(1 for x in b if x != 0) if any(x != 0 for x in b) else None),
                        estado_categoria=estado_cat[c])
            if gname == "los dos":
                fila["nota"] = "se reporta, no se prueba"
            elif estado_cat[c] == "desacuerdo":
                fila["nota"] = "desacuerdo con nflverse: no se prueba"
            elif estado_cat[c] != "no filtrada":
                fila["nota"] = "categoría filtrada: no se prueba"
            elif len(a) < MIN_GRUPO or len(b) < MIN_GRUPO:
                fila["nota"] = f"menos de {MIN_GRUPO} partidos: no se prueba"
            else:
                t = prueba_grupo(a, b)
                fila.update(efecto=t["dif"], ic_lo=t["ic"][0], ic_hi=t["ic"][1], p=t["p"], nota="probada")
            efectos.append(fila)
    qs = bh([f.get("p") for f in efectos])
    for f, q in zip(efectos, qs):
        f["q"] = q
        f["idea_F0"] = int(q is not None and q < Q_IDEA)
    pruebas += efectos

    # --- paso 4: autopsia ---
    sorpresas, control = muestra_autopsia(D)
    filas_a = []
    for grupo, lista in (("sorpresa", sorpresas), ("control", control)):
        for j in lista:
            r = resp_autopsia.get(j["game_id"]) or {}
            v = r.get("valores") if r.get("estado") in ("ok", "parcial") else None
            ver = verificacion_autopsia(D, j)
            fila = dict(game_id=j["game_id"], grupo=grupo, semana=j["semana"], visita=j["visita"], local=j["local"],
                        marcador=f"{j['pts_visita']}-{j['pts_local']}", spread_line=j["spread_line"],
                        favorito=lado_favorito(j), residuo_favorito=residuo_favorito(j),
                        gemini_estado=r.get("estado", "sin consulta"))
            for k in ("turnovers", "in_game_injury", "def_st_td", "weather", "coach_decision"):
                fila[f"g_{k}"] = None if not v or v.get(k) is None else int(v[k])
            fila.update(g_principal=(v or {}).get("main_reason"), g_jugador=(v or {}).get("injury_player", ""),
                        g_otra=(v or {}).get("other", ""), g_fecha=(v or {}).get("source_date", ""),
                        g_confianza=(v or {}).get("confidence", ""))
            fila.update(ver)
            filas_a.append(fila)
    return filas, filas_a, pruebas, estado_cat, exact, tasas, contagio


def _contar_fecha(acum, fd, dia):
    if fd is None:
        acum[3] += 1
    else:
        acum[0] += 1
        if fd > dia:
            acum[1] += 1
        elif fd == dia:
            acum[2] += 1


def resumen_llamadas(ruta):
    out = dict(n=0, costo=0.0, por_fase={}, evidencia={}, por_estado={})
    if not ruta.exists():
        return out
    with open(ruta, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            out["n"] += 1
            out["costo"] += _num(r.get("costo_usd")) or 0.0
            out["por_fase"][r["fase"]] = out["por_fase"].get(r["fase"], 0) + 1
            out["por_estado"][r["estado"]] = out["por_estado"].get(r["estado"], 0) + 1
            if r["estado"] in ("ok", "parcial"):
                out["evidencia"][r.get("evidencia_busqueda", "")] = out["evidencia"].get(r.get("evidencia_busqueda", ""), 0) + 1
    return out


def texto_resumen(D, filas, filas_a, pruebas, estado_cat, exact, tasas, contagio, resp_lista, resp_autopsia):
    ll = resumen_llamadas(LLAMADAS)
    est_l = {}
    for r in resp_lista.values():
        est_l[r["estado"]] = est_l.get(r["estado"], 0) + 1
    est_a = {}
    for r in resp_autopsia.values():
        est_a[r["estado"]] = est_a.get(r["estado"], 0) + 1
    L = []
    L.append("ESTUDIO e1 (decisión 47) · Gemini sobre la temporada 2025 · SOLO GENERA IDEAS: NO VALIDA NADA")
    L.append(f"{VERSION_E1} · generado {iso(dt.datetime.now(dt.timezone.utc))} · modelo {GEMINI_MODELO} · "
             f"huella e1 {huella('e1')} (e1-texto {huella('e1-texto')})")
    L.append("Datos (md5): " + " · ".join(f"{k} {v[:8]}" for k, v in sorted(D.huellas.items())))
    L.append("")
    L.append("1. CONSULTAS")
    L.append(f"   Lista: {len(resp_lista)} de {len(D.juegos)} partidos · {conteo(est_l)}")
    sorp, ctrl = muestra_autopsia(D)
    L.append(f"   Autopsia: {len(resp_autopsia)} de {len(sorp) + len(ctrl)} ({len(sorp)} sorpresas + {len(ctrl)} controles) · "
             f"{conteo(est_a)}")
    L.append(f"   Consultas hechas: {ll['n']} ({conteo(ll['por_fase'])}) · {usd(ll['costo'])} · "
             f"evidencia de búsqueda en las que respondieron: {conteo(ll['evidencia'])}")
    L.append("")
    L.append("2. FILTRACIÓN (¿Gemini usa lo que pasó después del inicio?)")
    L.append("   Regla escrita antes: filtrada si ≥ 10 % de sus fuentes con fecha son posteriores al día del partido, o si")
    L.append("   el IC 95 % de (dif. Gemini − dif. nflverse) queda entero POR ENCIMA de 0 (Gemini se pega al resultado).")
    L.append("   dif = % con bandera entre los que NO cubrieron − % entre los que sí cubrieron. IC entero por debajo de 0 =")
    L.append("   «desacuerdo»: Gemini no mide bien esa categoría (no se prueba, no contagia). Si una verificable queda")
    L.append("   filtrada, C5-C7 también (contagio). Decisión de Ozz del 8-oct, antes de correr.")
    L.append(f"   {'Categoría':<20}{'fuentes':>8}{'después':>9}{'dif G':>8}{'dif N':>8}{'G − N [IC 95 %]':>24}  estado")
    for f in [p for p in pruebas if p["prueba"] == "filtración"]:
        ic = (f"{num(100 * f['efecto'], 0)} [{num(100 * f['ic_lo'], 0)}; {num(100 * f['ic_hi'], 0)}] pp"
              if f.get("ic_lo") is not None else "no verificable")
        dg = num(100 * f["dif_gemini"], 0) if f.get("dif_gemini") is not None else "—"
        dn = num(100 * f["dif_nflverse"], 0) if f.get("dif_nflverse") is not None else "—"
        L.append(f"   {f['categoria'] + ' ' + f['nombre']:<20}{f['fuentes_con_fecha']:>8}"
                 f"{pct(f['despues'], f['fuentes_con_fecha']):>9}{dg:>8}{dn:>8}{ic:>24}  {f['estado']}")
    L.append(f"   Contagio: {'sí — C5, C6 y C7 se tratan como filtradas' if contagio else 'no'}")
    L.append("")
    L.append("3. EXACTITUD (Gemini contra nflverse; las definiciones de nflverse están en el registro 47)")
    nombres_ex = {"qb_nombre": "C1 nombre del QB", "C1": "C1 bandera", "C2": "C2 bandera (≥ 2 titulares fuera)",
                  "C3": "C3 bandera", "c4_corta": "C4 semana corta", "c4_costa": "C4 costa a costa",
                  "c4_intl": "C4 internacional", "C8": "C8 bandera"}
    for k, (n, a) in exact.items():
        L.append(f"   {nombres_ex[k]:<34} coincide {pct(a, n):>5} (n {n})")
    L.append("   Tasa de la bandera, Gemini contra nflverse: " + " · ".join(
        f"{c} {pct(t[1], t[0])} vs {pct(t[2], t[0])}" for c, t in tasas.items()))
    pares = [(f["g_n_out"], f["n_c2_n"]) for f in filas if f.get("g_n_out") is not None]
    if pares:
        mg, mn = sum(a for a, _ in pares) / len(pares), sum(b for _, b in pares) / len(pares)
        exactos = sum(1 for a, b in pares if a == b)
        L.append(f"   C2 titulares fuera por equipo, media: Gemini {mg:.2f} vs nflverse {mn:.2f}".replace(".", ",")
                 + f" · mismo número en {pct(exactos, len(pares))}")
    L.append("")
    L.append("4. EFECTO CONTRA EL CIERRE (residuo del favorito = su margen − su spread de cierre; BH sobre todas las pruebas)")
    L.append(f"   {'Categoría / grupo':<30}{'n':>5}{'residuo':>9}{'vs ninguno [IC 95 %]':>26}{'cubre':>7}{'p':>7}{'q':>7}  nota")
    def dec3(x):
        return "" if x is None else f"{x:.3f}".replace(".", ",")

    for f in [p for p in pruebas if p["prueba"] == "efecto"]:
        ef = (f"{num(f['efecto'])} [{num(f['ic_lo'])}; {num(f['ic_hi'])}]" if f.get("efecto") is not None else "")
        cubre = pct(f["cubre"], 1) if f.get("cubre") is not None else "—"
        L.append(f"   {f['categoria'] + ' ' + f['grupo']:<30}{f['n']:>5}{num(f['residuo_medio']):>9}{ef:>26}"
                 f"{cubre:>7}{dec3(f.get('p')):>7}{dec3(f.get('q')):>7}  "
                 f"{'IDEA PARA F0 · ' if f.get('idea_F0') else ''}{f.get('nota', '')}")
    ideas = [f for f in pruebas if f.get("idea_F0")]
    L.append(f"   Ideas para F0 (q < {str(Q_IDEA).replace('.', ',')}): " +
             (", ".join(f"{f['categoria']} {f['nombre']} ({f['grupo']})" for f in ideas) if ideas else "ninguna"))
    L.append("")
    L.append("5. AUTOPSIA (explicación posterior: NUNCA es señal)")
    razones = (("turnovers", "Balones perdidos", "v_balones"), ("in_game_injury", "Lesión en el partido", "v_lesion"),
               ("def_st_td", "TD de defensa o especiales", "v_td_def"), ("weather", "Clima en el partido", None),
               ("coach_decision", "Decisión del coach", None))
    L.append(f"   {'Razón':<28}{'Gemini: sorpresas':>18}{'control':>9}{'nflverse: sorpresas':>21}{'control':>9}{'coincide':>10}")
    for k, nom, kv in razones:
        cells = []
        for fuente in ("g", "v"):
            if fuente == "v" and kv is None:
                cells += ["—", "—"]
                continue
            col = f"g_{k}" if fuente == "g" else kv
            for grupo in ("sorpresa", "control"):
                xs = [f[col] for f in filas_a if f["grupo"] == grupo and f.get(col) is not None
                      and (fuente == "v" or f["gemini_estado"] in ("ok", "parcial"))]
                cells.append(pct(sum(xs), len(xs)))
        if kv:
            pares = [(f[f"g_{k}"], f[kv]) for f in filas_a if f.get(f"g_{k}") is not None]
            co = pct(sum(1 for a, b in pares if a == b), len(pares))
        else:
            co = "—"
        L.append(f"   {nom:<28}{cells[0]:>18}{cells[1]:>9}{cells[2]:>21}{cells[3]:>9}{co:>10}")
    princ = {}
    for f in filas_a:
        if f.get("g_principal"):
            princ.setdefault(f["grupo"], {}).setdefault(f["g_principal"], 0)
            princ[f["grupo"]][f["g_principal"]] += 1
    L.append(f"   Razón principal según Gemini · sorpresas: {conteo(princ.get('sorpresa', {}))} · "
             f"control: {conteo(princ.get('control', {}))}")
    otras = [f"{f['game_id']}: {f['g_otra']}" for f in filas_a if f["grupo"] == "sorpresa" and f.get("g_otra")]
    L.append(f"   «Otra» en sorpresas ({len(otras)}; se agrupan a mano en la lista de ideas):")
    for o in otras[:40]:
        L.append(f"     · {o}")
    L.append("")
    L.append("6. QUÉ SE HACE CON ESTO (registro 47, paso 5)")
    L.append("   · Ideas medibles con nflverse → prueba en F0 con 2016-2022, con su regla escrita antes en el contexto y BH.")
    L.append("   · Ideas solo medibles con Gemini → no se prueban con datos viejos (filtración); requieren una decisión nueva")
    L.append("     de Ozz sobre un registro en vivo a T−85.")
    L.append("   · Nada cambia s2-v1, 31A ni 29A. Nada se mira en 2026 antes de congelar s3. Ningún dinero.")
    return "\n".join(L)


def conteo(d):
    return " · ".join(f"{k} {v}" for k, v in sorted(d.items(), key=lambda kv: -kv[1])) or "—"


def usd(x):
    return f"USD {x:.2f}".replace(".", ",")


def texto_telegram(D, pruebas, exact, estado_cat, contagio, filas_a, resp_lista, resp_autopsia):
    """Versión corta para leer en el teléfono; el detalle va en el zip."""
    ll = resumen_llamadas(LLAMADAS)
    sorp, ctrl = muestra_autopsia(D)
    ok_l = sum(1 for r in resp_lista.values() if r["estado"] == "ok")
    ok_a = sum(1 for r in resp_autopsia.values() if r["estado"] == "ok")
    filt = [c for c in NOMBRE_CAT if estado_cat[c] == "filtrada"]
    cont = [c for c in NOMBRE_CAT if estado_cat[c] == "filtrada (contagio)"]
    desac = [c for c in NOMBRE_CAT if estado_cat[c] == "desacuerdo"]
    libres = [c for c in NOMBRE_CAT if estado_cat[c] == "no filtrada"]
    L = ["e1 (decisión 47) · Gemini sobre 2025 · SOLO IDEAS, no valida nada",
         f"Consultas: lista {ok_l} ok de {len(D.juegos)} · autopsia {ok_a} ok de {len(sorp) + len(ctrl)} · {usd(ll['costo'])}",
         "Filtración: " + ((", ".join(f"{c} {NOMBRE_CAT[c]}" for c in filt) + " filtrada(s)") if filt
                           else "ninguna categoría filtrada")
         + (f"; {', '.join(cont)} por contagio" if cont else "")
         + (f". En desacuerdo con nflverse (no se prueban): {', '.join(desac)}" if desac else "")
         + f". Sin filtración: {', '.join(libres) or 'ninguna'}.",
         "Exactitud contra nflverse: " + " · ".join(f"{k.replace('qb_nombre', 'QB').replace('c4_', 'C4 ')} {pct(a, n)}"
                                                    for k, (n, a) in exact.items())]
    ideas = [f for f in pruebas if f.get("idea_F0")]
    L.append("Ideas para F0 (q < 0,20): " + (", ".join(
        f"{f['categoria']} {f['nombre']} ({f['grupo']}: {num(f['efecto'])} pts, q {f['q']:.2f})".replace(".", ",") for f in ideas)
        if ideas else "ninguna"))
    partes = []
    for k, nom, kv in (("turnovers", "balones", "v_balones"), ("def_st_td", "TD def/esp", "v_td_def"),
                       ("in_game_injury", "lesión", "v_lesion")):
        def tasa(col, grupo, solo_ok):
            xs = [f[col] for f in filas_a if f["grupo"] == grupo and f.get(col) is not None
                  and (not solo_ok or f["gemini_estado"] in ("ok", "parcial"))]
            return pct(sum(xs), len(xs))
        partes.append(f"{nom} {tasa('g_' + k, 'sorpresa', True)} vs {tasa('g_' + k, 'control', True)} "
                      f"(nflverse {tasa(kv, 'sorpresa', False)} vs {tasa(kv, 'control', False)})")
    L.append("Autopsia, Gemini en sorpresas vs control: " + " · ".join(partes))
    L.append("Todo el detalle en el zip (resumen.txt). Nada cambia s2-v1, 31A ni 29A.")
    return "\n".join(L)


def escribir_csv(ruta, filas):
    if not filas:
        return
    campos = []
    for f in filas:
        for k in f:
            if k not in campos:
                campos.append(k)
    with open(ruta, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=campos)
        w.writeheader()
        for f in filas:
            w.writerow({k: ("" if f.get(k) is None else f.get(k)) for k in campos})


def correr_analisis(D, sin_telegram, forzar):
    resp_lista, resp_autopsia = leer_jsonl(RESP_LISTA), leer_jsonl(RESP_AUTOPSIA)
    sorp, ctrl = muestra_autopsia(D)
    faltan_l = len(D.juegos) - len(resp_lista)
    faltan_a = len(sorp) + len(ctrl) - len(resp_autopsia)
    if (faltan_l or faltan_a) and not forzar:
        msg = f"Faltan consultas: lista {faltan_l}, autopsia {faltan_a}. Usa --forzar para analizar igual."
        log(msg)
        return msg
    filas, filas_a, pruebas, estado_cat, exact, tasas, contagio = analizar(D, resp_lista, resp_autopsia)
    texto = texto_resumen(D, filas, filas_a, pruebas, estado_cat, exact, tasas, contagio, resp_lista, resp_autopsia)
    corto = texto_telegram(D, pruebas, exact, estado_cat, contagio, filas_a, resp_lista, resp_autopsia)
    if faltan_l or faltan_a:
        texto = f"AVISO: análisis forzado con consultas pendientes (lista {faltan_l}, autopsia {faltan_a}).\n" + texto
    SAL.mkdir(parents=True, exist_ok=True)
    escribir_csv(SAL / "lista_2025.csv", filas)
    escribir_csv(SAL / "autopsia_2025.csv", filas_a)
    escribir_csv(SAL / "pruebas_2025.csv", pruebas)
    (SAL / "resumen.txt").write_text(texto + "\n", encoding="utf-8")
    zp = SAL / "e1_resultados.zip"
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        for nombre in ("resumen.txt", "lista_2025.csv", "autopsia_2025.csv", "pruebas_2025.csv", "llamadas.csv",
                       "respuestas_lista.jsonl", "respuestas_autopsia.jsonl"):
            if (SAL / nombre).exists():
                z.write(SAL / nombre, nombre)
    log(f"análisis listo: resumen.txt, lista_2025.csv, autopsia_2025.csv, pruebas_2025.csv, {zp.name}")
    if not sin_telegram:
        telegram(corto, zp)
    return texto + "\n\n--- Telegram ---\n" + corto


# --------------------------------------------------------------------------------------
# Modos
# --------------------------------------------------------------------------------------
def modo_estado(D):
    rl, ra = leer_jsonl(RESP_LISTA), leer_jsonl(RESP_AUTOPSIA)
    sorp, ctrl = muestra_autopsia(D)
    ll = resumen_llamadas(LLAMADAS)
    e = leer_estado()
    corriendo = False
    try:
        with open(SAL / ".candado", "w") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        corriendo = True
    L = [f"{VERSION_E1} · huella e1 {huella('e1')} · {'HAY UNA CORRIDA EN MARCHA' if corriendo else 'sin corrida en marcha'}",
         f"Partidos de {TEMPORADA} en el estudio: {len(D.juegos)} · sorpresas {len(sorp)} · controles {len(ctrl)}",
         f"Lista: {len(rl)} de {len(D.juegos)} hechos · Autopsia: {len(ra)} de {len(sorp) + len(ctrl)} hechos",
         f"Consultas: {ll['n']} ({conteo(ll['por_estado'])}) · {usd(ll['costo'])}",
         f"Hoy ({hoy_caracas()}, Caracas): {e.get('tope', {}).get(hoy_caracas(), 0)} de {TOPE_DIA} consultas usadas",
         f"Llave de Gemini: {'sí' if LLAVE.exists() else 'NO (credenciales/gemini.key)'}",
         f"Análisis: {'hecho (' + (SAL / 'resumen.txt').name + ')' if (SAL / 'resumen.txt').exists() else 'pendiente'}"]
    return "\n".join(L)


def modo_prueba(D, tope):
    """Primera corrida en la EC2: 2 partidos de la semana 1, lista y autopsia (unas 4 consultas). Se guarda aparte."""
    juegos = [D.por_id[g] for g in JUEGOS_PRUEBA if g in D.por_id]
    if len(juegos) < 2:
        juegos = [j for j in D.juegos if j["semana"] == 1][:2]
    rl, ra = SAL_PRUEBA / "respuestas_lista.jsonl", SAL_PRUEBA / "respuestas_autopsia.jsonl"
    for r in (rl, ra):
        if r.exists():
            r.rename(r.with_name(r.stem + f"_{int(time.time())}.jsonl"))
    ruta_ll = SAL_PRUEBA / "llamadas.csv"
    if ruta_ll.exists():
        ruta_ll.rename(ruta_ll.with_name(f"llamadas_{int(time.time())}.csv"))
    c = Consultor(tope, ruta_ll)
    t0 = time.time()
    cl = c.tanda("lista", juegos, rl)
    ca = c.tanda("autopsia", juegos, ra) if not c.abortar else {}
    dur = time.time() - t0
    L = [f"PRUEBA e1 · {VERSION_E1} · huella e1 {huella('e1')} · {len(juegos)} partidos · {dur:.0f} s",
         f"Lista: {cl} · Autopsia: {ca}" + (f" · DETENIDO: {c.abortar}" if c.abortar else "")]
    filas = []
    if ruta_ll.exists():
        with open(ruta_ll, encoding="utf-8") as fh:
            filas = list(csv.DictReader(fh))
    for f in filas:
        L.append(f"  {f['fase']:<9}{f['game_id']:<17} intento {f['intento']} {f['variante']:<9} {f['estado']:<18} "
                 f"http {f['http'] or '—':<4} {f['latencia_s']:>6} s · USD {(f['costo_usd'] or '0').replace('.', ',')} · "
                 f"evidencia {f['evidencia_busqueda'] or '—'} · urls {f['urls'] or 0} ({f['urls_busqueda'] or 0} de búsqueda)"
                 + (f" · {f['detalle'][:120]}" if f.get("detalle") else ""))
    for nombre, ruta in (("lista", rl), ("autopsia", ra)):
        for gid, r in leer_jsonl(ruta).items():
            v = r.get("valores") or {}
            if nombre == "lista":
                for lado in ("away", "home"):
                    x = v.get(lado) or {}
                    if x:
                        L.append(f"  {gid} {lado}: QB {x.get('qb_expected') or '—'} (cambio {x.get('qb_changed')}, dudoso "
                                 f"{x.get('qb_uncertain')}) · fuera OL/skill/def {x.get('out_ol')}/{x.get('out_skill')}/"
                                 f"{x.get('out_def')} · corta {x.get('short_week')} · costa {x.get('cross_country')} · intl "
                                 f"{x.get('international')} · enfermedad {x.get('illness')} · vestuario {x.get('turmoil')} · "
                                 f"motivación {x.get('motivation')} · regreso {x.get('returning')} {x.get('returning_player') or ''}"
                                 f" · fechas QB {x.get('qb_date') or '—'}, bajas {x.get('inj_date') or '—'}")
                w = v.get("weather") or {}
                if w:
                    L.append(f"  {gid} clima: viento≥15 {w.get('wind_15')} · nieve/lluvia {w.get('snow_or_heavy_rain')} · "
                             f"techado {w.get('indoors')} · fecha {w.get('weather_date') or '—'}")
            else:
                if v:
                    L.append(f"  {gid} autopsia: principal {v.get('main_reason')} · balones {v.get('turnovers')} · lesión "
                             f"{v.get('in_game_injury')} {v.get('injury_player') or ''} · TD def/esp {v.get('def_st_td')} · "
                             f"clima {v.get('weather')} · coach {v.get('coach_decision')} · otra «{v.get('other') or ''}»")
    # criterios de la prueba (escritos en el registro 47 antes de correrla)
    ok = [f for f in filas if f["estado"] in ("ok", "parcial")]
    finales = {**{("lista", g): r for g, r in leer_jsonl(rl).items()}, **{("autopsia", g): r for g, r in leer_jsonl(ra).items()}}
    n_ok = sum(1 for r in finales.values() if r["estado"] == "ok")
    costos = [_num(f["costo_usd"]) or 0.0 for f in ok]
    lat = [_num(f["latencia_s"]) or 0.0 for f in ok]
    evid = sum(1 for f in ok if f.get("evidencia_busqueda") in ("metadatos", "enlace"))
    T1 = n_ok == len(finales) == 2 * len(juegos)
    T2 = bool(ok) and evid == len(ok)
    T3 = bool(costos) and sum(costos) / len(costos) <= 0.015
    T4 = bool(lat) and max(lat) <= 180
    rechazos = sum(1 for f in filas if f["http"] == "400" and f["variante"] == "e1")
    T5 = rechazos == 0
    L.append(f"T1 respuestas completas (las 4 en «ok»): {'SÍ' if T1 else 'NO'} ({n_ok} de {2 * len(juegos)})")
    L.append(f"T2 evidencia de búsqueda en todas las que respondieron: {'SÍ' if T2 else 'NO'} ({evid} de {len(ok)})")
    L.append(f"T3 costo medio ≤ USD 0,015 por consulta: {'SÍ' if T3 else 'NO'} "
             f"(USD {((sum(costos) / len(costos)) if costos else 0):.4f})".replace(".", ","))
    L.append(f"T4 ninguna tarda más de 180 s: {'SÍ' if T4 else 'NO'} ({max(lat) if lat else 0:.0f} s)")
    L.append(f"T5 Google acepta el esquema (ningún 400 con e1): {'SÍ' if T5 else 'NO'} ({rechazos} rechazos)")
    versiones = sorted({f["model_version"] for f in filas if f.get("model_version")})
    L.append(f"Versión del modelo que respondió: {', '.join(versiones) or '—'}")
    L.append("RESULTADO DE LA PRUEBA: " + ("OK — se puede lanzar la corrida completa (modo todo)" if (T1 and T2 and T3 and T4 and T5)
                                         else "NO — mándale este texto a Claude antes de seguir"))
    txt = "\n".join(L)
    SAL_PRUEBA.mkdir(parents=True, exist_ok=True)
    (SAL_PRUEBA / "informe_prueba.txt").write_text(txt + "\n", encoding="utf-8")
    return txt


def esperar_manana():
    ahora = dt.datetime.now(CARACAS)
    manana = (ahora + dt.timedelta(days=1)).replace(hour=0, minute=5, second=0, microsecond=0)
    s = (manana - ahora).total_seconds()
    log(f"tope del día alcanzado: espero hasta {manana:%Y-%m-%d %H:%M} (Caracas), {s / 3600:.1f} h")
    time.sleep(max(s, 60))


def modo_consultas(D, fases, tope, sin_espera, sin_telegram):
    """lista y/o autopsia, reanudable; con espera al día siguiente si se llega al tope (salvo --sin-espera)."""
    sorp, ctrl = muestra_autopsia(D)
    objetivo = {"lista": (D.juegos, RESP_LISTA), "autopsia": (sorp + ctrl, RESP_AUTOPSIA)}
    dias = 0
    while True:
        c = Consultor(tope, LLAMADAS)
        resumen = []
        for fase in fases:
            juegos, ruta = objetivo[fase]
            pend = pendientes(fase, juegos, ruta)
            if not pend:
                continue
            log(f"{fase}: {len(pend)} partidos pendientes")
            cuenta = c.tanda(fase, pend, ruta)
            log(f"{fase}: {conteo(cuenta)}")
            resumen.append(f"{fase}: {conteo(cuenta)}")
            if c.abortar:
                break
        faltan = sum(len(pendientes(f, *objetivo[f])) for f in fases)
        if c.abortar:
            msg = f"e1: DETENIDO — {c.abortar}. Faltan {faltan} partidos. Mándale el log a Claude."
            log(msg)
            if not sin_telegram:
                telegram(msg)
            return False
        if not faltan:
            return True
        if tope.maximo is not None and tope.usadas_corrida >= tope.maximo:
            log(f"llegué al máximo de esta corrida ({tope.maximo}); faltan {faltan}")
            return False
        msg = (f"e1: tope de {TOPE_DIA} consultas del día. Hecho hoy: {'; '.join(resumen) or 'nada'}. "
               f"Faltan {faltan} partidos" + ("; sigo mañana a las 00:05 (Caracas)." if not sin_espera else "."))
        log(msg)
        if not sin_telegram:
            telegram(msg)
        if sin_espera or dias >= MAX_DIAS_ESPERA:
            return False
        dias += 1
        esperar_manana()
        tope.usadas_corrida = 0


def main():
    ap = argparse.ArgumentParser(description="Estudio e1 (decisión 47): Gemini sobre 2025, solo ideas")
    ap.add_argument("modo", choices=["estado", "prueba", "lista", "autopsia", "analisis", "todo"])
    ap.add_argument("--sin-telegram", action="store_true")
    ap.add_argument("--sin-espera", action="store_true")
    ap.add_argument("--forzar", action="store_true")
    ap.add_argument("--max", type=int)
    args = ap.parse_args()
    if os.nice(0) < 10:
        os.nice(10 - os.nice(0))
    SAL.mkdir(parents=True, exist_ok=True)
    if args.modo == "estado":                          # solo lectura: no necesita el candado
        print(modo_estado(Datos(con_detalle=False)))
        return 0
    candado = open(SAL / ".candado", "w")
    try:
        fcntl.flock(candado, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("Ya hay una corrida de estudio_e1.py en marcha (mira el avance con el modo estado).")
        return 1
    log(f"{VERSION_E1} · modo {args.modo}")
    tope = Tope(TOPE_DIA, args.max)
    if args.modo == "prueba":
        txt = modo_prueba(Datos(con_detalle=False), tope)
        print(txt)
        return 0 if "RESULTADO DE LA PRUEBA: OK" in txt else 2
    if args.modo in ("lista", "autopsia"):
        completo = modo_consultas(Datos(con_detalle=False), [args.modo], tope, True, args.sin_telegram)
        print(modo_estado(Datos(con_detalle=False)))
        return 0 if completo else 3
    if args.modo == "analisis":
        print(correr_analisis(Datos(), args.sin_telegram, args.forzar))
        return 0
    # todo
    completo = modo_consultas(Datos(con_detalle=False), ["lista", "autopsia"], tope, args.sin_espera, args.sin_telegram)
    if completo:
        print(correr_analisis(Datos(), args.sin_telegram, args.forzar))
        return 0
    print(modo_estado(Datos(con_detalle=False)))
    return 3


if __name__ == "__main__":
    sys.exit(main() or 0)
