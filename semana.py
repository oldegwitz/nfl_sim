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
  7b. (v7) En las corridas que cuentan (miércoles, sábado, T−85) arma el "Boleto (informativo)" de los juegos del
     domingo y el lunes: lado = favorito de Pinnacle sin vig (el modelo solo deja una marca), precios de BetOnline,
     P(cobrar), EV y costo esperado de tres boletos (solo ML, mixto, teaser Wong) y la tabla de 3 a 8 patas. Se
     congela al empezar el primer juego del domingo; después de los juegos agrega el EV contra el cierre y el resultado.
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
  venv/bin/python semana.py informe [--semana N]          (v8.1: informe de CLV y autopsia de una semana jugada; sale
                                                           solo por Telegram cuando cierra cada semana que cuenta)
  venv/bin/python semana.py gemini-piloto [--variante g1] (piloto del agente Gemini: P1-P4; no cuenta para el piso)
  (v8.2) En las corridas automáticas T−85, después de g1, el registro en vivo e2 (decisión 49) consulta aparte
         enfermedad, vestuario y descanso anunciado; el modo estado muestra solo sus conteos.
  (v8.3) En las corridas automáticas T−85, después de g1 y antes de e2, el VIGÍA (decisión 55) busca bajas con fuente
         oficial y avisa cuando falta un titular que la máquina no conoce (Telegram aparte y columna E de la hoja).
  venv/bin/python semana.py vigia-prueba                  (v8.3: prueba del vigía sin consultar: pedido, esquema, lectura,
                                                           titulares con los snaps y la regla del piloto)
  venv/bin/python semana.py vigia-prueba --real           (v8.3: 1 consulta real por modelo sobre el próximo juego; no
                                                           cuenta para nada, no escribe en el registro; tope 4 por día)
  venv/bin/python semana.py hoja-prueba                   (prueba la hoja: conexión, y crea y borra una pestaña semanal y
                                                           un boleto de prueba con el formato real)
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
import shutil
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

VERSION_SEMANA = "semana-v8.3.1 (11-oct-2026)"
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
# v6 (35A, configuración g1 decidida por Ozz el 2-oct): el agente Gemini consulta un juego por llamada (hasta 8 a la
#     vez, 90 s en total), con generateContent, razonamiento medium, búsqueda de Google y salida con esquema; corre
#     DESPUÉS de guardar y enviar la proyección T−85; registra cada llamada (gemini_llamadas.csv) y deja un voto por
#     equipo (vacío si no hubo respuesta = no acierto). Modo 'gemini-piloto' (criterios P1-P4). La confiabilidad de
#     Gemini se cuenta solo con sus votos T−85 y por versión (g0 = v5, g1...). La proyección es idéntica a la de v5.
# v6.1 (2-oct): el formato de salida va como enum, como exige generateContent: responseFormat.text.mimeType =
#     "APPLICATION_JSON" (v6 mandaba "application/json" y Google respondía 400 en el primer piloto). Cambia la huella.
# v6.2 (2-oct, decisión de Ozz tras el diagnóstico): con 3.5 Flash-Lite la respuesta no trae groundingMetadata, pero las
#     fuentes vienen como enlaces grounding-api-redirect, que solo produce la búsqueda de Google. Nueva columna
#     'evidencia_busqueda' (metadatos | enlace | ninguna) y P2 del piloto = evidencia de búsqueda en el 100 % de las que
#     respondieron. Solo cambia la medición: lo que se envía y cómo se leen los QB no cambian (huella igual que v6.1).
#     gemini_llamadas.csv con columnas viejas se guarda aparte (gemini_llamadas_hasta_v61.csv) y se empieza uno nuevo.
# v7 (2-oct, siete ajustes de la hoja pedidos por Ozz; solo presentación y registro descriptivo: el modelo s2-v1, la
#     simulación, la regla 29A y el agente Gemini no cambian; la proyección es idéntica a v6.2):
#     (1) celdas de señal sin señal → "retro (n/a)", "sin señal" o "sin Pinnacle 3 h"; (2) en juegos excluidos la señal
#     se ve como "excluida · …"; (3) "REVISAR: …" → "Fuera: …" (desde 32b no hay revisión manual); (4) columna nueva
#     "Por qué difiere": piezas del número del modelo (fuerza de pase, de corrida, ajuste por QB, localía) y movimiento
#     de Pinnacle desde la primera foto del bot; (5) leyenda del verde corregida: ningún dinero por el motor (31A);
#     (6) señal en palabras ("MIA ML: modelo 20 % · precio 16 %"; "MIA +11.0: cubre 55 % (necesita 52,4 %)");
#     (7) pestaña "Boleto (informativo)". El registro suma 8 columnas al final (precio del spread de BetOnline, piezas
#     del modelo y apertura de Pinnacle); el archivo anterior se guarda intacto en proyecciones_2026_antes_v7.csv.
#     (8, pedido de Ozz el 2-oct, antes de instalar v7) récord de cada equipo junto a su nombre en "Juego" y, debajo de
#     los juegos de cada "Semana N", el bloque de los 32 equipos ordenados por récord con lo que pasó ANTES de esa
#     semana: récord, ganados esperados por el mercado, ATS contra el cierre, QB del último juego, puntos a favor y en
#     contra, rival de esta semana y la semana pasada. Sale solo de nflverse (descriptivo; no toca el modelo).
# v8 (3-oct, pedido de Ozz: "que la entienda un niño de 10 años y un abuelo de 76"; v7 no llegó a instalarse): la hoja
#     se lee en palabras. Cada "Semana N" empieza con la parte simple (partido, cuándo, favorito de las apuestas, qué tan
#     seguro con "7 de cada 10" y una barrita, la máquina en prueba en palabras, teaser y resultado) y deja todo el
#     detalle técnico de v7 a la derecha, en gris, después de una columna vacía. El bloque de equipos y el Boleto van en
#     frases (el Boleto conserva su tabla técnica a la derecha). Solo cambia la presentación: proyección, registro,
#     selecciones, boleto y agente Gemini quedan como en v7.
# v8.1 (decisiones 43, 45 y 46 de Ozz, 7-oct, registradas antes de la primera señal que cuenta): (43) la confiabilidad
#     de cada fuente del QB se mide contra el QB del primer dropback de cada equipo en la jugada por jugada de nflverse
#     (games.csv no corrige el QB después del juego: H34); sin jugada por jugada todavía, games.csv queda como verdad
#     provisional. (45) modo 'informe' y envío automático cuando cierra una semana que cuenta: CLV de las selecciones de
#     29A con la señal que cuenta (decide el CLV sin vig, 46; se reportan el CLV con el precio de Pinnacle y con el de
#     BetOnline), intervalos por remuestreo de juegos y autopsia de cada juego (38, con la prueba 1 en probabilidad sin
#     vig). No cambian el modelo, la simulación, el consenso del QB, las selecciones, el boleto ni la hoja (solo el texto
#     de confiabilidad que ya mostraba). La proyección es idéntica a la de v8.
# v8.2 (decisión 49, ruta A, aprobada por Ozz el 8-oct): registro en vivo «e2» en las corridas automáticas T−85,
#     después de g1 y en una consulta aparte (enfermedad, vestuario, descanso de titulares anunciado y una línea libre
#     por equipo; salidas/semana/e2_vivo.csv; tope propio de 20 consultas por día). El modo estado muestra solo conteos.
#     No cambian la proyección, g1 (ni su huella), el consenso del QB, las selecciones, el boleto, el informe ni la hoja.
# v8.3 (decisiones 50, 52 y 55 de Ozz, 9-11 oct; registradas antes de construir):
#     (50) sección «Fuera» del informe semanal: los juegos cuya proyección que cuenta quedó Fuera (spread, total o QB
#     dudoso), error del modelo contra el del cierre, si cubrió el lado del modelo, con y sin cambio de QB, acumulado con
#     IC; solo registro, no decide nada.
#     (52) 29A decide sobre el EXCESO: CLV sin vig de la selección menos el CLV sin vig medio de los lados del mismo tipo
#     (no favorito o favorito), mercado y semana; el CLV sin restar se reporta y no decide (H37).
#     (55) el VIGÍA (claude/registro_55_vigia.md): en las corridas automáticas T−85, después de g1 y antes de e2, Gemini
#     reporta solo hechos de fuente oficial sobre jugadores que no juegan; el código cruza nombres con el roster, decide los
#     titulares con los snaps y avisa «la máquina no sabe esto» (Telegram aparte y columna E de la hoja); verificación con
#     los snaps en el informe y piloto Flash-Lite contra 3.8 Flash con la regla escrita antes.
#     No cambian la proyección, s2-v1, g1 ni e2 (ni sus huellas), el consenso del QB, las selecciones ni el boleto.
# v8.3.1 (Ozz, 11-oct, opción b, después de que 3.8 Flash agotara los 180 s en la primera T−85 real): el vigía tiene
#     300 s en vez de 180 y 16 consultas a la vez en vez de 8 (todas las de 3.8 Flash de un grupo empiezan juntas).
#     Huellas nuevas: el piloto cuenta solo consultas con las huellas actuales y desde la semana 6 (VIGIA_PILOTO_DESDE);
#     lo consultado con v8.3 queda en el registro y en la verificación, pero no en el piloto. Nada más cambia.
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
FILAS_MAX = 60                     # filas por pestaña semanal (v7: encabezado en la 4, juegos 5-24, equipos 26-59)
JUEGOS_MAX = 20                    # filas de juegos de cada semana (5 a 24)
FILA_EQUIPOS = 26                  # v7, ajuste 8: título del bloque de equipos (encabezado en la 27, equipos desde la 28)
ENCAB_EQUIPOS = ["Equipo", "Ganados-perdidos", "Las apuestas esperaban (ganados)", "Contra la línea de las apuestas",
                 "Puntos por partido", "Esta semana", "La semana pasada"]
BE_ESTANDAR = -110                 # precio para "necesita X %" cuando BetOnline no tiene la línea de Pinnacle

CAMPOS = ["corrida_utc", "tipo", "version", "game_id", "semana", "game_type", "inicio_utc", "local", "visita",
          "qb_local_id", "qb_visita_id", "qb_local_fuente", "qb_visita_fuente", "margen", "mediana", "total",
          "p_local", "p_empate", "de_margen", "localia", "ajuste_qb_local_pts", "ajuste_qb_visita_pts",
          "pin_ts", "pin_horas", "pin_hcp_local", "pin_cuota_sp_local", "pin_cuota_sp_visit", "pin_ml_local",
          "pin_ml_visit", "pin_p_ml_local", "pin_p_sp_local", "bo_ts", "bo_horas", "bo_hcp_local", "bo_ml_local",
          "bo_ml_visit", "nfl_spread_line", "nfl_total_line", "ref_spread", "spread_modelo", "spread_ref",
          "dif_spread", "dif_total", "marcado_spread", "marcado_total", "sesgo_spread_semana", "sesgo_total_semana",
          "bandera_sesgo", "p_cubre_local", "p_push", "sel_ml", "sel_ml_ventaja", "sel_sp", "sel_sp_prob",
          "sel_estado", "wong", "wong_linea",
          # v7 (al final, para no mover las columnas anteriores): precio del spread de BetOnline; piezas del margen del
          # modelo en puntos a favor del local (respuesta lineal del simulador, RESP de s2-v1: descriptivo); primera foto
          # de Pinnacle del juego en el log del bot ("apertura" que vio el bot)
          "bo_cuota_sp_local", "bo_cuota_sp_visit", "comp_pase_pts", "comp_corrida_pts", "comp_qb_pts",
          "comp_localia_pts", "pin_ap_ts", "pin_ap_hcp_local"]
REGISTRO_ANTES_V7 = SAL / "proyecciones_2026_antes_v7.csv"   # copia intacta del registro con las columnas de v6.2


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


def migrar_registro():
    """v7: si el registro tiene las columnas de una versión anterior, agrega las nuevas al final (vacías en las filas
    viejas) sin tocar ningún valor; antes guarda el archivo original intacto. Devuelve (copia, filas) o None."""
    if not REGISTRO.exists():
        return None
    with open(REGISTRO, newline="", encoding="utf-8") as fh:
        enc = next(csv.reader(fh), None)
    if not enc or enc == CAMPOS:
        return None
    sobran = [c for c in enc if c not in CAMPOS]
    if sobran or enc != CAMPOS[:len(enc)]:
        raise SystemExit(f"El registro tiene columnas que no reconozco ({sobran[:5]}): no lo toco. Avísale a Claude.")
    copia = REGISTRO_ANTES_V7 if not REGISTRO_ANTES_V7.exists() else SAL / f"proyecciones_2026_antes_v7_{int(time.time())}.csv"
    shutil.copy2(REGISTRO, copia)
    with open(REGISTRO, newline="", encoding="utf-8") as fh:
        filas = list(csv.DictReader(fh))
    tmp = REGISTRO.with_suffix(".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CAMPOS)
        w.writeheader()
        for f in filas:
            w.writerow({k: (f.get(k) or "") for k in CAMPOS})
    tmp.replace(REGISTRO)
    return copia, len(filas)


def anexar_registro(filas):
    SAL.mkdir(parents=True, exist_ok=True)
    migrar_registro()
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


# Columnas de la pestaña semanal (v8). A-G: parte simple (lo que se lee) · H: separador · I-AB: detalle técnico de v7, en gris
#   (proyección I-T, cierre U-Y, control Z-AB). Todo lo escribe la EC2; la hoja es de solo lectura.
ENCAB_SIMPLE = ["Partido", "Cuándo", "Favorito (las apuestas)", "¿Qué tan seguro?",
                "La máquina (en prueba, no apostar por ella)", "Teaser (6 puntos extra)", "Resultado"]
ENCAB_TEC = ["Línea mercado", "Línea modelo", "Modelo vs mercado", "Total consenso", "Total modelo", "Gana (modelo)",
             "Gana (Pinnacle)", "Señal ML", "Señal spread", "Pata Wong (BetOnline)", "Estado", "Por qué difiere",
             "Resultado (técnico)", "Error modelo / cierre", "Lado del modelo", "Total real", "Pata Wong +6", "QB usados",
             "Corrida", "game_id"]
ENCAB = ENCAB_SIMPLE + [""] + ENCAB_TEC
NCOL = len(ENCAB)                                   # 28 (A-AB)
COL_ID = "AB"
NS = len(ENCAB_SIMPLE)                              # 7: A-G
T0 = NS + 1                                         # 8: primera columna técnica (I)
COLORES = {"verde": "#D9EAD3", "azul": "#9FC5E8", "rojo": "#F4CCCC", "cierre": "#D0E0E3", "resumen": "#F3F3F3",
           "encab": "#1F3864", "gris": "#999999", "gris_texto": "#808080", "blanco": "#FFFFFF",
           "cubrio": "#B7E1CD", "no_cubrio": "#F4C7C3", "encab_tec": "#7F7F7F"}
COMO_LEER = ("El favorito es el equipo que las apuestas creen que gana; «por 7 puntos» es por cuánto creen que gana. "
             "«7 de cada 10» quiere decir que, si el partido se jugara 10 veces, ganaría unas 7. La máquina es nuestro "
             "programa: está a prueba y no se apuesta por ella. Azul: ese equipo sirve para el teaser (6 puntos extra). "
             "🔎: el vigía encontró, con fuente oficial, titulares que no juegan y que la máquina no conoce. "
             "Más a la derecha, en gris, está el detalle técnico: no hace falta leerlo.")
LEYENDA_TEC = ("Detalle técnico (no hace falta leerlo). Verde: señal del modelo que cuenta para el registro 29A (sin validar; "
               "H29: el cierre le gana por 0,4 pts; ningún dinero por el motor, 31A). Azul: pata Wong (H28). Rojo (Fuera): el "
               "modelo y el mercado difieren mucho, o el QB es dudoso: no se usa el modelo. Gris en cursiva: retro (hecha "
               "después del juego; no cuenta). Cierre: verde = cubrió, rojo = no cubrió. Líneas en convención de la casa: "
               "DAL -3.5 = DAL favorito por 3,5.")


def _rgb(h):
    h = h.lstrip("#")
    return {"red": int(h[0:2], 16) / 255, "green": int(h[2:4], 16) / 255, "blue": int(h[4:6], 16) / 255}


def _rango(sid, f0, f1, c0, c1):
    return {"sheetId": sid, "startRowIndex": f0, "endRowIndex": f1, "startColumnIndex": c0, "endColumnIndex": c1}


TITULO_PRUEBA, SID_PRUEBA = "Prueba (se borra sola)", 1999     # pestaña temporal de 'hoja-prueba'


def crear_pestana(hoja, sem, titulo=None, sid=None):
    """Crea la pestaña 'Semana N' (primera a la izquierda). v8: parte simple A-G (A inmovilizada), separador H y detalle
    técnico I-AB en gris; bloque de equipos debajo de los juegos. Ninguna celda combinada cruza el borde A|B (Sheets
    rechaza toda la tanda con 400 si una combinación cruza las columnas inmovilizadas)."""
    sid = 1000 + sem if sid is None else sid
    t = titulo or pestana(sem)
    F = FILAS_MAX
    G = 4 + JUEGOS_MAX                                  # fin de las filas de juegos (los colores no tocan el bloque de equipos)
    E = FILA_EQUIPOS - 1                                # fila del título del bloque de equipos (índice desde 0)
    fondo = lambda r, color: {"repeatCell": {"range": r, "cell": {"userEnteredFormat": {"backgroundColorStyle": {"rgbColor": _rgb(color)}}},  # noqa: E731
                                             "fields": "userEnteredFormat.backgroundColorStyle"}}
    texto = lambda r, fmt, campos="userEnteredFormat.textFormat": {"repeatCell": {"range": r, "cell": {"userEnteredFormat": fmt},  # noqa: E731
                                                                                 "fields": campos}}
    regla = lambda rangos, formula, fmt, idx: {"addConditionalFormatRule": {"index": idx, "rule": {  # noqa: E731
        "ranges": rangos, "booleanRule": {"condition": {"type": "CUSTOM_FORMULA", "values": [{"userEnteredValue": formula}]}, "format": fmt}}}}
    fmt_fondo = lambda color, negrita=False: {"backgroundColorStyle": {"rgbColor": _rgb(color)}, "textFormat": {"bold": negrita}}  # noqa: E731
    gris_it = {"textFormat": {"italic": True, "foregroundColorStyle": {"rgbColor": _rgb(COLORES["gris_texto"])}}}
    ancho = lambda c0, c1, px: {"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": c0, "endIndex": c1},  # noqa: E731
                                                              "properties": {"pixelSize": px}, "fields": "pixelSize"}}
    alto = lambda f0, f1, px: {"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "ROWS", "startIndex": f0, "endIndex": f1},  # noqa: E731
                                                             "properties": {"pixelSize": px}, "fields": "pixelSize"}}
    combinar = lambda c0, c1, f=0: {"mergeCells": {"range": _rango(sid, f, f + 1, c0, c1), "mergeType": "MERGE_ALL"}}  # noqa: E731
    encab = lambda f, c0, c1, color: texto(_rango(sid, f, f + 1, c0, c1), {  # noqa: E731
        "textFormat": {"bold": True, "foregroundColorStyle": {"rgbColor": _rgb(COLORES["blanco"])}},
        "backgroundColorStyle": {"rgbColor": _rgb(color)}, "wrapStrategy": "WRAP", "verticalAlignment": "MIDDLE"},
        "userEnteredFormat.textFormat,userEnteredFormat.backgroundColorStyle,userEnteredFormat.wrapStrategy,userEnteredFormat.verticalAlignment")
    ajuste = "userEnteredFormat.wrapStrategy,userEnteredFormat.verticalAlignment"
    pedidos = [
        {"addSheet": {"properties": {"sheetId": sid, "title": t, "index": 0,
                                     "gridProperties": {"rowCount": F, "columnCount": NCOL, "frozenRowCount": 4, "frozenColumnCount": 1}}}},
        # filas 1-3: A rótulo | B-G texto simple | I-AB texto técnico (ninguna combinación cruza el borde A|B)
        combinar(1, NS, 0), combinar(T0, NCOL, 0), combinar(1, NS, 1), combinar(T0, NCOL, 1),
        combinar(1, NS, 2), combinar(T0, NCOL, 2),
        texto(_rango(sid, 0, 1, 0, 1), {"textFormat": {"bold": True, "fontSize": 13}}),
        texto(_rango(sid, 1, 3, 0, 1), {"textFormat": {"bold": True}}),
        texto(_rango(sid, 0, 3, 0, NCOL), {"wrapStrategy": "WRAP", "verticalAlignment": "MIDDLE"}, ajuste),
        fondo(_rango(sid, 1, 3, 0, NS), COLORES["resumen"]),
        texto(_rango(sid, 0, 3, T0, NCOL), {"textFormat": {"fontSize": 8, "italic": True,
                                                           "foregroundColorStyle": {"rgbColor": _rgb(COLORES["gris_texto"])}}}),
        alto(1, 2, 64), alto(2, 3, 48),
        # fila 4: encabezados (simple en azul oscuro, técnico en gris)
        encab(3, 0, NS, COLORES["encab"]), encab(3, T0, NCOL, COLORES["encab_tec"]),
        # juegos: la parte simple con texto ajustado; la técnica chica y gris
        texto(_rango(sid, 4, G, 0, NS), {"wrapStrategy": "WRAP", "verticalAlignment": "MIDDLE"}, ajuste),
        texto(_rango(sid, 4, G, T0, NCOL), {"textFormat": {"fontSize": 8, "foregroundColorStyle": {"rgbColor": _rgb(COLORES["gris"])}}}),
        ancho(0, 1, 180), ancho(1, 2, 95), ancho(2, 3, 135), ancho(3, 4, 180), ancho(4, 5, 190), ancho(5, 6, 120),
        ancho(6, 7, 200), ancho(7, 8, 30),
        ancho(8, 9, 115), ancho(9, 10, 95), ancho(10, 11, 110), ancho(11, 13, 75), ancho(13, 15, 85), ancho(15, 16, 215),
        ancho(16, 17, 230), ancho(17, 18, 140), ancho(18, 19, 220), ancho(19, 20, 360), ancho(20, 21, 125), ancho(21, 22, 105),
        ancho(22, 23, 120), ancho(23, 24, 85), ancho(24, 25, 130), ancho(25, 26, 210), ancho(26, 27, 115), ancho(27, 28, 125),
        # colores (en cada celda manda la primera regla que se cumple)
        # parte simple
        regla([_rango(sid, 4, G, 5, 6)], "=LEN($F5)>0", fmt_fondo(COLORES["azul"], True), 0),
        regla([_rango(sid, 4, G, 4, 5)], '=LEFT($E5,16)="No le hagas caso"', fmt_fondo(COLORES["rojo"]), 1),
        regla([_rango(sid, 4, G, 6, 7)], '=ISNUMBER(SEARCH("✔",$G5))', fmt_fondo(COLORES["cubrio"]), 2),
        regla([_rango(sid, 4, G, 6, 7)], '=ISNUMBER(SEARCH("✘",$G5))', fmt_fondo(COLORES["no_cubrio"]), 3),
        regla([_rango(sid, 4, G, 0, 5)], '=LEFT($AA5,5)="retro"', gris_it, 4),
        # detalle técnico (las mismas reglas de v7, corridas a I-AB)
        regla([_rango(sid, 4, G, 17, 18)], "=LEN($R5)>0", fmt_fondo(COLORES["azul"], True), 5),
        regla([_rango(sid, 4, G, T0, 20)], '=LEFT($AA5,5)="retro"', gris_it, 6),
        regla([_rango(sid, 4, G, T0, 20)], '=LEFT($S5,5)="Fuera"', fmt_fondo(COLORES["rojo"]), 7),
        regla([_rango(sid, 4, G, 15, 17)], '=AND(LEFT($S5,9)="candidata",LEN(P5)>0,LEFT(P5,3)<>"sin",'
                                           'LEFT(P5,5)<>"retro",LEFT(P5,8)<>"excluida")', fmt_fondo(COLORES["verde"], True), 8),
        regla([_rango(sid, 4, G, 22, 23)], '=LEFT($W5,6)="cubrió"', fmt_fondo(COLORES["cubrio"]), 9),
        regla([_rango(sid, 4, G, 22, 23)], '=LEFT($W5,2)="no"', fmt_fondo(COLORES["no_cubrio"]), 10),
        regla([_rango(sid, 4, G, 24, 25)], '=LEFT($Y5,6)="cubrió"', fmt_fondo(COLORES["cubrio"]), 11),
        regla([_rango(sid, 4, G, 24, 25)], '=LEFT($Y5,2)="no"', fmt_fondo(COLORES["no_cubrio"]), 12),
        # bloque de equipos: título A | B-G, encabezado A-G, filas con texto ajustado
        combinar(1, NS, E), fondo(_rango(sid, E, E + 1, 0, NS), COLORES["resumen"]),
        texto(_rango(sid, E, E + 1, 0, NS), {"wrapStrategy": "WRAP", "verticalAlignment": "MIDDLE"}, ajuste),
        texto(_rango(sid, E, E + 1, 0, 1), {"textFormat": {"bold": True}}),
        alto(E, E + 1, 52),
        encab(E + 1, 0, len(ENCAB_EQUIPOS), COLORES["encab"]),
        texto(_rango(sid, E + 2, F, 0, len(ENCAB_EQUIPOS)), {"wrapStrategy": "WRAP", "verticalAlignment": "MIDDLE"}, ajuste),
    ]
    hoja.lote(pedidos)
    hoja.escribir(f"'{t}'!A4", [ENCAB])
    return sid


def asegurar_pestana(hoja, sem):
    """La pestaña de la semana con el diseño v4. Si existe con otro diseño (versión anterior), la borra y la rehace:
    todo lo que muestra sale del registro, de la retrospectiva y de nflverse (no hay nada escrito a mano)."""
    t = pestana(sem)
    ps = hoja.pestanas()
    if t in ps:
        enc = hoja.leer(f"'{t}'!4:4")          # v7: la fila entera (una pestaña vieja de 21 columnas no tiene la V)
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


def pct(x, dec=0):
    """0.524 → '52,4 %' (coma decimal, como en el resto de la hoja)."""
    return f"{100 * x:.{dec}f}".replace(".", ",") + " %"


def senal_ml_txt(f):
    """v7, ajuste 6: la señal en palabras, para que no se lea como 'gana tal equipo': 'MIA ML: modelo 20 % · precio 16 %'
    (precio = probabilidad de Pinnacle sin vig). Vacío si no hay señal."""
    if not f.get("sel_ml"):
        return ""
    loc = f["sel_ml"] == "local"
    eq = f["local"] if loc else f["visita"]
    pm, pp = _num(f.get("p_local")), _num(f.get("pin_p_ml_local"))
    if pm is None or pp is None:
        return f"{eq} ML"
    if not loc:
        pm, pp = 1 - pm, 1 - pp
    return f"{eq} ML: modelo {pct(pm)} · precio {pct(pp)}"


def necesita_sp(f, lado):
    """Probabilidad de cubrir que hace falta para no perder: con el precio de BetOnline si su línea es la misma de
    Pinnacle (foto de ≤ 12 h); si no, a −110 (52,4 %)."""
    h, hb = _num(f.get("pin_hcp_local")), _num(f.get("bo_hcp_local"))
    c = _num(f.get("bo_cuota_sp_local" if lado == "local" else "bo_cuota_sp_visit"))
    cuota = c if (h is not None and hb is not None and c is not None and abs(h - hb) < 0.05) else BE_ESTANDAR
    return 1 / decimal(cuota)


def senal_sp_txt(f):
    """v7, ajuste 6: 'MIA +11.0: cubre 55 % (necesita 52,4 %)'. Vacío si no hay señal."""
    if not f.get("sel_sp"):
        return ""
    h = float(f["pin_hcp_local"])
    eq, lin = (f["local"], h) if f["sel_sp"] == "local" else (f["visita"], -h)
    lin_txt = "PK" if abs(lin) < 0.05 else f"{lin:+.1f}"
    return f"{eq} {lin_txt}: cubre {pct(float(f['sel_sp_prob']))} (necesita {pct(necesita_sp(f, f['sel_sp']), 1)})"


def fuera(f):
    """Juego en rojo: el modelo y el mercado difieren mucho (filtro de alucinación) o el QB es dudoso."""
    return f.get("tipo") != "retro" and (es_dudoso(f) or f.get("marcado_spread") in (1, "1") or f.get("marcado_total") in (1, "1"))


def celda_senal(f, cual):
    """v7, ajustes 1 y 2: lo que muestra la celda de señal (ML o spread) en la pestaña semanal."""
    if f.get("tipo") == "retro":
        return "retro (n/a)"
    if _num(f.get("pin_p_ml_local" if cual == "ml" else "pin_hcp_local")) is None:
        return "sin Pinnacle 3 h"
    txt = senal_ml_txt(f) if cual == "ml" else senal_sp_txt(f)
    if not txt:
        return "sin señal"
    if fuera(f) or str(f.get("sel_estado") or "").startswith("excluida"):
        return f"excluida · {txt}"
    return txt


def _a_favor(loc, vis, x):
    """Puntos a favor del local (x > 0) o del visitante (x < 0): 'DAL +3.2'."""
    return "0.0" if abs(x) < 0.05 else f"{loc if x > 0 else vis} +{abs(x):.1f}"


def porque_txt(f):
    """v7, ajuste 4 (descriptivo): de dónde sale el número del modelo y cuánto se movió Pinnacle desde la primera foto del
    bot. Piezas = respuesta lineal del simulador (puntos de margen por EPA/jugada, RESP de s2-v1); la suma se acerca
    al margen simulado sin ser exacta (el simulador no es lineal)."""
    loc, vis = f.get("local"), f.get("visita")
    partes = []
    comps = [("pase", _num(f.get("comp_pase_pts"))), ("corrida", _num(f.get("comp_corrida_pts"))),
             ("QB", _num(f.get("comp_qb_pts"))), ("localía", _num(f.get("comp_localia_pts")))]
    if all(v is not None for _, v in comps):
        for nombre, v in comps:
            if nombre == "localía" and abs(v) < 0.05:
                partes.append("sede neutral")
            elif nombre == "QB" and abs(v) < 0.05:
                partes.append("QB sin ajuste")
            else:
                partes.append(f"{nombre} {_a_favor(loc, vis, v)}")
    else:
        partes.append("sin desglose (corrida anterior a v7)")
    ap, h = _num(f.get("pin_ap_hcp_local")), _num(f.get("pin_hcp_local"))
    if ap is not None and h is not None:
        mov = h - ap                                    # < 0: la línea se movió hacia el local
        if abs(mov) < 0.05:
            partes.append(f"Pinnacle sin cambio desde la apertura ({linea_txt(loc, vis, ap)})")
        else:
            partes.append(f"Pinnacle abrió {linea_txt(loc, vis, ap)} y se movió {abs(mov):.1f} hacia {loc if mov < 0 else vis}")
    return " · ".join(partes)


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
    if dq:                                             # v7, ajuste 3: desde 32b no hay revisión manual → "Fuera"
        return "Fuera: QB dudoso (" + " | ".join(dq) + ")" + (f" · modelo y mercado difieren ({d})" if d else "")
    if d:
        return "Fuera: modelo y mercado difieren (" + d + ")"
    return f.get("sel_estado") or ""


# --------------------------------------------------------------------------------------
# v8: textos en palabras para la parte simple ("que lo entienda un niño de 10 años y un abuelo de 76")
# --------------------------------------------------------------------------------------
def apodo(t):
    """'BUF' → 'Bills' (el apodo del equipo)."""
    return EQUIPOS.get(t, t).split()[-1]


def cuando_txt(t):
    """Hora de Caracas en 12 horas: 'Dom 4 oct · 1:00 pm'."""
    c = t.astimezone(CARACAS)
    h = c.hour % 12 or 12
    return f"{DIAS[c.weekday()].capitalize()} {c.day} {MESES[c.month - 1]} · {h}:{c.minute:02d} {'am' if c.hour < 12 else 'pm'}"


def partido_txt(g, eq):
    """'Patriots (1-2) visitan a Bills (3-0)'; en cancha neutral, 'Colts (1-2) vs Commanders (1-2), cancha neutral'."""
    vis, loc = g["away_team"], g["home_team"]
    v, l_ = f"{apodo(vis)} ({record_txt(eq[vis])})", f"{apodo(loc)} ({record_txt(eq[loc])})"
    return f"{v} vs {l_}, cancha neutral" if g.get("location") == "Neutral" else f"{v} visitan a {l_}"


