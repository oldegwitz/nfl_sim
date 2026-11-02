#!/usr/bin/env python3
"""
tablero.py — decisión 58: tablero tipo PFF Pro / NFL Savant (DESCRIPTIVO).

Calcula con nflverse 2026 (temporada regular, semanas ya jugadas) y con los archivos del motor
(proyecciones_2026.csv, vigia_hechos.csv) las tablas que leen las pantallas de la hoja
«NFL Secret LAB — Tablero» (Partido, Equipo, Líderes, Jugador). Solo escribe las pestañas datos_*;
las pantallas son fórmulas que Claude mantiene con el conector. Nunca toca la hoja del motor.

No es un modelo: no cambia s2-v1, la proyección, 29A ni 31A. Ningún número es una «nota» ni una señal.

Uso (en ~/nfl_sim):
  venv/bin/python tablero.py              calcula y escribe la hoja (hoja_id en semana.ini [tablero])
  venv/bin/python tablero.py --local DIR  calcula y deja las tablas en DIR (CSV), sin tocar Google
  venv/bin/python tablero.py estado       configuración y última corrida
Lo llama semana.py (v8.4) al final de cada corrida, en un proceso aparte con límite de tiempo.
v1.2 (decisión 68): datos_equipos suma las métricas del briefing (briefing.py, las mismas de H44) con claves «eq_*» y su
puesto 1-32, más una fila «H44|eq_*» por métrica con su estabilidad (r y «se repite / a medias / casi suerte»). Si
briefing.py no está o falla, el tablero sale igual que en v1.1.
"""
from __future__ import annotations

import argparse
import configparser
import csv
import datetime as dt
import fcntl
import json
import math
import os
import sys
import time
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl

VERSION = "tablero-v1.2 (2-nov-2026)"  # v1.2: métricas del briefing (68) en datos_equipos · v1.1: etiqueta única por jugador y grupo (58) y puesto estable en los empates
TEMPORADA = 2026

BASE = Path(os.environ.get("NFL_SIM_BASE", str(Path.home() / "nfl_sim")))
CRED = BASE / "credenciales" / "google_sa.json"
INI = BASE / "semana.ini"
SEM = BASE / "salidas" / "semana"
CACHE = BASE / "datos" / "tablero"
SAL = BASE / "salidas" / "tablero"
LOG = SAL / "tablero.log"
CANDADO = SAL / ".candado"

URLS = {
    "pbp": (f"https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{TEMPORADA}.parquet", 1800),
    "snaps": (f"https://github.com/nflverse/nflverse-data/releases/download/snap_counts/snap_counts_{TEMPORADA}.parquet", 3600),
    "players": ("https://github.com/nflverse/nflverse-data/releases/download/players/players.parquet", 86400),
    "games": ("https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv", 1800),
}

ET = ZoneInfo("America/New_York")
CCS = ZoneInfo("America/Caracas")
TIPOS_QUE_CUENTAN = ("miercoles", "sabado", "t85")   # 37: las manuales y de Telegram no cuentan

EQUIPOS = {
    "ARI": ("Cardinals", "Arizona Cardinals"), "ATL": ("Falcons", "Atlanta Falcons"), "BAL": ("Ravens", "Baltimore Ravens"),
    "BUF": ("Bills", "Buffalo Bills"), "CAR": ("Panthers", "Carolina Panthers"), "CHI": ("Bears", "Chicago Bears"),
    "CIN": ("Bengals", "Cincinnati Bengals"), "CLE": ("Browns", "Cleveland Browns"), "DAL": ("Cowboys", "Dallas Cowboys"),
    "DEN": ("Broncos", "Denver Broncos"), "DET": ("Lions", "Detroit Lions"), "GB": ("Packers", "Green Bay Packers"),
    "HOU": ("Texans", "Houston Texans"), "IND": ("Colts", "Indianapolis Colts"), "JAX": ("Jaguars", "Jacksonville Jaguars"),
    "KC": ("Chiefs", "Kansas City Chiefs"), "LA": ("Rams", "Los Angeles Rams"), "LAC": ("Chargers", "Los Angeles Chargers"),
    "LV": ("Raiders", "Las Vegas Raiders"), "MIA": ("Dolphins", "Miami Dolphins"), "MIN": ("Vikings", "Minnesota Vikings"),
    "NE": ("Patriots", "New England Patriots"), "NO": ("Saints", "New Orleans Saints"), "NYG": ("Giants", "New York Giants"),
    "NYJ": ("Jets", "New York Jets"), "PHI": ("Eagles", "Philadelphia Eagles"), "PIT": ("Steelers", "Pittsburgh Steelers"),
    "SEA": ("Seahawks", "Seattle Seahawks"), "SF": ("49ers", "San Francisco 49ers"), "TB": ("Buccaneers", "Tampa Bay Buccaneers"),
    "TEN": ("Titans", "Tennessee Titans"), "WAS": ("Commanders", "Washington Commanders"),
}

# Métricas de equipo: clave, nombre en palabras, cómo se escribe, mejor ("alto", "bajo" o "identidad")
METRICAS_EQ = [
    ("off_epa_db", "Pase: puntos ganados por jugada (EPA por dropback)", "epa", "alto"),
    ("off_exito_pase", "Pase: jugadas que mantienen el ritmo (éxito)", "pct", "alto"),
    ("off_epa_corr", "Carrera: puntos ganados por jugada (EPA por corrida)", "epa", "alto"),
    ("off_exito_corr", "Carrera: jugadas que mantienen el ritmo (éxito)", "pct", "alto"),
    ("off_expl_pase", "Pases de 20 yardas o más", "pct", "alto"),
    ("off_expl_corr", "Corridas de 10 yardas o más", "pct", "alto"),
    ("off_golpe", "Su QB golpeado o capturado (sack)", "pct", "bajo"),
    ("off_frenadas", "Corridas frenadas en la línea (0 yardas o menos)", "pct", "bajo"),
    ("off_aly", "Yardas que gana la línea por corrida", "dec2", "alto"),
    ("off_pts", "Puntos a favor por partido", "dec1", "alto"),
    ("def_epa_db", "Pase rival: puntos que permite por jugada", "epa", "bajo"),
    ("def_exito_pase", "Pase rival: éxito que permite", "pct", "bajo"),
    ("def_epa_corr", "Carrera rival: puntos que permite por jugada", "epa", "bajo"),
    ("def_exito_corr", "Carrera rival: éxito que permite", "pct", "bajo"),
    ("def_expl_pase", "Pases de 20+ yardas que permite", "pct", "bajo"),
    ("def_expl_corr", "Corridas de 10+ yardas que permite", "pct", "bajo"),
    ("def_golpe", "QB rival golpeado o capturado (sack)", "pct", "alto"),
    ("def_frenadas", "Corridas rivales frenadas en la línea", "pct", "alto"),
    ("def_cpoe", "Precisión del QB rival sobre lo esperado (CPOE)", "dec1", "bajo"),
    ("def_pts", "Puntos en contra por partido", "dec1", "bajo"),
    ("id_proe", "Pasa más o menos de lo esperado (puntos %)", "dec1", "identidad"),
    ("id_jugadas", "Jugadas de ataque por partido", "dec1", "identidad"),
]

