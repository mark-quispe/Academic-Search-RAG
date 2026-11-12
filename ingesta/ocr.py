"""OCR de mallas escaneadas (Investigación Operativa).

1. Cada página se convierte en imagen a 300 dpi (PyMuPDF).
2. Se detecta la cuadrícula de cada tabla con operaciones morfológicas (OpenCV):
   líneas horizontales -> filas, líneas verticales -> columnas.
3. Se lee cada fila con EasyOCR (español, CPU) y cada texto se asigna a su columna.
   Las columnas numéricas (créditos, horas) se leen celda por celda, aceptando solo dígitos,
   porque los números sueltos en cursiva son los que el OCR más omite.
4. El resultado se guarda en caché (data/processed/ocr/) para no repetir el OCR en cada ingesta.
"""

import hashlib
import json
import re

import cv2
import numpy as np
import pymupdf

from . import config
from .lectura import Documento
from .texto import clave

_lector = None


def _ocr():
    global _lector
    if _lector is None:
        import easyocr  # carga perezosa: solo si hay documentos escaneados
        _lector = easyocr.Reader(["es"], gpu=False, verbose=False)
    return _lector


def _imagen(pagina) -> np.ndarray:
    pix = pagina.get_pixmap(dpi=300, colorspace=pymupdf.csGRAY)
    return np.frombuffer(pix.samples, np.uint8).reshape(pix.h, pix.w)


def _agrupar(indices: np.ndarray, separacion: int = 15) -> list[int]:
    grupos: list[list[int]] = []
    for i in indices:
        if grupos and i - grupos[-1][-1] <= separacion:
            grupos[-1].append(int(i))
        else:
            grupos.append([int(i)])
    return [int(np.mean(g)) for g in grupos]


