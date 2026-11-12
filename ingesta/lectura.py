"""Inventario (sources.csv) y lectura de texto por página (PyMuPDF)."""

import csv
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from . import config
from .texto import contar_correos, limpiar_pagina

pymupdf.TOOLS.mupdf_display_errors(False)  # PDF con contenido mal formado generan avisos sin importancia


@dataclass
class Documento:
    archivo: str  # nombre del PDF
    ruta: Path
    carrera: str
    plan: str
    tipo: str  # descripción del documento en sources.csv
    estado: str  # oficial / no_oficial
    calidad: str  # texto_nativo / ocr


def inventario() -> dict[str, Documento]:
    docs = {}
    with open(config.SOURCES, encoding="utf-8") as f:
        for fila in csv.DictReader(f):
            ruta = config.DATA / fila["archivo"]
            nombre = ruta.name
            docs[nombre] = Documento(
                archivo=nombre,
                ruta=ruta,
                carrera=fila["carrera"],
                plan=fila["plan"],
                tipo=fila["tipo"],
                estado="no_oficial" if nombre in config.NO_OFICIALES else "oficial",
                calidad="ocr" if nombre in config.ESCANEADOS else "texto_nativo",
            )
    faltan = [d.archivo for d in docs.values() if not d.ruta.exists()]
    if faltan:
        raise FileNotFoundError(f"PDF registrados en sources.csv que no existen: {faltan}")
    return docs


def leer_paginas(doc: Documento) -> list[tuple[int, str]]:
    """Devuelve [(número de página, texto limpio)].

    Se excluyen las páginas con listas de correos (datos personales de docentes o estudiantes).
    En los documentos escaneados se usa el texto reconocido por OCR.
    """
    if doc.archivo in config.ESCANEADOS:
        from .ocr import leer_escaneado
        return [(n, limpiar_pagina(t)) for n, t in leer_escaneado(doc)["paginas"]]
    paginas = []
    with pymupdf.open(doc.ruta) as pdf:
        for i, pagina in enumerate(pdf, start=1):
            crudo = pagina.get_text()
            if contar_correos(crudo) >= 3:
                continue
            paginas.append((i, limpiar_pagina(crudo)))
    return paginas
