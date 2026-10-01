#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sprint2.py — Motor nfl_sim, Sprint 2 (Bloque 2, sección 6b de contexto_proyecto_nfl.md)

Qué hace
  1. Descarga (una vez) de nflverse el calendario y la jugada por jugada a ~/nfl_sim/datos/: 2021-2025 para
     la base a nivel liga (22A, igual que el Sprint 1) y 2019-2025 para calificar a los equipos.
  2. Base a nivel liga (la del Sprint 1, con los mecanismos corregidos en el Sprint 2): campo en 14 tramos;
     penales a mitad de distancia; safeties con censura; reloj del final en 7 tramos (2:00-1:01 y 1:00-0:31
     separados); respaldos que conservan el tramo de tiempo; regla del reloj (quien necesita parar el reloj no
     lo deja vencer: tiempo muerto con 2-5 s o snap apurado).
  3. Capa de equipos (25A-27A): fuerza de cada equipo por su propio EPA y tasa de éxito por jugada (pase y
     corrida, ataque y defensa), con peso decreciente a lo antiguo, arrastre entre temporadas y ajuste hacia el
     promedio, sin usar líneas; QB titular contra el QB de referencia del equipo, encogido hacia el nivel de
     reemplazo (26A); una sola localía para la liga, de las 5 temporadas previas (27A). En el simulador, la
     fuerza corre el EPA medio de cada pase y corrida (inclinación exponencial por remuestreo ponderado).
  4. Evalúa S2-C0 a S2-C8 (28A, registrados el 1-oct-2026 antes de construir): rendimiento, nivel liga sin
     retroceso, safeties, empates, tiempo extra y la prueba hacia adelante 2023-2025 contra el cierre (una sola
     vez). Entrega resumen, CSV y zip, y los manda por Telegram.

Uso (en ~/nfl_sim):
  (nohup nice -n 10 venv/bin/python -u sprint2.py > salidas/sprint2.log 2>&1 &)
Opciones (solo para pruebas): --rapido (menos simulaciones) · --sin-telegram ·
  --ensayo (la "prueba" corre con 2022, temporada de ajuste; sin veredicto) · --sin-prueba (sin 2023-2025)

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

VERSION = "s2-v1 (1-oct-2026)"
BASE = Path(__file__).resolve().parent
DATOS = BASE / "datos"
SALIDA = BASE / "salidas" / "sprint2"
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
DUR_JUGADA = 5.0                   # duración de una jugada hasta el silbato (pase incompleto ≤ 2:00: mediana 5 s, 2021-25)
MIN_APURO = 12.0                   # mínimo entre un snap con reloj corriendo y el siguiente apurado (p10 de "jugada → spike": 12 s)
TEMP_PRUEBA = [2023, 2024, 2025]   # prueba hacia adelante (28A): 855 juegos, se corre una sola vez
FILTRO_SPREAD, FILTRO_TOTAL = 3.5, 5.0   # filtro de alucinación (Orden 7) contra el cierre, para S2-C8

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
            "posteam_timeouts_remaining", "defteam_timeouts_remaining", "epa"]
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
_LUT_YL = np.zeros(101, dtype=np.int16)            # yardas a la zona de anotación → 14 tramos
for _y in range(101):
    _LUT_YL[_y] = (0 if _y <= 2 else 1 if _y <= 5 else 2 if _y <= 10 else 3 if _y <= 15 else
                   4 if _y <= 20 else 5 if _y <= 30 else 6 if _y <= 40 else 7 if _y <= 50 else
                   8 if _y <= 60 else 9 if _y <= 70 else 10 if _y <= 80 else 11 if _y <= 90 else
                   12 if _y <= 95 else 13)
N_DIST, N_YL = 10, 14
_DB3 = np.array([0, 0, 0, 1, 1, 1, 2, 2, 2, 2], dtype=np.int64)          # distancia: 1-3, 4-9, 10+
# Agrupaciones gruesas del campo que conservan finos los tramos junto a las DOS metas
# (cerca de la propia meta, mezclar posiciones fabrica safeties que no ocurren).
_YB9 = np.array([0, 1, 2, 3, 4, 5, 5, 6, 6, 7, 7, 8, 9, 10], dtype=np.int64)  # 1-2, 3-5, 6-10, 11-15, 16-20, 21-40, 41-60, 61-80, 81-90, 91-95, 96-99
_YB5 = np.array([0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 4, 5, 6], dtype=np.int64)   # 1-10, 11-20, 21-40, 41-60, 61-90, 91-95, 96-99
_YB3 = np.array([0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 3, 4], dtype=np.int64)   # ≤20, 21-60, 61-90, 91-95, 96-99
N_YB9, N_YB5, N_YB3 = 11, 7, 5
# Campo en tres zonas (en rango de FG ≤ 40, 41-60, 61-99) y en dos (≤ 40 o no): último respaldo antes de
# dejar de lado el reloj en las situaciones raras del final (p. ej. empate con 0:08 en la propia 30)
_YBR3 = np.array([0, 0, 0, 0, 0, 0, 0, 1, 1, 2, 2, 2, 2, 2], dtype=np.int64)
_YBR2 = np.array([0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1], dtype=np.int64)

# ---- Situación (264): decide la jugada ----
#   0-27    juego normal: 7·fase + diferencia (fase: 1er cuarto, 2º antes de 2:00, 3er, 4º antes de 5:00;
#           diferencia: +17 o más, +9..+16, +1..+8, 0, −1..−8, −9..−16, −17 o menos)
#   28-39   final de la 1ª mitad: 28 + 2·(tiempo − 1) + tm (tiempo 1-6, ver abajo)
#   40-151  últimos 5:00 del 4º cuarto: 40 + 2·(7·dif + tiempo) + tm
#   152-263 tiempo extra: igual con base 152
#           dif: +9 o más, +4..+8, +1..+3, 0, −1..−3, −4..−8, −9..−16, −17 o menos
#           tiempo (7 tramos): > 2:00, 2:00-1:01, 1:00-0:31, 0:30-0:21, 0:20-0:11, 0:10-0:05, ≤ 0:04
#           (en tiempo extra, el reloj del periodo)
#           tm: 1 si el equipo que necesita parar el reloj (la defensa si la ofensiva gana; si no, la ofensiva) tiene tiempos muertos
# Los segundos finales van en tramos finos porque ahí se decide si se patea el FG (medido 2021-2025: con ≤ 0:04
# y en rango se patea 70-96 % de las veces; con 0:05-0:10, 9-50 %; con 0:11-0:30, casi nunca). El tramo
# 2:00-0:31 se parte en dos (s2): con 1:01-2:00 un pase consume 13,7 s y una corrida 22 s hasta el siguiente
# snap; con 0:31-1:00, 8,5 s y 11,5 s (final de la 1ª mitad y 4º cuarto, 2021-2025). Juntos, el equipo que
# empata con 0:50 jugaba con el reloj de quien tiene 1:50 y no llegaba al rango de FG.
N_TG = 7
BASE_H1, BASE_Q4, BASE_OT = 28, 28 + 2 * (N_TG - 1), 28 + 2 * (N_TG - 1) + 2 * 8 * N_TG
N_SIT = BASE_OT + 2 * 8 * N_TG
_SITMED = np.zeros(N_SIT, dtype=np.int64)        # nivel intermedio: fase o diferencia, sin tiempo fino ni tiempos muertos
# Grupo de tiempo: junta contextos con la misma urgencia y el mismo tramo de tiempo (para celdas raras):
#   0-3 fases normales · 4-10 "necesita FG" (fin de 1ª mitad, o pierde por 1-3 al final) por tiempo ·
#   11-17 "gasta reloj" (gana al final) · 18-24 "necesita TD" (pierde por 4+ al final) ·
#   25-31 empatado al final (juega para el FG y cuida el reloj; no hay sesgo de calidad: ninguno va ganando)
G_FG, G_GANA, G_TD, G_EMP = 4, 4 + N_TG, 4 + 2 * N_TG, 4 + 3 * N_TG
N_GT = 4 + 4 * N_TG
_GT = np.zeros(N_SIT, dtype=np.int64)
_TM = np.zeros(N_SIT, dtype=np.int64)            # bit de tiempos muertos de cada situación
for _f in range(4):
    _SITMED[_f * 7:(_f + 1) * 7] = _f
    _GT[_f * 7:(_f + 1) * 7] = _f
