#!/usr/bin/env python3
"""
bola.py — decisión 69 (aprobada el 4-nov-2026; ajustada por Ozz el mismo día: «12-7-4», «Solo el de 4», reparto «Más
al de 4» y presupuesto USD 150). Boletos de 12, 7 y 4 patas y la bola de nieve del de 4. DESCRIPTIVO.

Lo usa semana.py (v9.4); no es un modelo: no cambia s2-v1, la proyección, 31A ni 29A.
  · No calcula precios: toma las filas de la matriz de 68 que acaba de salir (matriz_semana_N_*.json).
  · Patas (B4, B5): las más probables entre las formas sugeridas por la matriz de 14 que pasan la regla (✅ o ⚠️;
    nunca ❌), una por partido y con la MISMA forma que la de 14. El de 4 lleva las 4 primeras, el de 7 las 7 y el de
    12 las 12 (mismas favoritas: si cobra el de 12, cobran los tres). Si no alcanzan las patas, ese boleto no sale.
  · Montos: el reparto del presupuesto semanal (briefing.reparto: 14 · 12 · 7 · 4 = 10 : 10 : 16 : 30).
  · Escalera (B1, B2), solo el de 4: escalón 1 con su parte del presupuesto; si cobra, esa base vuelve y rueda la
    ganancia; los escalones 2-4 ruedan todo (esas semanas su parte no se gasta); al cobrar el 4 se retira todo.
  · Estado sin escribir a mano: se reconstruye cada vez desde los boletos de Telegram cuyo nombre empieza con «Bola»
    (parlays_2026.json; la verdad es el boleto) y las órdenes /bola nueva N (solo la próxima bola) y /bola cobrar
    (salidas/semana/matriz/bola.json).
  · Mensaje «🎟️ Boletos 12 · 7 · 4» después de cada matriz, sección del informe del lunes, línea del estado y /bola.

Las funciones reciben el módulo de semana.py como S y el de briefing.py como B (no los importa: así no se cruzan).

Prueba sin costo (en ~/nfl_sim):  venv/bin/python bola.py prueba
"""
from __future__ import annotations

import configparser
import json
import math
import re
import sys
import unicodedata
from pathlib import Path

VERSION_BOLA = "bola-v1 (5-nov-2026)"

# --------------------------------------------------------------------------------------------------------------------
# Regla de 69 (aprobada el 4-nov-2026; registro claude/registro_69_bola_nieve.md)
# --------------------------------------------------------------------------------------------------------------------
ESCALONES = 4                     # B2
PATAS = 4                         # la bola (Ozz, 4-nov: «12-7-4» y «Solo el de 4»)
BOLETOS = (4, 7, 12)              # los tres boletos semanales; el de 4 es la bola
ESTADOS_OK = ("✅", "⚠️")          # B4: nunca ❌
BASE_OMISION = 10.0               # solo si el reparto está apagado y semana.ini [bola] no dice base_usd
P_ESCALON_H48 = 0.393             # H48: las 4 favoritas más probables cobraron el 39,3 % (2012-2025). ESTIMACIÓN para
                                  # los escalones que faltan (los precios de esas semanas todavía no existen)
SEMANA_MAX = 18                   # temporada regular; los playoffs no entran
TOPE_PAGO = 150_000.0             # premisa 3
PREFIJO = "bola"                  # nombre del boleto en Telegram: «Bola …»
FIN_TXT = {"perdida": "perdió", "completa": "completa (4 de 4)", "cobrada": "cobrada antes (/bola cobrar)",
           "temporada": "cerrada al terminar la temporada regular", "sin_pago": "sin pago legible", "nada": "sin nada que rodar"}


# --------------------------------------------------------------------------------------------------------------------
# textos chicos (los mismos criterios que briefing.py)
# --------------------------------------------------------------------------------------------------------------------
def coma(x, n=2):
    return f"{x:,.{n}f}".replace(",", "_").replace(".", ",").replace("_", ".")


def usd(x):
    if x is None:
        return "USD —"
    t = coma(x, 2)
    return "USD " + (t[:-3] if t.endswith(",00") else t)


def num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) or math.isinf(v) else v


