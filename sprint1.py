#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sprint1.py — Motor nfl_sim, Sprint 1 (Bloque 2, sección 6b de contexto_proyecto_nfl.md)

Qué hace
  1. Descarga (una vez) de nflverse el calendario y la jugada por jugada 2021-2025 a ~/nfl_sim/datos/.
  2. Construye la matriz de transición a nivel liga con las reglas de 22A. Cada jugada desde la línea
     de scrimmage se muestrea en DOS pasos, con las jugadas reales 2021-2025 como fuente:
       a) DECISIÓN (pase, corrida, penal, kneel, spike, punt o FG) según down, distancia, yarda y
          situación: fase del juego, marcador, segundos que quedan (tramos finos al final de cada mitad)
          y si el equipo que necesita parar el reloj tiene tiempos muertos;
       b) RESULTADO de pases y corridas (yardas, primer down, TD, pérdida, reloj, tiempos muertos) según
          down, distancia, yarda y RITMO (fase, apuro o gastar reloj), sin el marcador exacto, para no
          trasladar a dos equipos iguales la calidad de los equipos reales (el que va ganando suele ser
          mejor); al final del juego, solo de juegos parejos (|spread| ≤ 4).
     Celdas con pocas jugadas usan un respaldo jerárquico que engruesa primero el campo y conserva el
     tiempo y la urgencia. Además: punts por zona del campo; FG con curva logística por distancia;
     PAT y conversión de 2 por diferencia y momento; kickoff solo con 2025 (touchback a la 35),
     normal y "situación de onside"; tiempo extra con la regla 2025 (temporada regular 10 min, ambos
     poseen, empate posible; playoffs 15 min por periodo, sin empate); tiempos muertos por equipo.
     Un TD de una jugada tomada de más cerca de la meta se transfiere con la curva de supervivencia
     de la ganancia (Kaplan-Meier, la ganancia de un TD queda censurada en la yarda de origen).
  3. Simula juegos entre dos equipos promedio en cancha neutral, jugada por jugada, con todas las
     simulaciones en paralelo (NumPy; ningún bucle por simulación ni por juego).
  4. Evalúa los criterios C0-C6 (24A, registrados el 1-oct-2026 antes de construir) y los
     diagnósticos que se reportan sin decidir. Entrega resumen, CSV y zip, y los manda por Telegram.

Uso (en ~/nfl_sim):
  (nohup nice -n 10 venv/bin/python -u sprint1.py > salidas/sprint1.log 2>&1 &)
Opciones (solo para pruebas):  --rapido  (5 tandas de 2.000 y C0 con 16 × 1.000)   --sin-telegram

