"""Extracción de la malla curricular: PDF -> registros de cursos.

Tres lectores según el formato del documento (ver config.MALLAS):
  - leer_tablas:     tablas nativas (pdfplumber). Sirve para todos los planes 2018 y 2023.
  - leer_debe_decir: resoluciones "DICE / DEBE DECIR" (solo páginas DEBE DECIR).
  - leer_lista_2026: Plan 2026 (documento LaTeX, texto lineal).

Las tablas de cada escuela tienen columnas distintas (orden, nombres, celdas combinadas),
por eso cada celda se clasifica por su CONTENIDO (código, número, texto) y el encabezado
solo se usa para saber en qué posición están los créditos.
"""

import re

import pdfplumber
from rapidfuzz import fuzz, process

from .lectura import Documento, leer_paginas
from .texto import clave, dedoblar, normalizar_tildes, titulo

ORDINALES = {
    "PRIMER": 1, "PRIMERO": 1, "SEGUNDO": 2, "TERCER": 3, "TERCERO": 3, "CUARTO": 4,
    "QUINTO": 5, "SEXTO": 6, "SEPTIMO": 7, "SETIMO": 7, "OCTAVO": 8, "NOVENO": 9, "DECIMO": 10,
}
ROMANOS = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10}

RE_CICLO = re.compile(r"\b(" + "|".join(ORDINALES) + r")\s+(SEMESTRE|CICLO)\b")
RE_CODIGO = re.compile(r"^(?=(?:.*\d){3})[A-Z0-9]{5,8}$")  # 183044, CBO101, 23EG14, 18141E1
RE_NUMERO = re.compile(r"^(\d{1,2}(\.\d+)?|-+|—)$")
RE_TEXTO = re.compile(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]{3,}")
RE_NO_CURSO = re.compile(r"^(TOTAL.*|ELECTIVOS?( [IVX]+)?|CURSOS ELECTIVOS)$")


# ---------------------------------------------------------------- tablas nativas

def _celda(c: str | None) -> str:
    return normalizar_tildes(dedoblar(re.sub(r"\s+", " ", (c or "").replace("\n", " ")).strip()))


def _es_codigo(c: str) -> bool:
    return bool(c) and all(RE_CODIGO.match(t) for t in c.split())


def _etiqueta(c: str) -> str | None:
    """Tipo de columna según el texto del encabezado."""
    k = clave(c)
    if not k:
        return None
    if "REQUISITO" in k:
        return "req"
    if k.startswith("CR"):
        return "cr"
    if k in {"T", "P", "L", "HT", "HP", "TH", "PH", "P L", "TOTAL", "HORAS SEMANALES"}:
        return "horas"
    if "CODIGO" in k or k in {"N", "NO"} or "ASIGNATURA" in k or k == "TIPO":
        return "otro"
    return None


def _posicion_creditos(encabezados: list[list[str]]) -> str | None:
    """'primero' o 'ultimo' entre las columnas numéricas; None si la tabla no tiene créditos."""
    numericas = []
    for fila in encabezados:
        for i, c in enumerate(fila):
            e = _etiqueta(c)
            if e in ("cr", "horas"):
                numericas.append((i, e))
    numericas.sort()
    tipos = [e for _, e in numericas]
    if "cr" not in tipos:
        return None
    return "primero" if tipos[0] == "cr" else "ultimo"


def _a_float(c: str) -> float | None:
    try:
        return float(c)
    except ValueError:
        return None


