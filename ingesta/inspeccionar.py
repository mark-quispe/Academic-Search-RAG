"""Muestra cómo está formada la base vectorial y hace una búsqueda de prueba (solo lectura).

    uv run python -m ingesta.inspeccionar "¿dónde veo pilas y colas?"
    uv run python -m ingesta.inspeccionar "¿dónde veo pilas y colas?" --carrera computacion --plan 2018

Sin --carrera ni --plan busca en todas las carreras y planes.
Todavía no responde: devuelve los cursos más parecidos (la respuesta redactada la hará el LLM).
"""

import argparse
import os
import sys

os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")

import chromadb
from sentence_transformers import SentenceTransformer
from transformers.utils import logging as hf_logging

from . import config
from .texto import clave

hf_logging.set_verbosity_error()


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Inspección y búsqueda de prueba en ChromaDB")
    ap.add_argument("pregunta", nargs="?", default="¿En qué curso veré pilas y colas?")
    ap.add_argument("--carrera", help="nombre o parte del nombre: computacion, estadistica, matematica")
    ap.add_argument("--plan", help="2018, 2023 o 2026")
    ap.add_argument("-n", type=int, default=5, help="número de resultados")
    ap.add_argument("--sin-detalle", action="store_true", help="omitir la descripción de las colecciones")
    args = ap.parse_args()

    cliente = chromadb.PersistentClient(path=str(config.CHROMA))
    cursos = cliente.get_collection("cursos")

    if not args.sin_detalle:
        for nombre in ("cursos", "fragmentos"):
            col = cliente.get_collection(nombre)
            ej = col.get(limit=1, include=["documents", "metadatas", "embeddings"])
            print(f"\n=== Colección '{nombre}': {col.count()} registros")
            print("Metadatos:", ej["metadatas"][0])
            print("Texto:", ej["documents"][0][:200], "...")
            print(f"Vector: {len(ej['embeddings'][0])} dimensiones -> "
                  f"{[round(float(x), 4) for x in ej['embeddings'][0][:4]]} ...")

    # Filtros: se aceptan nombres parciales y sin tildes ("computacion" -> "Computación Científica")
    metas = cursos.get(include=["metadatas"])["metadatas"]
    disponibles = sorted({(m["carrera"], m["plan"]) for m in metas})
    condiciones = []
    if args.carrera:
        carreras = sorted({c for c, _ in disponibles if clave(args.carrera) in clave(c)})
        if not carreras:
            print(f"Carrera '{args.carrera}' no encontrada. Disponibles: {sorted({c for c, _ in disponibles})}")
            return
        condiciones.append({"carrera": carreras[0]})
    if args.plan:
        if args.plan not in {p for _, p in disponibles}:
            print(f"Plan '{args.plan}' no encontrado. Disponibles: {sorted({p for _, p in disponibles})}")
            return
        condiciones.append({"plan": args.plan})
    filtro = None if not condiciones else condiciones[0] if len(condiciones) == 1 else {"$and": condiciones}

    modelo = SentenceTransformer(config.MODELO_EMBEDDINGS, device="cpu")
    vector = modelo.encode(f"query: {args.pregunta}", normalize_embeddings=True).tolist()
    res = cursos.query(query_embeddings=[vector], n_results=args.n, where=filtro)

    print(f"\n=== Búsqueda: '{args.pregunta}'")
    print(f"    Filtro: {filtro or 'ninguno (todas las carreras y planes)'}")
    if not res["ids"][0]:
        print("    Sin resultados para ese filtro.")
        return
    for meta, dist in zip(res["metadatas"][0], res["distances"][0]):
        ciclo = f"ciclo {meta['ciclo']}" if meta["ciclo"] else "electivo"
        print(f"  {1 - dist:.3f}  {meta['curso']} ({meta.get('codigo', '-')}) · {meta['carrera']} {meta['plan']} · "
              f"{ciclo} · {meta.get('creditos', '-')} cr · {meta['documento']} p.{meta['pagina']}")


if __name__ == "__main__":
    main()