Solo lee ~/nfl_ev/config.ini (token de Telegram); no escribe nada fuera de ~/nfl_sim.
"""
import argparse
import configparser
import csv
import fcntl
import json
import os
import platform
import resource
import subprocess
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import polars as pl
import requests

VERSION = "s1-v19 (1-oct-2026)"
BASE = Path(__file__).resolve().parent
DATOS = BASE / "datos"
SALIDA = BASE / "salidas" / "sprint1"
CONFIG_BOT = Path.home() / "nfl_ev" / "config.ini"
URL_GAMES = "https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv"
URL_PBP = "https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{}.parquet"
TEMPORADAS = [2021, 2022, 2023, 2024, 2025]
TEMP_KICKOFF = [2025]              # 22A: kickoff solo con datos de 2025
SEMILLA = 20261001
MIN_CELDA = 40                     # jugadas mínimas para usar una celda antes de pasar al nivel más grueso
SPREAD_PAREJO = 4.0                # juegos "parejos" para los resultados del final del juego (|spread| ≤ 4)
Z99 = 2.5758293035489004           # intervalo del 99 % (C1-C5)
ERROR_MERCADO = 3.0                # supuesto de C2-C3 (pts de DE del error del cierre)

# Fases del simulador
KICK, SCRIM, PAT, FIN = 0, 1, 2, 3
# Motivos de fin de posesión (para comparar con fixed_drive_result de nflverse)
MOTIVOS = ["Touchdown", "Field goal", "Missed field goal", "Punt", "Turnover",
           "Turnover on downs", "End of half", "Opp touchdown", "Safety"]
M_TD, M_FG, M_FGX, M_PUNT, M_TO, M_DOWNS, M_MITAD, M_TDRIV, M_SAF = range(9)

COLS_PBP = ["game_id", "play_id", "season", "season_type", "qtr", "game_seconds_remaining",
            "half_seconds_remaining", "posteam", "defteam", "down", "ydstogo", "yardline_100",
            "play_type", "yards_gained", "touchdown", "td_team", "interception", "fumble_lost",
            "safety", "field_goal_result", "kick_distance", "extra_point_result",
            "two_point_conv_result", "score_differential", "fixed_drive", "fixed_drive_result",
            "drive_start_transition", "drive_start_yard_line", "timeout", "timeout_team",
            "posteam_timeouts_remaining", "defteam_timeouts_remaining"]
TIPOS_ACCION = ["pass", "run", "no_play", "punt", "field_goal", "qb_kneel", "qb_spike",
                "kickoff", "extra_point"]


def log(msg):
    print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC] {msg}", flush=True)


# --------------------------------------------------------------------------------------
# 1. Datos
# --------------------------------------------------------------------------------------
def descargar(url, destino, minimo_bytes):
    if destino.exists() and destino.stat().st_size >= minimo_bytes:
        return
    tmp = destino.with_suffix(destino.suffix + ".parcial")
    for intento in range(1, 4):
        try:
            with requests.get(url, stream=True, timeout=60) as r:
                r.raise_for_status()
                with open(tmp, "wb") as f:
                    for trozo in r.iter_content(1 << 20):
                        f.write(trozo)
            if tmp.stat().st_size < minimo_bytes:
                raise IOError(f"archivo incompleto ({tmp.stat().st_size} bytes)")
            tmp.replace(destino)
            log(f"descargado {destino.name} ({destino.stat().st_size / 1e6:.1f} MB)")
            return
        except Exception as e:  # noqa: BLE001
            log(f"descarga de {destino.name}, intento {intento}: {e}")
            time.sleep(5 * intento)
    raise SystemExit(f"No se pudo descargar {url}")


def preparar_datos():
    DATOS.mkdir(parents=True, exist_ok=True)
    descargar(URL_GAMES, DATOS / "games.csv", 500_000)
    for y in TEMPORADAS:
        descargar(URL_PBP.format(y), DATOS / f"pbp_{y}.parquet", 5_000_000)
    games = pl.read_csv(DATOS / "games.csv", infer_schema_length=20000)
    pbp = pl.concat([pl.read_parquet(DATOS / f"pbp_{y}.parquet", columns=COLS_PBP)
                     for y in TEMPORADAS], how="vertical_relaxed")
    return games, pbp


# --------------------------------------------------------------------------------------
# 2. Celdas y situaciones (mismas funciones para datos y simulador)
# --------------------------------------------------------------------------------------
_LUT_DIST = np.zeros(100, dtype=np.int16)          # distancia a primer down → 10 tramos
for _d in range(100):
    _LUT_DIST[_d] = (0 if _d <= 1 else 1 if _d == 2 else 2 if _d == 3 else 3 if _d <= 5 else
                     4 if _d <= 7 else 5 if _d <= 9 else 6 if _d == 10 else 7 if _d <= 13 else
                     8 if _d <= 17 else 9)
_LUT_YL = np.zeros(101, dtype=np.int16)            # yardas a la zona de anotación → 13 tramos
for _y in range(101):
    _LUT_YL[_y] = (0 if _y <= 2 else 1 if _y <= 5 else 2 if _y <= 10 else 3 if _y <= 15 else
                   4 if _y <= 20 else 5 if _y <= 30 else 6 if _y <= 40 else 7 if _y <= 50 else
                   8 if _y <= 60 else 9 if _y <= 70 else 10 if _y <= 80 else 11 if _y <= 90 else 12)
N_DIST, N_YL = 10, 13
_DB3 = np.array([0, 0, 0, 1, 1, 1, 2, 2, 2, 2], dtype=np.int64)          # distancia: 1-3, 4-9, 10+
_YB9 = np.array([0, 1, 2, 3, 4, 5, 5, 6, 6, 7, 7, 8, 8], dtype=np.int64)  # 1-2, 3-5, 6-10, 11-15, 16-20 (finos cerca de la meta), 21-40, 41-60, 61-80, 81-99
_YB5 = np.array([0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 4, 4], dtype=np.int64)  # 1-10, 11-20, 21-40, 41-60, 61-99
_YB3 = np.array([0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2], dtype=np.int64)  # ≤20, 21-60, 61+

# ---- Situación (230): decide la jugada ----
#   0-27    juego normal: 7·fase + diferencia (fase: 1er cuarto, 2º antes de 2:00, 3er, 4º antes de 5:00;
#           diferencia: +17 o más, +9..+16, +1..+8, 0, −1..−8, −9..−16, −17 o menos)
#   28-37   final de la 1ª mitad: 28 + 2·tramo + tm (tramo: 2:00-0:31, 0:30-0:21, 0:20-0:11, 0:10-0:05, ≤ 0:04)
#   38-133  últimos 5:00 del 4º cuarto: 38 + 2·(6·dif + tiempo) + tm
#   134-229 tiempo extra: igual con base 134
#           dif: +9 o más, +4..+8, +1..+3, 0, −1..−3, −4..−8, −9..−16, −17 o menos
#           tiempo: > 2:00, 2:00-0:31, 0:30-0:21, 0:20-0:11, 0:10-0:05, ≤ 0:04 (en tiempo extra, el reloj del periodo)
#           tm: 1 si el equipo que necesita parar el reloj (la defensa si la ofensiva gana; si no, la ofensiva) tiene tiempos muertos
# Los segundos finales van en tramos finos porque ahí se decide si se patea el FG (medido 2021-2025: con ≤ 0:04
# y en rango se patea 70-96 % de las veces; con 0:05-0:10, 9-50 %; con 0:11-0:30, casi nunca).
N_SIT = 230
_SITMED = np.zeros(N_SIT, dtype=np.int64)        # nivel intermedio: fase o diferencia, sin tiempo fino ni tiempos muertos
# Grupo de tiempo: junta contextos con la misma urgencia y el mismo tramo de tiempo (para celdas raras):
#   0-3 fases normales · 4-9 "necesita FG" (fin de 1ª mitad, o pierde por 1-3 al final) por tiempo ·
#   10-15 "gasta reloj" (gana al final) · 16-21 "necesita TD" (pierde por 4+ al final) ·
#   22-27 empatado al final (juega para el FG y cuida el reloj; no hay sesgo de calidad: ninguno va ganando)
N_GT = 28
_GT = np.zeros(N_SIT, dtype=np.int64)
for _f in range(4):
    _SITMED[_f * 7:(_f + 1) * 7] = _f
    _GT[_f * 7:(_f + 1) * 7] = _f
for _tb in range(5):
    for _tm in range(2):
        _SITMED[28 + 2 * _tb + _tm] = 4
        _GT[28 + 2 * _tb + _tm] = 4 + (_tb + 1)
for _base in (38, 134):
    for _dg in range(8):
        for _tg in range(6):
            for _tm in range(2):
                _s = _base + 2 * (6 * _dg + _tg) + _tm
                _SITMED[_s] = 5 + _dg
                _GT[_s] = (10 + _tg) if _dg <= 2 else (22 + _tg) if _dg == 3 else (4 + _tg) if _dg == 4 else (16 + _tg)
N_MED = 13
_TM = np.zeros(N_SIT, dtype=np.int64)            # bit de tiempos muertos de cada situación
_TM[28:] = (np.arange(28, N_SIT) - np.where(np.arange(28, N_SIT) >= 134, 134, np.where(np.arange(28, N_SIT) >= 38, 38, 28))) % 2
# ---- Ritmo (40): muestrea el RESULTADO de pases y corridas sin el marcador exacto ----
#   0-3 fases normales; 4 + 2·(grupo de tiempo − 4) + (1 si SIN tiempos muertos) para los grupos 4-27.
# En la SIMULACIÓN, quien "necesita TD" con ≤ 2:00 toma el resultado de "necesita FG" del mismo tramo
# (que incluye el apuro del final de la 1ª mitad, jugado por todos los equipos): quien pierde por 4+ al final
# de un juego real suele ser el peor equipo, y eso no debe pasar a dos equipos iguales.
N_RITMO = 52
RITMO = np.where(_GT < 4, _GT, 4 + 2 * (_GT - 4) + (1 - _TM))
# Ritmo grueso (para celdas de resultado con pocas jugadas): junta con y sin tiempos muertos, y el empatado
# con "necesita FG" del mismo tramo, antes de dejar de lado el reloj.
N_RG = 22
_RG = np.zeros(N_RITMO, dtype=np.int64)
_RG[:4] = np.arange(4)
for _g in range(4, 28):
    _RG[4 + 2 * (_g - 4)] = _RG[4 + 2 * (_g - 4) + 1] = (_g - 18) if _g >= 22 else _g
_GT_SIM = np.where((_GT >= 17) & (_GT <= 21), _GT - 12, _GT)   # "necesita TD" con ≤ 2:00 → "necesita FG" del mismo tramo
RITMO_SIM = np.where(_GT_SIM < 4, _GT_SIM, 4 + 2 * (_GT_SIM - 4) + (1 - _TM))


def _tramo(hs):
    return np.select([hs > 120, hs > 30, hs > 20, hs > 10, hs > 4], [0, 1, 2, 3, 4], 5)


def situacion(qtr, hs, diff, con_tm):
    """Situación del juego (0-229); ver la tabla de arriba. qtr: 1-4, 5 = tiempo extra; hs: segundos que
    quedan en la mitad (o en el periodo extra); diff: puntos de la ofensiva menos los de la defensa;
    con_tm: el equipo que necesita parar el reloj tiene al menos un tiempo muerto."""
    qtr = np.asarray(qtr); hs = np.asarray(hs); diff = np.asarray(diff)
    tm = np.asarray(con_tm).astype(np.int64)
    fase = np.select([qtr == 1, qtr == 2, qtr == 3], [0, 1, 2], 3)
    dgn = np.select([diff >= 17, diff >= 9, diff >= 1, diff == 0, diff >= -8, diff >= -16], [0, 1, 2, 3, 4, 5], 6)
    s = fase * 7 + dgn
    tg = _tramo(hs)
    s = np.where((qtr == 2) & (hs <= 120), 28 + 2 * (tg - 1) + tm, s)
    dg = np.select([diff >= 9, diff >= 4, diff >= 1, diff == 0, diff >= -3, diff >= -8, diff >= -16], [0, 1, 2, 3, 4, 5, 6], 7)
    s = np.where((qtr == 4) & (hs <= 300), 38 + 2 * (6 * dg + tg) + tm, s)
    s = np.where(qtr >= 5, 134 + 2 * (6 * dg + tg) + tm, s)
    return s.astype(np.int64)


def _niveles(d, db, yb, s):
    """Clave de cada nivel de agregación (L0 el más fino, L10 el más grueso). Primero se engruesa el campo
    y el down; después se juntan los tiempos muertos; después se juntan contextos con la misma urgencia y el
    mismo tramo de tiempo; recién al final se deja de lado el tiempo."""
    sin_tm = s - _TM[s]
    d4 = (d == 3).astype(np.int64)
    gt = _GT[s]
    l0 = ((d * N_DIST + db) * N_YL + yb) * N_SIT + s
    l1 = ((d * 3 + _DB3[db]) * 9 + _YB9[yb]) * N_SIT + s
    l2 = (d4 * 9 + _YB9[yb]) * N_SIT + s
    l3 = (d4 * 9 + _YB9[yb]) * N_SIT + sin_tm
    l4 = (d4 * 5 + _YB5[yb]) * N_SIT + sin_tm
    l5 = (d4 * 9 + _YB9[yb]) * N_GT + gt
    l6 = (d4 * 5 + _YB5[yb]) * N_GT + gt
    l7 = ((d * N_DIST + db) * N_YL + yb) * N_MED + _SITMED[s]
    l8 = (d * N_DIST + db) * N_YL + yb
    l9 = (d * N_DIST + db) * 3 + _YB3[yb]
    l10 = d * N_DIST + db
    return [l0, l1, l2, l3, l4, l5, l6, l7, l8, l9, l10]


TAM_NIVEL = [4 * N_DIST * N_YL * N_SIT, 4 * 3 * 9 * N_SIT, 2 * 9 * N_SIT, 2 * 9 * N_SIT, 2 * 5 * N_SIT,
             2 * 9 * N_GT, 2 * 5 * N_GT, 4 * N_DIST * N_YL * N_MED, 4 * N_DIST * N_YL, 4 * N_DIST * 3, 4 * N_DIST]
MIN_NIVEL = [MIN_CELDA, 20, 20, 20, 20, 20, 20, MIN_CELDA, MIN_CELDA, MIN_CELDA, 1]


def _niveles_res(d, db, yb, cat, rit):
    """Niveles para el RESULTADO de pases (cat 0) y corridas (cat 1): down, distancia, yarda y ritmo.
    El ritmo (reloj) se conserva hasta el final; primero se engruesa el campo y el down."""
    d4 = (d == 3).astype(np.int64)
    r0 = ((((d * N_DIST + db) * N_YL + yb) * 2 + cat) * N_RITMO) + rit
    r1 = ((((d * 3 + _DB3[db]) * 9 + _YB9[yb]) * 2 + cat) * N_RITMO) + rit
    r2 = (((d4 * 5 + _YB5[yb]) * 2 + cat) * N_RITMO) + rit
    r3 = ((_YB3[yb] * 2 + cat) * N_RITMO) + rit
    rg = _RG[rit]
    r4 = (((d4 * 5 + _YB5[yb]) * 2 + cat) * N_RG) + rg
    r5 = ((_YB3[yb] * 2 + cat) * N_RG) + rg
    r6 = ((d * N_DIST + db) * N_YL + yb) * 2 + cat
    r7 = ((d * N_DIST + db) * 3 + _YB3[yb]) * 2 + cat
    r8 = (d * N_DIST + db) * 2 + cat
    r9 = cat
    return [r0, r1, r2, r3, r4, r5, r6, r7, r8, r9]


TAM_RES = [4 * N_DIST * N_YL * 2 * N_RITMO, 4 * 3 * 9 * 2 * N_RITMO, 2 * 5 * 2 * N_RITMO, 3 * 2 * N_RITMO,
           2 * 5 * 2 * N_RG, 3 * 2 * N_RG, 4 * N_DIST * N_YL * 2, 4 * N_DIST * 3 * 2, 4 * N_DIST * 2, 2]
MIN_RES = [MIN_CELDA, 20, 20, 20, 20, 20, MIN_CELDA, MIN_CELDA, MIN_CELDA, 1]


def mapa_celdas_res():
    d, db, yb, c, r = np.meshgrid(np.arange(4), np.arange(N_DIST), np.arange(N_YL), np.arange(2), np.arange(N_RITMO), indexing="ij")
    niveles = _niveles_res(d.ravel(), db.ravel(), yb.ravel(), c.ravel(), r.ravel())
    orden = np.argsort(niveles[0])
    return [x[orden] for x in niveles]


def clave_res(down, dist, yl, cat, rit):
    return ((((down.astype(np.int64) - 1) * N_DIST + _LUT_DIST[np.clip(dist, 0, 99)]) * N_YL
             + _LUT_YL[np.clip(yl, 0, 100)]) * 2 + cat) * N_RITMO + rit


def claves_celda(down, dist, yl, sit):
    d = np.asarray(down, dtype=np.int64) - 1
    db = _LUT_DIST[np.clip(np.asarray(dist), 0, 99)].astype(np.int64)
    yb = _LUT_YL[np.clip(np.asarray(yl), 0, 100)].astype(np.int64)
    return _niveles(d, db, yb, np.asarray(sit, dtype=np.int64))


def clave_l0(down, dist, yl, sit):
    """Solo la clave más fina (la que usa el simulador en cada jugada)."""
    return (((down.astype(np.int64) - 1) * N_DIST + _LUT_DIST[np.clip(dist, 0, 99)]) * N_YL
            + _LUT_YL[np.clip(yl, 0, 100)]) * N_SIT + sit


def tabla_con_respaldo(claves_por_nivel, tam_por_nivel, mapa_l0_a_niveles, minimos):
    """Devuelve (orden, offset[L0], cuenta[L0], nivel) para muestrear filas por celda L0 con respaldo:
    se usa el primer nivel cuyo grupo tenga al menos el mínimo de filas de ese nivel."""
    partes, base, info = [], 0, []
    for k, tam in zip(claves_por_nivel, tam_por_nivel):
        orden = np.argsort(k, kind="stable")
        cuenta = np.bincount(k, minlength=tam)
        inicio = np.concatenate([[0], np.cumsum(cuenta)[:-1]]) + base
        partes.append(orden)
        info.append((inicio, cuenta))
        base += len(k)
    orden_total = np.concatenate(partes)
    n0 = tam_por_nivel[0]
    off = np.zeros(n0, dtype=np.int64)
    cnt = np.zeros(n0, dtype=np.int64)
    asignado = np.zeros(n0, dtype=bool)
    nivel_usado = np.full(n0, -1, dtype=np.int8)
    for nivel, (inicio, cuenta) in enumerate(info):
        g = mapa_l0_a_niveles[nivel]
        ok = (~asignado) & (cuenta[g] >= max(minimos[nivel], 1))
        off[ok] = inicio[g[ok]]
        cnt[ok] = cuenta[g[ok]]
        nivel_usado[ok] = nivel
        asignado |= ok
    return orden_total, off, cnt, nivel_usado


def mapa_celdas_l0():
    """Para cada celda L0 posible (en el orden de su clave), su grupo en cada nivel."""
    d, db, yb, s = np.meshgrid(np.arange(4), np.arange(N_DIST), np.arange(N_YL), np.arange(N_SIT), indexing="ij")
    niveles = _niveles(d.ravel(), db.ravel(), yb.ravel(), s.ravel())
    orden = np.argsort(niveles[0])
    return [x[orden] for x in niveles]


# --------------------------------------------------------------------------------------
# 3. Modelo (tablas de transición)
# --------------------------------------------------------------------------------------
def construir_modelo(pbp, games):
    t0 = time.time()
    # tiempos muertos pedidos entre una acción y la siguiente (filas sin tipo de jugada con timeout = 1)
    # en nflverse los tiempos muertos son filas 'no_play' sin equipo con la pelota: no son jugadas;
    # se asignan a la acción anterior para saber quién paró el reloj
    todo = (pbp.sort(["game_id", "play_id"])
            .with_columns((pl.col("play_type").is_in(TIPOS_ACCION)
                           & ~((pl.col("play_type") == "no_play") & pl.col("posteam").is_null())).fill_null(False).alias("es_acc"))
            .with_columns(pl.col("es_acc").cast(pl.Int64).cum_sum().over("game_id").alias("n_acc")))
    tms = (todo.filter(~pl.col("es_acc") & (pl.col("timeout") == 1) & pl.col("timeout_team").is_not_null())
           .select(["game_id", "n_acc", "timeout_team"]))
    acc = todo.filter(pl.col("es_acc")).select(["game_id", "play_id", "n_acc"])
    tms = tms.join(acc, on=["game_id", "n_acc"], how="inner").group_by(["game_id", "play_id"]).agg(
        pl.col("timeout_team").alias("tm_equipos"))
    # juegos parejos según el mercado antes del juego (|spread de cierre| ≤ SPREAD_PAREJO): en ellos quien va
    # ganando o perdiendo al final no es, en promedio, el mejor o el peor equipo
    parejos = (games.filter(pl.col("spread_line").abs() <= SPREAD_PAREJO).select("game_id")
               .with_columns(pl.lit(True).alias("parejo")))
    a = (todo.filter(pl.col("es_acc")).drop(["es_acc", "n_acc"])
         .join(tms, on=["game_id", "play_id"], how="left")
         .join(parejos, on="game_id", how="left")
         .sort(["game_id", "play_id"])
         .with_columns(pl.when(pl.col("qtr") <= 2).then(1).when(pl.col("qtr") <= 4).then(2)
                       .otherwise(3).alias("mitad")))
    sig = ["posteam", "yardline_100", "down", "ydstogo", "game_seconds_remaining", "half_seconds_remaining",
           "play_type", "mitad", "qtr"]
    a = a.with_columns([pl.col(c).shift(-1).over("game_id").alias("n_" + c) for c in sig] +
                       [pl.col("safety").shift(1).over("game_id").alias("p_safety")])
    a = a.with_columns((pl.col("n_mitad") == pl.col("mitad")).fill_null(False).alias("misma_mitad"))
    f = lambda c: a[c].fill_null(0).to_numpy()  # noqa: E731

    pt = a["play_type"].to_numpy()
    pos = a["posteam"].fill_null("").to_numpy()
    de = a["defteam"].fill_null("").to_numpy()
    tdt = a["td_team"].fill_null("").to_numpy()
    npos = a["n_posteam"].fill_null("").to_numpy()
    npt = a["n_play_type"].fill_null("").to_numpy()
    down = f("down").astype(np.int64)
    ndown = f("n_down").astype(np.int64)
    Y = f("yardline_100").astype(np.int64)
    NY = f("n_yardline_100").astype(np.int64)
    dist = f("ydstogo").astype(np.int64)
    qtr = f("qtr").astype(np.int64)
    hs = f("half_seconds_remaining").astype(np.float64)
    gsr = f("game_seconds_remaining").astype(np.float64)
    ngsr = a["n_game_seconds_remaining"].fill_null(-1).to_numpy().astype(np.float64)
    misma = a["misma_mitad"].to_numpy()
    td = f("touchdown") == 1
    td_of = td & (tdt == pos)
    td_def = td & (tdt == de)
    saf = f("safety") == 1
    perdida = ((f("interception") == 1) | (f("fumble_lost") == 1)) & ~td
    temporada = f("season").astype(np.int64)
    sdiff = f("score_differential").astype(np.int64)
    n_es_scrim = np.isin(npt, ["pass", "run", "no_play", "punt", "field_goal", "qb_kneel", "qb_spike"]) & (ndown > 0)

    transcurrido = np.where(misma & (ngsr >= 0), gsr - ngsr, np.minimum(hs, 45.0))
    transcurrido = np.clip(transcurrido, 0, 50)

    # ---- jugadas desde la línea de scrimmage ----
    es_scrim = np.isin(pt, ["pass", "run", "no_play", "punt", "field_goal", "qb_kneel", "qb_spike"]) & (down >= 1)
    tipo = np.where(pt == "punt", 1, np.where(pt == "field_goal", 2, 0))
    sigue = misma & n_es_scrim & (npos == pos)
    cambia = misma & n_es_scrim & (npos == de)
    avance = np.where(sigue, Y - NY, np.where(cambia, Y - (100 - NY), f("yards_gained").astype(np.int64)))
    # serie nueva = 1º y 10 (o 1º y meta); un 1º y 15 tras un penal en 1º down es repetición, no serie nueva
    ndist = f("n_ydstogo").astype(np.int64)
    serie_nueva = sigue & (ndown == 1) & (ndist == np.minimum(10, NY))
    auto_pd = serie_nueva & (avance < dist) & ~td
    repite = sigue & (ndown == down) & ~serie_nueva
    es_pase_corrida = np.isin(pt, ["pass", "run"])
    tm_eq = a["tm_equipos"].to_list()
    to_of = np.array([bool(x) and p in x for x, p in zip(tm_eq, pos)])
    to_def = np.array([bool(x) and q in x for x, q in zip(tm_eq, de)])
    tm_pos = a["posteam_timeouts_remaining"].fill_null(0).to_numpy()
    tm_def = a["defteam_timeouts_remaining"].fill_null(0).to_numpy()
    con_tm = np.where(sdiff > 0, tm_def >= 1, tm_pos >= 1)
    sit = situacion(qtr, hs, sdiff, con_tm)

    m = es_scrim
    km = supervivencia_ganancia(f("yards_gained").astype(np.int64)[es_pase_corrida & m & ~perdida],
                                Y[es_pase_corrida & m & ~perdida], td_of[es_pase_corrida & m & ~perdida])
    S = dict(tipo=tipo[m].astype(np.int8), avance=np.clip(avance[m], -99, 99).astype(np.int16), yo=Y[m].astype(np.int16), km=km,
             seg=transcurrido[m].astype(np.float32), td_of=td_of[m], td_def=td_def[m],
             saf=saf[m] & ~td[m], perdida=perdida[m], auto_pd=auto_pd[m], repite=repite[m],
             pr=es_pase_corrida[m], to_of=to_of[m], to_def=to_def[m])
    claves = claves_celda(down[m], dist[m], Y[m], sit[m])
    orden, off, cnt, nivel = tabla_con_respaldo(claves, TAM_NIVEL, mapa_celdas_l0(), MIN_NIVEL)
    if (cnt <= 0).any():
        raise SystemExit(f"Hay {(cnt <= 0).sum()} celdas sin jugadas después del respaldo")
    S.update(orden=orden.astype(np.int64), off=off, cnt=cnt)
    cat = np.select([pt == "pass", pt == "run", pt == "no_play", pt == "qb_kneel", pt == "qb_spike", pt == "punt",
                     pt == "field_goal"], [0, 1, 2, 3, 4, 5, 6], 2)[m]
    S["cat"] = cat.astype(np.int8)
    # filas (dentro de S) de pases y corridas para la tabla de resultados; las del final del juego
    # (últimos 5:00 y tiempo extra) solo de juegos parejos, para no heredar la calidad de los equipos
    parejo = a["parejo"].fill_null(False).to_numpy()[m]
    pr_idx = np.flatnonzero((cat <= 1) & ((sit[m] < 38) | parejo))
    dd = down[m][pr_idx] - 1
    db_ = _LUT_DIST[np.clip(dist[m][pr_idx], 0, 99)].astype(np.int64)
    yb_ = _LUT_YL[np.clip(Y[m][pr_idx], 0, 100)].astype(np.int64)
    rit = RITMO[sit[m][pr_idx]]
    claves_r = _niveles_res(dd, db_, yb_, cat[pr_idx].astype(np.int64), rit)
    r_orden, r_off, r_cnt, r_nivel = tabla_con_respaldo(claves_r, TAM_RES, mapa_celdas_res(), MIN_RES)
    S.update(r_orden=pr_idx[r_orden].astype(np.int64), r_off=r_off, r_cnt=r_cnt)
    n_scrim = int(m.sum())
    reparto_niveles = np.bincount(nivel[nivel >= 0], minlength=len(TAM_NIVEL))

    # ---- punts (2021-2025): resultado según la yarda del punt ----
    mp = (pt == "punt") & (down >= 1)
    pr_td = td & (tdt == de)                     # TD del equipo que recibe
    pk_td = td & (tdt == pos)                    # TD del equipo que patea
    recibe = misma & n_es_scrim & (npos == de) & ~td
    conserva = misma & n_es_scrim & (npos == pos) & ~td
    valido = mp & (pr_td | pk_td | recibe | conserva | saf)
    P = dict(Y=Y[valido].astype(np.int16), Z=np.where(recibe, NY, np.where(conserva, NY, 0))[valido].astype(np.int16),
             res=np.select([pr_td, pk_td, saf, conserva], [1, 2, 3, 4], 0)[valido].astype(np.int8),
             tb=((NY == 80) & recibe)[valido], seg=np.clip(transcurrido, 0, 20)[valido].astype(np.float32))
    # tramos de 5 yardas por la yarda del punt; con respaldo a tramos de 10 y a todos
    yb5 = np.minimum(P["Y"] // 5, 19).astype(np.int64)
    yb10 = (yb5 // 2).astype(np.int64)
    g5 = np.arange(20); g10 = g5 // 2; gall = np.zeros(20, dtype=np.int64)
    p_orden, p_off, p_cnt, _ = tabla_con_respaldo([yb5, yb10, np.zeros_like(yb5)], [20, 10, 1],
                                                 [g5, g10, gall], [60, 60, 1])
    P.update(orden=p_orden, off=p_off, cnt=p_cnt)

    # ---- goles de campo (2021-2025): curva logística por distancia ----
    mf = (pt == "field_goal")
    dist_fg = f("kick_distance").astype(np.float64)[mf]
    hecho = (a["field_goal_result"].fill_null("").to_numpy()[mf] == "made").astype(np.float64)
    ok = dist_fg > 0
    beta = ajustar_logistica(dist_fg[ok], hecho[ok])
    seg_fg = np.clip(transcurrido[mf], 0, 15).astype(np.float32)

    # ---- PAT y conversión de 2 (2021-2025) ----
    mx = pt == "extra_point"
    m2 = (f("down") == 0) & np.isin(pt, ["pass", "run", "no_play"]) & \
        (a["two_point_conv_result"].fill_null("").to_numpy() != "")
    p_xp = float((a["extra_point_result"].fill_null("").to_numpy()[mx] == "good").mean())
    p_2 = float((a["two_point_conv_result"].fill_null("").to_numpy()[m2] == "success").mean())
    intento = np.concatenate([np.zeros(mx.sum()), np.ones(m2.sum())])
    dif = np.clip(np.concatenate([sdiff[mx], sdiff[m2]]), -20, 20) + 20
    tarde = np.concatenate([qtr[mx], qtr[m2]]) >= 4
    dec2 = np.zeros((2, 41))
    for t in (0, 1):
        sel = tarde == bool(t)
        n_c = np.bincount(dif[sel], minlength=41)
        k_c = np.bincount(dif[sel], weights=intento[sel], minlength=41)
        general = k_c.sum() / max(n_c.sum(), 1)
        # suavizado mínimo (1 intento de peso hacia el promedio del momento): en el 4º cuarto la decisión es
        # casi determinista según la diferencia (perdiendo por 2 tras el TD se va por 2 el 100 %)
        dec2[t] = (k_c + 1 * general) / (n_c + 1)

    # ---- kickoffs (22A: solo 2025) y patadas tras safety (2021-2025) ----
    mk = (pt == "kickoff")
    k_recibe = misma & n_es_scrim & (npos == pos) & ~td
    k_conserva = misma & n_es_scrim & (npos == de) & ~td
    k_rtd = td & (tdt == pos)
    k_ktd = td & (tdt == de)
    k_ok = mk & (k_recibe | k_conserva | k_rtd | k_ktd) & (npt != "kickoff")
    tras_safety = a["p_safety"].fill_null(0).to_numpy() == 1
    dif_patea = -sdiff                                       # en el kickoff, posteam es quien recibe
    onside_sit = (qtr == 4) & (hs <= 300) & (dif_patea <= -1) & (dif_patea >= -16)
    K = {}
    for nombre, sel in [("normal", k_ok & ~tras_safety & ~onside_sit & np.isin(temporada, TEMP_KICKOFF)),
                        ("onside", k_ok & ~tras_safety & onside_sit & np.isin(temporada, TEMP_KICKOFF)),
                        ("safety", k_ok & tras_safety)]:
        K[nombre] = dict(res=np.select([k_rtd, k_ktd, k_conserva], [1, 2, 3], 0)[sel].astype(np.int8),
                         yl=np.where(k_recibe | k_conserva, NY, 0)[sel].astype(np.int16),
                         seg=np.clip(transcurrido, 0, 20)[sel].astype(np.float32))

    resumen = dict(
        filas_accion=int(a.height), jugadas_scrimmage=n_scrim,
        tiempos_muertos_ofensiva=int(to_of.sum()), tiempos_muertos_defensa=int(to_def.sum()),
        celdas_por_nivel={f"L{i}": int(x) for i, x in enumerate(reparto_niveles)},
        celdas_resultado_por_nivel={f"R{i}": int(x) for i, x in enumerate(np.bincount(r_nivel[r_nivel >= 0], minlength=len(TAM_RES)))},
        punts=int(len(P["Y"])), fg=int(mf.sum()), fg_beta=[float(b) for b in beta],
        p_xp=p_xp, p_2pt=p_2, intentos_2pt=int(m2.sum()), xp=int(mx.sum()),
        kickoffs_2025_normal=int(len(K["normal"]["res"])), kickoffs_2025_onside=int(len(K["onside"]["res"])),
        patadas_safety=int(len(K["safety"]["res"])), segundos=round(time.time() - t0, 1))
    return dict(S=S, P=P, beta=beta, seg_fg=seg_fg, p_xp=p_xp, p_2=p_2, dec2=dec2, K=K, resumen=resumen)


def supervivencia_ganancia(g, y, censurado):
    """S(x) = P(ganancia >= x) para x = 0..100 por Kaplan-Meier: en un TD la ganancia potencial
    queda censurada en la yarda de origen (la jugada habría ganado al menos eso)."""
    S = np.ones(102)
    S[0] = float(np.mean((g >= 0) | censurado))
    for x in range(0, 101):
        riesgo = np.sum(np.where(censurado, y >= x, g >= x))
        eventos = np.sum((~censurado) & (g == x))
        S[x + 1] = S[x] * (1 - eventos / riesgo) if riesgo > 0 else S[x]
    return S


def ajustar_logistica(x, y, iteraciones=50):
    """Regresión logística con distancia y distancia² (Newton-Raphson)."""
    xc = (x - 40.0) / 10.0
    X = np.column_stack([np.ones_like(xc), xc, xc ** 2])
    b = np.zeros(3)
    for _ in range(iteraciones):
        p = 1 / (1 + np.exp(-X @ b))
        W = p * (1 - p)
        H = X.T @ (X * W[:, None]) + 1e-6 * np.eye(3)
        paso = np.linalg.solve(H, X.T @ (y - p))
        b += paso
        if np.max(np.abs(paso)) < 1e-9:
            break
    return b


def prob_fg(beta, distancia):
    xc = (distancia - 40.0) / 10.0
    return 1 / (1 + np.exp(-(beta[0] + beta[1] * xc + beta[2] * xc ** 2)))


# --------------------------------------------------------------------------------------
# 4. Simulador vectorizado
# --------------------------------------------------------------------------------------
def simular(M, n, playoffs, rng):
    """Simula n juegos entre dos equipos promedio en cancha neutral. playoffs: bool para todos."""
    S, P, K = M["S"], M["P"], M["K"]
    gsr = np.full(n, 3600.0)          # segundos de reglamento
    otc = np.zeros(n)                  # reloj del tiempo extra
    per = np.zeros(n, dtype=np.int8)   # 0 1ª mitad, 1 2ª mitad, 2 tiempo extra
    pos = np.zeros(n, dtype=np.int8)
    Y = np.full(n, 75, dtype=np.int16)
    down = np.ones(n, dtype=np.int8)
    dist = np.full(n, 10, dtype=np.int16)
    sc = np.zeros((n, 2), dtype=np.int16)
    fase = np.full(n, KICK, dtype=np.int8)
    recibe1 = (rng.random(n) < 0.5).astype(np.int8)
    patea = (1 - recibe1).astype(np.int8)
    tipo_k = np.zeros(n, dtype=np.int8)        # 0 normal, 1 tras safety
    pat_eq = np.zeros(n, dtype=np.int8)
    ot_hechas = np.zeros((n, 2), dtype=np.int8)
    tms = np.full((n, 2), 3, dtype=np.int8)       # tiempos muertos por equipo (3 por mitad; 2 en el tiempo extra de temporada regular)
    ot_per = np.zeros(n, dtype=np.int8)
    fue_ot = np.zeros(n, dtype=bool)
    min_ot = 900.0 if playoffs else 600.0
    # diagnósticos
    posesiones = np.zeros(n, dtype=np.int16)
    jugadas_pr = np.zeros(n, dtype=np.int16)
    motivos = np.zeros(len(MOTIVOS), dtype=np.int64)
    ko_suma = 0.0; ko_n = 0
    pasos = 0

    def reloj_restar(idx, seg):
        enot = per[idx] == 2
        gsr[idx[~enot]] -= seg[~enot]
        otc[idx[enot]] -= seg[enot]

    def fin_posesion(idx, motivo):
        if len(idx):
            motivos[motivo] += len(idx)
            enot = idx[per[idx] == 2]
            if len(enot):
                ot_hechas[enot, pos[enot]] += 1

    def nueva_posesion(idx, equipo, yl):
        pos[idx] = equipo
        Y[idx] = np.clip(yl, 1, 99)
        down[idx] = 1
        dist[idx] = np.minimum(10, Y[idx])
        fase[idx] = SCRIM
        posesiones[idx] += 1

    def revisar_ot(idx):
        """Fin del juego en tiempo extra: ambos completaron una posesión y el marcador no está igualado."""
        if len(idx) == 0:
            return
        i = idx[(per[idx] == 2) & (fase[idx] != FIN)]
        if len(i) == 0:
            return
        listo = (ot_hechas[i, 0] >= 1) & (ot_hechas[i, 1] >= 1) & (sc[i, 0] != sc[i, 1])
        fase[i[listo]] = FIN

    def anotar_td(idx, equipo, motivo):
        """TD de 'equipo' (ofensiva o defensa). Decide si hay PAT o si termina el tiempo extra."""
        if len(idx) == 0:
            return
        sc[idx, equipo] += 6
        fin_posesion(idx, motivo)
        fase[idx] = PAT
        pat_eq[idx] = equipo
        enot = per[idx] == 2
        if enot.any():
            i = idx[enot]; e = equipo[enot]
            defensivo = motivo == M_TDRIV
            ventaja = sc[i, e] > sc[i, 1 - e]
            ambos = (ot_hechas[i, 0] >= 1) & (ot_hechas[i, 1] >= 1)
            termina = ventaja & (ambos | defensivo)
            fase[i[termina]] = FIN

    while True:
        vivos = fase != FIN
        if not vivos.any():
            break
        pasos += 1
        if pasos > 600:
            raise RuntimeError("el simulador no terminó en 600 pasos")
        i_k = np.flatnonzero(fase == KICK)
        i_s = np.flatnonzero(fase == SCRIM)
        i_p = np.flatnonzero(fase == PAT)

        # ---------- PAT / conversión de 2 ----------
        if len(i_p):
            e = pat_eq[i_p]
            dif = np.clip(sc[i_p, e] - sc[i_p, 1 - e], -20, 20) + 20
            tarde = ((per[i_p] == 1) & (gsr[i_p] <= 900)) | (per[i_p] == 2)
            p2 = M["dec2"][tarde.astype(int), dif]
            u = rng.random((2, len(i_p)))
            va2 = u[0] < p2
            exito = u[1] < np.where(va2, M["p_2"], M["p_xp"])
            sc[i_p, e] += np.where(exito, np.where(va2, 2, 1), 0).astype(np.int16)
            fase[i_p] = KICK
            patea[i_p] = e
            tipo_k[i_p] = 0
            revisar_ot(i_p)

        # ---------- kickoff ----------
        if len(i_k):
            kk = patea[i_k]
            rec = (1 - kk).astype(np.int8)
            dif_k = sc[i_k, kk] - sc[i_k, rec]
            onside = (per[i_k] == 1) & (gsr[i_k] <= 300) & (dif_k <= -1) & (dif_k >= -16)
            res = np.zeros(len(i_k), dtype=np.int8); yl = np.zeros(len(i_k), dtype=np.int16)
            seg = np.zeros(len(i_k), dtype=np.float32)
            for nombre, sel in (("safety", tipo_k[i_k] == 1), ("onside", (tipo_k[i_k] == 0) & onside),
                                ("normal", (tipo_k[i_k] == 0) & ~onside)):
                if sel.any():
                    T = K[nombre]
                    j = rng.integers(0, len(T["res"]), sel.sum())
                    res[sel] = T["res"][j]; yl[sel] = T["yl"][j]; seg[sel] = T["seg"][j]
            reloj_restar(i_k, seg)
            # 0 recibe, 1 TD de retorno, 2 TD del que patea, 3 el que patea recupera
            r0 = res == 0; r3 = res == 3
            nueva_posesion(i_k[r0], rec[r0], yl[r0])
            ko_suma += float(yl[r0].sum()); ko_n += int(r0.sum())
            nueva_posesion(i_k[r3], kk[r3], yl[r3])
            r1 = np.flatnonzero(res == 1)
            if len(r1):
                pos[i_k[r1]] = rec[r1]; posesiones[i_k[r1]] += 1
                anotar_td(i_k[r1], rec[r1], M_TD)
            r2 = np.flatnonzero(res == 2)
            if len(r2):
                pos[i_k[r2]] = rec[r2]; posesiones[i_k[r2]] += 1
                anotar_td(i_k[r2], kk[r2], M_TDRIV)

        # ---------- jugada desde la línea de scrimmage ----------
        if len(i_s):
            ofe = pos[i_s]; dfe = (1 - ofe).astype(np.int8)
            enot = per[i_s] == 2
            hs = np.where(per[i_s] == 0, gsr[i_s] - 1800, np.where(enot, otc[i_s], gsr[i_s]))
            qtr = np.where(per[i_s] == 0, np.where(gsr[i_s] > 2700, 1, 2),
                           np.where(enot, 5, np.where(gsr[i_s] > 900, 3, 4)))
            dif_o = sc[i_s, ofe].astype(np.int64) - sc[i_s, dfe]
            rel = np.where(dif_o > 0, dfe, ofe)                  # quien necesita parar el reloj
            sit = situacion(qtr, hs, dif_o, tms[i_s, rel] >= 1)
            c = clave_l0(down[i_s], dist[i_s], Y[i_s], sit)
            jd = S["orden"][S["off"][c] + (rng.random(len(i_s)) * S["cnt"][c]).astype(np.int64)]   # decisión
            cat = S["cat"][jd].astype(np.int64)
            j = jd.copy()
            pr = cat <= 1
            if pr.any():                                                                      # resultado
                cr = clave_res(down[i_s[pr]], dist[i_s[pr]], Y[i_s[pr]], cat[pr], RITMO_SIM[sit[pr]])
                j[pr] = S["r_orden"][S["r_off"][cr] + (rng.random(int(pr.sum())) * S["r_cnt"][cr]).astype(np.int64)]
            for marca, eq in ((S["to_of"][j], ofe), (S["to_def"][j], dfe)):
                if marca.any():
                    k = i_s[marca]; e = eq[marca]
                    tms[k, e] = np.maximum(tms[k, e] - 1, 0)
            tipo = S["tipo"][j]
            y0 = Y[i_s].astype(np.int64)
            seg = S["seg"][j].astype(np.float64)

            # --- jugada normal (corrida, pase, penal, kneel, spike) ---
            n0 = np.flatnonzero(tipo == 0)
            if len(n0):
                ii = i_s[n0]; jj = j[n0]; yy = y0[n0]
                jugadas_pr[ii] += S["pr"][jj]
                av = S["avance"][jj].astype(np.int64)
                # TD de una jugada tomada de más cerca de la meta que la simulación: se conserva con
                # probabilidad S(y_sim)/S(y_origen) (Kaplan-Meier); si no, gana entre y_origen y y_sim − 1
                yo = S["yo"][jj].astype(np.int64)
                lejos = S["td_of"][jj] & (yy > yo)
                if lejos.any():
                    km = S["km"]
                    u = rng.random((2, int(lejos.sum())))
                    sigue_td = u[0] < km[np.minimum(yy[lejos], 100)] / km[yo[lejos]]
                    gan = yo[lejos] + np.floor(u[1] * (yy[lejos] - yo[lejos])).astype(np.int64)
                    av[lejos] = np.where(sigue_td, yy[lejos], gan)
                nuevo = yy - av
                tdo = (nuevo <= 0) & ~S["perdida"][jj] & ~S["td_def"][jj]
                tdd = S["td_def"][jj]
                sf = (S["saf"][jj] | (nuevo >= 100)) & ~tdo & ~tdd & ~S["perdida"][jj]
                pe = S["perdida"][jj] & ~tdd & ~tdo
                resto = ~(tdo | tdd | sf | pe)
                if tdo.any():
                    anotar_td(ii[tdo], pos[ii[tdo]], M_TD)
                if tdd.any():
                    anotar_td(ii[tdd], (1 - pos[ii[tdd]]).astype(np.int8), M_TDRIV)
                if sf.any():
                    k = ii[sf]
                    sc[k, 1 - pos[k]] += 2
                    fin_posesion(k, M_SAF)
                    fase[k] = KICK; patea[k] = pos[k]; tipo_k[k] = 1
                    fin_ot = k[per[k] == 2]
                    fase[fin_ot] = FIN
                if pe.any():
                    k = ii[pe]
                    spot = nuevo[pe]                       # posición en coordenadas de la ofensiva
                    yl_def = np.where(spot <= 0, 80, 100 - spot)
                    fin_posesion(k, M_TO)
                    revisar_ot(k)
                    vivos_k = k[fase[k] != FIN]
                    sel = fase[k] != FIN
                    nueva_posesion(vivos_k, (1 - pos[vivos_k]).astype(np.int8), yl_def[sel])
                if resto.any():
                    k = ii[resto]; a_ = av[resto]; nv = nuevo[resto]
                    pd_ = S["auto_pd"][jj[resto]] | (a_ >= dist[k])
                    rep = S["repite"][jj[resto]] & ~pd_
                    Y[k] = np.clip(nv, 1, 99)
                    down[k] = np.where(pd_, 1, np.where(rep, down[k], down[k] + 1))
                    dist[k] = np.where(pd_, np.minimum(10, Y[k]), np.maximum(1, dist[k] - a_))
                    dist[k] = np.minimum(dist[k], 99)
                    abajo = down[k] > 4
                    if abajo.any():
                        kk = k[abajo]
                        fin_posesion(kk, M_DOWNS)
                        revisar_ot(kk)
                        vv = kk[fase[kk] != FIN]
                        nueva_posesion(vv, (1 - pos[vv]).astype(np.int8), 100 - Y[vv].astype(np.int64))

            # --- punt ---
            n1 = np.flatnonzero(tipo == 1)
            if len(n1):
                ii = i_s[n1]; yy = y0[n1]
                b5 = np.minimum(yy // 5, 19)
                jp = P["orden"][P["off"][b5] + (rng.random(len(ii)) * P["cnt"][b5]).astype(np.int64)]
                seg[n1] = P["seg"][jp]
                rp = P["res"][jp]
                desp = (yy - P["Y"][jp].astype(np.int64))      # diferencia con la yarda del punt real
                rec = (1 - pos[ii]).astype(np.int8)
                # 0 recibe en Z; 1 TD del que recibe; 2 TD del que patea; 3 safety; 4 el que patea conserva
                fin_posesion(ii, M_PUNT)
                z = np.where(P["tb"][jp], 80, P["Z"][jp].astype(np.int64) - desp)
                a0 = rp == 0
                revisar_ot(ii[a0])
                v0 = ii[a0][fase[ii[a0]] != FIN]
                sel0 = fase[ii[a0]] != FIN
                nueva_posesion(v0, rec[a0][sel0], z[a0][sel0])
                a4 = rp == 4
                if a4.any():
                    k = ii[a4]
                    nueva_posesion(k, pos[k], P["Z"][jp[a4]].astype(np.int64) + desp[a4])
                a1 = np.flatnonzero(rp == 1)
                if len(a1):
                    k = ii[a1]
                    posesiones[k] += 1
                    pos[k] = rec[a1]
                    anotar_td(k, rec[a1], M_TD)              # posesión del que recibe que termina en TD
                a2 = np.flatnonzero(rp == 2)
                if len(a2):
                    k = ii[a2]
                    sc[k, pos[k]] += 6
                    fase[k] = PAT; pat_eq[k] = pos[k]
                a3 = np.flatnonzero(rp == 3)
                if len(a3):
                    k = ii[a3]
                    sc[k, rec[a3]] += 2
                    fase[k] = KICK; patea[k] = pos[k]; tipo_k[k] = 1

            # --- gol de campo ---
            n2 = np.flatnonzero(tipo == 2)
            if len(n2):
                ii = i_s[n2]; yy = y0[n2]
                seg[n2] = M["seg_fg"][rng.integers(0, len(M["seg_fg"]), len(ii))]
                bueno = rng.random(len(ii)) < prob_fg(M["beta"], yy + 18.0)
                k = ii[bueno]
                if len(k):
                    sc[k, pos[k]] += 3
                    fin_posesion(k, M_FG)
                    fase[k] = KICK; patea[k] = pos[k]; tipo_k[k] = 0
                    revisar_ot(k)
                    # muerte súbita: si ya ambos poseyeron, el FG que pone adelante termina el juego
                k = ii[~bueno]
                if len(k):
                    yl_def = np.minimum(80, 92 - yy[~bueno])
                    fin_posesion(k, M_FGX)
                    revisar_ot(k)
                    vv = k[fase[k] != FIN]
                    sel = fase[k] != FIN
                    nueva_posesion(vv, (1 - pos[vv]).astype(np.int8), yl_def[sel])

            reloj_restar(i_s, seg)

        # ---------- reloj: fin de mitad, de reglamento y de tiempo extra ----------
        listos = (fase == KICK) | (fase == SCRIM)
        m1 = listos & (per == 0) & (gsr <= 1800)
        if m1.any():
            k = np.flatnonzero(m1)
            fin_posesion(k[fase[k] == SCRIM], M_MITAD)
            gsr[k] = 1800; per[k] = 1; tms[k] = 3
            fase[k] = KICK; patea[k] = recibe1[k]; tipo_k[k] = 0
        m2 = listos & (per == 1) & (gsr <= 0)
        if m2.any():
            k = np.flatnonzero(m2)
            fin_posesion(k[fase[k] == SCRIM], M_MITAD)
            gsr[k] = 0
            empate = sc[k, 0] == sc[k, 1]
            fase[k[~empate]] = FIN
            ko = k[empate]
            if len(ko):
                per[ko] = 2; otc[ko] = min_ot; fue_ot[ko] = True; ot_per[ko] = 1
                fase[ko] = KICK; patea[ko] = (rng.random(len(ko)) < 0.5).astype(np.int8); tipo_k[ko] = 0
                ot_hechas[ko] = 0
                tms[ko] = 3 if playoffs else 2
        m3 = listos & (per == 2) & (otc <= 0)
        if m3.any():
            k = np.flatnonzero(m3)
            if playoffs:
                sigue_ot = (sc[k, 0] == sc[k, 1]) & (ot_per[k] < 6)
                otc[k[sigue_ot]] = min_ot; ot_per[k[sigue_ot]] += 1
                fase[k[~sigue_ot]] = FIN
            else:
                fin_posesion(k[fase[k] == SCRIM], M_MITAD)
                fase[k] = FIN

    margen = sc[:, 0].astype(np.int64) - sc[:, 1].astype(np.int64)
    total = sc[:, 0].astype(np.int64) + sc[:, 1].astype(np.int64)
    return dict(margen=margen, total=total, puntos=sc.astype(np.int64).ravel(), fue_ot=fue_ot,
                empate=margen == 0, posesiones=posesiones.astype(np.int64), jugadas=jugadas_pr.astype(np.int64),
                motivos=motivos, ko_suma=ko_suma, ko_n=ko_n, pasos=pasos)


# --------------------------------------------------------------------------------------
# 5. Referencias reales (24A) y criterios
# --------------------------------------------------------------------------------------
def wilson(k, n, z):
    p = k / n; den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return c - h, c + h


def boot_de(x, rng, B=4000):
    idx = rng.integers(0, len(x), (B, len(x)))
    return np.percentile(x[idx].std(axis=1, ddof=1), [0.5, 99.5])


def referencias(games, pbp):
    rng = np.random.default_rng(SEMILLA + 7)
    g = games.filter(pl.col("season").is_between(2021, 2025) & pl.col("result").is_not_null())
    hs = g["home_score"].to_numpy().astype(float); aw = g["away_score"].to_numpy().astype(float)
    m = hs - aw; t = hs + aw
    sp = g["spread_line"].to_numpy().astype(float); tl = g["total_line"].to_numpy().astype(float)
    ok = ~np.isnan(sp) & ~np.isnan(tl)
    rm = (m - sp)[ok]; rt = (t - tl)[ok]
    r = dict(n_juegos=int(g.height), n_reg=int((g["game_type"] == "REG").sum()))
    g2 = g.filter(pl.col("season") >= 2024)
    t2 = (g2["home_score"] + g2["away_score"]).to_numpy().astype(float)
    r["total_2425"] = float(t2.mean()); r["ee_total_2425"] = float(t2.std(ddof=1) / np.sqrt(len(t2)))
    r["n_2425"] = int(len(t2))
    r["c1"] = (r["total_2425"] - Z99 * r["ee_total_2425"], r["total_2425"] + Z99 * r["ee_total_2425"])
    r["total_2125"] = float(t.mean()); r["pts_equipo"] = float(np.concatenate([hs, aw]).mean())
    r["de_res_margen"] = float(rm.std(ddof=1)); r["de_res_total"] = float(rt.std(ddof=1))
    lm, um = boot_de(rm, rng); lt, ut = boot_de(rt, rng)
    r["ic_de_res_margen"] = (float(lm), float(um)); r["ic_de_res_total"] = (float(lt), float(ut))
    r["c2"] = (float(np.sqrt(lm ** 2 - ERROR_MERCADO ** 2)), float(um))
    r["c3"] = (float(np.sqrt(lt ** 2 - ERROR_MERCADO ** 2)), float(ut))
    cer = g.filter(pl.col("spread_line").abs() <= 3)
    am = (cer["home_score"] - cer["away_score"]).abs().to_numpy()
    n = len(am); k3 = int((am == 3).sum()); k7 = int((am == 7).sum())
    kot = int(cer["overtime"].fill_null(0).sum())
    r.update(n_parejos=n, p3=k3 / n, p7=k7 / n, p_ot_parejos=kot / n,
             c4=tuple(float(x) for x in wilson(k3, n, Z99)), c5=tuple(float(x) for x in wilson(k7, n, Z99)),
             ic_ot_parejos=tuple(float(x) for x in wilson(kot, n, Z99)),
             p_le3=float((am <= 3).mean()), p_ge14=float((am >= 14).mean()), p_empate=float((am == 0).mean()))
    v, c = np.unique(am, return_counts=True)
    o = np.argsort(-c, kind="stable")
    r["ranking"] = [(int(v[i]), float(c[i] / n)) for i in o[:6]]
    r["p_ot_todos"] = float(g["overtime"].fill_null(0).mean())
    pts = np.concatenate([hs, aw])
    r["hist_puntos"] = {int(x): float((pts == x).mean()) for x in range(0, 61)}
    # diagnósticos de proceso (jugada por jugada)
    juegos = pbp["game_id"].n_unique()
    r["pase_corrida_por_juego"] = float(pbp.filter(pl.col("play_type").is_in(["pass", "run"])).height / juegos)
    dr = (pbp.filter(pl.col("posteam").is_not_null() & pl.col("fixed_drive").is_not_null())
          .unique(subset=["game_id", "fixed_drive"], keep="first"))
    r["posesiones_por_juego"] = float(dr.height / juegos)
    vc = dr["fixed_drive_result"].value_counts()
    tot = vc["count"].sum()
    r["motivos"] = {row["fixed_drive_result"]: row["count"] / tot for row in vc.iter_rows(named=True)}
    ko = (dr.filter((pl.col("drive_start_transition") == "KICKOFF") & (pl.col("season") == 2025))
          .with_columns(pl.col("drive_start_yard_line").str.split(" ").alias("sp")))
    ko = ko.with_columns(pl.when(pl.col("sp").list.len() == 2).then(pl.col("sp").list.get(0)).otherwise(pl.lit("MID")).alias("lado"),
                         pl.col("sp").list.last().cast(pl.Int32, strict=False).alias("num"))
    ko = ko.with_columns(pl.when(pl.col("lado") == "MID").then(50).when(pl.col("lado") == pl.col("posteam"))
                         .then(pl.col("num")).otherwise(100 - pl.col("num")).alias("ini"))
    r["inicio_kickoff_2025"] = float(ko["ini"].mean())
    return r


def evaluar(ref, sim, c0):
    am = np.abs(sim["margen"])
    v, c = np.unique(am, return_counts=True)
    o = np.argsort(-c, kind="stable")
    rank = [(int(v[i]), float(c[i] / len(am))) for i in o[:6]]
    tot_m = float(sim["total"].mean())
    de_m = float(sim["margen"].std(ddof=1)); de_t = float(sim["total"].std(ddof=1))
    p3 = float((am == 3).mean()); p7 = float((am == 7).mean())
    dentro = lambda x, ab: ab[0] <= x <= ab[1]  # noqa: E731
    filas = [
        ("C0", "Rendimiento", f"{c0['seg']:.1f} s; pico {c0['pico_mb']:.0f} MB; bot {c0['bot']}",
         "< 180 s, ≤ 1.536 MB, bot activo < 350 MB", c0["pasa"]),
        ("C1", "Nivel: total medio", f"{tot_m:.2f}", f"[{ref['c1'][0]:.2f}; {ref['c1'][1]:.2f}]", dentro(tot_m, ref["c1"])),
        ("C2", "DE del margen", f"{de_m:.2f}", f"[{ref['c2'][0]:.2f}; {ref['c2'][1]:.2f}]", dentro(de_m, ref["c2"])),
        ("C3", "DE del total", f"{de_t:.2f}", f"[{ref['c3'][0]:.2f}; {ref['c3'][1]:.2f}]", dentro(de_t, ref["c3"])),
        ("C4", "P(|margen| = 3)", f"{100 * p3:.1f} %", f"[{100 * ref['c4'][0]:.1f} %; {100 * ref['c4'][1]:.1f} %]", dentro(p3, ref["c4"])),
        ("C5", "P(|margen| = 7)", f"{100 * p7:.1f} %", f"[{100 * ref['c5'][0]:.1f} %; {100 * ref['c5'][1]:.1f} %]", dentro(p7, ref["c5"])),
        ("C6", "Márgenes más frecuentes", ", ".join(str(x[0]) for x in rank[:3]), "3 primero y 7 segundo",
         rank[0][0] == 3 and rank[1][0] == 7),
    ]
    return filas, rank


# --------------------------------------------------------------------------------------
# 6. Servidor: memoria, bot, Telegram
# --------------------------------------------------------------------------------------
def pico_mb():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


def estado_bot():
    try:
        activo = subprocess.run(["systemctl", "is-active", "nfl-ev-bot"], capture_output=True, text=True, timeout=10).stdout.strip()
        memo = subprocess.run(["systemctl", "show", "nfl-ev-bot", "-p", "MemoryCurrent", "--value"],
                              capture_output=True, text=True, timeout=10).stdout.strip()
        mb = int(memo) / 2 ** 20 if memo.isdigit() else None
        return activo or "desconocido", mb
    except Exception:  # noqa: BLE001
        return "desconocido", None


def telegram(texto, archivo=None):
    if not CONFIG_BOT.exists():
        log("Telegram: no encontré ~/nfl_ev/config.ini; se omite el envío")
        return False
    cfg = configparser.ConfigParser()
    cfg.read(CONFIG_BOT)
    try:
        token = cfg["telegram"]["token"].strip(); chat = cfg["telegram"]["chat_id"].strip()
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
                r = requests.post(url + "/sendDocument", data={"chat_id": chat}, files={"document": (archivo.name, fh)}, timeout=60)
                ok &= r.ok
    except Exception as e:  # noqa: BLE001
        log(f"Telegram: error al enviar ({type(e).__name__})")   # sin mostrar la URL (lleva el token)
        return False
    log("Telegram: enviado" if ok else "Telegram: la API respondió con error")
    return ok


# --------------------------------------------------------------------------------------
# 7. Principal
# --------------------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rapido", action="store_true")
    ap.add_argument("--sin-telegram", action="store_true")
    args = ap.parse_args()
    if os.nice(0) < 10:
        os.nice(10 - os.nice(0))
    SALIDA.mkdir(parents=True, exist_ok=True)
    candado = open(SALIDA / ".candado", "w")
    try:
        fcntl.flock(candado, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit("Ya hay una corrida de sprint1.py en marcha; no lanzo otra.")
    inicio = time.time()
    log(f"sprint1.py {VERSION} · Python {platform.python_version()} · numpy {np.__version__} · polars {pl.__version__} · nice {os.nice(0)}")

    games, pbp = preparar_datos()
    log(f"datos: {games.height} juegos en el calendario, {pbp.height} filas de jugada por jugada · pico {pico_mb():.0f} MB")
    M = construir_modelo(pbp, games)
    log(f"modelo: {json.dumps(M['resumen'], ensure_ascii=False)}")
    ref = referencias(games, pbp)
    del pbp
    log(f"referencias: C1 {ref['c1']}, C2 {ref['c2']}, C3 {ref['c3']}, C4 {ref['c4']}, C5 {ref['c5']}")

    # ---- C0: rendimiento con una semana de 16 juegos × 10.000 simulaciones en paralelo ----
    n_c0 = 16 * (1_000 if args.rapido else 10_000)
    bot_antes = estado_bot()
    t0 = time.time()
    simular(M, n_c0, False, np.random.default_rng(SEMILLA + 1))
    seg_c0 = time.time() - t0
    bot_despues = estado_bot()
    pico = pico_mb()
    bot_mb = max([x for x in (bot_antes[1], bot_despues[1]) if x is not None], default=None)
    bot_ok = bot_despues[0] in ("active", "desconocido") and (bot_mb is None or bot_mb < 350)
    c0 = dict(seg=seg_c0, pico_mb=pico, n=n_c0,
              bot=f"{bot_despues[0]}" + (f", {bot_mb:.0f} MB" if bot_mb is not None else ""),
              pasa=(seg_c0 < 180) and (pico <= 1536) and bot_ok)
    log(f"C0: {n_c0} simulaciones en {seg_c0:.1f} s · pico {pico:.0f} MB · bot {c0['bot']}")

    # ---- validación: 20 tandas de 10.000 (19 de temporada regular y 1 de playoffs) ----
    tandas = 5 if args.rapido else 20
    tam = 2_000 if args.rapido else 10_000
    partes = []
    t0 = time.time()
    for b in range(tandas):
        partes.append(simular(M, tam, playoffs=(b == tandas - 1), rng=np.random.default_rng(SEMILLA + 100 + b)))
    seg_val = time.time() - t0
    sim = {k: np.concatenate([p[k] for p in partes]) for k in ("margen", "total", "puntos", "fue_ot", "empate", "posesiones", "jugadas")}
    sim["motivos"] = np.sum([p["motivos"] for p in partes], axis=0)
    ko_media = sum(p["ko_suma"] for p in partes) / max(sum(p["ko_n"] for p in partes), 1)
    pasos_max = max(p["pasos"] for p in partes)
    log(f"validación: {len(sim['margen'])} juegos en {seg_val:.1f} s · pasos máx {pasos_max} · pico {pico_mb():.0f} MB")

    filas, rank = evaluar(ref, sim, c0)
    acepta = all(f[4] for f in filas)
    am = np.abs(sim["margen"])
    mot = sim["motivos"] / sim["motivos"].sum()
    diag = [
        ("Posesiones por juego", f"{sim['posesiones'].mean():.2f}", f"{ref['posesiones_por_juego']:.2f}"),
        ("Pases + corridas por juego", f"{sim['jugadas'].mean():.1f}", f"{ref['pase_corrida_por_juego']:.1f}"),
        ("Puntos por equipo", f"{sim['puntos'].mean():.2f}", f"{ref['pts_equipo']:.2f} (2021-25)"),
        ("Total medio 2021-2025 (referencia de contexto)", f"{sim['total'].mean():.2f}", f"{ref['total_2125']:.2f}"),
        ("Inicio tras kickoff (yarda propia)", f"{100 - ko_media:.1f}", f"{ref['inicio_kickoff_2025']:.1f} (2025)"),
        ("Tiempo extra", f"{100 * sim['fue_ot'].mean():.1f} %", f"{100 * ref['p_ot_parejos']:.1f} % parejos; {100 * ref['p_ot_todos']:.1f} % todos"),
        ("Empates", f"{100 * sim['empate'].mean():.2f} %", f"{100 * ref['p_empate']:.2f} % parejos"),
        ("P(|margen| ≤ 3)", f"{100 * (am <= 3).mean():.1f} %", f"{100 * ref['p_le3']:.1f} % parejos"),
        ("P(|margen| ≥ 14)", f"{100 * (am >= 14).mean():.1f} %", f"{100 * ref['p_ge14']:.1f} % parejos"),
        ("Márgenes más frecuentes", ", ".join(f"{a} ({100 * b:.1f} %)" for a, b in rank[:5]),
         ", ".join(f"{a} ({100 * b:.1f} %)" for a, b in ref["ranking"][:5])),
    ]
    for i, nombre in enumerate(MOTIVOS):
        diag.append((f"Posesión termina en: {nombre}", f"{100 * mot[i]:.1f} %", f"{100 * ref['motivos'].get(nombre, 0):.1f} %"))

    # ---- salida ----
    ahora = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lineas = [f"SPRINT 1 — motor nfl_sim {VERSION}", f"Corrida: {ahora} · {platform.node()} · {'PRUEBA RÁPIDA' if args.rapido else 'oficial'}",
              f"Veredicto: {'ACEPTADO (C0-C6 pasan)' if acepta else 'NO ACEPTADO: falla ' + ', '.join(f[0] for f in filas if not f[4])}",
              "", "Criterios (24A):"]
    for f in filas:
        lineas.append(f"  {f[0]} {'✅' if f[4] else '❌'} {f[1]}: {f[2]}  · pasa si {f[3]}")
    lineas += ["", "Se reporta, no decide (simulado · real):"]
    for d in diag:
        lineas.append(f"  {d[0]}: {d[1]} · {d[2]}")
    lineas += ["", f"Modelo: {M['resumen']['jugadas_scrimmage']} jugadas de scrimmage 2021-25; celdas usadas por nivel {M['resumen']['celdas_por_nivel']}; "
               f"{M['resumen']['kickoffs_2025_normal']} kickoffs 2025 + {M['resumen']['kickoffs_2025_onside']} en situación de onside; "
               f"XP {100 * M['p_xp']:.1f} %, 2 pts {100 * M['p_2']:.1f} %.",
               f"Validación: {len(sim['margen'])} juegos ({tandas} tandas, la última de playoffs) en {seg_val:.1f} s; pasos máx {pasos_max}.",
               f"Pico de memoria del proceso: {pico_mb():.0f} MB. Duración total: {time.time() - inicio:.0f} s.",
               "Advertencia: mide consistencia con los datos de origen (dentro de muestra); no valida predicción."]
    resumen = "\n".join(lineas)
    print(resumen, flush=True)
    (SALIDA / "resumen_s1.txt").write_text(resumen + "\n", encoding="utf-8")
    with open(SALIDA / "criterios_s1.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh); w.writerow(["criterio", "medida", "simulado", "pasa_si", "pasa"])
        for f in filas:
            w.writerow([f[0], f[1], f[2], f[3], int(f[4])])
    with open(SALIDA / "diagnostico_s1.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh); w.writerow(["medida", "simulado", "real"])
        w.writerows(diag)
    with open(SALIDA / "margenes_s1.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh); w.writerow(["margen_abs", "p_simulado"])
        for x in range(0, 50):
            w.writerow([x, f"{(am == x).mean():.5f}"])
    pts = sim["puntos"]
    with open(SALIDA / "puntos_s1.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh); w.writerow(["puntos_equipo", "p_simulado", "p_real_2021_25"])
        for x in range(0, 61):
            w.writerow([x, f"{(pts == x).mean():.5f}", f"{ref['hist_puntos'][x]:.5f}"])
    (SALIDA / "referencias_s1.json").write_text(json.dumps({k: v for k, v in ref.items() if k != "hist_puntos"},
                                                           ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (SALIDA / "modelo_s1.json").write_text(json.dumps(M["resumen"], ensure_ascii=False, indent=1), encoding="utf-8")
    zp = SALIDA / "sprint1_resultados.zip"
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        for nombre in ("resumen_s1.txt", "criterios_s1.csv", "diagnostico_s1.csv", "margenes_s1.csv",
                       "puntos_s1.csv", "referencias_s1.json", "modelo_s1.json"):
            z.write(SALIDA / nombre, nombre)
    log(f"salida en {SALIDA}")
    if not args.sin_telegram:
        telegram(resumen, zp)
    log("== LISTO")


if __name__ == "__main__":
    main()