for _tg in range(1, N_TG):
    for _tm in range(2):
        _s = BASE_H1 + 2 * (_tg - 1) + _tm
        _SITMED[_s] = 4
        _GT[_s] = G_FG + _tg
        _TM[_s] = _tm
for _base in (BASE_Q4, BASE_OT):
    for _dg in range(8):
        for _tg in range(N_TG):
            for _tm in range(2):
                _s = _base + 2 * (N_TG * _dg + _tg) + _tm
                _SITMED[_s] = 5 + _dg
                _GT[_s] = (G_GANA + _tg) if _dg <= 2 else (G_EMP + _tg) if _dg == 3 else (G_FG + _tg) if _dg == 4 else (G_TD + _tg)
                _TM[_s] = _tm
N_MED = 13
# ---- Ritmo: muestrea el RESULTADO de pases y corridas sin el marcador exacto ----
#   0-3 fases normales; 4 + 2·(grupo de tiempo − 4) + (1 si SIN tiempos muertos) para los grupos 4 en adelante.
# En la SIMULACIÓN, quien "necesita TD" con ≤ 2:00 toma el resultado de "necesita FG" del mismo tramo
# (que incluye el apuro del final de la 1ª mitad, jugado por todos los equipos): quien pierde por 4+ al final
# de un juego real suele ser el peor equipo, y eso no debe pasar a dos equipos iguales.
N_RITMO = 4 + 2 * (N_GT - 4)
RITMO = np.where(_GT < 4, _GT, 4 + 2 * (_GT - 4) + (1 - _TM))
# Ritmo grueso (para celdas de resultado con pocas jugadas): junta con y sin tiempos muertos, y el empatado
# con "necesita FG" del mismo tramo, antes de dejar de lado el reloj.
N_RG = G_EMP
_RG = np.zeros(N_RITMO, dtype=np.int64)
_RG[:4] = np.arange(4)
for _g in range(4, N_GT):
    _RG[4 + 2 * (_g - 4)] = _RG[4 + 2 * (_g - 4) + 1] = (_g - G_EMP + G_FG) if _g >= G_EMP else _g
_GT_SIM = np.where((_GT >= G_TD + 1) & (_GT < G_EMP), _GT - G_TD + G_FG, _GT)   # "necesita TD" con ≤ 2:00 → "necesita FG" del mismo tramo
RITMO_SIM = np.where(_GT_SIM < 4, _GT_SIM, 4 + 2 * (_GT_SIM - 4) + (1 - _TM))
# El empatado al final que todavía NO está en rango de FG (más de 40 yardas de la meta) juega con apuro,
# como "necesita FG" del mismo tramo; ya en rango, toma el grupo del empatado (gasta reloj y patea).
_ES_EMP = _GT >= G_EMP
_GT_EMP_FUERA = np.where(_ES_EMP, _GT - G_EMP + G_FG, _GT)
RITMO_SIM_FUERA = np.where(_ES_EMP, 4 + 2 * (_GT_EMP_FUERA - 4) + (1 - _TM), RITMO_SIM)


def ritmo_sim(sit, yl):
    """Grupo de ritmo para muestrear el resultado en la simulación (ver arriba)."""
    return np.where(yl > 40, RITMO_SIM_FUERA[sit], RITMO_SIM[sit])


def _tramo(hs):
    return np.select([hs > 120, hs > 60, hs > 30, hs > 20, hs > 10, hs > 4], [0, 1, 2, 3, 4, 5], 6)


def situacion(qtr, hs, diff, con_tm):
    """Situación del juego (0-263); ver la tabla de arriba. qtr: 1-4, 5 = tiempo extra; hs: segundos que
    quedan en la mitad (o en el periodo extra); diff: puntos de la ofensiva menos los de la defensa;
    con_tm: el equipo que necesita parar el reloj tiene al menos un tiempo muerto."""
    qtr = np.asarray(qtr); hs = np.asarray(hs); diff = np.asarray(diff)
    tm = np.asarray(con_tm).astype(np.int64)
    fase = np.select([qtr == 1, qtr == 2, qtr == 3], [0, 1, 2], 3)
    dgn = np.select([diff >= 17, diff >= 9, diff >= 1, diff == 0, diff >= -8, diff >= -16], [0, 1, 2, 3, 4, 5], 6)
    s = fase * 7 + dgn
    tg = _tramo(hs)
    s = np.where((qtr == 2) & (hs <= 120), BASE_H1 + 2 * (tg - 1) + tm, s)
    dg = np.select([diff >= 9, diff >= 4, diff >= 1, diff == 0, diff >= -3, diff >= -8, diff >= -16], [0, 1, 2, 3, 4, 5, 6], 7)
    s = np.where((qtr == 4) & (hs <= 300), BASE_Q4 + 2 * (N_TG * dg + tg) + tm, s)
    s = np.where(qtr >= 5, BASE_OT + 2 * (N_TG * dg + tg) + tm, s)
    return s.astype(np.int64)


def _niveles(d, db, yb, s):
    """Clave de cada nivel de agregación (L0 el más fino, L10 el más grueso). Primero se engruesa el campo
    y el down; después se juntan los tiempos muertos; después se juntan contextos con la misma urgencia y el
    mismo tramo de tiempo; recién al final se deja de lado el tiempo."""
    sin_tm = s - _TM[s]
    d4 = (d == 3).astype(np.int64)
    gt = _GT[s]
    l0 = ((d * N_DIST + db) * N_YL + yb) * N_SIT + s
    l1 = ((d * 3 + _DB3[db]) * N_YB9 + _YB9[yb]) * N_SIT + s
    l2 = (d4 * N_YB9 + _YB9[yb]) * N_SIT + s
    l3 = (d4 * N_YB9 + _YB9[yb]) * N_SIT + sin_tm
    l4 = (d4 * N_YB5 + _YB5[yb]) * N_SIT + sin_tm
    l5 = (d4 * N_YB9 + _YB9[yb]) * N_GT + gt
    l6 = (d4 * N_YB5 + _YB5[yb]) * N_GT + gt
    l7 = (d4 * 3 + _YBR3[yb]) * N_GT + gt
    l8 = (d4 * 2 + _YBR2[yb]) * N_GT + gt
    # empatado EN RANGO de FG: decide como quien necesita un FG en el mismo tramo (4º down en la 31 rival con
    # 0:25: se patea); fuera de rango se conserva el grupo del empatado (despeja o arrodilla para ir al tiempo extra)
    gtm = np.where((gt >= G_EMP) & (_YBR2[yb] == 0), gt - G_EMP + G_FG, gt)
    l8b = (d4 * 2 + _YBR2[yb]) * N_GT + gtm
    l9 = ((d * N_DIST + db) * N_YL + yb) * N_MED + _SITMED[s]
    l10 = (d * N_DIST + db) * N_YL + yb
    l11 = (d * N_DIST + db) * N_YB3 + _YB3[yb]
    l12 = d * N_DIST + db
    return [l0, l1, l2, l3, l4, l5, l6, l7, l8, l8b, l9, l10, l11, l12]


TAM_NIVEL = [4 * N_DIST * N_YL * N_SIT, 4 * 3 * N_YB9 * N_SIT, 2 * N_YB9 * N_SIT, 2 * N_YB9 * N_SIT, 2 * N_YB5 * N_SIT,
             2 * N_YB9 * N_GT, 2 * N_YB5 * N_GT, 2 * 3 * N_GT, 2 * 2 * N_GT, 2 * 2 * N_GT,
             4 * N_DIST * N_YL * N_MED, 4 * N_DIST * N_YL, 4 * N_DIST * N_YB3, 4 * N_DIST]
MIN_NIVEL = [MIN_CELDA, 20, 20, 20, 20, 20, 20, 20, 20, 20, MIN_CELDA, MIN_CELDA, MIN_CELDA, 1]


