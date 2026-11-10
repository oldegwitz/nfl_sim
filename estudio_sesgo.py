#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
estudio_sesgo.py — decisión 51: ¿la bandera de sesgo del TOTAL (21A) debe tumbar las selecciones de moneyline y spread
de 29A? Recrea 2023-2025 tal como corre hoy el motor y aplica la regla escrita ANTES en contexto_proyecto_nfl.md.

Qué hace:
  1. Vuelve a simular los 855 juegos de la prueba de H29 con s2-v1 (las funciones de sprint2.py, md5 baad72c6…, y la
     misma semilla) para tener la distribución completa del margen de cada juego.
     CONTROL: el margen y el total medios tienen que salir iguales a salidas/sprint2/proyecciones_2023_2025.csv; si no,
     se detiene (no decide con otra proyección).
  2. Con la línea de Pinnacle «3 h antes» y el cierre del histórico de la fase 1 (~/nfl_ev/historico/base_juegos.csv,
     solo lectura), recrea con las reglas de semana.py: el filtro (spread > 3,5 contra Pinnacle; total > 5,0 contra
     nflverse), la revisión de sesgo de cada semana (21A: |media| > 1,0 en spread o > 1,5 en total) y las selecciones de
     29A (moneyline: modelo − Pinnacle sin vig ≥ 3 pp; spread: P(cubre la línea de Pinnacle | sin push) ≥ 53 %).
  3. CLV sin vig (decisión 46) de cada selección entre la señal (3 h) y el cierre de Pinnacle. Moneyline: exacto.
     Spread: aproximado (el histórico no trae el precio del spread de Pinnacle): la línea de la señal y la del cierre se
     pasan a probabilidad con la distribución del margen de la sección 3 (clase Margen) anclada al 50 %.
  4. Regla de decisión (decisión 51): queda «a» (las reglas como están) salvo que se cumplan las dos:
     (1) con «a», la media de selecciones por temporada en las semanas 5-18 es < 60;
     (2) las selecciones que «b» agrega (semanas marcadas SOLO por el total) no son peores que las candidatas:
         diferencia de CLV medio (agregadas − candidatas) ≥ 0 y límite inferior del IC 95 % ≥ −1 punto porcentual
         (remuestreo de juegos, 10.000, semilla 5102026).
     Si se cumplen las dos → «b» desde la semana 6 de 2026. El CLV de las candidatas («lo que 29A habría dado») se
     reporta y no decide. 2023-2025 ya se usó en H29: esto es exploración para elegir cómo cuenta 29A; s2-v1 no cambia
     y el veredicto de 29A sigue siendo solo 2026.

Uso (en ~/nfl_sim, una sola vez):
  (nohup nice -n 10 venv/bin/python -u estudio_sesgo.py > salidas/estudio_sesgo.log 2>&1 &)
  venv/bin/python -u estudio_sesgo.py --prueba    solo 2023, semanas 1-4 (control de la semilla y del código; no decide)
  --base RUTA   otro base_juegos.csv · --sin-telegram

