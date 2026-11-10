#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
diag_gemini.py — Diagnóstico de P2 del piloto de 35A (2-oct-2026). Solo lectura del motor; no vota ni toca el cupo.

Hace DOS consultas a Gemini sobre el primer juego pendiente de la semana (o el que se indique con --juego):
  1. g1        (con esquema: responseFormat APPLICATION_JSON)
  2. g1-texto  (sin esquema)
con exactamente el mismo cuerpo que arma semana.py v6.1, y guarda la respuesta COMPLETA de Google en
salidas/semana/diag_gemini_<variante>.json (la respuesta no contiene la llave). Muestra dónde vienen (si vienen) los
datos de la búsqueda: groundingMetadata, webSearchQueries, groundingChunks, searchEntryPoint, y el uso de tokens.
Costo: ~USD 0,01 en total. No cuenta para el cupo del piloto ni deja votos.

Uso:  cd ~/nfl_sim && venv/bin/python diag_gemini.py [--juego 2026_04_IND_WAS]
"""
import argparse
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
import semana as s  # noqa: E402  (mismo cuerpo y mismo lector que la corrida real)

VERSION = "diag_gemini-v1 (2-oct-2026)"


def rutas(obj, prefijo="", out=None):
    """Lista de rutas de claves de la respuesta (sin valores largos), para ver la estructura."""
    out = [] if out is None else out
    if isinstance(obj, dict):
        for k, v in obj.items():
            rutas(v, f"{prefijo}.{k}" if prefijo else k, out)
    elif isinstance(obj, list):
        out.append(f"{prefijo}[{len(obj)}]")
        for v in obj[:1]:
            rutas(v, prefijo + "[0]", out)
    else:
        out.append(prefijo)
    return out


def buscar(obj, clave, ruta="", out=None):
    """Todas las apariciones de una clave en cualquier nivel de la respuesta: [(ruta, valor)]."""
    out = [] if out is None else out
    if isinstance(obj, dict):
        for k, v in obj.items():
            r = f"{ruta}.{k}" if ruta else k
            if k == clave:
                out.append((r, v))
            buscar(v, clave, r, out)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            buscar(v, clave, f"{ruta}[{i}]", out)
    return out


def main():
    import polars as pl
    import requests
    ap = argparse.ArgumentParser()
    ap.add_argument("--juego")
    args = ap.parse_args()
    if not s.GEMINI_LLAVE.exists():
        print("No hay llave de Gemini (credenciales/gemini.key).")
        return
    url_base = os.environ.get("DIAG_GEMINI_URL", s.GEMINI_URL)       # solo para pruebas con una API simulada
    ahora = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    _, g26 = s.calendario(1.0)
    if args.juego:
        jg = g26.filter(pl.col("game_id") == args.juego)
    else:
        sem = s.semana_actual(g26, ahora)
        jg = g26.filter((pl.col("week") == sem) & (pl.col("inicio") > ahora)).sort(["inicio", "game_id"]).head(1)
    if jg.height == 0:
        print("No encontré el juego.")
        return
    r0 = jg.row(0, named=True)
    j = dict(game_id=r0["game_id"], semana=int(r0["week"]), game_type=r0["game_type"], visita=r0["away_team"],
             local=r0["home_team"], inicio=r0["inicio"])
    print(f"{VERSION} · {s.VERSION_SEMANA} · juego {j['visita']} @ {j['local']} ({j['game_id']}) · 2 consultas")
    llave = s.GEMINI_LLAVE.read_text(encoding="utf-8").strip()
    s.SAL.mkdir(parents=True, exist_ok=True)
    for variante in ("g1", "g1-texto"):
        cuerpo = s.gemini_cuerpo(j, ahora, variante)
        t0 = time.time()
        try:
            r = requests.post(f"{url_base}/models/{s.GEMINI_MODELO}:generateContent",
                              headers={"x-goog-api-key": llave, "Content-Type": "application/json"}, json=cuerpo, timeout=90)
        except Exception as e:  # noqa: BLE001 — solo el tipo
            print(f"\n== {variante}: error de red ({type(e).__name__})")
            continue
        lat = time.time() - t0
        try:
            datos = r.json()
        except ValueError:
            datos = {"_texto_no_json": r.text[:2000]}
        destino = s.SAL / f"diag_gemini_{variante}.json"
        destino.write_text(json.dumps({"http": r.status_code, "latencia_s": round(lat, 2), "huella": s.gemini_huella(variante),
                                       "respuesta": datos}, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n== {variante} (huella {s.gemini_huella(variante)}): HTTP {r.status_code} en {lat:.1f} s · guardado en {destino.name}")
        if r.status_code != 200:
            print("   error:", str((datos.get("error") or {}).get("message", ""))[:300])
            continue
        cand = (datos.get("candidates") or [{}])[0] or {}
        print("   claves de la respuesta:", sorted(datos.keys()))
        print("   claves del candidato:", sorted(cand.keys()), "· fin:", cand.get("finishReason"))
        gm = cand.get("groundingMetadata")
        if gm is None:
            print("   groundingMetadata: NO VIENE en el candidato")
        else:
            print("   groundingMetadata: claves", sorted(gm.keys()))
            print("     webSearchQueries:", gm.get("webSearchQueries"))
            print("     groundingChunks:", len(gm.get("groundingChunks") or []),
                  [((c or {}).get("web") or {}).get("title") for c in (gm.get("groundingChunks") or [])][:8])
            print("     searchEntryPoint:", "sí" if gm.get("searchEntryPoint") else "no",
                  "· groundingSupports:", len(gm.get("groundingSupports") or []))
        otras = [(ruta, v) for clave in ("webSearchQueries", "groundingMetadata", "groundingChunks", "searchEntryPoint")
                 for ruta, v in buscar(datos, clave) if not ruta.startswith("candidates[0].groundingMetadata")
                 and ruta != "candidates[0].groundingMetadata"]
        print("   datos de búsqueda en otros lugares:", [r_ for r_, _ in otras] or "ninguno")
        print("   uso de tokens:", datos.get("usageMetadata"))
        partes = ((cand.get("content") or {}).get("parts")) or []
        print("   partes:", [sorted(p.keys()) for p in partes if isinstance(p, dict)])
        texto = "".join(p.get("text", "") for p in partes if isinstance(p, dict) and not p.get("thought"))
        print("   texto (inicio):", texto[:240].replace("\n", " "))
        lec = s.gemini_leer(datos, j)
        print(f"   lectura de semana.py: estado {lec['estado']} · búsquedas {lec['busquedas']} · dominios '{lec['dominios']}' · "
              f"costo USD {lec['costo_usd']}")
        print("   estructura:", "; ".join(p for p in rutas(datos) if "text" not in p.split(".")[-1])[:900])
    print("\nListo. Reenvía esta salida (y, si te la pido, los dos archivos diag_gemini_*.json).")


if __name__ == "__main__":
    main()