def _niveles_res(d, db, yb, cat, rit):
    """Niveles para el RESULTADO de pases (cat 0) y corridas (cat 1): down, distancia, yarda y ritmo.
    El ritmo (reloj) se conserva hasta el final; primero se engruesa el campo y el down."""
    d4 = (d == 3).astype(np.int64)
    r0 = ((((d * N_DIST + db) * N_YL + yb) * 2 + cat) * N_RITMO) + rit
    r1 = ((((d * 3 + _DB3[db]) * N_YB9 + _YB9[yb]) * 2 + cat) * N_RITMO) + rit
    r2 = (((d4 * N_YB5 + _YB5[yb]) * 2 + cat) * N_RITMO) + rit
    r3 = ((_YB3[yb] * 2 + cat) * N_RITMO) + rit
    rg = _RG[rit]
    r4 = (((d4 * N_YB5 + _YB5[yb]) * 2 + cat) * N_RG) + rg
    r5 = ((_YB3[yb] * 2 + cat) * N_RG) + rg
    r6 = ((d * N_DIST + db) * N_YL + yb) * 2 + cat
    r7 = ((d * N_DIST + db) * N_YB3 + _YB3[yb]) * 2 + cat
    r8 = (d * N_DIST + db) * 2 + cat
    r9 = cat
    return [r0, r1, r2, r3, r4, r5, r6, r7, r8, r9]


TAM_RES = [4 * N_DIST * N_YL * 2 * N_RITMO, 4 * 3 * N_YB9 * 2 * N_RITMO, 2 * N_YB5 * 2 * N_RITMO, N_YB3 * 2 * N_RITMO,
           2 * N_YB5 * 2 * N_RG, N_YB3 * 2 * N_RG, 4 * N_DIST * N_YL * 2, 4 * N_DIST * N_YB3 * 2, 4 * N_DIST * 2, 2]
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
             pr=es_pase_corrida[m], to_of=to_of[m], to_def=to_def[m], epa=f("epa").astype(np.float32)[m])
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
    pr_idx = np.flatnonzero((cat <= 1) & ((sit[m] < BASE_Q4) | parejo))
    dd = down[m][pr_idx] - 1
    db_ = _LUT_DIST[np.clip(dist[m][pr_idx], 0, 99)].astype(np.int64)
    yb_ = _LUT_YL[np.clip(Y[m][pr_idx], 0, 100)].astype(np.int64)
    rit = RITMO[sit[m][pr_idx]]
    claves_r = _niveles_res(dd, db_, yb_, cat[pr_idx].astype(np.int64), rit)
    r_orden, r_off, r_cnt, r_nivel = tabla_con_respaldo(claves_r, TAM_RES, mapa_celdas_res(), MIN_RES)
    S.update(r_orden=pr_idx[r_orden].astype(np.int64), r_off=r_off, r_cnt=r_cnt)
    # varianza del EPA en el grupo de cada celda de resultado (para inclinar el muestreo según la fuerza de los equipos)
    e_ord = S["epa"][S["r_orden"]].astype(np.float64)
    c1 = np.concatenate([[0.0], np.cumsum(e_ord)]); c2 = np.concatenate([[0.0], np.cumsum(e_ord ** 2)])
    fin_ = r_off + r_cnt
    media_ = (c1[fin_] - c1[r_off]) / np.maximum(r_cnt, 1)
    S["r_var"] = np.maximum((c2[fin_] - c2[r_off]) / np.maximum(r_cnt, 1) - media_ ** 2, 0.05).astype(np.float64)
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
# 3b. Capa de equipos (25A: rendimiento propio sin líneas; 26A: QB; 27A: localía única)
# --------------------------------------------------------------------------------------
EQUIV = {"OAK": "LV", "SD": "LAC", "STL": "LA"}      # mudanzas: el mismo equipo con su sigla actual
TEMP_EQUIPOS = list(range(2019, 2026))             # jugadas para calificar equipos (con 16 semanas de vida media,
                                                   # el peso de lo anterior a 2019 en 2023 es < 0,2 %)
COLS_EQ = ["game_id", "season", "week", "posteam", "defteam", "play_type", "down", "epa", "success", "passer_id"]
W_TEMP = 22                                        # semanas por temporada en el índice de tiempo (1-22 con playoffs)
# Hiperparámetros elegidos SOLO con 2019-2022 (ver contexto_proyecto_nfl.md, 6b, Sprint 2): vida media del peso
# (semanas), arrastre extra por cambio de temporada, encogimiento de la fuerza neta y del estilo anotador (en
# jugadas de peso), mezcla de tasa de éxito, peso del QB y encogimiento del QB hacia el nivel de reemplazo.
PAR_EQ = dict(vida=16.0, rho=0.5, lam_n=10.0, lam_s=25.0, alfa=0.5, beta=1.5, kq=400.0)
KAPPA = (2.435, 1.313)     # EPA por unidad de tasa de éxito por equipo-juego (pase, corrida; nflverse 2011-2018)
R_QB = -0.137              # nivel de reemplazo: EPA por pase de QB que no son el principal de su equipo, menos la liga (2011-2018)
RESP = dict(a_p=25.64, a_r=19.00, b_p=15.19, b_r=14.83)   # respuesta del simulador: pts de margen/total por EPA/jugada
N_LOCALIA = 5              # localía = margen medio del local en las 5 temporadas previas, sin sede neutral (27A)


def _eq(c):
    return pl.col(c).replace(EQUIV)


def cargar_equipos(games):
    for y in TEMP_EQUIPOS:
        descargar(URL_PBP.format(y), DATOS / f"pbp_{y}.parquet", 5_000_000)
    p = pl.concat([pl.read_parquet(DATOS / f"pbp_{y}.parquet", columns=COLS_EQ) for y in TEMP_EQUIPOS],
                  how="vertical_relaxed")
    p = p.filter(pl.col("play_type").is_in(["pass", "run"]) & pl.col("down").is_not_null()
                 & pl.col("epa").is_not_null() & pl.col("posteam").is_not_null())
    g = games.select(["game_id", "home_team", "location"]).with_columns(_eq("home_team"))
    p = (p.with_columns(_eq("posteam").alias("off"), _eq("defteam").alias("def"))
         .join(g, on="game_id", how="inner")
         .with_columns(pl.when(pl.col("location") == "Neutral").then(0)
                       .when(pl.col("off") == pl.col("home_team")).then(1).otherwise(-1).alias("h"),
                       (pl.col("play_type") == "run").cast(pl.Int8).alias("kind"),
                       (pl.col("season") * W_TEMP + pl.col("week")).alias("t")))
    return p


def preparar_equipos(p):
    """Agrega por equipo-juego (pase y corrida) y por QB-juego. Devuelve el insumo de las calificaciones."""
    equipos = sorted(set(p["off"].unique().to_list()) | set(p["def"].unique().to_list()))
    idx = {e: i for i, e in enumerate(equipos)}
    tg = (p.group_by(["game_id", "season", "t", "off", "def", "kind", "h"])
          .agg(pl.len().alias("n"), pl.col("epa").sum().alias("se"), pl.col("success").sum().alias("ss"))
          .sort(["game_id", "off", "kind"]))                    # orden fijo: resultados reproducibles
    qb = (p.filter((pl.col("kind") == 0) & pl.col("passer_id").is_not_null())
          .group_by(["game_id", "season", "t", "off", "def", "h", "passer_id"])
          .agg(pl.len().alias("n"), pl.col("epa").sum().alias("se"))
          .sort(["game_id", "off", "passer_id"]))
    a = lambda df, c: np.array([idx[x] for x in df[c].to_list()], dtype=np.int64)  # noqa: E731
    A = dict(season=tg["season"].to_numpy(), t=tg["t"].to_numpy(), kind=tg["kind"].to_numpy(), o=a(tg, "off"),
             d=a(tg, "def"), h=tg["h"].to_numpy().astype(float), n=tg["n"].to_numpy().astype(float),
             se=tg["se"].to_numpy().astype(float), ss=tg["ss"].to_numpy().astype(float))
    qbs = sorted(set(qb["passer_id"].to_list()))
    qidx = {q: i for i, q in enumerate(qbs)}
    Q = dict(season=qb["season"].to_numpy(), t=qb["t"].to_numpy(), o=a(qb, "off"), d=a(qb, "def"),
             h=qb["h"].to_numpy().astype(float), q=np.array([qidx[x] for x in qb["passer_id"].to_list()], dtype=np.int64),
             n=qb["n"].to_numpy().astype(float), se=qb["se"].to_numpy().astype(float))
    return dict(A=A, Q=Q, equipos=equipos, idx=idx, qidx=qidx)


def _pesos(t_obj, s_obj, t, s, par):
    dt = t_obj - t
    return np.where(dt > 0, 0.5 ** (dt / par["vida"]) * par["rho"] ** (s_obj - s), 0.0)