def favorito_de(g, u):
    """Lo que dicen las apuestas antes del juego: Pinnacle sin vig de la última proyección (≤ 3 h) o, si no hay, el
    consenso de nflverse. Devuelve dict(fav, local, puntos, p) o None. El favorito es el del spread; su probabilidad
    sale del moneyline sin vig (método de potencia)."""
    h = _num((u or {}).get("pin_hcp_local")) if u else None
    p_loc = _num((u or {}).get("pin_p_ml_local")) if u else None
    if h is None or p_loc is None:
        sl, ml_l, ml_v = _num(g.get("spread_line")), _num(g.get("home_moneyline")), _num(g.get("away_moneyline"))
        if sl is None:
            return None
        h = -sl
        p_loc = sin_vig_potencia(ml_l, ml_v) if ml_l is not None and ml_v is not None else None
    if p_loc is None:
        return None
    local = h < 0 or (abs(h) < 0.05 and p_loc >= 0.5)
    return dict(fav=g["home_team"] if local else g["away_team"], dog=g["away_team"] if local else g["home_team"],
                local=local, puntos=abs(h), p=p_loc if local else 1 - p_loc)


def puntos_txt(x):
    """7.0 → '7'; 2.5 → '2,5'."""
    return f"{x:.0f}" if abs(x - round(x)) < 1e-9 else _dec(x)


def favorito_txt(f):
    """'Bills, por 7 puntos' (el favorito de las apuestas y por cuánto creen que gana)."""
    if f is None:
        return "Todavía no hay apuestas"
    if f["puntos"] < 0.05:
        return f"Parejo (las apuestas se inclinan un poquito por {apodo(f['fav'])})"
    return f"{apodo(f['fav'])}, por {puntos_txt(f['puntos'])} puntos"


def etiqueta_seguro(k):
    """La palabra sale del mismo número que se muestra ('k de cada 10'), para que nunca se contradigan."""
    return "parejo" if k <= 5 else ("algo favorito" if k == 6 else ("favorito claro" if k <= 8 else "muy favorito"))


def seguro_txt(f):
    """'●●●●●●●○○○ 7 de cada 10 · favorito claro' (probabilidad de ganar del favorito, sin vig)."""
    if f is None:
        return ""
    k = min(10, max(0, int(f["p"] * 10 + 0.5)))
    return f"{'●' * k}{'○' * (10 - k)} {apodo(f['fav'])} gana {k} de cada 10 · {etiqueta_seguro(k)}"


def maquina_txt(u, f):
    """Lo que opina el modelo, en palabras (en prueba: no se apuesta por él)."""
    if not u or _num(u.get("p_local")) is None:
        return "Todavía no corrió"
    if f is None:
        return ""
    retro = u.get("tipo") == "retro"
    if fuera(u):
        if es_dudoso(u):
            return "No le hagas caso en este juego (no se sabe bien quién juega de QB)"
        return "No le hagas caso en este juego (ve algo muy distinto a las apuestas)"
    pm = float(u["p_local"]) if f["local"] else 1 - float(u["p_local"])
    if pm < 0.5:
        txt = f"Cree que gana {apodo(f['dog'])}"
    elif pm < f["p"] - 0.06:
        txt = f"También va con {apodo(f['fav'])}, pero lo ve más parejo"
    elif pm > f["p"] + 0.06:
        txt = f"Va con {apodo(f['fav'])} y lo ve más fácil"
    else:
        txt = "Opina igual"
    return ("Retro (hecha después del juego, no cuenta): " + txt[0].lower() + txt[1:]) if retro else txt


def teaser_txt(u):
    if not u or not u.get("wong"):
        return ""
    eq = u["local"] if u["wong"] == "local" else u["visita"]
    return f"Sirve: {apodo(eq)} +{float(u['wong_linea']) + 6:.1f}"


def resultado_simple(g, f, u):
    """'Ganó Bills 24-16 · el favorito acertó ✔' (+ el teaser, si había pata)."""
    res = _num(g.get("result"))
    if res is None or g.get("home_score") is None:
        return ""
    hs, as_ = int(g["home_score"]), int(g["away_score"])
    if res == 0:
        txt = f"Empate {hs}-{as_}"
    else:
        gan = g["home_team"] if res > 0 else g["away_team"]
        txt = f"Ganó {apodo(gan)} {max(hs, as_)}-{min(hs, as_)}"
        if f is not None and f["puntos"] >= 0.05:
            txt += " · el favorito acertó ✔" if gan == f["fav"] else " · el favorito falló ✘"
    if u and u.get("wong"):
        lin = _num(u.get("wong_linea"))
        if lin is not None:
            x = (res if u["wong"] == "local" else -res) + lin + 6
            txt += " · teaser " + ("✔" if x > 0 else ("empate" if x == 0 else "✘"))
    return txt


def resumen_simple(filas_info, n_juegos):
    """Fila 3, en palabras: cuántos se jugaron, cuántas veces ganó el favorito contra lo que se esperaba, y la máquina."""
    jugados = [(g, f, u) for g, f, u in filas_info if _num(g.get("result")) is not None]
    if not jugados:
        return f"Todavía no se juega ningún partido de esta semana ({n_juegos} en total)."
    con_fav = [(g, f) for g, f, _ in jugados if f is not None and f["puntos"] >= 0.05 and g["result"] != 0]
    acierta = sum(1 for g, f in con_fav if (g["result"] > 0) == f["local"])
    esperado = sum(f["p"] for _, f in con_fav)
    txt = (f"Jugados {len(jugados)} de {n_juegos}. El favorito ganó {acierta} de {len(con_fav)} "
           f"(las apuestas esperaban {_dec(esperado)}).")
    maq = [(g, u) for g, _, u in jugados if u and _num(u.get("p_local")) is not None and g["result"] != 0]
    if maq:
        ok = sum(1 for g, u in maq if (float(u["p_local"]) > 0.5) == (g["result"] > 0))
        txt += f" La máquina (en prueba) acertó el ganador {ok} de {len(maq)}."
    return txt


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
# Equipos antes de la semana (v7, ajuste 8; pedido de Ozz el 2-oct). Solo nflverse, descriptivo: el récord y las rachas
# ya los descuenta el mercado (H4, H14, H23); por eso se muestran junto a lo que el mercado esperaba.
# --------------------------------------------------------------------------------------
def _qb_corto(nombre):
    partes = str(nombre or "").split()
    return f"{partes[0][0]}. {' '.join(partes[1:])}" if len(partes) >= 2 else (partes[0] if partes else "")


def _dec(x, d=1):
    return f"{x:.{d}f}".replace(".", ",")


def equipos_antes(g26, semana):
    """{equipo: dict} con los juegos de 2026 de semanas ANTERIORES a 'semana' que ya tienen resultado: ganados, perdidos,
    empates, ganados esperados (probabilidad sin vig del moneyline de cierre de nflverse, método de potencia), récord
    contra el spread de cierre de nflverse (ATS), puntos a favor y en contra, y el último juego (con su QB titular)."""
    import polars as pl
    eq = {}
    for t in g26["home_team"].to_list() + g26["away_team"].to_list():
        eq.setdefault(t, dict(n=0, g=0, p=0, e=0, esp=0.0, n_esp=0, ats=[0, 0, 0], pf=0, pc=0, ult=None))
    previos = g26.filter((pl.col("week") < semana) & pl.col("result").is_not_null()).sort(["inicio", "game_id"])
    for r in previos.iter_rows(named=True):
        ml_l, ml_v = _num(r.get("home_moneyline")), _num(r.get("away_moneyline"))
        p_loc = sin_vig_potencia(ml_l, ml_v) if ml_l is not None and ml_v is not None else None
        sl = _num(r.get("spread_line"))
        for local in (True, False):
            t = r["home_team"] if local else r["away_team"]
            rival = r["away_team"] if local else r["home_team"]
            m = r["result"] if local else -r["result"]               # margen del equipo
            pts, opp = (r["home_score"], r["away_score"]) if local else (r["away_score"], r["home_score"])
            d = eq[t]
            d["n"] += 1
            d["pf"] += pts
            d["pc"] += opp
            d["g" if m > 0 else ("p" if m < 0 else "e")] += 1
            if p_loc is not None:
                d["esp"] += p_loc if local else 1 - p_loc
                d["n_esp"] += 1
            x = None
            if sl is not None:
                x = m - (sl if local else -sl)                          # contra el margen que esperaba el cierre
                d["ats"][0 if x > 0 else (1 if x < 0 else 2)] += 1
            d["ult"] = dict(semana=int(r["week"]), local=local, rival=rival, pts=pts, opp=opp, m=m,
                            hcp=None if sl is None else (-sl if local else sl), x=x,
                            qb=r.get("home_qb_name" if local else "away_qb_name"))
    return eq


def record_txt(d):
    return f"{d['g']}-{d['p']}" + (f"-{d['e']}" if d["e"] else "")


def filas_equipos(g26, semana):
    """Bloque de equipos de la pestaña semanal, en palabras: título, encabezado y una fila por equipo, de mejor a peor
    récord (desempate: diferencia de puntos; después, por nombre). Solo juegos de semanas anteriores."""
    import polars as pl
    eq = equipos_antes(g26, semana)
    esta = {}
    for r in g26.filter(pl.col("week") == semana).iter_rows(named=True):
        if r.get("location") == "Neutral":
            esta[r["home_team"]] = f"juega con {apodo(r['away_team'])} (cancha neutral)"
            esta[r["away_team"]] = f"juega con {apodo(r['home_team'])} (cancha neutral)"
        else:
            esta[r["home_team"]] = f"recibe a {apodo(r['away_team'])}"
            esta[r["away_team"]] = f"visita a {apodo(r['home_team'])}"
    orden = sorted(eq, key=lambda t: (-((eq[t]["g"] + 0.5 * eq[t]["e"]) / eq[t]["n"]) if eq[t]["n"] else 0.0,
                                      -(eq[t]["pf"] - eq[t]["pc"]), apodo(t)))
    filas = []
    for t in orden:
        d = eq[t]
        if not d["n"]:
            filas.append([apodo(t), "0-0", "", "", "", esta.get(t, "descansa"), "todavía no ha jugado"])
            continue
        u = d["ult"]
        if u["m"] > 0:
            txt = f"Le ganó {u['pts']}-{u['opp']} a {apodo(u['rival'])}"
        elif u["m"] < 0:
            txt = f"Perdió {u['pts']}-{u['opp']} con {apodo(u['rival'])}"
        else:
            txt = f"Empató {u['pts']}-{u['opp']} con {apodo(u['rival'])}"
        if u["qb"]:
            txt += f", con {_qb_corto(u['qb'])} de QB"
        if u["hcp"] is not None and u["x"] is not None:
            if abs(u["hcp"]) < 0.05:
                txt += ". Era parejo"
            elif u["hcp"] < 0:
                txt += f". Era favorito por {puntos_txt(abs(u['hcp']))}"
            else:
                txt += f". Las apuestas lo daban perdedor por {puntos_txt(u['hcp'])}"
            txt += (" y quedó justo en la línea" if u["x"] == 0 else
                    (f" y cubrió por {puntos_txt(abs(u['x']))}" if u["x"] > 0 else f" y no cubrió (le faltaron {puntos_txt(abs(u['x']))})"))
        txt += "."
        if u["semana"] != semana - 1:
            txt = f"(Semana {u['semana']}, su último partido) " + txt
        a, b, c = d["ats"]
        linea = f"cubrió {a} de {a + b + c}" + (f" ({c} justo en la línea)" if c else "")
        esperado = _dec(d["esp"]) + ("" if d["n_esp"] == d["n"] else f" (de {d['n_esp']} partidos)")
        filas.append([apodo(t), record_txt(d), esperado, linea,
                      f"anota {_dec(d['pf'] / d['n'])} · recibe {_dec(d['pc'] / d['n'])}", esta.get(t, "descansa"), txt])
    titulo = ["Cómo vienen los equipos",
              f"Antes de la semana {semana}, de mejor a peor. «Las apuestas esperaban» = cuántos partidos creían las apuestas "
              "que iba a ganar; ganar más de lo esperado puede ser suerte, y las apuestas ya lo saben (H4, H14, H23). "
              "«Contra la línea» = cuántas veces ganó por más (o perdió por menos) de lo que decían las apuestas."]
    return [titulo + [""] * (len(ENCAB_EQUIPOS) - len(titulo)), list(ENCAB_EQUIPOS)] + filas, eq


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


_LOG_BOT = {}
COLS_FOTO = ("ts_utc", "fuente", "game_id", "hcp_local", "cuota_sp_local", "cuota_sp_visit", "ml_local", "ml_visit")


def log_bot(bot_dir, con_cierres=False):
    """Fotos del bot (~/nfl_ev/lineas_log.csv, solo lectura), leídas una vez por corrida. con_cierres: suma
    cierres.csv (escaneo de T−10 del bot) si tiene las mismas columnas; si no, lo ignora."""
    import polars as pl
    clave = (str(bot_dir), con_cierres)
    if clave in _LOG_BOT:
        return _LOG_BOT[clave]
    ruta = Path(bot_dir) / "lineas_log.csv"
    if not ruta.exists():
        log(f"AVISO: no encuentro {ruta}; sin líneas del bot")
        _LOG_BOT[clave] = None
        return None
    lg = pl.read_csv(ruta, infer_schema_length=0)
    if con_cierres and (Path(bot_dir) / "cierres.csv").exists():
        try:
            ci = pl.read_csv(Path(bot_dir) / "cierres.csv", infer_schema_length=0)
            if all(c in ci.columns for c in COLS_FOTO) and all(c in lg.columns for c in COLS_FOTO):
                lg = pl.concat([lg.select(COLS_FOTO), ci.select(COLS_FOTO)], how="vertical_relaxed")
        except Exception as e:  # noqa: BLE001
            log(f"AVISO: no pude leer cierres.csv del bot ({type(e).__name__}); uso solo lineas_log.csv")
    _LOG_BOT[clave] = lg
    return lg


def lineas_bot(bot_dir, casa, ids, ahora, max_horas):
    """Última foto de una casa del bot de ≤ max_horas para cada juego: {game_id: dict}."""
    import polars as pl
    lg = log_bot(bot_dir)
    if lg is None:
        return {}
    lg = lg.filter((pl.col("fuente") == casa) & pl.col("game_id").is_in(ids))
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


def apertura_pin(bot_dir, ids, ahora):
    """Primera foto de Pinnacle de cada juego en el log del bot (la 'apertura' que vio el bot, que captura desde el
    24-sep-2026): {game_id: (ts, hcp_local)}. Solo descriptivo (columna 'Por qué difiere')."""
    import polars as pl
    lg = log_bot(bot_dir)
    if lg is None:
        return {}
    primera = {}
    for f in lg.filter((pl.col("fuente") == "pinnacle") & pl.col("game_id").is_in(ids)).iter_rows(named=True):
        ts, h = t_utc(f["ts_utc"]), _num(f.get("hcp_local"))
        if ts is None or h is None or ts > ahora:
            continue
        if f["game_id"] not in primera or ts < primera[f["game_id"]][0]:
            primera[f["game_id"]] = (ts, h)
    return {gid: (iso(ts), h) for gid, (ts, h) in primera.items()}


def cierre_pin(bot_dir, inicios):
    """Cierre de Pinnacle de cada juego: la última foto del bot antes del inicio (lineas_log.csv y, si tiene las mismas
    columnas, cierres.csv del escaneo de T−10). inicios: {game_id: datetime UTC} → {game_id: dict}."""
    import polars as pl
    lg = log_bot(bot_dir, con_cierres=True)
    if lg is None or not inicios:
        return {}
    ult = {}
    for f in lg.filter((pl.col("fuente") == "pinnacle") & pl.col("game_id").is_in(list(inicios))).iter_rows(named=True):
        ts, gid = t_utc(f["ts_utc"]), f["game_id"]
        if ts is None or ts > inicios[gid]:
            continue
        if gid not in ult or ts > ult[gid][0]:
            ult[gid] = (ts, f)
    out = {}
    for gid, (ts, f) in ult.items():
        d = dict(ts=iso(ts), min_antes=round((inicios[gid] - ts).total_seconds() / 60))
        for k in ("hcp_local", "cuota_sp_local", "cuota_sp_visit", "ml_local", "ml_visit"):
            d[k] = _num(f.get(k))
        out[gid] = d
    return out


# --------------------------------------------------------------------------------------
# Boleto (informativo) — ajuste 7 de v7. Especificación aprobada por Ozz el 2-oct (claude/ajustes_hoja_pendientes.md):
#   · Lado de cada pata = favorito de Pinnacle sin vig (foto de ≤ 3 h; si no hay, consenso de nflverse, marcado *).
#     El modelo NO elige: solo deja una marca si prefiere el otro lado (H29). ML por omisión (H6/H21).
#   · Tres boletos: (1) solo ML; (2) mixto: en cada juego, ML o spread del mismo favorito, el de menor costo (EV menos
#     negativo) al precio y número de BetOnline; (3) teaser Wong de 6 pts si hay ≥ 3 patas azules (tabla de BetOnline
#     con recargo, premisa 5). Más la tabla de P(cobrar) de 3 a 8 patas (ML, las más probables primero).
#   · Spread y teaser: distribución del margen de la sección 3 (resultados reales 2012-2025 con spread de cierre de
#     nflverse a ≤ 1,5 pts del centro), anclada a la probabilidad sin vig de la línea de referencia.
#   · Parlay: P(cobrar) = Π(p_gana + p_push); EV = Π(p_gana·D + p_push) − 1 (patas independientes, sección 3).
#   · Se arma en las corridas que cuentan (miércoles, sábado, T−85) mientras no empiece el primer juego del domingo;
#     una corrida con menos líneas frescas que el boleto guardado no lo reemplaza. Después de los juegos: EV contra el
#     cierre (última foto de Pinnacle antes del inicio) y resultado. Ningún dinero por el motor (31A).
# --------------------------------------------------------------------------------------
BOLETOS = SAL / "boletos"
TITULO_BOLETO, SID_BOLETO = "Boleto (informativo)", 900
TITULO_BOLETO_PRUEBA, SID_BOLETO_PRUEBA = "Prueba boleto (se borra sola)", 1998
TIPOS_BOLETO = ("miercoles", "sabado", "t85")
NOMBRE_CORRIDA = {"miercoles": "miércoles 10:15", "sabado": "sábado 10:15", "t85": "T−85"}
DIAS_BOLETO = ("Sunday", "Monday")
TEASER_PAGOS = {2: -120, 3: 151, 4: 248, 5: 420, 6: 600, 7: 900, 8: 1300}   # premisa 5: teaser de 6 pts con recargo Wong
PARLAY_PATAS = range(3, 9)                         # tabla de P(cobrar) de 3 a 8 patas
DIST_TEMPORADAS = (2012, 2025)
NUCLEO_PTS, NUCLEO_MIN_N, NUCLEO_MAX_PTS = 1.5, 150, 4.0
NCOL_BOLETO = 14                                   # v8: A rótulo · B en palabras · C separador · D-N detalle técnico
NT_BOLETO = 11                                     # columnas técnicas (D-N)
SEMANAS_TEMPORADA = 18                             # para decir "unas N temporadas"
_MARGENES = {}


def margenes_historicos():
    """(spread de cierre de nflverse, margen real del local) de 2012-2025: la base de la distribución del margen."""
    import polars as pl
    if "x" not in _MARGENES:
        g = pl.read_csv(DATOS / "games.csv", infer_schema_length=20000)
        g = g.filter(pl.col("season").is_between(*DIST_TEMPORADAS) & pl.col("result").is_not_null()
                     & pl.col("spread_line").is_not_null())
        _MARGENES["x"] = (g["spread_line"].cast(pl.Float64).to_numpy(), g["result"].cast(pl.Float64).to_numpy())
    return _MARGENES["x"]


class Margen:
    """Distribución del margen del local para un juego (sección 3): resultados reales de los juegos con spread de cierre
    a ≤ 1,5 pts del centro (se ensancha de 0,5 en 0,5 hasta 4 pts si hay < 150 juegos), anclada a la línea de
    referencia: en ella, P(local cubre) = probabilidad sin vig de la referencia. Las otras líneas (BetOnline, +6 del
    teaser) se mueven con la distribución empírica, que conserva los números clave (3, 7)."""

    def __init__(self, hcp_ref, p_sp_ref=None):
        import numpy as np
        sl, res = margenes_historicos()
        mu = -float(hcp_ref)                            # margen esperado del local según la línea de referencia
        w = NUCLEO_PTS
        while True:
            m = np.abs(sl - mu) <= w + 1e-9
            if m.sum() >= NUCLEO_MIN_N or w >= NUCLEO_MAX_PTS:
                break
            w += 0.5
        if m.sum() < 30:                                # línea extrema: los 150 juegos de spread más cercano
            m = np.zeros(len(sl), dtype=bool)
            m[np.argsort(np.abs(sl - mu), kind="stable")[:NUCLEO_MIN_N]] = True
        self.d, self.n, self.ancho = res[m], int(m.sum()), w
        self.adj = 0.0
        if p_sp_ref is not None:
            self.adj = p_sp_ref * (1 - self.push(hcp_ref)) - self._cubre(hcp_ref)

    def _cubre(self, h):
        return float((self.d + h > 1e-9).mean())

    def push(self, h):
        import numpy as np
        return float((np.abs(self.d + h) < 1e-9).mean())

    def local(self, h):
        """(P gana, P push) del local con hándicap h."""
        q = self.push(h)
        return min(max(self._cubre(h) + self.adj, 0.0), 1.0 - q), q

    def lado(self, es_local, h_lado):
        """(P gana, P push) del lado pedido con su propio hándicap (−3.5 = favorito por 3,5)."""
        if es_local:
            return self.local(h_lado)
        p_l, q = self.local(-h_lado)
        return max(1.0 - p_l - q, 0.0), q


def _dia_et(g):
    w = g.get("weekday")
    if w:
        return str(w)
    return g["inicio"].astimezone(NUEVA_YORK).strftime("%A") if g.get("inicio") else ""


def referencia_juego(g, p):
    """Precios de referencia de un juego: Pinnacle de ≤ 3 h (ML y spread) o, si no hay, el consenso de nflverse."""
    if (p and p.get("ml_local") is not None and p.get("ml_visit") is not None and p.get("hcp_local") is not None
            and sin_vig_potencia(p["ml_local"], p["ml_visit"]) is not None):
        return dict(fuente="pinnacle", ts=p["ts"], horas=p["horas"], ml_local=p["ml_local"], ml_visit=p["ml_visit"],
                    hcp_local=p["hcp_local"], sp_local=p.get("cuota_sp_local"), sp_visit=p.get("cuota_sp_visit"))
    ml_l, ml_v, sl = _num(g.get("home_moneyline")), _num(g.get("away_moneyline")), _num(g.get("spread_line"))
    if ml_l is None or ml_v is None or sl is None or sin_vig_potencia(ml_l, ml_v) is None:
        return None
    return dict(fuente="nflverse", ts=None, horas=None, ml_local=ml_l, ml_visit=ml_v, hcp_local=-sl,
                sp_local=_num(g.get("home_spread_odds")), sp_visit=_num(g.get("away_spread_odds")))


def _frescas(snap):
    """Juegos del boleto con Pinnacle de ≤ 3 h y algún precio de BetOnline de ≤ 12 h."""
    return sum(1 for j in (snap or {}).get("juegos", []) if j["ref"]["fuente"] == "pinnacle" and j.get("bo"))


def ruta_boleto(sem):
    return BOLETOS / f"boleto_semana_{sem}.json"