def _tablas(img: np.ndarray):
    """Devuelve [(x, y, w, h, filas_y, columnas_x)] por cada tabla de la página."""
    alto, ancho = img.shape
    bn = cv2.adaptiveThreshold(255 - img, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 15, -10)
    hor = cv2.morphologyEx(bn, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (ancho // 25, 1)))
    ver = cv2.morphologyEx(bn, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, alto // 80)))
    reja = cv2.dilate(hor | ver, np.ones((5, 5), np.uint8))
    contornos, _ = cv2.findContours(reja, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cajas = sorted((cv2.boundingRect(c) for c in contornos), key=lambda b: b[1])
    tablas = []
    for x, y, w, h in cajas:
        if w < ancho * 0.4 or h < 150:
            continue
        filas = _agrupar(np.where(hor[y:y + h, x:x + w].sum(1) / 255 > w * 0.5)[0])
        columnas = _agrupar(np.where(ver[y:y + h, x:x + w].sum(0) / 255 > h * 0.25)[0])
        tablas.append((x, y, w, h, filas, columnas))
    return tablas


def _unir_lineas(cajas: list[tuple]) -> str:
    """Ordena los textos de una celda por renglón (y) y luego de izquierda a derecha (x)."""
    cajas = sorted(cajas)
    renglones: list[list[tuple]] = []
    for cy, cx, t, alto in cajas:
        if renglones and abs(cy - renglones[-1][0][0]) < alto * 0.6:
            renglones[-1].append((cy, cx, t, alto))
        else:
            renglones.append([(cy, cx, t, alto)])
    return " ".join(t for r in renglones for _, _, t, _ in sorted(r, key=lambda c: c[1]))


_CONFUSIONES = str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1", "|": "1", "S": "5", "B": "8", "Z": "2"})


def _corregir_codigo(c: str) -> str:
    """CBOI01 -> CBO101, 18l4451 -> 1814451 (letras y dígitos que el OCR confunde)."""
    c = re.sub(r"[^A-Za-z0-9]", "", c).upper()
    if re.fullmatch(r"[0-9OISBZL]{7}", c):
        return c.translate(_CONFUSIONES)
    m = re.fullmatch(r"([A-Z0-9]{3})([0-9OISBZL]{3})", c)
    if m and m.group(1)[0] == "C":
        return m.group(1).replace("0", "O") + m.group(2).translate(_CONFUSIONES)
    return c


def _leer_digitos(celda: np.ndarray) -> str:
    """Lee un número suelto: el detector de EasyOCR omite dígitos aislados en cursiva, así que se
    localiza la tinta con OpenCV (descartando restos de las líneas de la tabla) y se pasa el
    recorte directamente al reconocedor."""
    alto = celda.shape[0]
    _, bn = cv2.threshold(celda, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    n, etiquetas, st, _ = cv2.connectedComponentsWithStats(bn)
    trazos = [i for i in range(1, n) if 20 <= st[i, 3] < 0.8 * alto and st[i, 2] >= 6 and st[i, 4] > 60]
    if not trazos:
        return ""
    x0, y0 = min(st[i, 0] for i in trazos), min(st[i, 1] for i in trazos)
    x1, y1 = max(st[i, 0] + st[i, 2] for i in trazos), max(st[i, 1] + st[i, 3] for i in trazos)
    limpio = np.where(np.isin(etiquetas, trazos), 0, 255).astype(np.uint8)[y0:y1, x0:x1]
    limpio = cv2.copyMakeBorder(limpio, 15, 15, 25, 25, cv2.BORDER_CONSTANT, value=255)
    h, w = limpio.shape
    return "".join(_ocr().recognize(limpio, horizontal_list=[[0, w, 0, h]], free_list=[],
                                    allowlist="0123456789.", detail=0))


def _candidatos(s: str) -> list[float]:
    """Interpretaciones posibles de un número leído: '33' -> 3 (cursiva duplicada), '30' -> 3.0."""
    s = s.strip(".")
    if not s:
        return []
    opciones = [s, s[0], s.replace(".", "")[:1]]
    if len(s) == 2 and s[0] == s[1]:
        opciones.insert(0, s[0])
    if re.fullmatch(r"\d0", s) or re.fullmatch(r"(\d)\1?0", s):
        opciones.insert(0, s[0])
    vistos = []
    for o in opciones:
        try:
            v = float(o)
        except ValueError:
            continue
        if 0 < v <= 10 and v not in vistos:
            vistos.append(v)
    return vistos


def _numeros_coherentes(cr: str, t: str, p: str, l: str) -> tuple[str, str, str, str]:
    """Elige la interpretación que cumple créditos = T + (P + L) / 2 (regla de estos planes).

    Si los créditos no se leyeron, se calculan con esa misma regla a partir de las horas.
    """
    opciones = [_candidatos(v) or [0.0] for v in (cr, t, p, l)]
    for vc in opciones[0]:
        for vt in opciones[1]:
            for vp in opciones[2]:
                for vl in opciones[3]:
                    if abs(vc - (vt + (vp + vl) / 2)) < 1e-6:
                        return tuple(f"{v:g}" if v else "" for v in (vc, vt, vp, vl))
    vc, vt, vp, vl = (o[0] for o in opciones)
    if not vc and vt:
        vc = vt + (vp + vl) / 2
    return tuple(f"{v:g}" if v else "" for v in (vc, vt, vp, vl))


_RE_NINGUNO = re.compile(r"^\W*[NV]i?n?[gq]?u?n?o\W*$", re.IGNORECASE)


def _limpiar_texto_ocr(s: str) -> str:
    """'Cálculo IlI' -> 'Cálculo III'; 'Vinguno' -> '' (sin requisitos)."""
    s = re.sub(r"\b[IlV]*[lI][IlV]*\b", lambda m: m.group(0).replace("l", "I"), s)
    s = s.replace(";", ",").strip()
    return "" if _RE_NINGUNO.match(s) else s


def _etiqueta_numerica(e: str) -> str | None:
    if e.startswith("CRED"):
        return "cr"
    return {"T": "t", "I": "t", "1": "t", "P": "p", "L": "l"}.get(e)


def _leer_tabla(img, x, y, w, filas_y, columnas_x) -> list[list[str]]:
    lector = _ocr()
    n_col = len(columnas_x) - 1
    numericas: list[int] = []
    por_etiqueta: dict[str, int] = {}  # cr/t/p/l -> índice de columna
    filas: list[list[str]] = []
    for a, b in zip(filas_y, filas_y[1:]):
        banda = img[y + a + 4 : y + b - 3, x : x + w]
        if banda.shape[0] < 20:
            continue
        celdas: dict[int, list] = {}
        for caja, texto, _ in lector.readtext(banda):
            xs = [p[0] for p in caja]
            ys = [p[1] for p in caja]
            col = sum(1 for cx in columnas_x if cx < np.mean(xs)) - 1
            celdas.setdefault(col, []).append((np.mean(ys), np.mean(xs), texto, max(ys) - min(ys)))
        fila = [_unir_lineas(celdas.get(i, [])) for i in range(n_col)]

        # El encabezado indica qué columnas son numéricas
        etiquetas = [clave(c) for c in fila]
        if any("CODIGO" in e for e in etiquetas) and any("ASIGNATURA" in e for e in etiquetas):
            # columnas numéricas: las que están entre "Asignatura" y "Requisitos"
            ini = next(i for i, e in enumerate(etiquetas) if "ASIGNATURA" in e) + 1
            fin = next((i for i, e in enumerate(etiquetas) if "REQUISITO" in e or "REAUISITO" in e), n_col)
            numericas = list(range(ini, fin))
            por_etiqueta = {}
            for i in numericas:
                e = _etiqueta_numerica(etiquetas[i])
                if e and e not in por_etiqueta:
                    por_etiqueta[e] = i
            titulo = " ".join(re.findall(r"\b\w+ (?:CICLO|SEMESTRE)\b", " ".join(fila)))
            if titulo:  # título del ciclo pegado al encabezado (falta la línea entre ambos)
                filas.append([titulo])
            pegada = re.search(r"\b\d{7}\b", fila[0])
            filas.append(["Código", "Asignatura", "Créditos", "T", "P", "L", "Requisitos"])
            if pegada:  # primera fila de datos pegada al encabezado: se lee solo del texto
                quitar = lambda s, *ps: re.sub("|".join(ps), "", s, flags=re.IGNORECASE).strip()
                nums = re.findall(r"\d+(?:\.\d)?", " ".join(quitar(fila[i], "Créditos", r"\bT\b", r"\bP\b", r"\bL\b")
                                                             for i in numericas))
                filas.append([pegada.group(0), quitar(fila[1], "Asignatura"),
                              *_numeros_coherentes(*(nums + ["", "", "", ""])[:4]),
                              _limpiar_texto_ocr(quitar(fila[-1], "Requisitos"))])
            continue
        if not numericas:
            filas.append(fila)
            continue

        if len(por_etiqueta) == 4:  # cada número desde la columna de su encabezado
            lecturas = [_leer_digitos(banda[:, columnas_x[i] + 4 : columnas_x[i + 1] - 4])
                        for i in (por_etiqueta[k] for k in ("cr", "t", "p", "l"))]
        else:  # encabezado ilegible: números en orden de aparición
            lecturas = [_leer_digitos(banda[:, columnas_x[i] + 4 : columnas_x[i + 1] - 4]) for i in numericas]
            lecturas = ([v for v in lecturas if v] if len(lecturas) > 4 else lecturas) + ["", "", "", ""]
        lecturas = lecturas[:4]
        if clave(fila[1]).startswith("TOTAL"):
            numeros = (lecturas[0], "", "", "")
        else:
            numeros = _numeros_coherentes(*lecturas)
        requisitos = _limpiar_texto_ocr(" ".join(fila[i] for i in range(numericas[-1] + 1, n_col) if fila[i]))
        codigo = _corregir_codigo(fila[0]) if fila[0] else ""
        nombre = _limpiar_texto_ocr(" ".join(fila[1 : numericas[0]]))
        filas.append([codigo, nombre, *numeros, requisitos])
    # una tabla sin encabezado reconocible (p. ej. un sello sobre el borde) no se usa
    if not numericas:
        return []
    _cuadrar_total(filas)
    return filas


def _cuadrar_total(filas: list[list[str]]) -> None:
    """Si la suma de créditos no coincide con el Total impreso y un solo curso es incoherente
    con la regla T + (P + L) / 2, ese curso recibe la diferencia."""
    inicio = next((i for i, f in enumerate(filas) if f and f[0] == "Código"), None)
    if inicio is None:
        return
    filas = filas[inicio + 1 :]
    datos = [f for f in filas if len(f) == 7 and f[0] != "Código" and not clave(f[1]).startswith("TOTAL")]
    total = next((f[2] for f in filas if len(f) == 7 and clave(f[1]).startswith("TOTAL")), "")
    if not total or not datos:
        return
    num = lambda s: float(s) if s else 0.0
    suma = sum(num(f[2]) for f in datos)
    dudosos = [f for f in datos if f[3] and num(f[2]) != num(f[3]) + (num(f[4]) + num(f[5])) / 2]
    if suma != num(total) and len(dudosos) == 1:
        f = dudosos[0]
        f[2] = f"{num(f[2]) + num(total) - suma:g}"


def leer_escaneado(doc: Documento) -> dict:
    """{'paginas': [(num, texto)], 'tablas': [(num, filas)]}; usa la caché si el PDF no cambió."""
    huella = hashlib.sha256(doc.ruta.read_bytes()).hexdigest()[:16]
    cache = config.PROCESSED / "ocr" / f"{doc.ruta.stem}.json"
    if cache.exists():
        datos = json.loads(cache.read_text(encoding="utf-8"))
        if datos.get("huella") == huella:
            return datos

    paginas, tablas = [], []
    with pymupdf.open(doc.ruta) as pdf:
        for num, pagina in enumerate(pdf, start=1):
            img = _imagen(pagina)
            texto_tablas = []
            for x, y, w, h, filas_y, columnas_x in _tablas(img):
                filas = _leer_tabla(img, x, y, w, filas_y, columnas_x)
                tablas.append((num, filas))
                texto_tablas += [" | ".join(c for c in f if c) for f in filas]
            if texto_tablas:
                texto = "\n".join(texto_tablas)
            else:  # página sin tablas: texto corrido
                texto = "\n".join(_ocr().readtext(img, detail=0, paragraph=True))
            paginas.append((num, texto))

    datos = {"huella": huella, "paginas": paginas, "tablas": tablas}
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
    return datos