# Grupos de Líderes: (grupo, unidad de jugadas, mínimo por defecto, orden de M1, encabezados M1..M6, explicación, es_equipo)
GRUPOS = [
    ("QB", "dropbacks", 80, "desc",
     ["EPA por dropback", "Éxito %", "Precisión sobre lo esperado (CPOE)", "Profundidad media (yardas)", "Sacks %", "TD / INT"],
     "Ordenados por puntos ganados por jugada. El QB es la posición cuya estadística propia más se repite de un año a otro.", "no"),
    ("Pasadores", "snaps de defensa", 100, "desc",
     ["Golpe o sack cada 100 snaps", "Jugadas con golpe o sack", "Sacks", "Posición", "% de los snaps del equipo", "Golpes sin sack"],
     "Golpe o sack al QB (sin apuros: nflverse 2026 no trae presión). La presión es lo que más se repite en defensa.", "no"),
    ("Receptores", "objetivos", 15, "desc",
     ["EPA por objetivo", "% atrapados", "Yardas", "Yardas por objetivo", "TD", "Profundidad media"],
     "Descriptivo: depende mucho del QB y del esquema.", "no"),
    ("Corredores", "corridas", 25, "desc",
     ["EPA por corrida", "Éxito %", "Yardas", "Yardas por corrida", "Corridas de 10+ %", "TD"],
     "Descriptivo: depende mucho de la línea ofensiva.", "no"),
    ("Línea ofensiva", "jugadas", 0, "desc",
     ["Yardas de la línea por corrida", "QB golpeado o capturado %", "Corridas frenadas %", "Sacks permitidos", "EPA por corrida", "EPA por dropback"],
     "La línea como grupo (equipo): con datos gratuitos no se separa a cada linier.", "si"),
    ("Cobertura", "dropbacks rivales", 0, "asc",
     ["EPA por dropback permitido", "CPOE permitido", "Pases de 20+ permitidos %", "Intercepciones", "QB rival golpeado o capturado %", "Éxito de pase permitido %"],
     "La defensa de pase como grupo (equipo). Menos EPA permitido es mejor.", "si"),
]


# --------------------------------------------------------------------------------------------------------------------
# utilidades
# --------------------------------------------------------------------------------------------------------------------
def log(msg: str) -> None:
    linea = f"{dt.datetime.now(dt.timezone.utc):%Y-%m-%dT%H:%M:%SZ} {msg}"
    print(linea, flush=True)
    try:
        SAL.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(linea + "\n")
    except OSError:
        pass


def bajar(nombre: str) -> Path:
    url, edad_max = URLS[nombre]
    CACHE.mkdir(parents=True, exist_ok=True)
    destino = CACHE / url.rsplit("/", 1)[1]
    if destino.exists() and time.time() - destino.stat().st_mtime < edad_max:
        return destino
    tmp = destino.with_suffix(destino.suffix + ".tmp")
    for intento in (1, 2):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "nfl-secret-lab-tablero"})
            with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
                while True:
                    b = r.read(1 << 20)
                    if not b:
                        break
                    f.write(b)
            os.replace(tmp, destino)
            return destino
        except Exception as e:  # noqa: BLE001 — se registra el tipo y se reintenta una vez
            log(f"aviso: no pude bajar {nombre} (intento {intento}): {type(e).__name__}")
            time.sleep(2)
    if destino.exists():
        log(f"aviso: uso la copia anterior de {nombre}")
        return destino
    raise SystemExit(f"Sin datos de {nombre}: no se pudo bajar y no hay copia guardada.")


def r(x, n=3):
    if x is None:
        return None
    try:
        if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
            return None
    except TypeError:
        return None
    return round(float(x), n)


def coma(x: float, n: int) -> str:
    return f"{x:.{n}f}".replace(".", ",")


def texto(valor, forma: str) -> str:
    if valor is None:
        return "—"
    if forma == "epa":
        return ("+" if valor >= 0 else "−") + coma(abs(valor), 2)
    if forma == "pct":
        return f"{coma(valor, 1)} %"
    if forma == "dec2":
        return coma(valor, 2)
    if forma == "dec1":
        return ("−" if valor < 0 else "") + coma(abs(valor), 1)
    return str(valor)


def cuando_caracas(gameday: str, gametime: str) -> tuple[str, dt.datetime | None]:
    try:
        h, m = (int(x) for x in (gametime or "00:00").split(":"))
        d = dt.datetime.fromisoformat(gameday).replace(hour=h, minute=m, tzinfo=ET).astimezone(CCS)
    except (ValueError, TypeError):
        return gameday or "", None
    dias = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
    meses = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
    hora = d.strftime("%I:%M").lstrip("0") + (" am" if d.hour < 12 else " pm")
    return f"{dias[d.weekday()].capitalize()} {d.day} {meses[d.month - 1]} · {hora}", d


# --------------------------------------------------------------------------------------------------------------------
# lectura de datos
# --------------------------------------------------------------------------------------------------------------------
COLS_PBP = ["game_id", "week", "season_type", "posteam", "defteam", "home_team", "away_team", "pass", "rush", "qb_scramble",
            "pass_attempt", "complete_pass", "sack", "qb_hit", "epa", "success", "cpoe", "air_yards", "yards_gained",
            "pass_oe", "passer_player_id", "rusher_player_id", "receiver_player_id", "receiving_yards", "rushing_yards",
            "pass_touchdown", "rush_touchdown", "interception", "sack_player_id", "half_sack_1_player_id",
            "half_sack_2_player_id", "qb_hit_1_player_id", "qb_hit_2_player_id", "play_id"]


def leer_pbp() -> pl.DataFrame:
    p = pl.read_parquet(bajar("pbp"))
    faltan = [c for c in COLS_PBP if c not in p.columns]
    for c in faltan:
        p = p.with_columns(pl.lit(None).alias(c))
    p = p.select(COLS_PBP).filter(pl.col("season_type") == "REG")
    num = ["pass", "rush", "qb_scramble", "pass_attempt", "complete_pass", "sack", "qb_hit", "epa", "success", "cpoe",
           "air_yards", "yards_gained", "pass_oe", "receiving_yards", "rushing_yards", "pass_touchdown", "rush_touchdown",
           "interception"]
    return p.with_columns([pl.col(c).cast(pl.Float64, strict=False) for c in num])


def leer_games() -> pl.DataFrame:
    g = pl.read_csv(bajar("games"), infer_schema_length=0)
    g = g.filter((pl.col("season") == str(TEMPORADA)) & (pl.col("game_type") == "REG"))
    return g.with_columns([pl.col(c).cast(pl.Float64, strict=False) for c in ("week", "home_score", "away_score", "result",
                                                                                "spread_line", "total_line")])


