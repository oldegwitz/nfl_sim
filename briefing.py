#!/usr/bin/env python3
"""
briefing.py — decisión 68 (aprobada el 1-nov-2026, D1-D8): briefing ampliado y matriz de decisión. DESCRIPTIVO.

Lo usa semana.py (v9.3); no es un modelo: no cambia s2-v1, la proyección, 31A, 29A ni el registro de #9.
  · Métricas de equipo de 2026 (nflverse, temporada regular) con su puesto 1-32 y la marca de estabilidad de H44.
  · Récord, casa y visita, contra la línea, últimos 5, racha, descanso y QB mezclado (43).
  · Precios: Pinnacle sin vig (método de potencia) contra BetOnline (ML, spread y puntos comprados), con el precio
    tope de la regla de 68 (costo 2 %) y la marca ✅ / ⚠️ / ❌ / ⏳.
  · Constructor del boleto de 12-13 patas (D6 = c): la forma más probable que pasa la regla, con la más barata al lado,
    comparado con «todo ML» y «todo más barato» (probabilidad de cobrar, pago, EV y costo esperado en USD).
  · Tarjeta a color en 2 imágenes por partido (matplotlib) y textos HTML para Telegram (solo el primero suena).
  · Seguimiento para el informe del lunes: lo que sugería la matriz frente a lo apostado (parlays_2026.json).

Las funciones reciben el módulo de semana.py como S (sin importarlo aquí: así no se duplica ni se cruza la importación).

Prueba sin costo (en ~/nfl_sim):  venv/bin/python briefing.py prueba
"""
from __future__ import annotations

import configparser
import hashlib
import html
import json
import math
import re
import sys
import time
from pathlib import Path

VERSION_BRIEFING = "briefing-v1 (2-nov-2026)"

# --------------------------------------------------------------------------------------------------------------------
# H44 congelada (registro 68): r de Pearson entre las semanas 1-8 y 10-18 de la misma temporada, 2016-2025, n 320.
# --------------------------------------------------------------------------------------------------------------------
ESTABILIDAD = {
    "exito_of": 0.53, "epa_of": 0.52, "net_epa": 0.47, "epa_pase_of": 0.47, "pts_f": 0.47, "sack_of": 0.41,
    "explos_of": 0.37, "3er_of": 0.37, "exito_de": 0.36, "epa_de": 0.34, "epa_corr_of": 0.32, "punt_neto": 0.30,
    "explos_de": 0.28, "castigos_pj": 0.28, "pts_c": 0.27, "castigos_yd_pj": 0.27, "inicio_de": 0.27, "epa_pase_de": 0.27,
    "epa_corr_de": 0.24, "st_epa_pj": 0.22, "entrega_pj": 0.21, "margen_tot": 0.17, "margen_pj": 0.17, "zr_td_of": 0.17,
    "sack_de": 0.15, "recupera_pj": 0.14, "3er_de": 0.14, "inicio_of": 0.12, "fg_pct": 0.11, "zr_td_de": 0.10,
    "fumbles_recup_pct": 0.05,
}
ESTABILIDAD_MD5 = "65c4ef11b8b2818faf97ffda920a4f3f"   # md5 de json.dumps(ESTABILIDAD, sort_keys=True); la prueba lo verifica

# sentido: 1 = más alto es mejor
SENTIDO = {"pts_f": 1, "pts_c": 0, "epa_of": 1, "exito_of": 1, "epa_pase_of": 1, "epa_corr_of": 1, "explos_of": 1,
           "sack_of": 0, "3er_of": 1, "zr_td_of": 1, "inicio_of": 1, "epa_de": 0, "exito_de": 0, "epa_pase_de": 0,
           "epa_corr_de": 0, "explos_de": 0, "sack_de": 1, "3er_de": 0, "zr_td_de": 0, "inicio_de": 0, "net_epa": 1,
           "entrega_pj": 0, "recupera_pj": 1, "margen_pj": 1, "fumbles_recup_pct": 1, "st_epa_pj": 1, "fg_pct": 1,
           "punt_neto": 1, "castigos_pj": 0, "castigos_yd_pj": 0}

# clave → (nombre en palabras, forma de escribir)
NOMBRES = {
    "pts_f": ("Puntos a favor por partido", "dec1"), "pts_c": ("Puntos en contra por partido", "dec1"),
    "epa_of": ("Ataque: EPA por jugada", "epa"), "exito_of": ("Ataque: jugadas con éxito", "pct"),
    "epa_pase_of": ("Ataque: EPA de pase", "epa"), "epa_corr_of": ("Ataque: EPA de corrida", "epa"),
    "explos_of": ("Ataque: jugadas explosivas", "pct"), "sack_of": ("Ataque: sacks recibidos por dropback", "pct"),
    "3er_of": ("Ataque: 3.er down convertido", "pct"), "zr_td_of": ("Ataque: TD en zona roja", "pct"),
    "inicio_of": ("Ataque: yardas por recorrer al empezar la serie", "dec1"),
    "epa_de": ("Defensa: EPA permitido por jugada", "epa"), "exito_de": ("Defensa: éxito permitido", "pct"),
    "epa_pase_de": ("Defensa: EPA de pase permitido", "epa"), "epa_corr_de": ("Defensa: EPA de corrida permitido", "epa"),
    "explos_de": ("Defensa: explosivas permitidas", "pct"), "sack_de": ("Defensa: sacks por dropback rival", "pct"),
    "3er_de": ("Defensa: 3.er down permitido", "pct"), "zr_td_de": ("Defensa: TD permitido en zona roja", "pct"),
    "inicio_de": ("Defensa: yardas por recorrer del rival al empezar", "dec1"),
    "net_epa": ("EPA neto por jugada (ataque − defensa)", "epa"),
    "entrega_pj": ("Pérdidas entregadas por partido", "dec1"), "recupera_pj": ("Pérdidas recuperadas por partido", "dec1"),
    "margen_pj": ("Margen de pérdidas por partido", "sdec1"), "fumbles_recup_pct": ("Fumbles que recupera", "pct"),
    "st_epa_pj": ("Equipos especiales: puntos por partido (EPA)", "sdec1"), "fg_pct": ("Goles de campo anotados", "pct"),
    "punt_neto": ("Despeje neto (yardas)", "dec1"), "castigos_pj": ("Castigos por partido", "dec1"),
    "castigos_yd_pj": ("Yardas de castigo por partido", "ent"),
}

TIER = [("🟢", "#0ca30c"), ("🟡", "#fab219"), ("🟠", "#ec835a"), ("🔴", "#d03b3b")]
BG, PANEL, T1, T2 = "#1a1a19", "#262624", "#f0efec", "#c3c2b7"
C_BIEN, C_AVISO, C_SERIO, C_MAL = "#0ca30c", "#fab219", "#ec835a", "#d03b3b"

# --------------------------------------------------------------------------------------------------------------------
# Regla de la matriz (68, escrita antes)
# --------------------------------------------------------------------------------------------------------------------
EV_BIEN, EV_AVISO = -0.020, -0.030           # ✅ EV ≥ −2,0 % · ⚠️ entre −2,0 y −3,0 % · ❌ < −3,0 %
CLAVES_PUNTOS = (3, 7, 10)                    # comprar puntos solo si cruza uno de estos
CLAVES_GRANDES = (6, 14)                      # … y estos en favoritos grandes
FAV_GRANDE = 7.0                              # |spread| ≥ 7
MAX_COMPRA = 4.5                              # puntos comprados como máximo
MAX_COMPRAS_FAV, MAX_COMPRAS_DOG = 3, 1         # líneas con puntos comprados que se muestran por lado
CENTAVOS_MEDIO_PUNTO = 10                     # ESTIMACIÓN de BetOnline (H47, 2 boletos); P7-bis la reemplaza (semana.ini)
PRESUPUESTO_OMISION = 66.0                    # D7: USD por semana mientras Ozz no diga el monto
TOPE_PAGO = 150_000.0                         # tope de pago de BetOnline en parlays
COLS_PBP = ["game_id", "play_id", "season_type", "week", "posteam", "defteam", "home_team", "away_team", "pass", "rush",
            "epa", "success", "yards_gained", "sack", "interception", "fumble", "fumble_lost", "fumble_out_of_bounds",
            "fumbled_1_team", "fumble_recovery_1_team", "third_down_converted", "third_down_failed", "fixed_drive",
            "fixed_drive_result", "yardline_100", "special_teams_play", "field_goal_attempt", "field_goal_result",
            "kick_distance", "penalty", "penalty_team", "penalty_yards", "home_score", "away_score", "punt_attempt",
            "return_yards", "touchback", "punt_blocked"]
TG_PAUSA_S = 1.1
TG_PLAZO_S = 60


# --------------------------------------------------------------------------------------------------------------------
# textos chicos
# --------------------------------------------------------------------------------------------------------------------
def coma(x, n=1):
    return f"{x:.{n}f}".replace(".", ",")


def num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) or math.isinf(v) else v


def pct(x, n=1):
    return "—" if x is None else f"{coma(100 * x, n)} %"


def ev_t(x):
    """EV en % con un decimal, redondeado HACIA ABAJO (−2,04 % se ve −2,1 %): así lo que se ve coincide con la marca."""
    if x is None:
        return "—"
    v = math.floor(1000 * x + 1e-9) / 10
    return ("+" if v > 0 else "−" if v < 0 else "") + coma(abs(v), 1) + " %"


def am(D):
    """Cuota americana con signo menos tipográfico: −175, +153."""
    if D is None or D <= 1.0:
        return "—"
    return f"+{(D - 1) * 100:.0f}" if D >= 2 else f"−{100 / (D - 1):.0f}"


def am_tope(D):
    """Precio tope en americana redondeado hacia el lado seguro: pagar exactamente lo que se ve cumple EV ≥ −2 %."""
    if D is None or D <= 1.0:
        return "—"
    return f"+{math.ceil((D - 1) * 100 - 1e-9):.0f}" if D >= 2 else f"−{math.floor(100 / (D - 1) + 1e-9):.0f}"


def dec_de_am(a):
    a = float(a)
    return 1 + (a / 100 if a > 0 else 100 / -a)


def linea_t(h):
    """Hándicap del lado: −6,5 / +3 / PK."""
    if h is None:
        return "—"
    if abs(h) < 1e-9:
        return "PK"
    s = coma(abs(h), 1).replace(",0", "")
    return ("+" if h > 0 else "−") + s


def valor_t(clave, v):
    if v is None:
        return "—"
    forma = NOMBRES.get(clave, ("", "dec1"))[1]
    if forma == "epa":
        return ("+" if v >= 0 else "−") + coma(abs(v), 2)
    if forma == "pct":
        return f"{coma(100 * v, 0)} %"
    if forma == "sdec1":
        return ("+" if v >= 0 else "−") + coma(abs(v), 1)
    if forma == "ent":
        return f"{v:.0f}"
    return coma(v, 1)