def _filas_a_cursos(filas, doc: Documento, pagina: int, estado: dict) -> list[dict]:
    """Convierte las filas de UNA tabla en cursos. `estado` guarda el contexto entre tablas."""
    cursos = []
    ciclo = None  # cada tabla empieza sin ciclo; lo fija su título ("PRIMER SEMESTRE")
    electivo_ctx = False
    encabezado_actual: list[list[str]] = []

    for fila in filas:
        celdas = [_celda(c) for c in fila]
        llenas = [c for c in celdas if c]
        if not llenas:
            continue
        unido = clave(" ".join(llenas))

        # Título de bloque: semestre, electivos o línea de especialización
        m = RE_CICLO.search(unido)
        if m and not any(_es_codigo(c) for c in llenas):
            ciclo, electivo_ctx = ORDINALES[m.group(1)], False
        if "ELECTIVA" in unido or "LINEA DE ESPECIALIZACION" in unido:
            if not any(_es_codigo(c) for c in llenas):
                ciclo, electivo_ctx = None, True

        # Encabezado: dos o más celdas reconocidas como nombres de columna
        if sum(1 for c in llenas if _etiqueta(c)) >= 2 and not any(_es_codigo(c) for c in llenas):
            encabezado_actual.append(celdas)
            estado["pos_creditos"] = _posicion_creditos(encabezado_actual)
            continue
        encabezado_actual = []

        # Fila de datos: clasificar cada celda por su contenido
        primer_num = next((i for i, c in enumerate(llenas) if RE_NUMERO.match(c)), len(llenas))
        codigos_propios, codigos_req, numeros, textos = [], [], [], []
        tipo_col = None
        for i, c in enumerate(llenas):
            if _es_codigo(c):
                (codigos_propios if i < primer_num else codigos_req).append(c)
            elif RE_NUMERO.match(c):
                numeros.append(c)
            elif i == 0 and c in ROMANOS:
                ciclo = ROMANOS[c]
            elif clave(c) in ("OBLIGATORIO", "ELECTIVO") and textos:
                tipo_col = clave(c).lower()
            elif RE_TEXTO.search(c):
                textos.append(c)
        if not textos or (not numeros and not codigos_propios):
            continue  # títulos de grupo, notas al pie
        nombre = textos[0]
        if RE_NO_CURSO.match(clave(nombre)):
            continue

        creditos = None
        pos = estado.get("pos_creditos")
        if numeros and pos:
            creditos = _a_float(numeros[0] if pos == "primero" else numeros[-1])

        tipo = tipo_col or ("electivo" if electivo_ctx or ciclo is None else "obligatorio")
        req = " | ".join(textos[1:] + codigos_req)
        req = "" if re.fullmatch(r"[-\s|]*", req) else req
        cursos.append({
            "carrera": doc.carrera, "plan": doc.plan,
            "codigo": codigos_propios[0] if codigos_propios else "",
            "curso": titulo(nombre), "ciclo": ciclo or 0, "creditos": creditos, "tipo": tipo,
            "prerrequisitos_texto": req, "documento": doc.archivo, "pagina": pagina,
            "estado": doc.estado,
        })
    return cursos


def leer_tablas(doc: Documento, solo_paginas: set[int] | None = None) -> list[dict]:
    cursos, estado = [], {}
    with pdfplumber.open(doc.ruta) as pdf:
        for num, pagina in enumerate(pdf.pages, start=1):
            if solo_paginas is not None and num not in solo_paginas:
                continue
            for tabla in pagina.extract_tables():
                cursos += _filas_a_cursos(tabla, doc, num, estado)
    return cursos


def leer_debe_decir(doc: Documento) -> list[dict]:
    paginas = {n for n, t in leer_paginas(doc) if "DEBE DECIR" in t.upper()}
    return leer_tablas(doc, solo_paginas=paginas)


# ---------------------------------------------------------------- Plan 2026 (LaTeX)

RE_COD_2026 = re.compile(r"^(?=.*\d)[A-Z]{2,3}[0-9A-Z]{2,3}$")
RE_REQ_2026 = re.compile(r"^([A-Z]{2,3}[0-9A-Z]{2,3}) \(|^\d+\s?[cC]r")
AREAS_2026 = {"Específicos", "Estudios generales", "Especialización"}