def _ridge(A, w, kind, ne, lam_n, lam_s):
    """Mínimos cuadrados ponderados: EPA (o éxito) por jugada = mu + o[ataque] + d[defensa] + eta·h, con
    penalización por equipo lam_n·(o − d)² (fuerza neta: decide el margen) + lam_s·(o + d)² (estilo anotador:
    decide el total). Devuelve (mu, o, d, eta) para EPA y para tasa de éxito."""
    m = (A["kind"] == kind) & (w > 0)
    W = w[m] * A["n"][m]; o = A["o"][m]; d = A["d"][m]; h = A["h"][m]
    P = 2 * ne + 2
    iu, io, idd, ih = 0, 1, 1 + ne, 1 + 2 * ne
    M = np.zeros((P, P))
    so = np.bincount(o, W, ne); sd = np.bincount(d, W, ne)
    M[iu, iu] = W.sum()
    M[iu, io:io + ne] = M[io:io + ne, iu] = so
    M[iu, idd:idd + ne] = M[idd:idd + ne, iu] = sd
    M[io:io + ne, io:io + ne] = np.diag(so)
    M[idd:idd + ne, idd:idd + ne] = np.diag(sd)
    od = np.bincount(o * ne + d, W, ne * ne).reshape(ne, ne)
    M[io:io + ne, idd:idd + ne] = od
    M[idd:idd + ne, io:io + ne] = od.T
    M[iu, ih] = M[ih, iu] = (W * h).sum()
    M[ih, ih] = (W * h * h).sum()
    M[io:io + ne, ih] = M[ih, io:io + ne] = np.bincount(o, W * h, ne)
    M[idd:idd + ne, ih] = M[ih, idd:idd + ne] = np.bincount(d, W * h, ne)
    ar = np.arange(ne)
    M[io + ar, io + ar] += lam_n + lam_s
    M[idd + ar, idd + ar] += lam_n + lam_s
    M[io + ar, idd + ar] += lam_s - lam_n
    M[idd + ar, io + ar] += lam_s - lam_n
    M += 1e-9 * np.eye(P)
    out = []
    for y in (w[m] * A["se"][m], w[m] * A["ss"][m]):
        b = np.zeros(P)
        b[iu] = y.sum(); b[io:io + ne] = np.bincount(o, y, ne); b[idd:idd + ne] = np.bincount(d, y, ne); b[ih] = (y * h).sum()
        x = np.linalg.solve(M, b)
        out.append((x[iu], x[io:io + ne], x[idd:idd + ne], x[ih]))
    return out


def calificar(EQ, t_obj, s_obj, par=PAR_EQ):
    """Calificaciones con las jugadas de semanas ANTERIORES a t_obj (índice temporada·22 + semana)."""
    A, Q = EQ["A"], EQ["Q"]
    ne, nq = len(EQ["equipos"]), len(EQ["qidx"])
    w = _pesos(t_obj, s_obj, A["t"], A["season"], par)
    R = {}
    for k in (0, 1):
        (mu_e, o_e, d_e, eta_e), (_, o_s, d_s, _) = _ridge(A, w, k, ne, par["lam_n"], par["lam_s"])
        a = par["alfa"]
        R[k] = dict(mu=mu_e, o=(1 - a) * o_e + a * KAPPA[k] * o_s, d=(1 - a) * d_e + a * KAPPA[k] * d_s,
                    eta=eta_e, d_e=d_e, peso=float((w * A["n"])[A["kind"] == k].sum()))
    wq = _pesos(t_obj, s_obj, Q["t"], Q["season"], par)
    r0 = R[0]
    res = Q["se"] - Q["n"] * (r0["mu"] + r0["d_e"][Q["d"]] + r0["eta"] * Q["h"])
    num = np.bincount(Q["q"], wq * res, nq); den = np.bincount(Q["q"], wq * Q["n"], nq)
    R["qhat"] = (num + par["kq"] * R_QB) / (den + par["kq"])
    wn = wq * Q["n"]
    R["qbar"] = np.bincount(Q["o"], wn * R["qhat"][Q["q"]], ne) / np.maximum(np.bincount(Q["o"], wn, ne), 1e-9)
    return R


def localia(games, temporada):
    g = games.filter(pl.col("result").is_not_null() & (pl.col("location") == "Home")
                     & pl.col("season").is_between(temporada - N_LOCALIA, temporada - 1))
    return float(g["result"].mean())


def fuerza_partidos(EQ, R, local, visita, qb_local, qb_visita, neutral, hfa_pts, mu_pool, par=PAR_EQ):
    """Corrimiento del EPA por jugada de cada equipo al atacar (local = equipo 0, visitante = 1), en arreglos
    (juegos × 2): fuerza propia + defensa rival + nivel de la liga (frente a la base del simulador) + cambio de
    QB (titular contra el QB de referencia del equipo) + localía. Devuelve dp, dr, ajuste por QB y h."""
    H = np.array([EQ["idx"][x] for x in local]); V = np.array([EQ["idx"][x] for x in visita])
    def qb(ids, eq_):
        out = np.empty(len(ids))
        for i, (q, e) in enumerate(zip(ids, eq_)):
            if not q:                                  # sin titular publicado: sin ajuste
                out[i] = R["qbar"][e]
            elif q in EQ["qidx"]:
                out[i] = R["qhat"][EQ["qidx"][q]]       # sin pases previos: queda en el nivel de reemplazo
            else:
                out[i] = R_QB
        return out
    adj_h = par["beta"] * (qb(qb_local, H) - R["qbar"][H])
    adj_v = par["beta"] * (qb(qb_visita, V) - R["qbar"][V])
    h = np.where(neutral, 0.0, hfa_pts / (2 * (RESP["a_p"] + RESP["a_r"])))
    lp = R[0]["mu"] - mu_pool[0]; lr = R[1]["mu"] - mu_pool[1]
    dp = np.column_stack([lp + R[0]["o"][H] + R[0]["d"][V] + adj_h + h, lp + R[0]["o"][V] + R[0]["d"][H] + adj_v - h])
    dr = np.column_stack([lr + R[1]["o"][H] + R[1]["d"][V] + h, lr + R[1]["o"][V] + R[1]["d"][H] - h])
    return dict(dp=dp, dr=dr, adj=np.column_stack([adj_h, adj_v]), h=h)


def proyectar(M, EQ, juegos, games, mu_pool, n_sims, semilla, par=PAR_EQ):
    """Simula cada juego n_sims veces, semana por semana (todos los juegos de la semana en paralelo).
    juegos: DataFrame de games.csv. Devuelve un DataFrame con la proyección por juego."""
    filas = []
    juegos = juegos.with_columns(_eq("home_team"), _eq("away_team")).sort(["season", "week", "game_id"])
    for (temp, sem), g in juegos.group_by(["season", "week"], maintain_order=True):
        R = calificar(EQ, temp * W_TEMP + sem, temp, par)
        hfa = localia(games, temp)
        F = fuerza_partidos(EQ, R, g["home_team"].to_list(), g["away_team"].to_list(),
                            g["home_qb_id"].fill_null("").to_list(), g["away_qb_id"].fill_null("").to_list(),
                            (g["location"] == "Neutral").to_numpy(), hfa, mu_pool, par)
        ng = g.height
        rep = np.repeat(np.arange(ng), n_sims)
        f = dict(dp=F["dp"][rep], dr=F["dr"][rep])
        po = np.repeat((g["game_type"] != "REG").to_numpy(), n_sims)
        r = simular(M, ng * n_sims, po, np.random.default_rng(semilla + temp * 100 + sem), fuerza=f)
        mg = r["margen"].reshape(ng, n_sims); tt = r["total"].reshape(ng, n_sims)
        filas.append(pl.DataFrame(dict(
            game_id=g["game_id"], season=np.full(ng, temp), week=np.full(ng, sem), game_type=g["game_type"],
            local=g["home_team"], visita=g["away_team"], neutral=F["h"] == 0,
            margen=mg.mean(axis=1), mediana=np.median(mg, axis=1).astype(float), total=tt.mean(axis=1),
            p_local=(mg > 0).mean(axis=1), p_empate=(mg == 0).mean(axis=1), de_margen=mg.std(axis=1),
            dp_local=F["dp"][:, 0], dp_visita=F["dp"][:, 1], dr_local=F["dr"][:, 0], dr_visita=F["dr"][:, 1],
            qb_local=F["adj"][:, 0], qb_visita=F["adj"][:, 1], localia=np.full(ng, hfa))))
    return pl.concat(filas, how="vertical_relaxed")