Salidas: salidas/estudio_sesgo/ (resumen, CSV por juego, por semana y por selección, zip) y Telegram (bot de líneas,
igual que sprint2.py y estudio_e1.py; el token se lee de ~/nfl_ev/config.ini y nunca se muestra). No escribe en la hoja,
no toca el registro, el temporizador ni los bots.
"""
import argparse
import csv
import fcntl
import hashlib
import json
import os
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import polars as pl

VERSION = "sesgo-v1 (10-oct-2026)"
BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
SAL = BASE / "salidas" / "estudio_sesgo"
PROY_H29 = BASE / "salidas" / "sprint2" / "proyecciones_2023_2025.csv"
BASE_HIST = Path.home() / "nfl_ev" / "historico" / "base_juegos.csv"
CONFIG_BOT = Path.home() / "nfl_ev" / "config.ini"
MD5_S2 = "baad72c6a5dc0054a7de22a79c88616f"
SEMILLA_BOOT = 5102026
B_BOOT = 10_000
SEM_29A = (5, 18)                  # 29A cuenta en la temporada regular, semanas 5 a 18
N_MIN_29A = 60                     # condición (1)
PISO_CLV = -0.01                   # condición (2): límite inferior ≥ −1 punto porcentual
TOL_CONTROL = 1e-6


def log(msg):
    print(f"[{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} UTC] {msg}", flush=True)


def md5(ruta):
    h = hashlib.md5()
    with open(ruta, "rb") as fh:
        for t in iter(lambda: fh.read(1 << 20), b""):
            h.update(t)
    return h.hexdigest()


def pico_mb():
    try:
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    except Exception:  # noqa: BLE001
        return float("nan")


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


def _f(x):
    try:
        return None if x in (None, "") else float(x)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------------------------------------------------
# 1. Proyección con s2-v1 (copia literal del bucle de sprint2.proyectar; solo guarda además P(cubre) en la línea de 3 h)
# --------------------------------------------------------------------------------------------------------------------
def proyectar_con_lineas(s2, M, EQ, juegos, games, mu_pool, n_sims, semilla, linea_3h):
    """Mismo orden, mismas semillas y mismas funciones que sprint2.proyectar. linea_3h: {game_id: hándicap del local
    de Pinnacle 3 h antes (convención de la casa)}. Devuelve una fila por juego."""
    filas = []
    juegos = juegos.with_columns(s2._eq("home_team"), s2._eq("away_team")).sort(["season", "week", "game_id"])
    for (temp, sem), g in juegos.group_by(["season", "week"], maintain_order=True):
        R = s2.calificar(EQ, temp * s2.W_TEMP + sem, temp, s2.PAR_EQ)
        hfa = s2.localia(games, temp)
        F = s2.fuerza_partidos(EQ, R, g["home_team"].to_list(), g["away_team"].to_list(),
                               g["home_qb_id"].fill_null("").to_list(), g["away_qb_id"].fill_null("").to_list(),
                               (g["location"] == "Neutral").to_numpy(), hfa, mu_pool, s2.PAR_EQ)
        ng = g.height
        rep = np.repeat(np.arange(ng), n_sims)
        f = dict(dp=F["dp"][rep], dr=F["dr"][rep])
        po = np.repeat((g["game_type"] != "REG").to_numpy(), n_sims)
        r = s2.simular(M, ng * n_sims, po, np.random.default_rng(semilla + temp * 100 + sem), fuerza=f)
        mg = r["margen"].reshape(ng, n_sims)
        tt = r["total"].reshape(ng, n_sims)
        for i in range(ng):
            m = mg[i]
            gid = g["game_id"][i]
            pw, pt_, pe = float((m > 0).mean()), float((m < 0).mean()), float((m == 0).mean())
            fila = dict(game_id=gid, season=int(temp), week=int(sem), game_type=g["game_type"][i],
                        local=g["home_team"][i], visita=g["away_team"][i],
                        margen=float(m.mean()), total=float(tt[i].mean()),
                        p_local_s2=pw, p_empate=pe,
                        p_ml_local=pw / max(pw + pt_, 1e-9))          # semana.fila_base: sin empates
            h = linea_3h.get(gid)
            if h is not None:                                           # semana.correr: P(cubre | sin push)
                cub, psh = float((m + h > 0).mean()), float((m + h == 0).mean())
                fila["p_cubre_local"] = cub / max(1 - psh, 1e-9)
            filas.append(fila)
        log(f"  {temp} semana {sem}: {ng} juegos · pico {pico_mb():.0f} MB")
    return filas


def control_h29(filas, ruta):
    """Compara el margen y el total medios con el archivo de la corrida oficial de H29. (n comparados, máx. diferencia)."""
    h = pl.read_csv(ruta, infer_schema_length=0)
    ref = {r["game_id"]: (float(r["margen"]), float(r["total"])) for r in h.iter_rows(named=True)}
    dif, n = 0.0, 0
    for f in filas:
        if f["game_id"] in ref:
            a, b = ref[f["game_id"]]
            dif = max(dif, abs(f["margen"] - a), abs(f["total"] - b))
            n += 1
    return n, dif


# --------------------------------------------------------------------------------------------------------------------
# 2. Filtro, sesgo semanal y selecciones (reglas de semana.py)
# --------------------------------------------------------------------------------------------------------------------
def recrear(S, filas, base, games):
    """Agrega a cada juego las líneas del histórico, el filtro y las selecciones; devuelve (juegos, semanas)."""
    nfl = {r["game_id"]: r for r in games.iter_rows(named=True)}
    for f in filas:
        b = base.get(f["game_id"]) or {}
        g = nfl.get(f["game_id"]) or {}
        f.update(pin_3h_hcp=_f(b.get("pin_3h_hcp_local")), pin_3h_ml_l=_f(b.get("pin_3h_ml_local")),
                 pin_3h_ml_v=_f(b.get("pin_3h_ml_visit")), pin_3h_min=_f(b.get("pin_3h_min_antes")),
                 ci_hcp=_f(b.get("ci_hcp_local")), ci_ml_l=_f(b.get("ci_ml_local")), ci_ml_v=_f(b.get("ci_ml_visit")),
                 cerrado=str(b.get("cerrado") or "") == "1",
                 nfl_spread=_f(g.get("spread_line")), nfl_total=_f(g.get("total_line")), result=_f(g.get("result")))
        f["spread_modelo"] = -f["margen"]
        if f["pin_3h_hcp"] is not None:
            f["ref_spread"], f["spread_ref"] = "pinnacle 3 h", f["pin_3h_hcp"]
        elif f["nfl_spread"] is not None:
            f["ref_spread"], f["spread_ref"] = "nflverse", -f["nfl_spread"]
        else:
            f["ref_spread"], f["spread_ref"] = "", None
        f["dif_spread"] = None if f["spread_ref"] is None else f["spread_modelo"] - f["spread_ref"]
        f["dif_total"] = None if f["nfl_total"] is None else f["total"] - f["nfl_total"]
        f["marcado_spread"] = f["dif_spread"] is not None and abs(f["dif_spread"]) > S.FILTRO_SPREAD
        f["marcado_total"] = f["dif_total"] is not None and abs(f["dif_total"]) > S.FILTRO_TOTAL
        # control 2 (H29): la misma revisión contra el cierre de nflverse
        f["dif_spread_nfl"] = None if f["nfl_spread"] is None else f["spread_modelo"] + f["nfl_spread"]
        # selecciones de 29A (solo con Pinnacle)
        f["p_pin_ml_local"] = (S.sin_vig_potencia(f["pin_3h_ml_l"], f["pin_3h_ml_v"])
                               if f["pin_3h_ml_l"] is not None and f["pin_3h_ml_v"] is not None else None)
        f["sel_ml"] = f["sel_sp"] = None
        if f["p_pin_ml_local"] is not None:
            v = f["p_ml_local"] - f["p_pin_ml_local"]
            f["sel_ml"] = "local" if v >= S.UMBRAL_ML else "visita" if -v >= S.UMBRAL_ML else None
        if f.get("p_cubre_local") is not None:
            pc = f["p_cubre_local"]
            f["sel_sp"] = "local" if pc >= S.UMBRAL_SP else "visita" if 1 - pc >= S.UMBRAL_SP else None
    # revisión de sesgo de cada semana (todas las semanas del período, como semana.sesgo_semanal)
    semanas = {}
    for f in filas:
        semanas.setdefault((f["season"], f["week"]), []).append(f)
    tabla = []
    for (s, w), fs in sorted(semanas.items()):
        ds = [f["dif_spread"] for f in fs if f["dif_spread"] is not None]
        dt = [f["dif_total"] for f in fs if f["dif_total"] is not None]
        dn = [f["dif_spread_nfl"] for f in fs if f["dif_spread_nfl"] is not None]
        ss = float(np.mean(ds)) if ds else None
        st = float(np.mean(dt)) if dt else None
        sn = float(np.mean(dn)) if dn else None
        b_sp = ss is not None and abs(ss) > S.SESGO_SPREAD
        b_to = st is not None and abs(st) > S.SESGO_TOTAL
        b_h29 = (sn is not None and abs(sn) > S.SESGO_SPREAD) or b_to
        tipo = "spread y total" if b_sp and b_to else "spread" if b_sp else "total" if b_to else ""
        tabla.append(dict(season=s, week=w, juegos=len(fs), sesgo_spread=ss, sesgo_total=st, sesgo_spread_nfl=sn,
                          bandera=tipo, bandera_h29=b_h29))
        for f in fs:
            f["bandera"] = tipo
    for f in filas:
        if f["marcado_spread"] or f["marcado_total"]:
            f["estado"] = "filtro"
        elif f["bandera"] == "total":
            f["estado"] = "sesgo solo total"            # lo que «b» dejaría contar
        elif f["bandera"]:
            f["estado"] = "sesgo spread"
        else:
            f["estado"] = "candidata"
    return filas, tabla


# --------------------------------------------------------------------------------------------------------------------
# 3. CLV sin vig de cada selección (decisión 46)
# --------------------------------------------------------------------------------------------------------------------
def selecciones(S, filas):
    out = []
    for f in filas:
        res = f["result"]
        for mercado in ("ML", "SP"):
            lado = f["sel_ml"] if mercado == "ML" else f["sel_sp"]
            if lado is None:
                continue
            s = dict(game_id=f["game_id"], season=f["season"], week=f["week"], game_type=f["game_type"],
                     mercado=mercado, lado=lado, equipo=f["local"] if lado == "local" else f["visita"],
                     estado=f["estado"], bandera=f["bandera"], pin_3h_min=f["pin_3h_min"])
            if mercado == "ML":
                q_sig = f["p_pin_ml_local"] if lado == "local" else 1 - f["p_pin_ml_local"]
                q_cie = None
                if f["cerrado"] and f["ci_ml_l"] is not None and f["ci_ml_v"] is not None:
                    pc = S.sin_vig_potencia(f["ci_ml_l"], f["ci_ml_v"])
                    q_cie = None if pc is None else (pc if lado == "local" else 1 - pc)
                s["ventaja_modelo"] = (f["p_ml_local"] - f["p_pin_ml_local"]) * (1 if lado == "local" else -1)
                s["no_favorito"] = q_sig < 0.5
                gano = None if res is None or res == 0 else ((res > 0) == (lado == "local"))
            else:
                h = f["pin_3h_hcp"]
                q_sig = 0.5                                        # sin precio del spread: la línea de la señal al 50 %
                q_cie = None
                if f["cerrado"] and f["ci_hcp"] is not None:
                    pw, pp = S.Margen(f["ci_hcp"], 0.5).local(h)
                    pl_ = pw / max(1 - pp, 1e-9)
                    q_cie = pl_ if lado == "local" else 1 - pl_
                s["ventaja_modelo"] = (f["p_cubre_local"] - 0.5) * (1 if lado == "local" else -1)
                s["no_favorito"] = (h > 0) if lado == "local" else (h < 0)
                if res is None:
                    gano = None
                else:
                    x = res + h if lado == "local" else -(res + h)
                    gano = None if abs(x) < 1e-9 else x > 0
            s.update(q_senal=q_sig, q_cierre=q_cie, clv=None if q_cie is None else q_cie / q_sig - 1,
                     resultado="" if gano is None else ("ganó" if gano else "perdió"), esperado=q_cie)
            out.append(s)
    return out


# --------------------------------------------------------------------------------------------------------------------
# 4. Estadística y regla de decisión
# --------------------------------------------------------------------------------------------------------------------
def _por_juego(sels):
    """(sumas de CLV, cuentas) por juego, en el mismo orden."""
    d = {}
    for s in sels:
        if s["clv"] is None:
            continue
        a = d.setdefault(s["game_id"], [0.0, 0])
        a[0] += s["clv"]
        a[1] += 1
    v = list(d.values())
    return np.array([x[0] for x in v], dtype=float), np.array([x[1] for x in v], dtype=float)


def media_ic(sels, rng):
    su, cu = _por_juego(sels)
    if cu.sum() == 0:
        return None, None, None, 0, 0
    est = float(su.sum() / cu.sum())
    k = len(su)
    idx = rng.integers(0, k, size=(B_BOOT, k))
    bs = su[idx].sum(axis=1) / np.maximum(cu[idx].sum(axis=1), 1)
    return est, float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5)), int(cu.sum()), k


def diferencia_ic(a, b, rng):
    """CLV medio de a − el de b, con remuestreo de juegos independiente en cada grupo."""
    sa, ca = _por_juego(a)
    sb, cb = _por_juego(b)
    if ca.sum() == 0 or cb.sum() == 0:
        return None, None, None
    est = float(sa.sum() / ca.sum() - sb.sum() / cb.sum())
    ia = rng.integers(0, len(sa), size=(B_BOOT, len(sa)))
    ib = rng.integers(0, len(sb), size=(B_BOOT, len(sb)))
    bs = sa[ia].sum(axis=1) / np.maximum(ca[ia].sum(axis=1), 1) - sb[ib].sum(axis=1) / np.maximum(cb[ib].sum(axis=1), 1)
    return est, float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


def fi(x, dec=2, signo=True):
    return "—" if x is None else (f"{x:+.{dec}f}" if signo else f"{x:.{dec}f}").replace(".", ",")


def pct(x, dec=2):
    return "—" if x is None else f"{100 * x:+.{dec}f} %".replace(".", ",")


def analizar(sels, tabla, temporadas, decidir):
    rng = np.random.default_rng(SEMILLA_BOOT)
    en = [s for s in sels if s["game_type"] == "REG" and SEM_29A[0] <= s["week"] <= SEM_29A[1]]
    grupos = {e: [s for s in en if s["estado"] == e] for e in ("candidata", "sesgo solo total", "sesgo spread", "filtro")}
    out = {"grupos": {}}
    for e, g in grupos.items():
        est, lo, hi, n, k = media_ic(g, rng)
        ml = [s for s in g if s["mercado"] == "ML"]
        res = [s for s in g if s["resultado"]]
        out["grupos"][e] = dict(
            n=len(g), n_clv=n, juegos=k, clv=est, lo=lo, hi=hi,
            ml=len(ml), sp=len(g) - len(ml),
            no_fav_ml=(sum(1 for s in ml if s["no_favorito"]) / len(ml)) if ml else None,
            gano=sum(1 for s in res if s["resultado"] == "ganó"), decididas=len(res),
            esperadas=sum(s["esperado"] or 0 for s in res),
            clv_ml=media_ic(ml, rng)[0], clv_sp=media_ic([s for s in g if s["mercado"] == "SP"], rng)[0])
    por_temp = {}
    for t in temporadas:
        ga = sum(1 for s in grupos["candidata"] if s["season"] == t)
        gb = ga + sum(1 for s in grupos["sesgo solo total"] if s["season"] == t)
        por_temp[t] = (ga, gb)
    out["por_temporada"] = por_temp
    out["media_a"] = float(np.mean([v[0] for v in por_temp.values()])) if por_temp else 0.0
    out["media_b"] = float(np.mean([v[1] for v in por_temp.values()])) if por_temp else 0.0
    d_est, d_lo, d_hi = diferencia_ic(grupos["sesgo solo total"], grupos["candidata"], rng)
    out["dif"] = (d_est, d_lo, d_hi)
    # semanas
    sem_29 = [w for w in tabla if SEM_29A[0] <= w["week"] <= SEM_29A[1]]
    out["semanas"] = dict(
        todas=len(tabla), marcadas=sum(1 for w in tabla if w["bandera"]),
        h29=sum(1 for w in tabla if w["bandera_h29"]),
        en_29a=len(sem_29), en_29a_marcadas=sum(1 for w in sem_29 if w["bandera"]),
        solo_total=sum(1 for w in sem_29 if w["bandera"] == "total"),
        solo_spread=sum(1 for w in sem_29 if w["bandera"] == "spread"),
        ambas=sum(1 for w in sem_29 if w["bandera"] == "spread y total"),
        sesgo_total_medio=float(np.mean([w["sesgo_total"] for w in sem_29 if w["sesgo_total"] is not None])) if sem_29 else None,
        sesgo_spread_medio=float(np.mean([w["sesgo_spread"] for w in sem_29 if w["sesgo_spread"] is not None])) if sem_29 else None)
    if decidir:
        c1 = out["media_a"] < N_MIN_29A
        c2 = d_est is not None and d_est >= 0 and d_lo is not None and d_lo >= PISO_CLV
        out["c1"], out["c2"] = c1, c2
        out["decision"] = "b" if (c1 and c2) else "a"
    return out


def texto_resumen(out, ctl, ctl2, decidir, meta):
    g = out["grupos"]
    s = out["semanas"]
    L = [f"ESTUDIO DE LA BANDERA DE SESGO (decisión 51) · {VERSION}", meta, ""]
    L.append(f"Control 1 (proyección = H29): {ctl[0]} juegos, diferencia máxima {ctl[1]:.2e} → {'OK' if ctl[1] <= TOL_CONTROL else 'NO COINCIDE'}")
    L.append(f"Control 2 (semanas marcadas contra el cierre de nflverse, como H29): {ctl2}")
    L += ["", "Semanas (temporada regular 5-18, contra Pinnacle 3 h como en vivo):",
          f"  marcadas {s['en_29a_marcadas']} de {s['en_29a']} · solo por el total {s['solo_total']} · solo por el spread "
          f"{s['solo_spread']} · por los dos {s['ambas']} · sesgo medio: total {fi(s['sesgo_total_medio'])}, spread {fi(s['sesgo_spread_medio'])}"
          if s["en_29a"] else "  (ninguna semana 5-18 en esta corrida)",
          f"  todas las semanas del período: {s['marcadas']} de {s['todas']} marcadas"]
    L += ["", "Selecciones de 29A, semanas 5-18 (CLV sin vig con IC 95 % por juego · % no favorito en ML · aciertos):"]
    nombres = {"candidata": "Candidatas (cuentan con «a» y con «b»)", "sesgo solo total": "Tumbadas solo por el total (las agrega «b»)",
               "sesgo spread": "Tumbadas por el sesgo del spread (fuera con las dos)", "filtro": "Tumbadas por el filtro (fuera con las dos)"}
    for e, nom in nombres.items():
        x = g[e]
        nf = "—" if x["no_fav_ml"] is None else f"{100 * x['no_fav_ml']:.0f} %"
        L.append(f"  {nom}: n {x['n']} ({x['ml']} ML, {x['sp']} spread; {x['juegos']} juegos) · CLV {pct(x['clv'])} "
                 f"[{pct(x['lo'])}; {pct(x['hi'])}] · ML {pct(x['clv_ml'])} · spread {pct(x['clv_sp'])} (aprox.) · "
                 f"no favorito {nf} · ganó {x['gano']} de {x['decididas']} (cierre esperaba {fi(x['esperadas'], 1, False)})")
    L += ["", "Selecciones por temporada (semanas 5-18): " + " · ".join(f"{t}: a {a}, b {b}" for t, (a, b) in out["por_temporada"].items()),
          f"Media por temporada: con «a» {fi(out['media_a'], 1, False)} · con «b» {fi(out['media_b'], 1, False)} (29A necesita 60)"]
    d = out["dif"]
    L.append(f"Diferencia de CLV (agregadas por «b» − candidatas): {pct(d[0])} [{pct(d[1])}; {pct(d[2])}]")
    if decidir:
        L += ["", "REGLA (escrita antes, decisión 51):",
              f"  (1) con «a» < {N_MIN_29A} selecciones por temporada: {'SÍ' if out['c1'] else 'NO'} ({fi(out['media_a'], 1, False)})",
              f"  (2) agregadas no peores (diferencia ≥ 0 y límite inferior ≥ −1 pp): {'SÍ' if out['c2'] else 'NO'}",
              f"DECISIÓN SEGÚN LA REGLA: «{out['decision']}» "
              + ("→ desde la semana 6, el sesgo del total deja de tumbar las selecciones de moneyline y spread"
                 if out["decision"] == "b" else "→ las reglas de 29A y 21A siguen como están")]
    else:
        L += ["", "PRUEBA (semanas fuera de 29A): no se aplica la regla."]
    L += ["", "Notas: la línea «3 h» del histórico es la última foto con 3 h o más (mediana ≈ 5 h antes); en vivo la señal "
          "es de ≤ 3 h a T−85. El CLV del spread es aproximado (sin precio del spread de Pinnacle en el histórico). "
          "2023-2025 ya se usó en H29: exploración para elegir cómo cuenta 29A; s2-v1 no cambia y el veredicto de 29A "
          "es solo con 2026. Las candidatas de 2023-2025 no validan nada."]
    return "\n".join(L)


def escribir_csv(ruta, filas, campos=None):
    if not filas:
        ruta.write_text("", encoding="utf-8")
        return
    campos = campos or list(filas[0].keys())
    with open(ruta, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=campos, extrasaction="ignore")
        w.writeheader()
        for f in filas:
            w.writerow({k: ("" if v is None else v) for k, v in f.items()})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prueba", action="store_true", help="solo 2023, semanas 1-4 (fuera de 29A): control, sin decisión")
    ap.add_argument("--base", default=str(BASE_HIST))
    ap.add_argument("--sin-telegram", action="store_true")
    ap.add_argument("--n-sims", type=int, default=10_000)
    args = ap.parse_args()
    if os.nice(0) < 10:
        os.nice(10 - os.nice(0))
    SAL.mkdir(parents=True, exist_ok=True)
    candado = open(SAL / ".candado", "w")
    try:
        fcntl.flock(candado, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit("Ya hay una corrida de estudio_sesgo.py en marcha; no lanzo otra.")
    t0 = time.time()
    salida = SAL / ("prueba" if args.prueba else "")
    salida.mkdir(parents=True, exist_ok=True)
    log(f"estudio_sesgo.py {VERSION} · {'PRUEBA 2023 semanas 1-4' if args.prueba else 'corrida completa 2023-2025'} · nice {os.nice(0)}")

    # ---- lo que tiene que estar ----
    if not (BASE / "sprint2.py").exists() or md5(BASE / "sprint2.py") != MD5_S2:
        raise SystemExit("sprint2.py no es el s2-v1 congelado (md5): no sigo")
    if not PROY_H29.exists():
        raise SystemExit(f"Falta {PROY_H29} (la proyección de H29 para el control)")
    if not Path(args.base).exists():
        raise SystemExit(f"Falta el histórico {args.base}")
    import sprint2 as s2      # solo sus funciones (no corre su main)
    import semana as S        # sin vig, Margen y los umbrales de 29A/21A que usa el motor en vivo
    log(f"s2-v1 {MD5_S2[:8]} · {S.VERSION_SEMANA} · umbrales: filtro {S.FILTRO_SPREAD}/{S.FILTRO_TOTAL}, sesgo "
        f"{S.SESGO_SPREAD}/{S.SESGO_TOTAL}, 29A ML {S.UMBRAL_ML} · spread {S.UMBRAL_SP}")

    # ---- datos y modelo, igual que sprint2.main ----
    games, pbp = s2.preparar_datos()
    M = s2.construir_modelo(pbp, games)
    pp = pbp.filter(pl.col("play_type").is_in(["pass", "run"]) & pl.col("down").is_not_null()
                    & pl.col("epa").is_not_null() & pl.col("posteam").is_not_null())
    mu_pool = (float(pp.filter(pl.col("play_type") == "pass")["epa"].mean()), float(pp.filter(pl.col("play_type") == "run")["epa"].mean()))
    del pbp, pp
    EQ = s2.preparar_equipos(s2.cargar_equipos(games))
    log(f"modelo y equipos listos · pico {pico_mb():.0f} MB · {time.time() - t0:.0f} s")
    juegos = games.filter(pl.col("season").is_in(s2.TEMP_PRUEBA) & pl.col("result").is_not_null())
    if args.prueba:
        juegos = juegos.filter((pl.col("season") == 2023) & (pl.col("week") <= 4))
    base = {r["game_id"]: r for r in pl.read_csv(args.base, infer_schema_length=0).iter_rows(named=True)}
    linea_3h = {gid: _f(r.get("pin_3h_hcp_local")) for gid, r in base.items() if _f(r.get("pin_3h_hcp_local")) is not None}

    # ---- proyección y control ----
    filas = proyectar_con_lineas(s2, M, EQ, juegos, games, mu_pool, args.n_sims, s2.SEMILLA + 1000, linea_3h)
    ctl = control_h29(filas, PROY_H29)
    log(f"control: {ctl[0]} juegos comparados con H29, diferencia máxima {ctl[1]:.2e}")
    if args.n_sims == 10_000 and (ctl[0] != len(filas) or ctl[1] > TOL_CONTROL):
        raise SystemExit(f"CONTROL FALLÓ: la proyección no es la de H29 ({ctl[0]} de {len(filas)} juegos, diferencia "
                         f"{ctl[1]:.2e}). No decido con otra proyección: mándale este registro a Claude.")

    # ---- recrear y medir ----
    filas, tabla = recrear(S, filas, base, games)
    n_h29 = sum(1 for w in tabla if w["bandera_h29"])
    ctl2 = f"{n_h29} de {len(tabla)} semanas" + ("" if args.prueba else " (H29 reportó 35 de 66)")
    sels = selecciones(S, filas)
    temporadas = sorted({f["season"] for f in filas})
    out = analizar(sels, tabla, temporadas, decidir=not args.prueba)
    meta = (f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC} · {len(filas)} juegos · {len(sels)} selecciones · "
            f"{args.n_sims} simulaciones por juego · {time.time() - t0:.0f} s · pico {pico_mb():.0f} MB")
    texto = texto_resumen(out, ctl, ctl2, not args.prueba, meta)
    print(texto, flush=True)

    # ---- archivos ----
    (salida / "resumen_sesgo.txt").write_text(texto + "\n", encoding="utf-8")
    escribir_csv(salida / "juegos_sesgo.csv", filas)
    escribir_csv(salida / "semanas_sesgo.csv", tabla)
    escribir_csv(salida / "selecciones_sesgo.csv", sels)
    (salida / "resultado_sesgo.json").write_text(json.dumps(dict(version=VERSION, prueba=args.prueba, control=ctl,
                                                                 decision=out.get("decision"), media_a=out["media_a"],
                                                                 media_b=out["media_b"], dif=out["dif"],
                                                                 semanas=out["semanas"]), ensure_ascii=False, indent=1),
                                                 encoding="utf-8")
    zp = salida / "estudio_sesgo_resultados.zip"
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        for n in ("resumen_sesgo.txt", "juegos_sesgo.csv", "semanas_sesgo.csv", "selecciones_sesgo.csv", "resultado_sesgo.json"):
            z.write(salida / n, n)
    log(f"archivos en {salida.relative_to(BASE)} · zip {zp.name}")
    if not args.sin_telegram:
        telegram(texto, zp)
    log("listo")


if __name__ == "__main__":
    main()
