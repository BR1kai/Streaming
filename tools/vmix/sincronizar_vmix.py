#!/usr/bin/env python3
"""Sincronizar vMix: LEE vMix por su API y compara con lo que dice la guía.
No cambia nada en vMix (solo hace peticiones GET a /api).

  python sincronizar_vmix.py            -> informe de diferencias
  python sincronizar_vmix.py --adoptar  -> además guarda lo leído como nuevo
                                           «esperado» (tras revisar el informe)
Solo usa la biblioteca estándar de Python 3.8+.
"""
import json, sys, time, datetime, pathlib, urllib.request
import xml.etree.ElementTree as ET

AQUI = pathlib.Path(__file__).resolve().parent
ESPERADO = AQUI / "esperado.json"
SNAP = AQUI / "instantaneas"


def leer_xml(url, texto=None):
    if texto is not None:
        return texto
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.read().decode("utf-8", "replace")


def interpretar(xml):
    """Devuelve un resumen simple y estable del estado de vMix."""
    raiz = ET.fromstring(xml)
    ins = {}
    for e in raiz.iter("input"):
        n = e.get("number")
        if not n:
            continue
        capas = []
        for o in e.findall("overlay"):
            capas.append({"indice": o.get("index"), "entrada": o.get("key") or o.get("number")})
        ins[n] = {
            "titulo": (e.get("title") or (e.text or "")).strip(),
            "tipo": e.get("type") or "",
            "estado": e.get("state") or "",
            "capas": capas,
        }
    g = lambda t: (raiz.findtext(t) or "").strip()
    return {
        "version": g("version"), "edicion": g("edition"), "preset": g("preset"),
        "activa": g("active"), "preview": g("preview"), "inputs": ins,
    }


def comparar(est, esp):
    dif, avisos, ok = [], [], 0
    ins = est["inputs"]
    if len(ins) != esp["total_inputs"]:
        dif.append(f"Hay {len(ins)} inputs y la guía dice {esp['total_inputs']}.")
    else:
        ok += 1
    for n, titulo in esp["inputs"].items():
        i = ins.get(n)
        if not i:
            dif.append(f"Input {n}: falta (la guía dice «{titulo}»).")
        elif i["titulo"].strip().lower() != titulo.strip().lower():
            dif.append(f"Input {n}: se llama «{i['titulo']}» y la guía dice «{titulo}».")
        else:
            ok += 1
    for n in ins:
        if n not in esp["inputs"]:
            dif.append(f"Input {n} «{ins[n]['titulo']}»: existe en vMix y no está en la guía.")
    ndi = sorted(int(n) for n, i in ins.items() if i["tipo"].upper() == "NDI")
    if ndi != sorted(esp["ndi"]):
        dif.append(f"Inputs NDI en vMix: {ndi}; la guía dice {sorted(esp['ndi'])}.")
    else:
        ok += 1
    for n in esp["mixes"]:
        t = ins.get(n, {}).get("tipo", "")
        if n in ins and t.lower() != "mix":
            dif.append(f"Input {n} debería ser un Mix y es «{t}».")
        elif n in ins:
            ok += 1
    for n, capas in esp["presets"].items():
        if n not in ins:
            continue
        reales = sorted({int(c["entrada"]) for c in ins[n]["capas"] if (c["entrada"] or "").isdigit()})
        if not ins[n]["capas"]:
            avisos.append(f"Input {n}: no pude leer sus capas por la API; compruébalo a mano ({capas}).")
        elif reales != sorted(capas):
            dif.append(f"Input {n}: sus capas son {reales} y la guía dice {sorted(capas)}.")
        else:
            ok += 1
    if esp["chyron_sala"] and str(esp["chyron_sala"]) in ins:
        ok += 1
    if esp["inputs"].get("7") == esp["inputs"].get("14"):
        avisos.append("Los inputs 7 y 14 figuran en la guía con el mismo nombre; aclara cuál es el chyron de la sala.")
    return ok, dif, avisos


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    adoptar = "--adoptar" in sys.argv
    esp = json.loads(ESPERADO.read_text(encoding="utf-8"))
    archivo = next((a for a in sys.argv[1:] if not a.startswith("--")), None)
    try:
        xml = leer_xml(esp["api"], pathlib.Path(archivo).read_text(encoding="utf-8") if archivo else None)
    except Exception as e:
        print("No puedo leer vMix:", e)
        print("¿Está vMix abierto y Web Controller activado (Settings > Web Controller)?")
        return 2
    est = interpretar(xml)
    SNAP.mkdir(exist_ok=True)
    marca = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    (SNAP / f"vmix-{marca}.xml").write_text(xml, encoding="utf-8")
    (SNAP / f"vmix-{marca}.json").write_text(json.dumps(est, ensure_ascii=False, indent=1), encoding="utf-8")
    ok, dif, avisos = comparar(est, esp)
    print(f"vMix {est['version']} {est['edicion']} · proyecto: {est['preset']}")
    print(f"Comprobaciones correctas: {ok}\n")
    if dif:
        print(f"DIFERENCIAS CON LA GUÍA ({len(dif)}):")
        for d in dif: print("  ✗", d)
    else:
        print("✓ vMix coincide con la guía.")
    if avisos:
        print("\nAVISOS:")
        for a in avisos: print("  !", a)
    print(f"\nInstantánea guardada en: instantaneas\\vmix-{marca}.json")
    if adoptar and dif:
        esp["inputs"] = {n: i["titulo"] for n, i in est["inputs"].items()}
        esp["total_inputs"] = len(est["inputs"])
        esp["ndi"] = sorted(int(n) for n, i in est["inputs"].items() if i["tipo"].upper() == "NDI")
        ESPERADO.write_text(json.dumps(esp, ensure_ascii=False, indent=1), encoding="utf-8")
        print("Guardado como nuevo «esperado». Pásame el informe para actualizar la guía.")
    return 1 if dif else 0


if __name__ == "__main__":
    sys.exit(main())
