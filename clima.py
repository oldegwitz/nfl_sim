#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
clima.py — Pronóstico del clima a T−85 (decisión 60d) y registro de #9 (60c), declarado sin potencia.

Especificación aprobada por Ozz el 30-oct-2026 (claude/registro_60_clima.md; regla de #9 registrada a las 17:06 UTC,
antes de mirar cualquier dato de 2026 sobre viento, totales o resultados). Es descriptivo: no toca s2-v1, la
proyección, 31A, 29A ni la hoja del motor.

Qué hace el modo 'registrar' (lo lanza semana.py en un proceso aparte, en cada T−85 automática)
  1. Lee de datos/games.csv (el calendario que semana.py acaba de refrescar) los juegos del grupo: inicio, estadio,
     techo según nflverse y total de nflverse en ese momento.
  2. Pide el pronóstico por hora de NWS (solo estadios de EE. UU.) y de Open-Meteo (todos), a la hora del inicio y en
     las 3 horas del partido. 10 s por consulta, un reintento ante un error 5xx o de red, 90 s en total.
  3. Guarda una fila por juego y fuente en salidas/semana/clima_pronostico.csv y una por juego en clima_casos.csv con
     la regla de #9 aplicada en ese momento:
       · caso: temporada regular, techo «outdoors» en nflverse, viento sostenido pronosticado para la hora del inicio
         ≥ 15 mph (NWS en EE. UU.; Open-Meteo fuera o si NWS falla; se anota cuál);
       · placebo: el mismo pronóstico ≥ 15 mph en un estadio techado (domo o retráctil que no figure abierto).
  4. Imprime una línea «CLIMA_JSON {...}» con el resumen y, si algún partido al aire libre tiene viento ≥ 15 mph,
     lluvia ≥ 60 % o ≤ 0 °C, el texto corto para Telegram (lo manda semana.py; decisión D2 = a).
  #9 va A CIEGAS: este archivo solo cuenta casos. Nunca calcula la tasa de unders ni el residuo del total; eso se hace
  una sola vez al cerrar la semana 18 de 2028, con revisor independiente (registro 60, sección 4).

