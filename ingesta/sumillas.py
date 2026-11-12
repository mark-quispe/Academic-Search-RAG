"""Separación de sumillas por curso.

Cada documento de sumillas es una secuencia: TÍTULO DEL CURSO (en mayúsculas, o "CÓDIGO. Nombre"
en el Plan 2026) seguido de su descripción. Un título se reconoce comparándolo (rapidfuzz) con los
nombres de los cursos ya extraídos de la malla del mismo plan.
"""

import re

from rapidfuzz import fuzz, process

from .lectura import Documento, leer_paginas
from .texto import clave

RE_TITULO_2026 = re.compile(r"^([A-Z]{2,3}[0-9A-Z]{2,3})\.\s+(.+)$")
MIN_CARACTERES = 60


def _es_titulo(linea: str) -> bool:
    letras = [c for c in linea if c.isalpha()]
    return len(letras) >= 4 and len(linea) <= 90 and sum(c.isupper() for c in letras) / len(letras) >= 0.9


def _romanos(s: str) -> list[str]:
    return re.findall(r"\b[IVX]+\b", s)


def _buscar(titulo: str, nombres: dict[str, str]) -> str | None:
    k = clave(titulo)
    if k in nombres:
        return nombres[k]
    mejor = process.extractOne(k, list(nombres), scorer=fuzz.ratio, score_cutoff=90)
    # "CÁLCULO III" no debe confundirse con "CÁLCULO II"
    if mejor and _romanos(mejor[0]) == _romanos(k):
        return nombres[mejor[0]]
    return None


def extraer_sumillas(doc: Documento, cursos: list[dict], desde: int = 1, hasta: int = 10_000) -> dict[str, tuple]:
    """Devuelve {clave del curso: (sumilla, página)} para los cursos del mismo plan."""
    del_plan = [c for c in cursos if c["carrera"] == doc.carrera and c["plan"] == doc.plan]
    nombres = {clave(c["curso"]): (c["codigo"] or clave(c["curso"])) for c in del_plan}
    codigos = {c["codigo"] for c in del_plan if c["codigo"]}

    resultado: dict[str, tuple] = {}
    actual, pagina_actual, buffer = None, 0, []
    pendiente: list[str] = []  # títulos en mayúsculas que ocupan varias líneas

    def cerrar():
        texto = " ".join(buffer).strip()
        if actual and len(texto) >= MIN_CARACTERES and actual not in resultado:
            resultado[actual] = (texto, pagina_actual)

    for num, texto in leer_paginas(doc):
        if not desde <= num <= hasta:
            continue
        for linea in texto.splitlines():
            m = RE_TITULO_2026.match(linea)
            if m and m.group(1) in codigos and ". . ." not in linea:
                cerrar()
                actual, pagina_actual, buffer = m.group(1), num, []
                continue
            if _es_titulo(linea):
                pendiente.append(linea)
                encontrado = _buscar(" ".join(pendiente), nombres) or _buscar(linea, nombres)
                if encontrado:
                    cerrar()
                    actual, pagina_actual, buffer, pendiente = encontrado, num, [], []
                continue
            if pendiente:  # títulos que no son cursos (SEMESTRE, AÑO...) cortan la sumilla
                cerrar()
                actual, buffer, pendiente = None, [], []
            if actual:
                buffer.append(linea)
    cerrar()
    return resultado
