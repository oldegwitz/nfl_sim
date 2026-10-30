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
  (v9) venv/bin/python semana.py vigia-manual [--equipo KC]   (/vigia: simula y consulta a los vigías; no cuenta)
  (v9) venv/bin/python semana.py autopsia [--semana N]        (/autopsia: por qué perdieron los favoritos del cierre)
  (v9) venv/bin/python semana.py briefing                     (/briefing: analista de los juegos que faltan)
  (v9) venv/bin/python semana.py claude-prueba [--real]       (prueba de los agentes de Claude; --real: 1 consulta real)
  (v9.2) En cada T−85 automática, clima.py guarda el pronóstico del clima (60d) en un proceso aparte; sus modos de
         prueba están en clima.py (prueba, prueba --real, coordenadas, estado, informe --semana N).
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
import threading
import time
from pathlib import Path
from zoneinfo import ZoneInfo

VERSION_SEMANA = "semana-v9.2 (30-oct-2026)"
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
# v8.4 (decisiones 57 y 58 de Ozz, 13-oct; registradas en claude/registro_57_58_tablero.md antes de construir):
#     · 57 (P1 = a): la bandera de sesgo (21A) sigue igual; el informe suma una línea, solo de registro, con cuántas
#       veces cambió en la semana y qué juegos decidieron con ella encendida o apagada (seccion_bandera).
#     · 58: al terminar cada corrida que escribió algo (y al cerrar resultados), llama a tablero.py en un proceso aparte
#       con límite de tiempo (TABLERO_TIMEOUT); si falla o tarda, se anota en el log y la corrida sigue igual.
#       Modo nuevo «tablero» para correrlo a mano. No cambian la proyección, s2-v1, g1, e2, el vigía ni las huellas.
# v9 (decisiones 63, 65 y 65.1 de Ozz, 15-20 oct; especificación en claude/registro_65_agentes_claude.md, escrita antes):
#     agentes de Claude (Opus 5.5, «Opus en todo»), en sombra y descriptivos:
#     · A1 vigía-alineador: en cada T−85, en un hilo aparte y en paralelo con el vigía de Gemini (no alarga la corrida),
#       hechos «fuera» de fuente oficial cuya URL apareció en los resultados de búsqueda y la alineación esperada; el
#       código decide titulares, titulares nuevos y quién no tiene historia en la NFL. Registros vigia_claude_*.csv,
#       Telegram aparte («piloto»), verificación con los snaps en el informe y comparación con Gemini en los mismos juegos.
#     · A3 autopsia del lunes: causas de H41 en puntos (código) y crónica corta de Opus para cada favorito del cierre que
#       perdió; automática desde la semana 7 después del informe y con el modo 'autopsia'.
#     · A4 analista del sábado: después de la corrida del sábado 10:15 y con el modo 'briefing'.
#     · 63: modo 'vigia-manual' (/vigia): simula como /correr (no cuenta) y consulta a los dos vigías; registros aparte.
#     · Las órdenes largas no corren si toca una automática en ≤ 12 min. Tope diario en USD ([claude_motor]).
#     No cambian la proyección, s2-v1, el consenso del QB, las selecciones, el boleto, g1, e2 ni el vigía de Gemini
#     (ni sus huellas): la proyección es idéntica a la de v8.4.
# v9.1 (20-oct, después de la primera consulta real, NE @ CHI: 160 s, 6 búsquedas, USD 1,22, la búsqueda llegó al tope de
#     8.000 tokens de salida): tope de salida 16.000 en el vigía-alineador (4.000 en la autopsia, 20.000 en el analista),
#     reservas de costo con lo medido (USD 1,30 por juego) y la prueba real muestra tokens y fin de cada paso. Antes de la
#     primera T−85 del vigía-alineador: el piloto empieza con la huella de v9.1. Nada más cambia.
# v9.2 (30-oct, decisión 60 de Ozz: D1 = a, D2 = a; especificación en claude/registro_60_clima.md, escrita antes):
#     · 60d: en cada T−85 automática lanza clima.py en un proceso aparte (como el tablero: nunca frena ni cambia la
#       corrida) para guardar el pronóstico de NWS y Open-Meteo de cada juego; si algún partido al aire libre tiene
#       viento ≥ 15 mph, lluvia ≥ 60 % o ≤ 0 °C, manda un Telegram corto («#9 en registro, sin dinero»).
#     · El informe semanal suma la sección «Clima» (consultas, conteos de #9 a ciegas, error del viento contra el
#       gamebook) y el conteo del movimiento tardío de la decisión 56 (solo cuántos casos; nunca la tasa).
#     · El modo estado suma la línea del clima.
#     No cambian la proyección, s2-v1, el consenso del QB, las selecciones, el boleto, g1, e2, los vigías ni sus huellas.
BASE = Path(__file__).resolve().parent
DATOS = BASE / "datos"
SAL = BASE / "salidas" / "semana"
REGISTRO = SAL / "proyecciones_2026.csv"
RETRO = SAL / "retro_2026.csv"                     # retrospectiva: no cuenta para 31A ni para el CLV
ESTADO = SAL / "estado.json"
MAX_EDAD_CAL_H = 1.0                                 # el calendario (resultados y QB) se refresca cada hora
CONFIG = BASE / "semana.ini"
MD5_SPRINT2 = "baad72c6a5dc0054a7de22a79c88616f"     # s2-v1 congelado (31A)
TABLERO = BASE / "tablero.py"                        # v8.4 (58): tablero tipo PFF Pro (descriptivo), hoja aparte
TABLERO_TIMEOUT = 150                                # segundos; si se pasa, se corta y la corrida sigue
CLIMA = BASE / "clima.py"                            # v9.2 (60d): pronóstico del clima a T−85 (descriptivo)
CLIMA_TIMEOUT = 100                                  # segundos desde que se lanza (clima.py se corta solo a los 90)
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