def leer_lista_2026(doc: Documento, desde: int, hasta: int) -> list[dict]:
    """Secuencia por curso: CÓDIGO / nombre (Pág N) / Área / HT / HP / CR / TIPO / requisitos."""
    cursos, ciclo = [], 0
    for num, texto in leer_paginas(doc):
        if not desde <= num <= hasta:
            continue
        lineas = texto.splitlines()
        i = 0
        while i < len(lineas):
            linea = lineas[i]
            m = RE_CICLO.search(clave(linea))
            if m and len(linea.split()) <= 3:
                ciclo = ORDINALES[m.group(1)]
            if not RE_COD_2026.match(linea):
                i += 1
                continue
            codigo, nombre, j = linea, [], i + 1
            while j < len(lineas) and lineas[j] not in AREAS_2026:
                nombre.append(lineas[j])
                j += 1
            if j + 4 >= len(lineas):
                break
            ht, hp, cr, tipo = lineas[j + 1 : j + 5]
            req, k = [], j + 5
            while k < len(lineas) and RE_REQ_2026.match(lineas[k]):
                req.append(lineas[k].rstrip(","))
                k += 1
            nombre_txt = re.sub(r"\s*\(Pág \d+\)", "", " ".join(nombre)).strip()
            cursos.append({
                "carrera": doc.carrera, "plan": doc.plan, "codigo": codigo,
                "curso": nombre_txt, "ciclo": ciclo, "creditos": _a_float(cr),
                "tipo": "electivo" if tipo.strip() == "E" else "obligatorio",
                "prerrequisitos_texto": " | ".join(req), "documento": doc.archivo,
                "pagina": num, "estado": doc.estado,
            })
            i = k
    return cursos


# ---------------------------------------------------------------- lista sin bordes (Estadística 2023, pág. 2)

RE_COD_NUM = re.compile(r"^\d{6}$")
RE_TIPO = re.compile(r"^(Obligatorio|Electivo)$", re.IGNORECASE)


def leer_lista_codigos(doc: Documento, desde: int, hasta: int) -> list[dict]:
    """Tabla sin bordes: CÓDIGO / nombre / TIPO / T / P / Total / CR / requisitos.

    Un código solo inicia un curso si antes del siguiente código aparece su TIPO; los demás
    códigos sueltos son prerrequisitos. El ciclo se lee del código (232071 -> ciclo 07).
    """
    cursos = []
    for num, texto in leer_paginas(doc):
        if not desde <= num <= hasta:
            continue
        lineas = [l.strip() for l in texto.splitlines()]

        def inicia_curso(i: int) -> bool:
            for l in lineas[i + 1 : i + 5]:
                if RE_TIPO.match(l):
                    return True
                if RE_COD_NUM.match(l.split(" ")[0]):
                    return False
            return False

        inicios = [i for i, l in enumerate(lineas) if RE_COD_NUM.match(l) and inicia_curso(i)]
        for n, i in enumerate(inicios):
            fin = inicios[n + 1] if n + 1 < len(inicios) else len(lineas)
            bloque = lineas[i + 1 : fin]
            t = next(j for j, l in enumerate(bloque) if RE_TIPO.match(l))
            nombre, tipo = " ".join(bloque[:t]), bloque[t].lower()
            j, numeros = t + 1, []
            while j < len(bloque) and RE_NUMERO.match(bloque[j]):
                numeros.append(bloque[j])
                j += 1
            req = []
            for l in bloque[j:]:
                if re.match(r"^(Total|Electivo [IVX]+|N°|VIII|IX|X|VII|ASIGNATURAS)", l):
                    break
                req.append(l)
            codigo = lineas[i]
            ciclo = int(codigo[3:5]) if 1 <= int(codigo[3:5]) <= 10 else 0
            cursos.append({
                "carrera": doc.carrera, "plan": doc.plan, "codigo": codigo, "curso": titulo(nombre),
                "ciclo": ciclo, "creditos": _a_float(numeros[-1]) if numeros else None,
                "tipo": "electivo" if tipo == "electivo" or ciclo == 0 else "obligatorio",
                "prerrequisitos_texto": " | ".join(req), "documento": doc.archivo,
                "pagina": num, "estado": doc.estado,
            })
    return cursos


# ---------------------------------------------------------------- escaneados (OCR)