def tier(k):
    if k is None:
        return ("⚪", "#5f5e5a")
    return TIER[min(3, max(0, int((k - 1) // 8)))]


def marca_estab(clave):
    r = ESTABILIDAD.get(clave)
    if r is None:
        return ""
    return "🔁" if r >= 0.40 else ("〰️" if r >= 0.25 else "🎲")


def estab_txt(clave):
    r = ESTABILIDAD.get(clave)
    if r is None:
        return ""
    return "se repite" if r >= 0.40 else ("a medias" if r >= 0.25 else "casi suerte")


def h(x):
    return html.escape(str(x), quote=False)


def md5_estabilidad():
    return hashlib.md5(json.dumps(ESTABILIDAD, sort_keys=True).encode()).hexdigest()


# --------------------------------------------------------------------------------------------------------------------
# métricas de equipo (port en polars de la medición del 31-oct; mismas definiciones que H44)
# --------------------------------------------------------------------------------------------------------------------
def leer_pbp(S):
    """Jugada por jugada de 2026 con las columnas de las métricas (la misma copia que baja semana.py)."""
    import polars as pl
    S.pbp_temporada()
    ruta = S.DATOS / f"pbp_{S.TEMPORADA}.parquet"
    if not ruta.exists():
        return None
    esquema = pl.read_parquet_schema(ruta)
    return pl.read_parquet(ruta, columns=[c for c in COLS_PBP if c in esquema])


def metricas_equipos(p):
    """{equipo: {clave: valor}} y {equipo: {clave: puesto 1-32}} con la temporada regular de p (polars)."""
    import polars as pl
    for c in COLS_PBP:
        if c not in p.columns:
            p = p.with_columns(pl.lit(None).alias(c))
    p = p.filter(pl.col("season_type") == "REG")
    num_cols = ["pass", "rush", "epa", "success", "yards_gained", "sack", "interception", "fumble", "fumble_lost",
                "fumble_out_of_bounds", "third_down_converted", "third_down_failed", "fixed_drive", "yardline_100",
                "special_teams_play", "field_goal_attempt", "kick_distance", "penalty", "penalty_yards", "home_score",
                "away_score", "punt_attempt", "return_yards", "touchback", "punt_blocked"]
    p = p.with_columns([pl.col(c).cast(pl.Float64, strict=False) for c in num_cols])
    uno = lambda c: pl.col(c).fill_null(0) == 1  # noqa: E731
    equipos = sorted(set(p["home_team"].drop_nulls().to_list()) | set(p["away_team"].drop_nulls().to_list()))
    out = {t: {} for t in equipos}

    def poner(df, clave_eq, col, nombre):
        for t, v in zip(df[clave_eq].to_list(), df[col].to_list()):
            if t in out:
                out[t][nombre] = num(v)

    g = p.group_by("game_id").agg(pl.col("home_team").drop_nulls().first().alias("home"),
                                  pl.col("away_team").drop_nulls().first().alias("away"),
                                  pl.col("home_score").max().alias("hs"), pl.col("away_score").max().alias("as_"))
    pj, pf, pc = {t: 0 for t in equipos}, {t: 0.0 for t in equipos}, {t: 0.0 for t in equipos}
    for _, ho, aw, hs, as_ in g.iter_rows():
        for t, a, b in ((ho, hs, as_), (aw, as_, hs)):
            if t in pj:
                pj[t] += 1
                pf[t] += a or 0.0
                pc[t] += b or 0.0
    for t in equipos:
        out[t]["pj"] = pj[t]
        out[t]["pts_f"] = pf[t] / pj[t] if pj[t] else None
        out[t]["pts_c"] = pc[t] / pj[t] if pj[t] else None

    jug = p.filter((uno("pass") | uno("rush")) & pl.col("epa").is_not_null())
    expl = ((uno("pass") & (pl.col("yards_gained") >= 20).fill_null(False))
            | (uno("rush") & (pl.col("yards_gained") >= 10).fill_null(False)))
    t3 = p.filter(uno("third_down_converted") | uno("third_down_failed"))
    dr = (p.filter(pl.col("posteam").is_not_null() & pl.col("fixed_drive").is_not_null())
          .group_by(["game_id", "fixed_drive", "posteam"], maintain_order=True)
          .agg(pl.col("defteam").drop_nulls().first().alias("defteam"), pl.col("yardline_100").min().alias("miny"),
               pl.col("fixed_drive_result").drop_nulls().first().alias("res"),
               pl.col("yardline_100").drop_nulls().first().alias("start")))
    rz = dr.filter(pl.col("miny") <= 20).with_columns((pl.col("res") == "Touchdown").fill_null(False).alias("td"))
    for lado, k in (("of", "posteam"), ("de", "defteam")):
        a = (jug.filter(pl.col(k).is_not_null()).with_columns(expl.alias("ex"))
             .group_by(k).agg(pl.col("epa").mean().alias("epa"), pl.col("success").mean().alias("exito"),
                              pl.col("ex").cast(pl.Float64).mean().alias("explos")))
        for col in ("epa", "exito", "explos"):
            poner(a, k, col, f"{col}_{lado}")
        b = jug.filter(uno("pass") & pl.col(k).is_not_null()).group_by(k).agg(
            pl.col("epa").mean().alias("e"), pl.col("sack").mean().alias("s"))
        poner(b, k, "e", f"epa_pase_{lado}")
        poner(b, k, "s", f"sack_{lado}")
        c = jug.filter(uno("rush") & pl.col(k).is_not_null()).group_by(k).agg(pl.col("epa").mean().alias("e"))
        poner(c, k, "e", f"epa_corr_{lado}")
        d = t3.filter(pl.col(k).is_not_null()).group_by(k).agg(pl.col("third_down_converted").mean().alias("x"))
        poner(d, k, "x", f"3er_{lado}")
        e = rz.filter(pl.col(k).is_not_null()).group_by(k).agg(pl.col("td").cast(pl.Float64).mean().alias("x"))
        poner(e, k, "x", f"zr_td_{lado}")
        f = (dr.filter(pl.col(k).is_not_null()).with_columns((100 - pl.col("start")).alias("ini"))
             .group_by(k).agg(pl.col("ini").mean().alias("x")))
        poner(f, k, "x", f"inicio_{lado}")
    for t in equipos:
        o = out[t]
        o["net_epa"] = (o["epa_of"] - o["epa_de"]) if o.get("epa_of") is not None and o.get("epa_de") is not None else None

    # pérdidas: intercepciones + fumbles perdidos (fumbled_1_team); recuperadas = las del rival en sus partidos
    ints = p.filter(uno("interception"))
    fl = p.filter(uno("fumble_lost") & pl.col("fumbled_1_team").is_not_null())
    cuenta = lambda df, col: {t: n for t, n in df.group_by(col).len().iter_rows() if t is not None}  # noqa: E731
    da_i, da_f, rec_i = cuenta(ints, "posteam"), cuenta(fl, "fumbled_1_team"), cuenta(ints, "defteam")
    fl2 = fl.with_columns(pl.when(pl.col("fumbled_1_team") == pl.col("home_team")).then(pl.col("away_team"))
                          .otherwise(pl.col("home_team")).alias("rec"))
    rec_f = cuenta(fl2, "rec")
    fu = p.filter(uno("fumble") & (pl.col("fumble_out_of_bounds").fill_null(0) != 1)
                  & pl.col("fumble_recovery_1_team").is_not_null())
    tot_f = {}
    for col in ("home_team", "away_team"):
        for t, n in cuenta(fu, col).items():
            tot_f[t] = tot_f.get(t, 0) + n
    rec_fu = cuenta(fu, "fumble_recovery_1_team")
    st = p.filter(uno("special_teams_play") & pl.col("epa").is_not_null())
    st_a = {t: v for t, v in st.group_by("posteam").agg(pl.col("epa").sum()).iter_rows() if t is not None}
    st_c = {t: v for t, v in st.group_by("defteam").agg(pl.col("epa").sum()).iter_rows() if t is not None}
    fg = p.filter(uno("field_goal_attempt")).with_columns(
        (pl.col("field_goal_result") == "made").fill_null(False).cast(pl.Float64).alias("ok"))
    fg_a = {t: (v, n) for t, v, n in fg.group_by("posteam").agg(pl.col("ok").mean(), pl.len()).iter_rows() if t is not None}
    pu = p.filter(uno("punt_attempt") & (pl.col("punt_blocked").fill_null(0) != 1)).with_columns(
        (pl.col("kick_distance").fill_null(0) - pl.col("return_yards").fill_null(0)
         - 20 * pl.col("touchback").fill_null(0)).alias("neto"))
    pu_a = {t: v for t, v in pu.group_by("posteam").agg(pl.col("neto").mean()).iter_rows() if t is not None}
    pe = p.filter(uno("penalty") & pl.col("penalty_team").is_not_null())
    pe_a = {t: (n, y) for t, n, y in pe.group_by("penalty_team").agg(pl.len(), pl.col("penalty_yards").sum()).iter_rows()}
    for t in equipos:
        o, n = out[t], pj[t]
        da = da_i.get(t, 0) + da_f.get(t, 0)
        to = rec_i.get(t, 0) + rec_f.get(t, 0)
        o["entrega_pj"] = da / n if n else None
        o["recupera_pj"] = to / n if n else None
        o["margen_tot"] = to - da
        o["margen_pj"] = (to - da) / n if n else None
        o["fumbles_n"] = tot_f.get(t, 0)
        o["fumbles_recup_pct"] = rec_fu.get(t, 0) / tot_f[t] if tot_f.get(t) else None
        o["st_epa_pj"] = (st_a.get(t, 0.0) - st_c.get(t, 0.0)) / n if n else None
        o["fg_pct"], o["fg_n"] = (fg_a[t][0], fg_a[t][1]) if t in fg_a else (None, 0)
        o["punt_neto"] = num(pu_a.get(t))
        o["castigos_pj"] = pe_a[t][0] / n if t in pe_a and n else None
        o["castigos_yd_pj"] = num(pe_a[t][1]) / n if t in pe_a and n and num(pe_a[t][1]) is not None else None
    return out, puestos(out)


def puestos(vals):
    """Puesto 1-32 de cada métrica (empates con el menor puesto, como rank(method='min'))."""
    rk = {t: {} for t in vals}
    for c, s in SENTIDO.items():
        xs = [(vals[t].get(c), t) for t in vals if vals[t].get(c) is not None]
        orden = sorted(xs, key=lambda x: -x[0] if s else x[0])
        for t in vals:
            v = vals[t].get(c)
            if v is None:
                continue
            mejor = sum(1 for w, _ in orden if (w > v if s else w < v))
            rk[t][c] = mejor + 1
    return rk


# --------------------------------------------------------------------------------------------------------------------
# récord, casa, visita, contra la línea, racha, descanso y QB mezclado
# --------------------------------------------------------------------------------------------------------------------
def resultados_equipos(g26, momento):
    """{equipo: dict(lista=[...], …)} con los juegos de temporada regular de 2026 con resultado antes de 'momento'."""
    import polars as pl
    jug = g26.filter(pl.col("result").is_not_null() & (pl.col("inicio") < momento)
                     & (pl.col("game_type") == "REG")).sort(["inicio", "game_id"])
    out = {}
    for g in jug.iter_rows(named=True):
        res, sl = num(g["result"]), num(g.get("spread_line"))
        neutral = g.get("location") == "Neutral"
        for eq, riv, signo, local in ((g["home_team"], g["away_team"], 1, True), (g["away_team"], g["home_team"], -1, False)):
            m = signo * res
            ats = None if sl is None else (lambda x: 1 if x > 0 else -1 if x < 0 else 0)(signo * (res - sl))
            out.setdefault(eq, []).append(dict(gid=g["game_id"], sem=int(g["week"]), local=None if neutral else local,
                                               margen=m, rival=riv, ats=ats))
    return {eq: resumen_equipo(v) for eq, v in out.items()}


def resumen_equipo(lista):
    def rec(xs):
        g_ = sum(1 for x in xs if x["margen"] > 0)
        p_ = sum(1 for x in xs if x["margen"] < 0)
        e_ = sum(1 for x in xs if x["margen"] == 0)
        return f"{g_}-{p_}" + (f"-{e_}" if e_ else "")
    casa = [x for x in lista if x["local"] is True]
    visita = [x for x in lista if x["local"] is False]
    ats = [x["ats"] for x in lista if x["ats"] is not None]
    letras = ["G" if x["margen"] > 0 else "P" if x["margen"] < 0 else "E" for x in lista]
    racha = 0
    for le in reversed(letras):
        if le != letras[-1]:
            break
        racha += 1
    return dict(lista=lista, n=len(lista), record=rec(lista), casa=rec(casa), visita=rec(visita),
                casa_dif=(sum(x["margen"] for x in casa) / len(casa)) if casa else None,
                visita_dif=(sum(x["margen"] for x in visita) / len(visita)) if visita else None,
                ats=(f"{ats.count(1)}-{ats.count(-1)}" + (f"-{ats.count(0)}" if ats.count(0) else "")) if ats else "—",
                ult5=" ".join(letras[-5:]) or "—", racha=(letras[-1], racha) if letras else None,
                gids=[x["gid"] for x in lista])


def record_de(res, eq):
    return (res.get(eq) or {}).get("record", "0-0")


def racha_txt(r):
    if not r:
        return "sin partidos"
    le, n = r
    verbo = {"G": "ganó", "P": "perdió", "E": "empató"}[le]
    return f"{verbo} {n} seguido{'s' if n > 1 else ''}" if n > 1 else f"{verbo} el último"


def qb_mezclado(eq, qb_proy, res, verdad, nombres):
    """43: partidos del equipo en 2026 con otro QB titular (primer dropback) que el proyectado para este juego."""
    gids = (res.get(eq) or {}).get("gids", [])
    vistos = [(g, verdad.get((g, eq))) for g in gids if verdad.get((g, eq))]
    if not qb_proy or not vistos:
        return None
    otros = [q for _, q in vistos if q != qb_proy]
    if not otros:
        return None
    nom = sorted({nombres.get(q, q) for q in otros})
    return dict(n_otro=len(otros), n=len(vistos), otros=nom, proy=nombres.get(qb_proy, qb_proy))


# --------------------------------------------------------------------------------------------------------------------
# precios: la foto (como el boleto, pero de los juegos que no empezaron), las formas y la regla de 68
# --------------------------------------------------------------------------------------------------------------------
def foto_juegos(S, g26, sem, bot_dir, ahora, ids=None, solo_dias=True):
    """Juegos de la semana que no empezaron (domingo y lunes si solo_dias) con su referencia (Pinnacle de ≤ 3 h o el
    consenso de nflverse) y la última foto de BetOnline de ≤ 12 h. Mismos datos que armar_boleto; no guarda nada."""
    import polars as pl
    jg = [g for g in g26.filter(pl.col("week") == sem).sort(["inicio", "game_id"]).iter_rows(named=True)
          if g.get("inicio") is not None and g["inicio"] > ahora and (ids is None or g["game_id"] in ids)
          and (not solo_dias or S._dia_et(g) in S.DIAS_BOLETO)]
    if not jg:
        return [], []
    lista = [g["game_id"] for g in jg]
    pin = S.lineas_bot(bot_dir, "pinnacle", lista, ahora, S.MAX_EDAD_PIN_H)
    bo = S.lineas_bot(bot_dir, "betonlineag", lista, ahora, S.MAX_EDAD_BO_H)
    juegos, sin_ref = [], []
    for g in jg:
        gid = g["game_id"]
        ref = S.referencia_juego(g, pin.get(gid))
        if ref is None:
            sin_ref.append(gid)
            continue
        b = bo.get(gid)
        bo_d = None if not b else {k: b[k] for k in ("ts", "horas", "ml_local", "ml_visit", "hcp_local",
                                                     "cuota_sp_local", "cuota_sp_visit")}
        juegos.append(dict(game_id=gid, inicio_utc=S.iso(g["inicio"]), local=g["home_team"], visita=g["away_team"],
                           total_nfl=num(g.get("total_line")), ref=ref, bo=bo_d))
    return juegos, sin_ref


def precio_estimado(D_base, medios, centavos):
    """Precio de BetOnline ESTIMADO al comprar 'medios' medios puntos: 'centavos' por medio punto (H47, P7-bis)."""
    a = (D_base - 1) * 100 if D_base >= 2 else -100 / (D_base - 1)
    v = a if a <= -100 else a - 200                     # escala lineal: +110 y −110 están a 20 centavos
    v -= centavos * medios
    a2 = v if v <= -100 else v + 200
    return dec_de_am(a2)


def lineas_compra(h_lado, h_ref_abs, maximo=MAX_COMPRAS_FAV):
    """Líneas con puntos comprados que cruzan un número clave (3, 7, 10; también 6 y 14 si |spread| ≥ 7)."""
    claves = CLAVES_PUNTOS + (CLAVES_GRANDES if h_ref_abs >= FAV_GRANDE - 1e-9 else ())
    out = []
    for k in sorted(set(claves)):
        if h_lado < 0:                                  # favorito: −a → −(k − 0,5) con k ≤ a
            a = -h_lado
            L = -(k - 0.5)
            comprado = a - (k - 0.5)
            if k <= a + 1e-9 and 1e-9 < comprado <= MAX_COMPRA + 1e-9:
                out.append((comprado, L, k))
        else:                                           # no favorito o PK: +a → +(k + 0,5) con k ≥ a
            L = k + 0.5
            comprado = L - h_lado
            if k >= h_lado - 1e-9 and 1e-9 < comprado <= MAX_COMPRA + 1e-9:
                out.append((comprado, L, k))
    out.sort()
    return out[:maximo]


def estado_forma(f):
    """Regla de 68 con el EV exacto (el que se ve va redondeado hacia abajo): ✅ ≥ −2,0 % · ⚠️ −2,0 a −3,0 % · ❌ < −3,0 %. Los puntos
    comprados entran solo si el precio está en el tope o mejor (con precio estimado la marca es orientativa)."""
    ev = f.get("ev")
    if ev is None:
        return "·"
    if f["tipo"] == "COMPRA":
        return "✅" if ev >= EV_BIEN - 1e-9 else "❌"
    return "✅" if ev >= EV_BIEN - 1e-9 else ("⚠️" if ev >= EV_AVISO - 1e-9 else "❌")


def nueva_forma(tipo, eq, es_local, es_fav, linea, p, q, D, est=False, clave=None, comprado=None):
    f = dict(tipo=tipo, equipo=eq, es_local=es_local, fav=es_fav, linea=linea, p=p, q=q, D=D, est=est,
             clave=clave, comprado=comprado)
    f["ev"] = None if D is None or p is None else p * D + q - 1
    f["justo"] = (1 - q) / p if p and p > 0 else None
    f["tope"] = (1 - 0.02 - q) / p if p and p > 0 else None
    f["estado"] = estado_forma(f)
    return f


def formas_juego(S, j, centavos=CENTAVOS_MEDIO_PUNTO):
    """Todas las formas de un juego (ML y spread de los dos lados, y puntos comprados que cruzan un número clave) con
    su probabilidad contra la referencia, EV contra el precio de BetOnline, precio justo y tope (costo 2 %)."""
    r, b = j["ref"], j.get("bo") or {}
    p_loc = S.sin_vig_potencia(r["ml_local"], r["ml_visit"])
    p_sp = (S.sin_vig_potencia(r["sp_local"], r["sp_visit"])
            if r.get("sp_local") is not None and r.get("sp_visit") is not None else None)
    M = S.Margen(r["hcp_local"], p_sp)
    fav_local = p_loc > 0.5 or (abs(p_loc - 0.5) < 1e-12 and r["hcp_local"] <= 0)
    formas = []
    for es_local in (fav_local, not fav_local):
        eq = j["local"] if es_local else j["visita"]
        es_fav = es_local == fav_local
        p = p_loc if es_local else 1 - p_loc
        ml = b.get("ml_local" if es_local else "ml_visit")
        formas.append(nueva_forma("ML", eq, es_local, es_fav, None, p, 0.0, None if ml is None else dec_de_am(ml)))
        hb, cs = b.get("hcp_local"), b.get("cuota_sp_local" if es_local else "cuota_sp_visit")
        if hb is not None:
            base_h = hb if es_local else -hb
            pw, pq = M.lado(es_local, base_h)
            base_D = None if cs is None else dec_de_am(cs)
            formas.append(nueva_forma("SP", eq, es_local, es_fav, base_h, pw, pq, base_D))
        else:
            base_h = r["hcp_local"] if es_local else -r["hcp_local"]
            base_D = None
        for comprado, L, k in lineas_compra(base_h, abs(r["hcp_local"]), MAX_COMPRAS_FAV if es_fav else MAX_COMPRAS_DOG):
            pw, pq = M.lado(es_local, L)
            D_est = precio_estimado(base_D if base_D else dec_de_am(-110), round(comprado / 0.5), centavos)
            formas.append(nueva_forma("COMPRA", eq, es_local, es_fav, L, pw, pq, D_est, est=True, clave=k, comprado=comprado))
    fav = j["local"] if fav_local else j["visita"]
    return dict(formas=formas, p_local=p_loc, fav=fav, fav_local=fav_local, M_n=M.n, ref_fuente=r.get("fuente"),
                ref_horas=r.get("horas"), bo_horas=b.get("horas"), hcp_ref=r["hcp_local"], bo_hcp=b.get("hcp_local"))


def forma_txt(f, corto=False):
    if f["tipo"] == "ML":
        base = f"{f['equipo']} ML"
    else:
        base = f"{f['equipo']} {linea_t(f['linea'])}"
    precio = am(f["D"]) + (" est." if f["est"] else "") if f["D"] else "sin precio"
    return base if corto else f"{base} {precio}"


def p_leg(f):
    return f["p"] + f["q"]


def elegir(formas, con_compras=False):
    """D6 = c: la forma más probable que pasa la regla (✅; si no hay, ⚠️; si tampoco, la más barata, que queda ❌) y la
    más barata (mayor EV). Nunca dos patas del mismo partido: una forma por juego. Los puntos comprados quedan fuera del
    boleto automático mientras su precio sea una estimación (semana.ini [matriz] compras_en_boleto = no): se muestran
    aparte con su precio tope, para compararlo con el boleto de BetOnline."""
    con_precio = [f for f in formas if f["ev"] is not None and (con_compras or f["tipo"] != "COMPRA")]
    if not con_precio:
        return None, None
    barata = max(con_precio, key=lambda f: (f["ev"], p_leg(f)))
    ok = [f for f in con_precio if f["estado"] == "✅"]
    medio = [f for f in con_precio if f["estado"] == "⚠️" and f["tipo"] != "COMPRA"]
    sug = max(ok or medio, key=lambda f: (p_leg(f), f["ev"])) if (ok or medio) else barata
    return sug, barata


def boleto(patas, monto):
    """Parlay de patas independientes: P(cobrar), pago, EV y costo esperado en USD (con el tope de pago)."""
    if not patas or any(f is None or f.get("D") is None for f in patas):
        return None
    P = R = D = 1.0
    for f in patas:
        P *= p_leg(f)
        R *= f["p"] * f["D"] + f["q"]
        D *= f["D"]
    pago = monto * D
    tope = pago > TOPE_PAGO
    ev = (ev_con_tope(patas, monto) if tope else R - 1)
    return dict(n=len(patas), p=P, D=D, pago=min(pago, TOPE_PAGO), ev=ev, costo=-ev * monto, tope=tope,
                ok=sum(1 for f in patas if f["estado"] == "✅"), aviso=sum(1 for f in patas if f["estado"] == "⚠️"),
                mal=sum(1 for f in patas if f["estado"] == "❌"))


def ev_con_tope(patas, monto):
    """EV exacto con el tope de pago: recorre las combinaciones de patas empatadas (una pata empatada sale del parlay),
    como ev_parlay_tope de parlay.py. Con más de 14 patas con empate, el empate se cuenta como ganada (aproximación)."""
    cap = TOPE_PAGO / monto
    con_push = [i for i, f in enumerate(patas) if f["q"] > 0]
    aprox = len(con_push) > 14
    if aprox:
        con_push = []
    p0 = d0 = 1.0
    for i, f in enumerate(patas):
        if i not in con_push:
            p0 *= (f["p"] + f["q"]) if aprox else f["p"]
            d0 *= f["D"]
    R = 0.0
    for mascara in range(1 << len(con_push)):
        p, d = p0, d0
        for j, i in enumerate(con_push):
            if mascara >> j & 1:
                p *= patas[i]["q"]
            else:
                p *= patas[i]["p"]
                d *= patas[i]["D"]
        R += p * min(d, cap)
    return R - 1


def uno_de(p):
    if not p:
        return "—"
    x = 1 / p
    return f"1 de cada {coma(x, 1)}" if x < 10 else "1 de cada " + f"{round(x):,}".replace(",", ".")


# --------------------------------------------------------------------------------------------------------------------
# configuración: presupuesto (D7) y centavos por medio punto (P7-bis)
# --------------------------------------------------------------------------------------------------------------------
def dir_matriz(S):
    return S.SAL / "matriz"


def config_matriz(S):
    c = configparser.ConfigParser()
    try:
        c.read(S.CONFIG, encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    sec = c["matriz"] if c.has_section("matriz") else {}
    pres = num(sec.get("presupuesto_usd", "")) if sec else None
    cent = num(sec.get("centavos_medio_punto", "")) if sec else None
    si = lambda k, d: str(sec.get(k, d)).strip().lower() in ("si", "sí", "1", "true", "yes") if sec else d == "si"  # noqa: E731
    return dict(presupuesto_ini=pres, centavos=cent if cent is not None and 0 <= cent <= 50 else CENTAVOS_MEDIO_PUNTO,
                activo=si("activo", "si"), con_compras=si("compras_en_boleto", "no"),
                centavos_medidos=cent is not None)


def presupuesto(S):
    """(USD, de dónde sale): /presupuesto N (presupuesto.json) > semana.ini [matriz] presupuesto_usd > 66."""
    try:
        d = json.loads((dir_matriz(S) / "presupuesto.json").read_text(encoding="utf-8"))
        v = num(d.get("usd"))
        if v is not None and 1 <= v <= 5000:
            return v, f"/presupuesto del {d.get('fecha', '?')}"
    except Exception:  # noqa: BLE001
        pass
    v = config_matriz(S)["presupuesto_ini"]
    if v is not None and 1 <= v <= 5000:
        return v, "semana.ini"
    return PRESUPUESTO_OMISION, "por omisión: falta el monto de D7"


def fijar_presupuesto(S, valor, ahora):
    v = num(valor)
    if v is None or not 1 <= v <= 5000:
        return f"Monto no válido: {valor}. Usa un número entre 1 y 5000 (USD por semana), por ejemplo /presupuesto 66."
    d = dir_matriz(S)
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / "presupuesto.json.tmp"
    tmp.write_text(json.dumps({"usd": round(v, 2), "fecha": ahora.astimezone(S.CARACAS).strftime("%d-%m-%Y %H:%M"),
                               "ts": S.iso(ahora)}, ensure_ascii=False), encoding="utf-8")
    tmp.replace(d / "presupuesto.json")
    S.log(f"Matriz: presupuesto semanal fijado en USD {v:.2f} (/presupuesto)")
    return f"Listo: presupuesto semanal USD {coma(v, 2).replace(',00', '')}. La matriz lo usa desde ahora (costo esperado y pago)."


# --------------------------------------------------------------------------------------------------------------------
# datos de la semana y de cada partido
# --------------------------------------------------------------------------------------------------------------------
class Semana:
    """Todo lo que el código calcula sin costo para una semana: métricas, récords, proyecciones, verdad del QB, vigía."""

    def __init__(self, S, g26, sem, momento, ahora, bot_dir):
        self.S, self.g26, self.sem, self.momento, self.ahora, self.bot_dir = S, g26, sem, momento, ahora, bot_dir
        self.cfg = config_matriz(S)
        self.avisos = []
        self.vals, self.rk, self.sem_pbp = {}, {}, None
        try:
            p = leer_pbp(S)
            if p is not None and p.height:
                self.vals, self.rk = metricas_equipos(p)
                ws = [w for w in p["week"].drop_nulls().to_list()] if "week" in p.columns else []
                self.sem_pbp = int(max(ws)) if ws else None
        except Exception as e:  # noqa: BLE001
            self.avisos.append(f"métricas: {type(e).__name__}")
        self.res = resultados_equipos(g26, momento)
        self.proy = self._seguro(lambda: S.ultimas_proyecciones(sem), {}, "proyecciones")
        self.verdad = self._seguro(lambda: S.verdad_qb(), {}, "verdad del QB")
        self.nombres = self._seguro(lambda: S.nombres_de_qb(g26, S.leer_roster()), {}, "nombres de QB")
        self.vigia = self._seguro(lambda: S.vigia_avisos_semana(sem), {}, "vigía")
        self.marcador = self._seguro(lambda: marcador_maquina(S, g26, momento), None, "marcador de la máquina")

    def _seguro(self, fn, defecto, nombre):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            self.avisos.append(f"{nombre}: {type(e).__name__}")
            return defecto


def marcador_maquina(S, g26, momento):
    """Máquina 2026 (descriptivo): la última proyección T−85 de cada juego jugado contra el cierre de nflverse."""
    import polars as pl
    reg = S.leer_registro()
    if reg.height == 0:
        return None
    reg = reg.filter(pl.col("tipo") == "t85").sort("corrida_utc")
    ult = {}
    for r in reg.iter_rows(named=True):
        ult[r["game_id"]] = r
    jug = g26.filter(pl.col("result").is_not_null() & (pl.col("inicio") < momento))
    em, ec, gm, gc, dt_ = [], [], [], [], []
    for g in jug.iter_rows(named=True):
        u = ult.get(g["game_id"])
        if u is None:
            continue
        c = S.cierre_de(g, u)
        if not c or c.get("err_m") is None or c.get("err_c") is None:
            continue
        em.append(c["err_m"])
        ec.append(c["err_c"])
        if c.get("gan_m") is not None:
            gm.append(c["gan_m"])
        if c.get("gan_c") is not None:
            gc.append(c["gan_c"])
        t, tot = num(u.get("total")), num(g.get("total"))
        if t is not None and tot is not None:
            dt_.append(t - tot)
    if not em:
        return None
    semanas = sorted({int(g["week"]) for g in jug.iter_rows(named=True) if g["game_id"] in ult})
    return dict(n=len(em), err_m=sum(em) / len(em), err_c=sum(ec) / len(ec), gan_m=sum(gm) / len(gm) if gm else None,
                n_gm=len(gm), gan_c=sum(gc) / len(gc) if gc else None, n_gc=len(gc),
                sesgo_total=sum(dt_) / len(dt_) if dt_ else None, n_t=len(dt_), semanas=(semanas[0], semanas[-1]))


def alertas_juego(W, gid, u, clima_j, ia_j, local, visita):
    """⏳ (68): QB dudoso, bajas sin confirmar, clima notable o aviso del vigía (🔎)."""
    al = []
    if u and W.S.es_dudoso(u):
        al.append("QB dudoso")
    for lado, eq in (("v", visita), ("l", local)):
        for b in ((ia_j or {}).get(lado) or {}).get("bajas") or []:
            if b.get("estado") in ("questionable", "doubtful") and str(b.get("pos", "")).upper() == "QB":
                al.append(f"QB de {eq} en duda ({b.get('nombre', '')}, {b.get('estado')})")
    if clima_j and str(clima_j.get("notable")) in ("1", "True", "true"):
        al.append("clima notable")
    for eq, lista in sorted((W.vigia.get(gid) or {}).items()):
        if any(a.get("qb") for a in lista):
            al.append(f"🔎 vigía: {eq} sin el QB proyectado")
        elif lista:
            al.append(f"🔎 vigía: {eq} con {len(lista)} titular{'es' if len(lista) > 1 else ''} fuera")
    return al


def maquina(W, u, local, visita, bo_hcp):
    """La máquina (s2-v1, en prueba): gana, margen, total, contra el spread de BetOnline y la señal 29A."""
    if not u or u.get("tipo") == "retro" or num(u.get("p_local")) is None:
        return None
    p, m, t = num(u.get("p_local")), num(u.get("margen")), num(u.get("total"))
    gana = local if p >= 0.5 else visita
    pg = p if p >= 0.5 else 1 - p
    hb = bo_hcp if bo_hcp is not None else num(u.get("bo_hcp_local"))
    cubre = None
    if hb is not None and m is not None:
        x = m + hb
        cubre = ("empate", None) if abs(x) < 1e-9 else ((local, hb) if x > 0 else (visita, -hb))
    sen = []
    for k, mer in (("sel_ml", "ML"), ("sel_sp", "spread")):
        v = u.get(k)
        if v in ("local", "visita"):
            sen.append(f"{mer} {local if v == 'local' else visita}")
    return dict(gana=gana, p=pg, margen=m, total=t, cubre=cubre, hb=hb, senal=sen, estado=u.get("sel_estado") or "",
                fuera=bool(W.S.fuera(u)), dudoso=bool(W.S.es_dudoso(u)), corrida=u.get("corrida_utc"), tipo=u.get("tipo"))


def contexto(W, g, j, clima_j, ia_j):
    """Todo lo de un partido para el texto, la tarjeta y la matriz."""
    gid, loc, vis = g["game_id"], g["home_team"], g["away_team"]
    u = W.proy.get(gid)
    F = formas_juego(W.S, j, W.cfg["centavos"]) if j else None
    rest = {loc: num(g.get("home_rest")), vis: num(g.get("away_rest"))}
    qbp = {loc: (u or {}).get("qb_local_id") or g.get("home_qb_id"), vis: (u or {}).get("qb_visita_id") or g.get("away_qb_id")}
    ctx = dict(gid=gid, local=loc, visita=vis, inicio=g["inicio"], neutral=g.get("location") == "Neutral",
               estadio=g.get("stadium") or "", roof=g.get("roof") or "", j=j, F=F, u=u, clima=clima_j, ia=ia_j or {},
               rest=rest, total_nfl=num(g.get("total_line")),
               maquina=maquina(W, u, loc, vis, (j or {}).get("bo", {}).get("hcp_local") if j and j.get("bo") else None),
               qb={t: qb_mezclado(t, qbp[t], W.res, W.verdad, W.nombres) for t in (vis, loc)},
               alertas=alertas_juego(W, gid, u, clima_j, ia_j, loc, vis))
    if F:
        ctx["sug"], ctx["barata"] = elegir(F["formas"], W.cfg["con_compras"])
        ctx["ml_fav"] = next((f for f in F["formas"] if f["tipo"] == "ML" and f["fav"]), None)
    return ctx


def m_eq(W, eq, clave):
    """(valor, puesto) de una métrica de un equipo."""
    return (W.vals.get(eq) or {}).get(clave), (W.rk.get(eq) or {}).get(clave)


def celda(W, eq, clave, con_marca=False):
    v, k = m_eq(W, eq, clave)
    if v is None:
        return "—"
    return f"{tier(k)[0]}#{k} {valor_t(clave, v)}" + (f" {marca_estab(clave)}" if con_marca else "")


# --------------------------------------------------------------------------------------------------------------------
# textos (HTML de Telegram)
# --------------------------------------------------------------------------------------------------------------------
CHOQUE = [("EPA por jugada", "epa"), ("Pase", "epa_pase"), ("Corrida", "epa_corr"), ("Explosivas", "explos"),
          ("3.er down", "3er"), ("Zona roja (TD)", "zr_td")]
PERDIDAS = [("entrega", "entrega_pj"), ("recupera", "recupera_pj"), ("margen", "margen_pj"),
            ("fumbles recuperados", "fumbles_recup_pct")]
ESPECIALES = [("equipos especiales", "st_epa_pj"), ("goles de campo", "fg_pct"), ("despeje neto", "punt_neto"),
              ("castigos", "castigos_pj")]


def cuando(S, t):
    return S.cuando_txt(t)


def clima_txt(c):
    """Una línea del clima para mostrar (clima.py mostrar: NWS y Open-Meteo; no escribe el registro de #9)."""
    cl = c.get("clima")
    roof = c.get("roof") or ""
    techo = {"dome": "domo", "closed": "techo cerrado", "open": "techo abierto", "outdoors": "al aire libre"}.get(roof, roof)
    if not cl:
        if roof in ("dome", "closed"):
            return f"{c['estadio']} ({techo}): bajo techo."
        return f"{c['estadio']} ({techo or 'sin dato del techo'}): sin pronóstico (no hubo consulta)."
    if cl.get("estado") not in (None, "ok"):
        return f"{c['estadio']} ({techo}): sin pronóstico ({cl.get('estado')})."
    if str(cl.get("al_aire_libre")) not in ("1", "True", "true"):
        return f"{c['estadio']} ({techo or 'techado'}): bajo techo."
    if not cl.get("fuente_decide"):
        return f"{c['estadio']} ({techo}): sin pronóstico (NWS y Open-Meteo no respondieron)."
    partes = []
    if num(cl.get("temp_c")) is not None:
        partes.append(f"{coma(num(cl['temp_c']), 0)} °C")
    if num(cl.get("viento_decide")) is not None:
        partes.append(f"viento {coma(num(cl['viento_decide']), 0)} mph" + (f" {cl['direccion']}" if cl.get("direccion") else ""))
    if num(cl.get("prob_lluvia")) is not None:
        partes.append(f"lluvia {coma(num(cl['prob_lluvia']), 0)} %")
    fuente = {"nws": "NWS", "openmeteo": "Open-Meteo"}.get(cl.get("fuente_decide"), "")
    nota = " · ⚠️ notable" if str(cl.get("notable")) in ("1", "True", "true") else ""
    return f"{c['estadio']} ({techo}): " + (", ".join(partes) or "sin datos") + (f" ({fuente})" if fuente else "") + nota


def precios_txt(c):
    """Bloque de precios: Pinnacle sin vig contra BetOnline, tope y la más barata."""
    F = c.get("F")
    if not F:
        return ["<b>💵 Precios</b>: sin referencia (no hay Pinnacle de ≤ 3 h ni consenso de nflverse)."]
    fo = F["formas"]
    p_l = F["p_local"]
    lin = ["<b>💵 Precios</b> (Pinnacle sin vig contra BetOnline)",
           f"Gana: {h(c['visita'])} {pct(1 - p_l)} (justa {am(1 / (1 - p_l))}) · {h(c['local'])} {pct(p_l)} (justa {am(1 / p_l)})"]
    for tipo, nombre in (("ML", "ML"), ("SP", "Spread")):
        partes = []
        for f in [x for x in fo if x["tipo"] == tipo]:
            if f["D"] is None:
                partes.append(f"{h(f['equipo'])}{' ' + linea_t(f['linea']) if tipo == 'SP' else ''} sin precio")
                continue
            cub = f" · cubre {pct(f['p'])}" + (f" + empate {pct(f['q'])}" if f["q"] > 0.0005 else "") if tipo == "SP" else ""
            partes.append(f"{h(f['equipo'])}{' ' + linea_t(f['linea']) if tipo == 'SP' else ''} {am(f['D'])}{cub} · EV "
                          f"{ev_t(f['ev'])} {f['estado']} (tope {am_tope(f['tope'])})")
        if partes:
            lin.append(f"{nombre}: " + " | ".join(partes))
        elif tipo == "SP":
            lin.append("Spread: BetOnline sin línea en la foto.")
    compras = [x for x in fo if x["tipo"] == "COMPRA"]
    if compras:
        lin.append("Comprar puntos (cruzan un número clave; entra si el boleto paga el tope o mejor): " + " | ".join(
            f"{h(f['equipo'])} {linea_t(f['linea'])} cubre {pct(f['p'])}" + (f" + empate {pct(f['q'])}" if f["q"] > 0.0005 else "")
            + f" · justa {am(f['justo'])} · tope {am_tope(f['tope'])}" for f in compras))
    sug, bar = c.get("sug"), c.get("barata")
    if bar:
        lin.append(f"Más barata: {h(forma_txt(bar))} (EV {ev_t(bar['ev'])} {bar['estado']}) · más probable que pasa la regla: "
                   f"{h(forma_txt(sug))} ({pct(p_leg(sug))})")
    ref = (f"Pinnacle de hace {coma(F['ref_horas'], 1)} h" if F["ref_fuente"] == "pinnacle" and F["ref_horas"] is not None
           else "consenso de nflverse (no hay Pinnacle de ≤ 3 h)")
    lin.append(f"<i>Referencia: {ref}" + (f" · BetOnline de hace {coma(F['bo_horas'], 1)} h" if F.get("bo_horas") is not None
                                          else " · sin foto de BetOnline de ≤ 12 h") + "</i>")
    return lin


def maquina_txt(c):
    mq = c.get("maquina")
    if not mq:
        return ["<b>🤖 La máquina</b>: sin proyección hacia adelante todavía (sale el miércoles, el sábado y en la T−85)."]
    if mq["fuera"]:
        motivo = "QB dudoso" if mq["dudoso"] else "difiere mucho del mercado"
        return [f"<b>🤖 La máquina</b>: «Fuera» ({motivo}): no hacerle caso en este partido."]
    cub = ""
    if mq["cubre"]:
        eq, hh = mq["cubre"]
        cub = " · con el spread de BetOnline: empate" if eq == "empate" else f" · con el spread de BetOnline cubre {h(eq)} {linea_t(hh)}"
    lin = ["<b>🤖 La máquina</b> (en prueba, 31A: no se apuesta por ella)",
           f"{h(mq['gana'])} gana {pct(mq['p'], 0)} (justa {am(1 / mq['p'])}) · margen {h(c['local'])} "
           f"{'+' if (mq['margen'] or 0) >= 0 else '−'}{coma(abs(mq['margen'] or 0), 1)} · total {coma(mq['total'] or 0, 1)}{cub}"]
    lin.append("Señal 29A (registro, sin dinero): " + (", ".join(mq["senal"]) + (f" ({h(mq['estado'])})" if mq["estado"] else "")
                                                       if mq["senal"] else "ninguna"))
    return lin


def record_txt(W, c):
    lin = ["<b>📊 Récord, casa, visita y racha</b>"]
    for eq in (c["visita"], c["local"]):
        r = W.res.get(eq)
        if not r:
            lin.append(f"{h(eq)}: sin partidos jugados.")
            continue
        dif = lambda x: "" if x is None else f" ({'+' if x >= 0 else '−'}{coma(abs(x), 1)})"  # noqa: E731
        d = c["rest"].get(eq)
        desc = "" if d is None else f" · descanso {d:.0f} días" + (" (viene de la semana libre)" if d >= 13 else "")
        lin.append(f"{h(eq)}: {r['record']} · casa {r['casa']}{dif(r['casa_dif'])} · visita {r['visita']}{dif(r['visita_dif'])}"
                   f" · contra la línea {r['ats']} · últimos 5: {r['ult5']} · {racha_txt(r['racha'])}{desc}")
    lin.append("<i>Casa y visita de cada equipo: casi suerte (H45). Las rachas ya están en la línea (H46).</i>")
    return lin


def choque_txt(W, c):
    lin = []
    for at, de in ((c["visita"], c["local"]), (c["local"], c["visita"])):
        lin.append(f"<b>⚔️ Cuando ataca {h(at)}</b> (ataque {h(at)} · defensa {h(de)})")
        for nombre, base in CHOQUE:
            lin.append(f"{nombre} {marca_estab(base + '_of')}: {celda(W, at, base + '_of')} · {celda(W, de, base + '_de')}")
    return lin


def perdidas_txt(W, c):
    lin = ["<b>🔄 Pérdidas de balón</b> (🎲 casi suerte: el mercado no las cobra hacia adelante)"]
    for eq in (c["visita"], c["local"]):
        n = (W.vals.get(eq) or {}).get("fumbles_n")
        lin.append(f"{h(eq)}: " + " · ".join(f"{nom} {celda(W, eq, k)}" for nom, k in PERDIDAS)
                   + (f" (n {n})" if n else ""))
    lin.append("<b>🦶 Equipos especiales y disciplina</b>")
    for eq in (c["visita"], c["local"]):
        lin.append(f"{h(eq)}: " + " · ".join(f"{nom} {celda(W, eq, k, True)}" for nom, k in ESPECIALES))
    for eq in (c["visita"], c["local"]):
        q = c["qb"].get(eq)
        if q:
            lin.append(f"⚠️ QB mezclado ({h(eq)}): {q['n_otro']} de {q['n']} partidos con otro QB ({h(', '.join(q['otros']))}); "
                       f"para este juego se proyecta a {h(q['proy'])}. Los puestos de ataque mezclan los dos.")
    return lin


def prensa_txt(c, estado_ia):
    d = c.get("ia") or {}
    if not d:
        return [f"<b>📰 Prensa y bajas (Opus)</b>: {h(estado_ia)}."] if estado_ia else []
    lin = ["<b>📰 Prensa y bajas (Opus)</b>"]
    for lado, eq in (("v", c["visita"]), ("l", c["local"])):
        e = d.get(lado) or {}
        rk = lambda v: f"#{v}" if v else "—"  # noqa: E731
        bajas = e.get("bajas") or []
        lin.append(f"{h(eq)}: NFL.com {rk(e.get('nflcom'))} · PFT {rk(e.get('pft'))}"
                   + (" · bajas: " + ", ".join(f"{h(b['pos'])} {h(b['nombre'])} ({h(BAJA_ES.get(b['estado'], b['estado']))})"
                                               for b in bajas[:6]) + ("…" if len(bajas) > 6 else "") if bajas else " · sin bajas oficiales"))
    if d.get("opinion"):
        lin.append(f"Lectura: {h(d['opinion'])}")
    if d.get("mirar"):
        lin.append(f"Qué mirar: {h(d['mirar'])}")
    return lin


BAJA_ES = {"out": "out", "doubtful": "doubtful", "injured_reserve": "lista de lesionados", "questionable": "questionable",
           "suspended": "suspendido"}


def texto_juego(W, c, estado_ia=""):
    S = W.S
    cab = (f"<b>🏈 {h(S.apodo(c['visita']))} ({record_de(W.res, c['visita'])}) {'vs' if c['neutral'] else '@'} "
           f"{h(S.apodo(c['local']))} ({record_de(W.res, c['local'])})</b>")
    lin = [cab, f"{cuando(S, c['inicio'])} Caracas · {h(c['estadio'])}" + (" · sede neutral" if c["neutral"] else "")]
    if c["alertas"]:
        lin.append(f"⏳ <b>Alerta abierta</b>: {h('; '.join(c['alertas']))} → revisar en la T−85.")
    bloques = [precios_txt(c), maquina_txt(c), record_txt(W, c), [f"<b>🌦️ Clima</b>: {h(clima_txt(c))}"],
               choque_txt(W, c), perdidas_txt(W, c), prensa_txt(c, estado_ia)]
    return "\n".join(lin) + "\n\n" + "\n\n".join("\n".join(b) for b in bloques if b)


def portada_txt(W, ctxs, origen, estado_ia, fuentes, costo, clima_res):
    S = W.S
    cuando_ = W.ahora.astimezone(S.CARACAS)
    lin = [f"<b>📋 BRIEFING · semana {W.sem}</b> · {S.DIAS[cuando_.weekday()]} {cuando_.day} {S.MESES[cuando_.month - 1]}"
           + (" (a pedido)" if origen != "sabado" else "") + f" · {len(ctxs)} partido{'s' if len(ctxs) != 1 else ''} por jugar",
           "Descriptivo: el cierre ya incluye todo esto. Cada número lleva su puesto entre 32 (🟢 1-8 · 🟡 9-16 · 🟠 17-24 · "
           "🔴 25-32) y lo que se repite según 2016-2025 (🔁 se repite · 〰️ a medias · 🎲 casi suerte, H44)."]
    if W.vals:
        orden = sorted((t for t in W.vals if W.vals[t].get("net_epa") is not None), key=lambda t: -W.vals[t]["net_epa"])
        fila = lambda i, t: f"{i}. {t} {valor_t('net_epa', W.vals[t]['net_epa'])} ({record_de(W.res, t)})"  # noqa: E731
        lin += ["", f"<b>🏆 Mejores y peores por EPA neto por jugada</b> 🔁 (nflverse 2026, semanas 1-{W.sem_pbp or '?'})",
                "Mejores: " + " · ".join(fila(i, t) for i, t in enumerate(orden[:5], 1)),
                "Peores: " + " · ".join(fila(len(orden) - 4 + i, t) for i, t in enumerate(orden[-5:]))]
        ch = choques_desparejos(W, ctxs)
        if ch:
            lin += ["", "<b>⚔️ Choques más desparejos de la semana</b> (ataque contra defensa)"] + [f"· {x}" for x in ch]
        su = rachas_suerte(W, ctxs)
        if su:
            lin += ["", "<b>🎲 Suerte que casi no se repite</b> (H44: el mercado no la cobra hacia adelante)"] + [f"· {x}" for x in su]
    else:
        lin += ["", "Métricas: sin jugada por jugada de nflverse en esta corrida."]
    lin += ["", "<b>🌦️ Clima</b>: " + clima_portada(ctxs, clima_res)]
    mk = W.marcador
    if mk:
        lin += ["", f"<b>🤖 Marcador de la máquina 2026</b> (T−85 contra el cierre de nflverse, semanas {mk['semanas'][0]}-"
                    f"{mk['semanas'][1]}, n {mk['n']})",
                f"Error del margen: máquina {coma(mk['err_m'], 1)} pts · cierre {coma(mk['err_c'], 1)} pts",
                f"Ganadores acertados: máquina {pct(mk['gan_m'], 0)} (n {mk['n_gm']}) · cierre {pct(mk['gan_c'], 0)} (n {mk['n_gc']})"]
        if mk["sesgo_total"] is not None:
            lin.append(f"Total: la máquina se {'pasa' if mk['sesgo_total'] >= 0 else 'queda corta'} por "
                       f"{coma(abs(mk['sesgo_total']), 1)} pts en promedio (n {mk['n_t']})")
        lin.append("<i>En prueba (31A, veredicto en enero de 2027): se muestra para entender, no se apuesta por ella.</i>")
    lin += ["", "Sigue un mensaje por partido (2 imágenes y el texto) y, al final, la matriz de decisión."
            if origen != "equipo" else "Sigue el partido pedido (2 imágenes y el texto)."]
    if estado_ia:
        lin.append(f"Opus (prensa y bajas): {h(estado_ia)}" + (f" · USD {coma(costo, 2)}" if costo else ""))
    if fuentes:
        lin.append("Rankings de la prensa: " + " · ".join(f'<a href="{html.escape(str(v), quote=True)}">{h(k)}</a>' for k, v in sorted(fuentes.items())))
    if W.avisos:
        lin.append(f"<i>Avisos del código: {h('; '.join(W.avisos))}</i>")
    return "\n".join(lin)


def choques_desparejos(W, ctxs, n=4):
    """Los cruces ataque-defensa con más diferencia en EPA de pase o de corrida (suma de los dos desvíos)."""
    import statistics as st
    out = []
    for base, nombre in (("epa_pase", "pase"), ("epa_corr", "corrida")):
        of = [W.vals[t].get(f"{base}_of") for t in W.vals if W.vals[t].get(f"{base}_of") is not None]
        de = [W.vals[t].get(f"{base}_de") for t in W.vals if W.vals[t].get(f"{base}_de") is not None]
        if len(of) < 10 or len(de) < 10:
            continue
        mo, md = st.mean(of), st.mean(de)
        for c in ctxs:
            for at, df in ((c["visita"], c["local"]), (c["local"], c["visita"])):
                a, d = m_eq(W, at, f"{base}_of")[0], m_eq(W, df, f"{base}_de")[0]
                if a is None or d is None:
                    continue
                out.append(((a - mo) + (d - md), at, df, base, nombre))
    out.sort(key=lambda x: -abs(x[0]))
    txt = []
    for v, at, df, base, nombre in out[:n]:
        txt.append(f"{h(at)}: su {nombre} {celda(W, at, base + '_of')} contra la defensa de {nombre} de {h(df)} "
                   f"{celda(W, df, base + '_de')} → {'ventaja de ' + h(at) if v > 0 else 'ventaja de la defensa de ' + h(df)}")
    return txt


def rachas_suerte(W, ctxs, n=5):
    eqs = sorted({c["visita"] for c in ctxs} | {c["local"] for c in ctxs})
    out = []
    for t in eqs:
        v = W.vals.get(t) or {}
        f, nf = v.get("fumbles_recup_pct"), v.get("fumbles_n") or 0
        if f is not None and nf >= 8 and abs(f - 0.5) >= 0.15:
            out.append((abs(f - 0.5) * 4, f"{h(t)} recupera el {pct(f, 0)} de los fumbles de sus partidos (n {nf}); a la larga "
                                          f"es cerca del 50 % (r 0,05)."))
        mg = v.get("margen_pj")
        if mg is not None and abs(mg) >= 1.0:
            out.append((abs(mg), f"{h(t)} lleva un margen de pérdidas de {valor_t('margen_pj', mg)} por partido; se repite poco "
                                 f"(r 0,17)."))
        fg, nfg = v.get("fg_pct"), v.get("fg_n") or 0
        if fg is not None and nfg >= 8 and (fg >= 0.95 or fg <= 0.70):
            out.append((abs(fg - 0.85) * 3, f"{h(t)} anota el {pct(fg, 0)} de sus goles de campo (n {nfg}); casi no se repite "
                                            f"(r 0,11)."))
    out.sort(key=lambda x: -x[0])
    return [x[1] for x in out[:n]]


def clima_portada(ctxs, clima_res):
    if clima_res is None:
        return "sin consulta (clima.py no instalado o apagado)."
    if clima_res.get("estado") not in ("ok",):
        return f"sin pronóstico ({h(clima_res.get('estado') or 'error')})."
    notables = [c for c in ctxs if c.get("clima") and str(c["clima"].get("notable")) in ("1", "True", "true")]
    techo = sum(1 for c in ctxs if c.get("clima") and str(c["clima"].get("al_aire_libre")) not in ("1", "True", "true"))
    txt = ("notable en " + "; ".join(f"{h(c['visita'])} @ {h(c['local'])}: {h(clima_txt(c).split(': ', 1)[-1])}" for c in notables)
           if notables else "nada notable (viento ≥ 15 mph, lluvia ≥ 60 % o bajo 0 °C)")
    return (f"{txt} · {techo} bajo techo. <i>Solo para mostrar: la T−85 lo vuelve a consultar y lo registra (#9). El cierre ya "
            f"descuenta el clima (H31).</i>")


# --------------------------------------------------------------------------------------------------------------------
# matriz de decisión (68): mensaje, archivo y comparación con el sábado
# --------------------------------------------------------------------------------------------------------------------
NOMBRE_MOMENTO = {"sabado": "preliminar del sábado", "final": "final del domingo (después de la T−85 de las 12:35)",
                  "pedido": "a pedido"}


def boletos_matriz(ctxs, monto):
    """Los tres boletos de D6; un partido sin precio de BetOnline para esa forma queda fuera de ese boleto (se dice)."""
    jm = [c for c in ctxs if c.get("F") and c.get("sug")]
    sug = boleto([c["sug"] for c in jm], monto)
    con_ml = [c for c in jm if c.get("ml_fav") and c["ml_fav"]["D"]]
    ml = boleto([c["ml_fav"] for c in con_ml], monto)
    if ml is not None:
        ml["faltan"] = [c["ml_fav"]["equipo"] if c.get("ml_fav") else c["gid"] for c in jm if c not in con_ml]
    bar = boleto([c["barata"] for c in jm], monto)
    return dict(sugerido=sug, todo_ml=ml, todo_barato=bar, n=len(jm))


def usd(x, dec=0):
    t = f"{x:,.{dec}f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return f"USD {t}"


def boleto_txt(nombre, b, monto):
    if not b:
        return f"<b>{nombre}</b>: sin precios de BetOnline."
    falta = b.get("faltan") or []
    return (f"<b>{nombre}</b>{(' (' + str(b['n']) + ' patas: sin ML en BetOnline para ' + ', '.join(falta) + ')') if falta else ''}: "
            f"cobra {uno_de(b['p'])} ({pct(b['p'])}) · paga ×{usd(b['D'])[4:] if b['D'] >= 100 else coma(b['D'], 1)}"
            f" ({usd(b['pago'])}{' con el tope' if b['tope'] else ''}) · EV {ev_t(b['ev'])} · costo esperado "
            f"{usd(b['costo'], 2)} · {b['ok']} ✅ {b['aviso']} ⚠️ {b['mal']} ❌")


def texto_matriz(W, ctxs, momento, monto, fuente_monto, cambios=None, sin_ref=()):
    S = W.S
    jm = [c for c in ctxs if c.get("F")]
    bol = boletos_matriz(jm, monto)
    hora = W.ahora.astimezone(S.CARACAS)
    lin = [f"<b>🧮 MATRIZ DE DECISIÓN · semana {W.sem} · {NOMBRE_MOMENTO.get(momento, momento)}</b>",
           f"Partidos de domingo y lunes que no empezaron · corrida de las {hora:%H:%M} (Caracas) con la última foto del bot "
           f"(Pinnacle de ≤ 3 h y BetOnline de ≤ 12 h; cada partido avisa si no) · presupuesto USD {coma(monto, 0)} "
           f"({h(fuente_monto)}; se cambia con /presupuesto N).",
           "Regla (68, escrita antes): ✅ costo hasta 2 % · ⚠️ 2-3 % · ❌ más de 3 % · ⏳ alerta abierta: revisar en la T−85. Puntos "
           "comprados: solo si cruzan el 3, el 7 o el 10 (6 y 14 en favoritos grandes) y el boleto los paga al tope o mejor. "
           "Nunca dos patas del mismo partido. El costo decide; la máquina y los rankings pesan 0."]
    for i, c in enumerate(jm, 1):
        F, sug, bar = c["F"], c.get("sug"), c.get("barata")
        al = f" ⏳ {h('; '.join(c['alertas']))}" if c["alertas"] else ""
        ref = "" if F["ref_fuente"] == "pinnacle" else " · ref. consenso nflverse"
        if F.get("bo_horas") is not None and F["bo_horas"] > 3:
            ref += f" · BetOnline de hace {coma(F['bo_horas'], 0)} h"
        lin += ["", f"<b>{i} · {h(c['visita'])} @ {h(c['local'])}</b> · {cuando(S, c['inicio'])}{ref}{al}"]
        if not sug:
            lin.append("  Sin precios de BetOnline en la foto.")
            continue
        fs = (f"{sug['estado']} {h(forma_txt(sug))} · {'cubre' if sug['tipo'] != 'ML' else 'gana'} {pct(p_leg(sug))} · "
              f"EV {ev_t(sug['ev'])} (tope {am_tope(sug['tope'])})")
        if sug["estado"] == "❌":
            lin.append(f"  Ninguna forma pasa la regla; la más barata: {fs}")
        elif bar is sug:
            lin.append(f"  Más probable y más barata: {fs}")
        else:
            lin.append(f"  Más probable: {fs}")
            lin.append(f"  Más barata: {bar['estado']} {h(forma_txt(bar))} · {pct(p_leg(bar))} · EV {ev_t(bar['ev'])}")
        compras = [f for f in F["formas"] if f["tipo"] == "COMPRA" and f["fav"]]
        if compras:
            lin.append("  Comprar: " + " · ".join(f"{h(f['equipo'])} {linea_t(f['linea'])} entra si pagan {am_tope(f['tope'])} o mejor "
                                                   f"({pct(p_leg(f))})" for f in compras[:2]))
    if sin_ref:
        lin += ["", f"Sin referencia de precio (fuera de la matriz): {h(', '.join(sin_ref))}."]
    n = bol["n"]
    lin += ["", f"<b>🎟️ Boleto completo: {n} patas (una por partido)</b>",
            boleto_txt("Sugerido (la más probable que pasa la regla; si ninguna pasa, la más barata)", bol["sugerido"], monto),
            boleto_txt("Todo ML de los favoritos", bol["todo_ml"], monto),
            boleto_txt("Todo lo más barato", bol["todo_barato"], monto)]
    if n:
        lin.append(f"<i>Referencia: {n} patas al −2 % cada una dan {ev_t(0.98 ** n - 1)}. Costo esperado = lo que se pierde en "
                   f"promedio con USD {coma(monto, 0)} contra los precios justos de Pinnacle. Patas independientes; el empate "
                   f"del ML cuenta como perdido, como en la hoja.</i>")
    if any(b and b["tope"] for b in (bol["sugerido"], bol["todo_ml"], bol["todo_barato"])):
        lin.append(f"<i>Algún boleto pasa el tope de pago de BetOnline (USD {coma(TOPE_PAGO, 0)}): el EV ya lo descuenta.</i>")
    if not W.cfg["con_compras"]:
        lin.append("<i>Los puntos comprados no entran solos al boleto: su precio en BetOnline todavía es una estimación "
                   "(P7-bis). Compara el tope con tu boleto.</i>")
    if cambios:
        lin += ["", "<b>Cambios desde el sábado</b>"] + [f"· {h(x)}" for x in cambios]
    return "\n".join(lin), bol


def forma_json(f):
    if not f:
        return None
    return {k: (round(v, 5) if isinstance(v, float) else v) for k, v in f.items()}


def guardar_matriz(W, ctxs, momento, monto, bol):
    d = dir_matriz(W.S)
    d.mkdir(parents=True, exist_ok=True)
    nombre = (f"matriz_semana_{W.sem}_{momento}.json" if momento in ("sabado", "final")
              else f"matriz_semana_{W.sem}_pedido_{W.ahora.astimezone(W.S.CARACAS):%Y%m%d_%H%M}.json")
    datos = dict(version=VERSION_BRIEFING, semana=W.sem, momento=momento, corrida_utc=W.S.iso(W.ahora), presupuesto=monto,
                 centavos_medio_punto=W.cfg["centavos"], compras_en_boleto=W.cfg["con_compras"],
                 regla=dict(ev_bien=EV_BIEN, ev_aviso=EV_AVISO, claves=list(CLAVES_PUNTOS), grandes=list(CLAVES_GRANDES)),
                 juegos=[dict(game_id=c["gid"], visita=c["visita"], local=c["local"], inicio_utc=W.S.iso(c["inicio"]),
                              ref=c["F"]["ref_fuente"], alertas=c["alertas"], formas=[forma_json(f) for f in c["F"]["formas"]],
                              sugerida=forma_json(c.get("sug")), barata=forma_json(c.get("barata")),
                              bajas_qb_duda=[a for a in c["alertas"] if a.startswith("QB de")],
                              clima_notable="clima notable" in c["alertas"])
                         for c in ctxs if c.get("F")],
                 boletos={k: v for k, v in bol.items() if k != "n"})
    tmp = d / (nombre + ".tmp")
    tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(d / nombre)
    return d / nombre


def leer_matriz(S, sem, momento):
    try:
        return json.loads((dir_matriz(S) / f"matriz_semana_{sem}_{momento}.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def cambios_desde(previa, ctxs):
    if not previa:
        return []
    ant = {j["game_id"]: j for j in previa.get("juegos", [])}
    out = []
    for c in ctxs:
        a = ant.get(c["gid"])
        if not a or not c.get("sug"):
            continue
        s0, s1 = a.get("sugerida") or {}, c["sug"]
        t0 = f"{s0.get('equipo')} {'ML' if s0.get('tipo') == 'ML' else linea_t(s0.get('linea'))} {s0.get('estado', '')}".strip()
        t1 = f"{s1['equipo']} {'ML' if s1['tipo'] == 'ML' else linea_t(s1['linea'])} {s1['estado']}"
        if t0 != t1:
            out.append(f"{c['visita']} @ {c['local']}: {t0} → {t1}")
        limpio = lambda x: x.replace(" (del sábado)", "")  # noqa: E731
        nuevas = [x for x in c["alertas"] if limpio(x) not in {limpio(y) for y in (a.get("alertas") or [])}]
        if nuevas:
            out.append(f"{c['visita']} @ {c['local']}: alerta nueva ({'; '.join(nuevas)})")
    return out or ["ninguno en la forma sugerida ni en las alertas."]


# --------------------------------------------------------------------------------------------------------------------
# tarjeta a color (2 imágenes por partido; sin emoji: la fuente DejaVu no los tiene)
# --------------------------------------------------------------------------------------------------------------------
COLOR_ESTADO = {"✅": C_BIEN, "⚠️": C_AVISO, "❌": C_MAL, "·": T2}
NOMBRE_ESTADO = {"✅": "pasa", "⚠️": "a medias", "❌": "no pasa", "·": ""}


def _lienzo(W_, H_):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig = plt.figure(figsize=(W_ / 100, H_ / 100), dpi=100)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, W_)
    ax.set_ylim(H_, 0)
    ax.axis("off")
    return plt, fig, ax


def _panel(ax, y, W_, titulo):
    from matplotlib.patches import FancyBboxPatch
    ax.add_patch(FancyBboxPatch((30, y - 24), W_ - 60, 48, boxstyle="round,pad=0,rounding_size=10", fc=PANEL, ec="none"))
    ax.text(48, y, titulo, color=T1, fontsize=18, weight="bold", va="center")
    return y + 50


def _sin_emoji(t):
    return re.sub(r"[\U0001F000-\U0001FFFF☀-➿️]", "", str(t)).strip()


def tarjeta(W, c, rutas):
    """Dos PNG: 1) precios, la máquina, récord y clima; 2) choque, pérdidas y equipos especiales."""
    S = W.S
    A, B_ = c["visita"], c["local"]
    WW, CX, LB = 1080, 540, 175
    nombre = lambda t: S.apodo(t).upper()  # noqa: E731

    # ---------------- imagen 1
    F = c.get("F")
    filas_p = []
    if F:
        pl_ = F["p_local"]
        filas_p.append(("Gana según Pinnacle (justo)", f"{pct(1 - pl_, 0)}  ({am(1 / (1 - pl_))})", T1,
                        f"{pct(pl_, 0)}  ({am(1 / pl_)})", T1))
        for tipo, et in (("ML", "Moneyline BetOnline"), ("SP", "Spread BetOnline")):
            lado = {f["equipo"]: f for f in F["formas"] if f["tipo"] == tipo}
            if not lado:
                continue
            def v(eq):  # noqa: E306
                f = lado.get(eq)
                if not f:
                    return "—", T2
                if f["D"] is None:
                    return (linea_t(f["linea"]) + " " if tipo == "SP" else "") + "sin precio", T2
                return ((linea_t(f["linea"]) + " " if tipo == "SP" else "") + f"{am(f['D'])} · EV {ev_t(f['ev'])}",
                        COLOR_ESTADO[f["estado"]])
            (ta, ca), (tb, cb) = v(A), v(B_)
            filas_p.append((et, ta, ca, tb, cb))
            if tipo == "SP":
                def cub(eq):  # noqa: E306
                    f = lado.get(eq)
                    return "—" if not f else pct(f["p"], 0) + (f" + {pct(f['q'], 0)} empate" if f["q"] > 0.005 else "")
                filas_p.append(("Cubre (y empate)", cub(A), T1, cub(B_), T1))
            def tp(eq):  # noqa: E306
                f = lado.get(eq)
                return "—" if not f else am_tope(f["tope"])
            filas_p.append((f"Tope {'del ML' if tipo == 'ML' else 'del spread'} (costo 2 %)", tp(A), T2, tp(B_), T2))
        comp = {}
        for f in F["formas"]:
            if f["tipo"] == "COMPRA":
                comp.setdefault(f["equipo"], f)
        if comp:
            def cp(eq):  # noqa: E306
                f = comp.get(eq)
                return "—" if not f else f"{linea_t(f['linea'])} a {am_tope(f['tope'])}"
            filas_p.append(("Comprar puntos: tope", cp(A), T2, cp(B_), T2))
    mq = c.get("maquina")
    if mq and not mq["fuera"]:
        pa = mq["p"] if mq["gana"] == A else 1 - mq["p"]
        filas_p.append(("La máquina: gana (cuota justa)", f"{pct(pa, 0)}  ({am(1 / pa)})", T1, f"{pct(1 - pa, 0)}  ({am(1 / (1 - pa))})", T1))
    notas_p = []
    if mq:
        if mq["fuera"]:
            notas_p.append("La máquina: «Fuera» en este partido (no hacerle caso).")
        else:
            notas_p.append(f"La máquina: margen {B_} {'+' if (mq['margen'] or 0) >= 0 else '−'}{coma(abs(mq['margen'] or 0), 1)} · "
                           f"total {coma(mq['total'] or 0, 1)} · señal 29A: {', '.join(mq['senal']) or 'ninguna'} (en prueba).")
    if c.get("barata"):
        notas_p.append(f"Más barata: {forma_txt(c['barata'])} (EV {ev_t(c['barata']['ev'])}). Más probable que pasa la regla: "
                       f"{forma_txt(c['sug'])}.")
    r = W.res
    def rr(eq, k):  # noqa: E306
        x = r.get(eq) or {}
        return x.get(k, "—")
    def dif(eq, k, kd):  # noqa: E306
        x = r.get(eq) or {}
        d = x.get(kd)
        return f"{x.get(k, '—')}" + ("" if d is None else f"  ({'+' if d >= 0 else '−'}{coma(abs(d), 1)})")
    filas_r = [("Récord", rr(A, "record"), rr(B_, "record")), ("En casa (dif. por partido)", dif(A, "casa", "casa_dif"), dif(B_, "casa", "casa_dif")),
               ("De visita (dif. por partido)", dif(A, "visita", "visita_dif"), dif(B_, "visita", "visita_dif")),
               ("Contra la línea", rr(A, "ats"), rr(B_, "ats")), ("Últimos 5 (el último a la derecha)", rr(A, "ult5"), rr(B_, "ult5")),
               ("Racha", racha_txt((r.get(A) or {}).get("racha")), racha_txt((r.get(B_) or {}).get("racha"))),
               ("Descanso (días)", "—" if c["rest"].get(A) is None else f"{c['rest'][A]:.0f}",
                "—" if c["rest"].get(B_) is None else f"{c['rest'][B_]:.0f}")]
    import textwrap
    alerta = textwrap.wrap(_sin_emoji("Alerta abierta: " + "; ".join(x.replace("🔎 ", "") for x in c["alertas"])
                                      + " -> revisar en la T-85"), 86)[:2] if c["alertas"] else []
    H1 = 200 + (16 + 30 * len(alerta) + 14 if alerta else 0) + 50 + 44 + len(filas_p) * 48 + len(notas_p) * 30 + 40 + 50 + 44 + len(filas_r) * 46 + 60 + 50 + 40 + 50 + 40
    plt, fig, ax = _lienzo(WW, H1)
    ax.text(40, 56, f"{S.apodo(A)} ({record_de(r, A)})  {'vs' if c['neutral'] else '@'}  {S.apodo(B_)} ({record_de(r, B_)})",
            color=T1, fontsize=28, weight="bold", va="center")
    ax.text(40, 104, f"{cuando(S, c['inicio'])} Caracas · {c['estadio']}" + (" · sede neutral" if c["neutral"] else ""),
            color=T2, fontsize=16, va="center")
    ax.text(40, 146, f"Semana {W.sem} · precios y probabilidades · récord · clima", color=T2, fontsize=14, va="center")
    y = 200
    if alerta:
        from matplotlib.patches import FancyBboxPatch
        alto_b = 14 + 30 * len(alerta)
        ax.add_patch(FancyBboxPatch((30, y - 22), WW - 60, alto_b, boxstyle="round,pad=0,rounding_size=8", fc=C_SERIO, ec="none"))
        for k, lin_ in enumerate(alerta):
            ax.text(48, y - 6 + 30 * k, lin_, color=BG, fontsize=14, weight="bold", va="center")
        y += alto_b + 16
    y = _panel(ax, y, WW, "Precios: Pinnacle sin vig contra BetOnline")
    ax.text(CX - LB, y, nombre(A), color=T2, fontsize=13, ha="right", va="center", weight="bold")
    ax.text(CX + LB, y, nombre(B_), color=T2, fontsize=13, ha="left", va="center", weight="bold")
    y += 44
    for et, ta, ca, tb, cb in filas_p:
        ax.text(CX, y, et, color=T1, fontsize=13, ha="center", va="center")
        ax.text(CX - LB, y, ta, color=ca, fontsize=15, ha="right", va="center", weight="bold")
        ax.text(CX + LB, y, tb, color=cb, fontsize=15, ha="left", va="center", weight="bold")
        y += 48
    for n_ in notas_p:
        ax.text(CX, y, n_[:120], color=T2, fontsize=12, ha="center", va="center", style="italic")
        y += 30
    y += 40
    y = _panel(ax, y, WW, "Récord, casa, visita y racha")
    ax.text(CX - LB, y, nombre(A), color=T2, fontsize=13, ha="right", va="center", weight="bold")
    ax.text(CX + LB, y, nombre(B_), color=T2, fontsize=13, ha="left", va="center", weight="bold")
    y += 44
    for et, ta, tb in filas_r:
        ax.text(CX, y, et, color=T1, fontsize=13, ha="center", va="center")
        ax.text(CX - LB, y, str(ta), color=T1, fontsize=15, ha="right", va="center", weight="bold")
        ax.text(CX + LB, y, str(tb), color=T1, fontsize=15, ha="left", va="center", weight="bold")
        y += 46
    ax.text(CX, y, "Casa y visita de cada equipo: casi suerte (H45). Las rachas ya están en la línea (H46).", color=T2,
            fontsize=12, ha="center", va="center", style="italic")
    y += 60
    y = _panel(ax, y, WW, "Clima")
    ax.text(48, y + 4, _sin_emoji(clima_txt(c))[:100], color=T1, fontsize=15, va="center")
    y += 40
    ax.text(48, y, "Solo para mostrar: la T-85 lo vuelve a consultar. El cierre ya descuenta el clima (H31).", color=T2,
            fontsize=12, va="center", style="italic")
    y += 50
    ax.text(40, y, "Datos: Pinnacle y BetOnline (bot), nflverse 2026, motor s2-v1. Descriptivo: no es una recomendación.",
            color=T2, fontsize=12, va="center")
    fig.savefig(rutas[0], facecolor=BG)
    plt.close(fig)

    # ---------------- imagen 2
    secciones = [(f"Cuando ataca {A} (ataque {A} - defensa {B_})", [(n_, b + "_of", b + "_de") for n_, b in CHOQUE], A, B_),
                 (f"Cuando ataca {B_} (ataque {B_} - defensa {A})", [(n_, b + "_of", b + "_de") for n_, b in CHOQUE], B_, A),
                 ("Pérdidas de balón", [(n_.capitalize() + (" (por partido)" if k.endswith("_pj") else ""), k, k) for n_, k in PERDIDAS], A, B_),
                 ("Equipos especiales y disciplina", [(n_.capitalize(), k, k) for n_, k in ESPECIALES], A, B_)]
    qbs = [f"QB mezclado ({eq}): {q['n_otro']} de {q['n']} partidos con otro QB ({', '.join(q['otros'])})."
           for eq, q in c["qb"].items() if q]
    RH = 56
    H2 = 150 + sum(50 + 40 + len(f) * RH + 24 for _, f, _, _ in secciones) + len(qbs) * 30 + 110
    plt, fig, ax = _lienzo(WW, H2)
    ax.text(40, 50, f"{A} {'vs' if c['neutral'] else '@'} {B_} · choque, pérdidas y equipos especiales", color=T1, fontsize=24,
            weight="bold", va="center")
    ax.text(40, 94, "Puesto entre 32 (barra más larga = mejor) · valor · si se repite según 2016-2025 (H44).", color=T2,
            fontsize=14, va="center")
    y = 150
    BAR = 190
    from matplotlib.patches import FancyBboxPatch
    for titulo, filas, ea, eb in secciones:
        y = _panel(ax, y, WW, titulo)
        ax.text(CX - LB, y, nombre(ea), color=T2, fontsize=13, ha="right", va="center", weight="bold")
        ax.text(CX + LB, y, nombre(eb), color=T2, fontsize=13, ha="left", va="center", weight="bold")
        y += 40
        for et, ka, kb in filas:
            ta = estab_txt(ka)
            tb = estab_txt(kb)
            marca = ta if ta == tb else f"ataque {ta} · defensa {tb}"
            ax.text(CX, y - 10, et, color=T1, fontsize=14, ha="center", va="center")
            ax.text(CX, y + 14, marca, color=T2, fontsize=11, ha="center", va="center", style="italic")
            for lado, eq, k in ((-1, ea, ka), (1, eb, kb)):
                v, pu = m_eq(W, eq, k)
                if v is None or pu is None:
                    ax.text(CX - LB if lado < 0 else CX + LB, y, "—", color=T2, fontsize=14, ha="right" if lado < 0 else "left", va="center")
                    continue
                L = BAR * (33 - pu) / 32
                x0 = CX - LB if lado < 0 else CX + LB
                xs = x0 - L if lado < 0 else x0
                ax.add_patch(FancyBboxPatch((xs, y - 12), L, 24, boxstyle="round,pad=0,rounding_size=4", fc=tier(pu)[1], ec="none"))
                t_ = f"({valor_t(k, v)})  #{pu}" if lado < 0 else f"#{pu}  ({valor_t(k, v)})"
                ax.text(xs - 10 if lado < 0 else xs + L + 10, y, t_, color=T1, fontsize=13, weight="bold",
                        ha="right" if lado < 0 else "left", va="center")
            y += RH
        y += 24
    for q in qbs:
        ax.text(40, y, q[:110], color=C_AVISO, fontsize=12, va="center")
        y += 30
    y += 20
    x = 40
    for (_, col), lab in zip(TIER, ("1-8", "9-16", "17-24", "25-32")):
        ax.add_patch(FancyBboxPatch((x, y - 10), 20, 20, boxstyle="round,pad=0,rounding_size=4", fc=col, ec="none"))
        ax.text(x + 30, y, f"#{lab}", color=T1, fontsize=14, va="center")
        x += 140
    y += 44
    ax.text(40, y, f"Datos: nflverse 2026, semanas 1-{W.sem_pbp or '?'}. Descriptivo: el cierre ya incluye todo esto.",
            color=T2, fontsize=12, va="center")
    fig.savefig(rutas[1], facecolor=BG)
    plt.close(fig)
    return rutas


# --------------------------------------------------------------------------------------------------------------------
# Telegram (HTML, fotos en grupo, solo suena el primero; nunca escribe la URL en el log: lleva el token)
# --------------------------------------------------------------------------------------------------------------------
def html_a_plano(t):
    return html.unescape(re.sub(r"<[^>]+>", "", t))


def partir(txt, limite=3900):
    """Partes de ≤ limite caracteres cortadas en líneas en blanco (y, si hace falta, en saltos de línea)."""
    partes, cur = [], ""
    for bloque in txt.split("\n\n"):
        trozos = [bloque] if len(bloque) <= limite else []
        if not trozos:
            t = ""
            for lin in bloque.split("\n"):
                while len(lin) > limite:
                    if t:
                        trozos.append(t)
                        t = ""
                    trozos.append(lin[:limite])
                    lin = lin[limite:]
                if t and len(t) + len(lin) + 1 > limite:
                    trozos.append(t)
                    t = lin
                else:
                    t = f"{t}\n{lin}" if t else lin
            if t:
                trozos.append(t)
        for tr in trozos:
            if cur and len(cur) + len(tr) + 2 > limite:
                partes.append(cur)
                cur = tr
            else:
                cur = f"{cur}\n\n{tr}" if cur else tr
    if cur:
        partes.append(cur)
    return partes


class Envio:
    """Envía al chat de ~/nfl_ev/config.ini (el mismo que sprint2.telegram). sin_telegram: imprime y no envía."""

    def __init__(self, S, sin_telegram=False, post=None):
        self.S, self.sin, self.post = S, sin_telegram, post
        self.token = self.chat = None
        self.n_ok = self.n_mal = 0
        self.primero = True
        self.copia = []                                   # lo que se mandó (para las pruebas y el archivo)
        self.error = None
        if not sin_telegram:
            cfg = configparser.ConfigParser()
            try:
                cfg.read(Path.home() / "nfl_ev" / "config.ini")
                self.token, self.chat = cfg["telegram"]["token"].strip(), cfg["telegram"]["chat_id"].strip()
            except Exception:  # noqa: BLE001
                self.error = "sin [telegram] token/chat_id en ~/nfl_ev/config.ini"

    def _llamar(self, metodo, data, rutas=None):
        if self.error:
            return False, self.error
        post = self.post
        if post is None:
            import requests
            post = requests.post
        url = f"https://api.telegram.org/bot{self.token}/{metodo}"
        desc = ""
        for _ in range(3):
            abiertos = []
            try:
                files = None
                if rutas:
                    files = {}
                    for k, ruta in rutas.items():
                        fh = open(ruta, "rb")
                        abiertos.append(fh)
                        files[k] = (Path(ruta).name, fh, "image/png")
                r = post(url, data=data, files=files, timeout=TG_PLAZO_S)
            except Exception as e:  # noqa: BLE001
                return False, f"error de red ({type(e).__name__})"
            finally:
                for fh in abiertos:
                    fh.close()
            try:
                js = r.json()
            except Exception:  # noqa: BLE001
                js = {}
            desc = str(js.get("description") or r.status_code)[:200]
            if r.status_code == 429:
                espera = min(30.0, float((js.get("parameters") or {}).get("retry_after", 5)))
                time.sleep(espera + 0.5)
                continue
            return bool(js.get("ok")) and r.status_code == 200, desc
        return False, f"429 repetido ({desc})"

    def _nota(self, ok, desc, que):
        if ok:
            self.n_ok += 1
        else:
            self.n_mal += 1
            self.S.log(f"Briefing: Telegram no aceptó {que} ({desc})")

    def texto(self, txt):
        for parte in partir(txt):
            self.copia.append(parte)
            if self.sin:
                print(parte + "\n" + "-" * 60)
                continue
            data = {"chat_id": self.chat, "text": parte, "parse_mode": "HTML", "disable_web_page_preview": "true",
                    "disable_notification": "false" if self.primero else "true"}
            ok, desc = self._llamar("sendMessage", data)
            if not ok and ("parse" in desc.lower() or "entit" in desc.lower()):
                data.pop("parse_mode")
                data["text"] = html_a_plano(parte)
                ok, desc = self._llamar("sendMessage", data)
            self._nota(ok, desc, "un texto")
            self.primero = False
            time.sleep(TG_PAUSA_S)

    def fotos(self, rutas, caption=""):
        rutas = [r for r in rutas if r and Path(r).exists()]
        if not rutas:
            return
        self.copia.append("[imágenes] " + " · ".join(Path(r).name for r in rutas))
        if self.sin:
            print("[imágenes] " + " · ".join(str(r) for r in rutas))
            return
        sonar = "false" if self.primero else "true"
        if len(rutas) == 1:
            ok, desc = self._llamar("sendPhoto", {"chat_id": self.chat, "caption": caption[:1000], "parse_mode": "HTML",
                                                  "disable_notification": sonar, "photo": "attach://f0"}, {"f0": rutas[0]})
        else:
            media = [{"type": "photo", "media": f"attach://f{i}"} for i in range(len(rutas))]
            if caption:
                media[0].update(caption=caption[:1000], parse_mode="HTML")
            ok, desc = self._llamar("sendMediaGroup", {"chat_id": self.chat, "media": json.dumps(media),
                                                       "disable_notification": sonar},
                                    {f"f{i}": r for i, r in enumerate(rutas)})
        self._nota(ok, desc, "las imágenes")
        self.primero = False
        time.sleep(2 * TG_PAUSA_S)


def tg_resumen(env):
    if env.sin:
        return "sin Telegram (impreso)"
    if env.error:
        return f"Telegram: {env.error}"
    return f"Telegram {env.n_ok} ok" + (f", {env.n_mal} con error" if env.n_mal else "")


# --------------------------------------------------------------------------------------------------------------------
# puntos de entrada (los llama semana.py)
# --------------------------------------------------------------------------------------------------------------------
def _juegos_de(S, g26, ids):
    import polars as pl
    return list(g26.filter(pl.col("game_id").is_in(list(ids))).sort(["inicio", "game_id"]).iter_rows(named=True))


def _clima_por_juego(clima_res):
    if not clima_res or clima_res.get("estado") != "ok":
        return {}
    return {x.get("game_id"): x for x in clima_res.get("juegos") or [] if isinstance(x, dict)}


def briefing_enviar(S, g26, ahora, momento, sem, ids, ia, fuentes, costo, estado_ia, origen, clima_res, bot_dir,
                    sin_telegram=False, equipo=None, post=None):
    """Arma y manda el briefing de 68: portada, por partido 2 imágenes y el texto, y la matriz (si no es de un equipo).
    Devuelve (resumen, ruta del texto guardado)."""
    t0 = time.time()
    W = Semana(S, g26, sem, momento, ahora, bot_dir)
    gs = _juegos_de(S, g26, ids)
    foto, sin_ref = foto_juegos(S, g26, sem, bot_dir, momento, ids=set(ids), solo_dias=False)
    por_gid = {j["game_id"]: j for j in foto}
    clima = _clima_por_juego(clima_res)
    ctxs = [contexto(W, g, por_gid.get(g["game_id"]), clima.get(g["game_id"]), (ia or {}).get(g["game_id"])) for g in gs]
    env = Envio(S, sin_telegram, post)
    try:
        return _briefing_cuerpo(S, W, ctxs, env, sem, momento, origen, estado_ia, fuentes, costo, clima_res, ia, equipo,
                                sin_ref, t0)
    except Exception as e:  # noqa: BLE001
        if not env.copia:                                  # nada salió todavía: semana.py manda el texto de v9.2
            raise
        S.log(f"Briefing: error después de enviar {len(env.copia)} partes ({type(e).__name__}: {str(e)[:200]}); no se repite")
        return f"{len(ctxs)} juegos · error parcial después de enviar ({type(e).__name__}) · {tg_resumen(env)}", None, env


def _briefing_cuerpo(S, W, ctxs, env, sem, momento, origen, estado_ia, fuentes, costo, clima_res, ia, equipo, sin_ref, t0):
    carpeta = S.SAL / "briefing" / "tarjetas" / f"semana_{sem}"
    tarjetas_ok, tarjetas_mal = 0, 0
    try:
        carpeta.mkdir(parents=True, exist_ok=True)
        for vieja in carpeta.parent.glob("semana_*"):     # se guardan las tarjetas de las últimas 3 semanas (≈ 6 MB c/u)
            m = re.fullmatch(r"semana_(\d+)", vieja.name)
            if m and int(m.group(1)) < sem - 2:
                for x in vieja.glob("*.png"):
                    x.unlink()
                vieja.rmdir()
    except Exception:  # noqa: BLE001
        pass
    textos = []
    if not equipo:
        p = portada_txt(W, ctxs, origen, estado_ia, fuentes, costo, clima_res)
        textos.append(p)
        env.texto(p)
    for c in ctxs:
        rutas = [carpeta / f"{c['gid']}_1.png", carpeta / f"{c['gid']}_2.png"]
        try:
            tarjeta(W, c, rutas)
            tarjetas_ok += 1
        except Exception as e:  # noqa: BLE001
            tarjetas_mal += 1
            rutas = []
            S.log(f"Briefing: no pude dibujar la tarjeta de {c['gid']} ({type(e).__name__}: {str(e)[:160]})")
        env.fotos(rutas, f"<b>{h(c['visita'])} @ {h(c['local'])}</b> · {cuando(S, c['inicio'])}")
        t = texto_juego(W, c, "" if ia else estado_ia)
        textos.append(t)
        env.texto(t)
    ruta_m = None
    if not equipo:
        try:                                               # la matriz no debe tumbar lo que ya salió
            jm = [c for c in ctxs if c.get("F") and S._dia_et({"weekday": None, "inicio": c["inicio"]}) in S.DIAS_BOLETO]
            if jm and W.cfg["activo"]:
                monto, fuente_m = presupuesto(S)
                momento_m = "sabado" if origen == "sabado" else "pedido"
                txt, bol = texto_matriz(W, jm, momento_m, monto, fuente_m,
                                        sin_ref=[x for x in sin_ref if x in {c["gid"] for c in ctxs}])
                ruta_m = guardar_matriz(W, jm, momento_m, monto, bol)
                textos.append(txt)
                env.texto(txt)
        except Exception as e:  # noqa: BLE001
            S.log(f"Briefing: la matriz falló ({type(e).__name__}: {str(e)[:200]})")
    BR = S.SAL / "briefing"
    BR.mkdir(parents=True, exist_ok=True)
    ruta = BR / f"briefing_semana_{sem}_{momento.astimezone(S.CARACAS):%Y%m%d_%H%M}{'_' + equipo if equipo else ''}.txt"
    ruta.write_text("\n\n".join(html_a_plano(t) for t in textos) + "\n", encoding="utf-8")
    res = (f"{len(ctxs)} juegos · tarjetas {tarjetas_ok} ok{f', {tarjetas_mal} con error' if tarjetas_mal else ''} · "
           + tg_resumen(env)
           + (f" · matriz {ruta_m.name}" if ruta_m else "") + f" · {time.time() - t0:.0f} s"
           + (f" · avisos: {'; '.join(W.avisos)}" if W.avisos else ""))
    return res, ruta, env


def matriz_enviar(S, g26, ahora, origen, bot_dir, sin_telegram=False, post=None):
    """Matriz sola (sin Opus ni tarjetas): 'final' (domingo, después de la primera T−85 automática de un grupo de las
    13:00 ET o más tarde) o 'pedido' (/matriz). Lleva las alertas del sábado (QB en duda, clima) y el vigía vigente."""
    sem = S.semana_actual(g26, ahora)
    if sem is None:
        return "No hay juegos por jugar.", None
    W = Semana.__new__(Semana)                              # ligera: sin jugada por jugada ni marcador
    W.S, W.g26, W.sem, W.momento, W.ahora, W.bot_dir = S, g26, sem, ahora, ahora, bot_dir
    W.cfg, W.avisos, W.vals, W.rk, W.sem_pbp, W.res, W.marcador = config_matriz(S), [], {}, {}, None, {}, None
    W.proy = W._seguro(lambda: S.ultimas_proyecciones(sem), {}, "proyecciones")
    W.verdad, W.nombres = {}, {}
    W.vigia = W._seguro(lambda: S.vigia_avisos_semana(sem), {}, "vigía")
    if not W.cfg["activo"]:
        return "Matriz: apagada en semana.ini [matriz] activo = no.", None
    foto, sin_ref = foto_juegos(S, g26, sem, bot_dir, ahora, solo_dias=True)
    if not foto:
        return f"Semana {sem}: no quedan juegos de domingo o lunes por empezar.", None
    sab = leer_matriz(S, sem, "sabado")
    ant = {j["game_id"]: j for j in (sab or {}).get("juegos", [])}
    por_gid = {j["game_id"]: j for j in foto}
    ctxs = []
    for g in _juegos_de(S, g26, por_gid):
        a = ant.get(g["game_id"]) or {}
        clima_j = {"notable": 1} if a.get("clima_notable") else None
        c = contexto(W, g, por_gid[g["game_id"]], clima_j, None)
        for x in a.get("bajas_qb_duda") or []:
            if x not in c["alertas"]:
                c["alertas"].append(x + " (del sábado)")
        if clima_j:
            c["alertas"] = [x if x != "clima notable" else "clima notable (del sábado)" for x in c["alertas"]]
        ctxs.append(c)
    monto, fuente_m = presupuesto(S)
    cambios = cambios_desde(sab, ctxs) if origen == "final" else None
    txt, bol = texto_matriz(W, ctxs, origen, monto, fuente_m, cambios, sin_ref)
    env = Envio(S, sin_telegram, post)
    env.texto(txt)
    ruta = guardar_matriz(W, ctxs, origen, monto, bol)
    s = bol["sugerido"]
    return (f"Matriz {NOMBRE_MOMENTO.get(origen, origen)} de la semana {sem}: {len(ctxs)} juegos"
            + (f" · sugerido cobra {pct(s['p'])}, EV {ev_t(s['ev'])}" if s else "")
            + " · " + tg_resumen(env)), ruta


# --------------------------------------------------------------------------------------------------------------------
# seguimiento con el informe del lunes (68): lo que sugería la matriz frente a lo apostado
# --------------------------------------------------------------------------------------------------------------------
ABBR = {"WSH": "WAS", "LAR": "LA", "JAC": "JAX", "LVR": "LV", "OAK": "LV", "SD": "LAC", "STL": "LA", "ARZ": "ARI"}


def _abbr(x):
    x = str(x or "").upper().strip()
    return ABBR.get(x, x)


def seccion_seguimiento(S, g26, sem):
    """(texto para Telegram, líneas del informe completo). Tolera que falten la matriz o el registro de parlays."""
    final, sab = leer_matriz(S, sem, "final"), leer_matriz(S, sem, "sabado")
    mat = final or sab
    ruta = S.BASE / "salidas" / "parlays" / "parlays_2026.json"
    try:
        todos = json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else []
    except Exception:  # noqa: BLE001
        todos = None
    if not mat and not todos:
        return "", []
    lin = [f"🧮 Matriz contra lo apostado (68) · semana {sem}"]
    if mat:
        s = (mat.get("boletos") or {}).get("sugerido")
        lin.append(f"Matriz {NOMBRE_MOMENTO.get(mat.get('momento'), mat.get('momento'))}: "
                   + (f"sugerido de {s['n']} patas, cobra {uno_de(s['p'])}, EV {ev_t(s['ev'])}, costo esperado USD "
                      f"{coma(s['costo'], 2)} sobre USD {coma(mat.get('presupuesto') or 0, 0)}." if s else "sin boleto sugerido."))
    else:
        lin.append("Matriz: no se guardó ninguna para esta semana.")
    if todos is None:
        lin.append("Parlays: no pude leer parlays_2026.json.")
        return "\n".join(lin), lin
    bs = [b for b in todos if isinstance(b, dict) and b.get("estado") != "borrado" and b.get("tipo", "PARLAY") == "PARLAY"
          and str(b.get("semana")) == str(sem) and int(b.get("fase") or 2) == 2
          and int(b.get("temporada") or S.TEMPORADA) == S.TEMPORADA]
    if not bs:
        lin.append("Apostado: ningún parlay cargado en Telegram para esta semana.")
        return "\n".join(lin), lin
    monto = sum(num(b.get("monto")) or 0.0 for b in bs)
    costo, n_costo, monto_ev = 0.0, 0, 0.0
    for b in bs:
        e = (b.get("cierre") or {}).get("ev")
        e = num(e) if e is not None else num((b.get("previo") or {}).get("ev"))
        if e is not None and num(b.get("monto")):
            costo += -e * num(b["monto"])
            monto_ev += num(b["monto"])
            n_costo += 1
    formas = {}
    for m_ in (sab, final):                              # la final manda; el sábado cubre los juegos que ya no estaban
        for j in (m_ or {}).get("juegos", []):
            for f in j.get("formas") or []:
                formas[(j["game_id"], f["equipo"], "ML" if f["tipo"] == "ML" else "SP",
                        None if f["tipo"] == "ML" else f["linea"])] = (f, j)
    patas = [p for b in bs for p in b.get("patas", []) if p.get("tipo") in ("ML", "SPREAD")]
    otras = sum(1 for b in bs for p in b.get("patas", []) if p.get("tipo") not in ("ML", "SPREAD"))
    cuenta = {"igual": 0, "✅": 0, "⚠️": 0, "❌": 0, "fuera": 0}
    for p in patas:
        eq, tipo = _abbr(p.get("equipo")), "ML" if p.get("tipo") == "ML" else "SP"
        lin_ = None if tipo == "ML" else num(p.get("linea"))
        gid = p.get("gid")
        cand = [v for k, v in formas.items() if k[1] == eq and k[2] == tipo and (gid is None or k[0] == gid)
                and (tipo == "ML" or (lin_ is not None and k[3] is not None and abs(k[3] - lin_) < 1e-6))]
        if not cand:
            cuenta["fuera"] += 1
            continue
        f, j = cand[0]
        cuenta[f.get("estado") if f.get("estado") in ("✅", "⚠️", "❌") else "fuera"] += 1
        s = j.get("sugerida") or {}
        if s.get("equipo") == f["equipo"] and s.get("tipo") == f["tipo"] and s.get("linea") == f.get("linea"):
            cuenta["igual"] += 1
    clv = [num(p.get("p_cierre")) - num(p.get("p_carga")) for b in bs for p in b.get("patas", [])
           if num(p.get("p_cierre")) is not None and num(p.get("p_carga")) is not None]
    dec = [p for b in bs for p in b.get("patas", []) if p.get("res") in ("G", "P", "E")]
    lin.append(f"Apostado: {len(bs)} parlay{'s' if len(bs) != 1 else ''}, USD {coma(monto, 0)}, {len(patas) + otras} patas"
               + (f"; costo esperado al cierre USD {coma(costo, 2)} ({ev_t(-costo / monto_ev) if monto_ev else '—'}"
                  + (f", {n_costo} de {len(bs)} boletos con EV" if n_costo < len(bs) else "") + ")" if n_costo else "") + ".")
    if patas:
        lin.append(f"Patas ML y spread ({len(patas)}): iguales a la sugerida {cuenta['igual']} · en ✅ {cuenta['✅']} · ⚠️ "
                   f"{cuenta['⚠️']} · ❌ {cuenta['❌']} · fuera de la matriz {cuenta['fuera']}" + (f" · otras patas {otras}" if otras else "") + ".")
    if clv:
        lin.append(f"CLV medio de las patas: {'+' if sum(clv) >= 0 else '−'}{coma(abs(100 * sum(clv) / len(clv)), 1)} pp (n {len(clv)}).")
    if dec:
        lin.append(f"Aciertos: {sum(1 for p in dec if p['res'] == 'G')} de {len(dec)} (esperados "
                   f"{coma(sum(num(p.get('p_cierre')) or 0 for p in dec), 1)} con el cierre).")
    lin.append("Objetivo (68): costo ≤ 2 % por pata. Alimenta el frente e (30-nov). Descriptivo.")
    return "\n".join(lin), lin


# --------------------------------------------------------------------------------------------------------------------
# prueba sin costo (no consulta a nadie ni manda nada)
# --------------------------------------------------------------------------------------------------------------------
def prueba():
    ok = True

    def chequeo(nombre, cond, detalle=""):
        nonlocal ok
        ok = ok and bool(cond)
        print(f"  {'ok ' if cond else 'MAL'} {nombre}{(': ' + detalle) if detalle else ''}")
    print(f"{VERSION_BRIEFING} · prueba sin costo")
    chequeo("tabla H44 congelada", md5_estabilidad() == ESTABILIDAD_MD5, md5_estabilidad())
    chequeo("cuota americana", am(dec_de_am(-110)) == "−110" and am(dec_de_am(153)) == "+153")
    chequeo("precio estimado (10 c por medio punto)", am(precio_estimado(dec_de_am(-110), 3, 10)) == "−140"
            and am(precio_estimado(dec_de_am(150), 2, 10)) == "+130" and am(precio_estimado(dec_de_am(105), 1, 10)) == "−105")
    chequeo("líneas con puntos comprados (JAX −10)", [x[1] for x in lineas_compra(-10, 10)] == [-9.5, -6.5, -5.5])
    chequeo("líneas con puntos comprados (BUF −3, dog +2,5)", [x[1] for x in lineas_compra(-3, 3)] == [-2.5]
            and [x[1] for x in lineas_compra(2.5, 2.5, 1)] == [3.5])
    f = nueva_forma("ML", "X", True, True, None, 0.606, 0.0, dec_de_am(-175))
    chequeo("EV y tope (SEA −175 con 60,6 %)", f["estado"] == "❌" and am_tope(f["tope"]) == "−162", f"EV {ev_t(f['ev'])}, tope {am_tope(f['tope'])}")
    b = boleto([nueva_forma("ML", "A", True, True, None, 0.6, 0.0, 1.7), nueva_forma("SP", "B", True, True, -3, 0.45, 0.1, 1.91)], 100)
    esperado = (0.6 * 1.7) * (0.45 * 1.91 + 0.1) - 1
    chequeo("parlay con empate", abs(b["ev"] - esperado) < 1e-12 and abs(b["p"] - 0.6 * 0.55) < 1e-12)
    malos = 0
    for i in range(1, 5500):
        p = 0.05 + 0.9 * i / 5500
        D_t = 0.98 / p
        txt = am_tope(D_t)
        a = float(txt.replace("−", "-"))
        if p * dec_de_am(a) - 1 < -0.02 - 1e-12:
            malos += 1
    chequeo("el tope que se ve cumple la regla (5.499 probabilidades)", malos == 0, f"{malos} fallan")
    chequeo("EV que se ve redondeado hacia abajo", ev_t(-0.02041) == "−2,1 %" and ev_t(-0.02) == "−2,0 %" and ev_t(0.0126) == "+1,2 %")
    pat = [nueva_forma("SP", "A", True, True, -3, 0.46, 0.06, dec_de_am(-110)) for _ in range(4)] + \
          [nueva_forma("SP", "A", True, True, -3, 0.5238, 0.0, dec_de_am(-110)) for _ in range(9)]
    exacto = 0.0
    import itertools
    for res in itertools.product((0, 1), repeat=4):                # 1 = empate en las 4 patas con empate
        pr, d = 0.5238 ** 9, dec_de_am(-110) ** 9
        for x in res:
            pr *= 0.06 if x else 0.46
            d *= 1.0 if x else dec_de_am(-110)
        exacto += pr * min(d, TOPE_PAGO / 66)
    bt = boleto(pat, 66)
    chequeo("EV con el tope de pago y empates (exacto)", bt["tope"] and abs(bt["ev"] - (exacto - 1)) < 1e-12, ev_t(bt["ev"]))
    chequeo("partir mensajes", all(len(x) <= 3900 for x in partir(("línea\n" * 2000) + "\n\n" + "x" * 5000)))
    try:
        import matplotlib  # noqa: F401
        chequeo("matplotlib instalado", True, matplotlib.__version__)
    except Exception as e:  # noqa: BLE001
        chequeo("matplotlib instalado", False, type(e).__name__)
    print("RESULTADO:", "OK" if ok else "FALLÓ")
    return 0 if ok else 1


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "prueba":
        sys.exit(prueba())
    print(__doc__)