# --------------------------------------------------------------------------------------
# 4. Simulador vectorizado
# --------------------------------------------------------------------------------------
K_INCL = 8                         # candidatas por jugada para inclinar el muestreo (remuestreo ponderado)


def simular(M, n, playoffs, rng, fuerza=None):
    """Simula n juegos. Sin 'fuerza': dos equipos promedio en cancha neutral. Con 'fuerza': dict con dp y dr (n × 2),
    corrimiento del EPA medio por pase y por corrida del equipo 0 (local) y 1 (visitante) cuando atacan
    (fuerza propia + defensa rival + QB + nivel de la liga + localía). playoffs: bool o arreglo de n."""
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
    playoffs = np.broadcast_to(np.asarray(playoffs, dtype=bool), (n,))
    min_ot = np.where(playoffs, 900.0, 600.0)
    # diagnósticos
    posesiones = np.zeros(n, dtype=np.int16)
    jugadas_pr = np.zeros(n, dtype=np.int16)
    motivos = np.zeros(len(MOTIVOS), dtype=np.int64)
    ko_suma = 0.0; ko_n = 0
    pasos = 0
    n_reloj = [0, 0]                   # veces que se aplicó la regla del reloj (tiempo muerto, apuro)
    safeties = np.zeros(n, dtype=np.int16)

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
                cr = clave_res(down[i_s[pr]], dist[i_s[pr]], Y[i_s[pr]], cat[pr], ritmo_sim(sit[pr], Y[i_s[pr]]))
                npr = int(pr.sum())
                if fuerza is None:
                    j[pr] = S["r_orden"][S["r_off"][cr] + (rng.random(npr) * S["r_cnt"][cr]).astype(np.int64)]
                else:
                    # inclinación exponencial por remuestreo ponderado: K candidatas de la misma celda, elegida con
                    # peso exp(θ·EPA), θ = Δ·K/((K−1)·varianza de la celda) → el EPA medio se corre en Δ (1er orden)
                    ip = i_s[pr]; of = ofe[pr]
                    delta = np.where(cat[pr] == 0, fuerza["dp"][ip, of], fuerza["dr"][ip, of])
                    th = delta * (K_INCL / (K_INCL - 1)) / S["r_var"][cr]
                    cand = S["r_orden"][S["r_off"][cr] + (rng.random((K_INCL, npr)) * S["r_cnt"][cr]).astype(np.int64)]
                    lw = th * S["epa"][cand]
                    w_ = np.exp(lw - lw.max(axis=0))
                    acum = np.cumsum(w_, axis=0)
                    elige = (rng.random(npr) * acum[-1] < acum).argmax(axis=0)
                    j[pr] = cand[elige, np.arange(npr)]
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
                # penales (filas 'no_play'): regla de la mitad de la distancia a la meta; nunca dan TD ni safety
                # por sí mismos (el safety por penal en la propia zona de anotación viene marcado en la fila)
                cj = S["cat"][jj]
                pen = cj == 2
                if pen.any():
                    lejos_meta = pen & (nuevo <= 0)
                    nuevo = np.where(lejos_meta, np.maximum(1, yy // 2), nuevo)
                    cerca_propia = pen & (nuevo >= 100) & ~S["saf"][jj]
                    nuevo = np.where(cerca_propia, 100 - np.maximum(1, (100 - yy) // 2), nuevo)
                    av = yy - nuevo
                # rodilla (kneel): nunca safety por geometría
                nuevo = np.where((cj == 3) & (nuevo >= 100), 99, nuevo)
                # safety de una jugada tomada MÁS CERCA de la propia meta que la simulación: la pérdida real
                # fue de al menos (100 − yarda de origen); se aplica esa pérdida (simétrico al TD censurado)
                saf_lejos = S["saf"][jj] & (yy < yo)
                nuevo = np.where(saf_lejos, yy + (100 - yo), nuevo)
                av = yy - nuevo
                tdo = (nuevo <= 0) & ~S["perdida"][jj] & ~S["td_def"][jj]
                tdd = S["td_def"][jj]
                sf = ((S["saf"][jj] & ~saf_lejos) | (nuevo >= 100)) & ~tdo & ~tdd & ~S["perdida"][jj]
                pe = S["perdida"][jj] & ~tdd & ~tdo
                resto = ~(tdo | tdd | sf | pe)
                if tdo.any():
                    anotar_td(ii[tdo], pos[ii[tdo]], M_TD)
                if tdd.any():
                    anotar_td(ii[tdd], (1 - pos[ii[tdd]]).astype(np.int8), M_TDRIV)
                if sf.any():
                    k = ii[sf]
                    sc[k, 1 - pos[k]] += 2
                    safeties[k] += 1
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
                    safeties[k] += 1
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

            # --- manejo del reloj al final de cada mitad (regla, no dato) ---
            # Quien necesita parar el reloj (al final de la 1ª mitad, o empatado o perdiendo al final del juego
            # o en tiempo extra) no deja que el reloj se acabe tras un pase, corrida o penal si puede evitarlo:
            # con tiempo muerto lo pide con 2-5 s en el reloj; sin tiempo muerto apura el siguiente snap (spike),
            # que llega como mínimo 12 s después del anterior. La fila real se tomó con más reloj y no lo refleja.
            sigue_of = (fase[i_s] == SCRIM) & (pos[i_s] == ofe) & (cat <= 2)
            necesita = ((qtr == 2) & (hs <= 120)) | (((qtr == 4) & (hs <= 300)) | (qtr == 5)) & (dif_o <= 0)
            expira = sigue_of & necesita & (seg >= hs)
            if expira.any():
                quedan = rng.integers(2, 6, len(i_s)).astype(np.float64)
                dur = np.minimum(seg, DUR_JUGADA)
                con_to = tms[i_s, ofe] >= 1
                a_to = expira & con_to & (hs - dur >= 1)
                a_sp = expira & ~con_to & (hs - MIN_APURO >= 1)
                seg = np.where(a_to, np.maximum(dur, hs - quedan), np.where(a_sp, np.maximum(MIN_APURO, hs - quedan), seg))
                k = i_s[a_to]
                tms[k, ofe[a_to]] -= 1
                n_reloj[0] += int(a_to.sum()); n_reloj[1] += int(a_sp.sum())
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
                per[ko] = 2; otc[ko] = min_ot[ko]; fue_ot[ko] = True; ot_per[ko] = 1
                fase[ko] = KICK; patea[ko] = (rng.random(len(ko)) < 0.5).astype(np.int8); tipo_k[ko] = 0
                ot_hechas[ko] = 0
                tms[ko] = np.where(playoffs[ko], 3, 2)[:, None]
        m3 = listos & (per == 2) & (otc <= 0)
        if m3.any():
            k = np.flatnonzero(m3)
            po = playoffs[k]
            sigue_ot = po & (sc[k, 0] == sc[k, 1]) & (ot_per[k] < 6)
            otc[k[sigue_ot]] = min_ot[k[sigue_ot]]; ot_per[k[sigue_ot]] += 1
            fin_posesion(k[~po & (fase[k] == SCRIM)], M_MITAD)
            fase[k[~sigue_ot]] = FIN

    margen = sc[:, 0].astype(np.int64) - sc[:, 1].astype(np.int64)
    total = sc[:, 0].astype(np.int64) + sc[:, 1].astype(np.int64)
    return dict(margen=margen, total=total, puntos=sc.astype(np.int64).ravel(), fue_ot=fue_ot,
                empate=margen == 0, posesiones=posesiones.astype(np.int64), jugadas=jugadas_pr.astype(np.int64),
                motivos=motivos, ko_suma=ko_suma, ko_n=ko_n, pasos=pasos, n_reloj=n_reloj,
                safeties=safeties.astype(np.int64))


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


def evaluar_liga(ref, sim):
    """C1-C6 del Sprint 1 (24A) con sus mismas bandas: dos equipos promedio en cancha neutral."""
    am = np.abs(sim["margen"])
    v, c = np.unique(am, return_counts=True)
    o = np.argsort(-c, kind="stable")
    rank = [(int(v[i]), float(c[i] / len(am))) for i in o[:6]]
    tot_m = float(sim["total"].mean())
    de_m = float(sim["margen"].std(ddof=1)); de_t = float(sim["total"].std(ddof=1))
    p3 = float((am == 3).mean()); p7 = float((am == 7).mean())
    dentro = lambda x, ab: ab[0] <= x <= ab[1]  # noqa: E731
    filas = [
        ("C1", "Nivel: total medio", f"{tot_m:.2f}", f"[{ref['c1'][0]:.2f}; {ref['c1'][1]:.2f}]", dentro(tot_m, ref["c1"])),
        ("C2", "DE del margen", f"{de_m:.2f}", f"[{ref['c2'][0]:.2f}; {ref['c2'][1]:.2f}]", dentro(de_m, ref["c2"])),
        ("C3", "DE del total", f"{de_t:.2f}", f"[{ref['c3'][0]:.2f}; {ref['c3'][1]:.2f}]", dentro(de_t, ref["c3"])),
        ("C4", "P(|margen| = 3)", f"{100 * p3:.1f} %", f"[{100 * ref['c4'][0]:.1f} %; {100 * ref['c4'][1]:.1f} %]", dentro(p3, ref["c4"])),
        ("C5", "P(|margen| = 7)", f"{100 * p7:.1f} %", f"[{100 * ref['c5'][0]:.1f} %; {100 * ref['c5'][1]:.1f} %]", dentro(p7, ref["c5"])),
        ("C6", "Márgenes más frecuentes", ", ".join(str(x[0]) for x in rank[:3]), "3 primero y 7 segundo",
         rank[0][0] == 3 and rank[1][0] == 7),
    ]
    return filas, rank


def pendiente_logistica(y, p, iteraciones=60):
    """Regresión logística de y (0/1) en logit(p): devuelve (intercepto, pendiente)."""
    lg = np.log(p / (1 - p))
    X = np.column_stack([np.ones_like(lg), lg])
    b = np.zeros(2)
    for _ in range(iteraciones):
        q = 1 / (1 + np.exp(-X @ b))
        paso = np.linalg.solve(X.T @ (X * (q * (1 - q))[:, None]) + 1e-9 * np.eye(2), X.T @ (y - q))
        b += paso
        if np.max(np.abs(paso)) < 1e-10:
            break
    return float(b[0]), float(b[1])


def cambios_de_qb(games):
    """(game_id, equipo) → True si el QB titular no es el del juego anterior de ese equipo."""
    g = games.filter(pl.col("result").is_not_null()).with_columns(_eq("home_team"), _eq("away_team"))
    largo = pl.concat([
        g.select(["game_id", "gameday", pl.col("home_team").alias("equipo"), pl.col("home_qb_id").alias("qb")]),
        g.select(["game_id", "gameday", pl.col("away_team").alias("equipo"), pl.col("away_qb_id").alias("qb")])])
    largo = (largo.sort(["equipo", "gameday", "game_id"])
             .with_columns(pl.col("qb").shift(1).over("equipo").alias("qb_ant"))
             .with_columns((pl.col("qb_ant").is_not_null() & (pl.col("qb") != pl.col("qb_ant"))).alias("cambio")))
    return {(a, b): c for a, b, c in largo.select(["game_id", "equipo", "cambio"]).iter_rows()}


def evaluar_prueba(P, games, juegos):
    """S2-C5 a S2-C8 y lo que se reporta, con la proyección P de los juegos de prueba."""
    j = juegos.with_columns(_eq("home_team"), _eq("away_team")).select(
        ["game_id", "result", "total", "spread_line", "total_line", "location"]).rename({"total": "total_real"})
    d = P.join(j, on="game_id", how="inner").sort(["season", "week", "game_id"])
    pm = d["margen"].to_numpy(); pt = d["total"].to_numpy()
    res = d["result"].to_numpy().astype(float); tot = d["total_real"].to_numpy().astype(float)
    sp = d["spread_line"].to_numpy().astype(float); tl = d["total_line"].to_numpy().astype(float)
    temp = d["season"].to_numpy()
    mae_m = float(np.abs(pm - res).mean()); mae_t = float(np.abs(pt - tot).mean())
    cie_m = float(np.abs(sp - res).mean()); cie_t = float(np.abs(tl - tot).mean())
    ses_m = float((pm - sp).mean()); ses_t = float((pt - tl).mean())
    marca = (np.abs(pm - sp) > FILTRO_SPREAD) | (np.abs(pt - tl) > FILTRO_TOTAL)
    # moneyline: probabilidad de ganar el local (empate = medio), sin los juegos empatados
    ok = res != 0
    y = (res > 0).astype(float)[ok]
    pw = np.clip(d["p_local"].to_numpy() + 0.5 * d["p_empate"].to_numpy(), 1e-4, 1 - 1e-4)[ok]
    _, pend = pendiente_logistica(y, pw)
    ll = float(-np.mean(y * np.log(pw) + (1 - y) * np.log(1 - pw)))
    # "solo localía": tasa de victorias del local (empate = medio) en las 5 temporadas previas; sede neutral = 0,5
    tasa = {}
    for s in set(temp.tolist()):
        gh = games.filter(pl.col("result").is_not_null() & (pl.col("location") == "Home")
                          & pl.col("season").is_between(s - N_LOCALIA, s - 1))
        r_ = gh["result"].to_numpy()
        tasa[s] = float(((r_ > 0) + 0.5 * (r_ == 0)).mean())
    pl0 = np.where(d["location"].to_numpy() == "Neutral", 0.5, np.array([tasa[s] for s in temp]))[ok]
    ll0 = float(-np.mean(y * np.log(pl0) + (1 - y) * np.log(1 - pl0)))
    # cambio de QB y tamaño del ajuste
    cq = cambios_de_qb(games)
    cl = np.array([cq.get((g_, e), False) for g_, e in zip(d["game_id"].to_list(), d["local"].to_list())])
    cv = np.array([cq.get((g_, e), False) for g_, e in zip(d["game_id"].to_list(), d["visita"].to_list())])
    con_cambio = cl | cv
    adj_pts = np.concatenate([d["qb_local"].to_numpy(), d["qb_visita"].to_numpy()]) * RESP["a_p"]
    adj_cambio = np.concatenate([d["qb_local"].to_numpy()[cl], d["qb_visita"].to_numpy()[cv]]) * RESP["a_p"]
    # revisión de sesgo semanal (21A): semanas con |sesgo| > 1,0 (spread) o > 1,5 (total)
    sem = d.with_columns(pl.Series("dm", pm - sp), pl.Series("dt", pt - tl)).group_by(["season", "week"]).agg(
        pl.col("dm").mean(), pl.col("dt").mean())
    sem_alerta = int(((sem["dm"].abs() > 1.0) | (sem["dt"].abs() > 1.5)).sum())
    filas = [
        ("S2-C5", f"Error absoluto medio {temp.min()}-{temp.max()}", f"margen {mae_m:.2f} (cierre {cie_m:.2f}); total {mae_t:.2f} (cierre {cie_t:.2f})",
         f"margen ≤ {cie_m + 0.40:.2f} y total ≤ {cie_t + 0.40:.2f}", (mae_m <= cie_m + 0.40) and (mae_t <= cie_t + 0.40)),
        ("S2-C6", "Sesgo contra el cierre", f"spread {ses_m:+.2f}; total {ses_t:+.2f}", "spread ±1,0 y total ±1,5",
         abs(ses_m) <= 1.0 and abs(ses_t) <= 1.5),
        ("S2-C7", "Calibración de la moneyline", f"pendiente {pend:.2f}; log-loss {ll:.4f} (solo localía {ll0:.4f})",
         "pendiente 0,8-1,2 y log-loss menor", (0.8 <= pend <= 1.2) and (ll < ll0)),
        ("S2-C8", "Juegos marcados por el filtro", f"{100 * marca.mean():.1f} %", "≤ 30 %", marca.mean() <= 0.30),
    ]
    rep = [
        ("Juegos de prueba", f"{len(d)}", "855 esperados"),
        ("Error del margen por temporada (modelo · cierre)",
         "; ".join(f"{s}: {np.abs(pm - res)[temp == s].mean():.2f} · {np.abs(sp - res)[temp == s].mean():.2f}" for s in sorted(set(temp.tolist()))), ""),
        ("Error del total por temporada (modelo · cierre)",
         "; ".join(f"{s}: {np.abs(pt - tot)[temp == s].mean():.2f} · {np.abs(tl - tot)[temp == s].mean():.2f}" for s in sorted(set(temp.tolist()))), ""),
        ("Ajuste por QB (pts de margen, todos los equipo-juego)", f"medio |{np.abs(adj_pts).mean():.2f}|; p95 |{np.percentile(np.abs(adj_pts), 95):.2f}|", ""),
        ("Ajuste por QB en equipo-juegos con cambio de titular", f"n {len(adj_cambio)}; medio {adj_cambio.mean() if len(adj_cambio) else 0:+.2f}; |medio| {np.abs(adj_cambio).mean() if len(adj_cambio) else 0:.2f}", ""),
        ("Error del margen en juegos con cambio de QB (modelo · cierre)",
         f"n {int(con_cambio.sum())}: {np.abs(pm - res)[con_cambio].mean():.2f} · {np.abs(sp - res)[con_cambio].mean():.2f}; resto: {np.abs(pm - res)[~con_cambio].mean():.2f} · {np.abs(sp - res)[~con_cambio].mean():.2f}", ""),
        ("Localía usada (pts, 5 temporadas previas)", "; ".join(f"{s}: {v_:.2f}" for s, v_ in sorted(
            {int(a): float(b) for a, b in zip(d["season"].to_list(), d["localia"].to_list())}.items())), ""),
        ("Marcados por spread / por total", f"{100 * (np.abs(pm - sp) > FILTRO_SPREAD).mean():.1f} % / {100 * (np.abs(pt - tl) > FILTRO_TOTAL).mean():.1f} %", ""),
        ("DE de (modelo − cierre)", f"spread {(pm - sp).std():.2f}; total {(pt - tl).std():.2f}", ""),
        ("Pendiente resultado ~ modelo", f"margen {np.polyfit(pm, res, 1)[0]:.2f}; total {np.polyfit(pt, tot, 1)[0]:.2f}", ""),
        ("Semanas que dispararían la revisión de sesgo (21A)", f"{sem_alerta} de {sem.height}", ""),
        ("Dispersión: DE simulada media del margen · DE real del error del cierre", f"{d['de_margen'].mean():.2f} · {(res - sp).std():.2f}", ""),
    ]
    d = d.with_columns(pl.Series("marcado", marca), pl.Series("cambio_qb_local", cl), pl.Series("cambio_qb_visita", cv))
    return filas, rep, d


# --------------------------------------------------------------------------------------
# 7. Principal
# --------------------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rapido", action="store_true", help="prueba de código: menos simulaciones")
    ap.add_argument("--sin-telegram", action="store_true")
    ap.add_argument("--ensayo", action="store_true", help="la 'prueba' corre con 2022 (temporada de ajuste); sin veredicto")
    ap.add_argument("--sin-prueba", action="store_true", help="no corre 2023-2025 (solo C0-C4)")
    args = ap.parse_args()
    if os.nice(0) < 10:
        os.nice(10 - os.nice(0))
    SALIDA.mkdir(parents=True, exist_ok=True)
    candado = open(SALIDA / ".candado", "w")
    try:
        fcntl.flock(candado, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit("Ya hay una corrida de sprint2.py en marcha; no lanzo otra.")
    inicio = time.time()
    modo = "ENSAYO con 2022 (sin veredicto)" if args.ensayo else "sin prueba 2023-2025 (sin veredicto)" if args.sin_prueba else "oficial"
    if args.rapido:
        modo = "PRUEBA RÁPIDA · " + modo
    log(f"sprint2.py {VERSION} · {modo} · Python {platform.python_version()} · numpy {np.__version__} · polars {pl.__version__} · nice {os.nice(0)}")

    # ---- datos y modelo a nivel liga ----
    games, pbp = preparar_datos()
    log(f"datos: {games.height} juegos en el calendario, {pbp.height} filas de jugada por jugada · pico {pico_mb():.0f} MB")
    M = construir_modelo(pbp, games)
    log(f"modelo: {json.dumps(M['resumen'], ensure_ascii=False)}")
    ref = referencias(games, pbp)
    pp = pbp.filter(pl.col("play_type").is_in(["pass", "run"]) & pl.col("down").is_not_null()
                    & pl.col("epa").is_not_null() & pl.col("posteam").is_not_null())
    mu_pool = (float(pp.filter(pl.col("play_type") == "pass")["epa"].mean()), float(pp.filter(pl.col("play_type") == "run")["epa"].mean()))
    del pbp, pp
    # ---- capa de equipos ----
    EQ = preparar_equipos(cargar_equipos(games))
    log(f"equipos: {len(EQ['equipos'])} equipos, {len(EQ['qidx'])} QB, EPA medio de la base: pase {mu_pool[0]:+.4f}, corrida {mu_pool[1]:+.4f} · pico {pico_mb():.0f} MB")

    # ---- S2-C0: semana de 16 juegos con equipos distintos (2025, semana 18) × 10.000 ----
    semana = games.filter((pl.col("season") == 2025) & (pl.col("week") == 18) & (pl.col("game_type") == "REG"))
    n_c0 = 1_000 if args.rapido else 10_000
    bot_antes = estado_bot()
    t0 = time.time()
    P0 = proyectar(M, EQ, semana, games, mu_pool, n_c0, SEMILLA + 1)
    seg_c0 = time.time() - t0
    bot_despues = estado_bot()
    pico = pico_mb()
    bot_mb = max([x for x in (bot_antes[1], bot_despues[1]) if x is not None], default=None)
    bot_ok = bot_despues[0] in ("active", "desconocido") and (bot_mb is None or bot_mb < 350)
    distintos = len(set(P0["local"].to_list() + P0["visita"].to_list()))
    c0_pasa = (seg_c0 < 180) and (pico <= 1536) and bot_ok and P0.height == 16 and distintos == 32
    bot_txt = f"{bot_despues[0]}" + (f", {bot_mb:.0f} MB" if bot_mb is not None else "")
    log(f"S2-C0: {P0.height} juegos ({distintos} equipos) × {n_c0} en {seg_c0:.1f} s · pico {pico:.0f} MB · bot {bot_txt}")

    # ---- S2-C1 a S2-C4: dos equipos promedio en cancha neutral, 20 tandas de 10.000 (19 de temporada regular) ----
    tandas = 5 if args.rapido else 20
    tam = 2_000 if args.rapido else 10_000
    partes = []
    t0 = time.time()
    for b in range(tandas):
        partes.append(simular(M, tam, playoffs=(b == tandas - 1), rng=np.random.default_rng(SEMILLA + 100 + b)))
    seg_val = time.time() - t0
    claves = ("margen", "total", "puntos", "fue_ot", "empate", "posesiones", "jugadas", "safeties")
    sim = {k: np.concatenate([p[k] for p in partes]) for k in claves}
    reg = {k: np.concatenate([p[k] for p in partes[:-1]]) for k in ("fue_ot", "empate")}
    sim["motivos"] = np.sum([p["motivos"] for p in partes], axis=0)
    reloj = np.sum([p["n_reloj"] for p in partes], axis=0)
    ko_media = sum(p["ko_suma"] for p in partes) / max(sum(p["ko_n"] for p in partes), 1)
    pasos_max = max(p["pasos"] for p in partes)
    log(f"nivel liga: {len(sim['margen'])} juegos en {seg_val:.1f} s · pasos máx {pasos_max} · pico {pico_mb():.0f} MB")
    filas_liga, rank = evaluar_liga(ref, sim)
    c1_pasa = all(f[4] for f in filas_liga)
    saf = float(sim["safeties"].mean()); emp = float(reg["empate"].mean()); ot = float(reg["fue_ot"].mean())

    # ---- localía en el simulador (se reporta): dos equipos iguales, uno de local, con la localía de 2026 ----
    hfa26 = localia(games, 2026)
    h26 = hfa26 / (2 * (RESP["a_p"] + RESP["a_r"]))
    nh = 4_000 if args.rapido else 40_000
    fh = dict(dp=np.tile([h26, -h26], (nh, 1)), dr=np.tile([h26, -h26], (nh, 1)))
    rh = simular(M, nh, False, np.random.default_rng(SEMILLA + 50), fuerza=fh)
    hfa_sim = float(rh["margen"].mean()); hfa_ee = float(rh["margen"].std() / np.sqrt(nh))

    # ---- prueba hacia adelante: 2023-2025 (una sola vez) o ensayo con 2022 ----
    filas_prueba, rep_prueba, D = [], [], None
    if not args.sin_prueba:
        temporadas = [2022] if args.ensayo else TEMP_PRUEBA
        juegos = games.filter(pl.col("season").is_in(temporadas) & pl.col("result").is_not_null())
        n_p = 1_000 if args.rapido else 10_000
        t0 = time.time()
        P = proyectar(M, EQ, juegos, games, mu_pool, n_p, SEMILLA + 1000)
        seg_p = time.time() - t0
        log(f"prueba {temporadas}: {P.height} juegos × {n_p} en {seg_p:.0f} s · pico {pico_mb():.0f} MB")
        filas_prueba, rep_prueba, D = evaluar_prueba(P, games, juegos)

    # ---- criterios ----
    filas = [
        ("S2-C0", "Rendimiento", f"{P0.height} juegos ({distintos} equipos) × {n_c0}: {seg_c0:.1f} s; pico {pico:.0f} MB; bot {bot_txt}",
         "< 180 s, ≤ 1.536 MB, bot activo < 350 MB", c0_pasa),
        ("S2-C1", "Sin retroceso a nivel liga (C1-C6)", "; ".join(f"{f[0]} {f[2]}{'' if f[4] else ' ✗'}" for f in filas_liga),
         "C1-C6 del Sprint 1 con sus bandas", c1_pasa),
        ("S2-C2", "Safeties por juego", f"{saf:.3f}", "0,034-0,065", 0.034 <= saf <= 0.065),
        ("S2-C3", "Empates (temporada regular)", f"{100 * emp:.2f} %", "≤ 0,81 %", emp <= 0.0081),
        ("S2-C4", "Juegos con tiempo extra (temporada regular)", f"{100 * ot:.2f} %", "4,4-6,8 %", 0.044 <= ot <= 0.068),
    ] + filas_prueba
    oficial = not (args.ensayo or args.sin_prueba or args.rapido)
    acepta = all(f[4] for f in filas) and len(filas) == 9
    if oficial:
        veredicto = "ACEPTADO (S2-C0 a S2-C8 pasan)" if acepta else "NO ACEPTADO: falla " + ", ".join(f[0] for f in filas if not f[4])
    else:
        veredicto = f"SIN VEREDICTO ({modo}); falla: " + (", ".join(f[0] for f in filas if not f[4]) or "ninguno")

    am = np.abs(sim["margen"])
    mot = sim["motivos"] / sim["motivos"].sum()
    diag = [
        ("Localía en el simulador (equipos iguales, localía 2026)", f"{hfa_sim:+.2f} ± {hfa_ee:.2f}", f"{hfa26:+.2f} pts (2021-2025, 27A)"),
        ("Posesiones por juego", f"{sim['posesiones'].mean():.2f}", f"{ref['posesiones_por_juego']:.2f}"),
        ("Pases + corridas por juego", f"{sim['jugadas'].mean():.1f}", f"{ref['pase_corrida_por_juego']:.1f}"),
        ("Puntos por equipo", f"{sim['puntos'].mean():.2f}", f"{ref['pts_equipo']:.2f} (2021-25)"),
        ("Inicio tras kickoff (yarda propia)", f"{100 - ko_media:.1f}", f"{ref['inicio_kickoff_2025']:.1f} (2025)"),
        ("Tiempo extra (todas las tandas)", f"{100 * sim['fue_ot'].mean():.1f} %", f"{100 * ref['p_ot_parejos']:.1f} % parejos 2021-25"),
        ("P(|margen| ≤ 3)", f"{100 * (am <= 3).mean():.1f} %", f"{100 * ref['p_le3']:.1f} % parejos"),
        ("P(|margen| ≥ 14)", f"{100 * (am >= 14).mean():.1f} %", f"{100 * ref['p_ge14']:.1f} % parejos"),
        ("Márgenes más frecuentes", ", ".join(f"{a} ({100 * b:.1f} %)" for a, b in rank[:5]),
         ", ".join(f"{a} ({100 * b:.1f} %)" for a, b in ref["ranking"][:5])),
        ("Regla del reloj aplicada (por juego)", f"tiempo muerto {reloj[0] / len(am):.3f}; apuro {reloj[1] / len(am):.3f}", ""),
    ]
    for i, nombre in enumerate(MOTIVOS):
        diag.append((f"Posesión termina en: {nombre}", f"{100 * mot[i]:.1f} %", f"{100 * ref['motivos'].get(nombre, 0):.1f} %"))

    # ---- salida ----
    ahora = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lineas = [f"SPRINT 2 — motor nfl_sim {VERSION}", f"Corrida: {ahora} · {platform.node()} · {modo}",
              f"Veredicto: {veredicto}", "", "Criterios (28A):"]
    for f in filas:
        lineas.append(f"  {f[0]} {'✅' if f[4] else '❌'} {f[1]}: {f[2]}  · pasa si {f[3]}")
    if rep_prueba:
        lineas += ["", "Prueba: se reporta, no decide:"]
        lineas += [f"  {r[0]}: {r[1]}" + (f" · {r[2]}" if r[2] else "") for r in rep_prueba]
    lineas += ["", "Nivel liga y simulador: se reporta, no decide (simulado · real):"]
    lineas += [f"  {d_[0]}: {d_[1]} · {d_[2]}" if d_[2] else f"  {d_[0]}: {d_[1]}" for d_ in diag]
    lineas += ["", f"Capa de equipos (25A-27A): parámetros elegidos solo con 2019-2022: {json.dumps(PAR_EQ)}; "
               f"nivel de reemplazo del QB {R_QB}; respuesta del simulador {json.dumps(RESP)}.",
               f"Modelo: {M['resumen']['jugadas_scrimmage']} jugadas de scrimmage 2021-25; XP {100 * M['p_xp']:.1f} %, 2 pts {100 * M['p_2']:.1f} %.",
               f"Pico de memoria del proceso: {pico_mb():.0f} MB. Duración total: {time.time() - inicio:.0f} s.",
               "Advertencia: S2-C1 a S2-C4 miden consistencia con los datos de origen; la prueba 2023-2025 mide precisión "
               "fuera de muestra contra el cierre. Nada de esto valida una ventaja: eso lo decide el CLV de 2026 (29A)."]
    resumen = "\n".join(lineas)
    print(resumen, flush=True)
    (SALIDA / "resumen_s2.txt").write_text(resumen + "\n", encoding="utf-8")
    with open(SALIDA / "criterios_s2.csv", "w", newline="", encoding="utf-8") as fh_:
        w = csv.writer(fh_); w.writerow(["criterio", "medida", "resultado", "pasa_si", "pasa"])
        for f in filas:
            w.writerow([f[0], f[1], f[2], f[3], int(f[4])])
    with open(SALIDA / "diagnostico_s2.csv", "w", newline="", encoding="utf-8") as fh_:
        w = csv.writer(fh_); w.writerow(["medida", "simulado", "real"])
        w.writerows(diag)
        w.writerows(rep_prueba)
    archivos = ["resumen_s2.txt", "criterios_s2.csv", "diagnostico_s2.csv", "semana_c0.csv", "modelo_s2.json"]
    P0.write_csv(SALIDA / "semana_c0.csv")
    if D is not None:
        nombre = "proyecciones_2022_ensayo.csv" if args.ensayo else "proyecciones_2023_2025.csv"
        D.select(["game_id", "season", "week", "game_type", "local", "visita", "margen", "total", "p_local", "p_empate",
                  "spread_line", "total_line", "result", "total_real", "marcado", "qb_local", "qb_visita",
                  "cambio_qb_local", "cambio_qb_visita", "localia"]).write_csv(SALIDA / nombre)
        archivos.append(nombre)
    (SALIDA / "modelo_s2.json").write_text(json.dumps(dict(version=VERSION, modo=modo, par_eq=PAR_EQ, r_qb=R_QB, kappa=KAPPA,
                                                           resp=RESP, mu_pool=mu_pool, localia_2026=hfa26, resumen=M["resumen"]),
                                                      ensure_ascii=False, indent=1), encoding="utf-8")
    zp = SALIDA / "sprint2_resultados.zip"
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        for nombre in archivos:
            z.write(SALIDA / nombre, nombre)
    log(f"salida en {SALIDA}")
    if not args.sin_telegram:
        telegram(resumen, zp)
    log("== LISTO")


if __name__ == "__main__":
    main()