def leer_boleto(sem):
    try:
        return json.loads(ruta_boleto(sem).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def ultimo_boleto():
    """El boleto guardado de la semana más reciente (el que muestra la pestaña)."""
    sems = []
    for r in BOLETOS.glob("boleto_semana_*.json") if BOLETOS.exists() else []:
        m = re.fullmatch(r"boleto_semana_(\d+)\.json", r.name)
        if m:
            sems.append(int(m.group(1)))
    return leer_boleto(max(sems)) if sems else None


def armar_boleto(g26, sem, bot_dir, ahora, tipo):
    """Arma y guarda la foto del boleto de la semana (solo los datos de entrada: precios y probabilidades se calculan al
    mostrarla, siempre igual). Devuelve la foto nueva, o None si no corresponde o si la guardada tiene más líneas frescas."""
    import polars as pl
    if tipo not in TIPOS_BOLETO or sem is None:
        return None
    jg = [g for g in g26.filter(pl.col("week") == sem).sort(["inicio", "game_id"]).iter_rows(named=True)
          if _dia_et(g) in DIAS_BOLETO and g.get("inicio") is not None]
    if not jg:
        return None
    if ahora >= min(g["inicio"] for g in jg):
        return None                                    # ya empezó el primer juego del domingo: queda congelado
    ids = [g["game_id"] for g in jg]
    pin = lineas_bot(bot_dir, "pinnacle", ids, ahora, MAX_EDAD_PIN_H)
    bo = lineas_bot(bot_dir, "betonlineag", ids, ahora, MAX_EDAD_BO_H)
    ult = ultimas_proyecciones(sem)
    juegos, sin_ref = [], []
    for g in jg:
        gid = g["game_id"]
        ref = referencia_juego(g, pin.get(gid))
        if ref is None:
            sin_ref.append(gid)
            continue
        b = bo.get(gid)
        bo_d = None if not b else {k: b[k] for k in ("ts", "horas", "ml_local", "ml_visit", "hcp_local",
                                                     "cuota_sp_local", "cuota_sp_visit")}
        u = ult.get(gid)
        modelo = None
        if u and u.get("tipo") != "retro" and _num(u.get("p_local")) is not None:
            motivo = "QB dudoso" if es_dudoso(u) else ("filtro" if fuera(u) else "")
            modelo = dict(p_local=_num(u.get("p_local")), fuera=motivo, corrida=u.get("corrida_utc"))
        juegos.append(dict(game_id=gid, inicio_utc=iso(g["inicio"]), local=g["home_team"], visita=g["away_team"],
                           total_nfl=_num(g.get("total_line")), ref=ref, bo=bo_d, modelo=modelo))
    nuevo = dict(version=VERSION_SEMANA, semana=sem, corrida_utc=iso(ahora), tipo=tipo, juegos=juegos, sin_ref=sin_ref)
    previo = leer_boleto(sem)
    if previo and _frescas(nuevo) < _frescas(previo):
        log(f"Boleto semana {sem}: se conserva el de {NOMBRE_CORRIDA.get(previo['tipo'], previo['tipo'])} "
            f"({fecha_cc(t_utc(previo['corrida_utc']))}) "
            f"({_frescas(previo)} juegos con líneas frescas; esta corrida tiene {_frescas(nuevo)})")
        return None
    BOLETOS.mkdir(parents=True, exist_ok=True)
    tmp = ruta_boleto(sem).with_suffix(".tmp")
    tmp.write_text(json.dumps(nuevo, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(ruta_boleto(sem))
    log(f"Boleto semana {sem}: {len(juegos)} juegos ({_frescas(nuevo)} con Pinnacle de ≤ 3 h y BetOnline)")
    return nuevo


def calcular_juego(j, ref=None):
    """Probabilidades, precios de BetOnline y EV de un juego del boleto. ref: otra referencia (el cierre) en lugar de
    la guardada; los precios y números de BetOnline son siempre los de la foto."""
    r = ref or j["ref"]
    b = j.get("bo") or {}
    p_loc = sin_vig_potencia(r["ml_local"], r["ml_visit"])
    p_sp = (sin_vig_potencia(r["sp_local"], r["sp_visit"])
            if r.get("sp_local") is not None and r.get("sp_visit") is not None else None)
    M = Margen(r["hcp_local"], p_sp)
    base = j["ref"]                                    # el lado lo fija la foto, aunque el cierre cambie de favorito
    p_base = sin_vig_potencia(base["ml_local"], base["ml_visit"])
    fav_local = p_base > 0.5 or (abs(p_base - 0.5) < 1e-12 and base["hcp_local"] <= 0)
    c = dict(fav=j["local"] if fav_local else j["visita"], fav_local=fav_local,
             p_fav=p_loc if fav_local else 1 - p_loc, nflverse=r.get("fuente") == "nflverse")
    ml = b.get("ml_local" if fav_local else "ml_visit")
    c["ml"], c["ev_ml"] = ml, (None if ml is None else c["p_fav"] * decimal(ml) - 1)
    hb, cs = b.get("hcp_local"), b.get("cuota_sp_local" if fav_local else "cuota_sp_visit")
    c["h_sp"] = c["cuota_sp"] = c["p_sp"] = c["q_sp"] = c["ev_sp"] = None
    if hb is not None and cs is not None:
        h_fav = hb if fav_local else -hb
        pw, pq = M.lado(fav_local, h_fav)
        c.update(h_sp=h_fav, cuota_sp=cs, p_sp=pw, q_sp=pq, ev_sp=pw * decimal(cs) + pq - 1)
    opciones = [(e, k) for e, k in ((c["ev_ml"], "ML"), (c["ev_sp"], "spread")) if e is not None]
    c["mixto"] = max(opciones)[1] if opciones else None
    c["wong"] = None
    tot = j.get("total_nfl")
    if hb is not None and tot is not None and tot < WONG_TOTAL_MAX:
        es_l, lin = (True, hb) if hb > 0 else (False, -hb)
        if any(abs(lin - w) < 1e-6 for w in WONG_LINEAS):
            pw, pq = M.lado(es_l, lin + 6)
            c["wong"] = dict(eq=j["local"] if es_l else j["visita"], es_local=es_l, lin=lin, p=pw, q=pq)
    return c


def pata_de(c, tipo):
    """(p_gana, p_push, cuota decimal o None si BetOnline no tiene precio) de una pata ML o spread ya calculada."""
    if tipo == "ML":
        return (c["p_fav"], 0.0, None if c["ml"] is None else decimal(c["ml"]))
    return (c["p_sp"], c["q_sp"], decimal(c["cuota_sp"]))


def parlay(patas):
    """P(cobrar), EV y cuota decimal de un parlay de patas independientes [(p_gana, p_push, D)]. Si a alguna pata le
    falta el precio de BetOnline, P(cobrar) se calcula igual y el EV y el pago quedan vacíos."""
    P = R = D = 1.0
    falta = False
    for pg, pq, d in patas:
        P *= pg + pq
        if d is None:
            falta = True
            continue
        R *= pg * d + pq
        D *= d
    return dict(n=len(patas), p=P, ev=None if falta else R - 1, D=None if falta else D)


def teaser(patas):
    """Teaser Wong de 6 pts [(p_gana, p_push)] con la tabla de BetOnline con recargo (premisa 5): un push baja un
    nivel; en 2 patas (o si queda una sola) se devuelve lo apostado."""
    n = len(patas)
    dp = [1.0] + [0.0] * n                             # P(ninguna pierde y k push)
    for pg, pq in patas:
        nuevo = [0.0] * (n + 1)
        for k in range(n + 1):
            if dp[k]:
                nuevo[k] += dp[k] * pg
                if k < n:
                    nuevo[k + 1] += dp[k] * pq
        dp = nuevo
    R = 0.0
    for k, pk in enumerate(dp):
        m = n - k
        R += pk * (1.0 if (n == 2 and k >= 1) or m <= 1 else decimal(TEASER_PAGOS[m]))
    return dict(n=n, p=sum(dp), ev=R - 1, D=decimal(TEASER_PAGOS[n]))


def resultado_lado(margen_local, es_local, h):
    x = (margen_local if es_local else -margen_local) + h
    return "push" if abs(x) < 1e-9 else ("gana" if x > 0 else "pierde")


def americana_txt(D):
    return f"+{(D - 1) * 100:.0f}" if D >= 2 else f"-{100 / (D - 1):.0f}"


def ev_txt(x):
    return "" if x is None else f"{100 * x:+.1f}".replace(".", ",") + " %"


def costo_txt(ev):
    if ev is None:
        return ""
    return f"${-10 * ev:.2f}".replace(".", ",") if ev < 0 else f"gana ${10 * ev:.2f}".replace(".", ",")


def uno_de_txt(p):
    if not p:
        return ""
    x = 1 / p
    return f"1 de cada {x:.1f}".replace(".", ",") if x < 10 else "1 de cada " + f"{round(x):,}".replace(",", ".")


def boleto_calculado(snap, g26, bot_dir, ahora=None):
    """Todo lo que muestra el boleto, calculado a partir de la foto guardada (y, si ya se jugó, del cierre y el resultado).
    El cierre solo existe para los juegos que ya empezaron (inicio ≤ ahora)."""
    import polars as pl
    info = {r["game_id"]: r for r in g26.filter(pl.col("week") == snap["semana"]).iter_rows(named=True)}
    juegos = [j for j in snap["juegos"] if j["game_id"] in info]
    calc = {j["game_id"]: calcular_juego(j) for j in juegos}
    inicios = {j["game_id"]: t_utc(j["inicio_utc"]) for j in juegos}
    empezados = {g: t for g, t in inicios.items() if ahora is not None and t <= ahora}
    ci = cierre_pin(bot_dir, empezados) if bot_dir and empezados else {}
    cierre = {}
    for j in juegos:
        cc = ci.get(j["game_id"])
        if cc and cc["ml_local"] is not None and cc["ml_visit"] is not None and cc["hcp_local"] is not None:
            try:
                cierre[j["game_id"]] = calcular_juego(j, dict(fuente="pinnacle", ml_local=cc["ml_local"], ml_visit=cc["ml_visit"],
                                                              hcp_local=cc["hcp_local"], sp_local=cc["cuota_sp_local"],
                                                              sp_visit=cc["cuota_sp_visit"]))
            except (TypeError, ValueError, ZeroDivisionError):
                pass                                   # una foto de cierre rara no frena el boleto: queda sin EV de cierre
    res = {gid: _num(info[gid].get("result")) for gid in calc}
    return juegos, calc, cierre, res, info


def boletos_de(juegos, calc):
    """Los boletos del resumen: [(nombre, tipo, patas[(gid, clase)], aviso)]; clase = 'ML', 'spread' o 'wong'."""
    todos = [j["game_id"] for j in juegos]
    sin_ml = sum(1 for g in todos if calc[g]["ml"] is None)
    out = [("Solo ML · todos los juegos", "parlay", [(g, "ML") for g in todos], sin_ml),
           ("Mixto · todos (ML o spread, el de menor costo)", "parlay", [(g, calc[g]["mixto"] or "ML") for g in todos],
            sum(1 for g in todos if not calc[g]["mixto"]))]
    orden = sorted(todos, key=lambda g: -calc[g]["p_fav"])
    for k in PARLAY_PATAS:
        if k <= len(orden):
            out.append((f"Parlay ML · las {k} más probables", "parlay", [(g, "ML") for g in orden[:k]],
                        sum(1 for g in orden[:k] if calc[g]["ml"] is None)))
    wong = sorted([g for g in calc if calc[g]["wong"]], key=lambda g: -calc[g]["wong"]["p"])
    if len(wong) >= 3:
        for k in range(3, min(len(wong), max(TEASER_PAGOS)) + 1):
            out.append((f"Teaser Wong 6 pts · {k} patas", "teaser", [(g, "wong") for g in wong[:k]], 0))
    else:
        out.append(("Teaser Wong 6 pts", "sin_wong", [(g, "wong") for g in wong], 0))
    return out


def medir_boleto(tipo, patas, calc):
    if tipo == "teaser":
        return teaser([(calc[g]["wong"]["p"], calc[g]["wong"]["q"]) for g, _ in patas])
    return parlay([pata_de(calc[g], c) for g, c in patas])


def resultado_boleto(tipo, patas, calc, res):
    """Texto del resultado cuando ya se jugaron todos los juegos del boleto."""
    if not patas or any(res.get(g) is None for g, _ in patas):
        hechos = sum(1 for g, _ in patas if res.get(g) is not None)
        return f"pendiente ({hechos} de {len(patas)} jugados)" if hechos else ""
    r = []
    for g, c in patas:
        x = calc[g]
        if c == "ML":
            r.append(resultado_lado(res[g], x["fav_local"], 0.0))
        elif c == "spread":
            r.append(resultado_lado(res[g], x["fav_local"], x["h_sp"]))
        else:
            r.append(resultado_lado(res[g], x["wong"]["es_local"], x["wong"]["lin"] + 6))
    gan, psh = r.count("gana"), r.count("push")
    if tipo == "teaser":
        esp = sum(calc[g]["wong"]["p"] for g, _ in patas)
    else:
        esp = sum(pata_de(calc[g], c)[0] for g, c in patas)
    estado = "perdió" if "pierde" in r else ("devuelto (todo push)" if gan == 0 else "cobró")
    return f"{estado} · acertó {gan} de {len(patas)}" + (f" ({psh} push)" if psh else "") + \
        f" · esperado {esp:.1f}".replace(".", ",")


def dinero_txt(x, decimales=0):
    return "$" + (f"{x:,.0f}".replace(",", ".") if decimales == 0 else f"{x:.{decimales}f}".replace(".", ","))


def frecuencia_txt(p):
    """0.575 → 'pasa 6 de cada 10 semanas'; 0.0018 → 'pasa 1 de cada 556 semanas (unas 31 temporadas)'."""
    if not p:
        return "no pasa nunca"
    if p >= 0.1:
        return f"pasa {min(10, int(p * 10 + 0.5))} de cada 10 semanas"
    x = 1 / p
    txt = f"pasa 1 de cada {round(x):,} semanas".replace(",", ".")
    return txt + (f" (unas {x / SEMANAS_TEMPORADA:.0f} temporadas)" if x >= 2 * SEMANAS_TEMPORADA else "")


def frase_boleto(tipo, patas, m, res_txt):
    """Una frase por boleto: cuánto cobras por $10, cada cuánto pasa y cuánto pierdes (o ganas) en promedio."""
    n = len(patas)
    partes = []
    if m["D"] is None:
        partes.append("no se sabe cuánto paga (falta el precio de BetOnline de algún partido)")
    else:
        quien = "los" if n > 1 else "el"
        partes.append(f"Cobras {dinero_txt(10 * m['D'])} si {'aciertan' if tipo == 'teaser' else 'aciertas'} {quien} {n}")
    partes.append(frecuencia_txt(m["p"]))
    if m["ev"] is not None:
        partes.append(f"en promedio {'pierdes' if m['ev'] < 0 else 'ganas'} {dinero_txt(abs(10 * m['ev']), 2)} de cada $10")
    txt = " · ".join(partes)
    txt = txt[0].upper() + txt[1:]
    if tipo == "teaser":
        txt += " ← lo único con ventaja medida: con poquito dinero"
    return txt + (f". {res_txt}" if res_txt else "")


def resultado_boleto_simple(tipo, patas, calc, res):
    if not patas:
        return ""
    hechos = sum(1 for g, _ in patas if res.get(g) is not None)
    if hechos < len(patas):
        return f"Van {hechos} de {len(patas)} partidos jugados." if hechos else ""
    r = []
    for g, c in patas:
        x = calc[g]
        if c == "ML":
            r.append(resultado_lado(res[g], x["fav_local"], 0.0))
        elif c == "spread":
            r.append(resultado_lado(res[g], x["fav_local"], x["h_sp"]))
        else:
            r.append(resultado_lado(res[g], x["wong"]["es_local"], x["wong"]["lin"] + 6))
    gan = r.count("gana")
    esp = sum((calc[g]["wong"]["p"] if tipo == "teaser" else pata_de(calc[g], c)[0]) for g, c in patas)
    if "pierde" in r:
        return f"Resultado: perdió ✘ (acertó {gan} de {len(patas)}; se esperaban {_dec(esp)})."
    return "Resultado: se devolvió la plata (todo empate con la línea)." if gan == 0 else f"Resultado: cobró ✔ (acertó {gan} de {len(patas)})."


def nombre_boleto(tipo, nombre_b, patas, calc, juegos):
    n = len(patas)
    if nombre_b.startswith("Solo ML"):
        return f"Los {n} favoritos juntos (a ganador)"
    if nombre_b.startswith("Mixto"):
        return f"Los {n} favoritos juntos (a ganador o con línea, lo más barato)"
    if tipo == "parlay":
        return f"Los {n} más seguros juntos: " + ", ".join(apodo(calc[g]["fav"]) for g, _ in patas)
    if tipo == "teaser":
        return f"Teaser de {n} perros con 6 puntos extra: " + ", ".join(apodo(calc[g]["wong"]["eq"]) for g, _ in patas)
    return "Teaser de perros (6 puntos extra)"


def grilla_boleto(snap, g26, bot_dir, ahora=None):
    """Filas de la pestaña (NCOL_BOLETO columnas: A rótulo, B en palabras, C vacía, D-N técnico) y qué filas llevan
    formato: {'encab': [...], 'azul': [...]}."""
    def fila(a="", b="", *tec):
        tec = ["" if x is None else x for x in tec]
        return [a, b, ""] + tec + [""] * (NT_BOLETO - len(tec))
    base = ("Esto es para jugar por diversión, con poquito dinero. Juntar muchos partidos casi nunca paga: los favoritos "
            "de toda la semana juntos salen más o menos 1 de cada 300 semanas y te cuestan un tercio de lo que apuestas. "
            "Lo único que ha mostrado ventaja es el teaser de perros (6 puntos extra), y aun así con poquito dinero. La "
            "máquina no elige nada aquí: los equipos los ponen las apuestas.")
    base_tec = ("Ningún dinero por el motor (31A). El lado de cada pata lo pone el mercado (favorito de Pinnacle sin vig); "
                "el modelo no elige (H29: el cierre le gana por 0,4 pts) y solo deja una marca. Los parlays son decisión de "
                "Ozz, por diversión: el de todos los favoritos cobra ~1 de cada 300 y cuesta ~33 % de lo apostado (H25). El "
                "teaser Wong es lo único con valor medido (H28): monto mínimo, preferir 4 patas; el pago exacto de 3 y 4 "
                "patas con recargo se confirma en el boleto de BetOnline.")
    meta = {"encab": [], "azul": []}
    if not snap:
        filas = [fila("Boleto", "Todavía no hay boleto: se arma solo el miércoles o el sábado a las 10:15, o 85 minutos "
                      "antes de un partido, con los partidos del domingo y el lunes."), fila("Antes de apostar", base, base_tec)]
        return filas, meta
    juegos, calc, cierre, res, info = boleto_calculado(snap, g26, bot_dir, ahora)
    hay_nfl = any(calc[j["game_id"]]["nflverse"] for j in juegos)
    nombre = NOMBRE_CORRIDA.get(snap["tipo"], snap["tipo"])
    corrida = t_utc(snap["corrida_utc"])
    detalle = (f"Armado el {cuando_txt(corrida)} (hora de Caracas) con los precios de BetOnline de esa hora. Se congela "
               "cuando empieza el primer partido del domingo; después de los partidos dice qué pasó."
               + (" * = esa semana no había línea fresca de Pinnacle: se usó el consenso." if hay_nfl else ""))
    detalle_tec = (f"Detalle técnico · corrida {nombre} ({fecha_cc(corrida)}, Caracas) con las fotos del bot. Probabilidad: "
                   f"Pinnacle sin vig (≤ 3 h)" + ("; * = sin Pinnacle de ≤ 3 h: consenso de nflverse" if hay_nfl else "")
                   + ". Precio: BetOnline (≤ 12 h). EV vs cierre: los mismos precios contra la última foto de Pinnacle "
                   "antes de cada juego.")
    filas = [fila(f"Boleto · Semana {snap['semana']}", detalle, detalle_tec), fila("Antes de apostar", base, base_tec), fila()]
    meta["encab"].append(len(filas))
    filas.append(fila("Si apuestas $10 a…", "Qué pasa", "Patas", "Pago", "P(cobrar)", "1 de cada", "EV (corrida)",
                      "Costo por $10", "EV vs cierre", "Resultado"))
    for nombre_b, tipo, patas, sin_precio in boletos_de(juegos, calc):
        if tipo == "sin_wong":
            filas.append(fila(nombre_boleto(tipo, nombre_b, patas, calc, juegos),
                              f"Esta semana hay {len(patas)} perro{'s' if len(patas) != 1 else ''} que sirve"
                              f"{'n' if len(patas) != 1 else ''} y hacen falta 3: no hay teaser.",
                              str(len(patas)), f"hay {len(patas)} patas azules: hacen falta 3"))
            meta["azul"].append(len(filas) - 1)
            continue
        if not patas:
            continue
        m = medir_boleto(tipo, patas, calc)
        evc = ""
        if all(g in cierre for g, _ in patas):
            try:
                evc = ev_txt(medir_boleto(tipo, patas, {g: cierre[g] for g, _ in patas})["ev"])
            except (TypeError, KeyError):
                evc = ""
        pago = "" if m["D"] is None else americana_txt(m["D"]) + (" (aprox.)" if tipo == "teaser" and m["n"] in (3, 4) else "")
        filas.append(fila(nombre_boleto(tipo, nombre_b, patas, calc, juegos),
                          frase_boleto(tipo, patas, m, resultado_boleto_simple(tipo, patas, calc, res)),
                          f"{m['n']}" + (f" ({sin_precio} sin precio)" if sin_precio else ""), pago,
                          pct(m["p"], 2 if m["p"] < 0.1 else 1), uno_de_txt(m["p"]), ev_txt(m["ev"]), costo_txt(m["ev"]),
                          evc, resultado_boleto(tipo, patas, calc, res)))
        if tipo == "teaser":
            meta["azul"].append(len(filas) - 1)
    filas.append(fila())
    meta["encab"].append(len(filas))
    filas.append(fila("Partido", "En palabras", "Lado (favorito)", "Gana (Pinnacle)", "ML BetOnline", "EV ML", "Spread BetOnline",
                      "Cubre (Pinnacle)", "EV spread", "Mixto usa", "Modelo (solo marca)", "Pata Wong +6", "Resultado"))
    for j in juegos:
        gid, c, g = j["game_id"], calc[j["game_id"]], info[j["game_id"]]
        b = j.get("bo") or {}
        edad = _num(b.get("horas"))
        edad_t = "" if edad is None else (f" (hace {edad:.0f} h)" if edad >= 1 else f" (hace {60 * edad:.0f} min)")
        ml = "sin precio" if c["ml"] is None else f"{c['ml']:+.0f}" + edad_t
        sp = "sin precio" if c["h_sp"] is None else f"{c['fav']} {c['h_sp']:+.1f} ({c['cuota_sp']:+.0f})"
        cubre = "" if c["p_sp"] is None else pct(c["p_sp"], 1) + (f" · push {pct(c['q_sp'], 1)}" if c["q_sp"] >= 0.005 else "")
        mo = j.get("modelo")
        if not mo:
            marca = ""
        elif mo.get("fuera"):
            marca = f"fuera ({mo['fuera']})"
        else:
            pm = mo["p_local"] if c["fav_local"] else 1 - mo["p_local"]
            otro = j["visita"] if c["fav_local"] else j["local"]
            marca = f"de acuerdo · {pct(pm)}" if pm >= 0.5 else f"prefiere {otro} · {pct(1 - pm)}"
        w = c["wong"]
        wong = "" if not w else f"{w['eq']} +{w['lin'] + 6:.1f} · {pct(w['p'], 1)}"
        r = res.get(gid)
        resultado = ""
        k = min(10, max(0, int(c["p_fav"] * 10 + 0.5)))
        frase = f"Favorito: {apodo(c['fav'])}{'*' if c['nflverse'] else ''} · gana {k} de cada 10"
        if w:
            frase += f" · para el teaser sirve {apodo(w['eq'])} +{w['lin'] + 6:.1f}"
        if r is not None:
            partes = [resultado_txt(g), "ML " + {"gana": "ganó", "pierde": "perdió", "push": "empate"}[resultado_lado(r, c["fav_local"], 0.0)]]
            if c["h_sp"] is not None:
                partes.append("spread " + {"gana": "cubrió", "pierde": "no cubrió", "push": "push"}[resultado_lado(r, c["fav_local"], c["h_sp"])])
            if w:
                partes.append("Wong " + {"gana": "cubrió", "pierde": "no cubrió", "push": "push"}[resultado_lado(r, w["es_local"], w["lin"] + 6)])
            resultado = " · ".join(partes)
            hs, as_ = int(g["home_score"]), int(g["away_score"])
            if r == 0:
                frase += f". Empate {hs}-{as_} (a ganador se devuelve)"
            else:
                gan = g["home_team"] if r > 0 else g["away_team"]
                frase += f". Ganó {apodo(gan)} {max(hs, as_)}-{min(hs, as_)} " + ("✔" if gan == c["fav"] else "✘")
            if w:
                frase += " · teaser " + {"gana": "✔", "pierde": "✘", "push": "empate"}[resultado_lado(r, w["es_local"], w["lin"] + 6)]
        neutral = j.get("local") and g.get("location") == "Neutral"
        partido = (f"{apodo(j['visita'])} vs {apodo(j['local'])} (cancha neutral)" if neutral
                   else f"{apodo(j['visita'])} visitan a {apodo(j['local'])}")
        filas.append(fila(f"{partido} · {cuando_txt(t_utc(j['inicio_utc']))}", frase,
                          c["fav"] + ("*" if c["nflverse"] else ""), pct(c["p_fav"], 1), ml, ev_txt(c["ev_ml"]), sp, cubre,
                          ev_txt(c["ev_sp"]), c["mixto"] or "", marca, wong, resultado))
        if w:
            meta["azul"].append(len(filas) - 1)
    for gid in snap.get("sin_ref", []):
        g = info.get(gid)
        if g:
            filas.append(fila(f"{apodo(g['away_team'])} visitan a {apodo(g['home_team'])}", "Todavía no hay apuestas para este partido.",
                              "sin líneas"))
    filas.append(fila())
    filas.append(fila("Para entender",
                      "«En promedio pierdes $3,81 de cada $10» quiere decir que si jugaras ese boleto muchas semanas, perderías "
                      "unos $3,81 cada vez. «Pasa 1 de cada 556 semanas» quiere decir que cobrarías más o menos una vez en 556 "
                      "semanas; una temporada tiene unas 18. «Gana 7 de cada 10» quiere decir que si el partido se jugara 10 "
                      "veces, ese equipo ganaría unas 7. En azul: el teaser de perros y los perros que sirven para él.",
                      "EV = ganancia esperada por cada $1 contra Pinnacle sin vig (negativo = costo). Costo por $10 = lo que "
                      "se pierde en promedio por cada $10. P(cobrar) supone patas independientes. Spread y teaser: "
                      "distribución del margen 2012-2025 (juegos con spread a ≤ 1,5 pts) anclada a la línea de referencia. "
                      "Teaser: tabla de BetOnline con recargo Wong (2 −120, 3 +151, 4 +248, 5 +420, 6 +600); un push baja "
                      "un nivel. Pata Wong = underdog +1,5 a +2,5 con total < 50."))
    return filas, meta


def grilla_boleto_prueba():
    """Boleto de muestra con todas las clases de fila (para 'hoja-prueba'; no sale de datos reales)."""
    def fila(a="", b="", *tec):
        return [a, b, ""] + list(tec) + [""] * (NT_BOLETO - len(tec))
    filas = [fila("Boleto · PRUEBA", "detalle en palabras", "detalle técnico"), fila("Antes de apostar", "advertencias", "base"),
             fila(),
             fila("Si apuestas $10 a…", "Qué pasa", "Patas", "Pago", "P(cobrar)", "1 de cada", "EV (corrida)", "Costo por $10",
                  "EV vs cierre", "Resultado"),
             fila("Los 15 favoritos juntos (a ganador)", "Cobras $3.439 si aciertas los 15 · pasa 1 de cada 556 semanas",
                  "15", "+34294", "0,18 %", "1 de cada 556", "-38,1 %", "$3,81", "", ""),
             fila("Teaser de 3 perros con 6 puntos extra: Giants, Broncos, Falcons", "Cobras $25 si aciertan los 3",
                  "3", "+151 (aprox.)", "43,8 %", "1 de cada 2,3", "+10,1 %", "gana $1,01", "", ""),
             fila(),
             fila("Partido", "En palabras", "Lado (favorito)", "Gana (Pinnacle)", "ML BetOnline", "EV ML", "Spread BetOnline",
                  "Cubre (Pinnacle)", "EV spread", "Mixto usa", "Modelo (solo marca)", "Pata Wong +6", "Resultado"),
             fila("Pruebas visitan a Ensayos · Dom 4 oct · 1:00 pm", "Favorito: Ensayos · gana 7 de cada 10", "EBA", "75,0 %",
                  "-320", "-1,6 %", "EBA -2.5 (-110)", "51,0 %", "-2,6 %", "ML", "de acuerdo · 70 %", "PRU +8.5 · 74,0 %", ""),
             fila(), fila("Para entender", "notas en palabras", "notas técnicas")]
    return filas, {"encab": [3, 7], "azul": [5, 8]}


def crear_boleto(hoja, filas, meta, titulo=TITULO_BOLETO, sid=SID_BOLETO):
    """(Re)crea la pestaña del boleto, primera a la izquierda, con su formato, y escribe las filas. v8: A inmovilizada,
    B en palabras (ancha), C separador, D-N detalle técnico chico y gris."""
    ps = hoja.pestanas()
    viejas = [i for nombre, i in ps.items() if nombre == titulo]       # solo la pestaña del boleto, por su nombre
    if viejas:
        hoja.lote([{"deleteSheet": {"sheetId": i}} for i in viejas])
    otras = {i for nombre, i in ps.items() if nombre != titulo}
    while sid in otras:                                                # nunca toca otra pestaña que use ese número
        sid += 1
    n = len(filas) + 2
    D = 3                                                              # primera columna técnica
    fondo = lambda f0, f1, c0, c1, color: {"repeatCell": {"range": _rango(sid, f0, f1, c0, c1), "cell": {"userEnteredFormat": {  # noqa: E731
        "backgroundColorStyle": {"rgbColor": _rgb(color)}}}, "fields": "userEnteredFormat.backgroundColorStyle"}}
    ancho = lambda c0, c1, px: {"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": c0,  # noqa: E731
                                                                        "endIndex": c1}, "properties": {"pixelSize": px}, "fields": "pixelSize"}}
    alto = lambda f0, f1, px: {"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "ROWS", "startIndex": f0,  # noqa: E731
                                                                       "endIndex": f1}, "properties": {"pixelSize": px}, "fields": "pixelSize"}}
    texto = lambda f0, f1, c0, c1, fmt, campos: {"repeatCell": {"range": _rango(sid, f0, f1, c0, c1), "cell": {"userEnteredFormat": fmt},  # noqa: E731
                                                                "fields": campos}}
    combinar = lambda f, c0, c1: {"mergeCells": {"range": _rango(sid, f, f + 1, c0, c1), "mergeType": "MERGE_ALL"}}  # noqa: E731
    ajuste = "userEnteredFormat.wrapStrategy,userEnteredFormat.verticalAlignment"
    pedidos = [
        {"addSheet": {"properties": {"sheetId": sid, "title": titulo, "index": 0,
                                     "gridProperties": {"rowCount": n, "columnCount": NCOL_BOLETO, "frozenColumnCount": 1}}}},
        # filas 1 y 2: A rótulo | B en palabras | D-N técnico combinado (nada cruza el borde de la columna A)
        combinar(0, D, NCOL_BOLETO), combinar(1, D, NCOL_BOLETO),
        texto(0, 2, 0, 1, {"textFormat": {"bold": True}}, "userEnteredFormat.textFormat"),
        texto(0, n, 0, 2, {"wrapStrategy": "WRAP", "verticalAlignment": "MIDDLE"}, ajuste),
        texto(0, 2, D, NCOL_BOLETO, {"wrapStrategy": "WRAP", "verticalAlignment": "MIDDLE"}, ajuste),
        texto(0, n, D, NCOL_BOLETO, {"textFormat": {"fontSize": 8, "foregroundColorStyle": {"rgbColor": _rgb(COLORES["gris"])}}},
              "userEnteredFormat.textFormat"),
        fondo(1, 2, 0, 2, COLORES["resumen"]),
        alto(0, 1, 56), alto(1, 2, 96),
        ancho(0, 1, 250), ancho(1, 2, 430), ancho(2, 3, 25),
        ancho(3, 4, 105), ancho(4, 5, 150), ancho(5, 6, 120), ancho(6, 7, 105), ancho(7, 8, 140), ancho(8, 9, 135),
        ancho(9, 10, 110), ancho(10, 11, 240), ancho(11, 12, 170), ancho(12, 13, 160), ancho(13, 14, 300),
    ]
    for f in meta.get("azul", []):
        pedidos.append(fondo(f, f + 1, 0, 2, COLORES["azul"]))
    for f in meta.get("encab", []):
        for c0, c1, color in ((0, 2, COLORES["encab"]), (D, NCOL_BOLETO, COLORES["encab_tec"])):
            pedidos.append(texto(f, f + 1, c0, c1, {
                "textFormat": {"bold": True, "fontSize": 10, "foregroundColorStyle": {"rgbColor": _rgb(COLORES["blanco"])}},
                "backgroundColorStyle": {"rgbColor": _rgb(color)}, "wrapStrategy": "WRAP", "verticalAlignment": "MIDDLE"},
                "userEnteredFormat.textFormat,userEnteredFormat.backgroundColorStyle,userEnteredFormat.wrapStrategy,"
                "userEnteredFormat.verticalAlignment"))
    if filas and filas[-1][0] == "Para entender":       # la fila de notas: técnico combinado, alto para leer completo
        f = len(filas) - 1
        pedidos += [combinar(f, D, NCOL_BOLETO), texto(f, f + 1, 0, 1, {"textFormat": {"bold": True}}, "userEnteredFormat.textFormat"),
                    texto(f, f + 1, D, NCOL_BOLETO, {"wrapStrategy": "WRAP", "verticalAlignment": "MIDDLE"}, ajuste),
                    alto(f, f + 1, 110)]
    hoja.lote(pedidos)
    hoja.escribir(f"'{titulo}'!A1:{chr(64 + NCOL_BOLETO)}{len(filas)}", filas)
    return sid


def actualizar_boleto(hoja, g26, bot_dir, ahora):
    """Pestaña 'Boleto (informativo)' con el boleto guardado más reciente (o el aviso de que todavía no hay)."""
    if hoja is None:
        return
    filas, meta = grilla_boleto(ultimo_boleto(), g26, bot_dir, ahora)
    crear_boleto(hoja, filas, meta)


def texto_boleto(snap, g26):
    """Una línea para Telegram con lo esencial del boleto recién armado."""
    if not snap:
        return ""
    juegos, calc, _, _, _ = boleto_calculado(snap, g26, None)
    partes = []
    for nombre_b, tipo, patas, _sp in boletos_de(juegos, calc):
        if nombre_b.startswith("Solo ML") or nombre_b.startswith("Mixto") or (tipo == "teaser" and len(patas) in (3, 4)):
            if patas:
                m = medir_boleto(tipo, patas, calc)
                corto = "teaser Wong" if tipo == "teaser" else ("solo ML" if nombre_b.startswith("Solo ML") else "mixto")
                partes.append(f"{corto} {m['n']} patas: P(cobrar) {pct(m['p'], 2 if m['p'] < 0.1 else 1)} "
                              f"({uno_de_txt(m['p'])}), " + (f"EV {ev_txt(m['ev'])}" if m["ev"] is not None
                                                             else "sin precio de BetOnline en alguna pata"))
        elif tipo == "sin_wong":
            partes.append(f"teaser Wong: {len(patas)} patas azules (hacen falta 3)")
    return ("🎫 Boleto semana " + str(snap["semana"]) + " (informativo, ningún dinero por el motor): " + " · ".join(partes)
            + ". Detalle en la pestaña Boleto.")


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
    """Aciertos de cada fuente contra el QB que jugó, con el voto de la corrida que cuenta (la última antes del inicio entre
    T−85, sábado y miércoles; si no hubo, la última). {fuente: (aciertos, total)}. v8.1 (43): el QB que jugó es el del
    primer dropback de la jugada por jugada de nflverse (verdad_qb); si ese juego todavía no está en la jugada por jugada,
    el QB de games.csv como verdad provisional (la clave '_provisional' cuenta cuántos equipo-juego la usaron)."""
    import polars as pl
    if not FUENTES_QB.exists():
        return {}
    reg = pl.read_csv(FUENTES_QB, infer_schema_length=0)
    if semana is not None:
        reg = reg.filter(pl.col("semana") == str(semana))
    hechos = g26.filter(pl.col("result").is_not_null())
    verdad = verdad_qb()
    ro = leer_roster()
    nombre_ro = dict(zip(ro["gsis_id"].to_list(), ro["full_name"].to_list())) if ro is not None else {}
    real, real_nom, inicio, provisional = {}, {}, {}, set()
    for r in hechos.iter_rows(named=True):
        for eq, qid, qnom in ((r["home_team"], _texto(r.get("home_qb_id")), r.get("home_qb_name")),
                              (r["away_team"], _texto(r.get("away_qb_id")), r.get("away_qb_name"))):
            k = (r["game_id"], eq)
            if k in verdad:
                real[k] = verdad[k]
                real_nom[k] = _norm(nombre_ro.get(verdad[k]) or (qnom if verdad[k] == qid else ""))
            else:
                real[k], real_nom[k] = qid, _norm(qnom)
                provisional.add(k)
        inicio[r["game_id"]] = r["inicio"]
    elegido = {}                                       # (game, equipo, fuente) → (prioridad, (qb_id, nombre))
    for f in reg.iter_rows(named=True):
        k = (f["game_id"], f["equipo"])
        if k not in real or not real[k]:
            continue
        t = t_utc(f["corrida_utc"])
        if t is None or (inicio.get(f["game_id"]) and t >= inicio[f["game_id"]]):
            continue
        fuente = f["fuente"]
        if fuente == "gemini":                         # v6: solo sus votos T−85, separados por versión (g0 = v5)
            if f["tipo"] != "t85":
                continue
            m = re.match(r"^(g\d[\w-]*) ·", _texto(f.get("nota")))
            fuente = "gemini " + (m.group(1) if m else "g0")
        prio = (1 if f["tipo"] in TIPOS_QUE_CUENTAN else 0, t)
        kk = (f["game_id"], f["equipo"], fuente)
        if kk not in elegido or prio > elegido[kk][0]:
            elegido[kk] = (prio, (_texto(f["qb_id"]), _norm(f.get("qb_nombre"))))
    out = {}
    for (gid, eq, fuente), (_, (qb, nom)) in elegido.items():
        acierto = (qb == real[(gid, eq)]) if qb else bool(nom and nom == real_nom.get((gid, eq)))
        a, n = out.get(fuente, (0, 0))
        out[fuente] = (a + int(acierto), n + 1)
    usados = {(gid, eq) for (gid, eq, _f) in elegido} & provisional
    if out and usados:
        out["_provisional"] = len(usados)
    return out


def confiabilidad_txt(c):
    prov = (c or {}).get("_provisional")
    c = {k: v for k, v in (c or {}).items() if not k.startswith("_")}
    if not c:
        return ""
    orden = ["consenso", "nflverse", "espn", "sleeper"] + sorted(f for f in c if f.startswith("gemini"))
    nombres = {"consenso": "consenso", "nflverse": "nflverse", "espn": "ESPN", "sleeper": "Sleeper"}
    nombres.update({f: f"Gemini {f.split(' ', 1)[1]} (sombra)" for f in c if f.startswith("gemini ")})
    return ("QB acertado por fuente (contra el primer dropback): " + " · ".join(f"{nombres.get(f, f)} {c[f][0]}/{c[f][1]}" for f in orden if f in c)
            + (f" · verdad provisional (games.csv) en {prov} equipo-juego sin jugada por jugada todavía" if prov else ""))


# --------------------------------------------------------------------------------------
# Agente Gemini en sombra (35A) — configuración g1 (decisiones de Ozz del 2-oct-2026, registradas antes de su
# primera consulta en claude/registro_35A_g1.md y en el contexto del proyecto). Nunca vota en el consenso.
#   · Modelo fijo en el código (semana.ini ya no lo elige); vía única generateContent; razonamiento medium;
#     sin temperature/top_p/top_k (obsoletos e ignorados en 3.5 Flash-Lite); búsqueda de Google; salida con esquema.
#   · Una consulta por juego, hasta 8 a la vez; 90 s en total para toda la tanda; sin reintentos.
#   · Corre SOLO en las corridas T−85 y DESPUÉS de guardar y enviar la proyección (no puede retrasarla).
#   · Cada llamada se registra en salidas/semana/gemini_llamadas.csv (latencia, tokens, búsquedas, costo, estado).
#   · Cada equipo pedido deja un voto en fuentes_qb.csv (fuente "gemini"); sin respuesta → voto vacío, que cuenta
#     como no acierto (decisión 5: misma regla que las abstenciones de nflverse, ESPN y Sleeper).
#   · Variantes predefinidas para el piloto (g1-low, g1-texto, g1-high): cada una tiene su etiqueta y su huella;
#     cualquier cambio de configuración es una versión nueva y reinicia el reloj del piso (decisión 6).
# --------------------------------------------------------------------------------------
GEMINI_LLAVE = BASE / "credenciales" / "gemini.key"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta"
GEMINI_MODELO = "gemini-3.5-flash-lite"            # D1: fijo y versionado
GEMINI_MAX_DIA = 20                                # tope de consultas por día (corridas T−85); semana.ini puede bajarlo o subirlo
GEMINI_MAX_PRUEBA_DIA = 40                         # tope aparte para el piloto (alcanza para probar una variante más el mismo día)
GEMINI_PLAZO_S = 90                                # 35A: 90 s en total para la tanda
GEMINI_HILOS = 8                                   # D3
GEMINI_MAX_TOKENS = 16384                          # techo de costo (incluye el razonamiento)
GEMINI_MIME = "APPLICATION_JSON"                   # v6.1: enum de generateContent (TextResponseFormat.MimeType)
PRECIO_ENTRADA, PRECIO_SALIDA = 0.30e-6, 2.50e-6   # USD por token, gemini-3.5-flash-lite (el razonamiento se cobra como salida)
PRECIO_BUSQUEDA = 0.014                            # USD por búsqueda, solo después de las 5.000 gratis al mes (se reporta aparte)
GEMINI_LLAMADAS = SAL / "gemini_llamadas.csv"
CAMPOS_GEM = ["corrida_utc", "tipo", "agente", "huella", "modelo", "model_version", "game_id", "semana", "visita", "local",
              "estado", "http", "latencia_s", "tok_entrada", "tok_herramienta", "tok_salida", "tok_razonamiento",
              "busquedas", "consultas_busqueda", "dominios", "evidencia_busqueda", "costo_usd", "qb_visita", "conf_visita", "url_visita",
              "fecha_visita", "url_visita_verificada", "qb_local", "conf_local", "url_local", "fecha_local",
              "url_local_verificada", "fin", "detalle"]
