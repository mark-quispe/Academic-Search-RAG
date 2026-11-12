"""Ejecuta la ingesta completa.

    uv run python -m ingesta             # PDF -> data/processed (dataset)
    uv run python -m ingesta --indexar   # además carga el dataset en ChromaDB
"""

import argparse
import json
import sys
import time
from collections import Counter
from datetime import datetime

import pandas as pd
import psutil
from pydantic import ValidationError

from . import config
from .fragmentos import fragmentar
from .lectura import inventario, leer_paginas
from .mallas import (aplicar, leer_debe_decir, leer_lista_2026, leer_lista_codigos, leer_ocr, leer_tablas,
                     resolver_prerrequisitos)
from .modelos import Curso
from .sumillas import extraer_sumillas
from .texto import clave


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--indexar", action="store_true", help="cargar el dataset en ChromaDB")
    args = ap.parse_args()

    tiempos, t0 = {}, time.perf_counter()
    marca = lambda etapa: tiempos.__setitem__(etapa, max(0.0, round(time.perf_counter() - t0 - sum(tiempos.values()), 2)))

    # 0. Inventario
    docs = inventario()
    print(f"[0] Inventario: {len(docs)} documentos en sources.csv")
    marca("inventario")

    # 1. Fragmentos de texto (todos los documentos)
    fragmentos = []
    for doc in docs.values():
        fragmentos += fragmentar(doc, leer_paginas(doc))
    print(f"[1] Fragmentos: {len(fragmentos)}")
    marca("fragmentos")

    # 2. Mallas: plan base + modificaciones en orden
    planes: dict[tuple, dict] = {}
    leidos: dict[tuple, set] = {}
    for m in config.MALLAS:
        doc = docs[m["archivo"]]
        if m["formato"] == "tabla":
            nuevos = leer_tablas(doc)
        elif m["formato"] == "debe_decir":
            nuevos = leer_debe_decir(doc)
        elif m["formato"] == "lista_codigos":
            nuevos = leer_lista_codigos(doc, *m["paginas"])
        elif m["formato"] == "ocr":
            nombres = [c["curso"] for p in planes.values() for c in p.values()]
            nuevos = leer_ocr(doc, nombres)
        else:
            nuevos = leer_lista_2026(doc, *m["paginas"])
        clave_plan = (doc.carrera, doc.plan)
        previos = leidos.setdefault(clave_plan, set())
        es_modificacion = bool(previos - {doc.archivo})
        previos.add(doc.archivo)
        aplicar(planes.setdefault(clave_plan, {}), nuevos, doc.archivo, es_modificacion)
        print(f"[2] Malla {doc.archivo}: {len(nuevos)} filas")
    cursos = [c for plan in planes.values() for c in plan.values()]
    sin_resolver = resolver_prerrequisitos(cursos)
    marca("mallas")

    # 3. Sumillas
    for s in config.SUMILLAS:
        doc = docs[s["archivo"]]
        desde, hasta = s.get("paginas", (1, 10_000))
        encontradas = extraer_sumillas(doc, cursos, desde, hasta)
        for c in cursos:
            k = c["codigo"] or clave(c["curso"])
            if (c["carrera"], c["plan"]) == (doc.carrera, doc.plan) and k in encontradas and not c.get("sumilla"):
                c["sumilla"], c["sumilla_pagina"] = encontradas[k]
                c["sumilla_documento"] = doc.archivo
        print(f"[3] Sumillas {doc.archivo}: {len(encontradas)}")
    marca("sumillas")

    # 4. Validación (Pydantic)
    validos, errores = [], []
    for c in cursos:
        try:
            validos.append(Curso(**c))
        except ValidationError as e:
            errores.append({"curso": c.get("curso"), "documento": c.get("documento"), "error": str(e.errors()[0]["msg"])})
    ids = Counter(c.id for c in validos)
    duplicados = [i for i, n in ids.items() if n > 1]
    print(f"[4] Cursos válidos: {len(validos)}  |  con error: {len(errores)}  |  ids duplicados: {len(duplicados)}")
    marca("validacion")

    # 5. Dataset
    config.PROCESSED.mkdir(parents=True, exist_ok=True)
    filas = []
    for c in validos:
        d = c.model_dump()
        d["prerrequisitos"] = "; ".join(d["prerrequisitos"])
        filas.append({"id": c.id, **d})
    df = pd.DataFrame(filas).sort_values(["carrera", "plan", "ciclo", "codigo"])
    df.to_csv(config.PROCESSED / "cursos.csv", index=False, encoding="utf-8")
    with open(config.PROCESSED / "fragmentos.jsonl", "w", encoding="utf-8") as f:
        for fr in fragmentos:
            f.write(fr.model_dump_json() + "\n")
    print(f"[5] Dataset guardado en {config.PROCESSED}")
    marca("dataset")

    # 6. Indexación (opcional)
    colecciones = {}
    if args.indexar:
        from .indexar import indexar  # importa torch solo si hace falta
        colecciones = indexar(validos, fragmentos)
        print(f"[6] ChromaDB: {colecciones}")
        marca("indexacion")

    # Reporte de calidad y consumo
    resumen = (df.groupby(["carrera", "plan"])
                 .agg(cursos=("id", "count"), con_sumilla=("sumilla", lambda s: int((s != "").sum())),
                      sin_creditos=("creditos", lambda s: int(s.isna().sum())),
                      creditos_obligatorios=("creditos", "sum"))
                 .reset_index())
    obligatorios = df[df.tipo == "obligatorio"].groupby(["carrera", "plan"])["creditos"].sum()
    resumen["creditos_obligatorios"] = [round(float(obligatorios.get((r.carrera, r.plan), 0)), 1)
                                        for r in resumen.itertuples()]
    reporte = {
        "fecha": datetime.now().isoformat(timespec="seconds"),
        "documentos": len(docs),
        "fragmentos": len(fragmentos),
        "fragmentos_por_documento": Counter(f.documento for f in fragmentos),
        "cursos": len(validos),
        "por_plan": resumen.to_dict(orient="records"),
        "prerrequisitos_sin_resolver": sin_resolver,
        "errores_validacion": errores,
        "ids_duplicados": duplicados,
        "colecciones_chroma": colecciones,
        "tiempos_s": tiempos,
        "ram_mb": round(psutil.Process().memory_info().rss / 2**20),
    }
    config.LOGS.mkdir(exist_ok=True)
    (config.LOGS / "ingesta.json").write_text(json.dumps(reporte, ensure_ascii=False, indent=2), encoding="utf-8")
    print(resumen.to_string(index=False))
    print(f"Tiempos (s): {tiempos}  |  RAM: {reporte['ram_mb']} MB  |  reporte: logs/ingesta.json")


if __name__ == "__main__":
    main()
