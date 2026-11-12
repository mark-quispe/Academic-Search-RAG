"""Rutas y reglas de la ingesta.

La procedencia de cada PDF (carrera, plan, URL) está en data/sources.csv.
Aquí solo se indica QUÉ rol cumple cada documento y CÓMO se lee.
"""

from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DATA = RAIZ / "data"
RAW = DATA / "raw"
PROCESSED = DATA / "processed"
CHROMA = DATA / "chroma"
CHROMA_RESPALDO = DATA / "chroma_respaldo"
SOURCES = DATA / "sources.csv"
LOGS = RAIZ / "logs"

# Modelo de embeddings (e5 exige los prefijos "passage: " y "query: ")
MODELO_EMBEDDINGS = "intfloat/multilingual-e5-small"

# Fragmentación: ~220 palabras ≈ 300-400 tokens (límite del modelo: 512)
PALABRAS_POR_FRAGMENTO = 220
SOLAPAMIENTO = 40
MIN_PALABRAS_PAGINA = 15

# Documentos no publicados oficialmente
NO_OFICIALES = {"cc_plan_2026_reporte_final.pdf"}

# Documentos escaneados: su texto se obtiene por OCR (ingesta/ocr.py), no de la capa de texto del PDF
ESCANEADOS = {"io_plan_2018_modif_2020_anexo.pdf"}

# Mallas, en orden cronológico por carrera y plan: un documento posterior
# modifica los cursos que ya existen (por código) y agrega los nuevos.
#   tabla       -> tablas nativas del PDF (pdfplumber)
#   debe_decir  -> resolución "DICE / DEBE DECIR": solo se aplican las páginas "DEBE DECIR"
#   lista_2026  -> documento LaTeX del Plan 2026 (texto lineal, PyMuPDF)
#   lista_codigos -> tabla sin bordes leída como texto lineal (PyMuPDF)
#   ocr         -> malla escaneada: cuadrícula con OpenCV + reconocimiento con EasyOCR
MALLAS = [
    {"archivo": "cc_plan_2018_modif_2021.pdf", "formato": "tabla"},
    {"archivo": "cc_plan_2018_modif_2026_anexo.pdf", "formato": "debe_decir"},
    {"archivo": "cc_plan_2026_reporte_final.pdf", "formato": "lista_2026", "paginas": (258, 262)},
    {"archivo": "mat_plan_2018.pdf", "formato": "tabla"},
    {"archivo": "est_plan_2018.pdf", "formato": "tabla"},
    {"archivo": "est_plan_2018_modif_2021_anexo.pdf", "formato": "tabla"},
    {"archivo": "est_plan_2023.pdf", "formato": "tabla"},
    {"archivo": "est_plan_2023.pdf", "formato": "lista_codigos", "paginas": (2, 2)},  # pág. 2 sin bordes
    {"archivo": "io_plan_2018_modif_2020_anexo.pdf", "formato": "ocr"},
]

# Sumillas: si un curso aparece en dos documentos, se queda la del primero de la lista.
SUMILLAS = [
    {"archivo": "cc_sumillas_2018.pdf"},
    {"archivo": "cc_plan_2018_original.pdf", "paginas": (23, 34)},
    {"archivo": "cc_plan_2026_reporte_final.pdf", "paginas": (279, 289)},  # 273-278: laboratorios
    {"archivo": "mat_sumillas_2018.pdf"},
    {"archivo": "est_sumillas_2018.pdf"},
    {"archivo": "est_sumillas_2023.pdf"},
]