def nombres_jugadores() -> tuple[dict, dict, dict]:
    pl_ = pl.read_parquet(bajar("players")).select("gsis_id", "display_name", "position", "pfr_id")
    nom = {a: b for a, b in zip(pl_["gsis_id"], pl_["display_name"]) if a}
    pos = {a: b for a, b in zip(pl_["gsis_id"], pl_["position"]) if a}
    pfr = {b: a for a, b in zip(pl_["gsis_id"], pl_["pfr_id"]) if a and b}
    return nom, pos, pfr


# --------------------------------------------------------------------------------------------------------------------
# equipos
# --------------------------------------------------------------------------------------------------------------------
def jugadas(p: pl.DataFrame) -> pl.DataFrame:
    return p.filter(pl.col("epa").is_not_null() & ((pl.col("pass") == 1) | (pl.col("rush") == 1)) & pl.col("posteam").is_not_null())


def aly(y: pl.Expr) -> pl.Expr:
    return (pl.when(y < 0).then(y * 1.2).when(y <= 4).then(y).when(y <= 10).then(4 + 0.5 * (y - 4)).otherwise(7.0))


def bloque_lado(j: pl.DataFrame, lado: str) -> pl.DataFrame:
    db = j.filter(pl.col("pass") == 1)
    ru = j.filter(pl.col("rush") == 1)
    a = db.group_by(lado).agg(
        pl.col("epa").mean().alias("epa_db"), pl.col("success").mean().alias("exito_pase"),
        (pl.col("yards_gained") >= 20).mean().alias("expl_pase"),
        ((pl.col("sack") == 1) | (pl.col("qb_hit") == 1)).mean().alias("golpe"),
        pl.col("cpoe").mean().alias("cpoe"), pl.col("interception").sum().alias("int"),
        pl.col("sack").sum().alias("sacks"), pl.len().alias("n_db"))
    b = ru.group_by(lado).agg(
        pl.col("epa").mean().alias("epa_corr"), pl.col("success").mean().alias("exito_corr"),
        (pl.col("yards_gained") >= 10).mean().alias("expl_corr"),
        (pl.col("yards_gained") <= 0).mean().alias("frenadas"), aly(pl.col("yards_gained")).mean().alias("aly"),
        pl.len().alias("n_corr"))
    return a.join(b, on=lado, how="full", coalesce=True).rename({lado: "equipo"})


def resultados_equipo(g: pl.DataFrame) -> dict:
    """Récord, contra la línea (cierre de nflverse), puntos y últimos partidos de cada equipo."""
    out = {t: dict(g=0, p=0, e=0, ag=0, ap=0, ae=0, pf=0.0, pc=0.0, n=0, ult=[]) for t in EQUIPOS}
    jugados = g.filter(pl.col("result").is_not_null()).sort("gameday", "gametime")
    for x in jugados.iter_rows(named=True):
        for eq, rival, pf, pc, local in ((x["home_team"], x["away_team"], x["home_score"], x["away_score"], True),
                                          (x["away_team"], x["home_team"], x["away_score"], x["home_score"], False)):
            if eq not in out:
                continue
            o = out[eq]
            o["n"] += 1
            o["pf"] += pf
            o["pc"] += pc
            o["g" if pf > pc else "p" if pf < pc else "e"] += 1
            if x["spread_line"] is not None:
                m = (x["result"] - x["spread_line"]) * (1 if local else -1)
                o["ag" if m > 0 else "ap" if m < 0 else "ae"] += 1
            res = "G" if pf > pc else "P" if pf < pc else "E"
            o["ult"].append(f"S{int(x['week'])} {res} {int(pf)}-{int(pc)} {'vs' if local else '@'} {rival}")
    return out


def tabla_equipos(p: pl.DataFrame, g: pl.DataFrame, nom: dict) -> tuple[list, list, dict]:
    j = jugadas(p)
    off = bloque_lado(j, "posteam")
    de = bloque_lado(j, "defteam")
    proe = j.filter(pl.col("pass_oe").is_not_null()).group_by("posteam").agg(pl.col("pass_oe").mean().alias("proe"))
    n_jug = j.group_by("posteam").agg(pl.len().alias("plays"), pl.col("game_id").n_unique().alias("pj"))
    res = resultados_equipo(g)

    # QB principal por equipo (más dropbacks)
    qb = j.filter(pl.col("pass") == 1).with_columns(
        pl.when(pl.col("qb_scramble") == 1).then(pl.col("rusher_player_id")).otherwise(pl.col("passer_player_id")).alias("qb"))
    qb = qb.filter(pl.col("qb").is_not_null()).group_by("posteam", "qb").agg(pl.len().alias("n")).sort("n", descending=True)
    qb_eq = {}
    for x in qb.iter_rows(named=True):
        qb_eq.setdefault(x["posteam"], nom.get(x["qb"], x["qb"]))

    O = {x["equipo"]: x for x in off.iter_rows(named=True)}
    D = {x["equipo"]: x for x in de.iter_rows(named=True)}
    P = {x["posteam"]: x["proe"] for x in proe.iter_rows(named=True)}
    N = {x["posteam"]: x for x in n_jug.iter_rows(named=True)}

    valores = {}
    for t in EQUIPOS:
        o, d, rr = O.get(t, {}), D.get(t, {}), res[t]
        pj = rr["n"] or None
        v = {
            "off_epa_db": o.get("epa_db"), "off_exito_pase": _pct(o.get("exito_pase")), "off_epa_corr": o.get("epa_corr"),
            "off_exito_corr": _pct(o.get("exito_corr")), "off_expl_pase": _pct(o.get("expl_pase")),
            "off_expl_corr": _pct(o.get("expl_corr")), "off_golpe": _pct(o.get("golpe")), "off_frenadas": _pct(o.get("frenadas")),
            "off_aly": o.get("aly"), "off_pts": rr["pf"] / pj if pj else None,
            "def_epa_db": d.get("epa_db"), "def_exito_pase": _pct(d.get("exito_pase")), "def_epa_corr": d.get("epa_corr"),
            "def_exito_corr": _pct(d.get("exito_corr")), "def_expl_pase": _pct(d.get("expl_pase")),
            "def_expl_corr": _pct(d.get("expl_corr")), "def_golpe": _pct(d.get("golpe")), "def_frenadas": _pct(d.get("frenadas")),
            "def_cpoe": d.get("cpoe"), "def_pts": rr["pc"] / pj if pj else None,
            "id_proe": P.get(t), "id_jugadas": (N[t]["plays"] / N[t]["pj"]) if t in N and N[t]["pj"] else None,
        }
        valores[t] = v

    filas_largo = []
    for clave, _nombre, forma, mejor in METRICAS_EQ:
        orden = sorted((t for t in EQUIPOS if valores[t][clave] is not None),
                       key=lambda t: valores[t][clave], reverse=(mejor != "bajo"))
        puesto, prev = {}, None
        for i, t in enumerate(orden, 1):
            v = valores[t][clave]
            puesto[t] = puesto[orden[i - 2]] if prev is not None and v == prev else i
            prev = v
        for t in EQUIPOS:
            v = valores[t][clave]
            filas_largo.append([f"{t}|{clave}", t, clave, r(v, 4), puesto.get(t), texto(r(v, 4), forma)])

    filas_lista = []
    for t, (corto, largo) in EQUIPOS.items():
        rr = res[t]
        rec = f"{rr['g']}-{rr['p']}" + (f"-{rr['e']}" if rr["e"] else "")
        ats = f"{rr['ag']}-{rr['ap']}" + (f"-{rr['ae']}" if rr["ae"] else "")
        ult = " · ".join(reversed(rr["ult"][-4:])) or "sin partidos"
        filas_lista.append([f"{corto} ({t})", t, corto, largo, rec, ats, qb_eq.get(t, "—"), ult, rr["n"]])
    filas_lista.sort(key=lambda x: x[2])
    return filas_largo, filas_lista, valores