EQUIPOS = {"ARI": "Arizona Cardinals", "ATL": "Atlanta Falcons", "BAL": "Baltimore Ravens", "BUF": "Buffalo Bills",
           "CAR": "Carolina Panthers", "CHI": "Chicago Bears", "CIN": "Cincinnati Bengals", "CLE": "Cleveland Browns",
           "DAL": "Dallas Cowboys", "DEN": "Denver Broncos", "DET": "Detroit Lions", "GB": "Green Bay Packers",
           "HOU": "Houston Texans", "IND": "Indianapolis Colts", "JAX": "Jacksonville Jaguars", "KC": "Kansas City Chiefs",
           "LA": "Los Angeles Rams", "LAC": "Los Angeles Chargers", "LV": "Las Vegas Raiders", "MIA": "Miami Dolphins",
           "MIN": "Minnesota Vikings", "NE": "New England Patriots", "NO": "New Orleans Saints", "NYG": "New York Giants",
           "NYJ": "New York Jets", "PHI": "Philadelphia Eagles", "PIT": "Pittsburgh Steelers", "SEA": "Seattle Seahawks",
           "SF": "San Francisco 49ers", "TB": "Tampa Bay Buccaneers", "TEN": "Tennessee Titans", "WAS": "Washington Commanders"}
RONDAS = {"WC": "wild-card round", "DIV": "divisional round", "CON": "conference championship", "SB": "Super Bowl"}
GEMINI_SISTEMA = """You identify NFL starting quarterbacks using Google Search. Rules:
1. Always search before answering. Your training data is out of date.
2. Prefer reports from the last 72 hours; ignore anything older than 7 days.
   Priority: official inactive list (released ~90 min before kickoff), team
   announcements, NFL.com, ESPN, team beat reporters.
3. "Starting quarterback" = the player expected to take the team's first offensive snap.
4. Return exactly one entry per requested team, using the team codes given.
5. source_url must be a page that appeared in your search results. Never build or guess a URL.
6. If reports conflict or are stale, still give your best answer and set confidence to "low"."""
GEMINI_USUARIO = """Now: {ahora_utc} UTC ({ahora_et} ET). NFL {temporada} {fase}.
Game: {visita_nombre} ({visita}) at {local_nombre} ({local}), kickoff {inicio_utc} UTC.
Who is the starting quarterback for {visita} and for {local}?"""
GEMINI_TEXTO_JSON = ("\nAnswer ONLY with a JSON object of this form and nothing else: "
                     '{{"teams": [{{"team": "{visita}", "qb": "Full Name", "confidence": "high|medium|low", '
                     '"source_url": "https://...", "source_date": "YYYY-MM-DD"}}, {{"team": "{local}", ...}}]}}')
GEMINI_VARIANTES = {                               # g1 = la decidida; las otras solo existen como salida prevista del piloto
    "g1": {"nivel": "medium", "esquema": True},
    "g1-low": {"nivel": "low", "esquema": True},       # si fallan P3 o P4
    "g1-texto": {"nivel": "medium", "esquema": False}, # si la API rechaza esquema + búsqueda
    "g1-high": {"nivel": "high", "esquema": True},     # si falla P2 (se prueba una sola vez)
}
CONFIANZAS = ("high", "medium", "low")
PREFIJO_BUSQUEDA = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/"   # enlaces que solo crea la búsqueda de Google


def gemini_esquema(visita, local):
    return {"type": "object",
            "properties": {"teams": {"type": "array", "minItems": 2, "maxItems": 2, "items": {
                "type": "object",
                "properties": {
                    "team": {"type": "string", "enum": [visita, local]},
                    "qb": {"type": "string", "description": "Full name of the expected starting quarterback."},
                    "confidence": {"type": "string", "enum": list(CONFIANZAS)},
                    "source_url": {"type": "string", "description": "URL of a page that appeared in your search results."},
                    "source_date": {"type": "string", "format": "date", "description": "Publication date of that source (YYYY-MM-DD)."}},
                "required": ["team", "qb", "confidence", "source_url", "source_date"]}}},
            "required": ["teams"]}


