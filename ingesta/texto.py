"""Limpieza y normalización de texto extraído de los PDF."""

import re
import unicodedata

_VOCALES = {"a": "á", "e": "é", "i": "í", "o": "ó", "u": "ú",
            "A": "Á", "E": "É", "I": "Í", "O": "Ó", "U": "Ú"}

# Líneas repetidas en cada página que no aportan contenido
_RUIDO = re.compile(
    r"copia auténtica imprimible|Art\. 25 de D\.S|Complementaria Final del D\.S|"
    r"autenticidad e inte|spsgd\.unmsm|ingresando el siguiente código|"
    r"Calle Germán Amezaga|Central:\s*\(511\)|^\s*// Ref\.|^\s*Foja \d+\s*$|"
    r"^\s*Universidad Nacional Mayor de San Marcos \(UNMSM\)\s*$|"
    r"^\s*Escuela Profesional de Computación Científica, Curriculo 2026\s*$",
    re.IGNORECASE,
)
_CORREO = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")


def arreglar_acentos_latex(s: str) -> str:
    """El PDF generado con LaTeX separa el acento de la vocal: 'Cient´ıfica' -> 'Científica'."""
    s = s.replace("´ı", "í")
    s = re.sub(r"´\s?([aeiouAEIOU])", lambda m: _VOCALES[m.group(1)], s)
    s = re.sub(r"˜\s?n", "ñ", s)
    s = re.sub(r"˜\s?N", "Ñ", s)
    s = re.sub(r"¨\s?u", "ü", s)
    return s


_GRAVES = str.maketrans("àèìòùÀÈÌÒÙ", "áéíóúÁÉÍÓÚ")


def normalizar_tildes(s: str) -> str:
    """En español no hay tildes graves: 'Càlculo' -> 'Cálculo' (error de tipeo en algunos PDF)."""
    return s.translate(_GRAVES)


def contar_correos(s: str) -> int:
    return len(_CORREO.findall(s))


def limpiar_pagina(s: str) -> str:
    """Normaliza el texto de una página: acentos, ruido institucional, correos y espacios."""
    s = normalizar_tildes(unicodedata.normalize("NFC", arreglar_acentos_latex(s)))
    s = _CORREO.sub("[correo]", s)
    lineas = []
    for linea in s.splitlines():
        linea = re.sub(r"\s+", " ", linea).strip()
        if linea and not _RUIDO.search(linea):
            lineas.append(linea)
    return "\n".join(lineas)


def dedoblar(s: str) -> str:
    """Corrige texto con caracteres duplicados por el PDF: 'PPrrooggrraammaa' -> 'Programa'."""
    palabras = []
    for p in s.split(" "):
        if len(p) >= 4 and len(p) % 2 == 0 and p[0::2] == p[1::2]:
            p = p[0::2]
        palabras.append(p)
    return " ".join(palabras)


def clave(s: str) -> str:
    """Forma canónica para comparar nombres: sin tildes, mayúsculas, sin puntuación."""
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^A-Za-z0-9]+", " ", s.upper())
    return re.sub(r"\s+", " ", s).strip()


def titulo(s: str) -> str:
    """'ESTRUCTURA DE DATOS' -> 'Estructura de Datos' (respeta números romanos)."""
    menores = {"de", "del", "la", "las", "los", "el", "y", "e", "en", "a", "al", "para", "por", "con"}
    out = []
    for i, p in enumerate(s.split()):
        if re.fullmatch(r"[IVX]+", p.upper()) and i > 0:
            out.append(p.upper())
        elif p.lower() in menores and i > 0:
            out.append(p.lower())
        else:
            out.append(p[:1].upper() + p[1:].lower())
    return " ".join(out)