def _pct(x):
    return None if x is None else 100.0 * x


# --------------------------------------------------------------------------------------------------------------------
# jugadores y grupos (Líderes y Jugador)
# --------------------------------------------------------------------------------------------------------------------
def _rival(df: pl.DataFrame, lado: str) -> pl.DataFrame:
    otro = "defteam" if lado == "posteam" else "posteam"
    return df.with_columns(
        pl.when(pl.col("home_team") == pl.col(lado)).then(pl.lit("vs ") + pl.col(otro)).otherwise(pl.lit("@ ") + pl.col(otro))
        .alias("rival"))


def metricas_qb(j: pl.DataFrame, por: list[str]) -> pl.DataFrame:
    db = j.filter(pl.col("pass") == 1).with_columns(
        pl.when(pl.col("qb_scramble") == 1).then(pl.col("rusher_player_id")).otherwise(pl.col("passer_player_id")).alias("clave"))
    db = db.filter(pl.col("clave").is_not_null())
    return db.group_by(["clave"] + por).agg(
        pl.len().alias("jugadas"), pl.col("posteam").last().alias("equipo"),
        pl.col("epa").mean().alias("M1"), (pl.col("success").mean() * 100).alias("M2"), pl.col("cpoe").mean().alias("M3"),
        pl.col("air_yards").filter(pl.col("pass_attempt") == 1).mean().alias("M4"), (pl.col("sack").mean() * 100).alias("M5"),
        pl.col("pass_touchdown").sum().alias("td"), pl.col("interception").sum().alias("int"))


def metricas_receptor(j: pl.DataFrame, por: list[str]) -> pl.DataFrame:
    t = j.filter((pl.col("pass_attempt") == 1) & pl.col("receiver_player_id").is_not_null()).rename({"receiver_player_id": "clave"})
    return t.group_by(["clave"] + por).agg(
        pl.len().alias("jugadas"), pl.col("posteam").last().alias("equipo"), pl.col("epa").mean().alias("M1"),
        (pl.col("complete_pass").mean() * 100).alias("M2"), pl.col("receiving_yards").fill_null(0).sum().alias("M3"),
        (pl.col("receiving_yards").fill_null(0).sum() / pl.len()).alias("M4"), pl.col("pass_touchdown").sum().alias("M5"),
        pl.col("air_yards").mean().alias("M6"))


def metricas_corredor(j: pl.DataFrame, por: list[str]) -> pl.DataFrame:
    c = j.filter((pl.col("rush") == 1) & pl.col("rusher_player_id").is_not_null()).rename({"rusher_player_id": "clave"})
    return c.group_by(["clave"] + por).agg(
        pl.len().alias("jugadas"), pl.col("posteam").last().alias("equipo"), pl.col("epa").mean().alias("M1"),
        (pl.col("success").mean() * 100).alias("M2"), pl.col("rushing_yards").fill_null(0).sum().alias("M3"),
        (pl.col("rushing_yards").fill_null(0).sum() / pl.len()).alias("M4"),
        ((pl.col("yards_gained") >= 10).mean() * 100).alias("M5"), pl.col("rush_touchdown").sum().alias("M6"))


def eventos_pasador(j: pl.DataFrame) -> pl.DataFrame:
    """Una fila por jugada y defensor que golpeó o capturó al QB (sin contar dos veces la misma jugada)."""
    db = j.filter(pl.col("pass") == 1)
    partes = []
    for col, peso_sack in (("sack_player_id", 1.0), ("half_sack_1_player_id", 0.5), ("half_sack_2_player_id", 0.5),
                           ("qb_hit_1_player_id", 0.0), ("qb_hit_2_player_id", 0.0)):
        partes.append(db.filter(pl.col(col).is_not_null()).select(
            pl.col(col).alias("clave"), "game_id", "play_id", "week", "defteam", "home_team", "posteam",
            pl.lit(peso_sack).alias("sack_w")))
    ev = pl.concat(partes)
    return ev.group_by("clave", "game_id", "play_id").agg(
        pl.col("week").first(), pl.col("defteam").first(), pl.col("home_team").first(), pl.col("posteam").first(),
        pl.col("sack_w").max())


def snaps_def(pfr2gsis: dict) -> pl.DataFrame:
    s = pl.read_parquet(bajar("snaps")).filter(pl.col("game_type") == "REG")
    s = s.with_columns(pl.col("pfr_player_id").replace_strict(pfr2gsis, default=None).alias("clave"),
                       pl.col("defense_snaps").cast(pl.Float64), pl.col("defense_pct").cast(pl.Float64))
    return s.filter(pl.col("clave").is_not_null() & (pl.col("defense_snaps") > 0))