def gemini_huella(variante):
    """Huella de la configuración completa (todo lo que se envía y cómo se lee). Cambia → versión nueva."""
    v = GEMINI_VARIANTES[variante]
    cfg = dict(modelo=GEMINI_MODELO, via="generateContent", variante=variante, nivel=v["nivel"], esquema=v["esquema"],
               mime=GEMINI_MIME if v["esquema"] else "",
               sistema=GEMINI_SISTEMA, usuario=GEMINI_USUARIO, texto_json=GEMINI_TEXTO_JSON if not v["esquema"] else "",
               forma_esquema=json.dumps(gemini_esquema("AAA", "BBB"), sort_keys=True), herramientas=["google_search"],
               plazo=GEMINI_PLAZO_S, hilos=GEMINI_HILOS, max_tokens=GEMINI_MAX_TOKENS, granularidad="juego")
    return hashlib.md5(json.dumps(cfg, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:8]


def gemini_cfg():
    """(variante, tope diario) desde semana.ini [gemini]. 'modelo' ya no se lee (D1): si existe y es otro, se avisa."""
    cfg = configparser.ConfigParser()
    if CONFIG.exists():
        cfg.read(CONFIG)
    sec = cfg["gemini"] if cfg.has_section("gemini") else {}
    mod = str(sec.get("modelo", GEMINI_MODELO)).strip()
    if mod and mod != GEMINI_MODELO:
        log(f"AVISO Gemini: semana.ini pide el modelo {mod}; se ignora (v6: el modelo es fijo, {GEMINI_MODELO})")
    var = str(sec.get("variante", "g1")).strip() or "g1"
    if var not in GEMINI_VARIANTES:
        log(f"AVISO Gemini: variante '{var}' desconocida en semana.ini; uso g1")
        var = "g1"
    try:
        tope = int(str(sec.get("max_llamadas_dia", GEMINI_MAX_DIA)).strip() or GEMINI_MAX_DIA)
    except ValueError:
        tope = GEMINI_MAX_DIA
    return var, tope


def _fmt_et(t):
    e = t.astimezone(NUEVA_YORK)
    return f"{['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][e.weekday()]} " \
           f"{['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][e.month - 1]} " \
           f"{e.day}, {(e.hour % 12) or 12}:{e.minute:02d} {'AM' if e.hour < 12 else 'PM'}"


def gemini_pregunta(j, ahora, variante):
    fase = (f"regular season, week {j['semana']}" if j.get("game_type", "REG") == "REG"
            else f"postseason, {RONDAS.get(j['game_type'], j['game_type'])}")
    txt = GEMINI_USUARIO.format(ahora_utc=ahora.astimezone(dt.timezone.utc).strftime("%Y-%m-%d %H:%M"),
                                ahora_et=_fmt_et(ahora), temporada=TEMPORADA, fase=fase,
                                visita_nombre=EQUIPOS.get(j["visita"], j["visita"]), visita=j["visita"],
                                local_nombre=EQUIPOS.get(j["local"], j["local"]), local=j["local"],
                                inicio_utc=j["inicio"].astimezone(dt.timezone.utc).strftime("%Y-%m-%d %H:%M"))
    if not GEMINI_VARIANTES[variante]["esquema"]:
        txt += GEMINI_TEXTO_JSON.format(visita=j["visita"], local=j["local"])
    return txt


def gemini_cuerpo(j, ahora, variante):
    v = GEMINI_VARIANTES[variante]
    gc = {"thinkingConfig": {"thinkingLevel": v["nivel"]}, "maxOutputTokens": GEMINI_MAX_TOKENS}
    if v["esquema"]:
        gc["responseFormat"] = {"text": {"mimeType": GEMINI_MIME, "schema": gemini_esquema(j["visita"], j["local"])}}
    return {"systemInstruction": {"parts": [{"text": GEMINI_SISTEMA}]},
            "contents": [{"role": "user", "parts": [{"text": gemini_pregunta(j, ahora, variante)}]}],
            "tools": [{"google_search": {}}],
            "generationConfig": gc}


def _objeto_json(txt):
    """El objeto JSON de la respuesta: directo, o el primero que aparezca en el texto (variante sin esquema)."""
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


def _dominio(url):
    m = re.match(r"^https?://([^/?#]+)", _texto(url).lower())
    return re.sub(r"^www\.", "", m.group(1)) if m else ""


def gemini_leer(datos, j):
    """De la respuesta de generateContent: uso de tokens, búsquedas, dominios, y la respuesta validada por equipo."""
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
    out["consultas_busqueda"] = " | ".join(consultas)[:400]
    dominios = []
    for ch in gm.get("groundingChunks") or []:
        w = (ch or {}).get("web") or {}
        d = _texto(w.get("domain")) or _texto(w.get("title")) or _dominio(w.get("uri"))
        d = re.sub(r"^www\.", "", d.lower())
        if d and d not in dominios:
            dominios.append(d)
    out["dominios"] = " ".join(dominios)[:400]
    meta_con_contenido = bool(consultas or (gm.get("groundingChunks") or []) or gm.get("searchEntryPoint"))
    partes = ((cand.get("content") or {}).get("parts")) or []
    texto = "".join(p.get("text", "") for p in partes if isinstance(p, dict) and not p.get("thought"))
    obj = _objeto_json(texto)
    equipos = {}
    if obj and isinstance(obj.get("teams"), list):
        for x in obj["teams"]:
            if not isinstance(x, dict):
                continue
            eq = DE_OTRAS.get(_texto(x.get("team")).upper(), _texto(x.get("team")).upper())
            qb = _texto(x.get("qb"))
            if eq not in (j["visita"], j["local"]) or not qb or eq in equipos:
                continue
            conf = _texto(x.get("confidence")).lower()
            url = _texto(x.get("source_url"))
            dom = _dominio(url)
            equipos[eq] = dict(qb=qb, conf=conf if conf in CONFIANZAS else "", url=url[:300],
                               fecha=_texto(x.get("source_date"))[:10],
                               verificada=int(bool(dom) and any(dom == d or dom.endswith("." + d) or d.endswith("." + dom) for d in dominios)))
    out["equipos"] = equipos
    # P2 (v6.2, registrado el 2-oct antes del piloto 3): (a) groundingMetadata con contenido, o (b) enlace de búsqueda
    # de Google (grounding-api-redirect) como fuente de los DOS equipos pedidos
    url_completa = {}                                # equipo → source_url sin recortar
    for x in (obj.get("teams") if obj and isinstance(obj.get("teams"), list) else []):
        if isinstance(x, dict):
            eq = DE_OTRAS.get(_texto(x.get("team")).upper(), _texto(x.get("team")).upper())
            url_completa.setdefault(eq, _texto(x.get("source_url")))
    con_enlace = all(url_completa.get(eq, "").startswith(PREFIJO_BUSQUEDA) for eq in (j["visita"], j["local"]))
    out["evidencia_busqueda"] = "metadatos" if meta_con_contenido else "enlace" if con_enlace else "ninguna"
    if obj is None:
        out["estado"], out["detalle"] = "respuesta inválida", ("sin texto" if not texto else "no es JSON: " + texto[:150])
    elif len(equipos) == 2:
        out["estado"] = "ok"
    elif equipos:
        out["estado"], out["detalle"] = "parcial", "respondió un solo equipo válido"
    else:
        out["estado"], out["detalle"] = "respuesta inválida", "JSON sin equipos válidos"
    return out


def gemini_llamar(llave, j, ahora, variante, limite):
    """Una consulta (un juego). Nunca lanza excepciones ni registra la llave."""
    import requests
    base = dict(game_id=j["game_id"], semana=j["semana"], visita=j["visita"], local=j["local"], equipos={})
    t0 = time.time()
    resta = limite - t0
    if resta < 5:
        return {**base, "estado": "tiempo agotado", "detalle": "sin tiempo para empezar", "latencia_s": 0.0}
    try:
        r = requests.post(f"{GEMINI_URL}/models/{GEMINI_MODELO}:generateContent",
                          headers={"x-goog-api-key": llave, "Content-Type": "application/json"},
                          json=gemini_cuerpo(j, ahora, variante), timeout=(min(10.0, resta), resta))
    except requests.exceptions.Timeout:
        return {**base, "estado": "tiempo agotado", "latencia_s": round(time.time() - t0, 2)}
    except Exception as e:  # noqa: BLE001 — solo el tipo: el texto podría traer datos de la conexión
        return {**base, "estado": "error de red", "detalle": type(e).__name__, "latencia_s": round(time.time() - t0, 2)}
    lat = round(time.time() - t0, 2)
    if r.status_code != 200:
        try:
            msg = _texto(((r.json() or {}).get("error") or {}).get("message"))
        except Exception:  # noqa: BLE001
            msg = ""
        return {**base, "estado": "error HTTP", "http": r.status_code, "detalle": msg[:300], "latencia_s": lat}
    try:
        datos = r.json()
    except ValueError:
        return {**base, "estado": "respuesta inválida", "http": 200, "detalle": "la respuesta no es JSON", "latencia_s": lat}
    return {**base, **gemini_leer(datos, j), "http": 200, "latencia_s": lat}


def gemini_tanda(juegos, ahora, estado, tipo, variante=None):
    """Consulta los juegos en paralelo (máx. 8) con 90 s en total. Devuelve (resultados, duración_s, variante, huella);
    resultados = [] si el agente está apagado (sin llave). Respeta el tope diario; lo que no se consulta queda 'tope'."""
    from concurrent.futures import ThreadPoolExecutor, wait
    if not GEMINI_LLAVE.exists() or not juegos:
        return [], 0.0, None, None
    var_ini, tope = gemini_cfg()
    variante = variante or var_ini
    if tipo != "t85":
        tope = GEMINI_MAX_PRUEBA_DIA
    huella = gemini_huella(variante)
    hoy = ahora.astimezone(CARACAS).date().isoformat()
    clave = "gemini" if tipo == "t85" else "gemini_prueba"
    usado = estado.setdefault(clave, {})
    for k in [k for k in usado if k != hoy]:
        usado.pop(k)
    disponibles = max(tope - usado.get(hoy, 0), 0)
    a_consultar, sin_cupo = juegos[:disponibles], juegos[disponibles:]
    usado[hoy] = usado.get(hoy, 0) + len(a_consultar)
    llave = GEMINI_LLAVE.read_text(encoding="utf-8").strip()
    t0 = time.time()
    limite = t0 + GEMINI_PLAZO_S
    res = {}
    if a_consultar:
        ex = ThreadPoolExecutor(max_workers=GEMINI_HILOS)
        futs = {ex.submit(gemini_llamar, llave, j, ahora, variante, limite): j for j in a_consultar}
        hechos, _ = wait(futs, timeout=max(limite - time.time(), 0) + 1.0)
        for f, j in futs.items():
            if f in hechos and f.exception() is None:
                res[j["game_id"]] = f.result()
            else:
                res[j["game_id"]] = dict(game_id=j["game_id"], semana=j["semana"], visita=j["visita"], local=j["local"],
                                         equipos={}, estado="tiempo agotado", latencia_s=float(GEMINI_PLAZO_S),
                                         detalle="" if f not in hechos else f"excepción {type(f.exception()).__name__}")
        ex.shutdown(wait=False, cancel_futures=True)
    del llave
    for j in sin_cupo:
        res[j["game_id"]] = dict(game_id=j["game_id"], semana=j["semana"], visita=j["visita"], local=j["local"],
                                 equipos={}, estado="tope", detalle=f"tope de {tope} consultas del día", latencia_s=0.0)
    dur = round(time.time() - t0, 2)
    salida = [res[j["game_id"]] for j in juegos]
    filas = []
    for x in salida:
        f = {k: x.get(k) for k in CAMPOS_GEM if k in x}
        f.update(corrida_utc=iso(ahora), tipo=tipo, agente=variante, huella=huella, modelo=GEMINI_MODELO)
        for lado, eq in (("visita", x["visita"]), ("local", x["local"])):
            e = x["equipos"].get(eq) or {}
            f.update({f"qb_{lado}": e.get("qb", ""), f"conf_{lado}": e.get("conf", ""), f"url_{lado}": e.get("url", ""),
                      f"fecha_{lado}": e.get("fecha", ""), f"url_{lado}_verificada": e.get("verificada", "")})
        filas.append(f)
    SAL.mkdir(parents=True, exist_ok=True)
    if GEMINI_LLAMADAS.exists():                     # v6.2: columnas nuevas → el archivo viejo se guarda aparte, no se mezcla
        with open(GEMINI_LLAMADAS, encoding="utf-8") as fh:
            encabezado = fh.readline().strip().split(",")
        if encabezado != CAMPOS_GEM:
            viejo = GEMINI_LLAMADAS.with_name("gemini_llamadas_hasta_v61.csv")
            if viejo.exists():
                viejo = GEMINI_LLAMADAS.with_name(f"gemini_llamadas_previo_{int(time.time())}.csv")
            GEMINI_LLAMADAS.rename(viejo)
            log(f"Gemini: el registro de llamadas tenía otras columnas; lo guardé como {viejo.name}")
    nuevo = not GEMINI_LLAMADAS.exists()
    with open(GEMINI_LLAMADAS, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CAMPOS_GEM)
        if nuevo:
            w.writeheader()
        for f in filas:
            w.writerow({k: ("" if f.get(k) is None else f.get(k)) for k in CAMPOS_GEM})
    cuenta = {}
    for x in salida:
        cuenta[x["estado"]] = cuenta.get(x["estado"], 0) + 1
    log(f"Gemini {variante} ({huella}, {tipo}): {len(salida)} juegos en {dur:.1f} s · {cuenta}")
    return salida, dur, variante, huella


def gid_por_nombre(fq, nombre, equipo):
    """Nombre que respondió Gemini → gsis: igual nombre normalizado; si no, único QB del roster de ese equipo con ese
    apellido. Si no se puede, '' (el voto se compara después por nombre contra el QB que jugó)."""
    n = _norm(nombre)
    if not n:
        return ""
    for g, nom in fq.nombre.items():
        if nom and _norm(nom) == n:
            return g
    ap = _norm(nombre.split()[-1]) if nombre.split() else ""
    cands = [g for g, f in fq.roster.items()
             if _texto(f.get("team")) == equipo and ap and _norm(_texto(f.get("full_name")).split()[-1] if _texto(f.get("full_name")) else "") == ap]
    return cands[0] if len(cands) == 1 else ""


def gemini_sombra(pendientes, ahora, estado):
    """Corridas T−85: consulta los juegos proyectados y registra los votos en sombra (uno por equipo, vacío si no hay
    respuesta). pendientes = [(juego, FuentesQB)]. Nunca detiene la corrida."""
    try:
        juegos = [j for j, _ in pendientes]
        salida, dur, variante, huella = gemini_tanda(juegos, ahora, estado, "t85")
        if not salida:
            return
        fq_de = {j["game_id"]: fq for j, fq in pendientes}
        votos = []
        for x in salida:
            fq = fq_de[x["game_id"]]
            for eq in (x["visita"], x["local"]):
                e = x["equipos"].get(eq) or {}
                nom = e.get("qb", "")
                nota = f"{variante} · {x['estado']}" + (f" · conf {e.get('conf')}" if e.get("conf") else "") + \
                       (f" · {e.get('url')}" if e.get("url") else "")
                votos.append(dict(corrida_utc=iso(ahora), tipo="t85", game_id=x["game_id"], semana=x["semana"], equipo=eq,
                                  fuente="gemini", qb_id=gid_por_nombre(fq, nom, eq) if nom else "", qb_nombre=nom,
                                  nota=nota[:200]))
        anexar_fuentes(votos)
    except Exception as e:  # noqa: BLE001
        log(f"Gemini: error en la sombra ({type(e).__name__}); la proyección no se afecta")


def gemini_piloto(g26, ahora, estado, variante=None):
    """Piloto (criterios P1-P4 escritos antes, registro 35A g1): consulta los juegos pendientes de la semana, tipo
    'prueba' (no cuenta para el piso ni deja votos). Devuelve el informe en texto."""
    import polars as pl
    if not GEMINI_LLAVE.exists():
        return "Piloto: no hay llave de Gemini (credenciales/gemini.key). Cárgala con: bash ~/nfl_sim/cargar_gemini.sh"
    sem = semana_actual(g26, ahora)
    if sem is None:
        return "Piloto: no hay juegos pendientes en el calendario."
    jg = g26.filter((pl.col("week") == sem) & (pl.col("inicio") > ahora)).sort(["inicio", "game_id"])
    juegos = [dict(game_id=r["game_id"], semana=sem, game_type=r["game_type"], visita=r["away_team"], local=r["home_team"],
                   inicio=r["inicio"]) for r in jg.iter_rows(named=True)]
    variante = variante or gemini_cfg()[0]
    hoy = ahora.astimezone(CARACAS).date().isoformat()
    usados = (estado.get("gemini_prueba") or {}).get(hoy, 0)
    if GEMINI_MAX_PRUEBA_DIA - usados < len(juegos):
        return (f"Piloto: no hay cupo para un piloto completo hoy ({usados} de {GEMINI_MAX_PRUEBA_DIA} consultas de prueba "
                f"usadas; hacen falta {len(juegos)}). No consulté nada; se puede repetir mañana.")
    salida, dur, variante, huella = gemini_tanda(juegos, ahora, estado, "prueba", variante)
    n = len(salida)
    if not n:
        return "Piloto: no se hizo ninguna consulta."
    resp = [x for x in salida if x.get("http") == 200]
    ok = [x for x in salida if x["estado"] == "ok"]
    con_busq = [x for x in resp if x.get("evidencia_busqueda") in ("metadatos", "enlace")]
    lat = [x.get("latencia_s") or 0.0 for x in salida]
    costos = [x.get("costo_usd") or 0.0 for x in resp]
    c_medio = sum(costos) / len(costos) if costos else None
    p1 = len(ok) / n >= 0.90
    p2 = bool(resp) and len(con_busq) == len(resp)
    p3 = dur <= 60 and max(lat) < GEMINI_PLAZO_S and not any(x["estado"] == "tiempo agotado" for x in salida)
    p4 = c_medio is not None and c_medio <= 0.02
    si = lambda b: "✅" if b else "❌"  # noqa: E731
    mv = sorted({x.get("model_version") for x in resp if x.get("model_version")})
    lin = [f"PILOTO Gemini · variante {variante} (huella {huella}) · {GEMINI_MODELO}"
           + (f" · versión devuelta: {', '.join(mv)}" if mv else ""),
           f"Semana {sem}: {n} consultas (juegos pendientes) en una tanda de {dur:.0f} s · tipo 'prueba': no cuenta para el piso",
           f"P1 JSON válido con los dos equipos: {len(ok)}/{n} ({100 * len(ok) / n:.0f} %) · pasa si ≥ 90 % {si(p1)}",
           f"P2 con evidencia de búsqueda (de las que respondieron): {len(con_busq)}/{len(resp)} · pasa si 100 % {si(p2)} "
           f"[metadatos {sum(1 for x in resp if x.get('evidencia_busqueda') == 'metadatos')} · enlace de búsqueda en los dos equipos "
           f"{sum(1 for x in resp if x.get('evidencia_busqueda') == 'enlace')}]",
           f"P3 tanda {dur:.0f} s (≤ 60) y la más lenta {max(lat):.0f} s (< 90) {si(p3)}",
           (f"P4 costo medio USD {c_medio:.4f} por consulta (máx {max(costos):.4f}) · pasa si ≤ 0,02 {si(p4)}"
            if c_medio is not None else f"P4 sin consultas respondidas {si(False)}")]
    if p1 and p2 and p3 and p4:
        lin.append(f"VEREDICTO: PASA. La variante {variante} queda como definitiva para las corridas T−85.")
    else:
        rech = [x for x in salida if x["estado"] == "error HTTP" and x.get("http") == 400]
        sug = []
        if rech and len(rech) >= n // 2 and GEMINI_VARIANTES[variante]["esquema"]:
            sug.append("la API rechazó la petición (400): probar g1-texto (sin esquema) → /piloto g1-texto")
        elif variante == "g1":
            if not (p3 and p4):
                sug.append("fallan P3 o P4: probar g1-low → /piloto g1-low")
            if not p2:
                sug.append("falla P2: probar g1-high una sola vez → /piloto g1-high")
        lin.append("VEREDICTO: NO PASA. " + ("Siguiente paso previsto: " + "; ".join(sug) if sug else "Mándame este informe."))
    # descriptivo (no decide): coincidencia con el consenso de fuentes, tokens, búsquedas, dominios, errores
    try:
        fq = FuentesQB(sem)
        igual = total = 0
        for x in salida:
            fila = jg.filter(pl.col("game_id") == x["game_id"]).row(0, named=True)
            for eq in (x["visita"], x["local"]):
                e = x["equipos"].get(eq)
                if not e:
                    continue
                base = _texto(fila["home_qb_id"] if eq == fila["home_team"] else fila["away_qb_id"])
                _, usado, _, _ = fq.votar(eq, base)
                g = gid_por_nombre(fq, e["qb"], eq)
                total += 1
                igual += int(bool(g) and g == usado)
        lin.append(f"Descriptivo: coincide con el consenso de fuentes en {igual} de {total} equipos respondidos.")
    except Exception as e:  # noqa: BLE001
        lin.append(f"Descriptivo: no pude comparar con el consenso ({type(e).__name__}).")
    if resp:
        media = lambda k: sum((x.get(k) or 0) for x in resp) / len(resp)  # noqa: E731
        lin.append(f"Tokens medios: entrada {media('tok_entrada'):.0f} · herramienta {media('tok_herramienta'):.0f} · "
                   f"salida {media('tok_salida'):.0f} · razonamiento {media('tok_razonamiento'):.0f} · "
                   f"búsquedas {sum(x.get('busquedas') or 0 for x in resp)} en total")
        doms = {}
        for x in resp:
            for d in (x.get("dominios") or "").split():
                doms[d] = doms.get(d, 0) + 1
        if doms:
            lin.append("Dominios citados: " + ", ".join(f"{d} ({c})" for d, c in sorted(doms.items(), key=lambda kv: -kv[1])[:8]))
    estados = {}
    for x in salida:
        estados[x["estado"]] = estados.get(x["estado"], 0) + 1
    lin.append("Estados: " + ", ".join(f"{k} {v}" for k, v in estados.items()))
    for x in salida:
        eqs = " · ".join(f"{eq} {x['equipos'][eq]['qb']} ({x['equipos'][eq]['conf'] or '—'})"
                         for eq in (x["visita"], x["local"]) if eq in x["equipos"])
        lin.append(f"  {x['visita']} @ {x['local']}: {x['estado']} · {x.get('latencia_s') or 0:.0f} s"
                   + (f" · {eqs}" if eqs else "") + (f" · {x['detalle']}" if x.get("detalle") else ""))
    lin.append(f"Registro: salidas/semana/{GEMINI_LLAMADAS.name}")
    return "\n".join(lin)


# --------------------------------------------------------------------------------------
# v8.2 (decisión 49, ruta A, aprobada por Ozz el 8-oct): registro en vivo «e2» a T−85 (claude/registro_49_vivo.md)
#   · Consulta APARTE de g1 (no toca su configuración, su huella ni el reloj de su piso): por equipo, V1 enfermedad,
#     V2 vestuario (suspensión, conflicto, despido o cambio de quien llama las jugadas), V3 descanso de titulares
#     anunciado y V4 una línea libre. Solo en las corridas automáticas T−85 (modo auto), después de g1.
#   · El pedido lleva la hora real: el resultado todavía no existe. Una fila consultada en o después del inicio queda
#     con valida = 0 y no entra al análisis.
#   · Tope propio (E2_MAX_DIA consultas por día de Caracas, estado["e2"]); sin reintentos; plazo propio de 120 s.
#   · Registro: salidas/semana/e2_vivo.csv (2 filas por juego). Se mide una sola vez al cerrar la semana 18; hasta
#     entonces el modo estado solo muestra conteos, nunca resultados contra la línea.
#   · semana.ini [e2] activo = no lo apaga sin tocar código.
# --------------------------------------------------------------------------------------
E2_MAX_DIA = 20
E2_PLAZO_S = 120
E2_HILOS = 8
E2_REGISTRO = SAL / "e2_vivo.csv"
_T0_PROCESO = time.time()
CAMPOS_E2 = ["corrida_utc", "game_id", "semana", "game_type", "inicio_utc", "minutos_antes", "valida", "equipo", "rival",
             "es_local", "huella", "modelo", "model_version", "estado", "http", "latencia_s", "costo_usd",
             "evidencia_busqueda", "v1_enfermedad", "v1_url", "v1_fecha", "v1_conf", "v2_vestuario", "v2_url", "v2_fecha",
             "v2_conf", "v3_descanso", "v3_url", "v3_fecha", "v3_conf", "v4_nota", "detalle"]
E2_SISTEMA = """You are a careful NFL news researcher using Google Search. Rules:
1. Always search before answering, using at most 5 Google searches in total.
2. Use only news published in the last 7 days. Report only what a source you found states; never guess.
3. Fill every field for both teams, using the team codes given. If you find nothing for a field, answer false and
   leave its url and date as empty strings.
4. Each *_url must be a page that appeared in your search results; never build or guess a URL. Each *_date is that
   page's publication date (YYYY-MM-DD).
5. *_conf: "high" if official or several reliable sources agree; "medium" if one reliable source; "low" if unclear."""
E2_USUARIO = """Now: {ahora_utc} UTC ({ahora_et} ET), {minutos} minutes before kickoff. NFL {temporada} {fase}.
Game: {visita_nombre} ({visita}) at {local_nombre} ({local}), kickoff {inicio_utc} UTC.
For EACH team, as reported this week:
- illness: was an illness or virus affecting several players reported?
- turmoil: was there a suspension, a public conflict, a firing, or a change of offensive or defensive play-caller?
- resting_starters: did the team announce it will rest starters in this game?
- other_news: one short line with any other relevant pre-game news that is not a routine injury update, or "" if none."""
E2_PARTES = (("illness", "v1", "v1_enfermedad"), ("turmoil", "v2", "v2_vestuario"), ("resting", "v3", "v3_descanso"))


def e2_esquema(visita, local):
    def equipo(eq):
        s, b = {"type": "string"}, {"type": "boolean"}
        conf = {"type": "string", "enum": list(CONFIANZAS)}
        props = {"team": {"type": "string", "enum": [eq]},
                 "illness": b, "illness_url": s, "illness_date": s, "illness_conf": conf,
                 "turmoil": b, "turmoil_url": s, "turmoil_date": s, "turmoil_conf": conf,
                 "resting_starters": b, "resting_url": s, "resting_date": s, "resting_conf": conf,
                 "other_news": s}
        return {"type": "object", "properties": props, "required": list(props)}
    return {"type": "object", "properties": {"away": equipo(visita), "home": equipo(local)}, "required": ["away", "home"]}


def e2_huella():
    """Huella de la configuración e2 completa. Cambia → configuración nueva (se anota en cada fila)."""
    cfg = dict(modelo=GEMINI_MODELO, via="generateContent", nivel="medium", mime=GEMINI_MIME, sistema=E2_SISTEMA,
               usuario=E2_USUARIO, forma_esquema=json.dumps(e2_esquema("AAA", "BBB"), sort_keys=True),
               herramientas=["google_search"], plazo=E2_PLAZO_S, hilos=E2_HILOS, max_tokens=GEMINI_MAX_TOKENS)
    return hashlib.md5(json.dumps(cfg, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:8]


def e2_activo():
    cfg = configparser.ConfigParser()
    if CONFIG.exists():
        cfg.read(CONFIG)
    val = str(cfg["e2"].get("activo", "si")).strip().lower() if cfg.has_section("e2") else "si"
    return val not in ("no", "0", "false", "apagado")


def e2_momento(ahora):
    """Hora de la consulta: la de la corrida más lo que lleva el proceso (igual en producción y con --ahora)."""
    return ahora + dt.timedelta(seconds=round(time.time() - _T0_PROCESO))


def e2_cuerpo(j, momento):
    fase = (f"regular season, week {j['semana']}" if j.get("game_type", "REG") == "REG"
            else f"postseason, {RONDAS.get(j['game_type'], j['game_type'])}")
    txt = E2_USUARIO.format(ahora_utc=momento.astimezone(dt.timezone.utc).strftime("%Y-%m-%d %H:%M"),
                            ahora_et=_fmt_et(momento), minutos=max(int((j["inicio"] - momento).total_seconds() // 60), 0),
                            temporada=TEMPORADA, fase=fase,
                            visita_nombre=EQUIPOS.get(j["visita"], j["visita"]), visita=j["visita"],
                            local_nombre=EQUIPOS.get(j["local"], j["local"]), local=j["local"],
                            inicio_utc=j["inicio"].astimezone(dt.timezone.utc).strftime("%Y-%m-%d %H:%M"))
    return {"systemInstruction": {"parts": [{"text": E2_SISTEMA}]},
            "contents": [{"role": "user", "parts": [{"text": txt}]}],
            "tools": [{"google_search": {}}],
            "generationConfig": {"thinkingConfig": {"thinkingLevel": "medium"}, "maxOutputTokens": GEMINI_MAX_TOKENS,
                                 "responseFormat": {"text": {"mimeType": GEMINI_MIME, "schema": e2_esquema(j["visita"], j["local"])}}}}


def _e2_bool(x):
    if isinstance(x, bool):
        return x
    t = _texto(x).lower()
    return True if t in ("true", "yes") else False if t in ("false", "no") else None


def e2_leer(datos, j):
    u = datos.get("usageMetadata") or {}
    ent = int(u.get("promptTokenCount") or 0) + int(u.get("toolUsePromptTokenCount") or 0)
    sal = int(u.get("candidatesTokenCount") or 0) + int(u.get("thoughtsTokenCount") or 0)
    out = dict(model_version=_texto(datos.get("modelVersion")), costo_usd=round(ent * PRECIO_ENTRADA + sal * PRECIO_SALIDA, 6))
    cand = (datos.get("candidates") or [{}])[0] or {}
    gm = cand.get("groundingMetadata") or {}
    partes = ((cand.get("content") or {}).get("parts")) or []
    texto = "".join(p.get("text", "") for p in partes if isinstance(p, dict) and not p.get("thought"))
    obj = _objeto_json(texto)
    equipos, urls = {}, []
    for lado, eq in (("away", j["visita"]), ("home", j["local"])):
        x = (obj or {}).get(lado)
        if not isinstance(x, dict) or DE_OTRAS.get(_texto(x.get("team")).upper(), _texto(x.get("team")).upper()) != eq:
            continue
        f = {}
        for pre, cod, col in E2_PARTES:
            clave = "resting_starters" if pre == "resting" else pre
            val = _e2_bool(x.get(clave))
            f[col] = "" if val is None else int(val)
            f[f"{cod}_url"] = _texto(x.get(f"{pre}_url"))[:300]
            f[f"{cod}_fecha"] = _texto(x.get(f"{pre}_date"))[:10]
            conf = _texto(x.get(f"{pre}_conf")).lower()
            f[f"{cod}_conf"] = conf if conf in CONFIANZAS else ""
            if f[f"{cod}_url"]:
                urls.append(f[f"{cod}_url"])
        f["v4_nota"] = _texto(x.get("other_news"))[:200]
        if all(f[col] != "" for _, _, col in E2_PARTES):
            equipos[eq] = f
    out["equipos"] = equipos
    meta = bool((gm.get("webSearchQueries") or []) or (gm.get("groundingChunks") or []) or gm.get("searchEntryPoint"))
    out["evidencia_busqueda"] = "metadatos" if meta else "enlace" if any(u_.startswith(PREFIJO_BUSQUEDA) for u_ in urls) else "ninguna"
    if obj is None:
        out["estado"], out["detalle"] = "respuesta inválida", ("sin texto" if not texto else "no es JSON: " + texto[:150])
    elif len(equipos) == 2:
        out["estado"], out["detalle"] = "ok", ""
    elif equipos:
        out["estado"], out["detalle"] = "parcial", "respondió un solo equipo válido"
    else:
        out["estado"], out["detalle"] = "respuesta inválida", "JSON sin equipos válidos"
    return out


def e2_llamar(llave, j, momento, limite):
    """Una consulta e2 (un juego). Nunca lanza excepciones ni registra la llave."""
    import requests
    base = dict(equipos={})
    t0 = time.time()
    resta = limite - t0
    if resta < 5:
        return {**base, "estado": "tiempo agotado", "detalle": "sin tiempo para empezar", "latencia_s": 0.0}
    try:
        r = requests.post(f"{GEMINI_URL}/models/{GEMINI_MODELO}:generateContent",
                          headers={"x-goog-api-key": llave, "Content-Type": "application/json"},
                          json=e2_cuerpo(j, momento), timeout=(min(10.0, resta), resta))
    except requests.exceptions.Timeout:
        return {**base, "estado": "tiempo agotado", "latencia_s": round(time.time() - t0, 2)}
    except Exception as e:  # noqa: BLE001
        return {**base, "estado": "error de red", "detalle": type(e).__name__, "latencia_s": round(time.time() - t0, 2)}
    lat = round(time.time() - t0, 2)
    if r.status_code != 200:
        try:
            msg = _texto(((r.json() or {}).get("error") or {}).get("message"))
        except Exception:  # noqa: BLE001
            msg = ""
        return {**base, "estado": "error HTTP", "http": r.status_code, "detalle": msg[:300], "latencia_s": lat}
    try:
        datos = r.json()
    except ValueError:
        return {**base, "estado": "respuesta inválida", "http": 200, "detalle": "la respuesta no es JSON", "latencia_s": lat}
    return {**base, **e2_leer(datos, j), "http": 200, "latencia_s": lat}


def e2_vivo(pendientes, ahora, estado):
    """Registro en vivo e2 de los juegos de una corrida automática T−85 (después de g1). Nunca detiene la corrida."""
    try:
        if not pendientes or not GEMINI_LLAVE.exists() or not e2_activo():
            return
        from concurrent.futures import ThreadPoolExecutor, wait
        juegos = [j for j, _ in pendientes]
        momento = e2_momento(ahora)
        hoy = momento.astimezone(CARACAS).date().isoformat()
        usado = estado.setdefault("e2", {})
        for k in [k for k in usado if k != hoy]:
            usado.pop(k)
        disponibles = max(E2_MAX_DIA - usado.get(hoy, 0), 0)
        a_consultar, sin_cupo = juegos[:disponibles], juegos[disponibles:]
        usado[hoy] = usado.get(hoy, 0) + len(a_consultar)
        llave = GEMINI_LLAVE.read_text(encoding="utf-8").strip()
        t0 = time.time()
        limite = t0 + E2_PLAZO_S
        res = {}
        if a_consultar:
            ex = ThreadPoolExecutor(max_workers=E2_HILOS)
            futs = {ex.submit(e2_llamar, llave, j, momento, limite): j for j in a_consultar}
            hechos, _ = wait(futs, timeout=max(limite - time.time(), 0) + 1.0)
            for f, j in futs.items():
                res[j["game_id"]] = (f.result() if f in hechos and f.exception() is None else
                                     dict(equipos={}, estado="tiempo agotado", latencia_s=float(E2_PLAZO_S)))
            ex.shutdown(wait=False, cancel_futures=True)
        del llave
        for j in sin_cupo:
            res[j["game_id"]] = dict(equipos={}, estado="tope", detalle=f"tope de {E2_MAX_DIA} consultas del día", latencia_s=0.0)
        huella = e2_huella()
        filas = []
        for j in juegos:
            x = res[j["game_id"]]
            minutos = round((j["inicio"] - momento).total_seconds() / 60, 1)
            for eq, rival, es_local in ((j["visita"], j["local"], 0), (j["local"], j["visita"], 1)):
                f = dict(corrida_utc=iso(momento), game_id=j["game_id"], semana=j["semana"], game_type=j.get("game_type", "REG"),
                         inicio_utc=iso(j["inicio"]), minutos_antes=minutos, valida=int(minutos > 0), equipo=eq, rival=rival,
                         es_local=es_local, huella=huella, modelo=GEMINI_MODELO, model_version=x.get("model_version", ""),
                         estado=x["estado"], http=x.get("http", ""), latencia_s=x.get("latencia_s", ""),
                         costo_usd=x.get("costo_usd", "") if es_local == 0 else "",      # el costo, una vez por juego
                         evidencia_busqueda=x.get("evidencia_busqueda", ""), detalle=x.get("detalle", ""))
                f.update(x["equipos"].get(eq) or {})
                filas.append(f)
        SAL.mkdir(parents=True, exist_ok=True)
        if E2_REGISTRO.exists():
            with open(E2_REGISTRO, encoding="utf-8") as fh:
                if fh.readline().strip().split(",") != CAMPOS_E2:
                    viejo = E2_REGISTRO.with_name(f"e2_vivo_previo_{int(time.time())}.csv")
                    E2_REGISTRO.rename(viejo)
                    log(f"e2: el registro tenía otras columnas; lo guardé como {viejo.name}")
        nuevo = not E2_REGISTRO.exists()
        with open(E2_REGISTRO, "a", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=CAMPOS_E2)
            if nuevo:
                w.writeheader()
            for f in filas:
                w.writerow({k: ("" if f.get(k) is None else f.get(k)) for k in CAMPOS_E2})
        cuenta = {}
        for gid in {j["game_id"] for j in juegos}:
            cuenta[res[gid]["estado"]] = cuenta.get(res[gid]["estado"], 0) + 1
        costo = sum(float(r.get("costo_usd") or 0) for r in res.values())
        log(f"e2 ({huella}): {len(juegos)} juegos en {time.time() - t0:.1f} s · {cuenta} · USD {costo:.4f}")
    except Exception as e:  # noqa: BLE001
        log(f"e2: error ({type(e).__name__}); la proyección y g1 no se afectan")


def texto_e2_estado(ahora, estado):
    """Solo conteos (registro 49: nada de resultados contra la línea antes de cerrar la semana 18)."""
    hoy = ahora.astimezone(CARACAS).date().isoformat()
    cab = (f"Registro en vivo e2 (49): {'activo' if e2_activo() else 'APAGADO en semana.ini'} · huella {e2_huella()} · "
           f"hoy {estado.get('e2', {}).get(hoy, 0)}/{E2_MAX_DIA} consultas")
    if not E2_REGISTRO.exists():
        return cab + " · todavía sin consultas (empieza en la próxima T−85 automática)"
    with open(E2_REGISTRO, encoding="utf-8") as fh:
        filas = list(csv.DictReader(fh))
    validas = [f for f in filas if f.get("valida") == "1"]
    juegos = {f["game_id"] for f in validas}
    ok = [f for f in validas if f.get("estado") in ("ok", "parcial") and f.get("v1_enfermedad") != ""]
    band = {col: sum(1 for f in ok if f.get(col) == "1") for _, _, col in E2_PARTES}
    costo = sum(float(f.get("costo_usd") or 0) for f in filas)
    return (cab + f" · {len(juegos)} juegos registrados ({len(ok)} equipos con respuesta) · banderas: enfermedad "
            f"{band['v1_enfermedad']}, vestuario {band['v2_vestuario']}, descanso {band['v3_descanso']} · USD {costo:.2f}")


# --------------------------------------------------------------------------------------
# v8.3 (decisión 55, aprobada por Ozz el 10-oct): el VIGÍA del motor (claude/registro_55_vigia.md, escrito antes)
#   · Gemini solo reporta HECHOS de fuente oficial: lista de inactivos, reporte final de lesiones (Out/Doubtful),
#     movimientos oficiales, declaraciones con nombre y anuncios de la NFL, con URL y hora. Nada anónimo ni especulativo.
#   · El código (sin IA) valida cada hecho, cruza el nombre con el roster 2026, decide los titulares habituales con los
#     snaps (definición de F0) y arma el aviso «la máquina no sabe esto» (s2-v1 solo usa el QB).
#   · Solo en las corridas automáticas T−85, después de g1 y antes de e2 (sus huellas no cambian). Piloto: Flash-Lite (A)
#     y 3.8 Flash (B) consultan cada juego hasta que la regla del registro elige uno (lo aplica el código).
#   · Si Google rechaza el esquema con 400 (pasó en los parlays, 42), el mismo pedido va sin esquema con el formato JSON
#     en el texto (columna 'forma'); un 400 no se cobra.
#   · No cambia la proyección, s2-v1, las selecciones de 29A, 31A, el boleto ni el consenso del QB.
# --------------------------------------------------------------------------------------
VIGIA_MODELOS = {"A": "gemini-3.5-flash-lite", "B": "gemini-3.8-flash"}
VIGIA_NOMBRE = {"A": "Flash-Lite", "B": "3.8 Flash"}
VIGIA_MAX_DIA = 40
VIGIA_PLAZO_S = 300                                # v8.3.1 (Ozz, 11-oct, opción b): antes 180
VIGIA_HILOS = 16                                   # v8.3.1: antes 8
VIGIA_MAX_JUG = 15
VIGIA_CONSULTAS = SAL / "vigia_consultas.csv"
VIGIA_HECHOS = SAL / "vigia_hechos.csv"
URL_SNAPS = "https://github.com/nflverse/nflverse-data/releases/download/snap_counts/snap_counts_{}.csv"
VIGIA_ESTADOS = ("inactive", "out", "doubtful", "injured_reserve", "suspended", "released_or_traded", "other_official")
VIGIA_NO_JUEGA = {"inactive", "out", "doubtful", "injured_reserve", "suspended", "released_or_traded"}
VIGIA_FUENTES = ("official_inactive_list", "official_injury_report", "team_transaction", "team_or_coach_statement",
                 "league_announcement")
VIGIA_SIN_TITULAR = {"K", "P", "LS"}
VIGIA_PILOTO_SEMANAS, VIGIA_PILOTO_MAX = 2, 4
VIGIA_PILOTO_DESDE = 6                             # v8.3.1: el piloto empieza en la semana 6 (huellas nuevas)
VIGIA_MIN_HECHOS, VIGIA_MIN_PRECISION, VIGIA_MAX_FALLAS, VIGIA_DIF_COBERTURA = 10, 0.90, 0.20, 0.05
VIGIA_HOLGURA_MIN = 5                              # minutos de tolerancia de reloj para «fuente posterior a la consulta»
ESTADO_ES = {"inactive": "inactivo", "out": "out", "doubtful": "doubtful", "injured_reserve": "lista de lesionados",
             "suspended": "suspendido", "released_or_traded": "cortado o cambiado", "other_official": "otro"}
FUENTE_ES = {"official_inactive_list": "lista oficial de inactivos", "official_injury_report": "reporte de lesiones",
             "team_transaction": "movimiento oficial", "team_or_coach_statement": "declaración oficial",
             "league_announcement": "anuncio de la NFL"}
CAMPOS_VC = ["corrida_utc", "game_id", "semana", "game_type", "inicio_utc", "minutos_antes", "valida", "modelo_clave",
             "modelo", "huella", "forma", "model_version", "estado", "http", "latencia_s", "costo_usd", "busquedas",
             "evidencia_busqueda", "inactivos_visita", "inactivos_local", "titulares_visita", "titulares_local",
             "n_hechos", "n_avisos", "detalle"]
CAMPOS_VH = ["corrida_utc", "game_id", "semana", "modelo_clave", "huella", "equipo", "nombre", "posicion",
             "estado_jugador", "tipo_fuente", "url", "publicada", "evidencia", "valido", "motivo_invalido", "gsis_id",
             "cruce", "titular", "part_media", "es_qb_usado", "aviso", "minutos_antes", "nombre_roster"]
VIGIA_SISTEMA = """You are a strict NFL player-availability fact checker using Google Search. Report ONLY official facts.
Rules:
1. Always search before answering. Your training data is out of date.
2. Report a player only if an official source says he will NOT play this game: the team's official inactive list for
   this game, the final injury report (Out or Doubtful), an official roster move (injured reserve, PUP, NFI, suspension,
   release, trade), an on-record statement by the team or its head coach, or an NFL announcement.
3. Never report rumors, anonymous sources ("sources say"), "expected to", "questionable", "game-time decision" or
   predictions.
4. source_url must be a page that appeared in your search results; never build or guess a URL. source_published is
   that page's publication time in UTC (YYYY-MM-DDTHH:MM), or its date (YYYY-MM-DD) if no time is shown.
5. evidence: what the source says, in 20 words or fewer.
6. inactives_published: true only if you found the official inactive list for THIS game.
7. Use the team codes given and return both teams. An empty players list is a valid answer."""
VIGIA_USUARIO = """Now: {ahora_utc} UTC ({ahora_et} ET), {minutos} minutes before kickoff. NFL {temporada} {fase}.
Game: {visita_nombre} ({visita}) at {local_nombre} ({local}), kickoff {inicio_utc} UTC.
For EACH team, list the players who will not play this game according to official sources (at most 15 per team)."""
VIGIA_TEXTO_JSON = ('\nAnswer ONLY with a JSON object of this form and nothing else: {"away": {"team": "@V@", '
                    '"inactives_published": true, "players": [{"name": "Full Name", "position": "C", "status": '
                    '"inactive|out|doubtful|injured_reserve|suspended|released_or_traded|other_official", "source_type": '
                    '"official_inactive_list|official_injury_report|team_transaction|team_or_coach_statement|'
                    'league_announcement", "source_url": "https://...", "source_published": "YYYY-MM-DDTHH:MM", '
                    '"evidence": "..."}]}, "home": {"team": "@L@", "inactives_published": false, "players": []}}')
_VIG = {}


def vigia_esquema(visita, local):
    def equipo(eq):
        s = {"type": "string"}
        jug = {"type": "object",
               "properties": {"name": s, "position": s, "status": {"type": "string", "enum": list(VIGIA_ESTADOS)},
                              "source_type": {"type": "string", "enum": list(VIGIA_FUENTES)}, "source_url": s,
                              "source_published": s, "evidence": s},
               "required": ["name", "position", "status", "source_type", "source_url", "source_published", "evidence"]}
        return {"type": "object",
                "properties": {"team": {"type": "string", "enum": [eq]}, "inactives_published": {"type": "boolean"},
                               "players": {"type": "array", "maxItems": VIGIA_MAX_JUG, "items": jug}},
                "required": ["team", "inactives_published", "players"]}
    return {"type": "object", "properties": {"away": equipo(visita), "home": equipo(local)}, "required": ["away", "home"]}


def vigia_huella(clave):
    """Huella de la configuración completa del vigía para un modelo. Cambia → configuración nueva (se anota en cada fila)."""
    cfg = dict(modelo=VIGIA_MODELOS[clave], via="generateContent", nivel="medium", mime=GEMINI_MIME, sistema=VIGIA_SISTEMA,
               usuario=VIGIA_USUARIO, texto_json=VIGIA_TEXTO_JSON, respaldo_400="texto",
               forma_esquema=json.dumps(vigia_esquema("AAA", "BBB"), sort_keys=True), herramientas=["google_search"],
               plazo=VIGIA_PLAZO_S, hilos=VIGIA_HILOS, max_tokens=GEMINI_MAX_TOKENS)
    return hashlib.md5(json.dumps(cfg, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:8]


def vigia_cfg():
    """(activo, tope diario) desde semana.ini [vigia]."""
    cfg = configparser.ConfigParser()
    if CONFIG.exists():
        cfg.read(CONFIG)
    sec = cfg["vigia"] if cfg.has_section("vigia") else {}
    activo = str(sec.get("activo", "si")).strip().lower() not in ("no", "0", "false", "apagado")
    try:
        tope = int(str(sec.get("max_llamadas_dia", VIGIA_MAX_DIA)).strip() or VIGIA_MAX_DIA)
    except ValueError:
        tope = VIGIA_MAX_DIA
    return activo, tope


def vigia_precio(clave, cuando):
    """USD por token (entrada, salida) del modelo en esa fecha (el razonamiento se cobra como salida)."""
    if clave == "A":
        return PRECIO_ENTRADA, PRECIO_SALIDA
    return (0.75e-6, 3.75e-6) if cuando.astimezone(dt.timezone.utc).date() <= dt.date(2026, 12, 31) else (1.50e-6, 7.50e-6)


def vigia_cuerpo(j, momento, con_esquema=True):
    fase = (f"regular season, week {j['semana']}" if j.get("game_type", "REG") == "REG"
            else f"postseason, {RONDAS.get(j['game_type'], j['game_type'])}")
    txt = VIGIA_USUARIO.format(ahora_utc=momento.astimezone(dt.timezone.utc).strftime("%Y-%m-%d %H:%M"),
                               ahora_et=_fmt_et(momento), minutos=max(int((j["inicio"] - momento).total_seconds() // 60), 0),
                               temporada=TEMPORADA, fase=fase,
                               visita_nombre=EQUIPOS.get(j["visita"], j["visita"]), visita=j["visita"],
                               local_nombre=EQUIPOS.get(j["local"], j["local"]), local=j["local"],
                               inicio_utc=j["inicio"].astimezone(dt.timezone.utc).strftime("%Y-%m-%d %H:%M"))
    gc = {"thinkingConfig": {"thinkingLevel": "medium"}, "maxOutputTokens": GEMINI_MAX_TOKENS}
    if con_esquema:
        gc["responseFormat"] = {"text": {"mimeType": GEMINI_MIME, "schema": vigia_esquema(j["visita"], j["local"])}}
    else:
        txt += VIGIA_TEXTO_JSON.replace("@V@", j["visita"]).replace("@L@", j["local"])
    return {"systemInstruction": {"parts": [{"text": VIGIA_SISTEMA}]},
            "contents": [{"role": "user", "parts": [{"text": txt}]}],
            "tools": [{"google_search": {}}],
            "generationConfig": gc}


def vigia_leer(datos, j, clave, momento):
    """Respuesta de generateContent → costo, búsquedas y, por equipo, si encontró la lista de inactivos y los hechos."""
    u = datos.get("usageMetadata") or {}
    ent = int(u.get("promptTokenCount") or 0) + int(u.get("toolUsePromptTokenCount") or 0)
    sal = int(u.get("candidatesTokenCount") or 0) + int(u.get("thoughtsTokenCount") or 0)
    pe, ps = vigia_precio(clave, momento)
    out = dict(model_version=_texto(datos.get("modelVersion")), costo_usd=round(ent * pe + sal * ps, 6))
    cand = (datos.get("candidates") or [{}])[0] or {}
    gm = cand.get("groundingMetadata") or {}
    out["busquedas"] = len({_texto(q) for q in (gm.get("webSearchQueries") or []) if _texto(q)})
    partes = ((cand.get("content") or {}).get("parts")) or []
    texto = "".join(p.get("text", "") for p in partes if isinstance(p, dict) and not p.get("thought"))
    obj = _objeto_json(texto)
    equipos, urls = {}, []
    for lado, eq in (("away", j["visita"]), ("home", j["local"])):
        x = (obj or {}).get(lado)
        if not isinstance(x, dict) or DE_OTRAS.get(_texto(x.get("team")).upper(), _texto(x.get("team")).upper()) != eq:
            continue
        jugs = []
        for p in (x.get("players") if isinstance(x.get("players"), list) else [])[:VIGIA_MAX_JUG]:
            if not isinstance(p, dict):
                continue
            h = dict(nombre=_texto(p.get("name"))[:80], posicion=_texto(p.get("position")).upper()[:6],
                     estado_jugador=_texto(p.get("status")).lower(), tipo_fuente=_texto(p.get("source_type")).lower(),
                     url=_texto(p.get("source_url"))[:300], publicada=_texto(p.get("source_published"))[:25],
                     evidencia=_texto(p.get("evidence"))[:200])
            jugs.append(h)
            if h["url"]:
                urls.append(h["url"])
        ib = _e2_bool(x.get("inactives_published"))
        equipos[eq] = dict(inactivos="" if ib is None else int(ib), jugadores=jugs)
    out["equipos"] = equipos
    meta = bool((gm.get("webSearchQueries") or []) or (gm.get("groundingChunks") or []) or gm.get("searchEntryPoint"))
    out["evidencia_busqueda"] = "metadatos" if meta else "enlace" if any(x.startswith(PREFIJO_BUSQUEDA) for x in urls) else "ninguna"
    if obj is None:
        out["estado"], out["detalle"] = "respuesta inválida", ("sin texto" if not texto else "no es JSON: " + texto[:150])
    elif len(equipos) == 2:
        out["estado"], out["detalle"] = "ok", ""
    elif equipos:
        out["estado"], out["detalle"] = "parcial", "respondió un solo equipo válido"
    else:
        out["estado"], out["detalle"] = "respuesta inválida", "JSON sin equipos válidos"
    return out


def vigia_llamar(llave, j, clave, momento, limite):
    """Una consulta del vigía (un juego, un modelo). Un 400 con esquema pasa una vez al pedido sin esquema (no se cobra).
    Nunca lanza excepciones ni registra la llave."""
    import requests
    base = dict(equipos={}, forma="esquema")
    for forma in ("esquema", "texto"):
        t0 = time.time()
        resta = limite - t0
        if resta < 5:
            return {**base, "forma": forma, "estado": "tiempo agotado", "detalle": "sin tiempo para empezar", "latencia_s": 0.0}
        try:
            r = requests.post(f"{GEMINI_URL}/models/{VIGIA_MODELOS[clave]}:generateContent",
                              headers={"x-goog-api-key": llave, "Content-Type": "application/json"},
                              json=vigia_cuerpo(j, momento, forma == "esquema"), timeout=(min(10.0, resta), resta))
        except requests.exceptions.Timeout:
            return {**base, "forma": forma, "estado": "tiempo agotado", "latencia_s": round(time.time() - t0, 2)}
        except Exception as e:  # noqa: BLE001 — solo el tipo: el texto podría traer datos de la conexión
            return {**base, "forma": forma, "estado": "error de red", "detalle": type(e).__name__, "latencia_s": round(time.time() - t0, 2)}
        lat = round(time.time() - t0, 2)
        if r.status_code == 400 and forma == "esquema":
            continue                                     # 400 = pedido rechazado (no se cobra): se prueba sin esquema
        if r.status_code != 200:
            try:
                msg = _texto(((r.json() or {}).get("error") or {}).get("message"))
            except Exception:  # noqa: BLE001
                msg = ""
            return {**base, "forma": forma, "estado": "error HTTP", "http": r.status_code, "detalle": msg[:300], "latencia_s": lat}
        try:
            datos = r.json()
        except ValueError:
            return {**base, "forma": forma, "estado": "respuesta inválida", "http": 200, "detalle": "la respuesta no es JSON", "latencia_s": lat}
        return {**base, **vigia_leer(datos, j, clave, momento), "forma": forma, "http": 200, "latencia_s": lat}
    return {**base, "forma": "texto", "estado": "error HTTP", "http": 400, "detalle": "400 con y sin esquema", "latencia_s": 0.0}


def _fecha_fuente(txt):
    """'YYYY-MM-DDTHH:MM[:SS][Z]' → datetime UTC; 'YYYY-MM-DD' → date; otra cosa → None."""
    t = _texto(txt)
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.\d+)?(Z|[+-]\d{2}:?\d{2})?)?$", t)
    if not m:
        return None
    try:
        if m.group(4) is None:
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        x = dt.datetime.fromisoformat(t.replace("Z", "+00:00").replace(" ", "T"))
        return (x if x.tzinfo else x.replace(tzinfo=dt.timezone.utc)).astimezone(dt.timezone.utc)
    except ValueError:
        return None


def vigia_validar(h, momento):
    """'' si el hecho cumple el registro 55; si no, el motivo."""
    if not h["nombre"]:
        return "sin nombre"
    if h["estado_jugador"] not in VIGIA_ESTADOS:
        return "estado desconocido"
    if h["tipo_fuente"] not in VIGIA_FUENTES:
        return "fuente no oficial"
    if not re.match(r"^https?://\S+$", h["url"]):
        return "sin URL"
    f = _fecha_fuente(h["publicada"])
    if f is None:
        return "sin fecha"
    if isinstance(f, dt.datetime):
        if f > momento + dt.timedelta(minutes=VIGIA_HOLGURA_MIN):
            return "fuente posterior a la consulta"
    elif f > momento.astimezone(dt.timezone.utc).date():
        return "fuente posterior a la consulta"
    return ""


def vigia_datos(max_edad_h=12.0):
    """(snaps 2026, roster 2026) de nflverse; None si no se pueden bajar ni hay copia."""
    import polars as pl
    if "d" in _VIG:
        return _VIG["d"]
    snaps = roster = None
    if bajar(URL_SNAPS.format(TEMPORADA), DATOS / f"snap_counts_{TEMPORADA}.csv", 10_000, max_edad_h):
        try:
            snaps = pl.read_csv(DATOS / f"snap_counts_{TEMPORADA}.csv", infer_schema_length=0)
        except Exception as e:  # noqa: BLE001
            log(f"Vigía: no pude leer los snaps ({type(e).__name__})")
    if bajar(URL_ROSTER.format(TEMPORADA), DATOS / f"roster_{TEMPORADA}.csv", 100_000, max_edad_h):
        try:
            roster = pl.read_csv(DATOS / f"roster_{TEMPORADA}.csv", infer_schema_length=0)
        except Exception as e:  # noqa: BLE001
            log(f"Vigía: no pude leer el roster ({type(e).__name__})")
    _VIG["d"] = (snaps, roster)
    return _VIG["d"]


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


GRUPO_POS = {"T": "OL", "G": "OL", "C": "OL", "OT": "OL", "OG": "OL", "OL": "OL", "LT": "OL", "RT": "OL", "LG": "OL",
             "RG": "OL", "DE": "DL", "DT": "DL", "NT": "DL", "DL": "DL", "EDGE": "DL", "LB": "LB", "ILB": "LB", "OLB": "LB",
             "MLB": "LB", "CB": "DB", "S": "DB", "SS": "DB", "FS": "DB", "DB": "DB", "NB": "DB", "RB": "RB", "HB": "RB",
             "FB": "RB", "WR": "WR", "TE": "TE", "QB": "QB", "K": "K", "P": "P", "LS": "LS"}


def _mismo_grupo(p1, p2):
    """El roster de nflverse usa grupos (OL, DL, DB) y Gemini o los snaps usan posiciones (T, DE, CB): se comparan
    grupos; DL y LB se aceptan entre sí (los «edge» figuran de las dos formas)."""
    a, b = GRUPO_POS.get(_texto(p1).upper(), _texto(p1).upper()), GRUPO_POS.get(_texto(p2).upper(), _texto(p2).upper())
    return a == b or {a, b} == {"DL", "LB"}


class VigiaIndice:
    """Roster y snaps de 2026 listos para cruzar nombres, decidir titulares habituales y verificar quién jugó."""

    def __init__(self, snaps, roster, g26):
        import polars as pl
        self.por_eq, self.pfr_gsis, self.gsis_pfr, self.nombre, self.pos, self.eq_de = {}, {}, {}, {}, {}, {}
        for f in (roster.iter_rows(named=True) if roster is not None else []):
            g = _texto(f.get("gsis_id"))
            if not g:
                continue
            eq, nom = _texto(f.get("team")), _texto(f.get("full_name"))
            self.nombre[g], self.pos[g], self.eq_de[g] = nom, _texto(f.get("position")).upper(), eq
            apel = _texto(f.get("last_name")) or (nom.split()[-1] if nom.split() else "")
            self.por_eq.setdefault(eq, []).append((g, _norm(nom), _norm(apel), self.pos[g]))
            pfr = _texto(f.get("pfr_id"))
            if pfr:
                self.pfr_gsis[pfr], self.gsis_pfr[g] = g, pfr
        self.part, self.pos_pfr, self.nom_pfr, self.jugaron, self.con_snaps = {}, {}, {}, {}, set()
        for f in (snaps.filter(pl.col("game_type") == "REG").iter_rows(named=True) if snaps is not None else []):
            gid, eq, pfr = _texto(f.get("game_id")), _texto(f.get("team")), _texto(f.get("pfr_player_id"))
            if not gid or not eq or not pfr:
                continue
            self.con_snaps.add(gid)
            tot = _f(f.get("offense_snaps")) + _f(f.get("defense_snaps")) + _f(f.get("st_snaps"))
            if tot > 0:
                self.jugaron.setdefault(gid, set()).add(pfr)
            self.part.setdefault(eq, {}).setdefault(pfr, {})[gid] = max(_f(f.get("offense_pct")), _f(f.get("defense_pct")))
            self.pos_pfr[pfr], self.nom_pfr[pfr] = _texto(f.get("position")).upper(), _texto(f.get("player"))
        self.juegos_eq = {}
        for r in g26.sort("inicio").iter_rows(named=True):
            if r.get("inicio") is None:
                continue
            for eq in (r["away_team"], r["home_team"]):
                self.juegos_eq.setdefault(eq, []).append((r["game_id"], r["inicio"]))

    def gsis_por_nombre(self, eq, nombre, pos=""):
        """Nombre → gsis: igual nombre normalizado en el roster del equipo; si no, apellido único (con la misma posición si
        la hay); si no, nombre igual en toda la liga (jugador recién cambiado de equipo). ('', 'sin cruzar') si no se puede."""
        n = _norm(nombre)
        if not n:
            return "", "sin cruzar"
        lista = self.por_eq.get(eq, [])
        c = [g for g, nf, _, _ in lista if nf == n]
        if len(c) > 1 and pos:
            c = [g for g in c if _mismo_grupo(self.pos.get(g, ""), pos)] or c
        if len(c) == 1:
            return c[0], "nombre"
        partes = _texto(nombre).replace(".", " ").split()
        ap = _norm(partes[-1]) if partes else ""
        if ap in ("jr", "sr", "ii", "iii", "iv", "v", "") and len(partes) > 1:
            ap = _norm(partes[-2])
        c = [g for g, _, nl, p in lista if ap and nl == ap and (not pos or _mismo_grupo(p, pos))]
        if len(c) == 1:
            return c[0], "apellido"
        c = [g for e, gl in self.por_eq.items() for g, nf, _, _ in gl if nf == n]
        if len(c) == 1:
            return c[0], "nombre (otro equipo)"
        return "", "sin cruzar"

    def titulares(self, eq, antes):
        """{gsis o 'pfr:ID': dict(part, pos, nombre, pfr)}: participación media (máximo de ataque y defensa) ≥ 50 % en los
        últimos 4 partidos del equipo con snaps antes de 'antes' (0 si no jugó); sin K, P ni LS. None si hay < 2."""
        juegos = [gid for gid, ini in self.juegos_eq.get(eq, []) if ini < antes and gid in self.con_snaps][-4:]
        if len(juegos) < 2:
            return None
        out = {}
        for pfr, partes in self.part.get(eq, {}).items():
            m = sum(partes.get(g, 0.0) for g in juegos) / len(juegos)
            if m < 0.5 or self.pos_pfr.get(pfr) in VIGIA_SIN_TITULAR:
                continue
            g = self.pfr_gsis.get(pfr) or self.gsis_por_nombre(eq, self.nom_pfr.get(pfr, ""), self.pos_pfr.get(pfr, ""))[0]
            out[g or f"pfr:{pfr}"] = dict(part=round(m, 3), pos=self.pos_pfr.get(pfr, ""), nombre=self.nom_pfr.get(pfr, ""), pfr=pfr)
        return out

    def jugo(self, gid, gsis, pfr=""):
        """1 si jugó (algún snap), 0 si no, None si ese juego todavía no tiene snaps o no se puede saber."""
        if gid not in self.con_snaps:
            return None
        pfr = pfr or self.gsis_pfr.get(gsis, "")
        if not pfr:
            return None
        return int(pfr in self.jugaron.get(gid, set()))


def _tit_txt(tit):
    return "" if tit is None else ";".join(f"{g}|{d['pos']}|{d['part']}|{d['pfr']}" for g, d in sorted(tit.items()))


def _tit_leer(txt):
    out = {}
    for p in _texto(txt).split(";"):
        x = p.split("|")
        if len(x) >= 4 and x[0]:
            out[x[0]] = dict(pos=x[1], part=_f(x[2]), pfr=x[3])
    return out


def _anexar_csv(ruta, campos, filas, prefijo):
    SAL.mkdir(parents=True, exist_ok=True)
    if ruta.exists():
        with open(ruta, encoding="utf-8") as fh:
            if fh.readline().strip().split(",") != campos:
                viejo = ruta.with_name(f"{prefijo}_previo_{int(time.time())}.csv")
                ruta.rename(viejo)
                log(f"Vigía: {ruta.name} tenía otras columnas; lo guardé como {viejo.name}")
    nuevo = not ruta.exists()
    with open(ruta, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=campos)
        if nuevo:
            w.writeheader()
        for f in filas:
            w.writerow({k: ("" if f.get(k) is None else f.get(k)) for k in campos})


def _leer_csv(ruta):
    if not ruta.exists():
        return []
    with open(ruta, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def vigia_modelos(estado):
    """Modelos que consultan: el elegido por la regla del piloto, o los dos mientras no haya ganador."""
    el = (estado.get("vigia") or {}).get("elegido")
    return [el["clave"]] if el and el.get("clave") in VIGIA_MODELOS else ["A", "B"]


def vigia_t85(pendientes, filas_proy, ahora, estado, g26):
    """El vigía de una corrida automática T−85 (después de g1). pendientes = [(juego, FuentesQB)]; filas_proy = las filas
    de la proyección de esta corrida (para saber con qué QB proyectó la máquina). Devuelve el resumen para Telegram y la
    hoja, o None. Nunca detiene la corrida."""
    try:
        activo, tope = vigia_cfg()
        if not pendientes or not GEMINI_LLAVE.exists() or not activo:
            return None
        from concurrent.futures import ThreadPoolExecutor, wait
        try:
            vigia_piloto_aplicar(g26, estado, ahora)
        except Exception as e:  # noqa: BLE001
            log(f"Vigía: no pude evaluar el piloto ({type(e).__name__}); sigo con los modelos de antes")
        claves = vigia_modelos(estado)
        juegos = [j for j, _ in pendientes]
        momento = e2_momento(ahora)
        hoy = momento.astimezone(CARACAS).date().isoformat()
        usado = estado.setdefault("vigia_dia", {})
        for k in [k for k in usado if k != hoy]:
            usado.pop(k)
        tareas_v = [(j, c) for j in juegos for c in claves]
        disponibles = max(tope - usado.get(hoy, 0), 0)
        a_consultar, sin_cupo = tareas_v[:disponibles], tareas_v[disponibles:]
        usado[hoy] = usado.get(hoy, 0) + len(a_consultar)
        snaps, roster = vigia_datos()
        ind = VigiaIndice(snaps, roster, g26)
        qb_usado = {}
        for f in filas_proy:
            qb_usado[(f["game_id"], f["local"])] = _texto(f.get("qb_local_id"))
            qb_usado[(f["game_id"], f["visita"])] = _texto(f.get("qb_visita_id"))
        llave = GEMINI_LLAVE.read_text(encoding="utf-8").strip()
        t0 = time.time()
        limite = t0 + VIGIA_PLAZO_S
        res = {}
        if a_consultar:
            ex = ThreadPoolExecutor(max_workers=VIGIA_HILOS)
            futs = {ex.submit(vigia_llamar, llave, j, c, momento, limite): (j, c) for j, c in a_consultar}
            hechos, _ = wait(futs, timeout=max(limite - time.time(), 0) + 1.0)
            for fu, (j, c) in futs.items():
                res[(j["game_id"], c)] = (fu.result() if fu in hechos and fu.exception() is None else
                                          dict(equipos={}, forma="esquema", estado="tiempo agotado", latencia_s=float(VIGIA_PLAZO_S),
                                               detalle="" if fu not in hechos else f"excepción {type(fu.exception()).__name__}"))
            ex.shutdown(wait=False, cancel_futures=True)
        del llave
        for j, c in sin_cupo:
            res[(j["game_id"], c)] = dict(equipos={}, forma="", estado="tope", detalle=f"tope de {tope} consultas del día", latencia_s=0.0)
        filas_c, filas_h = [], []
        resumen = dict(momento=momento, semanas=sorted({j["semana"] for j in juegos}), claves=claves, juegos=[], costo=0.0,
                       consultas={c: [0, 0] for c in claves}, inactivos=[0, 0], inicio=min(j["inicio"] for j in juegos))
        for j in juegos:
            gid = j["game_id"]
            minutos = round((j["inicio"] - momento).total_seconds() / 60, 1)
            valida = int(minutos > 0)
            tit = {eq: ind.titulares(eq, j["inicio"]) for eq in (j["visita"], j["local"])}
            avisos = {j["visita"]: {}, j["local"]: {}}
            inact_eq = {j["visita"]: False, j["local"]: False}
            for c in claves:
                x = res[(gid, c)]
                n_h = n_a = 0
                if x["estado"] != "tope":
                    resumen["consultas"][c][1] += 1
                    resumen["consultas"][c][0] += int(x["estado"] in ("ok", "parcial"))
                resumen["costo"] += float(x.get("costo_usd") or 0)
                for eq in (j["visita"], j["local"]):
                    e = x["equipos"].get(eq)
                    if not e:
                        continue
                    if e.get("inactivos") == 1:
                        inact_eq[eq] = True
                    vistos = set()
                    for h in e["jugadores"]:
                        motivo = vigia_validar(h, momento)
                        g, cruce = ind.gsis_por_nombre(eq, h["nombre"], h["posicion"]) if h["nombre"] else ("", "sin cruzar")
                        tt = (tit.get(eq) or {}).get(g) if g else None
                        es_qb = int(bool(g) and g == qb_usado.get((gid, eq), ""))
                        pos = (tt or {}).get("pos") or ind.pos.get(g, "") or h["posicion"]
                        aviso = int(not motivo and valida == 1 and h["estado_jugador"] in VIGIA_NO_JUEGA and bool(g)
                                    and g not in vistos and ((tt is not None and pos != "QB") or es_qb == 1))
                        if g:
                            vistos.add(g)
                        n_h += 1
                        n_a += aviso
                        filas_h.append(dict(corrida_utc=iso(momento), game_id=gid, semana=j["semana"], modelo_clave=c,
                                            huella=vigia_huella(c), equipo=eq, nombre=h["nombre"], posicion=h["posicion"],
                                            estado_jugador=h["estado_jugador"], tipo_fuente=h["tipo_fuente"], url=h["url"],
                                            publicada=h["publicada"], evidencia=h["evidencia"], valido=int(not motivo),
                                            motivo_invalido=motivo, gsis_id=g, cruce=cruce, titular=int(tt is not None),
                                            part_media="" if tt is None else tt["part"], es_qb_usado=es_qb, aviso=aviso,
                                            minutos_antes=minutos, nombre_roster=ind.nombre.get(g, "") if g else ""))
                        if aviso:
                            a = avisos[eq].setdefault(g, dict(nombre=ind.nombre.get(g) or h["nombre"], pos=pos, qb=es_qb,
                                                              estado=h["estado_jugador"], fuente=h["tipo_fuente"], modelos=[]))
                            if c not in a["modelos"]:
                                a["modelos"].append(c)
                filas_c.append(dict(corrida_utc=iso(momento), game_id=gid, semana=j["semana"], game_type=j.get("game_type", "REG"),
                                    inicio_utc=iso(j["inicio"]), minutos_antes=minutos, valida=valida, modelo_clave=c,
                                    modelo=VIGIA_MODELOS[c], huella=vigia_huella(c), forma=x.get("forma", ""),
                                    model_version=x.get("model_version", ""), estado=x["estado"], http=x.get("http", ""),
                                    latencia_s=x.get("latencia_s", ""), costo_usd=x.get("costo_usd", ""),
                                    busquedas=x.get("busquedas", ""), evidencia_busqueda=x.get("evidencia_busqueda", ""),
                                    inactivos_visita=(x["equipos"].get(j["visita"]) or {}).get("inactivos", ""),
                                    inactivos_local=(x["equipos"].get(j["local"]) or {}).get("inactivos", ""),
                                    titulares_visita=_tit_txt(tit[j["visita"]]), titulares_local=_tit_txt(tit[j["local"]]),
                                    n_hechos=n_h, n_avisos=n_a, detalle=x.get("detalle", "")))
            resumen["inactivos"][0] += sum(inact_eq.values())
            resumen["inactivos"][1] += 2
            resumen["juegos"].append(dict(game_id=gid, visita=j["visita"], local=j["local"], valida=valida, avisos=avisos,
                                          sin_titulares=[eq for eq in (j["visita"], j["local"]) if tit[eq] is None]))
        _anexar_csv(VIGIA_CONSULTAS, CAMPOS_VC, filas_c, "vigia_consultas")
        _anexar_csv(VIGIA_HECHOS, CAMPOS_VH, filas_h, "vigia_hechos")
        n_av = sum(len(v) for jj in resumen["juegos"] for v in jj["avisos"].values())
        log(f"Vigía ({'+'.join(claves)}; " + ", ".join(f"{c} {vigia_huella(c)}" for c in claves) + f"): {len(juegos)} juegos en "
            f"{time.time() - t0:.1f} s · " + " · ".join(f"{VIGIA_NOMBRE[c]} {resumen['consultas'][c][0]}/{resumen['consultas'][c][1]}"
                                                       for c in claves)
            + f" · {len(filas_h)} hechos · {n_av} avisos · USD {resumen['costo']:.4f}")
        return resumen
    except Exception as e:  # noqa: BLE001
        log(f"Vigía: error ({type(e).__name__}: {str(e)[:200]}); la proyección, g1 y e2 no se afectan")
        return None


def texto_vigia(resumen):
    """Mensaje de Telegram del vigía (aparte de la proyección)."""
    piloto = len(resumen["claves"]) > 1
    lin = [f"🔎 VIGÍA T−85 · semana {', '.join(map(str, resumen['semanas']))} · juegos de las {fecha_cc(resumen['inicio'])} (Caracas)"
           + (" · piloto: Flash-Lite y 3.8 Flash" if piloto else f" · {VIGIA_NOMBRE[resumen['claves'][0]]}")]
    sin = []
    for jj in resumen["juegos"]:
        nombre = f"{jj['visita']} @ {jj['local']}"
        partes = []
        for eq in (jj["visita"], jj["local"]):
            av = jj["avisos"][eq]
            qb = [a for a in av.values() if a["qb"]]
            otros = [a for a in av.values() if not a["qb"]]
            marca = lambda a: (" [los dos]" if len(a["modelos"]) > 1 else f" [solo {VIGIA_NOMBRE[a['modelos'][0]]}]") if piloto else ""  # noqa: E731
            for a in qb:
                partes.append(f"⚠️ {eq}: la máquina proyectó con {a['nombre']} y la fuente oficial lo da fuera "
                              f"({ESTADO_ES.get(a['estado'], a['estado'])} · {FUENTE_ES.get(a['fuente'], a['fuente'])}){marca(a)}")
            if otros:
                lista = ", ".join(f"{a['pos']} {a['nombre']} ({ESTADO_ES.get(a['estado'], a['estado'])} · "
                                  f"{FUENTE_ES.get(a['fuente'], a['fuente'])}){marca(a)}" for a in otros)
                partes.append(f"🔎 {eq}: falta{'n' if len(otros) > 1 else ''} {len(otros)} titular{'es' if len(otros) > 1 else ''} "
                              f"que la máquina no conoce: {lista}")
        if not jj["valida"]:
            partes.append(f"{nombre}: consulta después del inicio (no cuenta)")
        if partes:
            lin.append(f"{nombre}:")
            lin += ["  " + p for p in partes]
        else:
            sin.append(nombre)
        if jj["sin_titulares"]:
            lin.append(f"  (sin titulares calculables todavía: {', '.join(jj['sin_titulares'])})")
    if sin:
        lin.append("Sin bajas de titulares: " + ", ".join(sin))
    lin.append(f"Lista oficial de inactivos encontrada en {resumen['inactivos'][0]} de {resumen['inactivos'][1]} equipos · consultas "
               + ", ".join(f"{VIGIA_NOMBRE[c]} {v[0]}/{v[1]}" for c, v in resumen["consultas"].items())
               + f" · USD {resumen['costo']:.3f}".replace(".", ","))
    lin.append("Solo hechos con fuente oficial; el código decide quién es titular (snaps). No cambia la máquina ni las selecciones.")
    return "\n".join(lin)


def vigia_avisos_semana(semana):
    """{game_id: {equipo: [aviso, …]}} de la última corrida del vigía de cada juego de la semana (juntando los modelos)."""
    filas = [f for f in _leer_csv(VIGIA_HECHOS) if f.get("semana") == str(semana)]
    ultima = {}
    for f in filas:
        if f["corrida_utc"] > ultima.get(f["game_id"], ""):
            ultima[f["game_id"]] = f["corrida_utc"]
    out = {}
    for f in filas:
        if f["corrida_utc"] != ultima.get(f["game_id"]) or f.get("aviso") != "1":
            continue
        eq = out.setdefault(f["game_id"], {}).setdefault(f["equipo"], {})
        a = eq.setdefault(f["gsis_id"], dict(nombre=f.get("nombre_roster") or f["nombre"], pos=f["posicion"],
                                             qb=f.get("es_qb_usado") == "1", modelos=[]))
        if f["modelo_clave"] not in a["modelos"]:
            a["modelos"].append(f["modelo_clave"])
    return {g: {e: list(v.values()) for e, v in d.items()} for g, d in out.items()}


def vigia_frase(av):
    """Texto que se agrega a la columna de la máquina (E) cuando el vigía avisó en ese juego."""
    if not av:
        return ""
    partes = []
    for eq, lista in sorted(av.items()):
        qb = [a for a in lista if a["qb"]]
        otros = [a for a in lista if not a["qb"]]
        if qb:
            partes.append(f"la fuente oficial da fuera al QB con que proyectó la máquina ({apodo(eq)}: {qb[0]['nombre']})")
        if otros:
            n = len(otros)
            partes.append(f"a {apodo(eq)} le falta{'n' if n > 1 else ''} {n} titular{'es' if n > 1 else ''} que la máquina no "
                          f"conoce ({', '.join(a['nombre'] for a in otros[:4])}{'…' if n > 4 else ''})")
    return " · 🔎 el vigía: " + "; ".join(partes)


def vigia_verificar(g26, solo_actual=False):
    """Verificación con los snaps (código, sin IA). Devuelve (métricas por (modelo, semana), filas de hechos con 'jugo').
    solo_actual: solo las consultas con la huella actual de cada modelo (v8.3.1: la que usa el piloto)."""
    consultas = [f for f in _leer_csv(VIGIA_CONSULTAS) if f.get("valida") == "1"]
    if solo_actual:
        actual = {c: vigia_huella(c) for c in VIGIA_MODELOS}
        consultas = [f for f in consultas if f.get("huella") == actual.get(f.get("modelo_clave"))]
    hechos = [f for f in _leer_csv(VIGIA_HECHOS) if f.get("minutos_antes") and _f(f.get("minutos_antes")) > 0]
    if not consultas:
        return {}, []
    snaps, roster = vigia_datos()
    ind = VigiaIndice(snaps, roster, g26)
    met = {}

    def m_(c, s):
        return met.setdefault((c, s), dict(consultas=0, fallas=0, hechos=0, verificables=0, correctos=0,
                                           no_jugaron=0, avisados=0, juegos=set(), sin_snaps=set()))
    ult = {}
    for f in consultas:                              # la última consulta de cada juego y modelo (una por corrida T−85)
        k = (f["game_id"], f["modelo_clave"])
        if f["corrida_utc"] > ult.get(k, ""):
            ult[k] = f["corrida_utc"]
    filas_ver = []
    for f in consultas:
        k = (f["game_id"], f["modelo_clave"])
        if f["corrida_utc"] != ult[k] or f["estado"] == "tope":
            continue
        s, c, gid = int(f["semana"]), f["modelo_clave"], f["game_id"]
        m = m_(c, s)
        m["consultas"] += 1
        m["fallas"] += int(f["estado"] not in ("ok", "parcial"))
        m["juegos"].add(gid)
        if gid not in ind.con_snaps:
            m["sin_snaps"].add(gid)
        hs = [h for h in hechos if h["game_id"] == gid and h["modelo_clave"] == c and h["corrida_utc"] == f["corrida_utc"]]
        avisados = {}
        for h in hs:
            if h["valido"] == "1" and h["estado_jugador"] in VIGIA_NO_JUEGA and h["gsis_id"]:
                avisados.setdefault(h["equipo"], set()).add(h["gsis_id"])
        vistos = set()
        for h in hs:
            jugo = None
            if h["gsis_id"]:
                tt = _tit_leer(f["titulares_local"] if h["equipo"] == gid.split("_")[-1] else f["titulares_visita"]).get(h["gsis_id"])
                jugo = ind.jugo(gid, h["gsis_id"], (tt or {}).get("pfr", ""))
            filas_ver.append({**h, "jugo": "" if jugo is None else jugo})
            clave_h = (h["equipo"], h["gsis_id"])
            if (h["valido"] == "1" and h["titular"] == "1" and h["estado_jugador"] in VIGIA_NO_JUEGA and h["gsis_id"]
                    and clave_h not in vistos):
                vistos.add(clave_h)
                m["hechos"] += 1
                if jugo is not None:
                    m["verificables"] += 1
                    m["correctos"] += int(jugo == 0)
        for eq, col in ((gid.split("_")[-2], "titulares_visita"), (gid.split("_")[-1], "titulares_local")):
            if f.get("inactivos_visita" if col == "titulares_visita" else "inactivos_local", "") == "":
                continue                                 # el modelo no respondió por ese equipo
            for g, d in _tit_leer(f[col]).items():
                jugo = ind.jugo(gid, g, d.get("pfr", ""))
                if jugo == 0:
                    m["no_jugaron"] += 1
                    m["avisados"] += int(g in avisados.get(eq, set()))
    for m in met.values():
        m["precision"] = (m["correctos"] / m["verificables"]) if m["verificables"] else None
        m["cobertura"] = (m["avisados"] / m["no_jugaron"]) if m["no_jugaron"] else None
        m["tasa_fallas"] = (m["fallas"] / m["consultas"]) if m["consultas"] else None
    return met, filas_ver


def vigia_piloto(met):
    """Regla del piloto (registro 55, escrita antes). Devuelve dict(estado, semanas, por_modelo, ganador, motivo)."""
    semanas = sorted({s for (c, s) in met if c == "A"} & {s for (c, s) in met if c == "B"})
    if len(semanas) < VIGIA_PILOTO_SEMANAS:
        return dict(estado="en curso", semanas=semanas, por_modelo={}, ganador=None,
                    motivo=f"{len(semanas)} de {VIGIA_PILOTO_SEMANAS} semanas con los dos modelos; el piloto cuenta desde la semana {VIGIA_PILOTO_DESDE}")

    def junta(c, ss):
        t = dict(consultas=0, fallas=0, hechos=0, verificables=0, correctos=0, no_jugaron=0, avisados=0, sin_snaps=0)
        for s in ss:
            m = met.get((c, s))
            if m:
                for k in t:
                    t[k] += len(m[k]) if k == "sin_snaps" else m[k]
        t["precision"] = t["correctos"] / t["verificables"] if t["verificables"] else None
        t["cobertura"] = t["avisados"] / t["no_jugaron"] if t["no_jugaron"] else None
        t["tasa_fallas"] = t["fallas"] / t["consultas"] if t["consultas"] else None
        return t
    k = VIGIA_PILOTO_SEMANAS
    while True:
        ss = semanas[:k]
        pm = {c: junta(c, ss) for c in ("A", "B")}
        if any(pm[c]["sin_snaps"] for c in pm):
            return dict(estado="en curso", semanas=ss, por_modelo=pm, ganador=None, motivo="faltan snaps de nflverse de esas semanas")
        if all(pm[c]["verificables"] >= VIGIA_MIN_HECHOS for c in pm) or k >= VIGIA_PILOTO_MAX:
            break
        if len(semanas) <= k:
            return dict(estado="en curso", semanas=ss, por_modelo=pm, ganador=None,
                        motivo=f"menos de {VIGIA_MIN_HECHOS} hechos verificables: el piloto se alarga una semana")
        k += 1
    eleg = [c for c in ("A", "B") if pm[c]["precision"] is not None and pm[c]["precision"] >= VIGIA_MIN_PRECISION
            and pm[c]["verificables"] >= VIGIA_MIN_HECHOS and (pm[c]["tasa_fallas"] or 0) <= VIGIA_MAX_FALLAS]
    if not eleg:
        return dict(estado="sin ganador", semanas=ss, por_modelo=pm, ganador=None,
                    motivo="ninguno cumple precisión ≥ 90 %, ≥ 10 hechos y ≤ 20 % de fallas: siguen los dos y decide Ozz")
    if len(eleg) == 1:
        return dict(estado="decidido", semanas=ss, por_modelo=pm, ganador=eleg[0], motivo=f"solo {VIGIA_NOMBRE[eleg[0]]} es elegible")
    ca, cb = pm["A"]["cobertura"] or 0.0, pm["B"]["cobertura"] or 0.0
    if abs(ca - cb) < VIGIA_DIF_COBERTURA:
        return dict(estado="decidido", semanas=ss, por_modelo=pm, ganador="A",
                    motivo="los dos elegibles y la cobertura difiere menos de 5 pp: gana el más barato (Flash-Lite)")
    g = "A" if ca > cb else "B"
    return dict(estado="decidido", semanas=ss, por_modelo=pm, ganador=g, motivo=f"los dos elegibles: gana la mayor cobertura ({VIGIA_NOMBRE[g]})")


def vigia_met_piloto(g26):
    """v8.3.1: métricas que entran al piloto = huellas actuales y semanas desde VIGIA_PILOTO_DESDE."""
    met, _ = vigia_verificar(g26, solo_actual=True)
    return {k: m for k, m in met.items() if k[1] >= VIGIA_PILOTO_DESDE}


def vigia_piloto_aplicar(g26, estado, ahora):
    """Si la regla ya da resultado y todavía no se aplicó, lo anota en el estado (una sola vez). Devuelve (piloto, métricas)."""
    v = estado.setdefault("vigia", {})
    met = vigia_met_piloto(g26)
    p = vigia_piloto(met)
    if not v.get("elegido") and not v.get("sin_ganador") and p["estado"] in ("decidido", "sin ganador"):
        resumen_pm = {c: {k: (round(x, 4) if isinstance(x, float) else x) for k, x in d.items()} for c, d in p["por_modelo"].items()}
        reg = dict(fecha=iso(ahora), semanas=p["semanas"], motivo=p["motivo"], por_modelo=resumen_pm)
        if p["ganador"]:
            v["elegido"] = dict(clave=p["ganador"], modelo=VIGIA_MODELOS[p["ganador"]], **reg)
            log(f"Vigía: piloto decidido por la regla → {VIGIA_NOMBRE[p['ganador']]} ({p['motivo']})")
        else:
            v["sin_ganador"] = reg
            log(f"Vigía: piloto sin ganador ({p['motivo']})")
    return p, met


def texto_vigia_piloto(p, estado):
    v = estado.get("vigia") or {}
    if v.get("elegido"):
        e = v["elegido"]
        return f"Piloto del vigía: decidido el {fecha_cc(t_utc(e['fecha']))} → {VIGIA_NOMBRE[e['clave']]} ({e['motivo']})"
    if v.get("sin_ganador"):
        return f"Piloto del vigía: sin ganador ({v['sin_ganador']['motivo']})"
    if p["estado"] == "decidido":
        return f"Piloto del vigía: la regla eligió {VIGIA_NOMBRE[p['ganador']]} ({p['motivo']}); se aplica en la próxima T−85"
    if p["estado"] == "sin ganador":
        return f"Piloto del vigía: sin ganador ({p['motivo']}); se anota en la próxima T−85"
    return f"Piloto del vigía: en curso ({p['motivo']}; semanas {', '.join(map(str, p['semanas'])) or '—'})"


def texto_vigia_estado(ahora, estado):
    """Conteos del vigía para el modo estado (y /estado por Telegram)."""
    activo, tope = vigia_cfg()
    hoy = ahora.astimezone(CARACAS).date().isoformat()
    claves = vigia_modelos(estado)
    cab = (f"Vigía (55): {'activo' if activo else 'APAGADO en semana.ini'} · "
           + (f"piloto {' + '.join(VIGIA_NOMBRE[c] for c in claves)}" if len(claves) > 1 else f"modelo elegido {VIGIA_NOMBRE[claves[0]]}")
           + " · huellas " + ", ".join(f"{c} {vigia_huella(c)}" for c in claves)
           + f" · hoy {estado.get('vigia_dia', {}).get(hoy, 0)}/{tope} consultas")
    cons = [f for f in _leer_csv(VIGIA_CONSULTAS) if f.get("valida") == "1"]
    if not cons:
        return cab + " · todavía sin consultas (empieza en la próxima T−85 automática)"
    hs = [f for f in _leer_csv(VIGIA_HECHOS) if f.get("aviso") == "1"]
    costo = sum(_f(f.get("costo_usd")) for f in _leer_csv(VIGIA_CONSULTAS))
    return (cab + f" · {len({f['game_id'] for f in cons})} juegos consultados · {len(hs)} avisos (sumando modelos) · "
            f"USD {costo:.2f}")


VIGIA_MAX_PRUEBA_DIA = 4                           # consultas reales de prueba por día (aparte; nunca cuentan)


def vigia_prueba_real(g26, ahora, estado):
    """Una consulta REAL por modelo sobre el próximo juego (para ver que Google acepta el pedido de los dos modelos).
    No escribe en los registros del vigía, no cuenta para el piloto ni para nada; tope aparte de 4 por día."""
    import polars as pl
    if not GEMINI_LLAVE.exists():
        return "Sin credenciales/gemini.key: el vigía no puede consultar."
    prox = g26.filter(pl.col("inicio") > ahora).sort("inicio").head(1)
    if prox.height == 0:
        return "No hay juegos por jugar en el calendario."
    r = prox.row(0, named=True)
    j = dict(game_id=r["game_id"], semana=int(r["week"]), game_type=r["game_type"], visita=r["away_team"], local=r["home_team"],
             inicio=r["inicio"])
    hoy = ahora.astimezone(CARACAS).date().isoformat()
    usado = estado.setdefault("vigia_prueba", {})
    for k in [k for k in usado if k != hoy]:
        usado.pop(k)
    if usado.get(hoy, 0) + 2 > VIGIA_MAX_PRUEBA_DIA:
        return f"Tope de pruebas reales del día ({VIGIA_MAX_PRUEBA_DIA} consultas): prueba mañana."
    usado[hoy] = usado.get(hoy, 0) + 2
    momento = e2_momento(ahora)
    llave = GEMINI_LLAVE.read_text(encoding="utf-8").strip()
    snaps, roster = vigia_datos()
    ind = VigiaIndice(snaps, roster, g26)
    tit = {eq: ind.titulares(eq, j["inicio"]) for eq in (j["visita"], j["local"])}
    lin = [f"Prueba REAL del vigía (no cuenta): {j['visita']} @ {j['local']} · {fecha_cc(j['inicio'])} Caracas · "
           f"titulares calculados: {j['visita']} {len(tit[j['visita']] or {})}, {j['local']} {len(tit[j['local']] or {})}"]
    for c in ("A", "B"):
        x = vigia_llamar(llave, j, c, momento, time.time() + VIGIA_PLAZO_S)
        hs = [(eq, h) for eq, e in x.get("equipos", {}).items() for h in e["jugadores"]]
        val = [(eq, h) for eq, h in hs if not vigia_validar(h, momento)]
        cruz = [(eq, h) for eq, h in val if ind.gsis_por_nombre(eq, h["nombre"], h["posicion"])[0]]
        lin.append(f"  {VIGIA_NOMBRE[c]} ({VIGIA_MODELOS[c]}): {x['estado']}" + (f" (HTTP {x['http']})" if x.get("http") not in (None, "", 200) else "")
                   + f" · forma {x.get('forma', '')} · {x.get('latencia_s', 0)} s · USD {float(x.get('costo_usd') or 0):.4f} · "
                   f"{len(hs)} hechos, {len(val)} válidos, {len(cruz)} cruzados con el roster"
                   + (f" · {x.get('detalle')}" if x.get("detalle") else ""))
        for eq, h in hs[:6]:
            lin.append(f"    {eq} {h['posicion']} {h['nombre']} · {h['estado_jugador']} · {h['tipo_fuente']} · {h['publicada']}"
                       + (f" · INVÁLIDO: {vigia_validar(h, momento)}" if vigia_validar(h, momento) else ""))
    del llave
    return "\n".join(lin)


def vigia_autoprueba(g26):
    """Prueba sin consultar a Gemini (la usa el instalador): pedido y esquema de los dos modelos, lectura de una respuesta
    de ejemplo, validación de hechos, titulares con los snaps reales y la regla del piloto con números de ejemplo."""
    ok = []
    j = dict(game_id="2026_06_AAA_BBB", semana=6, game_type="REG", visita="GB", local="CHI",
             inicio=dt.datetime(2026, 10, 18, 17, 0, tzinfo=dt.timezone.utc))
    momento = j["inicio"] - dt.timedelta(minutes=84)
    for c in ("A", "B"):
        cu = vigia_cuerpo(j, momento)
        assert cu["generationConfig"]["thinkingConfig"]["thinkingLevel"] == "medium"
        assert cu["generationConfig"]["responseFormat"]["text"]["schema"]["properties"]["home"]["properties"]["team"]["enum"] == ["CHI"]
        assert "84 minutes before kickoff" in cu["contents"][0]["parts"][0]["text"]
        assert "@V@" not in json.dumps(vigia_cuerpo(j, momento, False))
    ok.append("pedido")
    resp = {"candidates": [{"content": {"parts": [{"text": json.dumps({
        "away": {"team": "GB", "inactives_published": True, "players": [
            {"name": "Elgton Jenkins", "position": "C", "status": "inactive", "source_type": "official_inactive_list",
             "source_url": PREFIJO_BUSQUEDA + "x", "source_published": "2026-10-18T15:30", "evidence": "Inactive"},
            {"name": "Rumor Man", "position": "WR", "status": "out", "source_type": "anonymous", "source_url": "https://x.com",
             "source_published": "2026-10-18", "evidence": "sources say"},
            {"name": "Futuro", "position": "WR", "status": "out", "source_type": "official_injury_report",
             "source_url": "https://x.com", "source_published": "2026-10-19", "evidence": "x"}]},
        "home": {"team": "CHI", "inactives_published": False, "players": []}})}]}}],
        "usageMetadata": {"promptTokenCount": 1000, "candidatesTokenCount": 500, "thoughtsTokenCount": 500}}
    x = vigia_leer(resp, j, "B", momento)
    assert x["estado"] == "ok" and len(x["equipos"]["GB"]["jugadores"]) == 3 and x["equipos"]["CHI"]["inactivos"] == 0
    assert abs(x["costo_usd"] - (1000 * 0.75e-6 + 1000 * 3.75e-6)) < 1e-9
    mot = [vigia_validar(h, momento) for h in x["equipos"]["GB"]["jugadores"]]
    assert mot == ["", "fuente no oficial", "fuente posterior a la consulta"], mot
    ok.append("lectura y validación")
    snaps, roster = vigia_datos()
    ind = VigiaIndice(snaps, roster, g26)
    con = [r for r in g26.sort("inicio").iter_rows(named=True) if r["game_id"] in ind.con_snaps]
    n_tit = []
    if con:
        ult = con[-1]
        for eq in (ult["away_team"], ult["home_team"]):
            t = ind.titulares(eq, ult["inicio"] + dt.timedelta(days=1))
            if t is not None:
                n_tit.append(len(t))
    assert not n_tit or all(10 <= n <= 30 for n in n_tit), n_tit
    ok.append(f"titulares con snaps ({', '.join(map(str, n_tit)) or 'sin snaps todavía'})")
    met = {}
    for c, (ver, cor, noj, av) in (("A", (20, 19, 30, 21)), ("B", (20, 19, 30, 24))):
        for s in (6, 7):
            met[(c, s)] = dict(consultas=16, fallas=0, hechos=ver, verificables=ver, correctos=cor, no_jugaron=noj, avisados=av,
                               juegos=set(), sin_snaps=set())
    p = vigia_piloto(met)
    assert p["ganador"] == "B", p
    ok.append("regla del piloto")
    huellas = ", ".join(f"{c} {vigia_huella(c)}" for c in ("A", "B"))
    return f"vigía OK ({'; '.join(ok)}) · huellas {huellas} · g1 {gemini_huella('g1')} · e2 {e2_huella()}"


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
    # v7 (ajuste 4, descriptivo): piezas del margen en puntos a favor del local, leídas de la fuerza del partido que ya
    # se usó en la simulación (no se simula nada aparte): diferencia de EPA por pase y por corrida (fuerza propia +
    # defensa rival), ajuste por QB y localía, por la respuesta lineal del simulador (RESP de s2-v1)
    a_p, a_r = s2.RESP["a_p"], s2.RESP["a_r"]
    adj, hh = float(F["adj"][i, 0] - F["adj"][i, 1]), float(F["h"][i])
    f["comp_qb_pts"] = round(a_p * adj, 2)
    f["comp_localia_pts"] = round((a_p + a_r) * 2 * hh, 2)
    f["comp_pase_pts"] = round(a_p * (float(F["dp"][i, 0] - F["dp"][i, 1]) - adj - 2 * hh), 2)
    f["comp_corrida_pts"] = round(a_r * (float(F["dr"][i, 0] - F["dr"][i, 1]) - 2 * hh), 2)
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


def consenso_semana(gs, sem, tipo, ahora):
    """QB por consenso para los juegos de una semana (v5). Reemplaza qbl/qbv por el QB elegido, deja el estado del
    consenso en fl/fv y registra cada voto. v6: el agente Gemini ya no se consulta aquí (corre después de enviar la
    proyección); devuelve también las fuentes cargadas, que la sombra usa para leer los nombres."""
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
    anexar_fuentes(votos_log)
    return gs.with_columns(pl.Series("qbl", qbl), pl.Series("qbv", qbv), pl.Series("fl", fl), pl.Series("fv", fv)), fq


def es_dudoso(f):
    return any(str(f.get(k) or "").startswith("dudoso") for k in ("qb_local_fuente", "qb_visita_fuente"))


def correr(tareas_a_correr, g_all, g26, args, ahora, ctx=None, sombra=None):
    """Corrida hacia adelante (la que cuenta para 31A y 29A): juegos que todavía no empiezan.
    sombra: lista donde se anotan los juegos T−85 (con sus fuentes) para el agente Gemini, que corre después."""
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
            gs, fq = consenso_semana(gs, sem, tipo, ahora)
            if tipo == "t85" and sombra is not None:
                sombra += [(dict(game_id=r["game_id"], semana=sem, game_type=r["game_type"], visita=r["away_team"],
                                 local=r["home_team"], inicio=r["inicio"]), fq) for r in gs.iter_rows(named=True)]
            mg, tt, F = simular_semana(ctx, gs, sem, args.n_sims)
            pin = lineas_bot(args.bot_dir, "pinnacle", gs["game_id"].to_list(), ahora, MAX_EDAD_PIN_H)
            bo = lineas_bot(args.bot_dir, "betonlineag", gs["game_id"].to_list(), ahora, MAX_EDAD_BO_H)
            ap = apertura_pin(args.bot_dir, gs["game_id"].to_list(), ahora)          # v7: solo descriptivo
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
                    f.update(bo_cuota_sp_local=b["cuota_sp_local"], bo_cuota_sp_visit=b["cuota_sp_visit"])     # v7
                if gid in ap:
                    f["pin_ap_ts"], f["pin_ap_hcp_local"] = ap[gid]                                           # v7
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
    """Pestaña 'Semana N' completa: una fila fija por juego (por hora de inicio) con la parte simple (A-G) y el detalle
    técnico de v7 (I-AB), el resumen de la semana en palabras y en técnico, y el bloque de equipos. Todo sale del
    registro, la retro y nflverse."""
    import polars as pl
    if hoja is None or semana is None:
        return
    t = pestana(semana)
    asegurar_pestana(hoja, semana)
    jg = g26.filter(pl.col("week") == semana).sort(["inicio", "game_id"])
    claves = [r[0] if r else "" for r in hoja.leer(f"'{t}'!{COL_ID}5:{COL_ID}{4 + JUEGOS_MAX}")]
    while claves and not claves[-1]:
        claves.pop()
    for gid in jg["game_id"].to_list():                 # juegos nuevos al final; nunca se reordena
        if gid not in claves:
            claves.append(gid)
    claves = claves[:JUEGOS_MAX]
    info = {r["game_id"]: r for r in jg.iter_rows(named=True)}
    bloque, eq = filas_equipos(g26, semana)
    ult = ultimas_proyecciones(semana)
    try:
        vig = vigia_avisos_semana(semana)              # v8.3 (55): avisos del vigía en la columna de la máquina
    except Exception as e:  # noqa: BLE001
        log(f"Vigía: no pude leer sus avisos para la hoja ({type(e).__name__})")
        vig = {}
    filas, cierres, filas_info = [], [], []
    for gid in claves:
        g = info.get(gid)
        u = ult.get(gid)
        if g is None:
            filas.append([""] * (NCOL - 1) + [gid]); continue
        loc, vis = g["home_team"], g["away_team"]
        f = favorito_de(g, u)
        filas_info.append((g, f, u))
        simple = [partido_txt(g, eq), cuando_txt(g["inicio"]), favorito_txt(f), seguro_txt(f),
                  maquina_txt(u, f) + vigia_frase(vig.get(gid)), teaser_txt(u), resultado_simple(g, f, u)]
        c = cierre_de(g, u)
        cierres.append(c)
        if not u:
            lin = linea_txt(loc, vis, -g["spread_line"] if g["spread_line"] is not None else None)
            tec = [lin + (" (nflverse)" if lin else "")] + [""] * 11 + columnas_cierre(c) + ["", "", gid]
        else:
            marca = {"nflverse": " (cierre)" if u.get("tipo") == "retro" else " (nflverse)"}.get(u.get("ref_spread"), "")
            tot_c = _num(u.get("nfl_total_line"))
            qb = (nombres_qb.get(u["qb_visita_id"], u["qb_visita_id"]) + " @ " + nombres_qb.get(u["qb_local_id"], u["qb_local_id"]))
            tec = [linea_txt(loc, vis, u["spread_ref"]) + marca, linea_txt(loc, vis, u["spread_modelo"]),
                   dif_txt(loc, vis, u["spread_modelo"], u["spread_ref"]), "" if tot_c is None else f"{tot_c:.1f}",
                   f"{float(u['total']):.1f}", gana_txt(loc, vis, u["p_local"]), gana_txt(loc, vis, u.get("pin_p_ml_local")),
                   celda_senal(u, "ml"), celda_senal(u, "sp"), wong_txt(u), estado_txt(u), porque_txt(u)] + \
                columnas_cierre(c) + [qb, f"{u['tipo']} {fecha_cc(t_utc(u['corrida_utc']), False)}", gid]
        filas.append(simple + [""] + tec)
    n = len(claves)
    if n:
        hoja.escribir(f"'{t}'!A5:{COL_ID}{4 + n}", [["" if x is None else x for x in f_] for f_ in filas])
    ult_col = chr(64 + len(ENCAB_EQUIPOS))
    hoja.escribir(f"'{t}'!A{FILA_EQUIPOS}:{ult_col}{FILA_EQUIPOS + len(bloque) - 1}", bloque)
    nota = (" Semana de repaso: la máquina se corrió después de los partidos." if semana < SEMANA_AUTO
            else " Semana de práctica: todavía no cuenta para la prueba de la máquina." if semana < SEMANA_31A else "")
    nota_tec = (" · semana retrospectiva: proyecciones hechas después de los juegos" if semana < SEMANA_AUTO
                else " · semana informativa, fuera de 31A" if semana < SEMANA_31A else "")
    conf = confiabilidad_txt(confiabilidad_qb(g26, semana))
    tec1 = (f"Detalle técnico · motor s2-v1 en modo registro (sin validar) · actualizado {fecha_cc(ahora)} (Caracas)" + nota_tec)
    hoja.escribir(f"'{t}'!A1:{COL_ID}3", [
        [f"Semana {semana}", f"NFL {TEMPORADA} · actualizado {cuando_txt(ahora)} (hora de Caracas)." + nota] + [""] * 6 + [tec1] + [""] * 19,
        ["Cómo leer", COMO_LEER] + [""] * 6 + [LEYENDA_TEC] + [""] * 19,
        ["Cómo va", resumen_simple(filas_info, jg.height)] + [""] * 6 +
        [resumen_txt(cierres, jg.height) + (" " + conf + "." if conf else "")] + [""] * 19,
    ])


def escribir_semanas(hoja, g26, semanas, nombres_qb, ahora, estado, bot_dir=None):
    """Reescribe las pestañas de esas semanas (de la más vieja a la más nueva, así la más nueva queda primera) y anota
    los resultados ya mostrados; al final (v7) rehace la pestaña del boleto, que queda primera. Devuelve las semanas
    que fallaron (un error en el boleto se anota en el log pero no frena nada)."""
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
    try:
        actualizar_boleto(hoja, g26, bot_dir, ahora)
        log(f"hoja: pestaña {TITULO_BOLETO} actualizada")
    except Exception as e:  # noqa: BLE001
        log(f"Hoja: error al escribir la pestaña {TITULO_BOLETO} ({type(e).__name__}: {str(e)[:300]})")
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
        lin.append("* = consenso de nflverse (no hay Pinnacle de ≤ 3 h). 🔴 fuera: no se usa el modelo (modelo y mercado muy "
                   "distintos, o QB dudoso) · 🟢 señal que cuenta para el registro 29A (ningún dinero por el motor, 31A) · 🔵 pata Wong.")
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
# v8.1 — Verdad del QB por primer dropback (decisión 43) e informe semanal de CLV con autopsia (45, con la fórmula de
# CLV de la decisión 46). Registrados el 7-oct-2026 antes de la primera señal que cuenta (claude/registro_43_46.md y
# contexto del proyecto). Todo es lectura y registro descriptivo: no toca s2-v1, la simulación, el consenso del QB, las
# selecciones de 29A ni la hoja (el informe va por Telegram y a archivos; 38: sin pestaña nueva).
# --------------------------------------------------------------------------------------
INFORMES = SAL / "informes"
N_BOOT = 10_000                    # remuestreos por juego para los intervalos del CLV
SEMILLA_BOOT = 20261007
UMBRAL_AUTOPSIA = 1.0              # 38: |spread del modelo − línea de la señal| ≥ 1,0 pt
MOV_PP = 0.01                      # 45: prueba 1 = la probabilidad sin vig del lado del modelo sube ≥ 1,0 pp
MOV_PTS = 0.5                      # 38 original (se reporta, no decide): la línea se mueve ≥ 0,5 pts hacia el modelo
ESPERA_PBP_H = 48                  # el informe espera la jugada por jugada de todos los juegos hasta 48 h tras el último
N_VEREDICTO = 60                   # 29A: el veredicto pide n ≥ 60 selecciones
COLS_PBP = ["game_id", "play_id", "posteam", "qb_dropback", "passer_player_id", "rusher_player_id", "play_type", "down",
            "epa", "interception", "fumble_lost", "touchdown", "td_team"]
_PBP26 = {}
_VERDAD = {}
_MU = {}


def pbp_temporada(max_edad_h=6.0):
    """Jugada por jugada de la temporada en curso (la misma que baja preparar_contexto), con las columnas que usan la
    verdad del QB y la autopsia. None si no se puede bajar ni hay copia."""
    import polars as pl
    if "x" in _PBP26:
        return _PBP26["x"]
    destino = DATOS / f"pbp_{TEMPORADA}.parquet"
    df = None
    if bajar(URL_PBP.format(TEMPORADA), destino, 500_000, max_edad_h):
        try:
            cols = [c for c in COLS_PBP if c in pl.read_parquet_schema(destino)]
            df = pl.read_parquet(destino, columns=cols)
        except Exception as e:  # noqa: BLE001
            log(f"AVISO: no pude leer {destino.name} ({type(e).__name__})")
    _PBP26["x"] = df
    return df


def verdad_qb(pbp=None):
    """43: el QB que jugó = el jugador del primer dropback del equipo (qb_dropback = 1) en la jugada por jugada de
    nflverse que figure como QB en el roster 2026 (passer_player_id; en un scramble, rusher_player_id). Si el roster no
    está, el del primer dropback. {(game_id, equipo): gsis} solo para los juegos que ya están en la jugada por jugada."""
    import polars as pl
    if "v" in _VERDAD:
        return _VERDAD["v"]
    pbp = pbp if pbp is not None else pbp_temporada()
    out = {}
    if pbp is not None and pbp.height and all(c in pbp.columns for c in ("qb_dropback", "passer_player_id", "rusher_player_id")):
        ro = leer_roster()
        qbs = set(ro["gsis_id"].drop_nulls().to_list()) if ro is not None else set()
        d = (pbp.filter((pl.col("qb_dropback") == 1) & pl.col("posteam").is_not_null())
             .with_columns(pl.coalesce([pl.col("passer_player_id"), pl.col("rusher_player_id")]).alias("qb"))
             .filter(pl.col("qb").is_not_null())
             .sort(["game_id", "play_id"]))
        primero = {}
        for gid, eq, qb in d.select(["game_id", "posteam", "qb"]).iter_rows():
            primero.setdefault((gid, eq), qb)
            if (gid, eq) not in out and (not qbs or qb in qbs):
                out[(gid, eq)] = qb
        for k, qb in primero.items():                   # equipo sin un QB del roster en sus dropbacks (raro)
            out.setdefault(k, qb)
    _VERDAD["v"] = out
    return out


def _bootstrap(valores, grupos, semilla):
    """Media de las selecciones e intervalos por remuestreo de juegos (no de selecciones: ML y spread del mismo juego
    están ligados). (media, IC 95 % bajo, IC 95 % alto, límite inferior unilateral 95 %)."""
    import numpy as np
    v = np.asarray(valores, dtype=float)
    if len(v) == 0:
        return None
    g = np.asarray(grupos)
    unicos = list(dict.fromkeys(g.tolist()))
    suma = np.array([v[g == u].sum() for u in unicos])
    cuenta = np.array([(g == u).sum() for u in unicos])
    rng = np.random.default_rng(semilla)
    idx = rng.integers(0, len(unicos), size=(N_BOOT, len(unicos)))
    medias = suma[idx].sum(axis=1) / cuenta[idx].sum(axis=1)
    return (float(v.mean()), float(np.percentile(medias, 2.5)), float(np.percentile(medias, 97.5)),
            float(np.percentile(medias, 5)))


def mu_de_ml(p_local):
    """Margen esperado del local que reproduce la probabilidad sin vig del ML con la distribución del margen de la sección
    3 (resultados 2012-2025 con spread de cierre cercano; sin anclar). Solo para reportar el movimiento del μ (45)."""
    import numpy as np
    if p_local is None:
        return None
    if "tabla" not in _MU:
        sl, res = margenes_historicos()
        grid = np.arange(-24.0, 24.01, 0.25)
        pw = []
        for mu in grid:
            w = NUCLEO_PTS
            while True:
                m = np.abs(sl - mu) <= w + 1e-9
                if m.sum() >= NUCLEO_MIN_N or w >= NUCLEO_MAX_PTS:
                    break
                w += 0.5
            d = res[m] if m.sum() else np.array([mu])
            pw.append(float((d > 0).mean() + 0.5 * (d == 0).mean()))
        _MU["tabla"] = (grid, np.maximum.accumulate(np.array(pw)))
    grid, pw = _MU["tabla"]
    return float(np.interp(p_local, pw, grid))


def _p_ml_lado(p_local, lado):
    return None if p_local is None else (p_local if lado == "local" else 1.0 - p_local)


def p_cubre_sin_vig(foto, h_local, lado):
    """P(el lado cubre el hándicap h_local del local | sin push) según una foto de Pinnacle: con el mismo número, su
    probabilidad sin vig (método de potencia); con otro número, la distribución del margen de la sección 3 anclada a esa
    foto (clase Margen, la del Boleto)."""
    if not foto:
        return None
    hc, sl, sv = foto.get("hcp_local"), foto.get("cuota_sp_local"), foto.get("cuota_sp_visit")
    if hc is None or sl is None or sv is None or h_local is None:
        return None
    p_ref = sin_vig_potencia(sl, sv)
    if p_ref is None:
        return None
    if abs(float(hc) - float(h_local)) < 1e-9:
        p_loc = p_ref
    else:
        pw, pp = Margen(hc, p_ref).local(float(h_local))
        p_loc = pw / max(1.0 - pp, 1e-9)
    return p_loc if lado == "local" else 1.0 - p_loc


def senal_que_cuenta(semana):
    """{game_id: fila del registro}: la señal que cuenta para 29A y 31A = la última corrida automática (T−85, sábado o
    miércoles) guardada antes del inicio del juego; las corridas manuales o por Telegram no cuentan (37)."""
    import polars as pl
    out = {}
    for r in leer_registro().filter(pl.col("semana") == str(semana)).iter_rows(named=True):
        if r.get("tipo") not in TIPOS_QUE_CUENTAN:
            continue
        t, ini = t_utc(r.get("corrida_utc")), t_utc(r.get("inicio_utc"))
        if t is None or ini is None or t >= ini:
            continue
        if r["game_id"] not in out or t > t_utc(out[r["game_id"]]["corrida_utc"]):
            out[r["game_id"]] = r
    return out


def _stats_juego(pbp, gid, eq):
    """EPA por pase y por corrida del ataque de eq (mismo filtro que s2-v1: pases y corridas con down y EPA), pérdidas
    de balón y TD de defensa o de equipos especiales (definición de H24)."""
    import polars as pl
    q = pbp.filter(pl.col("game_id") == gid)
    sc = q.filter(pl.col("play_type").is_in(["pass", "run"]) & pl.col("down").is_not_null() & pl.col("epa").is_not_null()
                  & (pl.col("posteam") == eq))
    ep = sc.filter(pl.col("play_type") == "pass")["epa"]
    er = sc.filter(pl.col("play_type") == "run")["epa"]
    perd = q.filter((pl.col("posteam") == eq) & ((pl.col("interception") == 1) | (pl.col("fumble_lost") == 1))).height
    tdx = q.filter((pl.col("touchdown") == 1) & (pl.col("td_team") == eq)
                   & ((pl.col("posteam") != eq) | (pl.col("play_type") == "kickoff"))).height
    return (float(ep.mean()) if ep.len() else None, float(er.mean()) if er.len() else None, perd, tdx)


def _pct(x, signo=True):
    if x is None:
        return "—"
    return (f"{100 * x:+.1f} %" if signo else f"{100 * x:.1f} %").replace(".", ",")


def _num_txt(x, signo=True, dec=1):
    if x is None:
        return "—"
    return (f"{x:+.{dec}f}" if signo else f"{x:.{dec}f}").replace(".", ",")


def datos_semana(g26, semana, bot_dir):
    """Juegos de la semana (nflverse), la señal que cuenta de cada uno y el cierre de Pinnacle del bot."""
    import polars as pl
    info = {r["game_id"]: r for r in g26.filter(pl.col("week") == semana).iter_rows(named=True)}
    inicios = {gid: r["inicio"] for gid, r in info.items() if r.get("inicio") is not None}
    return info, senal_que_cuenta(semana), cierre_pin(bot_dir, inicios)


def piso_semana(senal, cierre):
    """52: «un lado cualquiera». CLV sin vig (46) de TODOS los lados de la semana con la señal que cuenta, Pinnacle de ≤ 3 h
    en la señal y cierre del bot, estén o no excluidos por el filtro, el sesgo o el QB dudoso. Tipo de lado: no favorito si
    su P(moneyline, Pinnacle sin vig en la señal) < 0,5; si no, favorito (vale para los dos mercados). Spread: P(cubrir la
    línea de la señal), con el mismo cálculo de 46. Devuelve ({(mercado, tipo): media}, {(game_id, lado): tipo},
    {(mercado, tipo): n})."""
    sumas, tipo = {}, {}
    for gid, r in senal.items():
        c = cierre.get(gid)
        pml = _num(r.get("pin_p_ml_local"))
        if pml is None or not c:
            continue
        p_cie_ml = (sin_vig_potencia(c["ml_local"], c["ml_visit"]) if c.get("ml_local") is not None
                    and c.get("ml_visit") is not None else None)
        h, qs = _num(r.get("pin_hcp_local")), _num(r.get("pin_p_sp_local"))
        for lado in ("local", "visita"):
            p_l = pml if lado == "local" else 1.0 - pml
            t = "no favorito" if p_l < 0.5 else "favorito"
            tipo[(gid, lado)] = t
            q_cie = _p_ml_lado(p_cie_ml, lado)
            if p_l > 0 and q_cie is not None:
                s = sumas.setdefault(("ML", t), [0.0, 0])
                s[0] += q_cie / p_l - 1.0
                s[1] += 1
            if h is not None and qs is not None:
                q_sig = qs if lado == "local" else 1.0 - qs
                q_c = p_cubre_sin_vig(c, h, lado)
                if q_sig > 0 and q_c is not None:
                    s = sumas.setdefault(("SP", t), [0.0, 0])
                    s[0] += q_c / q_sig - 1.0
                    s[1] += 1
    return {k: v[0] / v[1] for k, v in sumas.items() if v[1]}, tipo, {k: v[1] for k, v in sumas.items()}


def clv_selecciones(g26, semana, bot_dir, datos=None):
    """CLV de cada selección de 29A de la semana con la señal que cuenta. v8.3 (52): decide el EXCESO = CLV sin vig − el
    piso de su semana, mercado y tipo de lado; se reportan el CLV sin vig sin restar (46), el CLV con el precio de
    Pinnacle de la señal y con el precio de BetOnline."""
    info, senal, cierre = datos or datos_semana(g26, semana, bot_dir)
    pisos, tipos, _ = piso_semana(senal, cierre)
    cuenta_31a = semana >= SEMANA_31A
    sels = []
    for gid, r in senal.items():
        g = info.get(gid) or {}
        c = cierre.get(gid)
        res = _num(g.get("result"))
        for mercado in ("ml", "sp"):
            lado = r.get("sel_ml") if mercado == "ml" else r.get("sel_sp")
            if lado not in ("local", "visita"):
                continue
            eq = r["local"] if lado == "local" else r["visita"]
            f = dict(semana=semana, game_id=gid, juego=f"{r['visita']} @ {r['local']}", corrida=f"{r['tipo']} {r['corrida_utc']}",
                     mercado=mercado.upper(), lado=lado, equipo=eq, estado=r.get("sel_estado") or "",
                     cuenta=int((r.get("sel_estado") == "candidata") and cuenta_31a))
            if mercado == "ml":
                q_sig = _p_ml_lado(_num(r.get("pin_p_ml_local")), lado)
                q_cie = _p_ml_lado(sin_vig_potencia(c["ml_local"], c["ml_visit"]) if c and c.get("ml_local") is not None
                                   and c.get("ml_visit") is not None else None, lado)
                cuota_pin = _num(r.get("pin_ml_local") if lado == "local" else r.get("pin_ml_visit"))
                cuota_bo = _num(r.get("bo_ml_local") if lado == "local" else r.get("bo_ml_visit"))
                q_bo = q_cie
                f["precio_senal"] = f"{eq} ML {cuota_pin:+.0f}" if cuota_pin is not None else ""
                gano = None if res is None or res == 0 else ((res > 0) == (lado == "local"))
            else:
                h = _num(r.get("pin_hcp_local"))
                q_sig = _num(r.get("pin_p_sp_local"))
                q_sig = None if q_sig is None else (q_sig if lado == "local" else 1.0 - q_sig)
                q_cie = p_cubre_sin_vig(c, h, lado)
                cuota_pin = _num(r.get("pin_cuota_sp_local") if lado == "local" else r.get("pin_cuota_sp_visit"))
                cuota_bo = _num(r.get("bo_cuota_sp_local") if lado == "local" else r.get("bo_cuota_sp_visit"))
                q_bo = p_cubre_sin_vig(c, _num(r.get("bo_hcp_local")), lado)
                hl = None if h is None else (h if lado == "local" else -h)
                f["precio_senal"] = (f"{eq} {hl:+.1f} ({cuota_pin:+.0f})" if hl is not None and cuota_pin is not None else "")
                if res is None or h is None:
                    gano = None
                else:
                    x = res + h if lado == "local" else -(res + h)
                    gano = None if abs(x) < 1e-9 else x > 0
            f["linea_cierre"] = "" if not c else f"{c.get('hcp_local')} · ML {c.get('ml_local')}/{c.get('ml_visit')} · {c.get('min_antes')} min antes"
            f["p_senal"] = q_sig
            f["p_cierre"] = q_cie
            f["clv_sin_vig"] = None if q_sig in (None, 0) or q_cie is None else q_cie / q_sig - 1.0
            f["tipo_lado"] = tipos.get((gid, lado), "")                                          # v8.3 (52)
            f["piso"] = pisos.get((f["mercado"], f["tipo_lado"])) if f["tipo_lado"] else None
            f["exceso"] = None if f["clv_sin_vig"] is None or f["piso"] is None else f["clv_sin_vig"] - f["piso"]
            f["clv_precio_pinnacle"] = None if q_cie is None or cuota_pin is None else q_cie * decimal(cuota_pin) - 1.0
            f["clv_precio_betonline"] = None if q_bo is None or cuota_bo is None else q_bo * decimal(cuota_bo) - 1.0
            f["resultado"] = "" if res is None else ("push" if gano is None else ("ganó" if gano else "perdió"))
            sels.append(f)
    return sels


def informe_semana(g26, semana, bot_dir, ahora):
    """Informe semanal (45): CLV de las selecciones de 29A con la señal que cuenta y autopsia de cada juego (38, prueba 1
    en probabilidad sin vig). Devuelve (texto para Telegram, texto completo, filas de selecciones, filas de autopsia)."""
    datos = datos_semana(g26, semana, bot_dir)
    info, senal, cierre = datos
    pbp = pbp_temporada()
    en_pbp = set(pbp["game_id"].unique().to_list()) if pbp is not None and pbp.height else set()
    cuenta_31a = semana >= SEMANA_31A
    sels = clv_selecciones(g26, semana, bot_dir, datos)

    def bloque(filas, semilla):
        val = [x for x in filas if x["clv_sin_vig"] is not None]
        b = _bootstrap([x["clv_sin_vig"] for x in val], [x["game_id"] for x in val], semilla)
        vx = [x for x in val if x.get("exceso") is not None]                          # v8.3 (52): decide el exceso
        bx = _bootstrap([x["exceso"] for x in vx], [x["game_id"] for x in vx], semilla)
        pin_ = [x["clv_precio_pinnacle"] for x in val if x["clv_precio_pinnacle"] is not None]
        bo_ = [x["clv_precio_betonline"] for x in val if x["clv_precio_betonline"] is not None]
        ac = [x for x in val if x["resultado"] in ("ganó", "perdió")]
        nf = [x for x in val if x.get("mercado") == "ML"]
        return dict(n=len(val), juegos=len({x["game_id"] for x in val}), sin_cierre=len(filas) - len(val), boot=b,
                    n_exc=len(vx), boot_exc=bx,
                    no_fav_ml=(sum(1 for x in nf if x.get("tipo_lado") == "no favorito") / len(nf)) if nf else None,
                    pin=(sum(pin_) / len(pin_)) if pin_ else None, bo=(sum(bo_) / len(bo_)) if bo_ else None,
                    aciertos=sum(1 for x in ac if x["resultado"] == "ganó"), n_res=len(ac),
                    esperado=sum(x["p_cierre"] for x in ac))

    candidatas = [x for x in sels if x["estado"] == "candidata"]
    excluidas = [x for x in sels if x["estado"] != "candidata"]
    b_sem = bloque(candidatas, SEMILLA_BOOT + semana)
    b_exc = bloque(excluidas, SEMILLA_BOOT + 100 + semana)
    b_acu = None
    if cuenta_31a:
        acu = list(candidatas)
        for s_ in range(SEMANA_31A, semana):
            acu += [x for x in clv_selecciones(g26, s_, bot_dir) if x["estado"] == "candidata"]
        b_acu = bloque(acu, SEMILLA_BOOT + 1000 + semana)

    # ---- Autopsia (38, con la prueba 1 de 45) ----
    auto = []
    for gid, r in senal.items():
        g = info.get(gid) or {}
        h, sm = _num(r.get("spread_ref")), _num(r.get("spread_modelo"))
        res = _num(g.get("result"))
        if h is None or sm is None or abs(h - sm) < UMBRAL_AUTOPSIA:
            continue
        lado = "local" if h - sm > 0 else "visita"
        eq_m = r["local"] if lado == "local" else r["visita"]
        a = dict(semana=semana, game_id=gid, juego=f"{r['visita']} @ {r['local']}", lado_modelo=eq_m,
                 dif_pts=round(abs(h - sm), 2), linea_senal=h, ref=r.get("ref_spread") or "",
                 seleccion=r.get("sel_estado") or "sin selección")
        c = cierre.get(gid)
        # prueba 1 (45): probabilidad sin vig del lado del modelo para cubrir la línea de la señal, señal → cierre
        q_sig = _num(r.get("pin_p_sp_local")) if r.get("ref_spread") == "pinnacle" else None
        q_sig = None if q_sig is None else (q_sig if lado == "local" else 1.0 - q_sig)
        q_cie = p_cubre_sin_vig(c, h, lado) if q_sig is not None else None
        a["mov_pp"] = None if q_sig is None or q_cie is None else round(100 * (q_cie - q_sig), 2)
        a["prueba1"] = None if a["mov_pp"] is None else a["mov_pp"] >= 100 * MOV_PP - 1e-9
        # se reportan: movimiento en puntos (38 original) y del μ de Pinnacle
        hc = _num(c.get("hcp_local")) if c else None
        a["mov_pts"] = None if hc is None or r.get("ref_spread") != "pinnacle" else round((h - hc) if lado == "local" else (hc - h), 2)
        mu_s = mu_de_ml(_num(r.get("pin_p_ml_local")))
        mu_c = mu_de_ml(sin_vig_potencia(c["ml_local"], c["ml_visit"]) if c and c.get("ml_local") is not None
                        and c.get("ml_visit") is not None else None)
        a["mov_mu"] = None if mu_s is None or mu_c is None else round((mu_c - mu_s) if lado == "local" else (mu_s - mu_c), 2)
        if res is None:
            a["caja"] = "sin resultado"
            auto.append(a)
            continue
        x = res + h
        cubre = None if abs(x) < 1e-9 else ("local" if x > 0 else "visita")
        a["resultado"] = resultado_txt(g)
        # prueba 2: la pieza más grande del margen del modelo contra lo que pasó en la cancha
        piezas = {k: _num(r.get(f"comp_{k}_pts")) for k in ("pase", "corrida", "qb")}
        piezas = {k: v for k, v in piezas.items() if v is not None}
        a["prueba2"] = None
        if piezas and gid in en_pbp:
            k = max(piezas, key=lambda z: abs(piezas[z]))
            sl_, sv_ = _stats_juego(pbp, gid, r["local"]), _stats_juego(pbp, gid, r["visita"])
            i = 1 if k == "corrida" else 0
            if sl_[i] is not None and sv_[i] is not None:
                real = sl_[i] - sv_[i]
                a["pieza"] = f"{k} {piezas[k]:+.1f}"
                a["epa_real"] = round(real, 3)
                a["prueba2"] = (real > 0) == (piezas[k] > 0)
        # prueba 3: suerte del lado que cubrió (balones por 2+ o TD de defensa o de equipos especiales; H24)
        a["prueba3"] = None
        if cubre and gid in en_pbp:
            eq_c = r["local"] if cubre == "local" else r["visita"]
            eq_o = r["visita"] if cubre == "local" else r["local"]
            sc, so = _stats_juego(pbp, gid, eq_c), _stats_juego(pbp, gid, eq_o)
            a["balones_lado_que_cubrio"] = so[2] - sc[2]
            a["td_def_st_lado_que_cubrio"] = sc[3]
            a["prueba3"] = (so[2] - sc[2] >= 2) or sc[3] > 0
        if cubre is None:
            a["caja"] = "push"
        elif cubre == lado:
            a["caja"] = ("acertó con información" if a["prueba1"] else
                         "acertó por suerte" if a["prueba3"] else "acertó sin explicación clara")
        else:
            a["caja"] = "falló" + (" (el otro lado tuvo suerte)" if a["prueba3"] else "")
        auto.append(a)

    # ---- textos ----
    falta_pbp = sorted(gid for gid in senal if info.get(gid, {}).get("result") is not None and gid not in en_pbp)
    def linea_bloque(nombre, b):
        if not b or not b["boot"]:
            return f"{nombre}: sin selecciones con cierre."
        m, lo, hi, lo1 = b["boot"]
        exc = ""
        if b.get("boot_exc"):
            mx, lox, hix, lo1x = b["boot_exc"]
            exc = (f" · EXCESO sobre un lado cualquiera del mismo tipo (decide 29A, 52) {_pct(mx)} (IC 95 % {_pct(lox)} a "
                   f"{_pct(hix)}; límite inferior unilateral {_pct(lo1x)}; n {b['n_exc']})")
        return (f"{nombre}: {b['n']} selecciones en {b['juegos']} juegos" + exc + f" · CLV sin vig sin restar {_pct(m)} "
                f"(IC 95 % {_pct(lo)} a {_pct(hi)}; límite inferior unilateral {_pct(lo1)}) · con el precio de Pinnacle "
                f"{_pct(b['pin'])} · con el de BetOnline {_pct(b['bo'])}"
                + (f" · no favoritos en moneyline {_pct(b['no_fav_ml'], False)}" if b.get("no_fav_ml") is not None else "")
                + (f" · aciertos {b['aciertos']} de {b['n_res']} (el cierre esperaba {b['esperado']:.1f})".replace(".", ",") if b["n_res"] else "")
                + (f" · {b['sin_cierre']} sin cierre del bot" if b["sin_cierre"] else ""))
    cajas = {}
    for a in auto:
        cajas[a["caja"]] = cajas.get(a["caja"], 0) + 1
    p1 = [a for a in auto if a.get("prueba1") is not None]
    p2 = [a for a in auto if a.get("prueba2") is not None]
    titulo = (f"INFORME SEMANAL · semana {semana} · motor s2-v1 en modo registro (sin dinero)"
              + ("" if cuenta_31a else " · semana informativa: NO cuenta para 29A ni 31A"))
    tel = [titulo,
           linea_bloque("Selecciones que cuentan (29A)" if cuenta_31a else "Selecciones (no cuentan)", b_sem)]
    if b_acu:
        faltan = max(N_VEREDICTO - b_acu["n_exc"], 0)
        tel.append(linea_bloque(f"Acumulado desde la semana {SEMANA_31A}", b_acu)
                   + (f" · faltan {faltan} para poder dar veredicto" if faltan else " · ya hay n para el veredicto (se da al final de la temporada)"))
    tel.append(f"Autopsia ({len(auto)} juegos donde el modelo difería ≥ {UMBRAL_AUTOPSIA:.0f} pt de la línea de la señal): "
               + " · ".join(f"{k} {v}" for k, v in sorted(cajas.items(), key=lambda kv: -kv[1]))
               + (f" · prueba 1 (el cierre se movió ≥ 1 pp hacia el modelo): {sum(a['prueba1'] for a in p1)} de {len(p1)}" if p1 else "")
               + (f" · pasó lo que el modelo esperaba: {sum(a['prueba2'] for a in p2)} de {len(p2)}" if p2 else ""))
    if falta_pbp:
        tel.append(f"Aviso: {len(falta_pbp)} juegos todavía sin jugada por jugada en nflverse (la autopsia queda parcial).")
    # ---- v8.3 (50): juegos «Fuera» ----
    try:
        fu_sem, fu_txt_tel, fu_txt = seccion_fuera(g26, semana, bot_dir, datos)
    except Exception as e:  # noqa: BLE001
        fu_sem, fu_txt_tel, fu_txt = [], f"Fuera (50): no se pudo armar ({type(e).__name__}).", []
    tel.append(fu_txt_tel)
    # ---- v8.3 (55): verificación del vigía ----
    try:
        vg_tel, vg_txt, vg_filas = seccion_vigia(g26)
    except Exception as e:  # noqa: BLE001
        vg_tel, vg_txt, vg_filas = f"Vigía (55): no se pudo verificar ({type(e).__name__}).", [], []
    if vg_tel:
        tel.append(vg_tel)
    tel.append("Exceso = CLV sin vig de la selección menos el CLV sin vig medio de los lados del mismo tipo (no favorito o "
               "favorito), mercado y semana (decide 29A, decisión 52). CLV sin vig = cuánto se movió la probabilidad justa de "
               "Pinnacle hacia el lado elegido, de la señal al cierre (46). Descriptivo: el veredicto se da al final de la "
               "temporada con n ≥ 60 y solo si 31A pasa.")
    pisos, _, n_pisos = piso_semana(senal, cierre)
    completo = list(tel) + ["", "Excluidas (se registran, no cuentan): " + linea_bloque("excluidas", b_exc),
                            "Piso de la semana (52; todos los lados con Pinnacle en la señal y al cierre): "
                            + (" · ".join(f"{m} {t} {_pct(pisos[(m, t)])} (n {n_pisos[(m, t)]})"
                                          for m in ("ML", "SP") for t in ("no favorito", "favorito") if (m, t) in pisos) or "sin datos"),
                            "", "SELECCIONES (señal → cierre de Pinnacle, probabilidades sin vig)"]
    for x in sels:
        completo.append(f"  {x['juego']} · {x['mercado']} {x['equipo']} ({x.get('tipo_lado') or '—'}) · {x['estado']} · {x['precio_senal']} · "
                        f"P señal {_pct(x['p_senal'], False)} → cierre {_pct(x['p_cierre'], False)} · CLV sin vig {_pct(x['clv_sin_vig'])}"
                        f" · piso {_pct(x.get('piso'))} · exceso {_pct(x.get('exceso'))}"
                        f" · precio Pinnacle {_pct(x['clv_precio_pinnacle'])} · BetOnline {_pct(x['clv_precio_betonline'])} · {x['resultado'] or 'sin resultado'}")
    completo += ["", "AUTOPSIA (lado del modelo · prueba 1 en pp · se reportan: puntos y μ · prueba 2 · prueba 3 · caja)"]
    for a in auto:
        sino = lambda v: "—" if v is None else ("sí" if v else "no")  # noqa: E731
        completo.append(f"  {a['juego']} · modelo con {a['lado_modelo']} (difiere {_num_txt(a['dif_pts'], False)} pts) · "
                        f"prueba 1: {_num_txt(a.get('mov_pp'))} pp ({sino(a.get('prueba1'))}) · línea {_num_txt(a.get('mov_pts'))} pts"
                        f" · μ {_num_txt(a.get('mov_mu'))} · prueba 2: {a.get('pieza', '—')} contra EPA real {_num_txt(a.get('epa_real'), True, 3)}"
                        f" ({sino(a.get('prueba2'))}) · prueba 3 suerte: {sino(a.get('prueba3'))} · {a['caja']}")
    if falta_pbp:
        completo.append("Sin jugada por jugada todavía: " + ", ".join(falta_pbp))
    completo += [""] + fu_txt + [""] + vg_txt
    completo.append(f"Generado {iso(ahora)} · {VERSION_SEMANA}")
    return "\n".join(tel), "\n".join(completo), sels, auto, {"fuera": fu_sem, "vigia": vg_filas}


def _boot_media(valores, semilla):
    """Media e IC 95 % por remuestreo de juegos (un valor por juego)."""
    import numpy as np
    v = np.asarray(valores, dtype=float)
    if len(v) == 0:
        return None
    rng = np.random.default_rng(semilla)
    m = v[rng.integers(0, len(v), size=(N_BOOT, len(v)))].mean(axis=1)
    return float(v.mean()), float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def fuera_juegos(g26, semana, bot_dir, datos=None):
    """50 (solo registro): los juegos cuya proyección que cuenta quedó «Fuera». Por juego: motivo; spread (señal, modelo,
    cierre de Pinnacle a T−10 o, si falta, nflverse; error del modelo y del cierre; lado del modelo y si cubrió el cierre)
    y total (modelo, consenso de la señal y del cierre de nflverse, errores, lado y si acertó); cambio de QB (primer
    dropback, 43, distinto del de su juego anterior de 2026)."""
    info, senal, cierre = datos or datos_semana(g26, semana, bot_dir)
    verdad = verdad_qb()
    previo = {}
    for r in g26.sort("inicio").iter_rows(named=True):
        if r.get("inicio") is None:
            continue
        for eq in (r["away_team"], r["home_team"]):
            previo.setdefault(eq, []).append((r["inicio"], r["game_id"]))
    out = []
    for gid, r in sorted(senal.items()):
        if not fuera(r):
            continue
        g = info.get(gid) or {}
        mot = [m for m, si in (("spread", r.get("marcado_spread") in (1, "1")), ("total", r.get("marcado_total") in (1, "1")),
                               ("QB dudoso", es_dudoso(r))) if si]
        d = dict(semana=semana, game_id=gid, juego=f"{r['visita']} @ {r['local']}", motivo=" + ".join(mot),
                 resultado=resultado_txt(g))
        res, h_sen, sm = _num(g.get("result")), _num(r.get("spread_ref")), _num(r.get("spread_modelo"))
        c = cierre.get(gid)
        hc, ref_c = (_num(c.get("hcp_local")) if c else None), "pinnacle"
        if hc is None and _num(g.get("spread_line")) is not None:
            hc, ref_c = -_num(g.get("spread_line")), "nflverse"
        if "spread" in mot or "QB dudoso" in mot:
            d.update(linea_senal=h_sen, ref_senal=r.get("ref_spread") or "", linea_modelo=sm, linea_cierre=hc,
                     ref_cierre=ref_c if hc is not None else "")
            if res is not None and sm is not None and hc is not None:
                d["err_modelo"], d["err_cierre"] = round(abs(res + sm), 2), round(abs(res + hc), 2)
                d["dif"] = round(d["err_modelo"] - d["err_cierre"], 2)       # > 0: el cierre acertó mejor
                if h_sen is not None and abs(h_sen - sm) > 1e-9:
                    lado = "local" if h_sen - sm > 0 else "visita"
                    d["lado_modelo"] = r["local"] if lado == "local" else r["visita"]
                    x = res + hc
                    d["cubrio"] = None if abs(x) < 1e-9 else int((x > 0) == (lado == "local"))
        if "total" in mot:
            tm, tl_s, tl_c, tr = _num(r.get("total")), _num(r.get("nfl_total_line")), _num(g.get("total_line")), _num(g.get("total"))
            d.update(total_modelo=tm, total_senal=tl_s, total_cierre=tl_c)
            if tr is not None and tm is not None and tl_c is not None:
                d["err_total_modelo"], d["err_total_cierre"] = round(abs(tr - tm), 2), round(abs(tr - tl_c), 2)
                d["dif_total"] = round(d["err_total_modelo"] - d["err_total_cierre"], 2)
                if tl_s is not None and abs(tm - tl_s) > 1e-9:
                    d["lado_total"] = "over" if tm > tl_s else "under"
                    d["acerto_total"] = None if abs(tr - tl_c) < 1e-9 else int((tr > tl_c) == (tm > tl_s))
        cambios = []
        ini = g.get("inicio")
        for eq in (r["local"], r["visita"]):
            ahora_qb = verdad.get((gid, eq))
            prev = [p for t, p in previo.get(eq, []) if ini is not None and t < ini and (p, eq) in verdad]
            antes_qb = verdad.get((prev[-1], eq)) if prev else None
            cambios.append(None if ahora_qb is None or antes_qb is None else int(ahora_qb != antes_qb))
        d["cambio_qb"] = 1 if 1 in cambios else (0 if all(x == 0 for x in cambios) else None)
        out.append(d)
    return out


def seccion_fuera(g26, semana, bot_dir, datos=None):
    """50: (filas de la semana, línea de Telegram, líneas del informe completo). Acumulado desde la semana 5."""
    sem_f = fuera_juegos(g26, semana, bot_dir, datos)
    acu = []
    for s_ in range(SEMANA_31A, semana + 1):
        acu += sem_f if s_ == semana else fuera_juegos(g26, s_, bot_dir)
    if semana < SEMANA_31A:
        acu = []
    sp = [x for x in acu if x.get("dif") is not None]
    tt = [x for x in acu if x.get("dif_total") is not None]

    def resumen(filas, col, col_lado, nombre):
        if not filas:
            return f"{nombre}: sin juegos con resultado"
        b = _boot_media([x[col] for x in filas], 5002026)
        lados = [x[col_lado] for x in filas if x.get(col_lado) is not None]
        txt = (f"{nombre}: {len(filas)} juegos · error del modelo − error del cierre {_num_txt(b[0])} pts "
               f"(IC 95 % {_num_txt(b[1])} a {_num_txt(b[2])}; > 0 = el cierre acertó mejor) · el lado del modelo acertó "
               f"{sum(lados)} de {len(lados)}")
        for et, v in (("con cambio de QB", 1), ("sin cambio", 0)):
            sub = [x[col] for x in filas if x.get("cambio_qb") == v]
            if sub:
                txt += f" · {et} {_num_txt(sum(sub) / len(sub))} (n {len(sub)})"
        return txt
    cuenta = {}
    for x in sem_f:
        for m in x["motivo"].split(" + "):
            cuenta[m] = cuenta.get(m, 0) + 1
    tel = (f"Fuera (50, solo registro): esta semana {len(sem_f)} juegos"
           + (" (" + ", ".join(f"{k} {v}" for k, v in cuenta.items()) + ")" if cuenta else "")
           + ("" if semana >= SEMANA_31A else " · semana informativa: no entra al acumulado")
           + (f" · acumulado desde la semana {SEMANA_31A}: " + resumen(sp, "dif", "cubrio", "spread")
              + " · " + resumen(tt, "dif_total", "acerto_total", "total") if acu else "")
           + " · referencia H29: en los marcados de 2023-2025 la diferencia fue +0,98 (el cierre acertó mejor).")
    txt = ["JUEGOS «FUERA» (50; solo registro: no decide nada, no cuenta para 29A ni 31A)"]
    for x in sem_f:
        partes = [f"  {x['juego']} · {x['motivo']} · {x['resultado'] or 'sin resultado'}"]
        if "linea_modelo" in x:
            partes.append(f"spread: señal {_num_txt(x.get('linea_senal'))} ({x.get('ref_senal')}) · modelo {_num_txt(x.get('linea_modelo'))}"
                          f" · cierre {_num_txt(x.get('linea_cierre'))} ({x.get('ref_cierre') or '—'}) · error modelo "
                          f"{_num_txt(x.get('err_modelo'), False)} / cierre {_num_txt(x.get('err_cierre'), False)}"
                          f" · lado del modelo {x.get('lado_modelo', '—')}: "
                          + {1: "cubrió", 0: "no cubrió", None: "push o sin dato"}[x.get("cubrio")])
        if "total_modelo" in x:
            partes.append(f"total: modelo {_num_txt(x.get('total_modelo'), False)} · señal {_num_txt(x.get('total_senal'), False)}"
                          f" · cierre {_num_txt(x.get('total_cierre'), False)} · error modelo {_num_txt(x.get('err_total_modelo'), False)}"
                          f" / cierre {_num_txt(x.get('err_total_cierre'), False)} · {x.get('lado_total', '—')}: "
                          + {1: "acertó", 0: "falló", None: "push o sin dato"}[x.get("acerto_total")])
        partes.append("cambio de QB: " + {1: "sí", 0: "no", None: "sin dato"}[x.get("cambio_qb")])
        txt.append(" · ".join(partes))
    if not sem_f:
        txt.append("  (ningún juego quedó Fuera esta semana)")
    return sem_f, tel, txt


def seccion_vigia(g26):
    """55: verificación del vigía con los snaps (por modelo y semana) y estado del piloto. ('', [], []) si no hay datos."""
    met, filas = vigia_verificar(g26)
    if not met:
        return "", [], []
    est = leer_estado()
    p = vigia_piloto(vigia_met_piloto(g26))
    lin = ["VIGÍA (55): verificación con los snaps de nflverse (código, sin IA)"]
    tot = {}
    for (c, s), m in sorted(met.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        lin.append(f"  semana {s} · {VIGIA_NOMBRE[c]}: {m['consultas']} consultas ({m['fallas']} fallidas) · hechos sobre titulares "
                   f"{m['hechos']}, verificables {m['verificables']}, correctos {m['correctos']} · precisión {_pct(m['precision'], False)}"
                   f" · cobertura {_pct(m['cobertura'], False)} ({m['avisados']} de {m['no_jugaron']} titulares que no jugaron)"
                   + (f" · {len(m['sin_snaps'])} juegos sin snaps todavía" if m["sin_snaps"] else ""))
        t = tot.setdefault(c, [0, 0, 0, 0])
        t[0] += m["correctos"]; t[1] += m["verificables"]; t[2] += m["avisados"]; t[3] += m["no_jugaron"]
    lin.append("  " + texto_vigia_piloto(p, est))
    tel = ("Vigía (55): " + " · ".join(f"{VIGIA_NOMBRE[c]} precisión {_pct(t[0] / t[1], False) if t[1] else '—'} "
                                        f"({t[0]} de {t[1]}), cobertura {_pct(t[2] / t[3], False) if t[3] else '—'}" for c, t in tot.items())
           + " · " + texto_vigia_piloto(p, est))
    return tel, lin, filas


def guardar_informe(semana, completo, sels, auto, extra=None):
    INFORMES.mkdir(parents=True, exist_ok=True)
    (INFORMES / f"informe_semana_{semana}.txt").write_text(completo + "\n", encoding="utf-8")
    for nombre, filas in (("selecciones", sels), ("autopsia", auto)) + tuple((extra or {}).items()):
        ruta = INFORMES / f"informe_semana_{semana}_{nombre}.csv"
        campos = []
        for f in filas:
            for k in f:
                if k not in campos:
                    campos.append(k)
        with open(ruta, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=campos or ["semana"])
            w.writeheader()
            for f in filas:
                w.writerow({k: ("" if f.get(k) is None else f.get(k)) for k in campos})
    return INFORMES / f"informe_semana_{semana}.txt"


def informes_pendientes(g26, estado, ahora):
    """Semanas que cuentan (≥ 5) con todos sus juegos jugados y sin informe enviado. Espera la jugada por jugada de todos
    los juegos de la semana, como máximo 48 h después del último inicio."""
    import polars as pl
    hechos = set(estado.get("informes", {}))
    out = []
    for (sem,), gr in g26.filter(pl.col("week") >= SEMANA_31A).group_by(["week"], maintain_order=True):
        sem = int(sem)
        if str(sem) in hechos or gr.height == 0 or gr["result"].null_count() > 0:
            continue
        ultimo = max(gr["inicio"].to_list())
        pbp = pbp_temporada()
        en_pbp = set(pbp["game_id"].unique().to_list()) if pbp is not None and pbp.height else set()
        if set(gr["game_id"].to_list()) <= en_pbp or (ahora - ultimo).total_seconds() > ESPERA_PBP_H * 3600:
            out.append(sem)
    return sorted(out)


def ultima_semana_cerrada(g26):
    """La semana más reciente (desde la 4) con todos sus juegos jugados."""
    import polars as pl
    cerradas = [int(w) for (w,), gr in g26.filter(pl.col("week") >= SEMANA_AUTO).group_by(["week"])
                if gr.height and gr["result"].null_count() == 0]
    return max(cerradas) if cerradas else None


def enviar_informe(g26, semana, bot_dir, ahora, estado, sin_telegram=False):
    """Arma el informe de la semana, lo guarda en salidas/semana/informes/ y lo manda por Telegram. Anota en el estado
    las semanas que cuentan y están completas (así el modo auto no lo repite). Devuelve el texto completo."""
    import polars as pl
    tel, completo, sels, auto, extra = informe_semana(g26, semana, bot_dir, ahora)
    ruta = guardar_informe(semana, completo, sels, auto, extra)
    log(f"informe de la semana {semana}: {len(sels)} selecciones, {len(auto)} juegos en la autopsia → {ruta.name}")
    if not sin_telegram:
        sys.path.insert(0, str(BASE))
        import sprint2 as s2
        s2.telegram(tel)
    gr = g26.filter(pl.col("week") == semana)
    if semana >= SEMANA_31A and gr.height and gr["result"].null_count() == 0:
        estado.setdefault("informes", {})[str(semana)] = iso(ahora)
    return completo


# --------------------------------------------------------------------------------------
# Principal
# --------------------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("modo", choices=["auto", "estado", "correr", "retro", "hoja", "qb", "hoja-prueba", "gemini-piloto", "informe",
                                     "vigia-prueba"])
    ap.add_argument("--variante", choices=sorted(GEMINI_VARIANTES))
    ap.add_argument("--semana", type=int)
    ap.add_argument("--juegos")
    ap.add_argument("--tipo", default="manual")
    ap.add_argument("--ahora")
    ap.add_argument("--sin-telegram", action="store_true")
    ap.add_argument("--real", action="store_true")     # v8.3: vigia-prueba --real hace 1 consulta real por modelo (no cuenta)
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
    _LOG_BOT.clear()
    mig = migrar_registro()                            # v7: columnas nuevas al final del registro (una sola vez)
    if mig:
        log(f"{VERSION_SEMANA}: registro con las columnas de v7 ({mig[1]} filas; ningún valor cambió); "
            f"el original quedó en {mig[0].name}")
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
        # v7: boleto de prueba con el mismo formato (encabezados, filas azules, notas); se borra al terminar
        try:
            filas, meta = grilla_boleto_prueba()
            sid_b = crear_boleto(hoja, filas, meta, TITULO_BOLETO_PRUEBA, SID_BOLETO_PRUEBA)
            hoja.lote([{"deleteSheet": {"sheetId": sid_b}}])
        except Exception as e:  # noqa: BLE001
            print(f"Hoja: falló el boleto de prueba ({type(e).__name__}: {str(e)[:300]})")
            return
        print("Hoja OK: boleto de prueba con el formato real creado, escrito y borrado")
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
        if GEMINI_LLAVE.exists():
            var, tope = gemini_cfg()
            hoy = ahora.astimezone(CARACAS).date().isoformat()
            print(f"Agente Gemini (sombra): activo · {GEMINI_MODELO} · variante {var} (huella {gemini_huella(var)}) · "
                  f"hoy {estado.get('gemini', {}).get(hoy, 0)}/{tope} consultas T−85 y "
                  f"{estado.get('gemini_prueba', {}).get(hoy, 0)}/{GEMINI_MAX_PRUEBA_DIA} de piloto")
        else:
            print("Agente Gemini (sombra): apagado (no hay credenciales/gemini.key)")
        if GEMINI_LLAVE.exists():
            print(texto_e2_estado(ahora, estado))
            try:
                print(texto_vigia_estado(ahora, estado))
            except Exception as e:  # noqa: BLE001
                print(f"Vigía (55): no pude leer su registro ({type(e).__name__})")
        inf = estado.get("informes", {})
        print("Informes de CLV enviados (v8.1): " + (", ".join(f"semana {k} ({fecha_cc(t_utc(v))})" for k, v in sorted(inf.items(), key=lambda kv: int(kv[0])))
                                                     if inf else "ninguno todavía (el primero sale cuando cierre la semana 5)"))
        b = ultimo_boleto()
        print(f"Boleto (informativo): semana {b['semana']}, armado en la corrida {NOMBRE_CORRIDA.get(b['tipo'], b['tipo'])} "
              f"({fecha_cc(t_utc(b['corrida_utc']))}) · "
              f"{len(b['juegos'])} juegos, {_frescas(b)} con líneas frescas" if b else
              "Boleto (informativo): todavía no hay (se arma en la próxima corrida que cuenta)")
        return

    if args.modo == "qb":
        print(texto_qb(g26, ahora, args.semana))
        return

    if args.modo == "vigia-prueba":                    # v8.3 (55): sin consultar a Gemini; --real: 1 consulta por modelo
        if args.real:
            print(vigia_prueba_real(g26, ahora, estado))
            guardar_estado(estado)
        else:
            print(vigia_autoprueba(g26))
        return

    if args.modo == "informe":                         # v8.1 (45): informe de CLV y autopsia de una semana jugada
        sem = args.semana or ultima_semana_cerrada(g26)
        if sem is None:
            print("Todavía no hay una semana jugada para el informe.")
            return
        print(enviar_informe(g26, sem, args.bot_dir, ahora, estado, args.sin_telegram))
        guardar_estado(estado)
        return

    if args.modo == "gemini-piloto":
        print(gemini_piloto(g26, ahora, estado, args.variante))
        guardar_estado(estado)
        return

    if args.modo == "hoja":
        if hoja is None:
            print("Hoja: no configurada (falta semana.ini o la credencial) o no se pudo abrir.")
            return
        semanas = [args.semana] if args.semana else semanas_con_datos(g26)
        log(f"{VERSION_SEMANA}: rehago las pestañas {semanas} y el boleto (sin simular)")
        escribir_semanas(hoja, g26, semanas, nombres_de_qb(g26, leer_roster()), ahora, estado, args.bot_dir)
        guardar_estado(estado)
        log("== LISTO")
        return

    if args.modo == "retro":
        log(f"{VERSION_SEMANA}: retrospectiva de los juegos de {TEMPORADA} ya jugados")
        filas, ctx = retro(g_all, g26, args, ahora)
        if hoja is not None and filas:
            escribir_semanas(hoja, g26, {f["semana"] for f in filas}, ctx["nombres_qb"], ahora, estado, args.bot_dir)
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
                if escribir_semanas(hoja, g26, nuevos.keys(), nombres_de_qb(g26, leer_roster()), ahora, estado, args.bot_dir):
                    estado["ultima_falla_hoja"] = iso(ahora)
                else:
                    estado.pop("ultima_falla_hoja", None)
                guardar_estado(estado)
            # v8.1 (45): informe de CLV y autopsia cuando cierra una semana que cuenta (una sola vez por semana; si falla,
            # reintenta cada 30 min y nunca frena el temporizador)
            falla_inf = t_utc(estado.get("ultima_falla_informe"))
            if falla_inf is None or (ahora - falla_inf).total_seconds() > 1800:
                try:
                    pend = informes_pendientes(g26, estado, ahora)
                    for s_ in pend:
                        enviar_informe(g26, s_, args.bot_dir, ahora, estado, args.sin_telegram)
                    if pend:
                        estado.pop("ultima_falla_informe", None)
                        guardar_estado(estado)
                except Exception as e:  # noqa: BLE001
                    log(f"Informe: error ({type(e).__name__}: {str(e)[:300]})")
                    estado["ultima_falla_informe"] = iso(ahora)
                    guardar_estado(estado)
            return                                         # nada que hacer: sale sin escribir en el log
    else:
        import polars as pl
        sem = args.semana or semana_actual(g26, ahora)
        ids = args.juegos.split(",") if args.juegos else g26.filter((pl.col("week") == sem) & (pl.col("inicio") > ahora))["game_id"].to_list()
        lista = [(args.tipo, f"{args.tipo}-{iso(ahora)}", ids)]

    log(f"{VERSION_SEMANA}: corre {[(t, c, len(i)) for t, c, i in lista]}")
    g_all, g26 = calendario(0.25)                    # calendario fresco (QB titulares y líneas) antes de proyectar
    sombra = []
    resumenes, nombres_qb = correr(lista, g_all, g26, args, ahora, sombra=sombra)
    for tipo, clave, ids in lista:
        if tipo in ("miercoles", "sabado"):
            estado["fijas"][clave] = iso(ahora)
        elif tipo == "t85":
            estado["grupos"][clave] = iso(ahora)
    guardar_estado(estado)
    boletos = []                                      # v7: boleto informativo, solo en las corridas que cuentan
    for tipo, _, filas, _ in resumenes:
        for s_ in sorted({f["semana"] for f in filas}):
            try:
                b = armar_boleto(g26, s_, args.bot_dir, ahora, tipo)
                if b:
                    boletos.append(b)
            except Exception as e:  # noqa: BLE001
                log(f"Boleto: no se pudo armar el de la semana {s_} ({type(e).__name__}: {str(e)[:200]})")
    if hoja is not None:
        sems = {f["semana"] for _, _, filas, _ in resumenes for f in filas} | set(resultados_nuevos(g26, estado).keys())
        escribir_semanas(hoja, g26, sems, nombres_qb, ahora, estado, args.bot_dir)
        guardar_estado(estado)
    if resumenes and not args.sin_telegram:
        sys.path.insert(0, str(BASE))
        import sprint2 as s2
        txt = texto_telegram(resumenes)
        try:
            txt += ("\n\n" + texto_boleto(boletos[-1], g26)) if boletos else ""
        except Exception as e:  # noqa: BLE001
            log(f"Boleto: no se pudo resumir para Telegram ({type(e).__name__})")
        s2.telegram(txt)
    if sombra:                                        # 35A: el agente en sombra corre después de guardar y enviar
        gemini_sombra(sombra, ahora, estado)
        guardar_estado(estado)
    if sombra and args.modo == "auto":                # v8.3 (55): el vigía, después de g1 y antes de e2
        res_v = vigia_t85(sombra, [f for _, _, filas, _ in resumenes for f in filas], ahora, estado, g26)
        guardar_estado(estado)
        if res_v:
            if hoja is not None:
                for s_ in res_v["semanas"]:
                    try:
                        actualizar_hoja(hoja, g26, s_, nombres_qb, ahora)
                        log(f"hoja: pestaña {pestana(s_)} actualizada con el vigía")
                    except Exception as e:  # noqa: BLE001
                        log(f"Hoja: no pude agregar el vigía a {pestana(s_)} ({type(e).__name__}: {str(e)[:200]})")
            if not args.sin_telegram:
                try:
                    sys.path.insert(0, str(BASE))
                    import sprint2 as s2
                    s2.telegram(texto_vigia(res_v))
                except Exception as e:  # noqa: BLE001
                    log(f"Vigía: no pude mandar el Telegram ({type(e).__name__})")
    if sombra and args.modo == "auto":                # v8.2 (49): registro en vivo e2, aparte de g1 y después de él
        e2_vivo(sombra, ahora, estado)
        guardar_estado(estado)
    log("== LISTO")


if __name__ == "__main__":
    main()
