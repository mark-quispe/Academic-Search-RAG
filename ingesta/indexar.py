"""Carga del dataset en ChromaDB (embeddings multilingual-e5-small, en CPU).

Versión inicial: reconstruye las dos colecciones desde cero en cada ejecución.
"""

import shutil

import chromadb
from sentence_transformers import SentenceTransformer

from . import config
from .modelos import Curso, Fragmento


def ficha(c: Curso) -> str:
    """Texto que se vectoriza por curso: datos principales + sumilla."""
    partes = [f"{c.curso} ({c.codigo})" if c.codigo else c.curso,
              f"Carrera de {c.carrera}, plan {c.plan}.",
              f"Ciclo {c.ciclo}." if c.ciclo else "Curso electivo.",
              f"Créditos: {c.creditos:g}." if c.creditos is not None else ""]
    if c.prerrequisitos_texto:
        partes.append(f"Prerrequisitos: {c.prerrequisitos_texto.replace(' | ', ', ')}.")
    if c.sumilla:
        partes.append(f"Sumilla: {c.sumilla}")
    return " ".join(p for p in partes if p)


def _metadatos(d: dict) -> dict:
    """Chroma solo acepta valores escalares no nulos."""
    out = {}
    for k, v in d.items():
        if v is None or v == "":
            continue
        out[k] = "; ".join(v) if isinstance(v, list) else v
    return out


def indexar(cursos: list[Curso], fragmentos: list[Fragmento]) -> dict:
    if config.CHROMA.exists() and any(p.name != ".gitkeep" for p in config.CHROMA.iterdir()):
        shutil.rmtree(config.CHROMA_RESPALDO, ignore_errors=True)
        shutil.copytree(config.CHROMA, config.CHROMA_RESPALDO)

    modelo = SentenceTransformer(config.MODELO_EMBEDDINGS, device="cpu")
    cliente = chromadb.PersistentClient(path=str(config.CHROMA))

    lotes = {
        "cursos": ([c.id for c in cursos], [ficha(c) for c in cursos],
                   [_metadatos(c.model_dump(exclude={"sumilla"})) for c in cursos]),
        "fragmentos": ([f.id for f in fragmentos], [f.texto for f in fragmentos],
                       [_metadatos(f.model_dump(exclude={"id", "texto"})) for f in fragmentos]),
    }
    for nombre, (ids, textos, metas) in lotes.items():
        try:
            cliente.delete_collection(nombre)
        except Exception:
            pass
        col = cliente.create_collection(nombre, metadata={"hnsw:space": "cosine"})
        vectores = modelo.encode([f"passage: {t}" for t in textos], batch_size=32,
                                 normalize_embeddings=True, show_progress_bar=True)
        for i in range(0, len(ids), 1000):
            col.add(ids=ids[i:i + 1000], documents=textos[i:i + 1000],
                    metadatas=metas[i:i + 1000], embeddings=vectores[i:i + 1000].tolist())
    return {n: cliente.get_collection(n).count() for n in lotes}