def tabla_grupos(p: pl.DataFrame, g: pl.DataFrame, valores_eq: dict, nom: dict, pos: dict, pfr2gsis: dict):
    j = jugadas(p)
    jr = _rival(j, "posteam")
    resultado = _resultado_por_juego(g)
    lideres, juegos = [], []

    def agregar(grupo: str, temp: pl.DataFrame, por_juego: pl.DataFrame, fmt_m6=None):
        for x in temp.iter_rows(named=True):
            c = x["clave"]
            m6 = fmt_m6(x) if fmt_m6 else r(x.get("M6"), 1)
            lideres.append([grupo, c, nom.get(c, c), x["equipo"], pos.get(c, ""), int(x["jugadas"]),
                            r(x["M1"], 3), r(x["M2"], 1), r(x["M3"], 2), r(x["M4"], 2), r(x["M5"], 2), m6])
        for x in por_juego.iter_rows(named=True):
            m6 = fmt_m6(x) if fmt_m6 else r(x.get("M6"), 1)
            juegos.append([f"{grupo}|{x['clave']}", int(x["week"]), x["rival"], resultado.get((x["game_id"], x["equipo"]), ""),
                           int(x["jugadas"]), r(x["M1"], 3), r(x["M2"], 1), r(x["M3"], 2), r(x["M4"], 2), r(x["M5"], 2), m6])

    td_int = lambda x: f"{int(x['td'] or 0)} / {int(x['int'] or 0)}"  # noqa: E731
    agregar("QB", metricas_qb(j, []), metricas_qb(jr, ["game_id", "week", "rival"]), td_int)
    agregar("Receptores", metricas_receptor(j, []), metricas_receptor(jr, ["game_id", "week", "rival"]))
    agregar("Corredores", metricas_corredor(j, []), metricas_corredor(jr, ["game_id", "week", "rival"]))

    # Pasadores
    ev = eventos_pasador(j)
    ev = ev.with_columns(pl.when(pl.col("home_team") == pl.col("defteam")).then(pl.lit("vs ") + pl.col("posteam"))
                         .otherwise(pl.lit("@ ") + pl.col("posteam")).alias("rival"))
    sn = snaps_def(pfr2gsis)
    tot_eq = sn.group_by("team").agg(pl.col("defense_snaps").sum().alias("eq_snaps"))  # snaps del jugador por equipo
    s_tot = sn.group_by("clave").agg(pl.col("defense_snaps").sum().alias("jugadas"), pl.col("team").last().alias("equipo"),
                                     pl.col("defense_pct").mean().alias("pct"))
    e_tot = ev.group_by("clave").agg(pl.len().alias("gs"), pl.col("sack_w").sum().alias("sacks"),
                                     (pl.col("sack_w") == 0).sum().alias("golpes"))
    tp = s_tot.join(e_tot, on="clave", how="left").with_columns(pl.col("gs").fill_null(0), pl.col("sacks").fill_null(0.0),
                                                                pl.col("golpes").fill_null(0))
    posiciones_frente = {"DE", "DT", "NT", "DL", "OLB", "ILB", "LB", "MLB", "EDGE"}
    tp = tp.filter((pl.col("gs") > 0) | pl.col("clave").replace_strict(pos, default="").is_in(list(posiciones_frente)))
    for x in tp.iter_rows(named=True):
        c, n = x["clave"], x["jugadas"]
        lideres.append(["Pasadores", c, nom.get(c, c), x["equipo"], pos.get(c, ""), int(n),
                        r(100.0 * x["gs"] / n, 2) if n else None, int(x["gs"]), r(x["sacks"], 1), pos.get(c, ""),
                        r(100.0 * (x["pct"] or 0), 1), int(x["golpes"])])
    s_j = sn.join(g.select(pl.col("game_id"), pl.col("home_team")), on="game_id", how="left").with_columns(
        pl.when(pl.col("home_team") == pl.col("team")).then(pl.lit("vs ") + pl.col("opponent"))
        .otherwise(pl.lit("@ ") + pl.col("opponent")).alias("rival"))
    e_j = ev.group_by("clave", "game_id").agg(pl.len().alias("gs"), pl.col("sack_w").sum().alias("sacks"),
                                              (pl.col("sack_w") == 0).sum().alias("golpes"))
    pj = s_j.join(e_j, on=["clave", "game_id"], how="left").with_columns(
        pl.col("gs").fill_null(0), pl.col("sacks").fill_null(0.0), pl.col("golpes").fill_null(0))
    claves_p = {x[1] for x in lideres if x[0] == "Pasadores"}
    for x in pj.filter(pl.col("clave").is_in(list(claves_p))).iter_rows(named=True):
        n = x["defense_snaps"]
        juegos.append([f"Pasadores|{x['clave']}", int(x["week"]), x["rival"], resultado.get((x["game_id"], x["team"]), ""),
                       int(n), r(100.0 * x["gs"] / n, 2) if n else None, int(x["gs"]), r(x["sacks"], 1), pos.get(x["clave"], ""),
                       r(100.0 * (x["defense_pct"] or 0), 1), int(x["golpes"])])

    # Línea ofensiva y Cobertura (equipo), con su partido a partido
    for t in EQUIPOS:
        v = valores_eq[t]
        o = j.filter(pl.col("posteam") == t)
        d = j.filter(pl.col("defteam") == t)
        lideres.append(["Línea ofensiva", t, EQUIPOS[t][1], t, "OL", o.height, r(v["off_aly"], 2), r(v["off_golpe"], 1),
                        r(v["off_frenadas"], 1), int(o.filter(pl.col("pass") == 1)["sack"].sum() or 0), r(v["off_epa_corr"], 3),
                        r(v["off_epa_db"], 3)])
        dd = d.filter(pl.col("pass") == 1)
        lideres.append(["Cobertura", t, EQUIPOS[t][1], t, "DEF", dd.height, r(v["def_epa_db"], 3), r(v["def_cpoe"], 2),
                        r(v["def_expl_pase"], 1), int(dd["interception"].sum() or 0), r(v["def_golpe"], 1), r(v["def_exito_pase"], 1)])
    off_j = bloque_juego(jr, "posteam")
    for x in off_j.iter_rows(named=True):
        juegos.append([f"Línea ofensiva|{x['equipo']}", int(x["week"]), x["rival"], resultado.get((x["game_id"], x["equipo"]), ""),
                       int(x["plays"]), r(x["aly"], 2), r(_pct(x["golpe"]), 1), r(_pct(x["frenadas"]), 1), int(x["sacks"] or 0),
                       r(x["epa_corr"], 3), r(x["epa_db"], 3)])
    jd = _rival(j, "defteam")
    def_j = bloque_juego(jd, "defteam")
    for x in def_j.iter_rows(named=True):
        juegos.append([f"Cobertura|{x['equipo']}", int(x["week"]), x["rival"], resultado.get((x["game_id"], x["equipo"]), ""),
                       int(x["n_db"] or 0), r(x["epa_db"], 3), r(x["cpoe"], 2), r(_pct(x["expl_pase"]), 1), int(x["int"] or 0),
                       r(_pct(x["golpe"]), 1), r(_pct(x["exito_pase"]), 1)])

    # puesto dentro del grupo (entre los que llegan al mínimo por defecto), según el orden del grupo
    info = {gr[0]: gr for gr in GRUPOS}
    for grupo, _u, minimo, orden, *_ in GRUPOS:
        filas = [x for x in lideres if x[0] == grupo and x[5] >= minimo and x[6] is not None]
        filas.sort(key=lambda x: ((-x[6] if orden == "desc" else x[6]), x[1]))   # v1.1: empates por clave (antes, al azar)
        for i, x in enumerate(filas, 1):
            x.append(i)
            x.append(len(filas))
        for x in lideres:
            if x[0] == grupo and len(x) == 12:
                x.extend([None, len(filas)])
    for x in lideres:
        etiqueta = f"{x[2]} · {x[3]} · {x[4] or x[0]}" if info[x[0]][6] == "no" else f"{x[2]} ({x[0]})"
        x.append(etiqueta)
    unicas(lideres, info)
    juegos.sort(key=lambda x: (x[0], x[1]))
    return lideres, juegos