def normal(x):
    x = unicodedata.normalize("NFKD", str(x or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", x).strip()


def es_bola(b):
    """El boleto es de la bola si su nombre empieza con «Bola» (sin importar mayúsculas ni acentos)."""
    return normal(b.get("nombre")).startswith(PREFIJO)


def decimal_de(a):
    a = num(a)
    if a is None or a == 0 or -100 < a < 100:
        return None
    return 1 + (a / 100 if a > 0 else 100 / -a)


def p_leg(f):
    return (num(f.get("p")) or 0.0) + (num(f.get("q")) or 0.0)


def h(x):
    import html
    return html.escape(str(x), quote=False)


# --------------------------------------------------------------------------------------------------------------------
# configuración y archivo de órdenes (bola.json)
# --------------------------------------------------------------------------------------------------------------------
def config_bola(S):
    c = configparser.ConfigParser()
    try:
        c.read(S.CONFIG, encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    sec = c["bola"] if c.has_section("bola") else {}
    activo = str(sec.get("activo", "si")).strip().lower() in ("si", "sí", "1", "true", "yes") if sec else True
    base = num(sec.get("base_usd", "")) if sec else None
    return dict(activo=activo, base_ini=base if base is not None and 1 <= base <= 5000 else None)


def base_bola(S):
    """Base de una bola nueva: semana.ini [bola] base_usd; si no, la parte del de 4 en el reparto del presupuesto (69);
    si el reparto está apagado o no se puede leer, USD 10."""
    cfg = config_bola(S)
    if cfg["base_ini"]:
        return cfg["base_ini"]
    try:
        r = S._modulo_briefing().reparto(S)
        if r["activo"] and r["partes"].get(4):
            return float(r["partes"][4])
    except Exception:  # noqa: BLE001
        pass
    return BASE_OMISION


def reparto_de(S):
    try:
        return S._modulo_briefing().reparto(S)
    except Exception:  # noqa: BLE001
        return None


def ruta_ordenes(S):
    return S.SAL / "matriz" / "bola.json"


def leer_ordenes(S):
    try:
        d = json.loads(ruta_ordenes(S).read_text(encoding="utf-8"))
        if isinstance(d, dict) and isinstance(d.get("acciones"), list):
            return d
    except Exception:  # noqa: BLE001
        pass
    return {"version": VERSION_BOLA, "acciones": []}


def guardar_ordenes(S, d):
    r = ruta_ordenes(S)
    r.parent.mkdir(parents=True, exist_ok=True)
    tmp = r.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(r)


# --------------------------------------------------------------------------------------------------------------------
# boletos «Bola» y su pago
# --------------------------------------------------------------------------------------------------------------------
def leer_parlays(S):
    ruta = S.BASE / "salidas" / "parlays" / "parlays_2026.json"
    if not ruta.exists():
        return []
    d = json.loads(ruta.read_text(encoding="utf-8"))
    return d if isinstance(d, list) else []


def boletos_bola(S, todos=None):
    todos = leer_parlays(S) if todos is None else todos
    bs = [b for b in todos if isinstance(b, dict) and es_bola(b) and b.get("estado") != "borrado"
          and (b.get("tipo") or "PARLAY") == "PARLAY" and int(b.get("fase") or 2) == 2
          and int(b.get("temporada") or S.TEMPORADA) == S.TEMPORADA and num(b.get("monto"))]
    return sorted(bs, key=lambda b: (int(b.get("semana") or 0), str(b.get("cargado") or ""), int(b.get("id") or 0)))


def pago_cobrado(b):
    """Lo que paga un parlay cobrado, como pago_vigente de parlay.py v1.6: con patas empatadas («E») BetOnline las saca
    del boleto (pago ÷ Π cuota de las empatadas; si empatan todas, devuelve lo apostado). Tope USD 150.000. None si no
    se puede saber (pago sin leer o empatada sin cuota)."""
    pago, monto = num(b.get("pago")), num(b.get("monto"))
    patas = b.get("patas") or []
    emp = [p for p in patas if p.get("res") == "E"]
    if emp:
        if len(emp) == len(patas):
            pago = monto
        elif pago and all(decimal_de(p.get("cuota")) for p in emp):
            for p in emp:
                pago /= decimal_de(p["cuota"])
        else:
            pago = None
    if pago is None:
        return None
    return min(pago, TOPE_PAGO)


# --------------------------------------------------------------------------------------------------------------------
# la escalera, reconstruida desde los boletos y las órdenes
# --------------------------------------------------------------------------------------------------------------------
def reconstruir(S, todos=None, ordenes=None, cerrada_temporada=False, base=None):
    """Recorre en orden de tiempo los boletos «Bola» y las órdenes. Devuelve las escaleras, la viva (o None), los boletos
    que no movieron la escalera (extras), la base de la próxima y los totales de la temporada. /bola nueva N vale solo
    para la próxima bola; después vuelve la base del reparto."""
    ordenes = leer_ordenes(S) if ordenes is None else ordenes
    base_omision = base_bola(S) if base is None else base
    pendiente = None
    eventos = [(str(a.get("ts") or ""), 1, "orden", a) for a in ordenes.get("acciones", []) if isinstance(a, dict)]
    eventos += [(str(b.get("cargado") or ""), 0, "boleto", b) for b in boletos_bola(S, todos)]
    eventos.sort(key=lambda e: (e[0], e[1]))
    escaleras, extras, semanas_usadas = [], [], set()
    viva = None
    out_ = in_ = 0.0
    for _, _, tipo, x in eventos:
        if tipo == "orden":
            if x.get("tipo") == "nueva" and num(x.get("valor")):
                pendiente = num(x["valor"])
            elif x.get("tipo") == "cobrar" and viva and viva["escalones"] and viva["escalones"][-1]["estado"] == "cobrado":
                viva.update(fin="cobrada", retiro=viva["rueda"], fin_ts=x.get("ts"))
                in_ += viva["rueda"]
                viva = None
            continue
        b = x
        sem = int(b.get("semana") or 0)
        if sem > SEMANA_MAX:
            continue
        if viva and viva["escalones"] and viva["escalones"][-1]["estado"] == "vivo":
            extras.append(dict(boleto=b, motivo="otro escalón estaba en juego"))
            continue
        if sem in semanas_usadas:
            extras.append(dict(boleto=b, motivo="ya había un boleto «Bola» en esa semana"))
            continue
        semanas_usadas.add(sem)
        monto = num(b["monto"])
        if viva is None:
            esperado = pendiente if pendiente else base_omision
            pendiente = None
            viva = dict(n=len(escaleras) + 1, base=monto, base_sugerida=esperado, escalones=[], rueda=0.0, fin=None,
                        retiro=0.0, devuelto=0.0)
            escaleras.append(viva)
            out_ += monto
        else:
            esperado = viva["rueda"]
            dif = monto - esperado
            if dif > 0:
                out_ += dif
            else:
                in_ += -dif
        k = len(viva["escalones"]) + 1
        e = dict(k=k, semana=sem, id=b.get("id"), nombre=b.get("nombre"), monto=monto, esperado=esperado,
                 estado=b.get("estado") or "vivo", pago=None, devuelto=0.0, rueda=0.0, n_patas=len(b.get("patas") or []))
        viva["escalones"].append(e)
        if e["estado"] == "perdido":
            viva.update(fin="perdida", rueda=0.0)
            viva = None
        elif e["estado"] == "cobrado":
            pago = pago_cobrado(b)
            if pago is None:
                e["estado"] = "sin_pago"
                viva.update(fin="sin_pago", rueda=0.0)
                viva = None
                continue
            e["pago"] = pago
            if k == 1:                                    # B1: la base vuelve al primer cobro y rueda la ganancia
                e["devuelto"] = min(viva["base"], pago)
                in_ += e["devuelto"]
                viva["devuelto"] = e["devuelto"]
                e["rueda"] = pago - e["devuelto"]
            else:
                e["rueda"] = pago
            viva["rueda"] = e["rueda"]
            if k >= ESCALONES or e["rueda"] <= 0.005:
                viva.update(fin="completa" if k >= ESCALONES else "nada", retiro=e["rueda"])
                in_ += e["rueda"]
                viva = None
        else:
            e["estado"] = "vivo"
    if cerrada_temporada and viva and viva["escalones"] and viva["escalones"][-1]["estado"] == "cobrado":
        viva.update(fin="temporada", retiro=viva["rueda"])
        in_ += viva["rueda"]
        viva = None
    costo = 0.0
    n_costo = 0
    for b in boletos_bola(S, todos):
        ev = num((b.get("cierre") or {}).get("ev"))
        if ev is None:
            ev = num((b.get("previo") or {}).get("ev"))
        if ev is not None and int(b.get("semana") or 0) <= SEMANA_MAX:
            costo += -ev * num(b["monto"])
            n_costo += 1
    rodando = viva["rueda"] if viva and viva["escalones"] and viva["escalones"][-1]["estado"] == "cobrado" else 0.0
    en_juego = viva["escalones"][-1]["monto"] if viva and viva["escalones"] and viva["escalones"][-1]["estado"] == "vivo" else 0.0
    return dict(escaleras=escaleras, viva=viva, extras=extras, base_siguiente=pendiente or base_omision,
                base_reparto=base_omision, base_pendiente=pendiente,
                totales=dict(puesto=out_, recibido=in_, neto=in_ - out_, rodando=rodando, en_juego=en_juego,
                             n=len(escaleras), completas=sum(1 for x in escaleras if x["fin"] == "completa"),
                             costo=costo, n_costo=n_costo))


def siguiente(rec):
    """('en_juego', k, escalón) · ('escalon', k, monto) · ('nueva', 1, base)."""
    v = rec["viva"]
    if v and v["escalones"] and v["escalones"][-1]["estado"] == "vivo":
        return "en_juego", v["escalones"][-1]["k"], v["escalones"][-1]
    if v and v["escalones"]:
        return "escalon", len(v["escalones"]) + 1, v["rueda"]
    return "nueva", 1, rec["base_siguiente"]


# --------------------------------------------------------------------------------------------------------------------
# las patas: desde la matriz de 14 que acaba de salir
# --------------------------------------------------------------------------------------------------------------------
def candidatas(mat):
    """Forma sugerida por la matriz de 14 en cada partido, si pasa la regla (✅ o ⚠️) y tiene precio de BetOnline."""
    out = []
    for j in (mat or {}).get("juegos") or []:
        s = j.get("sugerida")
        if not s or s.get("estado") not in ESTADOS_OK or not num(s.get("D")) or num(s.get("p")) is None:
            continue
        if s.get("tipo") == "COMPRA" and s.get("estado") != "✅":
            continue
        out.append(dict(j=j, f=s))
    out.sort(key=lambda c: (-p_leg(c["f"]), -(num(c["f"].get("ev")) or -9), c["j"].get("game_id", "")))
    return out


def sugerir(B, mat, montos):
    """Los tres boletos anidados (4 ⊂ 7 ⊂ 12) con sus montos {4: USD, 7: USD, 12: USD}; el de 4 también en su versión más
    barata (las 4 de mejor EV). Un boleto sin patas suficientes no sale (None)."""
    cand = candidatas(mat)
    r = dict(n_cand=len(cand), cand=cand, boletos={}, baratas=None, bb=None)
    for n in BOLETOS:
        if len(cand) >= n and montos.get(n):
            r["boletos"][n] = dict(patas=cand[:n], monto=montos[n], b=B.boleto([c["f"] for c in cand[:n]], montos[n]))
    if PATAS in r["boletos"]:
        bar = sorted(cand, key=lambda c: (-(num(c["f"].get("ev")) or -9), -p_leg(c["f"]), c["j"].get("game_id", "")))[:PATAS]
        if {c["j"]["game_id"] for c in bar} != {c["j"]["game_id"] for c in cand[:PATAS]}:
            r["baratas"] = bar
            r["bb"] = B.boleto([c["f"] for c in bar], montos[PATAS])
    return r


def p_completar(p_ahora, k):
    """P(llegar al escalón 4 desde el escalón k): la de esta semana × 0,393 por cada escalón que falta (H48; estimación)."""
    return p_ahora * P_ESCALON_H48 ** max(0, ESCALONES - k)


def pago_txt(B, b, monto):
    return f"×{coma(b['D'], 2)} ({usd(monto * b['D'] if not b['tope'] else b['pago'])})"


def lineas_boleto(B, b, monto):
    return (f"cobra {B.uno_de(b['p'])} ({B.pct(b['p'])}) · paga {pago_txt(B, b, monto)} · EV {B.ev_t(b['ev'])} · "
            f"costo esperado {usd(b['costo'])}")


def mayus(x):
    return x[:1].upper() + x[1:]


def texto_bola(S, B, mat, rec, ahora, rp=None):
    """Mensaje HTML de Telegram (después de la matriz): los boletos de 12, 7 y 4 patas y la escalera del de 4."""
    sem, momento = mat.get("semana"), mat.get("momento")
    rp = rp or reparto_de(S) or dict(activo=False, total=None, partes={})
    partes = rp.get("partes") or {}
    que, k, x = siguiente(rec)
    lin = [f"<b>🎟️ BOLETOS 12 · 7 · 4 · semana {sem} · {h(B.NOMBRE_MOMENTO.get(momento, momento))}</b>"]
    if rp.get("activo"):
        lin.append(f"Presupuesto USD {coma(rp['total'], 0)} de la semana: {h(B.reparto_txt(rp))} (la bola). "
                   "Se cambia con /presupuesto N.")
    montos = {7: partes.get(7), 12: partes.get(12)}
    if que == "en_juego":
        bola_txt = (f"<b>⛄ 4 patas · bola, escalón {k} de {ESCALONES} en juego:</b> «{h(x.get('nombre'))}» con {usd(x['monto'])}. "
                    "No hace falta otra esta semana.")
    else:
        montos[PATAS] = x
        if que == "nueva":
            sigue = (f"Si cobra, los {usd(x)} vuelven a tu bolsillo y la ganancia rueda al escalón 2.")
        elif k < ESCALONES:
            sigue = (f"Es lo que rueda (la base de {usd(rec['viva']['base'])} ya volvió; su parte del presupuesto no se gasta "
                     f"esta semana). Si cobra, todo rueda al escalón {k + 1}.")
        else:
            sigue = (f"Es lo que rueda. Si cobra, retiras todo y la próxima semana empieza otra bola con "
                     f"{usd(rec['base_siguiente'])}.")
        bola_txt = f"<b>⛄ 4 patas · bola, escalón {k} de {ESCALONES}: apuesta {usd(x)}.</b> {sigue}"
    r = sugerir(B, mat, montos)
    lin += ["", f"<b>Las patas</b> (las más probables que pasan la regla, una por partido, con la misma forma que en la matriz "
                f"de 14; el de 4 lleva la 1-4, el de 7 la 1-7 y el de 12 la 1-12)"]
    n_lista = max([n for n in r["boletos"]] or [min(r["n_cand"], PATAS)])
    for i, c in enumerate(r["cand"][:n_lista], 1):
        f, j = c["f"], c["j"]
        ini = S.t_utc(j.get("inicio_utc"))
        al = f" ⏳ {h('; '.join(j['alertas']))}" if j.get("alertas") else ""
        lin.append(f"{i}. {f['estado']} {h(B.forma_txt(f))} · {'gana' if f['tipo'] == 'ML' else 'cubre'} {B.pct(p_leg(f))} · "
                   f"EV {B.ev_t(num(f['ev']))} · {h(S.cuando_txt(ini)) if ini else ''}{al}")
    if not r["cand"]:
        lin.append("Ninguna forma pasa la regla esta semana.")
    lin.append("")
    lin.append(bola_txt)
    b4 = r["boletos"].get(PATAS)
    if que != "en_juego":
        if b4:
            lin.append(mayus(lineas_boleto(B, b4["b"], b4["monto"])) + ".")
            if k < ESCALONES:
                lin.append(f"Llegar al escalón {ESCALONES} desde aquí: ≈ {B.pct(p_completar(b4['b']['p'], k))} (esta semana "
                           f"{B.pct(b4['b']['p'])} × {B.pct(P_ESCALON_H48)} por cada uno de los {ESCALONES - k} que faltan, "
                           "medido en H48; estimación).")
        else:
            lin.append(f"<b>No hay {PATAS} patas ✅ o ⚠️ (hay {r['n_cand']}): la bola espera.</b> No apuestes; el escalón y el "
                       "monto quedan guardados.")
    for n in (7, 12):
        bn = r["boletos"].get(n)
        if bn:
            lin.append(f"<b>{n} patas: apuesta {usd(bn['monto'])}.</b> {mayus(lineas_boleto(B, bn['b'], bn['monto']))}.")
        elif montos.get(n):
            lin.append(f"<b>{n} patas:</b> no sale esta semana (solo {r['n_cand']} patas pasan la regla); su parte no se gasta.")
    if b4 or que == "en_juego":
        lin.append("")
        lin.append("<i>Los tres llevan las mismas favoritas: si una de las 4 primeras pierde, pierden los tres (y el boleto de 14, "
                   "que lleva las mismas patas). Cobrar al menos uno es lo mismo que cobrar el de 4.</i>")
    if r["baratas"] and r["bb"] and que != "en_juego":
        lin.append(f"<i>La bola más barata</i> ({', '.join(h(B.forma_txt(c['f'], corto=True)) for c in r['baratas'])}): "
                   f"{lineas_boleto(B, r['bb'], montos[PATAS])}.")
    lin.append("<i>Cárgalos en Telegram; el de 4 con un nombre que empiece con «Bola» (por ejemplo «Bola 9»). Regla (69): ✅ o "
               "⚠️, nunca ❌; la bola tiene 4 escalones y la base vuelve al primer cobro. Patas independientes, precios contra "
               "Pinnacle sin vig. Descriptivo: no cuenta para nada.</i>")
    return "\n".join(lin), r


def forma_corta(f):
    return {k: f.get(k) for k in ("tipo", "equipo", "linea", "p", "q", "D", "ev", "estado")}


def guardar_sugerencia(S, mat, rec, r, ahora):
    """bola_semana_N_{sabado|final}.json (o _pedido_FECHA): lo que sugirió la bola, para compararlo con lo cargado."""
    d = S.SAL / "matriz"
    d.mkdir(parents=True, exist_ok=True)
    sem, momento = mat.get("semana"), mat.get("momento")
    nombre = (f"bola_semana_{sem}_{momento}.json" if momento in ("sabado", "final")
              else f"bola_semana_{sem}_pedido_{ahora.astimezone(S.CARACAS):%Y%m%d_%H%M}.json")
    que, k, x = siguiente(rec)
    bs = (r or {}).get("boletos") or {}
    datos = dict(version=VERSION_BOLA, semana=sem, momento=momento, corrida_utc=S.iso(ahora), matriz=mat.get("corrida_utc"),
                 situacion=que, escalon=k, monto=None if que == "en_juego" else round(x, 2),
                 patas=[dict(game_id=c["j"]["game_id"], **forma_corta(c["f"])) for c in (bs.get(PATAS) or {}).get("patas") or []]
                 if que != "en_juego" else [],
                 boletos={str(n): dict(monto=v["monto"], boleto=v["b"],
                                       patas=[dict(game_id=c["j"]["game_id"], **forma_corta(c["f"])) for c in v["patas"]])
                          for n, v in bs.items()})
    tmp = d / (nombre + ".tmp")
    tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(d / nombre)
    return d / nombre


def tras_matriz(S, B, ruta_matriz, ahora, sin_telegram=False, post=None, cerrada_temporada=False):
    """Punto de entrada: después de cada matriz (sábado, final del domingo, /matriz y /briefing). Lee la matriz que acaba
    de salir, arma el mensaje y lo manda aparte. Devuelve un resumen corto. Nunca toca la matriz ni su archivo."""
    if not config_bola(S)["activo"]:
        return "bola apagada (semana.ini [bola] activo = no)"
    mat = json.loads(Path(ruta_matriz).read_text(encoding="utf-8"))
    if int(mat.get("semana") or 0) > SEMANA_MAX:
        return f"bola: semana {mat.get('semana')} fuera de la temporada regular (los playoffs no entran); no se manda"
    rp = B.reparto(S)
    rec = reconstruir(S, cerrada_temporada=cerrada_temporada,
                      base=config_bola(S)["base_ini"] or (float(rp["partes"][4]) if rp["activo"] and rp["partes"].get(4) else BASE_OMISION))
    txt, r = texto_bola(S, B, mat, rec, ahora, rp)
    env = B.Envio(S, sin_telegram, post)
    env.primero = False                                    # no suena: el que suena es el primero de la matriz o del briefing
    env.texto(txt)
    ruta = guardar_sugerencia(S, mat, rec, r, ahora)
    que, k, _ = siguiente(rec)
    bs = r["boletos"]
    res = (f"bola: escalón {k}{' en juego' if que == 'en_juego' else ''} · boletos "
           + (", ".join(f"{n} patas cobra {B.pct(v['b']['p'])}" for n, v in sorted(bs.items())) or "ninguno")
           + f" · {B.tg_resumen(env)} → {ruta.name}")
    return res


# --------------------------------------------------------------------------------------------------------------------
# /bola, el modo estado y el informe del lunes
# --------------------------------------------------------------------------------------------------------------------
def escalon_txt(e):
    if e["estado"] == "vivo":
        res = "en juego"
    elif e["estado"] == "perdido":
        res = "perdió"
    elif e["estado"] == "sin_pago":
        res = "cobró (no pude leer el pago)"
    else:
        res = f"cobró {usd(e['pago'])}" + (f" (vuelven {usd(e['devuelto'])}, ruedan {usd(e['rueda'])})" if e["k"] == 1 else "")
    dif = "" if abs((e["monto"] or 0) - (e["esperado"] or 0)) < 0.01 else f", la bola decía {usd(e['esperado'])}"
    return f"«{e['nombre']}» semana {e['semana']} · escalón {e['k']} · {usd(e['monto'])}{dif} · {e['n_patas']} patas → {res}"


def ahora_txt(rec):
    que, k, x = siguiente(rec)
    if que == "en_juego":
        return f"Escalón {k} de {ESCALONES} en juego: {escalon_txt(x)}."
    if que == "escalon":
        return (f"Escalón {k} de {ESCALONES} por apostar: ruedan {usd(x)} (la base de {usd(rec['viva']['base'])} ya volvió). "
                f"/bola cobrar los retira y cierra la bola.")
    return (f"Ninguna bola viva: la próxima empieza con {usd(x)}"
            + (" (/bola nueva, solo esa)." if rec.get("base_pendiente") else " (su parte del presupuesto; /presupuesto N la cambia).")) 


def totales_txt(rec):
    t = rec["totales"]
    if not t["n"]:
        return "Esta temporada: ninguna bola cargada todavía."
    neto = "0 USD" if abs(t["neto"]) < 0.005 else f"{'+' if t['neto'] > 0 else '−'}{usd(abs(t['neto']))[4:]} USD"
    return (f"Esta temporada: {t['n']} bola{'s' if t['n'] != 1 else ''}, {t['completas']} completa{'s' if t['completas'] != 1 else ''}"
            f" · del bolsillo {usd(t['puesto'])} · volvió o se retiró {usd(t['recibido'])} · neto {neto}"
            + (f" (más {usd(t['rodando'])} rodando)" if t["rodando"] else "")
            + (f" (más {usd(t['en_juego'])} en juego)" if t["en_juego"] else "")
            + (f" · costo esperado acumulado {usd(t['costo'])} ({t['n_costo']} boleto{'s' if t['n_costo'] != 1 else ''} con EV)"
               if t["n_costo"] else ""))


def texto_estado(S, cerrada_temporada=False):
    rec = reconstruir(S, cerrada_temporada=cerrada_temporada)
    lin = [f"⛄ Bola de nieve (69) · {VERSION_BOLA}", ahora_txt(rec), totales_txt(rec)]
    ult = [e for x in rec["escaleras"] for e in x["escalones"]][-6:]
    if ult:
        lin.append("Últimos boletos «Bola»:")
        lin += [f"· {escalon_txt(e)}" for e in ult]
        fin = [x for x in rec["escaleras"] if x["fin"]][-3:]
        for x in fin:
            lin.append(f"· Bola {x['n']}: {FIN_TXT.get(x['fin'], x['fin'])}" + (f", retiraste {usd(x['retiro'])}" if x.get("retiro") else ""))
    if rec["extras"]:
        lin.append(f"No movieron la escalera ({len(rec['extras'])}): " + "; ".join(
            f"«{e['boleto'].get('nombre')}» ({e['motivo']})" for e in rec["extras"][-3:]))
    rp = reparto_de(S)
    if rp and rp.get("activo"):
        lin.append(f"Reparto del presupuesto (USD {coma(rp['total'], 0)} por semana): {reparto_txt_seguro(rp)} (la bola).")
    lin.append("Órdenes: /bola nueva 20 (solo la próxima bola empieza con USD 20) · /bola cobrar (retiras lo que rueda y cierras "
               "la bola) · /presupuesto N (cambia el reparto). El boleto de 4 se carga como siempre, con un nombre «Bola…».")
    return "\n".join(lin)


def reparto_txt_seguro(rp):
    try:
        return " · ".join(f"{k} patas {usd(rp['partes'][k])}" for k in (14, 12, 7, 4))
    except Exception:  # noqa: BLE001
        return "—"


def linea_estado(S):
    rec = reconstruir(S)
    t = rec["totales"]
    return f"Bola de nieve (69): {VERSION_BOLA} · {ahora_txt(rec)} · {t['n']} bolas, {t['completas']} completas"


def accion(S, que, valor, ahora):
    """/bola nueva N y /bola cobrar. Se guarda solo si vale; devuelve el texto para Telegram."""
    rec = reconstruir(S)
    sig, k, x = siguiente(rec)
    d = leer_ordenes(S)
    if que == "nueva":
        v = num(str(valor or "").replace(",", ".").lstrip("$"))
        if v is None or not 1 <= v <= 5000:
            return f"Monto no válido: {valor}. Usa un número entre 1 y 5000, por ejemplo /bola nueva 10."
        if sig != "nueva":
            return (f"Hay una bola viva (escalón {k} de {ESCALONES}). El monto nuevo vale para la próxima: si quieres cerrar esta, "
                    f"usa /bola cobrar{' cuando termine el escalón en juego' if sig == 'en_juego' else ''}; si no, "
                    f"repite /bola nueva {coma(v, 2).replace(',00', '')} cuando termine.")
        d["acciones"].append(dict(tipo="nueva", valor=round(v, 2), ts=S.iso(ahora)))
        guardar_ordenes(S, d)
        S.log(f"Bola (69): base de la próxima bola USD {v:.2f} (/bola nueva)")
        return (f"Listo: la próxima bola empieza con {usd(v)} (solo esa; después vuelve a su parte del presupuesto, "
                f"{usd(rec['base_reparto'])}).")
    if que == "cobrar":
        if sig == "en_juego":
            return f"El escalón {k} está en juego: espera el resultado y después usa /bola cobrar."
        if sig != "escalon":
            return "No hay ninguna bola viva que cobrar."
        d["acciones"].append(dict(tipo="cobrar", ts=S.iso(ahora)))
        guardar_ordenes(S, d)
        S.log(f"Bola (69): /bola cobrar en el escalón {k} ({usd(x)})")
        return (f"Listo: la bola se cierra en el escalón {k - 1} de {ESCALONES} y retiras {usd(x)}. La próxima empieza con "
                f"{usd(rec['base_siguiente'])}.")
    return texto_estado(S)


def _abbr(x):
    ab = {"WSH": "WAS", "LAR": "LA", "JAC": "JAX", "LVR": "LV", "OAK": "LV", "SD": "LAC", "STL": "LA", "ARZ": "ARI"}
    x = str(x or "").upper().strip()
    return ab.get(x, x)


def leer_sugerencia(S, sem):
    """La sugerencia con patas más representativa de la semana: la final del domingo, si no la del sábado, si no la
    última a pedido (las que dicen «en juego» no traen patas y se saltan)."""
    d = S.SAL / "matriz"
    rutas = [d / f"bola_semana_{sem}_final.json", d / f"bola_semana_{sem}_sabado.json"]
    rutas += sorted(d.glob(f"bola_semana_{sem}_pedido_*.json"), reverse=True)
    for r in rutas:
        try:
            s = json.loads(r.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if s.get("patas"):
            return s
    return None


def seccion_informe(S, sem, todos=None, cerrada_temporada=False):
    """(texto para Telegram, líneas del informe completo). Descriptivo. Tolera que falte todo."""
    bs = [b for b in boletos_bola(S, todos) if str(b.get("semana")) == str(sem)]
    rec = reconstruir(S, todos=todos, cerrada_temporada=cerrada_temporada)
    sug = leer_sugerencia(S, sem)
    if not bs and not rec["escaleras"] and not sug:
        return "", []
    lin = [f"⛄ Bola de nieve (69) · semana {sem}"]
    esc = {e["id"]: e for x in rec["escaleras"] for e in x["escalones"]}
    if not bs:
        lin.append("Esta semana no se cargó ningún boleto «Bola»" + (" (la bola sugería apostar)." if sug and sug.get("patas") else "."))
    for b in bs:
        e = esc.get(b.get("id"))
        patas = b.get("patas") or []
        dec = [p for p in patas if p.get("res") in ("G", "P", "E")]
        clv = [num(p.get("p_cierre")) - num(p.get("p_carga")) for p in patas
               if num(p.get("p_cierre")) is not None and num(p.get("p_carga")) is not None]
        ev = num((b.get("cierre") or {}).get("ev"))
        partes = [escalon_txt(e) if e else f"«{b.get('nombre')}»: no movió la escalera (otro boleto «Bola» en la misma semana o con un escalón en juego)"]
        if dec:
            partes.append(f"aciertos {sum(1 for p in dec if p['res'] == 'G')} de {len(dec)} (esperados "
                          f"{coma(sum(num(p.get('p_cierre')) or 0 for p in dec), 1)} con el cierre)")
        if clv:
            m = 100 * sum(clv) / len(clv)
            partes.append(f"CLV medio {'+' if m >= 0 else '−'}{coma(abs(m), 1)} pp (n {len(clv)})")
        if ev is not None:
            partes.append(f"costo esperado al cierre {usd(-ev * num(b['monto']))} (EV {('+' if ev >= 0 else '−') + coma(abs(100 * ev), 1)} %)")
        if sug and sug.get("patas"):
            claves = {(_abbr(p.get("equipo")), "ML" if p.get("tipo") == "ML" else "SP",
                       None if p.get("tipo") == "ML" else num(p.get("linea"))) for p in sug["patas"]}
            iguales = sum(1 for p in patas if (_abbr(p.get("equipo")), "ML" if p.get("tipo") == "ML" else "SP",
                                               None if p.get("tipo") == "ML" else num(p.get("linea"))) in claves)
            partes.append(f"iguales a la sugerida: {iguales} de {len(sug['patas'])}")
        lin.append(" · ".join(partes) + ".")
    lin.append(ahora_txt(rec))
    lin.append(totales_txt(rec) + ".")
    lin.append("Descriptivo (69): no cuenta para nada. Alimenta el frente e (30-nov).")
    return "\n".join(lin), lin


# --------------------------------------------------------------------------------------------------------------------
# prueba sin costo (no consulta a nadie ni manda nada)
# --------------------------------------------------------------------------------------------------------------------
def prueba():
    import datetime as dt
    import tempfile
    import types
    ok = True

    def chequeo(nombre, cond, detalle=""):
        nonlocal ok
        ok = ok and bool(cond)
        print(f"  {'ok ' if cond else 'MAL'} {nombre}{(': ' + detalle) if detalle else ''}")

    print(f"{VERSION_BOLA} · prueba sin costo")
    tmp = Path(tempfile.mkdtemp())
    S = types.SimpleNamespace(BASE=tmp, SAL=tmp / "salidas" / "semana", CONFIG=tmp / "semana.ini", TEMPORADA=2026,
                              CARACAS=dt.timezone(dt.timedelta(hours=-4)), log=lambda m: None,
                              iso=lambda t: t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))

    def bol(i, sem, nombre, monto, estado, pago, res=None, cuotas=None, t=None):
        patas = [dict(k=n, tipo="ML", equipo=f"E{n}", res=(res or [None] * 3)[n], cuota=(cuotas or [-200] * 3)[n]) for n in range(3)]
        return dict(id=i, tipo="PARLAY", semana=sem, temporada=2026, fase=2, nombre=nombre, monto=monto, pago=pago,
                    estado=estado, cargado=t or f"2026-11-{sem:02d}T12:00:00Z", patas=patas)

    # escalera completa: 10 → cobra 21,55 (vuelven 10, ruedan 11,55) → 3 cobros más
    todos = [bol(1, 9, "Bola 9", 10, "cobrado", 21.55), bol(2, 10, "bola 10", 11.55, "cobrado", 25.0),
             bol(3, 11, "Bóla once", 25.0, "cobrado", 50.0), bol(4, 12, "BOLA 12", 50.0, "cobrado", 110.0),
             bol(5, 12, "Domingo 14", 66, "perdido", 9000)]
    r = reconstruir(S, todos, {"acciones": []})
    t = r["totales"]
    chequeo("escalera completa de 4 (B1: la base vuelve)", r["viva"] is None and r["escaleras"][0]["fin"] == "completa"
            and abs(r["escaleras"][0]["escalones"][0]["rueda"] - 11.55) < 1e-9 and abs(t["recibido"] - 120.0) < 1e-9
            and abs(t["puesto"] - 10) < 1e-9 and t["completas"] == 1, f"neto {t['neto']:.2f}")
    chequeo("los boletos sin «Bola» no cuentan", len(boletos_bola(S, todos)) == 4)
    # pierde en el escalón 2 → la siguiente empieza con la base
    todos = [bol(1, 9, "Bola", 10, "cobrado", 21.55), bol(2, 10, "Bola", 11.55, "perdido", 30)]
    r = reconstruir(S, todos, {"acciones": []})
    chequeo("pierde en el escalón 2", r["viva"] is None and r["escaleras"][0]["fin"] == "perdida"
            and siguiente(r) == ("nueva", 1, 10.0) and abs(r["totales"]["neto"]) < 1e-9)
    # en juego y semana sin boleto (espera)
    todos = [bol(1, 9, "Bola", 10, "cobrado", 21.55), bol(2, 11, "Bola", 11.55, "vivo", 30)]
    r = reconstruir(S, todos, {"acciones": []})
    chequeo("semana sin boleto: el escalón espera; luego en juego", siguiente(r)[0] == "en_juego" and siguiente(r)[1] == 2)
    # otro boleto Bola mientras un escalón está en juego, y dos en la misma semana
    todos = [bol(1, 9, "Bola", 10, "vivo", 21.55, t="2026-11-08T10:00:00Z"), bol(2, 9, "Bola b", 10, "cobrado", 20, t="2026-11-08T11:00:00Z")]
    r = reconstruir(S, todos, {"acciones": []})
    chequeo("un boleto «Bola» extra no mueve la escalera", len(r["extras"]) == 1 and len(r["escaleras"]) == 1)
    todos = [bol(1, 9, "Bola", 10, "cobrado", 20, t="2026-11-08T10:00:00Z"), bol(2, 9, "Bola b", 10, "cobrado", 20, t="2026-11-09T11:00:00Z")]
    r = reconstruir(S, todos, {"acciones": []})
    chequeo("dos boletos «Bola» en la misma semana: cuenta el primero", len(r["extras"]) == 1 and len(r["escaleras"][0]["escalones"]) == 1)
    # monto distinto del sugerido: la verdad es el boleto
    todos = [bol(1, 9, "Bola", 10, "cobrado", 21.55), bol(2, 10, "Bola", 11.0, "cobrado", 24.0)]
    r = reconstruir(S, todos, {"acciones": []})
    e2 = r["escaleras"][0]["escalones"][1]
    chequeo("monto distinto: manda el boleto y se nota la diferencia", abs(e2["esperado"] - 11.55) < 1e-9
            and abs(r["viva"]["rueda"] - 24.0) < 1e-9 and abs(r["totales"]["recibido"] - 10.55) < 1e-9)
    # /bola cobrar y /bola nueva
    acc = {"acciones": [dict(tipo="cobrar", ts="2026-11-12T00:00:00Z"), dict(tipo="nueva", valor=20, ts="2026-11-12T00:01:00Z")]}
    todos = [bol(1, 9, "Bola", 10, "cobrado", 21.55)]
    r = reconstruir(S, todos, acc)
    chequeo("/bola cobrar y /bola nueva 20", r["escaleras"][0]["fin"] == "cobrada" and siguiente(r) == ("nueva", 1, 20.0)
            and abs(r["totales"]["neto"] - 11.55) < 1e-9)
    # empate: la pata empatada sale del boleto
    b = bol(1, 9, "Bola", 10, "cobrado", 10 * 1.5 * 1.5 * 1.5, res=["G", "E", "G"], cuotas=[-200, -200, -200])
    chequeo("pago con una pata empatada", abs(pago_cobrado(b) - 22.5) < 1e-9)
    b = bol(1, 9, "Bola", 10, "cobrado", 33.75, res=["E", "E", "E"])
    chequeo("pago con todas empatadas = lo apostado", abs(pago_cobrado(b) - 10) < 1e-9)
    b = bol(1, 9, "Bola", 10, "cobrado", 33.75, res=["G", "E", "G"], cuotas=[-200, None, -200])
    chequeo("empatada sin cuota: pago desconocido (no adivina)", pago_cobrado(b) is None)
    # fin de la temporada regular
    r = reconstruir(S, [bol(1, 17, "Bola", 10, "cobrado", 21.55), bol(2, 19, "Bola", 11.55, "cobrado", 25)], {"acciones": []},
                    cerrada_temporada=True)
    chequeo("cierre de la temporada (los playoffs no entran)", r["escaleras"][0]["fin"] == "temporada" and r["viva"] is None
            and len(r["escaleras"][0]["escalones"]) == 1)
    # candidatas: ❌ nunca; COMPRA solo ✅; orden por probabilidad
    mat = {"juegos": [
        {"game_id": "a", "sugerida": {"tipo": "ML", "equipo": "A", "p": 0.80, "q": 0, "D": 1.21, "ev": -0.03, "estado": "❌"}},
        {"game_id": "b", "sugerida": {"tipo": "ML", "equipo": "B", "p": 0.78, "q": 0, "D": 1.25, "ev": -0.015, "estado": "✅"}},
        {"game_id": "c", "sugerida": {"tipo": "ML", "equipo": "C", "p": 0.69, "q": 0, "D": 1.41, "ev": -0.022, "estado": "⚠️"}},
        {"game_id": "d", "sugerida": {"tipo": "COMPRA", "equipo": "D", "p": 0.70, "q": 0.04, "D": 1.3, "ev": -0.035, "estado": "❌"}},
        {"game_id": "e", "sugerida": {"tipo": "SP", "equipo": "E", "linea": 7.0, "p": 0.548, "q": 0, "D": 1.885, "ev": -0.0199, "estado": "✅"}},
        {"game_id": "f", "sugerida": None}]}
    c = candidatas(mat)
    chequeo("candidatas: ❌ nunca, ordenadas por probabilidad", [x["j"]["game_id"] for x in c] == ["b", "c", "e"])
    chequeo("P(completar) desde el escalón 1 (4 patas: 39,3 % por escalón, H48)", abs(p_completar(0.30, 1) - 0.30 * 0.393 ** 3) < 1e-12)
    # /bola nueva vale solo para la próxima bola
    acc = {"acciones": [dict(tipo="nueva", valor=20, ts="2026-11-01T00:00:00Z")]}
    todos = [bol(1, 9, "Bola", 20, "perdido", 50), bol(2, 10, "Bola", 10, "vivo", 30)]
    r = reconstruir(S, todos, acc)
    chequeo("/bola nueva N vale solo para la próxima", r["escaleras"][0]["base_sugerida"] == 20 and r["escaleras"][1]["base_sugerida"] == 10.0)
    r = reconstruir(S, [], {"acciones": []}, base=68.0)
    chequeo("la base sale del reparto (USD 68 con 150)", siguiente(r) == ("nueva", 1, 68.0))
    print("RESULTADO:", "OK" if ok else "FALLÓ")
    return 0 if ok else 1


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "prueba":
        sys.exit(prueba())
    print(__doc__)