Uso
  venv/bin/python clima.py registrar --corrida 2026-11-01T16:35:00Z --juegos ID,ID   (lo usa semana.py)
  venv/bin/python clima.py prueba              (sin red: NWS y Open-Meteo simulados, reglas de #9, registro temporal)
  venv/bin/python clima.py prueba --real       (1 consulta real a NWS y a Open-Meteo para un estadio de EE. UU. y uno
                                                de fuera; no escribe en el registro)
  venv/bin/python clima.py coordenadas         (revisa la tabla de estadios: ciudad según NWS, altura según Open-Meteo y
                                                cruce con el calendario 2026)
  venv/bin/python clima.py estado              (conteos)
  venv/bin/python clima.py informe --semana N  (la sección «Clima» del informe semanal, como la arma semana.py)

Datos del tiempo: National Weather Service (api.weather.gov, dominio público) y Open-Meteo.com (CC BY 4.0, uso no
comercial, sin llave). Ninguna credencial: NWS solo pide un User-Agent (semana.ini [clima] contacto es opcional).
"""
import argparse
import configparser
import csv
import datetime as dt
import fcntl
import io
import json
import os
import re
import sys
import tempfile
import threading
import time
from pathlib import Path
from zoneinfo import ZoneInfo

VERSION_CLIMA = "clima-v1 (30-oct-2026)"
BASE = Path(__file__).resolve().parent
DATOS = BASE / "datos"
SAL = BASE / "salidas" / "semana"
CONFIG = BASE / "semana.ini"
GAMES = DATOS / "games.csv"                          # el calendario que baja semana.py (nflverse)
PBP = DATOS / "pbp_2026.parquet"                     # la jugada por jugada que baja semana.py (verdad del viento)
CACHE_PUNTOS = DATOS / "clima" / "nws_points.json"   # /points de NWS por estadio (NWS: se pueden guardar)
PRONOSTICO = SAL / "clima_pronostico.csv"
CASOS = SAL / "clima_casos.csv"
NUEVA_YORK = ZoneInfo("America/New_York")
CARACAS = ZoneInfo("America/Caracas")
TEMPORADA = 2026

URL_NWS_PUNTO = "https://api.weather.gov/points/{lat:.4f},{lon:.4f}"
URL_OM = "https://api.open-meteo.com/v1/forecast"
OM_VARIABLES = ("temperature_2m", "precipitation_probability", "precipitation", "snowfall", "wind_speed_10m",
                "wind_direction_10m", "wind_gusts_10m")
PLAZO_CONSULTA_S = 10                               # por consulta (conectar 5 s, leer 10 s)
PLAZO_TOTAL_S = 60                                  # tope duro de las consultas; después se guarda lo que haya
                                                    # (semana.py espera hasta 100 s: queda margen para escribir)
REINTENTO_S = 2
HILOS = 8
VENTANA_H = 3                                       # horas del partido
UMBRAL_VIENTO = 15.0                                # #9 y aviso (mph, viento sostenido)
UMBRAL_LLUVIA = 60                                  # aviso (% de probabilidad)
UMBRAL_FRIO_C = 0.0                                 # aviso (°C)
INFORME_FINAL = "al cerrar la semana 18 de 2028"    # #9: informe descriptivo, una sola vez (registro 60)
SEMILLA_INFORME_FINAL = 6002026                     # remuestreo del informe final (registro 60)
JSON_MARCA = "CLIMA_JSON "

# Tabla de estadios: (stadium_id, nombre en nflverse, lat, lon, país, techo real, ciudad).
# Coordenadas revisadas el 30-oct-2026: los 30 de EE. UU. contra /points de NWS (ciudad y distancia); los de fuera se
# revisan con el modo 'coordenadas' (altura de Open-Meteo). techo: abierto | domo | retractil (el techo real; nflverse
# marca «dome» a estadios de Europa y Australia que tienen la cancha descubierta).
ESTADIOS = [
    ("ATL97", "Mercedes-Benz Stadium", 33.7554, -84.4008, "US", "retractil", "Atlanta, GA"),
    ("BAL00", "M&T Bank Stadium", 39.2780, -76.6227, "US", "abierto", "Baltimore, MD"),
    ("BOS00", "Gillette Stadium", 42.0909, -71.2643, "US", "abierto", "Foxborough, MA"),
    ("BUF00", "Highmark Stadium", 42.7738, -78.7870, "US", "abierto", "Orchard Park, NY"),
    ("CAR00", "Bank of America Stadium", 35.2258, -80.8528, "US", "abierto", "Charlotte, NC"),
    ("CHI98", "Soldier Field", 41.8623, -87.6167, "US", "abierto", "Chicago, IL"),
    ("CIN00", "Paycor Stadium", 39.0954, -84.5160, "US", "abierto", "Cincinnati, OH"),
    ("CLE00", "Huntington Bank Field", 41.5061, -81.6995, "US", "abierto", "Cleveland, OH"),
    ("DAL00", "AT&T Stadium", 32.7473, -97.0945, "US", "retractil", "Arlington, TX"),
    ("DEN00", "Empower Field at Mile High", 39.7439, -105.0201, "US", "abierto", "Denver, CO"),
    ("DET00", "Ford Field", 42.3400, -83.0456, "US", "domo", "Detroit, MI"),
    ("GNB00", "Lambeau Field", 44.5013, -88.0622, "US", "abierto", "Green Bay, WI"),
    ("HOU00", "Reliant Stadium", 29.6847, -95.4107, "US", "retractil", "Houston, TX"),
    ("IND00", "Lucas Oil Stadium", 39.7601, -86.1639, "US", "retractil", "Indianapolis, IN"),
    ("JAX00", "EverBank Stadium", 30.3239, -81.6373, "US", "abierto", "Jacksonville, FL"),
    ("KAN00", "GEHA Field at Arrowhead Stadium", 39.0489, -94.4839, "US", "abierto", "Kansas City, MO"),
    ("LAX01", "SoFi Stadium", 33.9535, -118.3392, "US", "domo", "Inglewood, CA"),
    ("MIA00", "Hard Rock Stadium", 25.9580, -80.2389, "US", "abierto", "Miami Gardens, FL"),
    ("MIN01", "U.S. Bank Stadium", 44.9737, -93.2575, "US", "domo", "Minneapolis, MN"),
    ("NAS00", "Nissan Stadium", 36.1665, -86.7713, "US", "abierto", "Nashville, TN"),
    ("NOR00", "Caesars Superdome", 29.9511, -90.0812, "US", "domo", "New Orleans, LA"),
    ("NYC01", "MetLife Stadium", 40.8135, -74.0745, "US", "abierto", "East Rutherford, NJ"),
    ("PHI00", "Lincoln Financial Field", 39.9008, -75.1675, "US", "abierto", "Philadelphia, PA"),
    ("PHO00", "State Farm Stadium", 33.5276, -112.2626, "US", "retractil", "Glendale, AZ"),
    ("PIT00", "Acrisure Stadium", 40.4468, -80.0158, "US", "abierto", "Pittsburgh, PA"),
    ("SEA00", "Lumen Field", 47.5952, -122.3316, "US", "abierto", "Seattle, WA"),
    ("SFO01", "Levi's Stadium", 37.4030, -121.9700, "US", "abierto", "Santa Clara, CA"),
    ("TAM00", "Raymond James Stadium", 27.9759, -82.5033, "US", "abierto", "Tampa, FL"),
    ("VEG00", "Allegiant Stadium", 36.0909, -115.1833, "US", "domo", "Paradise, NV"),
    ("WAS00", "Northwest Stadium", 38.9078, -76.8645, "US", "abierto", "Landover, MD"),
    ("LON00", "Wembley Stadium", 51.5560, -0.2796, "GB", "abierto", "London"),
    ("LON02", "Tottenham Hotspur Stadium", 51.6043, -0.0664, "GB", "abierto", "London"),
    ("MAD01", "Bernabeu", 40.4531, -3.6883, "ES", "retractil", "Madrid"),
    ("MEL00", "Melbourne Cricket Ground", -37.8200, 144.9834, "AU", "abierto", "Melbourne"),
    ("MEX00", "Estadio Banorte", 19.3029, -99.1505, "MX", "abierto", "Mexico City"),
    ("MUN01", "FC Bayern Munich Stadium", 48.2188, 11.6247, "DE", "abierto", "Munich"),
    ("PAR00", "Stade de France", 48.9245, 2.3602, "FR", "abierto", "Saint-Denis"),
    ("RIO00", "Maracana Stadium", -22.9122, -43.2302, "BR", "abierto", "Rio de Janeiro"),
]
CAMPOS_EST = ("stadium_id", "nombre", "lat", "lon", "pais", "techo", "ciudad")
POR_NOMBRE = {e[1].strip().lower(): dict(zip(CAMPOS_EST, e)) for e in ESTADIOS}
POR_ID = {e[0]: dict(zip(CAMPOS_EST, e)) for e in ESTADIOS}

CAMPOS_PRON = ["corrida_utc", "consultado_utc", "version", "game_id", "semana", "game_type", "inicio_utc",
               "minutos_antes", "visita", "local", "stadium_id", "estadio", "cruce", "pais", "techo_tabla", "roof_t85",
               "location", "total_t85", "lat", "lon", "fuente", "estado", "http", "latencia_s", "nws_rejilla",
               "nws_actualizado", "hora_pronostico_utc", "temp_c", "viento_mph", "viento_texto", "rafaga_mph",
               "direccion", "prob_lluvia", "lluvia_mm", "nieve_cm", "texto", "temp_c_3h", "viento_mph_3h",
               "rafaga_mph_3h", "prob_lluvia_3h", "lluvia_mm_3h", "nieve_cm_3h", "detalle"]
CAMPOS_CASOS = ["corrida_utc", "version", "game_id", "semana", "game_type", "inicio_utc", "visita", "local", "estadio",
                "techo_tabla", "roof_t85", "techo_coincide", "total_t85", "fuente_decide", "viento_decide", "temp_c",
                "prob_lluvia", "al_aire_libre", "caso9", "placebo9", "notable"]
RUMBOS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


# --------------------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------------------
_AVISOS = []                                        # avisos de esta corrida (van también en el resumen para semana.py)


def log(msg):
    _AVISOS.append(str(msg)[:200])
    print(f"[{dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC] clima: {msg}", flush=True)


def iso(t):
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def t_utc(txt):
    if not txt:
        return None
    try:
        t = dt.datetime.fromisoformat(str(txt).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)).astimezone(dt.timezone.utc)


def fecha_cc(t):
    c = t.astimezone(CARACAS)
    return f"{DIAS[c.weekday()]} {c.day:02d}-{MESES[c.month - 1]} {c:%H:%M}"


def inicio_utc(gameday, gametime):
    """Fecha y hora de nflverse (hora del Este de EE. UU.) → UTC (igual que semana.py)."""
    if not gameday or not gametime:
        return None
    h, m = (int(x) for x in str(gametime).split(":")[:2])
    y, mo, d = (int(x) for x in str(gameday).split("-"))
    return dt.datetime(y, mo, d, h, m, tzinfo=NUEVA_YORK).astimezone(dt.timezone.utc)


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if v != v else v


def _r(x, d=1):
    if x is None:
        return None
    return int(round(x)) if d == 0 else round(x, d)


def f_a_c(f):
    return None if f is None else (f - 32.0) * 5.0 / 9.0


def rumbo(grados):
    g = _num(grados)
    return "" if g is None else RUMBOS[int((g % 360) / 22.5 + 0.5) % 16]


def viento_de_texto(txt):
    """«15 mph» → 15; «10 to 15 mph» → 12,5; «Calm» → 0. None si no se entiende."""
    if txt is None:
        return None
    s = str(txt).strip().lower()
    if not s:
        return None
    if "calm" in s:
        return 0.0
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:to|-)\s*(\d+(?:\.\d+)?)", s)
    if m:
        return (float(m.group(1)) + float(m.group(2))) / 2.0
    m = re.search(r"(\d+(?:\.\d+)?)", s)
    return float(m.group(1)) if m else None


def viento_del_gamebook(txt):
    """Viento real del texto 'weather' de la jugada por jugada (el del gamebook): «… Wind: NW 13 mph» → 13;
    «Wind: Calm» → 0; «Wind: 0-5 mph» → 2,5. Solo lee «Wind:» (no «Windy» ni «Wind Chill:»). None si no trae viento."""
    if not txt:
        return None
    ms = list(re.finditer(r"\bwind\s*:\s*([^,;)]*)", str(txt), flags=re.IGNORECASE))
    if not ms:
        return None
    resto = ms[-1].group(1)
    m2 = re.search(r"(\d+(?:\.\d+)?)\s*(?:-|to)\s*(\d+(?:\.\d+)?)", resto)
    if m2:
        return (float(m2.group(1)) + float(m2.group(2))) / 2.0
    m3 = re.search(r"(\d+(?:\.\d+)?)", resto)
    if m3:
        return float(m3.group(1))
    return 0.0 if re.search(r"\b(calm|none)\b", resto, flags=re.IGNORECASE) else None


def cfg():
    c = configparser.ConfigParser()
    try:
        c.read(CONFIG, encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    s = c["clima"] if c.has_section("clima") else {}
    activo = str(s.get("activo", "si")).strip().lower() not in ("no", "0", "false")
    contacto = str(s.get("contacto", "")).strip()
    return {"activo": activo, "contacto": contacto}


def user_agent(contacto=""):
    return f"nfl-secret-lab/1.0 (uso personal{'; ' + contacto if contacto else ''})"


# --------------------------------------------------------------------------------------
# Juegos y estadios
# --------------------------------------------------------------------------------------
def leer_juegos(ids=None, ruta=GAMES, temporada=TEMPORADA):
    """Juegos de la temporada desde games.csv de nflverse (solo los campos que hacen falta; nunca resultados)."""
    out = []
    if not Path(ruta).exists():
        return out
    pedir = set(ids) if ids else None
    with open(ruta, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if str(r.get("season")) != str(temporada):
                continue
            if pedir is not None and r.get("game_id") not in pedir:
                continue
            out.append(dict(game_id=r.get("game_id"), semana=int(_num(r.get("week")) or 0), game_type=r.get("game_type") or "",
                            inicio=inicio_utc(r.get("gameday"), r.get("gametime")), visita=r.get("away_team") or "",
                            local=r.get("home_team") or "", stadium_id=r.get("stadium_id") or "",
                            estadio=r.get("stadium") or "", roof=(r.get("roof") or "").strip().lower(),
                            location=r.get("location") or "", total=_num(r.get("total_line"))))
    return out


def estadio_de(g):
    """Cruce con la tabla: (1) por nombre; (2) por id solo si el juego es de local (un juego en el extranjero puede venir
    con el id del equipo local, p. ej. Tottenham con JAX00). → (dict | None, 'nombre' | 'id' | 'sin cruce')."""
    e = POR_NOMBRE.get((g.get("estadio") or "").strip().lower())
    if e:
        return e, "nombre"
    e = POR_ID.get(g.get("stadium_id") or "")
    if e and (g.get("location") or "").strip().lower() == "home":
        return e, "id"
    return None, "sin cruce"


# --------------------------------------------------------------------------------------
# Cliente HTTP con plazo total, reintento y User-Agent
# --------------------------------------------------------------------------------------
def _get_requests(url, params=None, headers=None, timeout=10):
    import requests
    r = requests.get(url, params=params, headers=headers, timeout=(min(5.0, timeout), timeout))
    return r.status_code, r.text


class Cliente:
    """get(url, params, headers, timeout) → (status, texto). Un reintento ante 5xx o error de red; plazo total."""

    def __init__(self, ua, get=None, plazo_total=PLAZO_TOTAL_S, dormir=time.sleep, reloj=time.monotonic):
        self.ua, self.get, self.dormir, self.reloj = ua, (get or _get_requests), dormir, reloj
        self.fin = reloj() + plazo_total

    def json(self, url, params=None, accept="application/geo+json"):
        info = {"http": "", "latencia": 0.0, "error": ""}
        for intento in (1, 2):
            restante = self.fin - self.reloj()
            if restante <= 0.5:
                info["error"] = "plazo"
                return None, info
            t0 = self.reloj()
            try:
                st, txt = self.get(url, params=params, headers={"User-Agent": self.ua, "Accept": accept},
                                   timeout=min(PLAZO_CONSULTA_S, restante))
            except Exception as e:  # noqa: BLE001
                info.update(latencia=round(self.reloj() - t0, 2), error=f"red: {type(e).__name__}", http="")
                if intento == 1:
                    self.dormir(REINTENTO_S)
                    continue
                return None, info
            info.update(http=st, latencia=round(self.reloj() - t0, 2))
            if st == 200:
                try:
                    return json.loads(txt), dict(info, error="")
                except (ValueError, TypeError):
                    info["error"] = "respuesta rota"
                    return None, info
            info["error"] = f"http {st}"
            if 500 <= int(st) < 600 and intento == 1:
                self.dormir(REINTENTO_S)
                continue
            return None, info
        return None, info


# --------------------------------------------------------------------------------------
# NWS y Open-Meteo
# --------------------------------------------------------------------------------------
_CANDADO_CACHE = threading.Lock()


def cargar_cache(ruta=CACHE_PUNTOS):
    try:
        return json.loads(Path(ruta).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def guardar_cache(cache, ruta=CACHE_PUNTOS):
    with _CANDADO_CACHE:                                 # algún hilo vencido por el plazo podría seguir escribiendo
        datos = dict(cache)
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_suffix(".tmp")
    tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(ruta)


def nws_punto(cli, est, cache):
    """/points del estadio (de la caché si ya se pidió). → (dict | None, info)."""
    clave = est["stadium_id"] + "|" + est["nombre"]
    with _CANDADO_CACHE:
        if clave in cache and cache[clave].get("forecastHourly"):
            return cache[clave], {"http": "caché", "latencia": 0.0, "error": ""}
    d, info = cli.json(URL_NWS_PUNTO.format(lat=est["lat"], lon=est["lon"]))
    if d is None:
        return None, info
    p = d.get("properties") or {}
    rl = ((p.get("relativeLocation") or {}).get("properties") or {})
    punto = {"forecastHourly": p.get("forecastHourly"), "rejilla": f"{p.get('gridId')} {p.get('gridX')},{p.get('gridY')}",
             "ciudad": f"{rl.get('city', '')}, {rl.get('state', '')}",
             "distancia_km": _r((_num((rl.get("distance") or {}).get("value")) or 0) / 1000.0, 1)}
    if not punto["forecastHourly"]:
        return None, dict(info, error="sin forecastHourly")
    with _CANDADO_CACHE:
        cache[clave] = punto
    return punto, info


def _ventana(ini, fin, inicio, horas=VENTANA_H):
    """¿El intervalo [ini, fin) se cruza con las horas del partido [inicio, inicio + horas)?"""
    return ini < inicio + dt.timedelta(hours=horas) and fin > inicio


def _media(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def nws_pronostico(cli, est, inicio, cache):
    """Pronóstico por hora de NWS en el período que contiene el inicio y en las horas del partido."""
    fila = {"fuente": "nws"}
    punto, info = nws_punto(cli, est, cache)
    if punto is None:
        fila.update(estado="error", http=info["http"], latencia_s=info["latencia"],
                    detalle=f"points: {info['error'] or 'sin datos'}")
        return fila
    fila["nws_rejilla"] = punto.get("rejilla", "")
    d, info2 = cli.json(punto["forecastHourly"])
    fila.update(http=info2["http"], latencia_s=round((info["latencia"] or 0) + (info2["latencia"] or 0), 2))
    if d is None:
        fila.update(estado="error", detalle=f"hourly: {info2['error'] or 'sin datos'}")
        return fila
    props = d.get("properties") or {}
    fila["nws_actualizado"] = props.get("updateTime") or props.get("updated") or ""
    periodos = []
    for p in props.get("periods") or []:
        a, b = t_utc(p.get("startTime")), t_utc(p.get("endTime"))
        if a is None or b is None:
            continue
        unidad = (p.get("temperatureUnit") or "F").upper()
        temp = _num(p.get("temperature"))
        temp_c = f_a_c(temp) if unidad == "F" else temp
        pp = p.get("probabilityOfPrecipitation")
        prob = _num(pp.get("value") if isinstance(pp, dict) else pp)
        raf = p.get("windGust")
        raf = viento_de_texto(raf.get("value") if isinstance(raf, dict) else raf) if raf not in (None, "") else None
        periodos.append(dict(a=a, b=b, temp_c=temp_c, viento=viento_de_texto(p.get("windSpeed")),
                             viento_texto=p.get("windSpeed") or "", rafaga=raf, dir=p.get("windDirection") or "",
                             prob=prob, texto=p.get("shortForecast") or ""))
    en = [p for p in periodos if p["a"] <= inicio < p["b"]]
    if not en:
        fila.update(estado="sin hora", detalle=f"el pronóstico no cubre el inicio ({len(periodos)} períodos)")
        return fila
    k = en[0]
    ven = [p for p in periodos if _ventana(p["a"], p["b"], inicio)]
    probs = [p["prob"] for p in ven if p["prob"] is not None]
    fila.update(estado="ok", hora_pronostico_utc=iso(k["a"]), temp_c=_r(k["temp_c"]), viento_mph=_r(k["viento"]),
                viento_texto=k["viento_texto"], rafaga_mph=_r(k["rafaga"]), direccion=k["dir"],
                prob_lluvia=_r(k["prob"], 0), texto=k["texto"],
                temp_c_3h=_r(_media([p["temp_c"] for p in ven])), viento_mph_3h=_r(_media([p["viento"] for p in ven])),
                rafaga_mph_3h=_r(_media([p["rafaga"] for p in ven])), prob_lluvia_3h=_r(max(probs), 0) if probs else None)
    return fila


def om_pronostico(cli, est, inicio, dias=7):
    """Pronóstico por hora de Open-Meteo (hora UTC) en la hora del inicio y en las horas del partido."""
    fila = {"fuente": "openmeteo"}
    params = {"latitude": f"{est['lat']:.4f}", "longitude": f"{est['lon']:.4f}", "hourly": ",".join(OM_VARIABLES),
              "wind_speed_unit": "mph", "timezone": "GMT", "forecast_days": str(dias)}
    d, info = cli.json(URL_OM, params=params, accept="application/json")
    fila.update(http=info["http"], latencia_s=info["latencia"])
    if d is None:
        fila.update(estado="error", detalle=info["error"] or "sin datos")
        return fila
    h = d.get("hourly") or {}
    horas = [t_utc((x or "") + ("" if str(x).endswith("Z") else "+00:00")) for x in (h.get("time") or [])]
    if not horas:
        fila.update(estado="error", detalle="respuesta sin horas")
        return fila

    def col(nombre):
        v = h.get(nombre) or []
        return [_num(x) for x in v] + [None] * (len(horas) - len(v))

    # Open-Meteo: temperatura, viento sostenido y dirección son del instante de la marca horaria; lluvia, su
    # probabilidad, nieve y ráfaga valen para la hora ANTERIOR a la marca (la hora del inicio es la marca siguiente).
    temp, prob, lluvia, nieve = col("temperature_2m"), col("precipitation_probability"), col("precipitation"), col("snowfall")
    vel, dire, raf = col("wind_speed_10m"), col("wind_direction_10m"), col("wind_gusts_10m")
    piso = inicio.replace(minute=0, second=0, microsecond=0)
    try:
        i = horas.index(piso)
    except ValueError:
        fila.update(estado="sin hora", detalle=f"el pronóstico no cubre el inicio ({len(horas)} horas)")
        return fila
    k = i + 1 if i + 1 < len(horas) else None                     # la hora que contiene el inicio, para lo «anterior»
    fin = inicio + dt.timedelta(hours=VENTANA_H)
    v_inst = [j for j, t in enumerate(horas) if t is not None and piso <= t < fin]
    v_prev = [j for j, t in enumerate(horas) if t is not None and inicio < t and t - dt.timedelta(hours=1) < fin]
    probs = [prob[j] for j in v_prev if prob[j] is not None]

    def en(v, j, d=1):
        return None if j is None else _r(v[j], d)

    fila.update(estado="ok", hora_pronostico_utc=iso(horas[i]), temp_c=_r(temp[i]), viento_mph=_r(vel[i]),
                viento_texto="", rafaga_mph=en(raf, k), direccion=rumbo(dire[i]), prob_lluvia=en(prob, k, 0),
                lluvia_mm=en(lluvia, k, 2), nieve_cm=en(nieve, k, 2), texto="",
                temp_c_3h=_r(_media([temp[j] for j in v_inst])), viento_mph_3h=_r(_media([vel[j] for j in v_inst])),
                rafaga_mph_3h=_r(_media([raf[j] for j in v_prev])), prob_lluvia_3h=_r(max(probs), 0) if probs else None,
                lluvia_mm_3h=_r(sum(lluvia[j] or 0 for j in v_prev), 2), nieve_cm_3h=_r(sum(nieve[j] or 0 for j in v_prev), 2),
                detalle=f"altura {d.get('elevation')} m")
    return fila


# --------------------------------------------------------------------------------------
# Regla de #9 y aviso (aplicadas en la T−85; registro 60, secciones 4 y 5)
# --------------------------------------------------------------------------------------
def techo_coincide(roof, techo):
    if roof == "outdoors":
        return techo == "abierto"
    if roof in ("dome", "closed"):
        return techo in ("domo", "retractil")
    if roof == "open":
        return techo == "retractil"
    return True                                       # vacío (retráctil antes del juego): no hay con qué comparar


def al_aire_libre(roof, techo):
    """Para el aviso y la precisión (descriptivo): nflverse lo da abierto («outdoors» u «open») o la tabla dice que el
    estadio no tiene techo (nflverse marca «dome» a estadios de Europa con la cancha descubierta)."""
    return roof in ("outdoors", "open") or techo == "abierto"


def decidir(g, est, filas):
    """Fila de clima_casos.csv: fuente que decide, viento que decide, caso de #9, placebo y aviso."""
    por = {f.get("fuente"): f for f in filas if f.get("fuente")}
    nws, om = por.get("nws", {}), por.get("openmeteo", {})
    if est and est["pais"] == "US" and nws.get("estado") == "ok" and nws.get("viento_mph") is not None:
        dec = nws
    elif om.get("estado") == "ok" and om.get("viento_mph") is not None:
        dec = om
    else:
        dec = {}
    techo = est["techo"] if est else ""
    roof = g.get("roof") or ""
    v = _num(dec.get("viento_mph"))
    aire = al_aire_libre(roof, techo) if est else roof in ("outdoors", "open")
    # #9 (regla registrada): techo «outdoors» en nflverse a la T−85; los retráctiles quedan fuera
    caso = int(roof == "outdoors" and techo != "retractil" and v is not None and v >= UMBRAL_VIENTO)
    # placebo: estadio techado de verdad (domo o retráctil) que nflverse no da como abierto
    placebo = int(techo in ("domo", "retractil") and roof not in ("open", "outdoors") and v is not None
                  and v >= UMBRAL_VIENTO)
    temp, prob = _num(dec.get("temp_c")), _num(dec.get("prob_lluvia"))
    notable = int(aire and bool(dec) and ((v is not None and v >= UMBRAL_VIENTO) or (prob is not None and prob >= UMBRAL_LLUVIA)
                                          or (temp is not None and temp <= UMBRAL_FRIO_C)))
    return dict(game_id=g["game_id"], semana=g["semana"], game_type=g["game_type"], inicio_utc=iso(g["inicio"]),
                visita=g["visita"], local=g["local"], estadio=g["estadio"], techo_tabla=techo, roof_t85=roof,
                techo_coincide=int(techo_coincide(roof, techo)) if est else "", total_t85=g.get("total"),
                fuente_decide=dec.get("fuente", ""), viento_decide=dec.get("viento_mph"), temp_c=dec.get("temp_c"),
                prob_lluvia=dec.get("prob_lluvia"), al_aire_libre=int(aire), caso9=caso, placebo9=placebo,
                notable=notable)


def _fmt(x, dec=0):
    if x is None:
        return "—"
    return f"{x:.{dec}f}".replace(".", ",")


def linea_aviso(c, filas):
    fuente = {"nws": "NWS", "openmeteo": "Open-Meteo"}.get(c["fuente_decide"], "?")
    partes = []
    v, p, t = _num(c["viento_decide"]), _num(c["prob_lluvia"]), _num(c["temp_c"])
    dec = next((f for f in filas if f.get("fuente") and f.get("fuente") == c["fuente_decide"]), {})
    if v is not None:
        partes.append(f"viento {_fmt(v)} mph{(' ' + dec['direccion']) if dec.get('direccion') else ''}")
    if p is not None:
        partes.append(f"lluvia {_fmt(p)} %")
    if t is not None:
        partes.append(f"{_fmt(t)} °C")
    extra = " · #9 en registro (sin dinero)" if c["caso9"] and c["game_type"] == "REG" else (
        " · #9 en registro, playoffs (aparte)" if c["caso9"] else "")
    return f"· {c['visita']} @ {c['local']} ({c['estadio']}): " + ", ".join(partes) + f" — {fuente}{extra}"


def mensaje_telegram(casos, filas_por_juego, inicio):
    notables = [c for c in casos if c["notable"]]
    if not notables:
        return ""
    lin = [f"🌦️ CLIMA T−85 · {fecha_cc(inicio)} (Caracas)"]
    lin += [linea_aviso(c, filas_por_juego.get(c["game_id"], [])) for c in notables]
    lin.append("Solo registro: el cierre ya descuenta el clima (H31). Datos: NWS y Open-Meteo.com (CC BY 4.0).")
    return "\n".join(lin)


# --------------------------------------------------------------------------------------
# Registro (CSV con candado)
# --------------------------------------------------------------------------------------
def _anexar(ruta, campos, filas):
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(str(ruta) + ".lock", "w") as cand:
        fcntl.flock(cand, fcntl.LOCK_EX)
        if ruta.exists():
            with open(ruta, newline="", encoding="utf-8") as fh:
                enc = next(csv.reader(fh), None)
            if enc != campos:
                viejo = ruta.with_name(f"{ruta.stem}_anterior_{int(time.time())}{ruta.suffix}")
                ruta.replace(viejo)
                log(f"{ruta.name} tenía otras columnas: lo guardé como {viejo.name} y empiezo uno nuevo")
        nuevo = not ruta.exists()
        buf = io.StringIO(newline="")
        w = csv.DictWriter(buf, fieldnames=campos)
        if nuevo:
            w.writeheader()
        for f in filas:
            w.writerow({k: ("" if f.get(k) is None else f.get(k)) for k in campos})
        with open(ruta, "a", newline="", encoding="utf-8") as fh:      # una sola escritura: o entra todo o nada
            fh.write(buf.getvalue())
            fh.flush()
            os.fsync(fh.fileno())


def _leer(ruta):
    ruta = Path(ruta)
    if not ruta.exists():
        return []
    with open(ruta, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def primeras_por_juego(filas, clave=("game_id",)):
    """Una fila por juego (y fuente): la de la primera corrida (si un grupo se consultó dos veces, cuenta la primera)."""
    out = {}
    for f in sorted(filas, key=lambda x: x.get("corrida_utc") or ""):
        k = tuple(f.get(c) for c in clave)
        out.setdefault(k, f)
    return list(out.values())


# --------------------------------------------------------------------------------------
# Modo registrar
# --------------------------------------------------------------------------------------
def base_de(g, ahora, corrida):
    """Campos comunes de las filas de un juego (y su estadio). Nunca falla."""
    est, cruce = estadio_de(g)
    base = dict(corrida_utc=corrida, consultado_utc=iso(ahora), version=VERSION_CLIMA, game_id=g["game_id"],
                semana=g["semana"], game_type=g["game_type"], inicio_utc=iso(g["inicio"]),
                minutos_antes=round((g["inicio"] - ahora).total_seconds() / 60), visita=g["visita"], local=g["local"],
                stadium_id=g["stadium_id"], estadio=g["estadio"], cruce=cruce, roof_t85=g["roof"],
                location=g["location"], total_t85=g.get("total"))
    if est is not None:
        base.update(pais=est["pais"], techo_tabla=est["techo"], lat=est["lat"], lon=est["lon"])
    return base, est


def consultar_juego(cli, g, cache, ahora, corrida):
    """Filas del juego (una por fuente) y su estadio. Nunca lanza: cada fuente tiene su propio control de errores."""
    base, est = base_de(g, ahora, corrida)
    if est is None:
        return [dict(base, fuente="", estado="sin coordenadas", detalle="estadio que no está en la tabla")], None
    fuentes = ([("nws", lambda: nws_pronostico(cli, est, g["inicio"], cache))] if est["pais"] == "US" else []) \
        + [("openmeteo", lambda: om_pronostico(cli, est, g["inicio"]))]
    filas = []
    for fuente, fn in fuentes:
        try:
            fila = fn()
        except Exception as e:  # noqa: BLE001  (respuesta con otra forma: se registra, no tumba la tanda)
            fila = {"fuente": fuente, "estado": "error", "detalle": f"respuesta rota ({type(e).__name__})"}
        filas.append(dict(base, **fila))
    return filas, est


def registrar_juegos(juegos, corrida, ahora, cli, cache, ruta_pron=PRONOSTICO, ruta_casos=CASOS, plazo=PLAZO_TOTAL_S + 5):
    """Consulta todos los juegos (hasta HILOS a la vez, en hilos que no retienen el proceso), aplica la regla de #9 y
    guarda. A los 'plazo' segundos guarda lo que haya: los juegos sin respuesta quedan como «error: plazo». → (resumen,
    mensaje)."""
    t0 = time.time()
    resultados, pendientes, candado = {}, list(juegos), threading.Lock()

    def trabajador():
        while True:
            with candado:
                if not pendientes:
                    return
                g = pendientes.pop(0)
            try:
                r = consultar_juego(cli, g, cache, ahora, corrida)
            except Exception as e:  # noqa: BLE001
                b, est = base_de(g, ahora, corrida)
                r = ([dict(b, fuente="", estado="error", detalle=f"{type(e).__name__}: {str(e)[:120]}")], est)
            with candado:
                resultados[g["game_id"]] = r

    hilos = [threading.Thread(target=trabajador, daemon=True) for _ in range(max(1, min(HILOS, len(juegos))))]
    for h in hilos:
        h.start()
    fin = time.monotonic() + plazo
    for h in hilos:
        h.join(max(0.0, fin - time.monotonic()))
    with candado:
        listos = dict(resultados)
        pendientes.clear()                              # lo que no empezó ya no empieza
    filas, casos, por_juego = [], [], {}
    for g in juegos:
        if g["game_id"] in listos:
            fs, est = listos[g["game_id"]]
        else:
            b, est = base_de(g, ahora, corrida)
            fs = [dict(b, fuente="", estado="error", detalle=f"plazo total agotado ({plazo:.0f} s)")]
        g_ = g
        filas += fs
        por_juego[g["game_id"]] = fs
        c = decidir(g_, est, fs)
        c.update(corrida_utc=corrida, version=VERSION_CLIMA)
        casos.append(c)
    _anexar(ruta_pron, CAMPOS_PRON, filas)
    _anexar(ruta_casos, CAMPOS_CASOS, casos)
    inicio = min(g["inicio"] for g in juegos)
    msg = mensaje_telegram(casos, por_juego, inicio)
    res = {"estado": "ok", "juegos": len(juegos), "segundos": round(time.time() - t0, 1),
           "nws_ok": sum(1 for f in filas if f.get("fuente") == "nws" and f.get("estado") == "ok"),
           "nws_total": sum(1 for f in filas if f.get("fuente") == "nws"),
           "om_ok": sum(1 for f in filas if f.get("fuente") == "openmeteo" and f.get("estado") == "ok"),
           "om_total": sum(1 for f in filas if f.get("fuente") == "openmeteo"),
           "sin_coordenadas": sum(1 for f in filas if f.get("estado") == "sin coordenadas"),
           "casos9": sum(c["caso9"] for c in casos if c["game_type"] == "REG"),
           "placebo9": sum(c["placebo9"] for c in casos if c["game_type"] == "REG"),
           "notables": sum(c["notable"] for c in casos), "mensaje": msg, "avisos": _AVISOS[-10:]}
    return res, msg


def modo_registrar(args):
    c = cfg()
    if not c["activo"]:
        print(JSON_MARCA + json.dumps({"estado": "apagado"}, ensure_ascii=False), flush=True)
        return 0
    ahora = t_utc(args.ahora) if args.ahora else dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    ids = [x.strip() for x in (args.juegos or "").split(",") if x.strip()]
    juegos = [g for g in leer_juegos(ids) if g["inicio"] is not None]
    if not juegos:
        print(JSON_MARCA + json.dumps({"estado": "sin juegos", "pedidos": len(ids)}, ensure_ascii=False), flush=True)
        return 0
    cache = cargar_cache()
    cli = Cliente(user_agent(c["contacto"]))
    res, _ = registrar_juegos(juegos, args.corrida or iso(ahora), ahora, cli, cache)
    try:
        guardar_cache(cache)
    except Exception as e:  # noqa: BLE001
        log(f"no pude guardar la caché de NWS ({type(e).__name__})")
    log(f"{res['juegos']} juegos en {res['segundos']} s · NWS {res['nws_ok']}/{res['nws_total']} · "
        f"Open-Meteo {res['om_ok']}/{res['om_total']} · #9 {res['casos9']} · placebo {res['placebo9']} · notables {res['notables']}")
    res["avisos"] = _AVISOS[-10:]
    print(JSON_MARCA + json.dumps(res, ensure_ascii=False), flush=True)
    return 0


# --------------------------------------------------------------------------------------
# Verdad (después del juego), informe y estado — #9 siempre a ciegas: solo conteos
# --------------------------------------------------------------------------------------
def verdad_viento(ids, ruta_pbp=PBP, ruta_games=GAMES):
    """Viento real por juego: texto 'weather' de la jugada por jugada (gamebook); si falta, la columna 'wind' de la
    jugada por jugada; si falta, games.csv. → {game_id: (mph, fuente)}."""
    ids = set(ids)
    out = {}
    if ids and Path(ruta_pbp).exists():
        try:
            import polars as pl
            cols = [c for c in ("game_id", "weather", "wind") if c in pl.read_parquet_schema(ruta_pbp)]
            if "game_id" in cols and len(cols) > 1:
                df = pl.read_parquet(ruta_pbp, columns=cols).filter(pl.col("game_id").is_in(list(ids)))
                for gid, gr in df.group_by("game_id"):
                    gid = gid[0] if isinstance(gid, tuple) else gid
                    w = None
                    if "weather" in cols:
                        for t in gr["weather"].drop_nulls().unique().to_list():
                            w = viento_del_gamebook(t)
                            if w is not None:
                                out[gid] = (w, "gamebook")
                                break
                    if w is None and "wind" in cols:
                        v = [x for x in gr["wind"].drop_nulls().to_list() if _num(x) is not None]
                        if v:
                            out[gid] = (float(v[0]), "pbp wind")
        except Exception as e:  # noqa: BLE001
            log(f"no pude leer el viento de la jugada por jugada ({type(e).__name__})")
    faltan = ids - set(out)
    if faltan and Path(ruta_games).exists():
        with open(ruta_games, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if r.get("game_id") in faltan and _num(r.get("wind")) is not None:
                    out[r["game_id"]] = (float(r["wind"]), "games.csv")
    return out


def precision(filas_pron, verdad):
    """Error del viento pronosticado a la hora del inicio contra el viento real, por fuente (solo descriptivo)."""
    out = {}
    for f in primeras_por_juego(filas_pron, ("game_id", "fuente")):    # la primera consulta de cada juego y fuente
        if f.get("estado") != "ok" or not al_aire_libre(f.get("roof_t85") or "", f.get("techo_tabla") or ""):
            continue                                                       # bajo techo el viento de afuera no aplica
        v, r = _num(f.get("viento_mph")), verdad.get(f.get("game_id"))
        if v is None or r is None:
            continue
        d = out.setdefault(f["fuente"], [])
        d.append(v - r[0])
    return {k: (len(v), sum(abs(x) for x in v) / len(v), sum(v) / len(v)) for k, v in out.items()}


NOMBRE_FUENTE = {"nws": "NWS", "openmeteo": "Open-Meteo"}


def seccion_informe(semana, ruta_pron=PRONOSTICO, ruta_casos=CASOS, verdad=None):
    """Sección «Clima» del informe semanal: consultas, conteos de #9 (a ciegas) y precisión del viento.
    → (línea para Telegram, líneas del informe completo). ('', []) si todavía no hay registros."""
    casos = primeras_por_juego(_leer(ruta_casos))
    pron = _leer(ruta_pron)
    if not casos and not pron:
        return "", []
    cs = [c for c in casos if str(c.get("semana")) == str(semana)]
    ps = [p for p in pron if str(p.get("semana")) == str(semana)]
    ps1 = primeras_por_juego(ps, ("game_id", "fuente"))
    reg = [c for c in casos if c.get("game_type") == "REG"]
    po = [c for c in casos if c.get("game_type") not in ("REG", "")]

    def n(lista, campo):
        return sum(1 for c in lista if str(c.get(campo)) == "1")

    def ok(fuente, lista):
        t = [p for p in lista if p.get("fuente") == fuente]
        return f"{sum(1 for p in t if p.get('estado') == 'ok')}/{len(t)}"

    if verdad is None:
        try:
            verdad = verdad_viento({p["game_id"] for p in pron})
        except Exception:  # noqa: BLE001
            verdad = {}
    pr_sem, pr_acu = precision(ps, verdad), precision(pron, verdad)

    def prec_txt(pr):
        return " · ".join(f"{NOMBRE_FUENTE.get(k, k)} {_fmt(m, 1)} mph (sesgo {'+' if s >= 0 else '−'}{_fmt(abs(s), 1)}, n {c})"
                          for k, (c, m, s) in sorted(pr.items())) or "sin datos todavía"

    cs_reg = [c for c in cs if c.get("game_type") == "REG"]
    tel = (f"Clima (60d): {len(cs)} juegos con pronóstico esta semana (NWS ok {ok('nws', ps1)}, Open-Meteo ok "
           f"{ok('openmeteo', ps1)}) · #9: casos esta semana {n(cs_reg, 'caso9')}, acumulados {n(reg, 'caso9')} "
           f"(placebo {n(reg, 'placebo9')}) · solo conteos hasta el informe final ({INFORME_FINAL}) · "
           f"error medio del viento: {prec_txt(pr_sem)}")
    lin = ["CLIMA (60d y #9): pronóstico a T−85, descriptivo (registro 60)",
           f"  Semana {semana}: {len(cs)} juegos · consultas NWS ok {ok('nws', ps1)}, Open-Meteo ok {ok('openmeteo', ps1)}"
           f" · avisos en Telegram {n(cs, 'notable')} · techo de nflverse distinto del real en {sum(1 for c in cs if str(c.get('techo_coincide')) == '0')}",
           f"  #9 (registro sin potencia, a ciegas): casos esta semana {n(cs_reg, 'caso9')}, placebo {n(cs_reg, 'placebo9')} · "
           f"acumulado de temporada regular: casos {n(reg, 'caso9')}, placebo {n(reg, 'placebo9')}"
           + (f" · playoffs (aparte) {n(po, 'caso9')}" if po else "")
           + f" · informe final {INFORME_FINAL} (sin tasa ni residuo hasta entonces)",
           f"  Error del viento a la hora del inicio contra el gamebook — semana: {prec_txt(pr_sem)} · acumulado: {prec_txt(pr_acu)}",
           "  Datos del tiempo: National Weather Service y Open-Meteo.com (CC BY 4.0)."]
    return tel, lin


def texto_estado():
    c = cfg()
    casos = primeras_por_juego(_leer(CASOS))
    pron = _leer(PRONOSTICO)
    if not c["activo"]:
        return "Clima (60d): apagado en semana.ini [clima]"
    if not casos:
        return f"Clima (60d): activo ({VERSION_CLIMA}) · todavía sin consultas (empieza en la próxima T−85 automática)"
    reg = [x for x in casos if x.get("game_type") == "REG"]
    ok = lambda fu: (f"{sum(1 for p in pron if p.get('fuente') == fu and p.get('estado') == 'ok')}/"  # noqa: E731
                     f"{sum(1 for p in pron if p.get('fuente') == fu)}")
    ult = max((x.get("corrida_utc") or "") for x in casos)
    return (f"Clima (60d): activo ({VERSION_CLIMA}) · {len(casos)} juegos registrados · consultas NWS ok {ok('nws')}, "
            f"Open-Meteo ok {ok('openmeteo')} · última {fecha_cc(t_utc(ult)) if t_utc(ult) else ult} · #9: "
            f"casos {sum(1 for x in reg if x.get('caso9') == '1')}, placebo {sum(1 for x in reg if x.get('placebo9') == '1')} "
            f"(a ciegas; informe final {INFORME_FINAL})")


# --------------------------------------------------------------------------------------
# Modo coordenadas (revisión de la tabla) y prueba real
# --------------------------------------------------------------------------------------
def modo_coordenadas(args):
    c = cfg()
    cache = cargar_cache()
    cli = Cliente(user_agent(c["contacto"]), plazo_total=600)
    mal = 0
    print(f"{VERSION_CLIMA} · revisión de la tabla de estadios ({len(ESTADIOS)})")
    for e in [dict(zip(CAMPOS_EST, x)) for x in ESTADIOS]:
        if e["pais"] == "US":
            p, info = nws_punto(cli, e, cache)
            if p is None:
                mal += 1
                print(f"  REVISAR {e['stadium_id']} {e['nombre']}: NWS no respondió ({info['error']})")
                continue
            okc = p["ciudad"] == e["ciudad"] or (p["ciudad"].split(", ")[-1] == e["ciudad"].split(", ")[-1]
                                                  and (p.get("distancia_km") or 99) < 8)
            mal += not okc
            print(f"  {'ok' if okc else 'REVISAR'} {e['stadium_id']} {e['nombre']}: NWS {p['ciudad']} a "
                  f"{_fmt(p.get('distancia_km'), 1)} km · rejilla {p['rejilla']} (esperado {e['ciudad']})")
        else:
            d, info = cli.json(URL_OM, params={"latitude": f"{e['lat']:.4f}", "longitude": f"{e['lon']:.4f}",
                                               "hourly": "temperature_2m", "forecast_days": "1"}, accept="application/json")
            if d is None:
                mal += 1
                print(f"  REVISAR {e['stadium_id']} {e['nombre']}: Open-Meteo no respondió ({info['error']})")
            else:
                print(f"  ok {e['stadium_id']} {e['nombre']} ({e['ciudad']}): Open-Meteo responde, altura {d.get('elevation')} m")
    guardar_cache(cache)
    juegos = leer_juegos()
    sin = sorted({(g["stadium_id"], g["estadio"], g["location"]) for g in juegos if estadio_de(g)[0] is None})
    por_id = sorted({(g["stadium_id"], g["estadio"]) for g in juegos if estadio_de(g)[1] == "id"})
    print(f"Calendario {TEMPORADA}: {len(juegos)} juegos · sin estadio en la tabla: {len(sin)}"
          + ("".join(f"\n  SIN CRUCE {s[0]} «{s[1]}» ({s[2]})" for s in sin))
          + (f" · cruzados por id (nombre nuevo): {por_id}" if por_id else ""))
    print(f"RESULTADO: {'OK' if mal == 0 and not sin else 'REVISAR'} · {mal} estadios por revisar")
    return 0 if mal == 0 and not sin else 1


def modo_prueba_real(args):
    """1 consulta real por fuente: el próximo juego en un estadio de EE. UU. al aire libre y un estadio de fuera
    (Wembley, a mañana a la misma hora). No escribe en el registro."""
    c = cfg()
    ahora = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    cache = cargar_cache()
    cli = Cliente(user_agent(c["contacto"]), plazo_total=60)
    juegos = [g for g in leer_juegos() if g["inicio"] and ahora < g["inicio"] < ahora + dt.timedelta(days=6)]
    us = next((g for g in sorted(juegos, key=lambda x: x["inicio"])
               if (estadio_de(g)[0] or {}).get("pais") == "US" and g["roof"] == "outdoors"), None)
    if us is None:
        us = dict(game_id="prueba", semana=0, game_type="REG", inicio=ahora + dt.timedelta(hours=24), visita="—",
                  local="BUF", stadium_id="BUF00", estadio="Highmark Stadium", roof="outdoors", location="Home", total=None)
    fuera = dict(game_id="prueba-fuera", semana=0, game_type="REG", inicio=(ahora + dt.timedelta(hours=24)).replace(minute=0),
                 visita="—", local="—", stadium_id="LON00", estadio="Wembley Stadium", roof="outdoors", location="Neutral",
                 total=None)
    print(f"{VERSION_CLIMA} · prueba real (no escribe en el registro) · User-Agent: {user_agent(c['contacto'])}")
    ok_total = True
    for g in (us, fuera):
        filas, est = consultar_juego(cli, g, cache, ahora, iso(ahora))
        print(f"\n{g['visita']} @ {g['local']} · {g['estadio']} · inicio {fecha_cc(g['inicio'])} Caracas · techo nflverse "
              f"«{g['roof'] or 'vacío'}», tabla «{(est or {}).get('techo', '?')}»")
        for f in filas:
            ok_total &= f.get("estado") == "ok"
            print(f"  {NOMBRE_FUENTE.get(f.get('fuente'), f.get('fuente'))}: {f.get('estado')} (http {f.get('http')}, "
                  f"{_fmt(_num(f.get('latencia_s')), 1)} s) · hora {f.get('hora_pronostico_utc', '—')} · {_fmt(_num(f.get('temp_c')), 1)} °C · "
                  f"viento {_fmt(_num(f.get('viento_mph')), 1)} mph {f.get('direccion', '')} "
                  f"(«{f.get('viento_texto', '')}») · ráfaga {_fmt(_num(f.get('rafaga_mph')), 1)} · lluvia "
                  f"{_fmt(_num(f.get('prob_lluvia')))} % · 3 h: viento {_fmt(_num(f.get('viento_mph_3h')), 1)} mph"
                  + (f" · NWS actualizado {f.get('nws_actualizado')}" if f.get("nws_actualizado") else "")
                  + (f" · {f.get('detalle')}" if f.get("detalle") else ""))
        cs = decidir(g, est, filas)
        print(f"  decide {cs['fuente_decide'] or '—'} · caso #9 {cs['caso9']} · placebo {cs['placebo9']} · aviso {cs['notable']}")
    guardar_cache(cache)
    print(f"\nRESULTADO: {'OK' if ok_total else 'REVISAR'}")
    return 0 if ok_total else 1


# --------------------------------------------------------------------------------------
# Modo prueba (sin red)
# --------------------------------------------------------------------------------------
def _nws_hourly_falso(inicio, viento="16 mph", prob=70, temp_f=46, horas=8):
    t0 = (inicio - dt.timedelta(hours=2)).astimezone(NUEVA_YORK).replace(minute=0, second=0, microsecond=0)
    periodos = []
    for k in range(horas):
        a = t0 + dt.timedelta(hours=k)
        periodos.append({"number": k + 1, "startTime": a.isoformat(), "endTime": (a + dt.timedelta(hours=1)).isoformat(),
                         "temperature": temp_f, "temperatureUnit": "F",
                         "probabilityOfPrecipitation": {"unitCode": "wmoUnit:percent", "value": prob},
                         "windSpeed": viento if k == 2 else "10 to 15 mph", "windDirection": "NW",
                         "shortForecast": "Rain Showers"})
    return {"properties": {"updateTime": "2026-11-01T12:00:00+00:00", "periods": periodos}}


def _om_falso(inicio, viento=9.5, horas=48, por_hora=False):
    t0 = (inicio - dt.timedelta(hours=10)).replace(minute=0, second=0, microsecond=0)
    ts = [(t0 + dt.timedelta(hours=k)).strftime("%Y-%m-%dT%H:%M") for k in range(horas)]
    if por_hora:                                    # cada variable vale su número de hora: se ve qué marca se leyó
        return {"elevation": 180.0, "hourly": {"time": ts, "temperature_2m": [float(k) for k in range(horas)],
                                               "precipitation_probability": list(range(horas)),
                                               "precipitation": [k / 10 for k in range(horas)], "snowfall": [0.0] * horas,
                                               "wind_speed_10m": [float(k) for k in range(horas)],
                                               "wind_direction_10m": [315] * horas,
                                               "wind_gusts_10m": [k + 0.5 for k in range(horas)]}}
    return {"elevation": 180.0, "hourly": {"time": ts, "temperature_2m": [4.0] * horas,
                                           "precipitation_probability": [20] * horas, "precipitation": [0.1] * horas,
                                           "snowfall": [0.0] * horas, "wind_speed_10m": [viento] * horas,
                                           "wind_direction_10m": [315] * horas, "wind_gusts_10m": [22.0] * horas}}


class _ApiFalsa:
    """Simula NWS y Open-Meteo. modo por host: 'ok', '403', '500-una-vez', '500', 'rota', 'red', 'lenta'."""

    def __init__(self, inicio, nws="ok", om="ok", viento_nws="16 mph", viento_om=9.5, om_por_hora=False, lento=None):
        self.inicio, self.nws, self.om, self.v_nws, self.v_om = inicio, nws, om, viento_nws, viento_om
        self.om_por_hora, self.lento = om_por_hora, lento        # lento: (texto en la URL, segundos de espera)
        self.llamadas, self.ua = [], []
        self._500 = set()

    def __call__(self, url, params=None, headers=None, timeout=10):
        self.llamadas.append(url)
        self.ua.append((headers or {}).get("User-Agent"))
        modo = self.nws if "weather.gov" in url else self.om
        if not (headers or {}).get("User-Agent"):
            return 403, "{}"
        if modo == "403":
            return 403, '{"title": "Forbidden"}'
        if modo == "500":
            return 500, "{}"
        if modo == "500-una-vez" and url not in self._500:
            self._500.add(url)
            return 500, "{}"
        if modo == "rota":
            return 200, "<html>no es json"
        if modo == "red":
            raise ConnectionError("sin red")
        if self.lento and self.lento[0] in url + json.dumps(params or {}):
            time.sleep(self.lento[1])
        if modo == "lista" and "/points/" in url:
            return 200, "[]"
        if modo == "periodos-nulos" and "/points/" not in url and "weather.gov" in url:
            return 200, json.dumps({"properties": {"periods": [None]}})
        if modo == "horas-raras":
            return 200, json.dumps({"hourly": {"time": [1, 2], "wind_speed_10m": [3, 4]}})
        if "/points/" in url:
            return 200, json.dumps({"properties": {"forecastHourly": "https://api.weather.gov/gridpoints/XXX/1,1/forecast/hourly",
                                                   "gridId": "XXX", "gridX": 1, "gridY": 1,
                                                   "relativeLocation": {"properties": {"city": "Seattle", "state": "WA",
                                                                                       "distance": {"value": 120.0}}}}})
        if "weather.gov" in url:
            return 200, json.dumps(_nws_hourly_falso(self.inicio, self.v_nws))
        return 200, json.dumps(_om_falso(self.inicio, self.v_om, por_hora=self.om_por_hora))


def _juego_prueba(gid, estadio, sid, roof, inicio, location="Home", game_type="REG", total=41.5):
    return dict(game_id=gid, semana=9, game_type=game_type, inicio=inicio, visita="AAA", local="BBB", stadium_id=sid,
                estadio=estadio, roof=roof, location=location, total=total)


def modo_prueba(args):
    if args.real:
        return modo_prueba_real(args)
    pruebas = []

    def chk(nombre, cond, detalle=""):
        pruebas.append((nombre, bool(cond), detalle))

    inicio = dt.datetime(2026, 11, 3, 1, 15, tzinfo=dt.timezone.utc)      # lun 02-nov 20:15 ET (CHI @ SEA)
    ahora = inicio - dt.timedelta(minutes=85)
    # lectura de textos
    chk("viento «15 mph» → 15", viento_de_texto("15 mph") == 15.0)
    chk("viento «10 to 15 mph» → 12,5", viento_de_texto("10 to 15 mph") == 12.5)
    chk("viento «Calm» → 0", viento_de_texto("Calm") == 0.0)
    chk("gamebook «Wind: NW 13 mph» → 13", viento_del_gamebook("Cloudy Temp: 47° F, Humidity: 70%, Wind: NW 13 mph") == 13.0)
    chk("gamebook «Wind: Calm» → 0", viento_del_gamebook("Clear, Wind: Calm") == 0.0)
    chk("gamebook sin viento → nada", viento_del_gamebook("N/A (Indoors)") is None)
    chk("gamebook «Windy … Wind: W 20 mph» → 20", viento_del_gamebook("Windy Temp: 40° F, Humidity: 50%, Wind: W 20 mph") == 20.0)
    chk("gamebook con «Wind Chill: 14° F» → 12 (el viento, no la sensación)",
        viento_del_gamebook("Temp: 25° F (Wind Chill: 14° F), Humidity: 60%, Wind: NW 12 mph") == 12.0)
    chk("gamebook «Wind: 0-5 mph» → 2,5", viento_del_gamebook("Clear Temp: 50° F, Wind: 0-5 mph") == 2.5)
    chk("gamebook «Wind: 0 mph» → 0", viento_del_gamebook("Temp: 50° F, Wind: 0 mph") == 0.0)
    chk("32 °F → 0 °C", abs(f_a_c(32) - 0.0) < 1e-9)
    chk("rumbo 315° → NW", rumbo(315) == "NW")
    chk("inicio ET → UTC con cambio de hora", inicio_utc("2026-11-02", "20:15") == inicio)
    # cruce de estadios
    e, cr = estadio_de({"estadio": "Tottenham Hotspur Stadium", "stadium_id": "JAX00", "location": "Neutral"})
    chk("Tottenham con id de JAX → cruza por nombre (Londres)", e and e["stadium_id"] == "LON02" and cr == "nombre")
    e, cr = estadio_de({"estadio": "Estadio Nuevo", "stadium_id": "JAX00", "location": "Neutral"})
    chk("nombre desconocido fuera de casa → sin cruce", e is None and cr == "sin cruce")
    e, cr = estadio_de({"estadio": "EverBank Field 2027", "stadium_id": "JAX00", "location": "Home"})
    chk("nombre nuevo de local → cruza por id", e and e["stadium_id"] == "JAX00" and cr == "id")
    chk("tabla sin ids repetidos", len(POR_ID) == len(ESTADIOS) and len(POR_NOMBRE) == len(ESTADIOS))
    with tempfile.TemporaryDirectory() as tmp:
        rp, rc = Path(tmp) / "p.csv", Path(tmp) / "c.csv"
        # 1) caso normal: SEA al aire libre, NWS 16 mph → caso #9 y aviso; domo con 16 mph → placebo
        api = _ApiFalsa(inicio)
        cli = Cliente(user_agent(), get=api, dormir=lambda s: None)
        cache = {}
        juegos = [_juego_prueba("2026_08_CHI_SEA", "Lumen Field", "SEA00", "outdoors", inicio),
                  _juego_prueba("2026_08_X_DET", "Ford Field", "DET00", "dome", inicio),
                  _juego_prueba("2026_08_X_LON", "Wembley Stadium", "LON00", "outdoors", inicio, "Neutral"),
                  _juego_prueba("2026_08_X_NUEVO", "Estadio Desconocido", "ZZZ00", "outdoors", inicio, "Neutral")]
        res, msg = registrar_juegos(juegos, iso(ahora), ahora, cli, cache, rp, rc)
        casos = {c["game_id"]: c for c in _leer(rc)}
        pron = _leer(rp)
        sea = [p for p in pron if p["game_id"] == "2026_08_CHI_SEA"]
        nws = next(p for p in sea if p["fuente"] == "nws")
        chk("SEA: NWS ok en la hora del inicio", nws["estado"] == "ok" and nws["viento_mph"] == "16.0", nws)
        chk("SEA: 46 °F → 7,8 °C y lluvia 70 %", nws["temp_c"] == "7.8" and nws["prob_lluvia"] == "70")
        chk("SEA: ventana de 3 h promedia (16 + 12,5 + 12,5 + 12,5)/4", nws["viento_mph_3h"] == "13.4", nws["viento_mph_3h"])
        chk("SEA: Open-Meteo también consultado", any(p["fuente"] == "openmeteo" and p["estado"] == "ok" for p in sea))
        chk("SEA: decide NWS, caso #9 y aviso", casos["2026_08_CHI_SEA"]["fuente_decide"] == "nws"
            and casos["2026_08_CHI_SEA"]["caso9"] == "1" and casos["2026_08_CHI_SEA"]["notable"] == "1")
        chk("DET (domo) con 16 mph → placebo, no caso, sin aviso", casos["2026_08_X_DET"]["placebo9"] == "1"
            and casos["2026_08_X_DET"]["caso9"] == "0" and casos["2026_08_X_DET"]["notable"] == "0")
        lon = [p for p in pron if p["game_id"] == "2026_08_X_LON"]
        chk("Wembley: solo Open-Meteo (fuera de EE. UU.)", [p["fuente"] for p in lon] == ["openmeteo"])
        chk("Wembley: 9,5 mph y 4 °C → sin caso; aviso por frío no (4 > 0)", casos["2026_08_X_LON"]["caso9"] == "0"
            and casos["2026_08_X_LON"]["notable"] == "0")
        chk("estadio desconocido → «sin coordenadas», sin consultas", any(p["game_id"] == "2026_08_X_NUEVO" and p["estado"] == "sin coordenadas" for p in pron)
            and not any("ZZZ" in u for u in api.llamadas))
        chk("User-Agent siempre presente", all(api.ua))
        chk("caché de NWS guardada por estadio", any(k.startswith("SEA00|") for k in cache) and any(k.startswith("DET00|") for k in cache))
        chk("mensaje de Telegram solo con SEA y la marca de #9", "CHI" not in msg.split("\n")[0] and "AAA @ BBB (Lumen Field)" in msg
            and "#9 en registro (sin dinero)" in msg and "Ford Field" not in msg and "Wembley" not in msg, msg)
        chk("resumen: 1 caso, 1 placebo, 1 aviso", res["casos9"] == 1 and res["placebo9"] == 1 and res["notables"] == 1, res)
        # 2) segunda corrida del mismo grupo: no cuenta dos veces
        registrar_juegos(juegos[:1], iso(ahora + dt.timedelta(minutes=5)), ahora, cli, cache, rp, rc)
        tel, lin = seccion_informe(9, rp, rc, verdad={"2026_08_CHI_SEA": (13.0, "gamebook")})
        chk("informe: 1 caso, 1 placebo (la repetición no cuenta)", "#9: casos esta semana 1, acumulados 1 (placebo 1)" in tel, tel)
        chk("informe: error del viento NWS 3 mph (16 contra 13)", "NWS 3,0 mph (sesgo +3,0, n 1)" in tel, tel)
        chk("informe a ciegas: no menciona unders ni resultados", "under" not in (tel + " ".join(lin)).lower()
            and "residuo" not in tel.lower())
        # 3) NWS cae (500 dos veces) → decide Open-Meteo; 9,5 mph → sin caso
        rp2, rc2 = Path(tmp) / "p2.csv", Path(tmp) / "c2.csv"
        api2 = _ApiFalsa(inicio, nws="500")
        r2, _ = registrar_juegos(juegos[:1], iso(ahora), ahora, Cliente(user_agent(), get=api2, dormir=lambda s: None), {}, rp2, rc2)
        c2 = _leer(rc2)[0]
        chk("NWS 500 → reintenta una vez y decide Open-Meteo", c2["fuente_decide"] == "openmeteo" and c2["caso9"] == "0"
            and sum(1 for u in api2.llamadas if "/points/" in u) == 2, api2.llamadas)
        # 4) NWS 500 una vez → el reintento funciona
        api3 = _ApiFalsa(inicio, nws="500-una-vez")
        r3, _ = registrar_juegos(juegos[:1], iso(ahora), ahora, Cliente(user_agent(), get=api3, dormir=lambda s: None), {},
                                 Path(tmp) / "p3.csv", Path(tmp) / "c3.csv")
        chk("NWS 500 una vez → el reintento responde", r3["nws_ok"] == 1, r3)
        # 5) 403, respuesta rota y sin red → error registrado, nunca excepción
        for modo in ("403", "rota", "red"):
            api4 = _ApiFalsa(inicio, nws=modo, om=modo)
            r4, m4 = registrar_juegos(juegos[:1], iso(ahora), ahora, Cliente(user_agent(), get=api4, dormir=lambda s: None),
                                      {}, Path(tmp) / f"p_{modo}.csv", Path(tmp) / f"c_{modo}.csv")
            c4 = _leer(Path(tmp) / f"c_{modo}.csv")[0]
            chk(f"ambas fuentes «{modo}» → sin decisión, sin caso, sin aviso", r4["nws_ok"] == 0 and r4["om_ok"] == 0
                and c4["fuente_decide"] == "" and c4["caso9"] == "0" and m4 == "", r4)
        # 6) plazo total vencido → no consulta
        reloj = iter([0.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0])
        cli6 = Cliente(user_agent(), get=_ApiFalsa(inicio), plazo_total=90, dormir=lambda s: None, reloj=lambda: next(reloj, 100.0))
        d6, i6 = cli6.json("https://api.weather.gov/points/1,1")
        chk("plazo total vencido → «plazo», sin consulta", d6 is None and i6["error"] == "plazo")
        # 7) rango «10 to 15» en NWS no llega a 15 → sin caso; 15 exacto sí
        for txt, esperado in (("10 to 15 mph", "0"), ("15 mph", "1")):
            api7 = _ApiFalsa(inicio, viento_nws=txt)
            rc7 = Path(tmp) / f"c7_{esperado}.csv"
            registrar_juegos(juegos[:1], iso(ahora), ahora, Cliente(user_agent(), get=api7, dormir=lambda s: None), {},
                             Path(tmp) / f"p7_{esperado}.csv", rc7)
            chk(f"NWS «{txt}» → caso #9 = {esperado}", _leer(rc7)[0]["caso9"] == esperado)
        # 8) retráctil con techo vacío (antes del juego) y 20 mph → placebo; playoffs al aire libre → caso aparte
        api8 = _ApiFalsa(inicio, viento_nws="20 mph")
        rc8 = Path(tmp) / "c8.csv"
        registrar_juegos([_juego_prueba("2026_08_X_IND", "Lucas Oil Stadium", "IND00", "", inicio),
                          _juego_prueba("2026_20_X_BUF", "Highmark Stadium", "BUF00", "outdoors", inicio, game_type="DIV")],
                         iso(ahora), ahora, Cliente(user_agent(), get=api8, dormir=lambda s: None), {}, Path(tmp) / "p8.csv", rc8)
        c8 = {c["game_id"]: c for c in _leer(rc8)}
        chk("retráctil sin techo publicado → placebo", c8["2026_08_X_IND"]["placebo9"] == "1" and c8["2026_08_X_IND"]["caso9"] == "0")
        chk("playoffs con 20 mph → caso registrado aparte", c8["2026_20_X_BUF"]["caso9"] == "1"
            and c8["2026_20_X_BUF"]["game_type"] == "DIV")
        tel8, lin8 = seccion_informe(20, Path(tmp) / "p8.csv", rc8, verdad={})
        chk("informe: los playoffs no suman al acumulado de temporada regular", "acumulado de temporada regular: casos 0" in " ".join(lin8)
            and "playoffs (aparte) 1" in " ".join(lin8), lin8)
        # 10) respuestas mal formadas: nunca tumban la tanda; la otra fuente del juego se conserva
        for modo_nws, modo_om, nombre in (("periodos-nulos", "ok", "NWS con períodos nulos"), ("lista", "ok", "NWS /points como lista"),
                                          ("ok", "horas-raras", "Open-Meteo con horas que no son fechas")):
            api10 = _ApiFalsa(inicio, nws=modo_nws, om=modo_om)
            rp10, rc10 = Path(tmp) / f"p10_{modo_nws}{modo_om}.csv", Path(tmp) / f"c10_{modo_nws}{modo_om}.csv"
            r10, _ = registrar_juegos(juegos[:2], iso(ahora), ahora, Cliente(user_agent(), get=api10, dormir=lambda s: None), {},
                                      rp10, rc10)
            p10 = _leer(rp10)
            mala = "nws" if modo_nws != "ok" else "openmeteo"
            buena = "openmeteo" if mala == "nws" else "nws"
            chk(f"{nombre} → se guardan los 2 juegos, la fuente rota como error y la otra bien",
                len(_leer(rc10)) == 2 and all(p["estado"] == "error" for p in p10 if p["fuente"] == mala)
                and all(p["estado"] == "ok" for p in p10 if p["fuente"] == buena), [(p["game_id"], p["fuente"], p["estado"], p["detalle"]) for p in p10])
        # 11) Open-Meteo: lo instantáneo en la marca del inicio; lluvia, probabilidad y ráfaga en la marca siguiente
        api11 = _ApiFalsa(inicio, om_por_hora=True)
        rp11 = Path(tmp) / "p11.csv"
        registrar_juegos([juegos[2]], iso(ahora), ahora, Cliente(user_agent(), get=api11, dormir=lambda s: None), {}, rp11,
                         Path(tmp) / "c11.csv")
        o = _leer(rp11)[0]
        chk("Open-Meteo: viento y temperatura de la marca 01:00Z (hora 10)", o["viento_mph"] == "10.0" and o["temp_c"] == "10.0", o)
        chk("Open-Meteo: lluvia, probabilidad y ráfaga de la hora 01-02Z (marca 02:00, hora 11)",
            o["prob_lluvia"] == "11" and o["rafaga_mph"] == "11.5" and o["lluvia_mm"] == "1.1", o)
        chk("Open-Meteo: ventana 01:15-04:15Z → instantáneas 01-04Z (media 11,5), anteriores 02-05Z (máx 14, suma 5,0)",
            o["viento_mph_3h"] == "11.5" and o["prob_lluvia_3h"] == "14" and o["lluvia_mm_3h"] == "5.0", o)
        # 12) tope duro: un estadio que no responde no frena a los demás; queda como «plazo»
        api12 = _ApiFalsa(inicio, lento=("47.5952", 6))
        t12 = time.time()
        rp12, rc12 = Path(tmp) / "p12.csv", Path(tmp) / "c12.csv"
        r12, _ = registrar_juegos(juegos[:3], iso(ahora), ahora, Cliente(user_agent(), get=api12, dormir=lambda s: None), {},
                                  rp12, rc12, plazo=2)
        p12 = _leer(rp12)
        chk("tope duro: termina a los ~2 s aunque SEA tarde 6 s", time.time() - t12 < 4, round(time.time() - t12, 1))
        chk("tope duro: SEA queda como «plazo» y los otros 2 se guardan bien",
            any(p["game_id"] == "2026_08_CHI_SEA" and "plazo" in p["detalle"] for p in p12)
            and sum(1 for p in p12 if p["estado"] == "ok") >= 2 and len(_leer(rc12)) == 3, [(p["game_id"], p["estado"], p["detalle"]) for p in p12])
        # 13) definiciones de techo: retráctil marcado «outdoors» no es caso; retráctil abierto y estadio abierto que
        # nflverse marca «dome» sí avisan (descriptivo)
        api13 = _ApiFalsa(inicio, viento_nws="20 mph", viento_om=20.0)
        rc13 = Path(tmp) / "c13.csv"
        registrar_juegos([_juego_prueba("2026_08_X_ATL", "Mercedes-Benz Stadium", "ATL97", "outdoors", inicio),
                          _juego_prueba("2026_08_X_DAL", "AT&T Stadium", "DAL00", "open", inicio),
                          _juego_prueba("2026_08_X_MUN", "FC Bayern Munich Stadium", "MUN01", "dome", inicio, "Neutral")],
                         iso(ahora), ahora, Cliente(user_agent(), get=api13, dormir=lambda s: None), {}, Path(tmp) / "p13.csv", rc13)
        c13 = {c["game_id"]: c for c in _leer(rc13)}
        chk("retráctil marcado «outdoors» → no es caso #9 (la regla deja fuera los retráctiles)", c13["2026_08_X_ATL"]["caso9"] == "0")
        chk("retráctil abierto con 20 mph → avisa, no es caso ni placebo", c13["2026_08_X_DAL"]["notable"] == "1"
            and c13["2026_08_X_DAL"]["caso9"] == "0" and c13["2026_08_X_DAL"]["placebo9"] == "0")
        chk("Allianz (nflverse «dome», cancha abierta) con 20 mph → avisa, no es caso ni placebo", c13["2026_08_X_MUN"]["notable"] == "1"
            and c13["2026_08_X_MUN"]["caso9"] == "0" and c13["2026_08_X_MUN"]["placebo9"] == "0")
        # 14) la precisión no compara pronósticos de juegos bajo techo
        pr = precision(_leer(rp), {"2026_08_X_DET": (0.0, "gamebook"), "2026_08_CHI_SEA": (13.0, "gamebook")})
        chk("precisión: el domo no entra (solo SEA, n 1 por fuente)", pr.get("nws", (0,))[0] == 1, pr)
        # 9) archivo con columnas viejas → se aparta y empieza uno nuevo
        rv = Path(tmp) / "viejo.csv"
        rv.write_text("a,b\n1,2\n", encoding="utf-8")
        _anexar(rv, CAMPOS_CASOS, [{"game_id": "x"}])
        chk("registro con otras columnas → se aparta sin borrar", rv.exists() and any(p.name.startswith("viejo_anterior_") for p in Path(tmp).iterdir()))
    malas = [p for p in pruebas if not p[1]]
    for nombre, ok, det in pruebas:
        print(f"  {'✅' if ok else '❌'} {nombre}" + ("" if ok else f" · {str(det)[:300]}"))
    print(f"{VERSION_CLIMA} · PRUEBA {'OK' if not malas else 'CON FALLAS'}: {len(pruebas) - len(malas)} de {len(pruebas)}")
    return 0 if not malas else 1


# --------------------------------------------------------------------------------------
# Principal
# --------------------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description="Pronóstico del clima a T−85 (60d) y registro de #9 (60c)")
    ap.add_argument("modo", choices=["registrar", "prueba", "coordenadas", "estado", "informe"])
    ap.add_argument("--corrida")
    ap.add_argument("--juegos")
    ap.add_argument("--ahora")
    ap.add_argument("--semana", type=int)
    ap.add_argument("--real", action="store_true")
    args = ap.parse_args(argv)
    try:
        if os.nice(0) < 10:
            os.nice(10 - os.nice(0))
    except OSError:
        pass
    if args.modo == "registrar":
        return modo_registrar(args)
    if args.modo == "prueba":
        return modo_prueba(args)
    if args.modo == "coordenadas":
        return modo_coordenadas(args)
    if args.modo == "estado":
        print(texto_estado())
        return 0
    if args.modo == "informe":
        if args.semana is None:
            print("Falta --semana N")
            return 1
        tel, lin = seccion_informe(args.semana)
        print(tel or "Clima (60d): todavía sin registros.")
        print("\n".join(lin))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