def unicas(lideres: list, info: dict) -> None:
    """v1.1 (58): una etiqueta por jugador y grupo. Si la misma etiqueta sale en varias filas de jugadores (un QB que
    también corre, un receptor que también corre), la conserva la fila con más jugadas (la que ya mostraba la pantalla
    Jugador) y las demás suman « · <grupo>». Si aun así se repite (dos jugadores con el mismo nombre, equipo y posición),
    se agrega la clave. Las pantallas no cambian: buscan la fila por la etiqueta."""
    por_et = {}
    for x in lideres:
        if info[x[0]][6] == "no":
            por_et.setdefault(x[14], []).append(x)
    orden_g = {g[0]: i for i, g in enumerate(GRUPOS)}
    for et, filas in por_et.items():
        if len(filas) < 2:
            continue
        filas.sort(key=lambda x: (-(x[5] or 0), orden_g[x[0]], x[1]))
        for x in filas[1:]:
            x[14] = f"{et} · {x[0]}"
    vistas = {}
    for x in lideres:
        if info[x[0]][6] == "no":
            vistas.setdefault(x[14], []).append(x)
    for et, filas in vistas.items():
        if len(filas) > 1:
            for x in filas[1:]:
                x[14] = f"{et} ({x[1]})"


def bloque_juego(jr: pl.DataFrame, lado: str) -> pl.DataFrame:
    db = jr.filter(pl.col("pass") == 1).group_by(lado, "game_id", "week", "rival").agg(
        pl.col("epa").mean().alias("epa_db"), pl.col("success").mean().alias("exito_pase"),
        (pl.col("yards_gained") >= 20).mean().alias("expl_pase"),
        ((pl.col("sack") == 1) | (pl.col("qb_hit") == 1)).mean().alias("golpe"), pl.col("cpoe").mean().alias("cpoe"),
        pl.col("interception").sum().alias("int"), pl.col("sack").sum().alias("sacks"), pl.len().alias("n_db"))
    ru = jr.filter(pl.col("rush") == 1).group_by(lado, "game_id").agg(
        pl.col("epa").mean().alias("epa_corr"), (pl.col("yards_gained") <= 0).mean().alias("frenadas"),
        aly(pl.col("yards_gained")).mean().alias("aly"), pl.len().alias("n_corr"))
    out = db.join(ru, on=[lado, "game_id"], how="left").rename({lado: "equipo"})
    return out.with_columns((pl.col("n_db") + pl.col("n_corr").fill_null(0)).alias("plays"))


def _resultado_por_juego(g: pl.DataFrame) -> dict:
    out = {}
    for x in g.filter(pl.col("result").is_not_null()).iter_rows(named=True):
        for eq, pf, pc in ((x["home_team"], x["home_score"], x["away_score"]), (x["away_team"], x["away_score"], x["home_score"])):
            res = "G" if pf > pc else "P" if pf < pc else "E"
            out[(x["game_id"], eq)] = f"{res} {int(pf)}-{int(pc)}"
    return out


# --------------------------------------------------------------------------------------------------------------------
# partidos (lo del motor + vigía)
# --------------------------------------------------------------------------------------------------------------------
def leer_proyecciones() -> dict:
    """Última proyección automática (miércoles, sábado o T−85) antes del inicio de cada juego (31A)."""
    f = SEM / "proyecciones_2026.csv"
    if not f.exists():
        return {}
    out = {}
    with open(f, encoding="utf-8", newline="") as fh:
        for x in csv.DictReader(fh):
            if x.get("tipo") not in TIPOS_QUE_CUENTAN:
                continue
            if x.get("inicio_utc") and x.get("corrida_utc") and x["corrida_utc"] >= x["inicio_utc"]:
                continue
            prev = out.get(x["game_id"])
            if prev is None or x["corrida_utc"] >= prev["corrida_utc"]:
                out[x["game_id"]] = x
    return out


def leer_vigia() -> dict:
    """Avisos del vigía (55): titulares que la máquina no conoce, por juego y equipo, sin repetir."""
    f = SEM / "vigia_hechos.csv"
    out = {}
    if not f.exists():
        return out
    with open(f, encoding="utf-8", newline="") as fh:
        for x in csv.DictReader(fh):
            if x.get("aviso") != "1" or x.get("valido") != "1":
                continue
            nombre = x.get("nombre_roster") or x.get("nombre") or ""
            lista = out.setdefault((x["game_id"], x["equipo"]), [])
            if nombre and nombre not in lista:
                lista.append(nombre)
    return out


def sin_vig_potencia(ml_local, ml_visita):
    """Probabilidad sin vig del local por el método de potencia (sección 3), a partir de cuotas americanas."""
    def impl(ml):
        ml = _f(ml)
        if ml is None or ml == 0:
            return None
        return 100.0 / (ml + 100.0) if ml > 0 else -ml / (-ml + 100.0)
    a, b = impl(ml_local), impl(ml_visita)
    if a is None or b is None:
        return None
    lo, hi = 0.5, 3.0
    for _ in range(60):
        k = (lo + hi) / 2
        if a ** k + b ** k > 1:
            lo = k
        else:
            hi = k
    k = (lo + hi) / 2
    return a ** k / (a ** k + b ** k)


def _f(x):
    try:
        return float(x) if x not in (None, "") else None
    except ValueError:
        return None