def vigia_t85(pendientes, filas_proy, ahora, estado, g26, manual=False):
    """El vigía de una corrida automática T−85 (después de g1). pendientes = [(juego, FuentesQB)]; filas_proy = las filas
    de la proyección de esta corrida (para saber con qué QB proyectó la máquina). Devuelve el resumen para Telegram y la
    hoja, o None. Nunca detiene la corrida. v9 (63): manual=True es /vigia: mismos modelos y reglas, registros aparte
    (vigia_manual_*.csv, huella marcada «manual:»), con su propio contador diario (no gasta el cupo de la T−85 que
    cuenta), no aplica la regla del piloto y no entra a ninguna medición."""
    marca = "manual:" if manual else ""
    try:
        activo, tope = vigia_cfg()
        if not pendientes or not GEMINI_LLAVE.exists() or not activo:
            return None
        from concurrent.futures import ThreadPoolExecutor, wait
        if not manual:
            try:
                vigia_piloto_aplicar(g26, estado, ahora)
            except Exception as e:  # noqa: BLE001
                log(f"Vigía: no pude evaluar el piloto ({type(e).__name__}); sigo con los modelos de antes")
        claves = vigia_modelos(estado)
        juegos = [j for j, _ in pendientes]
        momento = e2_momento(ahora)
        hoy = momento.astimezone(CARACAS).date().isoformat()
        usado = estado.setdefault("vigia_manual_dia_gemini" if manual else "vigia_dia", {})   # v9: /vigia no gasta el cupo de la T−85
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
        resumen = dict(momento=momento, semanas=sorted({j["semana"] for j in juegos}), claves=claves, juegos=[], costo=0.0, manual=manual,
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
                                            huella=marca + vigia_huella(c), equipo=eq, nombre=h["nombre"], posicion=h["posicion"],
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
                                    modelo=VIGIA_MODELOS[c], huella=marca + vigia_huella(c), forma=x.get("forma", ""),
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
        _anexar_csv(VIGIA_MANUAL_C if manual else VIGIA_CONSULTAS, CAMPOS_VC, filas_c, "vigia_manual_consultas" if manual else "vigia_consultas")
        _anexar_csv(VIGIA_MANUAL_H if manual else VIGIA_HECHOS, CAMPOS_VH, filas_h, "vigia_manual_hechos" if manual else "vigia_hechos")
        n_av = sum(len(v) for jj in resumen["juegos"] for v in jj["avisos"].values())
        log(f"Vigía{' a pedido' if manual else ''} ({'+'.join(claves)}; " + ", ".join(f"{c} {vigia_huella(c)}" for c in claves) + f"): {len(juegos)} juegos en "
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
    lin = [f"{'🔎 VIGÍA A PEDIDO (no cuenta)' if resumen.get('manual') else '🔎 VIGÍA T−85'} · semana {', '.join(map(str, resumen['semanas']))} · juegos de las {fecha_cc(resumen['inicio'])} (Caracas)"
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
    lin.append("Solo hechos con fuente oficial; el código decide quién es titular (snaps). No cambia la máquina ni las selecciones."
               + (" Registro aparte (a pedido): no entra al piloto ni a la medición." if resumen.get("manual") else ""))
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
# v9 (decisiones 65 y 65.1, 20-oct): agentes de Claude (Opus 5.5) — vigía-alineador A1 (T−85 y /vigia), autopsia
# del lunes A3 y analista del sábado A4; /vigia a pedido (63). Todo en sombra y descriptivo: no tocan s2-v1, la
# proyección, el consenso del QB, 29A ni 31A, ni a g1, e2 o el vigía de Gemini (ni sus huellas).
# Especificación: claude/registro_65_agentes_claude.md (65.1 y «Especificación del paquete 2»), escrita antes.
# --------------------------------------------------------------------------------------
CLAUDE_LLAVE = BASE / "credenciales" / "anthropic.key"     # la carga cargar_anthropic.sh (entrada oculta, 600)
CLAUDE_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_VERSION_API = "2023-06-01"
CLAUDE_MODELO = "claude-opus-5-5"                          # 65.1 (Ozz, 20-oct): Opus en todo
CLAUDE_NOMBRE = "Opus 5.5"
CLAUDE_PRECIO = (4.0e-6, 20.0e-6)                          # USD por token de entrada y de salida (verificado el 18-oct-2026)
CLAUDE_USD_BUSQUEDA = 0.01                                 # USD 10 por 1.000 búsquedas
CLAUDE_BUSQUEDA = "web_search_20260318"
CLAUDE_TOPE_USD_DIA = 25.0                                 # semana.ini [claude_motor] tope_usd_dia (aparte del lector de boletos)
CLAUDE_MAX_CONT = 3                                        # continuaciones pause_turn por consulta
CLAUDE_LLAMADAS = SAL / "claude_llamadas.csv"
CAMPOS_CL = ["hora_utc", "fecha_ccs", "agente", "origen", "huella", "game_id", "paso", "modelo", "estado", "http",
             "latencia_s", "tok_entrada", "tok_salida", "tok_cache_escritura", "tok_cache_lectura", "busquedas", "costo_usd",
             "continuaciones", "stop_reason", "detalle", "lim_entrada", "lim_salida", "lim_pedidos"]
DOMINIOS_EQUIPOS = {"ARI": "azcardinals.com", "ATL": "atlantafalcons.com", "BAL": "baltimoreravens.com",
                    "BUF": "buffalobills.com", "CAR": "panthers.com", "CHI": "chicagobears.com", "CIN": "bengals.com",
                    "CLE": "clevelandbrowns.com", "DAL": "dallascowboys.com", "DEN": "denverbroncos.com",
                    "DET": "detroitlions.com", "GB": "packers.com", "HOU": "houstontexans.com", "IND": "colts.com",
                    "JAX": "jaguars.com", "KC": "chiefs.com", "LA": "therams.com", "LAC": "chargers.com", "LV": "raiders.com",
                    "MIA": "miamidolphins.com", "MIN": "vikings.com", "NE": "patriots.com", "NO": "neworleanssaints.com",
                    "NYG": "giants.com", "NYJ": "newyorkjets.com", "PHI": "philadelphiaeagles.com", "PIT": "steelers.com",
                    "SEA": "seahawks.com", "SF": "49ers.com", "TB": "buccaneers.com", "TEN": "tennesseetitans.com",
                    "WAS": "commanders.com"}
DOMINIOS_OFICIALES = ["nfl.com", "espn.com"] + [DOMINIOS_EQUIPOS[e] for e in sorted(DOMINIOS_EQUIPOS)]
_CL_CANDADO = threading.Lock()


def claude_cfg():
    """(activo, tope en USD por día de Caracas) desde semana.ini [claude_motor]."""
    cfg = configparser.ConfigParser()
    if CONFIG.exists():
        cfg.read(CONFIG)
    sec = cfg["claude_motor"] if cfg.has_section("claude_motor") else {}
    activo = str(sec.get("activo", "si")).strip().lower() not in ("no", "0", "false", "apagado")
    try:
        tope = float(str(sec.get("tope_usd_dia", CLAUDE_TOPE_USD_DIA)).strip().replace(",", ".") or CLAUDE_TOPE_USD_DIA)
    except ValueError:
        tope = CLAUDE_TOPE_USD_DIA
    return activo, tope


def claude_gasto_hoy(hoy):
    """USD que costaron hoy (día de Caracas) las consultas de los agentes del motor (claude_llamadas.csv)."""
    return round(sum(_f(f.get("costo_usd")) for f in _leer_csv(CLAUDE_LLAMADAS) if f.get("fecha_ccs") == hoy), 6)


def claude_cupo(ahora):
    """(USD que quedan hoy, motivo si no se puede consultar). Sin llave o apagado → (0, motivo)."""
    if not CLAUDE_LLAVE.exists():
        return 0.0, "sin credenciales/anthropic.key"
    activo, tope = claude_cfg()
    if not activo:
        return 0.0, "apagado en semana.ini [claude_motor]"
    resto = tope - claude_gasto_hoy(ahora.astimezone(CARACAS).date().isoformat())
    return max(resto, 0.0), ("" if resto > 0 else f"tope del día (USD {tope:.2f})")


def _motivo_claude(r):
    """Tipo, código y mensaje de error de la API de Claude (nunca trae la llave)."""
    try:
        err = (r.json() or {}).get("error") or {}
    except Exception:  # noqa: BLE001
        return ""
    det = err.get("details") if isinstance(err.get("details"), dict) else {}
    cod = _texto(det.get("error_code"))
    return f"{_texto(err.get('type'))}{' ' + cod if cod else ''}: {_texto(err.get('message'))}".strip(": ")[:300]


def _registrar_claude(reg, out):
    momento = reg.get("momento") or dt.datetime.now(dt.timezone.utc)
    fila = dict(hora_utc=iso(momento), fecha_ccs=momento.astimezone(CARACAS).date().isoformat(), agente=reg.get("agente", ""),
                origen=reg.get("origen", ""), huella=reg.get("huella", ""), game_id=reg.get("game_id", ""),
                paso=reg.get("paso", ""), modelo=CLAUDE_MODELO, estado=out["estado"], http=out["http"],
                latencia_s=out["latencia_s"], tok_entrada=out["tok_entrada"], tok_salida=out["tok_salida"],
                tok_cache_escritura=out["tok_cache_escritura"], tok_cache_lectura=out["tok_cache_lectura"],
                busquedas=out["busquedas"], costo_usd=out["costo_usd"], continuaciones=out["continuaciones"],
                stop_reason=out["stop_reason"], detalle=_texto(out["detalle"])[:300],
                lim_entrada=out["limites"].get("entrada", ""), lim_salida=out["limites"].get("salida", ""),
                lim_pedidos=out["limites"].get("pedidos", ""))
    with _CL_CANDADO:
        try:
            _anexar_csv(CLAUDE_LLAMADAS, CAMPOS_CL, [fila], "claude_llamadas")
        except OSError as e:
            log(f"Claude: no pude anotar la consulta ({type(e).__name__})")


def claude_post(cuerpo, limite, reg, post=None, dormir=time.sleep):
    """Una consulta a la API de Claude (Messages) con sus continuaciones (pause_turn, hasta 3; si la respuesta trae un
    contenedor del filtrado dinámico, la continuación lo reutiliza) y un reintento si la API pide esperar (429 con retry-after, o 529) y queda plazo. Un 429 sin retry-after (tope de gasto de la Console) no se
    reintenta. Si el pedido salió y no hubo respuesta a tiempo, anota como costo la reserva del paso (reg['reserva_usd']):
    así el tope del día no queda corto cuando la API anda lenta. Anota la consulta en claude_llamadas.csv. Devuelve dict(estado, http, contenido, texto, tokens, búsquedas,
    costo_usd, latencia_s, detalle, stop_reason, continuaciones, limites). Nunca lanza excepciones ni registra la llave."""
    import requests
    out = dict(estado="", http="", contenido=[], texto="", tok_entrada=0, tok_salida=0, tok_cache_escritura=0,
               tok_cache_lectura=0, busquedas=0, costo_usd=0.0, latencia_s=0.0, detalle="", stop_reason="",
               continuaciones=0, limites={}, estimado=0.0)
    t0 = time.time()
    if not CLAUDE_LLAVE.exists():
        out["estado"] = "sin llave"
    else:
        llave = CLAUDE_LLAVE.read_text(encoding="utf-8").strip()
        asistente, reintentos, contenedor = [], 0, ""
        while True:
            resta = limite - time.time()
            if resta < 5:
                out.update(estado="tiempo agotado", detalle=out["detalle"] or "sin tiempo para seguir")
                break
            msgs = list(cuerpo["messages"]) + ([{"role": "assistant", "content": asistente}] if asistente else [])
            pedido = {**cuerpo, "messages": msgs, **({"container": contenedor} if contenedor else {})}
            try:
                r = (post or requests.post)(CLAUDE_URL, headers={"x-api-key": llave, "anthropic-version": CLAUDE_VERSION_API,
                                                                 "content-type": "application/json"},
                                            json=pedido, timeout=(min(10.0, resta), resta))
            except requests.exceptions.ConnectTimeout:
                out.update(estado="tiempo agotado", detalle="sin conexión con la API")
                break
            except requests.exceptions.Timeout:          # el pedido salió: la API pudo cobrar lo que alcanzó a hacer
                out.update(estado="tiempo agotado", detalle="sin respuesta a tiempo: costo estimado (reserva del paso)")
                out["estimado"] = float(reg.get("reserva_usd") or 0.0)
                break
            except Exception as e:  # noqa: BLE001 — solo el tipo: el texto podría traer datos de la conexión
                out.update(estado="error de red", detalle=type(e).__name__)
                if isinstance(e, (requests.exceptions.ConnectionError, requests.exceptions.ChunkedEncodingError)):
                    out["estimado"] = float(reg.get("reserva_usd") or 0.0)   # pudo cortarse con el pedido ya enviado
                    if out["estimado"]:
                        out["detalle"] += ": costo estimado (reserva del paso)"
                break
            out["http"] = r.status_code
            hs = getattr(r, "headers", None) or {}
            for k, n in (("entrada", "anthropic-ratelimit-input-tokens-limit"), ("salida", "anthropic-ratelimit-output-tokens-limit"),
                         ("pedidos", "anthropic-ratelimit-requests-limit")):
                if hs.get(n):
                    out["limites"][k] = _texto(hs.get(n))
            if r.status_code in (429, 529) and reintentos < 1:
                ra = hs.get("retry-after")
                espera = _f(ra) if ra else (5.0 if r.status_code == 529 else None)
                if espera is not None and time.time() + espera + 15 < limite:
                    reintentos += 1
                    dormir(espera)
                    continue
            if r.status_code != 200:
                out.update(estado="error HTTP", detalle=_motivo_claude(r))
                break
            try:
                d = r.json()
            except ValueError:
                out.update(estado="respuesta inválida", detalle="la respuesta no es JSON")
                break
            u = d.get("usage") or {}
            out["tok_entrada"] += int(u.get("input_tokens") or 0)
            out["tok_salida"] += int(u.get("output_tokens") or 0)
            out["tok_cache_escritura"] += int(u.get("cache_creation_input_tokens") or 0)
            out["tok_cache_lectura"] += int(u.get("cache_read_input_tokens") or 0)
            out["busquedas"] += int(((u.get("server_tool_use") or {}).get("web_search_requests")) or 0)
            asistente = asistente + [b for b in (d.get("content") or []) if isinstance(b, dict)]
            if isinstance(d.get("container"), dict) and d["container"].get("id"):
                contenedor = _texto(d["container"]["id"])      # el filtrado dinámico usa un contenedor: se reutiliza al continuar
            out["stop_reason"] = _texto(d.get("stop_reason"))
            if out["stop_reason"] == "pause_turn":
                if out["continuaciones"] < CLAUDE_MAX_CONT:
                    out["continuaciones"] += 1
                    continue
                out.update(estado="pausada", detalle=f"siguió en pausa después de {CLAUDE_MAX_CONT} continuaciones")
                break
            out["estado"] = "cortada" if out["stop_reason"] == "max_tokens" else "ok"
            if out["estado"] == "cortada":
                out["detalle"] = "llegó al tope de tokens de salida"
            break
        out["contenido"] = asistente
        del llave
    out["texto"] = "".join(b.get("text") or "" for b in out["contenido"] if b.get("type") == "text")
    pe, ps = CLAUDE_PRECIO
    out["costo_usd"] = round(out["tok_entrada"] * pe + out["tok_cache_escritura"] * pe * 1.25 + out["tok_cache_lectura"] * pe * 0.1
                             + out["tok_salida"] * ps + out["busquedas"] * CLAUDE_USD_BUSQUEDA + out["estimado"], 6)
    out["latencia_s"] = round(time.time() - t0, 2)
    _registrar_claude(reg, out)
    return out


def _urls_de(bloques):
    """Las URL de los resultados de búsqueda y de las citas de una respuesta (no las del pedido de búsqueda)."""
    vistas = set()

    def rec(x):
        if isinstance(x, dict):
            if x.get("type") == "server_tool_use":
                return
            u = x.get("url")
            if isinstance(u, str) and u.startswith("http"):
                vistas.add(u)
            for v in x.values():
                rec(v)
        elif isinstance(x, list):
            for v in x:
                rec(v)
    rec(bloques)
    return vistas


def _errores_busqueda(bloques):
    """Códigos de error de las búsquedas que vinieron dentro de una respuesta 200 (web_search_tool_result_error)."""
    cods = []

    def rec(x):
        if isinstance(x, dict):
            if x.get("type") == "web_search_tool_result_error":
                cods.append(_texto(x.get("error_code")) or "desconocido")
            for v in x.values():
                rec(v)
        elif isinstance(x, list):
            for v in x:
                rec(v)
    rec(bloques)
    return cods


def _url_norm(u):
    """URL comparable: sin esquema, www, consulta, fragmento ni barra final; en minúsculas."""
    from urllib.parse import urlsplit
    try:
        p = urlsplit(_texto(u))
    except ValueError:
        return ""
    host = (p.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return (host + p.path.rstrip("/")).lower() if host else ""


def _vars_juego(j, momento):
    fase = (f"regular season, week {j['semana']}" if j.get("game_type", "REG") == "REG"
            else f"postseason, {RONDAS.get(j['game_type'], j['game_type'])}")
    return dict(ahora_utc=momento.astimezone(dt.timezone.utc).strftime("%Y-%m-%d %H:%M"), ahora_et=_fmt_et(momento),
                minutos=max(int((j["inicio"] - momento).total_seconds() // 60), 0), temporada=TEMPORADA, fase=fase,
                visita_nombre=EQUIPOS.get(j["visita"], j["visita"]), visita=j["visita"],
                local_nombre=EQUIPOS.get(j["local"], j["local"]), local=j["local"],
                inicio_utc=j["inicio"].astimezone(dt.timezone.utc).strftime("%Y-%m-%d %H:%M"))


def _huella(cfg):
    return hashlib.md5(json.dumps(cfg, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:8]


def enviar_tg(txt, sin_telegram=False):
    """Manda un texto por Telegram en partes de ≤ 3.800 caracteres cortadas en saltos de línea (con --sin-telegram lo
    imprime). Devuelve True si todo salió."""
    if sin_telegram:
        print(txt)
        return True
    sys.path.insert(0, str(BASE))
    import sprint2 as s2
    partes, cur = [], ""
    for lin in txt.split("\n"):
        while len(lin) > 3800:
            if cur:
                partes.append(cur)
                cur = ""
            partes.append(lin[:3800])
            lin = lin[3800:]
        if cur and len(cur) + len(lin) + 1 > 3800:
            partes.append(cur)
            cur = lin
        else:
            cur = f"{cur}\n{lin}" if cur else lin
    if cur:
        partes.append(cur)
    ok = True
    for p in partes:
        ok = bool(s2.telegram(p)) and ok
    return ok


def automatica_cerca(g26, ahora, estado, minutos=None):
    """La corrida automática (T−85, miércoles o sábado 10:15) que toca dentro de 'minutos' (o ya toca), o None. Las
    órdenes largas (/vigia, /autopsia, /briefing) no corren entonces, para no retrasar la señal que cuenta (65)."""
    minutos = ANTES_AUTOMATICA_MIN if minutos is None else minutos
    for t in (ahora, ahora + dt.timedelta(minutes=minutos)):
        lista, _ = tareas(g26, t, estado)
        if lista:
            return lista[0]
    return None


# ---------------------------------------------------------------- A1 · vigía-alineador
A1_HERRAMIENTA = {"type": CLAUDE_BUSQUEDA, "name": "web_search", "max_uses": 8, "allowed_domains": DOMINIOS_OFICIALES}
A1_MAX_TOKENS = 16000                                     # v9.1: con 8000 la búsqueda real (20-oct) se cortó; el filtrado
                                                           # dinámico escribe código que también cuenta como salida
A1_PLAZO_S = 420                                   # 300 s para la búsqueda (como 55) + 120 s reservados para la extracción
A1_RESERVA_EXTRACCION_S = 120
A1_RESERVA_USD = {"busqueda": 1.00, "extraccion": 0.30}  # costo que se anota si el pedido salió y no hubo respuesta
A1_HILOS = 16
A1_USD_JUEGO = 1.30                                        # v9.1: reserva por juego para el tope del día (medido el 20-oct: USD 1,22)
A1_MAX_FUERA, A1_MAX_ALIN = 15, 30
A1_TIPOS_ALIN = ("official_depth_chart", "espn_depth_chart", "official_inactive_list", "team_or_coach_statement", "other")
A1_UNIDADES = ("offense", "defense", "special")
A1_PILOTO_SEMANAS = 2
VIGIA_MANUAL_MAX_DIA = 10                                  # 63: /vigia por día de Caracas
VIGIA_MANUAL_MARGEN_MIN = 15                               # 65 (revisión): /vigia solo con juegos que empiecen en > 15 min (H36)
ANTES_AUTOMATICA_MIN = 12                                  # 65: órdenes largas no corren si toca una automática en ≤ 12 min
A1_RUTAS = {o: dict(consultas=SAL / f"vigia_claude{s}_consultas.csv", hechos=SAL / f"vigia_claude{s}_hechos.csv",
                    alineacion=SAL / f"vigia_claude{s}_alineacion.csv") for o, s in (("t85", ""), ("manual", "_manual"))}
VIGIA_MANUAL_C = SAL / "vigia_manual_consultas.csv"        # 63: el vigía de Gemini a pedido (registro aparte)
VIGIA_MANUAL_H = SAL / "vigia_manual_hechos.csv"
CAMPOS_A1C = CAMPOS_VC + ["origen", "n_alineacion", "n_nuevos", "n_urls"]
CAMPOS_A1H = CAMPOS_VH + ["origen", "url_en_resultados"]
CAMPOS_A1A = ["corrida_utc", "game_id", "semana", "origen", "huella", "equipo", "nombre", "posicion", "unidad", "tipo_fuente",
              "url", "publicada", "valido", "motivo_invalido", "url_en_resultados", "gsis_id", "pfr_id", "cruce",
              "titular_habitual", "jugados_2026", "years_exp", "sin_historia", "sin_2026", "nuevo", "minutos_antes",
              "nombre_roster"]
A1_SISTEMA = """You are a strict NFL availability and lineup fact checker with web search. Report only what official or
authoritative sources say; never guess.
Rules:
1. Always search before answering: your training data is out of date. Look for the official inactive list for THIS game,
   the final official injury report, official roster moves and the team's most recent official depth chart (team website,
   NFL.com or ESPN).
2. OUT: list a player only if an official source says he will not play this game: the official inactive list for this
   game, the final injury report (Out or Doubtful), an official roster move (injured reserve, PUP, NFI, suspension,
   release, trade), an on-record statement by the team or its head coach, or an NFL announcement. Never use rumors,
   anonymous sources, "expected to", "questionable", "game-time decision" or predictions.
3. LINEUP: the expected starters for THIS game: 11 on offense, 11 on defense, plus kicker, punter, kick returner and punt
   returner. Start from the most recent official depth chart and change it only for the OUT players of rule 2.
4. Every OUT player and every LINEUP player needs the URL of a page that appeared in your search results and that page's
   publication time in UTC (YYYY-MM-DDTHH:MM, or YYYY-MM-DD if no time is shown; leave it empty if the page shows none).
   Never build or guess a URL.
5. Write a plain-text report. For each team: a line "TEAM <code> - official inactive list found: yes/no"; then "OUT:"
   with one line per player (name | position | status | source type | URL | published | evidence in 20 words or fewer);
   then "LINEUP:" with one line per player (name | position | offense/defense/special | source type | URL | published).
   OUT status: inactive, out, doubtful, injured_reserve, suspended, released_or_traded or other_official. OUT source type:
   official_inactive_list, official_injury_report, team_transaction, team_or_coach_statement or league_announcement.
   LINEUP source type: official_depth_chart, espn_depth_chart, official_inactive_list, team_or_coach_statement or other."""
A1_USUARIO = """Now: {ahora_utc} UTC ({ahora_et} ET), {minutos} minutes before kickoff. NFL {temporada} {fase}.
Game: {visita_nombre} ({visita}) at {local_nombre} ({local}), kickoff {inicio_utc} UTC.
Report OUT (at most 15 players per team) and LINEUP for both teams."""
A1_EXTRAE = """Convert the NFL report below into JSON that follows the schema exactly.
Rules: copy names, positions, URLs and times exactly as they appear in the report; do not add players or facts that are
not in the report; keep a URL only if it appears in the SEARCH RESULT URLS list (otherwise leave source_url empty); use an
empty string for any missing value. Team codes: {visita} is the away team and {local} the home team."""


def a1_esquema(visita, local):
    """Esquema de la extracción (output_config.format): additionalProperties false en cada objeto, sin maxItems (no los
    acepta la API; el código corta a 15 y 30)."""
    s = {"type": "string"}
    fuera = {"type": "object", "additionalProperties": False,
             "properties": {"name": s, "position": s, "status": {"type": "string", "enum": list(VIGIA_ESTADOS)},
                            "source_type": {"type": "string", "enum": list(VIGIA_FUENTES)}, "source_url": s,
                            "source_published": s, "evidence": s},
             "required": ["name", "position", "status", "source_type", "source_url", "source_published", "evidence"]}
    alin = {"type": "object", "additionalProperties": False,
            "properties": {"name": s, "position": s, "unit": {"type": "string", "enum": list(A1_UNIDADES)},
                           "source_type": {"type": "string", "enum": list(A1_TIPOS_ALIN)}, "source_url": s,
                           "source_published": s},
            "required": ["name", "position", "unit", "source_type", "source_url", "source_published"]}

    def equipo(eq):
        return {"type": "object", "additionalProperties": False,
                "properties": {"team": {"type": "string", "enum": [eq]}, "inactives_published": {"type": "boolean"},
                               "out": {"type": "array", "items": fuera}, "lineup": {"type": "array", "items": alin}},
                "required": ["team", "inactives_published", "out", "lineup"]}
    return {"type": "object", "additionalProperties": False, "properties": {"away": equipo(visita), "home": equipo(local)},
            "required": ["away", "home"]}


def a1_huella():
    """Huella de la configuración completa del vigía-alineador. Cambia → versión nueva (se anota en cada fila)."""
    return _huella(dict(modelo=CLAUDE_MODELO, sistema=A1_SISTEMA, usuario=A1_USUARIO, extrae=A1_EXTRAE,
                        herramienta=A1_HERRAMIENTA, esquema=json.dumps(a1_esquema("AAA", "BBB"), sort_keys=True),
                        max_tokens=A1_MAX_TOKENS, plazo=A1_PLAZO_S, reserva=A1_RESERVA_EXTRACCION_S, hilos=A1_HILOS))


def a1_cuerpo(j, momento):
    return {"model": CLAUDE_MODELO, "max_tokens": A1_MAX_TOKENS, "system": A1_SISTEMA,
            "messages": [{"role": "user", "content": A1_USUARIO.format(**_vars_juego(j, momento))}], "tools": [A1_HERRAMIENTA]}


def a1_cuerpo_extraer(j, texto, urls):
    return {"model": CLAUDE_MODELO, "max_tokens": A1_MAX_TOKENS, "system": A1_EXTRAE.format(visita=j["visita"], local=j["local"]),
            "messages": [{"role": "user", "content": "REPORT:\n" + texto[:60000] + "\n\nSEARCH RESULT URLS:\n"
                          + "\n".join(sorted(urls)[:400])}],
            "output_config": {"format": {"type": "json_schema", "schema": a1_esquema(j["visita"], j["local"])}}}


def a1_leer(obj, j):
    """JSON de la extracción → {equipo: dict(inactivos, fuera=[hechos], alineacion=[jugadores])} (solo equipos válidos)."""
    equipos = {}
    for lado, eq in (("away", j["visita"]), ("home", j["local"])):
        x = (obj or {}).get(lado)
        if not isinstance(x, dict) or DE_OTRAS.get(_texto(x.get("team")).upper(), _texto(x.get("team")).upper()) != eq:
            continue
        fuera, alin = [], []
        for p in (x.get("out") if isinstance(x.get("out"), list) else [])[:A1_MAX_FUERA]:
            if isinstance(p, dict):
                fuera.append(dict(nombre=_texto(p.get("name"))[:80], posicion=_texto(p.get("position")).upper()[:6],
                                  estado_jugador=_texto(p.get("status")).lower(), tipo_fuente=_texto(p.get("source_type")).lower(),
                                  url=_texto(p.get("source_url"))[:300], publicada=_texto(p.get("source_published"))[:25],
                                  evidencia=_texto(p.get("evidence"))[:200]))
        for p in (x.get("lineup") if isinstance(x.get("lineup"), list) else [])[:A1_MAX_ALIN]:
            if isinstance(p, dict):
                alin.append(dict(nombre=_texto(p.get("name"))[:80], posicion=_texto(p.get("position")).upper()[:6],
                                 unidad=_texto(p.get("unit")).lower(), tipo_fuente=_texto(p.get("source_type")).lower(),
                                 url=_texto(p.get("source_url"))[:300], publicada=_texto(p.get("source_published"))[:25]))
        ib = _e2_bool(x.get("inactives_published"))
        equipos[eq] = dict(inactivos="" if ib is None else int(ib), fuera=fuera, alineacion=alin)
    return equipos


def a1_consultar(j, momento, limite, origen, post=None):
    """Un juego: búsqueda con citas (Opus + web_search) y extracción a JSON con esquema (Opus, sin herramientas). Devuelve
    dict(estado, equipos, urls normalizadas, costo_usd, busquedas, latencia_s, detalle). Nunca lanza excepciones."""
    t0 = time.time()
    base = dict(equipos={}, urls=set(), costo_usd=0.0, busquedas=0, latencia_s=0.0, detalle="", forma="busqueda+extraccion",
                http="")
    reg = dict(agente="A1", origen=origen, huella=a1_huella(), game_id=j["game_id"], momento=momento)
    try:
        b = claude_post(a1_cuerpo(j, momento), limite - A1_RESERVA_EXTRACCION_S,
                        {**reg, "paso": "busqueda", "reserva_usd": A1_RESERVA_USD["busqueda"]}, post)
        base.update(costo_usd=b["costo_usd"], busquedas=b["busquedas"], http=b["http"])
        if b["estado"] not in ("ok", "cortada", "pausada") or not b["texto"].strip():
            return {**base, "estado": b["estado"] or "respuesta inválida", "detalle": b["detalle"] or "sin texto",
                    "latencia_s": round(time.time() - t0, 2)}
        urls = _urls_de(b["contenido"])
        base["urls"] = {_url_norm(u) for u in urls} - {""}
        errs = _errores_busqueda(b["contenido"])
        if not base["urls"]:                         # sin resultados no hay hechos válidos posibles: cuenta como falla
            return {**base, "estado": "sin búsqueda", "latencia_s": round(time.time() - t0, 2),
                    "detalle": ("errores de búsqueda: " + ", ".join(sorted(set(errs)))) if errs else "la búsqueda no trajo resultados"}
        e = claude_post(a1_cuerpo_extraer(j, b["texto"], urls), limite,
                        {**reg, "paso": "extraccion", "reserva_usd": A1_RESERVA_USD["extraccion"]}, post)
        base["costo_usd"] = round(base["costo_usd"] + e["costo_usd"], 6)
        if e["estado"] != "ok":
            return {**base, "estado": e["estado"], "detalle": ("extracción: " + (e["detalle"] or "")).strip(),
                    "http": e["http"], "latencia_s": round(time.time() - t0, 2)}
        equipos = a1_leer(_objeto_json(e["texto"]), j)
        estado = "ok" if len(equipos) == 2 else "parcial" if equipos else "respuesta inválida"
        det = {"ok": "", "parcial": "respondió un solo equipo válido"}.get(estado, "JSON sin equipos válidos")
        if b["estado"] != "ok":
            det = (det + " · " if det else "") + f"búsqueda {b['estado']}"
        if errs:
            det = (det + " · " if det else "") + "errores de búsqueda: " + ", ".join(sorted(set(errs)))
        return {**base, "equipos": equipos, "estado": estado, "detalle": det, "latencia_s": round(time.time() - t0, 2)}
    except Exception as ex:  # noqa: BLE001
        return {**base, "estado": "error", "detalle": type(ex).__name__, "latencia_s": round(time.time() - t0, 2)}


def a1_lanzar(juegos, ahora, origen, post=None):
    """Arranca el vigía-alineador en un hilo aparte y vuelve enseguida (la corrida sigue con g1, el vigía de Gemini y e2).
    juegos: [dict(game_id, semana, game_type, visita, local, inicio)]. Reparte el tope del día ANTES de consultar.
    Nunca consulta juegos empezados (H36). Devuelve el trabajo para a1_cerrar, o None si no corre (sin llave o apagado)."""
    try:
        resto, motivo = claude_cupo(ahora)
        if not CLAUDE_LLAVE.exists() or motivo.startswith("apagado"):
            return None
        momento = e2_momento(ahora)
        futuros = [j for j in juegos if j["inicio"] > momento]
        if not futuros:
            return None
        n = int(resto // A1_USD_JUEGO)
        a_consultar, sin_cupo = futuros[:n], futuros[n:]
        t0 = time.time()
        limite = t0 + A1_PLAZO_S
        res = {}

        def trabajar():
            from concurrent.futures import ThreadPoolExecutor, wait
            if not a_consultar:
                return
            ex = ThreadPoolExecutor(max_workers=A1_HILOS)
            futs = {ex.submit(a1_consultar, j, momento, limite, origen, post): j for j in a_consultar}
            hechos, _ = wait(futs, timeout=max(limite - time.time(), 0) + 2.0)
            for fu, j in futs.items():
                res[j["game_id"]] = (fu.result() if fu in hechos and fu.exception() is None else
                                     dict(equipos={}, urls=set(), estado="tiempo agotado", detalle="", costo_usd=0.0,
                                          busquedas=0, latencia_s=float(A1_PLAZO_S)))
            ex.shutdown(wait=False, cancel_futures=True)
        hilo = threading.Thread(target=trabajar, name="vigia-claude", daemon=True)
        hilo.start()
        log(f"Vigía-alineador Claude ({origen}): {len(a_consultar)} juegos en consulta"
            + (f", {len(sin_cupo)} sin cupo ({motivo or 'tope del día'})" if sin_cupo else ""))
        return dict(hilo=hilo, res=res, juegos=futuros, sin_cupo=sin_cupo, momento=momento, t0=t0, limite=limite,
                    origen=origen, motivo=motivo)
    except Exception as e:  # noqa: BLE001
        log(f"Vigía-alineador Claude: no arrancó ({type(e).__name__}); la corrida sigue")
        return None


def _a1_historia(ind, g26, roster):
    """(jugados: {pfr: [inicio de cada juego de 2026 con algún snap]}, exp: {gsis: years_exp del roster de nflverse})."""
    ini = {r["game_id"]: r["inicio"] for r in g26.iter_rows(named=True) if r.get("inicio") is not None}
    jug = {}
    for gid, pfrs in ind.jugaron.items():
        t = ini.get(gid)
        if t is not None:
            for p in pfrs:
                jug.setdefault(p, []).append(t)
    exp = {}
    for f in (roster.iter_rows(named=True) if roster is not None else []):
        g = _texto(f.get("gsis_id"))
        try:
            if g:
                exp[g] = int(float(f.get("years_exp")))
        except (TypeError, ValueError):
            pass
    return jug, exp


def _pfr_por_nombre(ind, eq, nombre):
    """El pfr de los snaps del equipo con ese nombre (para jugadores sin pfr en el roster), o ''."""
    n = _norm(nombre)
    if not n:
        return ""
    c = [p for p in ind.part.get(eq, {}) if _norm(ind.nom_pfr.get(p, "")) == n]
    return c[0] if len(c) == 1 else ""


def _a1_validar_alin(a, momento):
    """'' si el jugador de la alineación tiene fuente válida; si no, el motivo. La fecha es opcional (las tablas de
    profundidad casi nunca la muestran), pero si la hay no puede ser posterior a la consulta."""
    if not a["nombre"]:
        return "sin nombre"
    if a["unidad"] not in A1_UNIDADES:
        return "unidad desconocida"
    if a["tipo_fuente"] not in A1_TIPOS_ALIN:
        return "tipo de fuente desconocido"
    if not re.match(r"^https?://\S+$", a["url"]):
        return "sin URL"
    f = _fecha_fuente(a["publicada"]) if a["publicada"] else None
    if isinstance(f, dt.datetime) and f > momento + dt.timedelta(minutes=VIGIA_HOLGURA_MIN):
        return "fuente posterior a la consulta"
    if isinstance(f, dt.date) and not isinstance(f, dt.datetime) and f > momento.astimezone(dt.timezone.utc).date():
        return "fuente posterior a la consulta"
    return ""


def a1_cerrar(trab, filas_proy, g26):
    """Espera al hilo del vigía-alineador (hasta su plazo), cruza lo que trajo con el roster y los snaps (el código decide:
    titulares habituales, qué no sabe la máquina, quién no tiene historia en la NFL), escribe sus registros y devuelve el
    resumen para Telegram, o None. Nunca detiene la corrida."""
    if not trab:
        return None
    try:
        trab["hilo"].join(timeout=max(trab["limite"] - time.time(), 0) + 10.0)
        momento, origen, huella = trab["momento"], trab["origen"], a1_huella()
        snaps, roster = vigia_datos()
        ind = VigiaIndice(snaps, roster, g26)
        jug, exp = _a1_historia(ind, g26, roster)
        qb_usado = {}
        for f in filas_proy:
            qb_usado[(f["game_id"], f["local"])] = _texto(f.get("qb_local_id"))
            qb_usado[(f["game_id"], f["visita"])] = _texto(f.get("qb_visita_id"))
        res = dict(trab["res"])
        sin_cupo = {j["game_id"] for j in trab["sin_cupo"]}
        filas_c, filas_h, filas_a = [], [], []
        resumen = dict(momento=momento, origen=origen, huella=huella, semanas=sorted({j["semana"] for j in trab["juegos"]}),
                       juegos=[], costo=0.0, consultas=[0, 0], inactivos=[0, 0], alineacion=[0, 0],
                       inicio=min(j["inicio"] for j in trab["juegos"]), sin_roster=0)
        for j in trab["juegos"]:
            gid = j["game_id"]
            if gid in sin_cupo:
                x = dict(equipos={}, urls=set(), estado="tope", detalle=trab.get("motivo") or "tope del día en USD",
                         costo_usd=0.0, busquedas=0, latencia_s=0.0)
            else:
                x = res.get(gid) or dict(equipos={}, urls=set(), estado="tiempo agotado", detalle="", costo_usd=0.0,
                                         busquedas=0, latencia_s=float(A1_PLAZO_S))
            minutos = round((j["inicio"] - momento).total_seconds() / 60, 1)
            valida = int(minutos > 0)
            if x["estado"] != "tope":
                resumen["consultas"][1] += 1
                resumen["consultas"][0] += int(x["estado"] in ("ok", "parcial"))
            resumen["costo"] += float(x.get("costo_usd") or 0)
            tit = {eq: ind.titulares(eq, j["inicio"]) for eq in (j["visita"], j["local"])}
            avisos = {j["visita"]: {}, j["local"]: {}}
            nuevos = {j["visita"]: [], j["local"]: []}
            n_h = n_a = n_al = n_nu = 0
            for eq in (j["visita"], j["local"]):
                resumen["inactivos"][1] += 1
                resumen["alineacion"][1] += 1
                e = x["equipos"].get(eq)
                if not e:
                    continue
                resumen["inactivos"][0] += int(e.get("inactivos") == 1)
                resumen["alineacion"][0] += int(sum(1 for a in e["alineacion"] if a["unidad"] in ("offense", "defense")) >= 15)
                vistos = set()
                for h in e["fuera"]:
                    en_res = int(bool(h["url"]) and _url_norm(h["url"]) in x["urls"])
                    motivo = vigia_validar(h, momento) or ("" if en_res else "URL fuera de los resultados de búsqueda")
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
                    filas_h.append(dict(corrida_utc=iso(momento), game_id=gid, semana=j["semana"], modelo_clave="C", huella=huella,
                                        equipo=eq, nombre=h["nombre"], posicion=h["posicion"], estado_jugador=h["estado_jugador"],
                                        tipo_fuente=h["tipo_fuente"], url=h["url"], publicada=h["publicada"], evidencia=h["evidencia"],
                                        valido=int(not motivo), motivo_invalido=motivo, gsis_id=g, cruce=cruce,
                                        titular=int(tt is not None), part_media="" if tt is None else tt["part"],
                                        es_qb_usado=es_qb, aviso=aviso, minutos_antes=minutos,
                                        nombre_roster=ind.nombre.get(g, "") if g else "", origen=origen, url_en_resultados=en_res))
                    if aviso:
                        avisos[eq][g] = dict(nombre=ind.nombre.get(g) or h["nombre"], pos=pos, qb=es_qb, estado=h["estado_jugador"],
                                             fuente=h["tipo_fuente"])
                vistos_a = set()
                for a in e["alineacion"]:
                    en_res = int(bool(a["url"]) and _url_norm(a["url"]) in x["urls"])
                    motivo = _a1_validar_alin(a, momento) or ("" if en_res else "URL fuera de los resultados de búsqueda")
                    g, cruce = ind.gsis_por_nombre(eq, a["nombre"], a["posicion"]) if a["nombre"] else ("", "sin cruzar")
                    pfr = (ind.gsis_pfr.get(g, "") if g else "") or _pfr_por_nombre(ind, eq, a["nombre"])
                    jugados = sum(1 for t in jug.get(pfr, []) if t < j["inicio"]) if pfr else 0
                    ye = exp.get(g) if g else None
                    habit = bool(tit.get(eq) is not None and g and (g in tit[eq] or (pfr and f"pfr:{pfr}" in tit[eq])))
                    sin_hist = int(bool(g) and ye == 0 and jugados == 0)
                    sin_26 = int(bool(g) and (ye or 0) > 0 and jugados == 0)
                    nuevo = int(not motivo and valida == 1 and a["unidad"] in ("offense", "defense") and tit.get(eq) is not None
                                and bool(g) and not habit)
                    n_al += 1
                    if not motivo and not g:
                        resumen["sin_roster"] += 1
                    filas_a.append(dict(corrida_utc=iso(momento), game_id=gid, semana=j["semana"], origen=origen, huella=huella,
                                        equipo=eq, nombre=a["nombre"], posicion=a["posicion"], unidad=a["unidad"],
                                        tipo_fuente=a["tipo_fuente"], url=a["url"], publicada=a["publicada"],
                                        valido=int(not motivo), motivo_invalido=motivo, url_en_resultados=en_res, gsis_id=g,
                                        pfr_id=pfr, cruce=cruce, titular_habitual=int(habit), jugados_2026=jugados,
                                        years_exp="" if ye is None else ye, sin_historia=sin_hist, sin_2026=sin_26, nuevo=nuevo,
                                        minutos_antes=minutos, nombre_roster=ind.nombre.get(g, "") if g else ""))
                    clave_a = g or _norm(a["nombre"])
                    if not motivo and valida == 1 and (nuevo or sin_hist) and clave_a not in vistos_a:
                        vistos_a.add(clave_a)
                        n_nu += 1
                        nuevos[eq].append(dict(nombre=ind.nombre.get(g) or a["nombre"], pos=ind.pos.get(g) or a["posicion"],
                                               sin_hist=sin_hist, sin_26=sin_26, unidad=a["unidad"]))
            filas_c.append(dict(corrida_utc=iso(momento), game_id=gid, semana=j["semana"], game_type=j.get("game_type", "REG"),
                                inicio_utc=iso(j["inicio"]), minutos_antes=minutos, valida=valida, modelo_clave="C",
                                modelo=CLAUDE_MODELO, huella=huella, forma=x.get("forma", ""), model_version=CLAUDE_MODELO,
                                estado=x["estado"], http=x.get("http", ""), latencia_s=x.get("latencia_s", ""),
                                costo_usd=x.get("costo_usd", ""), busquedas=x.get("busquedas", ""),
                                evidencia_busqueda="resultados" if x.get("urls") else "ninguna",
                                inactivos_visita=(x["equipos"].get(j["visita"]) or {}).get("inactivos", ""),
                                inactivos_local=(x["equipos"].get(j["local"]) or {}).get("inactivos", ""),
                                titulares_visita=_tit_txt(tit[j["visita"]]), titulares_local=_tit_txt(tit[j["local"]]),
                                n_hechos=n_h, n_avisos=n_a, detalle=_texto(x.get("detalle"))[:300], origen=origen,
                                n_alineacion=n_al, n_nuevos=n_nu, n_urls=len(x.get("urls") or ())))
            resumen["juegos"].append(dict(game_id=gid, visita=j["visita"], local=j["local"], valida=valida, avisos=avisos,
                                          nuevos=nuevos, estado=x["estado"], detalle=_texto(x.get("detalle")),
                                          sin_titulares=[eq for eq in (j["visita"], j["local"]) if tit[eq] is None]))
        r_ = A1_RUTAS[origen]
        _anexar_csv(r_["consultas"], CAMPOS_A1C, filas_c, r_["consultas"].stem)
        _anexar_csv(r_["hechos"], CAMPOS_A1H, filas_h, r_["hechos"].stem)
        _anexar_csv(r_["alineacion"], CAMPOS_A1A, filas_a, r_["alineacion"].stem)
        n_av = sum(len(v) for jj in resumen["juegos"] for v in jj["avisos"].values())
        n_nu = sum(len(v) for jj in resumen["juegos"] for v in jj["nuevos"].values())
        log(f"Vigía-alineador Claude ({origen}, {CLAUDE_MODELO}, huella {huella}): {len(trab['juegos'])} juegos en "
            f"{time.time() - trab['t0']:.1f} s · consultas {resumen['consultas'][0]}/{resumen['consultas'][1]} · "
            f"{len(filas_h)} hechos · {n_av} avisos · {len(filas_a)} en la alineación · {n_nu} nuevos · USD {resumen['costo']:.4f}")
        return resumen
    except Exception as e:  # noqa: BLE001
        log(f"Vigía-alineador Claude: error ({type(e).__name__}: {str(e)[:200]}); la proyección y los demás agentes no se afectan")
        return None


def texto_a1(r):
    """Mensaje de Telegram del vigía-alineador (aparte; marcado piloto o «a pedido, no cuenta»)."""
    manual = r["origen"] == "manual"
    lin = [("🧭 VIGÍA-ALINEADOR CLAUDE A PEDIDO (no cuenta)" if manual else "🧭 VIGÍA-ALINEADOR CLAUDE · piloto 65.1")
           + f" · {CLAUDE_NOMBRE} · semana {', '.join(map(str, r['semanas']))} · juegos de las {fecha_cc(r['inicio'])} (Caracas)"]
    sin = []
    for jj in r["juegos"]:
        nombre = f"{jj['visita']} @ {jj['local']}"
        partes = []
        for eq in (jj["visita"], jj["local"]):
            av = jj["avisos"][eq]
            for a in [a for a in av.values() if a["qb"]]:
                partes.append(f"⚠️ {eq}: la máquina proyectó con {a['nombre']} y la fuente oficial lo da fuera "
                              f"({ESTADO_ES.get(a['estado'], a['estado'])} · {FUENTE_ES.get(a['fuente'], a['fuente'])})")
            otros = [a for a in av.values() if not a["qb"]]
            if otros:
                n = len(otros)
                partes.append(f"🔎 {eq}: falta{'n' if n > 1 else ''} {n} titular{'es' if n > 1 else ''} que la máquina no conoce: "
                              + ", ".join(f"{a['pos']} {a['nombre']} ({ESTADO_ES.get(a['estado'], a['estado'])} · "
                                          f"{FUENTE_ES.get(a['fuente'], a['fuente'])})" for a in otros))
            nu = jj["nuevos"][eq]
            if nu:
                n = len(nu)
                partes.append(f"🆕 {eq}: {n} titular{'es' if n > 1 else ''} nuevo{'s' if n > 1 else ''} en la alineación esperada: "
                              + ", ".join(f"{a['pos']} {a['nombre']}" + (" (primer partido en la NFL)" if a["sin_hist"] else
                                                                       " (no jugó en 2026)" if a["sin_26"] else "")
                                          for a in nu))
        if jj["estado"] not in ("ok", "parcial"):
            partes.append(f"sin respuesta ({jj['estado']}{': ' + jj['detalle'][:80] if jj['detalle'] else ''})")
        if not jj["valida"]:
            partes.append("consulta después del inicio (no cuenta)")
        if partes:
            lin.append(f"{nombre}:")
            lin += ["  " + p for p in partes]
        else:
            sin.append(nombre)
        if jj["sin_titulares"]:
            lin.append(f"  (sin titulares calculables todavía: {', '.join(jj['sin_titulares'])})")
    if sin:
        lin.append("Sin bajas de titulares ni titulares nuevos: " + ", ".join(sin))
    lin.append(f"Lista oficial de inactivos en {r['inactivos'][0]} de {r['inactivos'][1]} equipos · alineación completa en "
               f"{r['alineacion'][0]} de {r['alineacion'][1]} · consultas {r['consultas'][0]}/{r['consultas'][1]}"
               + (f" · {r['sin_roster']} nombres sin cruzar con el roster" if r.get("sin_roster") else "")
               + f" · USD {r['costo']:.2f}".replace(".", ","))
    lin.append("Solo hechos con URL de los resultados de búsqueda; el código decide quién es titular (snaps) y quién no tiene "
               "historia en la NFL (roster). No cambia la máquina ni las selecciones."
               + (" Registro aparte: no entra a ninguna medición." if manual else " La columna 🔎 de la hoja sigue siendo la de Gemini."))
    return "\n".join(lin)


# ---------------------------------------------------------------- A1 · medición con los snaps (código, sin IA)
def _metricas_juego(f, hs, ind):
    """Métricas de 55 de UNA consulta (fila de consultas) con sus hechos: hechos sobre titulares, verificables, correctos
    (no jugó), titulares que no jugaron y cuántos de ellos se avisaron. Igual que vigia_verificar."""
    gid = f["game_id"]
    vis, loc = gid.split("_")[-2], gid.split("_")[-1]
    m = dict(hechos=0, verificables=0, correctos=0, no_jugaron=0, avisados=0)
    avisados = {}
    for h in hs:
        if h["valido"] == "1" and h["estado_jugador"] in VIGIA_NO_JUEGA and h["gsis_id"]:
            avisados.setdefault(h["equipo"], set()).add(h["gsis_id"])
    vistos = set()
    for h in hs:
        if not (h["valido"] == "1" and h["titular"] == "1" and h["estado_jugador"] in VIGIA_NO_JUEGA and h["gsis_id"]):
            continue
        k = (h["equipo"], h["gsis_id"])
        if k in vistos:
            continue
        vistos.add(k)
        m["hechos"] += 1
        tt = _tit_leer(f["titulares_local"] if h["equipo"] == loc else f["titulares_visita"]).get(h["gsis_id"])
        jugo = ind.jugo(gid, h["gsis_id"], (tt or {}).get("pfr", ""))
        if jugo is not None:
            m["verificables"] += 1
            m["correctos"] += int(jugo == 0)
    for eq, col, ci in ((vis, "titulares_visita", "inactivos_visita"), (loc, "titulares_local", "inactivos_local")):
        if f.get(ci, "") == "":
            continue                                     # el modelo no respondió por ese equipo
        for g, d in _tit_leer(f[col]).items():
            jugo = ind.jugo(gid, g, d.get("pfr", ""))
            if jugo == 0:
                m["no_jugaron"] += 1
                m["avisados"] += int(g in avisados.get(eq, set()))
    return m


def _metricas_alin(f, als, ind):
    """Alineación de UNA consulta: titulares de ataque y defensa dados por Claude con participación ≥ 50 % en el partido
    (precisión) y titulares del partido que no eran habituales, cuántos estaban en su alineación (cobertura de nuevos)."""
    gid = f["game_id"]
    m = dict(alin=0, alin_ok=0, alin_sin_cruzar=0, nuevos_reales=0, nuevos_cubiertos=0)
    if gid not in ind.con_snaps:
        return m
    vis, loc = gid.split("_")[-2], gid.split("_")[-1]
    dados = {}
    for a in als:
        if a["valido"] != "1" or a["unidad"] not in ("offense", "defense"):
            continue
        pfr = a.get("pfr_id") or ind.gsis_pfr.get(a["gsis_id"], "") or _pfr_por_nombre(ind, a["equipo"], a["nombre"])
        if not pfr:
            m["alin_sin_cruzar"] += 1                    # no verificable con los snaps: se reporta aparte
            continue
        if (a["equipo"], pfr) in dados:
            continue
        dados[(a["equipo"], pfr)] = 1
        m["alin"] += 1
        m["alin_ok"] += int((ind.part.get(a["equipo"], {}).get(pfr, {}).get(gid) or 0.0) >= 0.5)
    for eq, col in ((vis, "titulares_visita"), (loc, "titulares_local")):
        if f.get(col, "") == "" or not any(k[0] == eq for k in dados):
            continue
        habit = {d.get("pfr") for d in _tit_leer(f[col]).values()}
        for pfr, partes in ind.part.get(eq, {}).items():
            if (partes.get(gid) or 0.0) >= 0.5 and pfr not in habit and ind.pos_pfr.get(pfr) not in VIGIA_SIN_TITULAR:
                m["nuevos_reales"] += 1
                m["nuevos_cubiertos"] += int((eq, pfr) in dados)
    return m


def a1_piloto_semanas(g26):
    """Semanas completas del piloto 65.1: una consulta T−85 válida de la huella actual en cada juego de la semana. Las
    2 primeras forman el piloto."""
    import polars as pl
    cons = [f for f in _leer_csv(A1_RUTAS["t85"]["consultas"]) if f.get("valida") == "1" and f.get("huella") == a1_huella()
            and f.get("estado") != "tope"]
    por_sem = {}
    for f in cons:
        por_sem.setdefault(int(f["semana"]), set()).add(f["game_id"])
    out = []
    for s_, ids in sorted(por_sem.items()):
        todos = set(g26.filter(pl.col("week") == s_)["game_id"].to_list())
        if todos and todos <= ids:
            out.append(s_)
    return out


def a1_verificar(g26):
    """Verificación del vigía-alineador con los snaps (por semana) y comparación con Gemini en los mismos juegos.
    Devuelve (métricas por semana, comparación por modelo de Gemini, juegos en común)."""
    cons = [f for f in _leer_csv(A1_RUTAS["t85"]["consultas"]) if f.get("valida") == "1" and f.get("huella") == a1_huella()
            and f.get("estado") != "tope"]
    if not cons:
        return {}, {}, 0
    hechos = _leer_csv(A1_RUTAS["t85"]["hechos"])
    alins = _leer_csv(A1_RUTAS["t85"]["alineacion"])
    snaps, roster = vigia_datos()
    ind = VigiaIndice(snaps, roster, g26)
    ult = {}
    for f in cons:
        if f["corrida_utc"] > ult.get(f["game_id"], {}).get("corrida_utc", ""):
            ult[f["game_id"]] = f
    met = {}
    juegos_c = {}
    for gid, f in ult.items():
        s_ = int(f["semana"])
        m = met.setdefault(s_, dict(consultas=0, fallas=0, hechos=0, verificables=0, correctos=0, no_jugaron=0, avisados=0,
                                    alin=0, alin_ok=0, alin_sin_cruzar=0, nuevos_reales=0, nuevos_cubiertos=0, sin_snaps=0))
        m["consultas"] += 1
        m["fallas"] += int(f["estado"] not in ("ok", "parcial"))
        if gid not in ind.con_snaps:
            m["sin_snaps"] += 1
            continue
        mj = _metricas_juego(f, [h for h in hechos if h["game_id"] == gid and h["corrida_utc"] == f["corrida_utc"]], ind)
        ma = _metricas_alin(f, [a for a in alins if a["game_id"] == gid and a["corrida_utc"] == f["corrida_utc"]], ind)
        for k, v in {**mj, **ma}.items():
            m[k] += v
        juegos_c[gid] = (f, mj)
    # Gemini (55) en los mismos juegos: huella actual de cada modelo, última consulta T−85 válida de cada juego
    gem = {}
    act = {c: vigia_huella(c) for c in VIGIA_MODELOS}
    cons_g = [f for f in _leer_csv(VIGIA_CONSULTAS) if f.get("valida") == "1" and f.get("huella") == act.get(f.get("modelo_clave"))
              and f.get("estado") != "tope" and f["game_id"] in juegos_c]
    ult_g = {}
    for f in cons_g:
        k = (f["game_id"], f["modelo_clave"])
        if f["corrida_utc"] > ult_g.get(k, {}).get("corrida_utc", ""):
            ult_g[k] = f
    hechos_g = _leer_csv(VIGIA_HECHOS) if ult_g else []
    comunes = {}
    for (gid, c), f in ult_g.items():
        mg = _metricas_juego(f, [h for h in hechos_g if h["game_id"] == gid and h["modelo_clave"] == c
                                 and h["corrida_utc"] == f["corrida_utc"]], ind)
        t = gem.setdefault(c, dict(juegos=0, fallas=0, hechos=0, verificables=0, correctos=0, no_jugaron=0, avisados=0))
        tc = comunes.setdefault(c, dict(juegos=0, fallas=0, hechos=0, verificables=0, correctos=0, no_jugaron=0, avisados=0))
        t["juegos"] += 1
        t["fallas"] += int(f["estado"] not in ("ok", "parcial"))
        for k, v in mg.items():
            t[k] += v
        fc, mc = juegos_c[gid]
        tc["juegos"] += 1
        tc["fallas"] += int(fc["estado"] not in ("ok", "parcial"))
        for k, v in mc.items():
            tc[k] += v
    return met, dict(gemini=gem, claude=comunes), len({g for g, _ in ult_g})


def _tasa(a, b):
    return (a / b) if b else None


def seccion_vigia_claude(g26):
    """65.1: verificación del vigía-alineador de Claude con los snaps, regla de 55 aplicada a Opus en el piloto y
    comparación con Gemini en los mismos juegos. ('', []) si todavía no hay consultas."""
    met, comp, n_com = a1_verificar(g26)
    if not met:
        return "", []
    sem_p = a1_piloto_semanas(g26)[:A1_PILOTO_SEMANAS]
    lin = [f"VIGÍA-ALINEADOR CLAUDE (65.1, {CLAUDE_NOMBRE}, huella {a1_huella()}): verificación con los snaps de nflverse (código, sin IA)"]
    for s_, m in sorted(met.items()):
        lin.append(f"  semana {s_}: {m['consultas']} consultas ({m['fallas']} fallidas) · fuera: hechos sobre titulares {m['hechos']}, "
                   f"verificables {m['verificables']}, correctos {m['correctos']} · precisión {_pct(_tasa(m['correctos'], m['verificables']), False)}"
                   f" · cobertura {_pct(_tasa(m['avisados'], m['no_jugaron']), False)} ({m['avisados']} de {m['no_jugaron']}) · "
                   f"alineación {_pct(_tasa(m['alin_ok'], m['alin']), False)} ({m['alin_ok']} de {m['alin']} jugaron ≥ 50 %"
                   + (f"; {m['alin_sin_cruzar']} sin cruzar con el roster, no verificables" if m["alin_sin_cruzar"] else "") + ") · "
                   f"titulares nuevos cubiertos {m['nuevos_cubiertos']} de {m['nuevos_reales']}"
                   + (f" · {m['sin_snaps']} juegos sin snaps todavía" if m["sin_snaps"] else ""))
    t = {k: sum(met[s_][k] for s_ in sem_p) for k in ("consultas", "fallas", "verificables", "correctos", "avisados", "no_jugaron")}
    if len(sem_p) >= A1_PILOTO_SEMANAS and not any(met[s_]["sin_snaps"] for s_ in sem_p):
        prec, fal = _tasa(t["correctos"], t["verificables"]), _tasa(t["fallas"], t["consultas"])
        eleg = prec is not None and prec >= VIGIA_MIN_PRECISION and t["verificables"] >= VIGIA_MIN_HECHOS and (fal or 0) <= VIGIA_MAX_FALLAS
        piloto = (f"Piloto 65.1 (semanas {', '.join(map(str, sem_p))}): regla de 55 aplicada a Opus → "
                  f"{'ELEGIBLE' if eleg else 'NO elegible'} (precisión {_pct(prec, False)} con {t['verificables']} hechos, "
                  f"fallas {_pct(fal, False)}, cobertura {_pct(_tasa(t['avisados'], t['no_jugaron']), False)}). "
                  "Retirar o no a Gemini lo decide Ozz con estos números.")
    else:
        piloto = (f"Piloto 65.1: en curso ({len(sem_p)} de {A1_PILOTO_SEMANAS} semanas completas"
                  + (f": {', '.join(map(str, sem_p))}" if sem_p else "") + "; cuenta una semana con consulta T−85 en todos sus juegos)")
    lin.append("  " + piloto)
    comp_txt = ""
    if n_com:
        el = (leer_estado().get("vigia") or {}).get("elegido")
        claves = [el["clave"]] if el and el.get("clave") in comp["gemini"] else sorted(comp["gemini"])
        partes = []
        for c in claves:
            g, cl = comp["gemini"][c], comp["claude"][c]
            partes.append(f"{VIGIA_NOMBRE[c]}: precisión {_pct(_tasa(g['correctos'], g['verificables']), False)} "
                          f"({g['correctos']} de {g['verificables']}), cobertura {_pct(_tasa(g['avisados'], g['no_jugaron']), False)} "
                          f"contra Opus {_pct(_tasa(cl['correctos'], cl['verificables']), False)} y "
                          f"{_pct(_tasa(cl['avisados'], cl['no_jugaron']), False)} en los mismos {g['juegos']} juegos")
        comp_txt = "En los mismos juegos que Gemini: " + " · ".join(partes)
        lin.append("  " + comp_txt)
    tot = {k: sum(m[k] for m in met.values()) for k in ("correctos", "verificables", "avisados", "no_jugaron", "alin_ok", "alin")}
    tel = (f"Vigía-alineador Claude (65.1): precisión {_pct(_tasa(tot['correctos'], tot['verificables']), False)} "
           f"({tot['correctos']} de {tot['verificables']}), cobertura {_pct(_tasa(tot['avisados'], tot['no_jugaron']), False)}, "
           f"alineación {_pct(_tasa(tot['alin_ok'], tot['alin']), False)} · {piloto}" + (f" · {comp_txt}" if comp_txt else ""))
    return tel, lin


def texto_claude_estado(ahora, estado):
    """Conteos de los agentes de Claude para el modo estado (y /estado por Telegram)."""
    activo, tope = claude_cfg()
    hoy = ahora.astimezone(CARACAS).date().isoformat()
    cab = (f"Agentes de Claude (65.1, {CLAUDE_NOMBRE}): "
           + ("llave presente" if CLAUDE_LLAVE.exists() else "SIN llave (credenciales/anthropic.key): no corren")
           + f" · {'activos' if activo else 'APAGADOS en semana.ini [claude_motor]'} · hoy USD {claude_gasto_hoy(hoy):.2f} de {tope:.2f}"
           + f" · huellas A1 {a1_huella()}, A3 {a3_huella()}, A4 {a4_huella()}")
    cons = [f for f in _leer_csv(A1_RUTAS["t85"]["consultas"]) if f.get("valida") == "1"]
    av = sum(int(f.get("n_avisos") or 0) for f in cons)
    nu = sum(int(f.get("n_nuevos") or 0) for f in cons)
    lin = [cab,
           f"  Vigía-alineador (A1): {len(cons)} consultas T−85 en {len({f['game_id'] for f in cons})} juegos "
           f"({sum(1 for f in cons if f.get('estado') not in ('ok', 'parcial', 'tope'))} fallidas) · {av} avisos · {nu} titulares nuevos"
           f" · /vigia hoy {estado.get('vigia_manual_dia', {}).get(hoy, 0)} de {VIGIA_MANUAL_MAX_DIA}"]
    aut = sorted(estado.get("autopsias", {}), key=int)
    bri = sorted(estado.get("briefing", {}), key=int)
    lin.append(f"  Autopsia (A3): semanas {', '.join(aut) or 'ninguna todavía'} (automática desde la semana {A3_DESDE}) · "
               f"Analista del sábado (A4): semanas {', '.join(bri) or 'ninguna todavía'} · /briefing hoy "
               f"{estado.get('briefing_dia', {}).get(hoy, 0)} de {A4_MAX_DIA}")
    return "\n".join(lin)


# ---------------------------------------------------------------- A3 · autopsia del lunes
A3_HERRAMIENTA = {"type": CLAUDE_BUSQUEDA, "name": "web_search", "max_uses": 3, "allowed_domains": ["espn.com", "nfl.com"]}
A3_MAX_TOKENS = 4000                               # v9.1: el código del filtrado dinámico también cuenta como salida
A3_PLAZO_S = 240
A3_HILOS = 8
A3_USD_JUEGO = 0.25
A3_DESDE = 7                                       # automática desde la semana 7 (la primera después de instalar)
COEF_H41 = dict(perdidas=3.335, ee=0.692, neto=35.49)  # pts por balón, por punto de EPA de EE y por 1,0 de EPA/jugada (H41)
CAUSA_ES = {"perdidas": "pérdidas de balón", "ee": "equipos especiales", "neto": "jugó peor (sin contar pérdidas)",
            "ninguna": "ninguna de las tres (lo no medido)"}
AUTOPSIA_CLAUDE = SAL / "autopsia_claude.csv"
CAMPOS_A3 = ["corrida_utc", "origen", "huella", "semana", "game_id", "juego", "favorito", "ganador", "fuente_favorito",
             "p_favorito", "esperado_pts", "resultado", "margen_favorito", "sorpresa_pts", "perdidas_dif", "perdidas_pts",
             "ee_epa", "ee_pts", "neto_sin", "neto_pts", "explicado_pts", "cerrado", "ultima_serie", "cambio_qb", "qb_inicio",
             "qb_final", "causa", "texto", "url", "estado", "costo_usd", "detalle"]
A3_SISTEMA = """You explain, for a Spanish-speaking audience, why the betting favorite lost an NFL game. Search the official
game recap on espn.com or nfl.com and rely only on it and on the numbers given. Write in Spanish, at most 70 words, plain
text without lists: the plays that decided the game (turnovers, special teams, the last drive, an injury) as the recap
reports them. Do not predict, do not give betting advice, do not invent quotes."""
A3_USUARIO = """Game: {visita_nombre} at {local_nombre} (NFL {temporada}, week {semana}). Final: {resultado}.
The favorite at the close was {favorito} and lost.
Computed from the play-by-play, from the favorite's side: turnover differential {perd}; special-teams EPA {ee}; EPA per
play without turnovers {neto}; close game (8 points or less): {cerrado}; decided on the last drive: {ultima}; quarterback
change during the game: {cambio}."""
A3_COLS = ["game_id", "play_id", "posteam", "defteam", "home_team", "away_team", "qtr", "game_seconds_remaining",
           "total_home_score", "total_away_score", "play_type", "special_teams_play", "epa", "interception", "fumble",
           "fumble_lost", "qb_dropback", "passer_player_id", "passer_player_name", "rusher_player_id", "rusher_player_name"]


def a3_huella():
    return _huella(dict(modelo=CLAUDE_MODELO, sistema=A3_SISTEMA, usuario=A3_USUARIO, herramienta=A3_HERRAMIENTA,
                        max_tokens=A3_MAX_TOKENS, plazo=A3_PLAZO_S, coef=COEF_H41))


def _pbp_columnas(cols, ids=None):
    """Jugada por jugada de 2026 con esas columnas (la misma copia que baja pbp_temporada), solo esos juegos."""
    import polars as pl
    pbp_temporada()
    ruta = DATOS / f"pbp_{TEMPORADA}.parquet"
    if not ruta.exists():
        return None
    esquema = pl.read_parquet_schema(ruta)
    df = pl.read_parquet(ruta, columns=[c for c in cols if c in esquema])
    return df.filter(pl.col("game_id").is_in(list(ids))) if ids is not None else df


def _a3_causas(q, fav, dog):
    """Causas de H41 de un juego vistas por el favorito, con las definiciones del estudio (perdidas.py y ee_completo.py
    del registro 64), más partido cerrado, última serie y cambio de QB. q: jugadas del juego (polars)."""
    import polars as pl
    q = q.sort("play_id")
    j = q.filter(pl.col("play_type").is_in(["pass", "run"]) & pl.col("epa").is_not_null())

    def entregas(t):
        intc = int(j.filter(pl.col("posteam") == t)["interception"].fill_null(0).sum())
        fum = int(q.filter((pl.col("fumble").fill_null(0) == 1) & (pl.col("posteam") == t))["fumble_lost"].fill_null(0).sum())
        return intc + fum
    perd = entregas(dog) - entregas(fav)
    st = q.filter(((pl.col("special_teams_play").fill_null(0) == 1)
                   | pl.col("play_type").is_in(["field_goal", "extra_point", "punt", "kickoff"])) & pl.col("epa").is_not_null())
    ee = float(st.filter(pl.col("posteam") == fav)["epa"].sum() or 0.0) - float(st.filter(pl.col("defteam") == fav)["epa"].sum() or 0.0)
    lim = j.filter((pl.col("interception").fill_null(0) != 1) & (pl.col("fumble_lost").fill_null(0) != 1))
    of, de = lim.filter(pl.col("posteam") == fav)["epa"], lim.filter(pl.col("defteam") == fav)["epa"]
    neto = (float(of.mean()) - float(de.mean())) if of.len() and de.len() else None
    # última serie: el ganador (dog) toma la ventaja definitiva con ≤ 2:00 del 4.º cuarto o en tiempo extra
    dog_local = q["home_team"][0] == dog if q.height else False
    ultimo, lider_prev = None, False
    for qtr, gsr, h, a in q.select(["qtr", "game_seconds_remaining", "total_home_score", "total_away_score"]).drop_nulls(
            ["total_home_score", "total_away_score"]).iter_rows():
        lider = ((h - a) if dog_local else (a - h)) > 0
        if lider and not lider_prev:
            ultimo = (qtr, gsr)
        lider_prev = lider
    ultima = None if ultimo is None else bool((ultimo[0] or 0) >= 5 or ((ultimo[0] or 0) == 4 and (ultimo[1] if ultimo[1] is not None else 9e9) <= 120))
    # cambio de QB: el QB con más dropbacks del 2.º tiempo no es el del primer dropback
    d = q.filter((pl.col("posteam") == fav) & (pl.col("qb_dropback").fill_null(0) == 1)).with_columns(
        pl.coalesce([pl.col("passer_player_id"), pl.col("rusher_player_id")]).alias("qb"),
        pl.coalesce([pl.col("passer_player_name"), pl.col("rusher_player_name")]).alias("qb_n")).filter(pl.col("qb").is_not_null())
    cambio, q0, qf = None, "", ""
    if d.height:
        q0 = _texto(d["qb_n"][0])
        s2_ = d.filter(pl.col("qtr") >= 3)
        if s2_.height:
            top = s2_.group_by(["qb", "qb_n"]).len().sort(["len", "qb"], descending=[True, False]).row(0)
            cambio, qf = bool(top[0] != d["qb"][0]), _texto(top[1])
    return dict(perdidas_dif=perd, ee_epa=round(ee, 2), neto_sin=None if neto is None else round(neto, 4), ultima_serie=ultima,
                cambio_qb=cambio, qb_inicio=q0, qb_final=qf)


def autopsia_calcular(g26, semana, bot_dir):
    """Juegos de la semana con resultado en que perdió el favorito del cierre (Pinnacle sin vig del bot; si no hay,
    nflverse), con las causas de H41 pasadas a puntos con sus coeficientes. Sin empates ni pick'em."""
    info, _sen, cierre = datos_semana(g26, semana, bot_dir)
    filas = []
    for gid, g in sorted(info.items(), key=lambda kv: (kv[1].get("inicio") or dt.datetime.max.replace(tzinfo=dt.timezone.utc), kv[0])):
        res = _num(g.get("result"))
        if res is None or abs(res) < 1e-9:
            continue
        loc, vis = g["home_team"], g["away_team"]
        c = cierre.get(gid)
        p_loc = (sin_vig_potencia(c["ml_local"], c["ml_visit"]) if c and c.get("ml_local") is not None
                 and c.get("ml_visit") is not None else None)
        sl = _num(g.get("spread_line"))
        hcp = _num(c.get("hcp_local")) if c else None
        if p_loc is not None and abs(p_loc - 0.5) > 1e-9:
            fav, fuente = (loc if p_loc > 0.5 else vis), "Pinnacle"
            p_fav = p_loc if fav == loc else 1.0 - p_loc
        elif sl is not None and abs(sl) > 1e-9:
            fav, fuente, p_fav = (loc if sl > 0 else vis), "nflverse", None
        else:
            continue
        esp_loc = -hcp if hcp is not None else sl                  # margen esperado del local en el cierre
        esperado = None if esp_loc is None else (esp_loc if fav == loc else -esp_loc)
        margen = res if fav == loc else -res
        if margen > 0:
            continue
        dog = vis if fav == loc else loc
        filas.append(dict(semana=semana, game_id=gid, juego=f"{vis} @ {loc}", favorito=fav, ganador=dog, fuente_favorito=fuente,
                          p_favorito=None if p_fav is None else round(p_fav, 4), esperado_pts=esperado, resultado=resultado_txt(g),
                          margen_favorito=margen, sorpresa_pts=None if esperado is None else round(margen - esperado, 1),
                          cerrado=int(abs(res) <= 8), visita=vis, local=loc))
    if not filas:
        return filas
    p = _pbp_columnas(A3_COLS, [f["game_id"] for f in filas])
    for f in filas:
        q = p.filter(p["game_id"] == f["game_id"]) if p is not None else None
        if q is None or q.height == 0:
            f["estado_pbp"] = "sin jugada por jugada"
            continue
        f.update(_a3_causas(q, f["favorito"], f["ganador"]))
        pts = dict(perdidas=COEF_H41["perdidas"] * f["perdidas_dif"], ee=COEF_H41["ee"] * f["ee_epa"],
                   neto=None if f["neto_sin"] is None else COEF_H41["neto"] * f["neto_sin"])
        f["perdidas_pts"], f["ee_pts"] = round(pts["perdidas"], 1), round(pts["ee"], 1)
        f["neto_pts"] = None if pts["neto"] is None else round(pts["neto"], 1)
        val = {k: v for k, v in pts.items() if v is not None}
        f["explicado_pts"] = round(sum(val.values()), 1)
        k_min = min(val, key=val.get) if val else None
        f["causa"] = k_min if k_min is not None and val[k_min] < 0 else "ninguna"
    return filas


def a3_cuerpo(f):
    sino = lambda v: "unknown" if v is None else ("yes" if v else "no")  # noqa: E731
    txt = A3_USUARIO.format(visita_nombre=EQUIPOS.get(f["visita"], f["visita"]), local_nombre=EQUIPOS.get(f["local"], f["local"]),
                            temporada=TEMPORADA, semana=f["semana"], resultado=f["resultado"],
                            favorito=EQUIPOS.get(f["favorito"], f["favorito"]),
                            perd="unknown" if f.get("perdidas_dif") is None else f"{f['perdidas_dif']:+d}",
                            ee="unknown" if f.get("ee_epa") is None else f"{f['ee_epa']:+.1f}",
                            neto="unknown" if f.get("neto_sin") is None else f"{f['neto_sin']:+.3f}",
                            cerrado=sino(f.get("cerrado")), ultima=sino(f.get("ultima_serie")),
                            cambio=("unknown" if f.get("cambio_qb") is None else
                                    f"yes ({f.get('qb_inicio')} to {f.get('qb_final')})" if f["cambio_qb"] else "no"))
    return {"model": CLAUDE_MODELO, "max_tokens": A3_MAX_TOKENS, "system": A3_SISTEMA,
            "messages": [{"role": "user", "content": txt}], "tools": [A3_HERRAMIENTA]}


def _a3_narrar(f, limite, origen, momento, post=None):
    reg = dict(agente="A3", origen=origen, huella=a3_huella(), game_id=f["game_id"], paso="cronica", momento=momento,
               reserva_usd=A3_USD_JUEGO)
    r = claude_post(a3_cuerpo(f), limite, reg, post)
    texto = re.sub(r"\s+", " ", r["texto"]).strip()
    urls = []
    for b in r["contenido"]:
        for c in (b.get("citations") or []) if isinstance(b, dict) else []:
            u = _texto((c or {}).get("url"))
            if u and u not in urls:
                urls.append(u)
    return dict(texto=texto[:700], url=urls[0] if urls else "", estado=r["estado"], costo_usd=r["costo_usd"], detalle=r["detalle"])


def _pts_txt(x, dec=1):
    """+1,5 / −2,0 (signo de menos tipográfico); 0 sin signo."""
    if x is None:
        return "—"
    if round(x, dec) == 0:
        return f"{0:.{dec}f}".replace(".", ",")
    return f"{x:+.{dec}f}".replace(".", ",").replace("-", "−")


def autopsia_enviar(g26, semana, bot_dir, ahora, estado, origen, sin_telegram=False, post=None):
    """A3: calcula las causas (código), pide a Opus la crónica corta de cada juego (en paralelo, con plazo y tope del día),
    guarda las filas en autopsia_claude.csv y manda el mensaje con el acumulado por causa. Devuelve una línea de resumen."""
    from concurrent.futures import ThreadPoolExecutor, wait
    filas = autopsia_calcular(g26, semana, bot_dir)
    resto, motivo = claude_cupo(ahora)
    n = min(len(filas), int(resto // A3_USD_JUEGO)) if not motivo.startswith(("sin", "apagado")) else 0
    narr = {}
    if n:
        limite = time.time() + A3_PLAZO_S
        ex = ThreadPoolExecutor(max_workers=A3_HILOS)
        momento = e2_momento(ahora)
        futs = {ex.submit(_a3_narrar, f, limite, origen, momento, post): f["game_id"] for f in filas[:n]}
        hechos, _ = wait(futs, timeout=A3_PLAZO_S + 5)
        for fu, gid in futs.items():
            narr[gid] = (fu.result() if fu in hechos and fu.exception() is None else
                         dict(texto="", url="", estado="tiempo agotado", costo_usd=0.0, detalle=""))
        ex.shutdown(wait=False, cancel_futures=True)
    huella = a3_huella()
    for f in filas:
        x = narr.get(f["game_id"]) or dict(texto="", url="", estado="sin Claude", costo_usd=0.0,
                                           detalle=motivo or "tope del día en USD")
        f.update(corrida_utc=iso(ahora), origen=origen, huella=huella, texto=x["texto"], url=x["url"], estado=x["estado"],
                 costo_usd=x["costo_usd"], detalle=_texto(x["detalle"])[:200])
    _anexar_csv(AUTOPSIA_CLAUDE, CAMPOS_A3, filas, "autopsia_claude")
    import polars as pl
    n_jug = g26.filter((pl.col("week") == semana) & pl.col("result").is_not_null()).height
    n_tot = g26.filter(pl.col("week") == semana).height
    lin = [f"🩺 AUTOPSIA DEL LUNES · semana {semana}{' (a pedido)' if origen != 'auto' else ''} · {CLAUDE_NOMBRE} · "
           f"{len(filas)} favorito{'s' if len(filas) != 1 else ''} del cierre perdi{'eron' if len(filas) != 1 else 'ó'} "
           f"(de {n_jug} juegos jugados{'' if n_jug == n_tot else f', faltan {n_tot - n_jug}'})"]
    for f in filas:
        prob = f" ({_pct(f['p_favorito'], False)})" if f.get("p_favorito") is not None else ""
        esp = f"por {_num_txt(abs(f['esperado_pts']), False)}" if f.get("esperado_pts") is not None else ""
        lin.append(f"• {f['juego']}: el cierre daba a {f['favorito']}{prob} {esp}; terminó {f['resultado']}"
                   + (f" · sorpresa {_pts_txt(f['sorpresa_pts'])} pts" if f.get("sorpresa_pts") is not None else ""))
        if f.get("estado_pbp"):
            lin.append(f"  {f['estado_pbp']} todavía: sin causas")
        else:
            extra = [x for x, si in (("cerrado (≤ 8)", f.get("cerrado")), ("decidido en la última serie", f.get("ultima_serie")),
                                     (f"cambio de QB en el partido ({f.get('qb_inicio')} → {f.get('qb_final')})", f.get("cambio_qb")))
                     if si]
            lin.append(f"  pérdidas {_pts_txt(f['perdidas_dif'], 0) if f['perdidas_dif'] else '0'} (≈ {_pts_txt(f['perdidas_pts'])} pts) · equipos especiales "
                       f"{_pts_txt(f['ee_epa'])} EPA (≈ {_pts_txt(f['ee_pts'])} pts) · juego sin pérdidas {_pts_txt(f['neto_sin'], 3)} "
                       f"EPA por jugada (≈ {_pts_txt(f['neto_pts'])} pts)" + (" · " + " · ".join(extra) if extra else "")
                       + f" · causa principal: {CAUSA_ES[f['causa']]}")
        if f.get("texto"):
            lin.append(f"  Opus: {f['texto']}" + (f" ({f['url']})" if f.get("url") else ""))
        elif f.get("estado") not in ("ok",):
            lin.append(f"  (sin crónica: {f.get('estado')}{' · ' + f['detalle'][:60] if f.get('detalle') else ''})")
    if not filas:
        lin.append("Ningún favorito del cierre perdió (o todavía no hay resultados).")
    # acumulado: la última autopsia de cada juego (cualquier origen)
    ult = {}
    for r in _leer_csv(AUTOPSIA_CLAUDE):
        if r.get("corrida_utc", "") >= ult.get(r["game_id"], {}).get("corrida_utc", ""):
            ult[r["game_id"]] = r
    cuenta, n_u, n_c = {}, 0, 0
    for r in ult.values():
        if r.get("causa"):
            cuenta[r["causa"]] = cuenta.get(r["causa"], 0) + 1
        n_u += int(r.get("ultima_serie") == "True")
        n_c += int(r.get("cerrado") == "1")
    sem_a = sorted({int(r["semana"]) for r in ult.values()})
    if ult:
        lin.append(f"Acumulado 2026 (semanas {', '.join(map(str, sem_a))}; {len(ult)} favoritos que perdieron): causa principal "
                   + " · ".join(f"{CAUSA_ES[k]} {v}" for k, v in sorted(cuenta.items(), key=lambda kv: -kv[1]))
                   + f" · cerrados {n_c} · decididos en la última serie {n_u}")
    costo = sum(_f(f.get("costo_usd")) for f in filas)
    lin.append("Puntos de cada causa con los coeficientes de H41 (2006-2025: 3,34 pts por balón, 0,69 por punto de EPA de equipos "
               "especiales, 35,5 por 1,0 de EPA por jugada). H41: pérdidas y equipos especiales casi no se repiten de un partido "
               "al siguiente. Descriptivo: no cuenta para nada · " + f"USD {costo:.2f}".replace(".", ","))
    enviar_tg("\n".join(lin), sin_telegram)
    if origen == "auto":
        estado.setdefault("autopsias", {})[str(semana)] = iso(ahora)
    log(f"Autopsia (A3) semana {semana} ({origen}): {len(filas)} juegos, {sum(1 for f in filas if f.get('texto'))} con crónica, "
        f"USD {costo:.4f}")
    return f"Autopsia de la semana {semana}: {len(filas)} favoritos que perdieron; mensaje enviado."


def autopsias_pendientes(estado):
    """Semanas desde A3_DESDE cuyo informe semanal ya salió y que no tienen autopsia automática."""
    hechos = set(estado.get("autopsias", {}))
    return sorted(int(s) for s in estado.get("informes", {}) if int(s) >= A3_DESDE and s not in hechos)


def semana_reciente(g26):
    """La semana del último juego con resultado (para /autopsia sin número)."""
    import polars as pl
    j = g26.filter(pl.col("result").is_not_null()).sort("inicio")
    return int(j["week"][-1]) if j.height else None


# ---------------------------------------------------------------- A4 · analista del sábado
A4_DOMINIOS = ["nfl.com", "espn.com", "nbcsports.com"] + [DOMINIOS_EQUIPOS[e] for e in sorted(DOMINIOS_EQUIPOS)]
A4_HERRAMIENTA = {"type": CLAUDE_BUSQUEDA, "name": "web_search", "max_uses": 12, "allowed_domains": A4_DOMINIOS}
A4_MAX_TOKENS = 20000                              # v9.1: idem
A4_PLAZO_S = 600                                   # búsqueda hasta 480 s + 120 s reservados para la extracción
A4_USD = 2.0                                        # reserva para el tope del día
A4_MAX_DIA = 3                                      # /briefing por día de Caracas
BRIEFINGS = SAL / "briefing"
A4_SISTEMA = """You are an NFL analyst preparing a Saturday briefing in Spanish for a betting research lab. Use web search.
For every game listed: (1) each team's position in this week's NFL.com power rankings and in this week's Pro Football
Talk (PFT, nbcsports.com) power rankings; (2) the players ruled Out, Doubtful or placed on injured reserve in the final
official injury report or official roster moves, and the starting quarterback's status if he is Questionable; (3) an
opinion in Spanish of at most 35 words saying which team is more likely to win and why, using the lab data given and what
you found. Rules: only facts from pages in your search results, each with its URL; never guess a ranking; never recommend
a bet; the betting market already prices official injuries, so never present an injury as an edge. Write a plain report,
one block per game, plus the URLs of the two power rankings."""
A4_USUARIO = """Today: {hoy} ET. NFL {temporada}, week {semana}.
Lab data per game (our rank 1-32 = net EPA per play this season; form = last 2 games against the season average; market =
Pinnacle no-vig win probability):
{tabla}"""
A4_EXTRAE = """Convert the briefing report below into JSON following the schema exactly. Copy rankings, names and URLs exactly as
in the report; use 0 for a ranking the report does not give; keep a URL only if it appears in the SEARCH RESULT URLS list
(otherwise leave it empty); opinions in Spanish, at most 35 words; do not add anything that is not in the report."""
A4_ESTADOS = ("out", "doubtful", "injured_reserve", "questionable", "suspended")
FLECHAS = [(0.15, "↑↑"), (0.05, "↑"), (-0.05, "="), (-0.15, "↓")]


def a4_esquema(ids):
    s = {"type": "string"}
    baja = {"type": "object", "additionalProperties": False,
            "properties": {"name": s, "position": s, "status": {"type": "string", "enum": list(A4_ESTADOS)}, "source_url": s},
            "required": ["name", "position", "status", "source_url"]}
    eq = {"type": "object", "additionalProperties": False,
          "properties": {"rank_nflcom": {"type": "integer"}, "rank_pft": {"type": "integer"},
                         "injuries": {"type": "array", "items": baja}},
          "required": ["rank_nflcom", "rank_pft", "injuries"]}
    juego = {"type": "object", "additionalProperties": False,
             "properties": {"game_id": {"type": "string", "enum": list(ids)}, "away": eq, "home": eq, "opinion": s},
             "required": ["game_id", "away", "home", "opinion"]}
    fuente = {"type": "object", "additionalProperties": False,
              "properties": {"outlet": {"type": "string", "enum": ["NFL.com", "PFT"]}, "url": s}, "required": ["outlet", "url"]}
    return {"type": "object", "additionalProperties": False,
            "properties": {"games": {"type": "array", "items": juego}, "ranking_sources": {"type": "array", "items": fuente}},
            "required": ["games", "ranking_sources"]}


def a4_huella():
    return _huella(dict(modelo=CLAUDE_MODELO, sistema=A4_SISTEMA, usuario=A4_USUARIO, extrae=A4_EXTRAE, herramienta=A4_HERRAMIENTA,
                        esquema=json.dumps(a4_esquema(["X"]), sort_keys=True), max_tokens=A4_MAX_TOKENS, plazo=A4_PLAZO_S,
                        flechas=FLECHAS))


def _flecha(d):
    if d is None:
        return "—"
    for umbral, f in FLECHAS:
        if d >= umbral:
            return f
    return "↓↓"


def a4_equipos(g26, hasta):
    """{equipo: dict(record, rank, neto, forma, d_forma, jugados)}: EPA neto por jugada de 2026 (ataque − defensa, pases y
    corridas con EPA) en los juegos con resultado antes de 'hasta'; forma = EPA neto de los últimos 2 partidos − temporada."""
    import polars as pl
    jugados = g26.filter(pl.col("result").is_not_null() & (pl.col("inicio") < hasta)).sort("inicio")
    rec = {}
    for r in jugados.iter_rows(named=True):
        for eq, m in ((r["home_team"], r["result"]), (r["away_team"], -r["result"])):
            w = rec.setdefault(eq, [0, 0, 0])
            w[0 if m > 0 else 1 if m < 0 else 2] += 1
    p = _pbp_columnas(["game_id", "posteam", "defteam", "play_type", "epa"], jugados["game_id"].to_list())
    out = {}
    if p is None:
        return out
    j = p.filter(pl.col("play_type").is_in(["pass", "run"]) & pl.col("epa").is_not_null())
    of = j.group_by(["game_id", "posteam"]).agg(pl.col("epa").sum().alias("s"), pl.len().alias("n")).rename({"posteam": "eq"})
    de = j.group_by(["game_id", "defteam"]).agg(pl.col("epa").sum().alias("sd"), pl.len().alias("nd")).rename({"defteam": "eq"})
    x = of.join(de, on=["game_id", "eq"], how="inner")
    orden = {gid: i for i, gid in enumerate(jugados["game_id"].to_list())}
    por_eq = {}
    for r in x.iter_rows(named=True):
        por_eq.setdefault(r["eq"], []).append((orden.get(r["game_id"], 0), r["s"], r["n"], r["sd"], r["nd"]))
    netos = {}
    for eq, v in por_eq.items():
        v.sort()
        neto = sum(a[1] for a in v) / max(sum(a[2] for a in v), 1) - sum(a[3] for a in v) / max(sum(a[4] for a in v), 1)
        ult = [a[1] / max(a[2], 1) - a[3] / max(a[4], 1) for a in v[-2:]]
        d = (sum(ult) / len(ult) - neto) if len(v) >= 3 else None
        netos[eq] = neto
        out[eq] = dict(record="-".join(map(str, rec.get(eq, [0, 0, 0])[:2])) + (f"-{rec[eq][2]}" if rec.get(eq, [0, 0, 0])[2] else ""),
                       neto=round(neto, 3), d_forma=None if d is None else round(d, 3), forma=_flecha(d), jugados=len(v))
    for i, eq in enumerate(sorted(netos, key=lambda e: -netos[e]), 1):
        out[eq]["rank"] = i
    return out


def a4_tabla(sem, juegos, eqs, proy, g26):
    """Datos del código por juego (para el pedido y el mensaje)."""
    import polars as pl
    anterior = set()
    if sem > 1:
        g_ant = g26.filter(pl.col("week") == sem - 1)
        anterior = set(g_ant["home_team"].to_list()) | set(g_ant["away_team"].to_list())
    filas = []
    for r in juegos.iter_rows(named=True):
        u = proy.get(r["game_id"]) or {}
        pl_ = _num(u.get("pin_p_ml_local"))
        fila = dict(game_id=r["game_id"], visita=r["away_team"], local=r["home_team"], inicio=r["inicio"],
                    neutral=r.get("location") == "Neutral", p_local=pl_)
        for lado, eq in (("v", r["away_team"]), ("l", r["home_team"])):
            e = eqs.get(eq) or {}
            fila[lado] = dict(eq=eq, record=e.get("record", "0-0"), rank=e.get("rank"), forma=e.get("forma", "—"),
                              bye=sem > 1 and eq not in anterior)
        filas.append(fila)
    return filas


def a4_cuerpo(sem, filas, momento):
    lin = []
    for f in filas:
        v, l_ = f["v"], f["l"]
        merc = "" if f["p_local"] is None else (f" | market: {l_['eq']} {f['p_local']:.0%}" if f["p_local"] >= 0.5
                                               else f" | market: {v['eq']} {1 - f['p_local']:.0%}")
        lin.append(f"{f['game_id']}: {v['eq']} @ {l_['eq']}{' (neutral site)' if f['neutral'] else ''} | {_fmt_et(f['inicio'])} ET | "
                   + " | ".join(f"{x['eq']} {x['record']}, our rank {x['rank'] or '—'}, form {x['forma']}"
                                + (", coming off a bye" if x["bye"] else "") for x in (v, l_)) + merc)
    txt = A4_USUARIO.format(hoy=_fmt_et(momento), temporada=TEMPORADA, semana=sem, tabla="\n".join(lin))
    return {"model": CLAUDE_MODELO, "max_tokens": A4_MAX_TOKENS, "system": A4_SISTEMA,
            "messages": [{"role": "user", "content": txt}], "tools": [A4_HERRAMIENTA]}


def a4_cuerpo_extraer(texto, urls, ids):
    return {"model": CLAUDE_MODELO, "max_tokens": A4_MAX_TOKENS, "system": A4_EXTRAE,
            "messages": [{"role": "user", "content": "REPORT:\n" + texto[:80000] + "\n\nSEARCH RESULT URLS:\n"
                          + "\n".join(sorted(urls)[:500])}],
            "output_config": {"format": {"type": "json_schema", "schema": a4_esquema(ids)}}}


def a4_leer(obj, ids, urls_n):
    """JSON de la extracción → {game_id: dict(v=..., l=..., opinion)} y fuentes; descarta bajas sin URL de los resultados y
    rankings fuera de 1-32 o de un medio sin URL verificada."""
    fuentes = {}
    for s_ in (obj or {}).get("ranking_sources") or []:
        if isinstance(s_, dict) and _url_norm(s_.get("url")) in urls_n:
            fuentes.setdefault(_texto(s_.get("outlet")), _texto(s_.get("url")))
    out, descartadas = {}, 0
    for g in (obj or {}).get("games") or []:
        if not isinstance(g, dict) or g.get("game_id") not in ids:
            continue
        d = {}
        for lado, k in (("v", "away"), ("l", "home")):
            e = g.get(k) if isinstance(g.get(k), dict) else {}
            bajas = []
            for b in (e.get("injuries") if isinstance(e.get("injuries"), list) else [])[:12]:
                if not isinstance(b, dict):
                    continue
                if _url_norm(b.get("source_url")) not in urls_n or _texto(b.get("status")).lower() not in A4_ESTADOS:
                    descartadas += 1
                    continue
                bajas.append(dict(nombre=_texto(b.get("name"))[:60], pos=_texto(b.get("position")).upper()[:6],
                                  estado=_texto(b.get("status")).lower()))

            def rk(x, medio):
                try:
                    v = int(x)
                except (TypeError, ValueError):
                    return None
                return v if 1 <= v <= 32 and medio in fuentes else None
            d[lado] = dict(nflcom=rk(e.get("rank_nflcom"), "NFL.com"), pft=rk(e.get("rank_pft"), "PFT"), bajas=bajas)
        d["opinion"] = re.sub(r"\s+", " ", _texto(g.get("opinion")))[:320]
        out[g["game_id"]] = d
    return out, fuentes, descartadas


BAJA_ES = {"out": "out", "doubtful": "doubtful", "injured_reserve": "lista de lesionados", "questionable": "questionable",
           "suspended": "suspendido"}


def texto_briefing(sem, filas, ia, fuentes, eqs, costo, estado_ia, origen):
    lin = [f"📋 ANALISTA DEL SÁBADO · semana {sem}{' (a pedido)' if origen != 'sabado' else ''} · {CLAUDE_NOMBRE} · descriptivo, no cuenta",
           "Cómo leer: «datos» es nuestro puesto del 1 al 32 por EPA neto por jugada (ataque menos defensa, nflverse 2026) · "
           "NFL.com y PFT son los rankings de la prensa de esta semana · forma: últimos 2 partidos contra la temporada "
           "(↑↑ mucho mejor, ↑ mejor, = igual, ↓ peor, ↓↓ mucho peor) · mercado: Pinnacle sin vig.",
           "Lo que el laboratorio ya midió: las rachas no predicen el siguiente partido (H4); la sorpresa de un partido la "
           "explican sobre todo las pérdidas de balón, los equipos especiales y el juego sin pérdidas, y las dos primeras casi "
           "no se repiten (H41); no hay «ley del resorte» contra el mercado (H42). El mercado ya descuenta récord, momento y "
           "bajas oficiales: esto sirve para entender los partidos, no es una señal para apostar."]
    for f in filas:
        d = ia.get(f["game_id"]) or {}
        merc = ("" if f["p_local"] is None else f" · mercado {f['local']} {_pct(f['p_local'], False)}" if f["p_local"] >= 0.5
                else f" · mercado {f['visita']} {_pct(1 - f['p_local'], False)}")
        lin.append("")
        lin.append(f"{f['visita']} {'vs' if f['neutral'] else '@'} {f['local']} · {cuando_txt(f['inicio'])}"
                   + (" · sede neutral" if f["neutral"] else "") + merc)
        for lado in ("v", "l"):
            x, e = f[lado], d.get(lado) or {}
            rk = lambda v: f"#{v}" if v else "—"  # noqa: E731
            bajas = e.get("bajas") or []
            lin.append(f"• {apodo(x['eq'])} {x['record']} · datos {rk(x['rank'])} · NFL.com {rk(e.get('nflcom'))} · PFT {rk(e.get('pft'))}"
                       f" · forma {x['forma']}" + (" · vienen de la semana libre" if x["bye"] else "")
                       + (" · bajas: " + ", ".join(f"{b['pos']} {b['nombre']} ({BAJA_ES.get(b['estado'], b['estado'])})"
                                                   for b in bajas[:6]) + ("…" if len(bajas) > 6 else "") if bajas else ""))
        if d.get("opinion"):
            lin.append(f"• Opinión (Opus): {d['opinion']}")
    lin.append("")
    if fuentes:
        lin.append("Fuentes: " + " · ".join(f"{k} {v}" for k, v in sorted(fuentes.items())))
    if estado_ia != "ok":
        lin.append(f"Opus no completó la parte de la prensa ({estado_ia}): se muestran solo los datos del laboratorio.")
    lin.append(f"Datos: nflverse (jugada por jugada) y la última proyección del motor · USD {costo:.2f}".replace(".", ","))
    return "\n".join(lin)


def briefing_correr(g26, ahora, estado, origen, sin_telegram=False, post=None):
    """A4: datos del código + prensa y bajas con Opus (búsqueda y extracción con esquema). Solo juegos que no empezaron.
    origen 'sabado' (automática, una vez por semana) o 'pedido' (/briefing, tope por día). Devuelve una línea de resumen."""
    import polars as pl
    momento = e2_momento(ahora)
    sem = semana_actual(g26, momento)
    if sem is None:
        return "No hay juegos por jugar."
    juegos = g26.filter((pl.col("week") == sem) & (pl.col("inicio") > momento)).sort(["inicio", "game_id"])
    if juegos.height == 0:
        return f"Semana {sem}: no quedan juegos por empezar."
    hoy = momento.astimezone(CARACAS).date().isoformat()
    if origen != "sabado":
        usado = estado.setdefault("briefing_dia", {})
        for k in [k for k in usado if k != hoy]:
            usado.pop(k)
        if usado.get(hoy, 0) >= A4_MAX_DIA:
            return f"Ya van {A4_MAX_DIA} /briefing hoy (tope por día). Prueba mañana."
        usado[hoy] = usado.get(hoy, 0) + 1
    eqs = a4_equipos(g26, momento)
    filas = a4_tabla(sem, juegos, eqs, ultimas_proyecciones(sem), g26)
    ids = [f["game_id"] for f in filas]
    ia, fuentes, costo, estado_ia, desc = {}, {}, 0.0, "no corrió", 0
    resto, motivo = claude_cupo(ahora)
    if resto >= A4_USD:
        limite = time.time() + A4_PLAZO_S
        reg = dict(agente="A4", origen=origen, huella=a4_huella(), game_id=f"semana-{sem}", momento=momento)
        b = claude_post(a4_cuerpo(sem, filas, momento), limite - 120, {**reg, "paso": "busqueda", "reserva_usd": 1.5}, post)
        costo = b["costo_usd"]
        estado_ia = b["estado"]
        if b["estado"] in ("ok", "cortada", "pausada") and b["texto"].strip():
            urls = _urls_de(b["contenido"])
            e = claude_post(a4_cuerpo_extraer(b["texto"], urls, ids), limite, {**reg, "paso": "extraccion", "reserva_usd": 0.4}, post)
            costo += e["costo_usd"]
            estado_ia = e["estado"] if e["estado"] != "ok" else ("ok" if b["estado"] == "ok" else f"búsqueda {b['estado']}")
            if e["estado"] == "ok":
                ia, fuentes, desc = a4_leer(_objeto_json(e["texto"]), set(ids), {_url_norm(u) for u in urls} - {""})
    else:
        estado_ia = motivo or f"tope del día (quedan USD {resto:.2f})"
    txt = texto_briefing(sem, filas, ia, fuentes, eqs, costo, estado_ia, origen)
    BRIEFINGS.mkdir(parents=True, exist_ok=True)
    (BRIEFINGS / f"briefing_semana_{sem}_{momento.astimezone(CARACAS):%Y%m%d_%H%M}.txt").write_text(txt + "\n", encoding="utf-8")
    enviar_tg(txt, sin_telegram)
    if origen == "sabado":
        estado.setdefault("briefing", {})[str(sem)] = iso(ahora)
    log(f"Analista (A4) semana {sem} ({origen}): {len(filas)} juegos · Opus {estado_ia} · {len(ia)} juegos con prensa · "
        f"{desc} bajas descartadas sin URL · USD {costo:.4f}")
    return f"Analista de la semana {sem}: {len(filas)} juegos; mensaje enviado (Opus: {estado_ia})."


# ---------------------------------------------------------------- /vigia (63) y pruebas
def vigia_manual(g26, args, ahora, estado, hoja):
    """/vigia (63): simula los juegos pedidos como /correr (tipo telegram: no cuenta para 31A ni 29A) y consulta a los dos
    vigías en paralelo: Gemini (modelos del piloto 55) y Claude. Registros aparte que no entran a ninguna medición; no
    escribe la columna del vigía. Rechaza juegos empezados y si toca una corrida automática en ≤ 12 min."""
    import polars as pl
    hoy = ahora.astimezone(CARACAS).date().isoformat()
    usado = estado.setdefault("vigia_manual_dia", {})
    for k in [k for k in usado if k != hoy]:
        usado.pop(k)
    cerca = automatica_cerca(g26, ahora, estado)
    if cerca:
        print(f"No corro /vigia ahora: en menos de {ANTES_AUTOMATICA_MIN} min toca la corrida automática "
              f"({NOMBRE_CORRIDA.get(cerca[0], cerca[0])}), que es la que cuenta. Pídelo después de esa corrida.")
        return
    if usado.get(hoy, 0) >= VIGIA_MANUAL_MAX_DIA:
        print(f"Ya van {VIGIA_MANUAL_MAX_DIA} /vigia hoy (tope por día). Prueba mañana.")
        return
    sem = semana_actual(g26, ahora)
    if sem is None:
        print("No hay juegos por jugar.")
        return
    g_sem = g26.filter(pl.col("week") == sem)
    if args.equipo:
        eq = DE_OTRAS.get(args.equipo.strip().upper(), args.equipo.strip().upper())
        if eq not in EQUIPOS:
            print(f"No conozco el equipo «{args.equipo}». Usa la abreviatura, por ejemplo: /vigia KC")
            return
        g_eq = g_sem.filter((pl.col("home_team") == eq) | (pl.col("away_team") == eq))
        if g_eq.height == 0:
            print(f"{eq} no juega en la semana {sem}.")
            return
        fut = g_eq.filter(pl.col("inicio") > ahora + dt.timedelta(minutes=VIGIA_MANUAL_MARGEN_MIN)).sort("inicio")
        if fut.height == 0:
            print(f"El juego de {eq} de la semana {sem} ya empezó o empieza en menos de {VIGIA_MANUAL_MARGEN_MIN} min: el vigía "
                  "no consulta juegos empezados (H36) y la consulta tarda hasta ~9 min.")
            return
        ids = fut.head(1)["game_id"].to_list()
    else:
        fut = g_sem.filter(pl.col("inicio") > ahora + dt.timedelta(minutes=VIGIA_MANUAL_MARGEN_MIN))
        if fut.height == 0:
            print(f"No quedan juegos de la semana {sem} que empiecen en más de {VIGIA_MANUAL_MARGEN_MIN} min.")
            return
        ids = fut.filter(pl.col("inicio") == fut["inicio"].min())["game_id"].to_list()
    usado[hoy] = usado.get(hoy, 0) + 1
    guardar_estado(estado)
    log(f"{VERSION_SEMANA}: /vigia {args.equipo or '(próximo grupo)'} → {len(ids)} juegos (a pedido, no cuenta)")
    g_all, g26 = calendario(0.25)
    resumenes, nombres_qb = correr([("telegram", f"telegram-{iso(ahora)}", ids)], g_all, g26, args, ahora)
    filas = [f for _, _, ff, _ in resumenes for f in ff]
    if not filas:
        print("Esos juegos ya empezaron: no hay nada que simular.")
        return
    if hoja is not None:
        escribir_semanas(hoja, g26, {f["semana"] for f in filas}, nombres_qb, ahora, estado, args.bot_dir)
        guardar_estado(estado)
    juegos = [dict(game_id=f["game_id"], semana=f["semana"], game_type=f["game_type"], visita=f["visita"], local=f["local"],
                   inicio=t_utc(f["inicio_utc"])) for f in filas]
    textos = [texto_telegram(resumenes)]
    tope_ini = e2_momento(ahora) + dt.timedelta(seconds=A1_PLAZO_S + 60)       # H36: la consulta termina antes del inicio
    tarde = [j for j in juegos if j["inicio"] <= tope_ini]
    juegos = [j for j in juegos if j["inicio"] > tope_ini]
    if tarde:
        textos.append("Vigías: no consulto " + ", ".join(f"{j['visita']} @ {j['local']}" for j in tarde)
                      + " porque empieza antes de que termine la consulta (H36).")
    if not juegos:
        enviar_tg("\n\n".join(textos), args.sin_telegram)
        print("/vigia: simulé, pero los juegos empiezan antes de que termine la consulta: no consulté a los vigías (H36).")
        return
    trab = a1_lanzar(juegos, ahora, "manual")
    res_v = vigia_t85([(j, None) for j in juegos], filas, ahora, estado, g26, manual=True)
    guardar_estado(estado)
    if res_v:
        textos.append(texto_vigia(res_v))
    else:
        textos.append("Vigía de Gemini: no corrió (sin credenciales/gemini.key, apagado en semana.ini o error; ver el log).")
    res_c = a1_cerrar(trab, filas, g26)
    if res_c:
        textos.append(texto_a1(res_c))
    else:
        textos.append(f"Vigía-alineador de Claude: no corrió ({claude_cupo(ahora)[1] or 'ver el log'}).")
    enviar_tg("\n\n".join(textos), args.sin_telegram)
    print(f"/vigia: {len(juegos)} juego{'s' if len(juegos) != 1 else ''} simulado{'s' if len(juegos) != 1 else ''} y consultado"
          f"{'s' if len(juegos) != 1 else ''} (a pedido, no cuenta) · Gemini {'sí' if res_v else 'no'} · Claude {'sí' if res_c else 'no'}"
          f" · /vigia hoy {usado.get(hoy, 0)} de {VIGIA_MANUAL_MAX_DIA}")


CLAUDE_MAX_PRUEBA_DIA = 2


def claude_prueba_real(g26, ahora, estado):
    """Una consulta REAL del vigía-alineador (búsqueda y extracción) sobre el próximo juego, para ver que la API acepta
    los pedidos. No escribe en los registros del vigía ni cuenta para nada; sí queda en claude_llamadas.csv (origen
    'prueba'). Tope aparte de 2 por día."""
    import polars as pl
    resto, motivo = claude_cupo(ahora)
    if motivo.startswith(("sin", "apagado")):
        return f"Claude: {motivo}."
    prox = g26.filter(pl.col("inicio") > e2_momento(ahora)).sort("inicio").head(1)
    if prox.height == 0:
        return "No hay juegos por jugar en el calendario."
    hoy = ahora.astimezone(CARACAS).date().isoformat()
    usado = estado.setdefault("claude_prueba", {})
    for k in [k for k in usado if k != hoy]:
        usado.pop(k)
    if usado.get(hoy, 0) >= CLAUDE_MAX_PRUEBA_DIA:
        return f"Tope de pruebas reales del día ({CLAUDE_MAX_PRUEBA_DIA}): prueba mañana."
    if resto < A1_USD_JUEGO:
        return f"Claude: {motivo or 'no queda cupo hoy'}."
    usado[hoy] = usado.get(hoy, 0) + 1
    r = prox.row(0, named=True)
    j = dict(game_id=r["game_id"], semana=int(r["week"]), game_type=r["game_type"], visita=r["away_team"], local=r["home_team"],
             inicio=r["inicio"])
    momento = e2_momento(ahora)
    x = a1_consultar(j, momento, time.time() + A1_PLAZO_S, "prueba")
    snaps, roster = vigia_datos()
    ind = VigiaIndice(snaps, roster, g26)
    lim, pasos = {}, []
    for f in reversed(_leer_csv(CLAUDE_LLAMADAS)):
        if f.get("origen") == "prueba" and f.get("game_id") == j["game_id"] and f.get("paso") in ("busqueda", "extraccion"):
            if not lim.get("lim_entrada") and f.get("lim_entrada"):
                lim = f
            pasos.insert(0, f)
            if len(pasos) == 2 or f.get("paso") == "busqueda":
                break
    lin = [f"Prueba REAL del vigía-alineador (no cuenta): {j['visita']} @ {j['local']} · {fecha_cc(j['inicio'])} Caracas · "
           f"{CLAUDE_MODELO} · huella {a1_huella()}",
           f"  estado {x['estado']}" + (f" (HTTP {x['http']})" if x.get("http") not in (None, "", 200) else "")
           + f" · {x['latencia_s']} s · {x['busquedas']} búsquedas · USD {x['costo_usd']:.4f} · {len(x['urls'])} URL en los resultados"
           + (f" · {x['detalle']}" if x.get("detalle") else ""),
           "  límites de la API (pedidos/min, tokens de entrada/min, de salida/min): "
           f"{lim.get('lim_pedidos') or '—'} · {lim.get('lim_entrada') or '—'} · {lim.get('lim_salida') or '—'}"]
    for f in pasos:                                    # v9.1: de dónde sale el costo
        lin.append(f"  paso {f.get('paso')}: {f.get('tok_entrada')} tokens de entrada · {f.get('tok_salida')} de salida (tope "
                   f"{A1_MAX_TOKENS}) · {f.get('busquedas') or 0} búsquedas · fin {f.get('stop_reason') or '—'} · "
                   f"{f.get('continuaciones') or 0} continuaciones · {f.get('latencia_s')} s · USD {_f(f.get('costo_usd')):.4f}")
    for eq, e in x["equipos"].items():
        val_f = [h for h in e["fuera"] if not vigia_validar(h, momento) and _url_norm(h["url"]) in x["urls"]]
        val_a = [a for a in e["alineacion"] if not _a1_validar_alin(a, momento) and _url_norm(a["url"]) in x["urls"]]
        cruz = [a for a in val_a if ind.gsis_por_nombre(eq, a["nombre"], a["posicion"])[0]]
        lin.append(f"  {eq}: inactivos oficiales {'sí' if e['inactivos'] == 1 else 'no'} · fuera {len(e['fuera'])} ({len(val_f)} válidos)"
                   f" · alineación {len(e['alineacion'])} ({len(val_a)} válidos, {len(cruz)} cruzados con el roster)")
        for h in e["fuera"][:4]:
            m = vigia_validar(h, momento) or ("" if _url_norm(h["url"]) in x["urls"] else "URL fuera de los resultados")
            lin.append(f"    fuera: {h['posicion']} {h['nombre']} · {h['estado_jugador']} · {h['tipo_fuente']} · {h['publicada'] or 'sin fecha'}"
                       + (f" · INVÁLIDO: {m}" if m else ""))
    return "\n".join(lin)


def _revisar_esquema(s, ruta="raíz"):
    """Lista de problemas que la API rechazaría en un esquema de output_config.format (vacía si está bien)."""
    malos = []
    if isinstance(s, dict):
        if s.get("type") == "object" and s.get("additionalProperties") is not False:
            malos.append(f"{ruta}: objeto sin additionalProperties false")
        for k in ("maxItems", "minLength", "maxLength", "minimum", "maximum", "multipleOf"):
            if k in s:
                malos.append(f"{ruta}: {k} no se acepta")
        if s.get("minItems", 0) not in (0, 1):
            malos.append(f"{ruta}: minItems solo 0 o 1")
        for k, v in s.items():
            malos += _revisar_esquema(v, f"{ruta}.{k}")
    elif isinstance(s, list):
        for i, v in enumerate(s):
            malos += _revisar_esquema(v, f"{ruta}[{i}]")
    return malos


class _RespuestaFalsa:
    def __init__(self, codigo, datos, cab=None):
        self.status_code, self._d, self.headers = codigo, datos, cab or {}

    def json(self):
        if isinstance(self._d, Exception):
            raise self._d
        return self._d


def claude_autoprueba(g26):
    """Prueba sin consultar a Claude (la usa el instalador): pedidos y esquemas que la API acepta, continuación pause_turn,
    reintento 429, tope de gasto, lectura de una respuesta de ejemplo, validación por URL de los resultados, cruce con el
    roster y los snaps reales, causas de H41 sobre un juego real y el ranking del analista. No escribe registros."""
    ok = []
    j = dict(game_id="2026_07_GB_CHI", semana=7, game_type="REG", visita="GB", local="CHI",
             inicio=dt.datetime(2026, 10, 25, 17, 0, tzinfo=dt.timezone.utc))
    momento = j["inicio"] - dt.timedelta(minutes=84)
    cu = a1_cuerpo(j, momento)
    assert cu["model"] == "claude-opus-5-5" and cu["tools"][0]["type"] == "web_search_20260318"
    assert len(cu["tools"][0]["allowed_domains"]) == 34 and "84 minutes before kickoff" in cu["messages"][0]["content"]
    for nombre, esq in (("A1", a1_esquema("GB", "CHI")), ("A4", a4_esquema(["X", "Y"]))):
        assert not _revisar_esquema(esq), (nombre, _revisar_esquema(esq))
    ce = a1_cuerpo_extraer(j, "texto", {"https://www.packers.com/x"})
    assert "tools" not in ce and ce["output_config"]["format"]["type"] == "json_schema"
    ok.append("pedidos y esquemas")
    # claude_post con respuestas falsas: pause_turn → fin; 429 con retry-after; tope de gasto (429 sin retry-after)
    global CLAUDE_LLAVE, CLAUDE_LLAMADAS
    llave0, reg0 = CLAUDE_LLAVE, CLAUDE_LLAMADAS
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        CLAUDE_LLAVE, CLAUDE_LLAMADAS = Path(tmp) / "k", Path(tmp) / "l.csv"
        CLAUDE_LLAVE.write_text("sk-ant-prueba", encoding="utf-8")
        try:
            seq = [_RespuestaFalsa(200, {"content": [{"type": "text", "text": "Busco. "},
                                                     {"type": "web_search_tool_result", "content": [
                                                         {"type": "web_search_result", "url": "https://www.packers.com/news/inactives"}]}],
                                         "stop_reason": "pause_turn", "usage": {"input_tokens": 1000, "output_tokens": 100,
                                                                                "server_tool_use": {"web_search_requests": 2}}}),
                   _RespuestaFalsa(429, {"error": {"type": "rate_limit_error", "message": "x"}}, {"retry-after": "1"}),
                   _RespuestaFalsa(200, {"content": [{"type": "text", "text": "TEAM GB", "citations": [
                       {"type": "web_search_result_location", "url": "https://www.chicagobears.com/news/injury-report"}]}],
                       "stop_reason": "end_turn", "usage": {"input_tokens": 2000, "output_tokens": 200}})]
            vistos = []

            def post(url, headers=None, json=None, timeout=None):
                assert headers["x-api-key"] == "sk-ant-prueba" and url == CLAUDE_URL
                vistos.append(json)
                return seq.pop(0)
            r = claude_post(cu, time.time() + 120, dict(agente="A1", origen="prueba", momento=momento), post, dormir=lambda s: None)
            assert r["estado"] == "ok" and r["continuaciones"] == 1 and r["busquedas"] == 2, r
            assert vistos[1]["messages"][-1]["role"] == "assistant" and len(vistos[2]["messages"][-1]["content"]) == 2
            assert abs(r["costo_usd"] - (3000 * 4e-6 + 300 * 20e-6 + 2 * 0.01)) < 1e-9, r["costo_usd"]
            assert {_url_norm(u) for u in _urls_de(r["contenido"])} == {"packers.com/news/inactives", "chicagobears.com/news/injury-report"}
            r2 = claude_post(cu, time.time() + 120, dict(agente="A1", origen="prueba", momento=momento),
                             lambda *a, **k: _RespuestaFalsa(429, {"error": {"type": "rate_limit_error", "message": "spend",
                                                                             "details": {"error_code": "enforced_spend_limit_reached"}}}),
                             dormir=lambda s: None)
            assert r2["estado"] == "error HTTP" and "enforced_spend_limit_reached" in r2["detalle"], r2
            assert "sk-ant-prueba" not in CLAUDE_LLAMADAS.read_text(encoding="utf-8")
            assert claude_gasto_hoy(momento.astimezone(CARACAS).date().isoformat()) > 0
        finally:
            CLAUDE_LLAVE, CLAUDE_LLAMADAS = llave0, reg0
    ok.append("API simulada (pause_turn, 429, tope de gasto, costo, sin llave en el registro)")
    # lectura, validación y cruce con roster y snaps reales
    snaps, roster = vigia_datos()
    ind = VigiaIndice(snaps, roster, g26)
    con = [r for r in g26.sort("inicio").iter_rows(named=True) if r["game_id"] in ind.con_snaps]
    n_tit = "sin snaps todavía"
    if con:
        u = con[-1]
        eq = u["home_team"]
        tit = ind.titulares(eq, u["inicio"] + dt.timedelta(days=1)) or {}
        habit = [d["nombre"] for g, d in tit.items() if not g.startswith("pfr:") and ind.gsis_por_nombre(eq, d["nombre"], d["pos"])[0] == g][:1]
        jug, exp = _a1_historia(ind, g26, roster)
        novato = ""
        for f in (roster.iter_rows(named=True) if roster is not None else []):
            g = _texto(f.get("gsis_id"))
            if f.get("team") == eq and g and exp.get(g) == 0 and not jug.get(ind.gsis_pfr.get(g, ""), []):
                novato = _texto(f.get("full_name"))
                break
        obj = {"away": {"team": u["away_team"], "inactives_published": True, "out": [], "lineup": []},
               "home": {"team": eq, "inactives_published": False, "out": [
                   {"name": "Rumor Man", "position": "WR", "status": "out", "source_type": "official_injury_report",
                    "source_url": "https://www.nfl.com/fuera-de-resultados",
                    "source_published": (u["inicio"] - dt.timedelta(days=1)).date().isoformat(), "evidence": "x"}],
                   "lineup": [{"name": n, "position": "", "unit": "offense", "source_type": "official_depth_chart",
                               "source_url": "https://www.nfl.com/depth", "source_published": ""} for n in habit + ([novato] if novato else [])]}}
        jj = dict(game_id=u["game_id"], semana=int(u["week"]), game_type="REG", visita=u["away_team"], local=eq, inicio=u["inicio"])
        eqs = a1_leer(obj, jj)
        assert set(eqs) == {u["away_team"], eq} and len(eqs[eq]["fuera"]) == 1
        h = eqs[eq]["fuera"][0]
        assert not vigia_validar(h, u["inicio"]) and _url_norm(h["url"]) not in {"nfl.com/depth"}
        for a in eqs[eq]["alineacion"][:len(habit)]:
            g, _c = ind.gsis_por_nombre(eq, a["nombre"], a["posicion"])
            assert g, a["nombre"]
        n_tit = f"{len(tit)} titulares habituales de {eq}; habitual reconocido; novato {'sin snaps: ' + novato if novato else 'no hallado'}"
    ok.append(f"lectura y cruce ({n_tit})")
    # A3 sobre un juego real jugado (favorito de nflverse que perdió) y A4
    import polars as pl
    perd = g26.filter(pl.col("result").is_not_null() & pl.col("spread_line").is_not_null()
                      & (((pl.col("spread_line") > 0) & (pl.col("result") < 0)) | ((pl.col("spread_line") < 0) & (pl.col("result") > 0))))
    txt3 = "sin juegos"
    if perd.height:
        r = perd.sort("inicio").row(-1, named=True)
        p = _pbp_columnas(A3_COLS, [r["game_id"]])
        if p is not None and p.height:
            fav = r["home_team"] if r["spread_line"] > 0 else r["away_team"]
            dog = r["away_team"] if fav == r["home_team"] else r["home_team"]
            c = _a3_causas(p, fav, dog)
            assert c["neto_sin"] is not None and c["ultima_serie"] is not None, c
            txt3 = f"{r['game_id']}: pérdidas {c['perdidas_dif']:+d}, EE {c['ee_epa']:+.1f}, neto {c['neto_sin']:+.3f}"
    ok.append(f"causas de H41 ({txt3})")
    eqs4 = a4_equipos(g26, dt.datetime.now(dt.timezone.utc))
    if eqs4:
        assert sorted(e["rank"] for e in eqs4.values()) == list(range(1, len(eqs4) + 1))
    ok.append(f"ranking del analista ({len(eqs4)} equipos)")
    return (f"claude OK ({'; '.join(ok)}) · {CLAUDE_MODELO} · huellas A1 {a1_huella()}, A3 {a3_huella()}, A4 {a4_huella()} · "
            f"llave {'presente' if CLAUDE_LLAVE.exists() else 'ausente'}")


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


def _es_uno(v):
    return str(v).strip().lower() in ("1", "1.0", "true", "si", "sí")


def seccion_bandera(semana, senal):
    """v8.4 (57, solo registro): la bandera de sesgo (21A) se recalcula en cada corrida con la última proyección de cada
    juego. Cuenta las corridas que cuentan de la semana, cuántas veces cambió la bandera y qué juegos decidieron con ella
    encendida o apagada (su señal que cuenta). No decide nada. Devuelve (línea para Telegram, líneas del informe)."""
    import polars as pl
    corr = {}
    for r in leer_registro().filter(pl.col("semana") == str(semana)).iter_rows(named=True):
        if r.get("tipo") in TIPOS_QUE_CUENTAN and r.get("corrida_utc"):
            corr.setdefault(r["corrida_utc"], r)
    seq = [(c, _es_uno(corr[c].get("bandera_sesgo")), corr[c].get("sesgo_total_semana"), corr[c].get("sesgo_spread_semana"),
            corr[c].get("tipo")) for c in sorted(corr)]
    if not seq:
        return "Bandera de sesgo (57, solo registro): sin corridas que cuenten esta semana.", []
    cambios = sum(1 for a, b in zip(seq, seq[1:]) if a[1] != b[1])
    con = sorted(f"{r['visita']} @ {r['local']}" for r in senal.values() if _es_uno(r.get("bandera_sesgo")))
    sin = sorted(f"{r['visita']} @ {r['local']}" for r in senal.values() if not _es_uno(r.get("bandera_sesgo")))
    tel = (f"Bandera de sesgo (21A; 57, solo registro): {sum(1 for x in seq if x[1])} de {len(seq)} corridas con la bandera "
           f"encendida · cambió {cambios} {'vez' if cambios == 1 else 'veces'} en la semana · decidieron con la bandera "
           f"encendida {len(con)} juegos y apagada {len(sin)}")
    det = ["BANDERA DE SESGO (21A; 57, solo registro: no decide nada)"]
    for c, b, st, ss, tp in seq:
        det.append(f"  {fecha_cc(t_utc(c))} Caracas · {NOMBRE_CORRIDA.get(tp, tp)} · sesgo total {st or '—'} · spread "
                   f"{ss or '—'} · {'ENCENDIDA' if b else 'apagada'}")
    det.append("  Encendida en la señal que cuenta: " + (", ".join(con) or "ninguno"))
    det.append("  Apagada en la señal que cuenta: " + (", ".join(sin) or "ninguno"))
    return tel, det


def actualizar_tablero(motivo):
    """v8.4 (58): corre tablero.py (hoja «NFL Secret LAB — Tablero», solo pestañas datos_*) en un proceso aparte con
    límite de tiempo. Nunca frena ni cambia la corrida: cualquier falla queda en el log."""
    import subprocess
    if not TABLERO.exists():
        return "tablero: no instalado"
    cfg = configparser.ConfigParser()
    cfg.read(CONFIG, encoding="utf-8")
    if not cfg.has_section("tablero") or not cfg["tablero"].get("hoja_id", "").strip():
        return "tablero: sin hoja_id en semana.ini [tablero]"
    if cfg["tablero"].get("activo", "si").strip().lower() in ("no", "0", "false"):
        return "tablero: apagado en semana.ini"
    t0 = time.time()
    try:
        r = subprocess.run([sys.executable, str(TABLERO)], cwd=str(BASE), capture_output=True, text=True,
                           timeout=TABLERO_TIMEOUT)
        ult = ((r.stdout or "").strip().splitlines() or [""])[-1]
        err = ((r.stderr or "").strip().splitlines() or [""])[-1]
        txt = (f"tablero ({motivo}): {'ok' if r.returncode == 0 else 'FALLÓ'} en {time.time() - t0:.0f} s · "
               f"{(ult if r.returncode == 0 else (err or ult))[:240]}")
    except subprocess.TimeoutExpired:
        txt = f"tablero ({motivo}): tiempo agotado ({TABLERO_TIMEOUT} s); la corrida sigue"
    except Exception as e:  # noqa: BLE001
        txt = f"tablero ({motivo}): no pude correrlo ({type(e).__name__})"
    log(txt)
    return txt


# --------------------------------------------------------------------------------------
# v9.2 (60d): clima a T−85 (clima.py en un proceso aparte) y conteo del movimiento tardío (56)
# --------------------------------------------------------------------------------------
def clima_lanzar(sombra, ahora):
    """Lanza clima.py con los juegos de la T−85 en un proceso aparte. Nunca frena ni cambia la corrida: si no está
    instalado o no arranca, se anota en el log y todo sigue igual. → dict de seguimiento o None."""
    import subprocess
    if not CLIMA.exists():
        return None
    ids = sorted({j["game_id"] for j, _ in sombra})
    if not ids:
        return None
    try:
        p = subprocess.Popen([sys.executable, str(CLIMA), "registrar", "--corrida", iso(ahora), "--juegos", ",".join(ids)],
                             cwd=str(BASE), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    except Exception as e:  # noqa: BLE001
        log(f"clima: no pude lanzarlo ({type(e).__name__})")
        return None
    return {"p": p, "t0": time.time(), "listo": False}


def clima_revisar(trab, esperar=False, sin_telegram=False):
    """Si clima.py ya terminó (con esperar: hasta CLIMA_TIMEOUT desde que se lanzó), anota su resumen en el log y manda
    su Telegram si hay clima notable (D2 = a). Una sola vez por corrida; cualquier falla queda en el log."""
    import subprocess
    if not trab or trab["listo"]:
        return
    p = trab["p"]
    if not esperar and p.poll() is None:
        return
    trab["listo"] = True
    try:
        out, _ = p.communicate(timeout=max(1.0, CLIMA_TIMEOUT - (time.time() - trab["t0"])))
    except subprocess.TimeoutExpired:
        try:                                          # primero le pide que termine; si no, lo corta
            p.terminate()
            p.communicate(timeout=5)
        except Exception:  # noqa: BLE001
            try:
                p.kill()
                p.communicate(timeout=5)
            except Exception:  # noqa: BLE001
                pass
        log(f"clima: tiempo agotado ({CLIMA_TIMEOUT} s); la corrida sigue")
        return
    except Exception as e:  # noqa: BLE001
        log(f"clima: no pude leer su resultado ({type(e).__name__})")
        return
    res = None
    for lin in (out or "").splitlines():
        if lin.startswith("CLIMA_JSON "):
            try:
                res = json.loads(lin[len("CLIMA_JSON "):])
            except ValueError:
                res = None
    if res is None:
        ult = ((out or "").strip().splitlines() or [""])[-1]
        log(f"clima: terminó sin resumen (código {p.returncode}) · {ult[:240]}")
        return
    log(f"clima: {res.get('estado')} · {res.get('juegos', 0)} juegos en {res.get('segundos', '?')} s · NWS "
        f"{res.get('nws_ok', 0)}/{res.get('nws_total', 0)} · Open-Meteo {res.get('om_ok', 0)}/{res.get('om_total', 0)} · "
        f"#9 {res.get('casos9', 0)} · notables {res.get('notables', 0)}")
    for a in (res.get("avisos") or [])[:-1]:          # el último es el resumen que ya está arriba
        log(f"clima (aviso): {a}")
    if res.get("mensaje"):
        try:
            enviar_tg(res["mensaje"], sin_telegram)
        except Exception as e:  # noqa: BLE001
            log(f"clima: no pude mandar el Telegram ({type(e).__name__})")


def _modulo_clima():
    if not CLIMA.exists():
        return None
    sys.path.insert(0, str(BASE))
    import clima as cl
    return cl


def seccion_clima(semana):
    """Sección «Clima» del informe semanal (la arma clima.py; #9 a ciegas: solo conteos)."""
    cl = _modulo_clima()
    return ("", []) if cl is None else cl.seccion_informe(semana)


def texto_clima_estado():
    cl = _modulo_clima()
    return "Clima (60d): clima.py no instalado" if cl is None else cl.texto_estado()


M56_DESDE_ET = dt.date(2026, 10, 11)        # 56: juegos desde el domingo 11-oct-2026 (fecha del Este; semana 5)
M56_UMBRAL = 1.0                            # |hándicap al cierre − hándicap temprano| ≥ 1,0 pt
M56_TEMPRANA_H = (3.0, 8.0)                 # foto temprana: la más reciente de Pinnacle entre 3 y 8 h antes del inicio
M56_CIERRE_MAX_MIN = 20                     # cierre del bot: la última foto de Pinnacle ≤ 20 min antes (escaneo de T−10)
M56_REPROG_H = 6.0                          # reprogramado: el inicio que vio alguna proyección difiere > 6 h del final
M56_REPROGRAMADOS = set()                   # para anotar a mano un caso que el registro no muestre


def _cierres_legible(bot_dir):
    """¿cierres.csv del bot existe y tiene las columnas de las fotos? (si no, el cierre sale solo de lineas_log.csv)"""
    ruta = Path(bot_dir) / "cierres.csv"
    try:
        with open(ruta, newline="", encoding="utf-8") as fh:
            enc = next(csv.reader(fh), [])
        return all(c in enc for c in COLS_FOTO)
    except Exception:  # noqa: BLE001
        return False


def _inicios_registrados():
    """Inicio de cada juego según cada proyección guardada en el registro (para ver si se reprogramó)."""
    out = {}
    try:
        with open(REGISTRO, newline="", encoding="utf-8") as fh:
            for f in csv.DictReader(fh):
                t = t_utc(f.get("inicio_utc"))
                if t is not None:
                    out.setdefault(f.get("game_id"), []).append(t)
    except FileNotFoundError:
        pass
    return out


def conteo_56(g26, bot_dir):
    """56 (regla registrada el 11-oct): SOLO conteos, nunca la tasa. Por semana, en temporada regular desde el 11-oct-2026,
    cuántos juegos tienen las dos fotos de Pinnacle del bot (temprana 3-8 h antes y cierre ≤ 20 min antes) y en cuántos el
    hándicap se movió ≥ 1,0 pt entre ellas. → {semana: dict(casos, con_fotos, sin_temprana, sin_cierre, reprogramados)}"""
    import polars as pl
    jug = g26.filter((pl.col("game_type") == "REG") & pl.col("result").is_not_null() & pl.col("inicio").is_not_null())
    jug = [r for r in jug.iter_rows(named=True) if r["inicio"].astimezone(NUEVA_YORK).date() >= M56_DESDE_ET]
    lg = log_bot(bot_dir, con_cierres=True)
    fotos = {}
    if lg is not None and jug:
        for f in lg.filter((pl.col("fuente") == "pinnacle") & pl.col("game_id").is_in([r["game_id"] for r in jug])).iter_rows(named=True):
            ts = t_utc(f["ts_utc"])
            if ts is not None:
                fotos.setdefault(f["game_id"], []).append((ts, _num(f.get("hcp_local"))))
    reg = _inicios_registrados()
    out = {}
    for r in jug:
        d = out.setdefault(int(r["week"]), dict(casos=0, con_fotos=0, sin_temprana=0, sin_cierre=0, sin_handicap=0,
                                                reprogramados=0))
        gid, ini = r["game_id"], r["inicio"]
        if gid in M56_REPROGRAMADOS or any(abs((t - ini).total_seconds()) > M56_REPROG_H * 3600 for t in reg.get(gid, [])):
            d["reprogramados"] += 1
            continue
        fs = fotos.get(gid, [])
        temp = [x for x in fs if M56_TEMPRANA_H[0] * 3600 <= (ini - x[0]).total_seconds() <= M56_TEMPRANA_H[1] * 3600]
        cie = [x for x in fs if 0 < (ini - x[0]).total_seconds() <= M56_CIERRE_MAX_MIN * 60]
        if not temp:
            d["sin_temprana"] += 1
        elif not cie:
            d["sin_cierre"] += 1
        else:
            t_, c_ = max(temp, key=lambda x: x[0]), max(cie, key=lambda x: x[0])
            if t_[1] is None or c_[1] is None:          # la foto que corresponde no trae hándicap: fuera (se cuenta)
                d["sin_handicap"] += 1
            else:
                d["con_fotos"] += 1
                d["casos"] += int(abs(c_[1] - t_[1]) >= M56_UMBRAL)
    return out


def seccion_56(g26, bot_dir, semana):
    """Línea del informe semanal con el conteo de 56 (solo cuántos casos). ('', []) si todavía no hay juegos."""
    c = conteo_56(g26, bot_dir)
    if not c:
        return "", []
    vacio = dict(casos=0, con_fotos=0, sin_temprana=0, sin_cierre=0, sin_handicap=0, reprogramados=0)
    s = c.get(semana, vacio)
    t = {k: sum(v[k] for v in c.values()) for k in vacio}
    aviso = "" if _cierres_legible(bot_dir) else " · aviso: cierres.csv del bot no se pudo leer (el cierre sale de lineas_log.csv)"
    tel = (f"Movimiento tardío (56, solo conteos): semana {semana}: {s['casos']} casos de {s['con_fotos']} juegos con las dos "
           f"fotos · acumulado desde el 11-oct: {t['casos']} de {t['con_fotos']} (fuera: sin foto "
           f"{t['sin_temprana'] + t['sin_cierre']}, sin hándicap {t['sin_handicap']}, reprogramados {t['reprogramados']})"
           f"{aviso} · veredicto una sola vez al cerrar la semana 18 de 2027 si hay ≥ 40 casos")
    lin = ["MOVIMIENTO TARDÍO (56): casos = |Pinnacle al cierre − Pinnacle 3-8 h antes| ≥ 1,0 pt; solo conteos, nunca la tasa",
           f"  Semana {semana}: casos {s['casos']} · con las dos fotos {s['con_fotos']} · sin foto temprana {s['sin_temprana']} · "
           f"sin cierre del bot (≤ {M56_CIERRE_MAX_MIN} min) {s['sin_cierre']} · sin hándicap {s['sin_handicap']} · "
           f"reprogramados {s['reprogramados']}",
           f"  Acumulado desde el 11-oct-2026: casos {t['casos']} · con las dos fotos {t['con_fotos']} · sin foto temprana "
           f"{t['sin_temprana']} · sin cierre {t['sin_cierre']} · sin hándicap {t['sin_handicap']} · reprogramados {t['reprogramados']}",
           "  Cierre = la última foto de Pinnacle del bot (lineas_log.csv o cierres.csv) tomada ≤ 20 min antes del inicio, como el "
           "cierre que usa 29A." + aviso,
           "  Regla (56): veredicto una sola vez al cerrar la semana 18 de 2027 con ≥ 40 casos (si no, la de 2028)."]
    return tel, lin


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
    # ---- v9 (65.1): verificación del vigía-alineador de Claude ----
    try:
        vc_tel, vc_txt = seccion_vigia_claude(g26)
    except Exception as e:  # noqa: BLE001
        vc_tel, vc_txt = f"Vigía-alineador Claude (65.1): no se pudo verificar ({type(e).__name__}).", []
    if vc_tel:
        tel.append(vc_tel)
    # ---- v8.4 (57): bandera de sesgo dentro de la semana (solo registro) ----
    try:
        bd_tel, bd_txt = seccion_bandera(semana, senal)
    except Exception as e:  # noqa: BLE001
        bd_tel, bd_txt = f"Bandera de sesgo (57): no se pudo contar ({type(e).__name__}).", []
    tel.append(bd_tel)
    # ---- v9.2 (60d): clima a T−85 (#9 a ciegas: solo conteos) ----
    try:
        cl_tel, cl_txt = seccion_clima(semana)
    except Exception as e:  # noqa: BLE001
        cl_tel, cl_txt = f"Clima (60d): no se pudo armar ({type(e).__name__}).", []
    if cl_tel:
        tel.append(cl_tel)
    # ---- v9.2 (56): movimiento tardío, solo conteos ----
    try:
        m56_tel, m56_txt = seccion_56(g26, bot_dir, semana)
    except Exception as e:  # noqa: BLE001
        m56_tel, m56_txt = f"Movimiento tardío (56): no se pudo contar ({type(e).__name__}).", []
    if m56_tel:
        tel.append(m56_tel)
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
    completo += [""] + fu_txt + [""] + vg_txt + ([""] + bd_txt if bd_txt else []) + ([""] + vc_txt if vc_txt else [])
    completo += ([""] + cl_txt if cl_txt else []) + ([""] + m56_txt if m56_txt else [])      # v9.2
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
                                     "vigia-prueba", "tablero", "vigia-manual", "autopsia", "briefing", "claude-prueba"])
    ap.add_argument("--variante", choices=sorted(GEMINI_VARIANTES))
    ap.add_argument("--semana", type=int)
    ap.add_argument("--juegos")
    ap.add_argument("--tipo", default="manual")
    ap.add_argument("--ahora")
    ap.add_argument("--sin-telegram", action="store_true")
    ap.add_argument("--real", action="store_true")     # v8.3: vigia-prueba --real hace 1 consulta real por modelo (no cuenta)
    ap.add_argument("--equipo")                         # v9 (63): vigia-manual --equipo KC
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
        try:
            print(texto_claude_estado(ahora, estado))      # v9 (65.1)
        except Exception as e:  # noqa: BLE001
            print(f"Agentes de Claude (65): no pude leer su registro ({type(e).__name__})")
        try:
            print(texto_clima_estado())                # v9.2 (60d)
        except Exception as e:  # noqa: BLE001
            print(f"Clima (60d): no pude leer su registro ({type(e).__name__})")
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

    if args.modo == "tablero":                         # v8.4 (58): tablero tipo PFF Pro a mano (no toca el motor)
        print(actualizar_tablero("a mano"))
        return

    if args.modo == "vigia-prueba":                    # v8.3 (55): sin consultar a Gemini; --real: 1 consulta por modelo
        if args.real:
            print(vigia_prueba_real(g26, ahora, estado))
            guardar_estado(estado)
        else:
            print(vigia_autoprueba(g26))
        return

    if args.modo == "claude-prueba":                   # v9 (65.1): sin consultar; --real: 1 consulta real (no cuenta)
        if args.real:
            print(claude_prueba_real(g26, ahora, estado))
            guardar_estado(estado)
        else:
            print(claude_autoprueba(g26))
        return

    if args.modo in ("vigia-manual", "autopsia", "briefing"):   # v9: órdenes largas, nunca antes de una automática
        cerca = automatica_cerca(g26, ahora, estado)
        if cerca and args.modo != "vigia-manual":
            print(f"No corro ahora: en menos de {ANTES_AUTOMATICA_MIN} min toca la corrida automática "
                  f"({NOMBRE_CORRIDA.get(cerca[0], cerca[0])}), que es la que cuenta. Pídelo después de esa corrida.")
            return
        if args.modo == "vigia-manual":              # 63 (/vigia): la protección y los topes van dentro
            vigia_manual(g26, args, ahora, estado, hoja)
        elif args.modo == "autopsia":                # A3 a pedido (/autopsia [N])
            sem = args.semana or semana_reciente(g26)
            print("Todavía no hay juegos jugados." if sem is None else
                  autopsia_enviar(g26, sem, args.bot_dir, ahora, estado, "pedido", args.sin_telegram))
        else:                                        # A4 a pedido (/briefing)
            print(briefing_correr(g26, ahora, estado, "pedido", args.sin_telegram))
        guardar_estado(estado)
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
                actualizar_tablero("resultados nuevos")       # v8.4 (58)
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
            # v9 (65, A3): autopsia del lunes de cada semana cuyo informe ya salió (desde la semana 7), una vez por semana;
            # si falla, reintenta cada 30 min y nunca frena el temporizador
            falla_a3 = t_utc(estado.get("ultima_falla_autopsia"))
            if CLAUDE_LLAVE.exists() and claude_cfg()[0] and (falla_a3 is None or (ahora - falla_a3).total_seconds() > 1800):
                try:
                    for s_ in autopsias_pendientes(estado):
                        autopsia_enviar(g26, s_, args.bot_dir, ahora, estado, "auto", args.sin_telegram)
                        estado.pop("ultima_falla_autopsia", None)
                        guardar_estado(estado)
                except Exception as e:  # noqa: BLE001
                    log(f"Autopsia (A3): error ({type(e).__name__}: {str(e)[:300]})")
                    estado["ultima_falla_autopsia"] = iso(ahora)
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
    # v9.2 (60d): el clima arranca en un proceso aparte, ya guardada la proyección; nunca la frena ni la cambia
    trab_clima = clima_lanzar(sombra, ahora) if sombra and args.modo == "auto" else None
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
    # v9 (65.1): el vigía-alineador de Claude arranca en un hilo aparte y corre en paralelo con g1, el vigía y e2
    trab_c = a1_lanzar([j for j, _ in sombra], ahora, "t85") if sombra and args.modo == "auto" else None
    if sombra:                                        # 35A: el agente en sombra corre después de guardar y enviar
        gemini_sombra(sombra, ahora, estado)
        guardar_estado(estado)
    clima_revisar(trab_clima, sin_telegram=args.sin_telegram)      # v9.2: si ya terminó, su Telegram sale ahora
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
    clima_revisar(trab_clima, sin_telegram=args.sin_telegram)      # v9.2
    if sombra and args.modo == "auto":                # v8.2 (49): registro en vivo e2, aparte de g1 y después de él
        e2_vivo(sombra, ahora, estado)
        guardar_estado(estado)
    if trab_c:                                        # v9 (65.1): resultado del vigía-alineador (Telegram aparte, piloto)
        res_c = a1_cerrar(trab_c, [f for _, _, filas, _ in resumenes for f in filas], g26)
        if res_c and not args.sin_telegram:
            try:
                enviar_tg(texto_a1(res_c))
            except Exception as e:  # noqa: BLE001
                log(f"Vigía-alineador Claude: no pude mandar el Telegram ({type(e).__name__})")
    clima_revisar(trab_clima, esperar=True, sin_telegram=args.sin_telegram)   # v9.2: a más tardar a los 100 s
    actualizar_tablero(", ".join(sorted({t for t, _, _ in lista})))   # v8.4 (58): al final, sin frenar nada
    if (args.modo == "auto" and any(t == "sabado" for t, _, _ in lista) and CLAUDE_LLAVE.exists() and claude_cfg()[0]):
        try:                                          # v9 (65, A4): analista del sábado, una vez por semana
            sem_b = semana_actual(g26, ahora)
            if sem_b is not None and str(sem_b) not in estado.get("briefing", {}):
                briefing_correr(g26, ahora, estado, "sabado", args.sin_telegram)
                guardar_estado(estado)
        except Exception as e:  # noqa: BLE001
            log(f"Analista (A4): error ({type(e).__name__}: {str(e)[:300]})")
    log("== LISTO")


if __name__ == "__main__":
    main()