def leer_ocr(doc: Documento, nombres_conocidos: list[str]) -> list[dict]:
    """Tablas reconocidas por OCR (ingesta/ocr.py) -> cursos.

    Los nombres se corrigen comparándolos con los de las mallas con texto nativo
    ('Realidad Vacional y Mundial' -> 'Realidad Nacional y Mundial').
    """
    from .ocr import leer_escaneado  # importa EasyOCR solo si hace falta

    claves = {clave(n): n for n in nombres_conocidos}
    cursos, estado = [], {}
    for num, filas in leer_escaneado(doc)["tablas"]:
        # se descartan filas sin código que tienen números ("Electivo I", "Total"); los títulos se conservan
        filas = [f for f in filas if len(f) != 7 or f[0] == "Código" or _es_codigo(f[0])
                 or not any(re.fullmatch(r"[\d.]+", c) for c in f[2:6])]
        for c in _filas_a_cursos(filas, doc, num, estado):
            mejor = process.extractOne(clave(c["curso"]), list(claves), scorer=fuzz.ratio, score_cutoff=90)
            if mejor and re.findall(r"\b[IVX]+\b", mejor[0]) == re.findall(r"\b[IVX]+\b", clave(c["curso"])):
                c["curso"] = titulo(claves[mejor[0]])
            cursos.append(c)
    return cursos


# ---------------------------------------------------------------- versiones y prerrequisitos

def aplicar(base: dict[str, dict], nuevos: list[dict], documento: str, es_modificacion: bool):
    """Agrega o actualiza cursos (por código, o por nombre si no tienen código)."""
    for c in nuevos:
        k = c["codigo"] or clave(c["curso"])
        if k not in base:
            base[k] = c
            continue
        anterior = base[k]
        cambios = [campo for campo in ("creditos", "prerrequisitos_texto", "ciclo")
                   if c[campo] not in (None, "", 0) and clave(str(c[campo])) != clave(str(anterior[campo]))]
        for campo in cambios:
            anterior[campo] = c[campo]
        if cambios and es_modificacion:
            previo = anterior.get("modificado_por", "")
            anterior["modificado_por"] = f"{previo}; {documento}".strip("; ")


def resolver_prerrequisitos(cursos: list[dict]) -> int:
    """Convierte el texto de prerrequisitos en códigos de cursos del mismo plan.

    1) códigos escritos tal cual; 2) nombres completos contenidos en el texto;
    3) coincidencia difusa (rapidfuzz) para abreviaturas o errores de escritura.
    Devuelve cuántos fragmentos de texto quedaron sin resolver.
    """
    sin_resolver = 0
    por_plan: dict[tuple, list[dict]] = {}
    for c in cursos:
        por_plan.setdefault((c["carrera"], c["plan"]), []).append(c)

    for lista in por_plan.values():
        codigos = {c["codigo"] for c in lista if c["codigo"]}
        nombres = {clave(c["curso"]): (c["codigo"] or c["curso"]) for c in lista}
        orden = sorted(nombres, key=len, reverse=True)
        for c in lista:
            texto = c["prerrequisitos_texto"]
            encontrados = [t for t in re.findall(r"[A-Z0-9]{5,8}", texto) if t in codigos]
            resto = " " + clave(texto) + " "
            for t in encontrados:
                resto = resto.replace(f" {t} ", " ")
            for nombre in orden:
                patron = rf"(?<![A-Z0-9]){re.escape(nombre)}(?![A-Z0-9])"
                if re.search(patron, resto):
                    encontrados.append(nombres[nombre])
                    resto = re.sub(patron, " ", resto)
            for trozo in re.split(r"\bY\b|\s{2,}", resto):
                trozo = trozo.strip()
                if len(trozo) < 5 or re.search(r"\bSEM\b|CICLO|SEMESTRE|ASESOR|APROBAD|CR\b", trozo):
                    continue
                mejor = process.extractOne(trozo, orden, scorer=fuzz.token_set_ratio, score_cutoff=88)
                # el número romano debe coincidir: "COMPUTACIONAL II" no es "COMPUTACIONAL I"
                romanos = lambda s: re.findall(r"\b[IVX]+\b", s)
                if mejor and romanos(mejor[0]) == romanos(trozo):
                    encontrados.append(nombres[mejor[0]])
                else:
                    sin_resolver += 1
            c["prerrequisitos"] = list(dict.fromkeys(e for e in encontrados if e != (c["codigo"] or c["curso"])))
    return sin_resolver