def tabla_partidos(g: pl.DataFrame) -> list:
    proy, vig = leer_proyecciones(), leer_vigia()
    jugadas_hasta = int(g.filter(pl.col("result").is_not_null())["week"].max() or 0)
    semana_max = jugadas_hasta + 1
    filas = []
    for x in g.filter(pl.col("week") <= semana_max).iter_rows(named=True):
        gid, sem = x["game_id"], int(x["week"])
        loc, vis = x["home_team"], x["away_team"]
        cuando, d = cuando_caracas(x["gameday"], x["gametime"])
        neutral = (x.get("location") or "") == "Neutral"
        partido = (f"{EQUIPOS[vis][0]} vs {EQUIPOS[loc][0]}, cancha neutral" if neutral
                   else f"{EQUIPOS[vis][0]} visitan a {EQUIPOS[loc][0]}")
        pr = proy.get(gid)
        # línea: Pinnacle de la proyección que cuenta (≤ 3 h); si no, nflverse (convención: hándicap del local)
        hcp = _f(pr.get("pin_hcp_local")) if pr else None
        fuente = "Pinnacle"
        if hcp is None:
            sl = x["spread_line"]
            hcp, fuente = (-sl if sl is not None else None), "nflverse"
        p_loc = _f(pr.get("pin_p_ml_local")) if pr else None
        fuente_p = "Pinnacle sin vig"
        if p_loc is None:
            p_loc, fuente_p = sin_vig_potencia(x.get("home_moneyline"), x.get("away_moneyline")), "consenso de nflverse sin vig"
        if hcp is None:
            fav = "sin línea todavía"
        elif hcp == 0:
            fav = "parejo (sin favorito)"
        else:
            eq_fav = loc if hcp < 0 else vis
            fav = f"{EQUIPOS[eq_fav][0]}, por {coma(abs(hcp), 1).replace(',0', '')} puntos"
        prob = ""
        if p_loc is not None:
            pf = max(p_loc, 1 - p_loc)
            eq = loc if p_loc >= 0.5 else vis
            prob = f"{EQUIPOS[eq][0]} gana {round(pf * 10)} de cada 10 ({fuente_p})"
        maq, estado = "sin corrida todavía", ""
        if pr:
            sm = _f(pr.get("spread_modelo"))
            if sm is not None:
                eqm = loc if sm < 0 else vis
                maq = f"{EQUIPOS[eqm][0]} por {coma(abs(sm), 1)}" if abs(sm) >= 0.05 else "parejo"
            if pr.get("marcado_spread") == "1" or pr.get("marcado_total") == "1":
                estado = "No hacerle caso en este juego: ve algo muy distinto a las apuestas"
            elif pr.get("sel_estado"):
                estado = {"candidata": "Su opinión cuenta para la prueba (29A)",
                          "excluida: sesgo de la semana": "Excluida esta vez: semana marcada por sesgo",
                          "excluida: filtro": "No hacerle caso en este juego",
                          "sin Pinnacle de 3 h": "Sin línea de Pinnacle reciente: no cuenta"}.get(pr["sel_estado"], pr["sel_estado"])
            else:
                estado = "Opina parecido a las apuestas"
        v_vis = ", ".join(vig.get((gid, vis), [])) or ("—" if sem <= jugadas_hasta else "el vigía corre 85 min antes")
        v_loc = ", ".join(vig.get((gid, loc), [])) or ("—" if sem <= jugadas_hasta else "el vigía corre 85 min antes")
        if x["result"] is not None:
            hs, as_ = int(x["home_score"]), int(x["away_score"])
            resultado = ("Empate " if hs == as_ else f"Ganó {EQUIPOS[loc if hs > as_ else vis][0]} ") + f"{max(hs, as_)}-{min(hs, as_)}"
        else:
            resultado = "por jugarse"
        etiqueta = f"S{sem} · {EQUIPOS[vis][0]} @ {EQUIPOS[loc][0]} · {cuando}"
        tec = (f"{gid} · línea {fuente} {('local ' + coma(hcp, 1)) if hcp is not None else '—'} · "
               f"total mercado {x['total_line'] if x['total_line'] is not None else '—'}"
               + (f" · máquina {pr.get('spread_modelo')} · total máquina {(pr.get('total') or '—')[:5]} · corrida "
                  f"{pr.get('tipo', '')} {(pr.get('corrida_utc') or '')[:16]}" if pr else " · sin corrida de la máquina"))
        orden = -sem * 1e10 + (d.timestamp() if d else 0)
        filas.append([etiqueta, gid, sem, vis, loc, cuando, partido, fav, prob, maq, estado, v_vis, v_loc, resultado, tec, orden])
    filas.sort(key=lambda z: z[-1])
    return filas


# --------------------------------------------------------------------------------------------------------------------
# hoja de Google (solo pestañas datos_*)
# --------------------------------------------------------------------------------------------------------------------
PESTANAS = ["datos_meta", "datos_equipos", "datos_equipos_lista", "datos_partidos", "datos_lideres", "datos_lideres_enc",
            "datos_juegos", "datos_jugadores_lista"]


def filas_briefing() -> list:
    """v1.2 (68): métricas del briefing en formato largo para datos_equipos (no cambia ninguna fila de v1.1)."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import briefing as B
    except Exception as e:  # noqa: BLE001
        log(f"aviso: sin las métricas del briefing (no pude importar briefing.py: {type(e).__name__})")
        return []
    try:
        ruta = bajar("pbp")
        esquema = pl.read_parquet_schema(ruta)
        p = pl.read_parquet(ruta, columns=[c for c in B.COLS_PBP if c in esquema])
        vals, rk = B.metricas_equipos(p)
    except Exception as e:  # noqa: BLE001
        log(f"aviso: sin las métricas del briefing ({type(e).__name__}: {str(e)[:160]})")
        return []
    filas = []
    for clave in B.SENTIDO:
        k = f"eq_{clave}"
        for t in EQUIPOS:
            v = (vals.get(t) or {}).get(clave)
            filas.append([f"{t}|{k}", t, k, r(v, 4), (rk.get(t) or {}).get(clave), B.valor_t(clave, v)])
        filas.append([f"H44|{k}", "H44", k, B.ESTABILIDAD.get(clave), None, B.estab_txt(clave)])
    return filas


def tablas() -> dict:
    t0 = time.time()
    p, g = leer_pbp(), leer_games()
    nom, pos, pfr2gsis = nombres_jugadores()
    eq_largo, eq_lista, valores = tabla_equipos(p, g, nom)
    eq_largo = eq_largo + filas_briefing()            # v1.2 (68)
    lideres, juegos = tabla_grupos(p, g, valores, nom, pos, pfr2gsis)
    partidos = tabla_partidos(g)
    semanas = sorted(int(w) for w in p["week"].unique().to_list() if w is not None)
    minimos = {gr[0]: (gr[2], gr[6]) for gr in GRUPOS}
    lista_j = sorted({(x[14], x[0] + "|" + x[1]) for x in lideres
                      if minimos[x[0]][1] == "no" and x[5] >= max(1, minimos[x[0]][0] // 4)})
    enc = [[gr, u, mn, orden, *hs, expl, es_eq] for gr, u, mn, orden, hs, expl, es_eq in GRUPOS]
    ahora = dt.datetime.now(CCS)
    meta = [["clave", "valor"],
            ["actualizado", f"{ahora:%d-%m-%Y %H:%M} (hora de Caracas)"],
            ["semanas", f"{semanas[0]}-{semanas[-1]}" if semanas else "—"],
            ["ultima_semana", semanas[-1] if semanas else 0],
            ["version", VERSION],
            ["fuente", "nflverse 2026 (jugada por jugada, calendario, snaps, jugadores) y archivos del motor"]]
    out = {
        "datos_meta": meta,
        "datos_equipos": [["clave", "equipo", "metrica", "valor", "puesto", "texto"]] + eq_largo,
        "datos_equipos_lista": [["etiqueta", "equipo", "nombre", "nombre_largo", "record", "ats", "qb", "ultimos", "pj"]] + eq_lista,
        "datos_partidos": [["etiqueta", "game_id", "semana", "visita", "local", "cuando", "partido", "favorito", "probabilidad",
                            "maquina", "estado", "vigia_visita", "vigia_local", "resultado", "tecnico", "orden"]] + partidos,
        "datos_lideres": [["grupo", "clave", "nombre", "equipo", "posicion", "jugadas", "M1", "M2", "M3", "M4", "M5", "M6",
                           "puesto", "calificados", "etiqueta"]] + lideres,
        "datos_lideres_enc": [["grupo", "unidad", "minimo", "orden", "h1", "h2", "h3", "h4", "h5", "h6", "explicacion", "es_equipo"]] + enc,
        "datos_juegos": [["clave", "semana", "rival", "resultado", "jugadas", "M1", "M2", "M3", "M4", "M5", "M6"]] + juegos,
        "datos_jugadores_lista": [["etiqueta", "clave"]] + [[a, b] for a, b in lista_j],
    }
    log(f"tablas listas en {time.time() - t0:.1f} s · equipos {len(eq_lista)} · partidos {len(partidos)} · "
        f"líderes {len(lideres)} · partido a partido {len(juegos)} · jugadores {len(lista_j)}")
    return out


def _limpio(v):
    if v is None:
        return ""
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return ""
    return v


def sesion_google():
    from google.auth.transport.requests import AuthorizedSession
    from google.oauth2 import service_account

    cred = service_account.Credentials.from_service_account_file(
        str(config()["cred"]), scopes=["https://www.googleapis.com/auth/spreadsheets"])
    return AuthorizedSession(cred)


def escribir_google(datos: dict, hoja_id: str, s=None) -> None:
    """Limpia y reescribe solo las pestañas datos_* (RAW). Si una pestaña se queda corta, le agrega filas o columnas."""
    s = s or sesion_google()
    base = f"https://sheets.googleapis.com/v4/spreadsheets/{hoja_id}"
    meta = s.get(base, params={"fields": "sheets.properties"}, timeout=60)
    if meta.status_code != 200:
        raise SystemExit(f"Google respondió {meta.status_code} al leer la hoja: {meta.text[:300]}")
    props = {x["properties"]["title"]: x["properties"] for x in meta.json().get("sheets", [])}
    faltan = [t for t in PESTANAS if t not in props]
    if faltan:
        raise SystemExit(f"A la hoja le faltan las pestañas {faltan}: las crea Claude con el conector; no las creo yo.")
    crecer = []
    for t in PESTANAS:
        gp = props[t].get("gridProperties", {})
        filas, cols = len(datos[t]), max((len(f) for f in datos[t]), default=0)
        if filas > gp.get("rowCount", 0):
            crecer.append({"appendDimension": {"sheetId": props[t]["sheetId"], "dimension": "ROWS",
                                               "length": filas - gp.get("rowCount", 0) + 500}})
        if cols > gp.get("columnCount", 0):
            crecer.append({"appendDimension": {"sheetId": props[t]["sheetId"], "dimension": "COLUMNS",
                                               "length": cols - gp.get("columnCount", 0)}})
    if crecer:
        rg = s.post(f"{base}:batchUpdate", json={"requests": crecer}, timeout=60)
        if rg.status_code != 200:
            raise SystemExit(f"Google respondió {rg.status_code} al agrandar las pestañas de datos: {rg.text[:300]}")
        log(f"pestañas de datos agrandadas ({len(crecer)} cambios)")
    rangos = [f"'{t}'" for t in PESTANAS]
    rc = s.post(f"{base}/values:batchClear", json={"ranges": rangos}, timeout=60)
    if rc.status_code != 200:
        raise SystemExit(f"Google respondió {rc.status_code} al limpiar: {rc.text[:300]}")
    data = [{"range": f"'{t}'!A1", "values": [[_limpio(v) for v in fila] for fila in datos[t]]} for t in PESTANAS]
    ru = s.post(f"{base}/values:batchUpdate", json={"valueInputOption": "RAW", "data": data}, timeout=120)
    if ru.status_code != 200:
        raise SystemExit(f"Google respondió {ru.status_code} al escribir: {ru.text[:300]}")
    celdas = ru.json().get("totalUpdatedCells")
    log(f"hoja actualizada: {celdas} celdas en {len(PESTANAS)} pestañas de datos")


def escribir_local(datos: dict, carpeta: Path) -> None:
    carpeta.mkdir(parents=True, exist_ok=True)
    for t, filas in datos.items():
        with open(carpeta / f"{t}.csv", "w", encoding="utf-8", newline="") as fh:
            csv.writer(fh).writerows([[_limpio(v) for v in f] for f in filas])
    (carpeta / "tablas.json").write_text(json.dumps({t: [[_limpio(v) for v in f] for f in filas] for t, filas in datos.items()},
                                                    ensure_ascii=False), encoding="utf-8")
    log(f"tablas guardadas en {carpeta}")


def config() -> dict:
    c = configparser.ConfigParser()
    c.read(INI, encoding="utf-8")
    sec = c["tablero"] if c.has_section("tablero") else {}
    cred = CRED                                       # la misma llave que usa semana.py ([google] credenciales)
    if c.has_section("google") and (c["google"].get("credenciales") or "").strip():
        cred = (BASE / c["google"]["credenciales"].strip()).resolve()
    return {"hoja_id": (sec.get("hoja_id") or "").strip(), "activo": (sec.get("activo") or "si").strip().lower(), "cred": cred}


def main() -> int:
    ap = argparse.ArgumentParser(description="Tablero tipo PFF Pro (descriptivo) para la hoja NFL Secret LAB — Tablero")
    ap.add_argument("modo", nargs="?", default="correr", choices=["correr", "estado"])
    ap.add_argument("--local", help="carpeta donde dejar las tablas (CSV) sin escribir en Google")
    a = ap.parse_args()
    cfg = config()
    if a.modo == "estado":
        print(f"{VERSION}\nhoja_id: {'configurada' if cfg['hoja_id'] else 'FALTA'} · activo: {cfg['activo']}\n"
              f"credencial: {'ok' if cfg['cred'].exists() else 'FALTA'} · log: {LOG}")
        if LOG.exists():
            print("".join(LOG.read_text(encoding="utf-8").splitlines(keepends=True)[-5:]), end="")
        return 0
    if not a.local and cfg["activo"] in ("no", "0", "false"):
        log("tablero apagado en semana.ini ([tablero] activo = no)")
        return 0
    SAL.mkdir(parents=True, exist_ok=True)
    with open(CANDADO, "w") as fc:
        try:
            fcntl.flock(fc, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log("ya hay una corrida del tablero en marcha; no lanzo otra")
            return 0
        os.nice(0 if os.nice(0) >= 10 else 10 - os.nice(0))
        datos = tablas()
        if a.local:
            escribir_local(datos, Path(a.local))
        else:
            if not cfg["hoja_id"]:
                raise SystemExit("Falta [tablero] hoja_id en semana.ini.")
            escribir_google(datos, cfg["hoja_id"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
