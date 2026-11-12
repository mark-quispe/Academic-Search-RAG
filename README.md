# Grupo 09 — API RAG de mallas curriculares (Facultad de Ciencias Matemáticas, UNMSM)

API en FastAPI que responde consultas sobre los planes de estudio de las escuelas de la Facultad de Ciencias Matemáticas, con citas al documento y página oficial.

La propuesta completa (problema, hipótesis, datos, arquitectura) está en [docs/propuesta.md](docs/propuesta.md).
Avances: [Informe de Avance N.° 1 — Ingesta de datos y base vectorial](docs/informe_avance_01.md).

## Estructura

```
docs/propuesta.md        # plan del proyecto
data/
├── sources.csv          # procedencia de cada PDF (URL oficial y fecha de descarga)
├── raw/                 # PDF oficiales, sin modificar
│   └── ciencias_matematicas/
│       ├── computacion_cientifica/
│       ├── matematica/
│       ├── estadistica/
│       └── investigacion_operativa/
└── processed/           # lo generará el pipeline de ingesta (cursos.csv, fragmentos.jsonl)
eval/                    # conjunto de preguntas y resultados de evaluación
logs/                    # métricas de consumo por consulta
```

## Ingesta (PDF → dataset → ChromaDB)

Requisito: [uv](https://docs.astral.sh/uv/). La primera vez instala Python 3.11 y las dependencias (PyTorch solo CPU).

```bash
uv sync
uv run python -m ingesta             # PDF -> data/processed/cursos.csv + fragmentos.jsonl
uv run python -m ingesta --indexar   # además genera la base vectorial en data/chroma/
uv run python -m ingesta.inspeccionar "¿En qué curso veré pilas y colas?" --carrera computacion --plan 2018
```

Sin uv (Python 3.11): `pip install -r requirements.txt` y luego los mismos comandos sin `uv run`. `requirements.txt` se genera desde `uv.lock` con `uv export --format requirements-txt --no-hashes --no-dev --no-emit-project`.

La base vectorial (`data/chroma/`) no se versiona: se genera localmente con `--indexar`.

| Etapa | Qué hace | Herramienta |
|:--|:--|:--|
| 0. Inventario | Lee `sources.csv` y verifica que cada PDF exista | Python |
| 1. Fragmentos | Texto por página, limpieza (acentos LaTeX, sellos, correos) y ventanas de ~220 palabras | PyMuPDF |
| 2. Mallas | Tablas → cursos (código, ciclo, créditos, tipo, prerrequisitos); aplica las modificaciones en orden | pdfplumber, PyMuPDF, OpenCV + EasyOCR (escaneados) |
| 3. Sumillas | Separa la sumilla de cada curso comparando títulos con los nombres de la malla | rapidfuzz |
| 4. Validación | Esquema de cada registro (créditos, ciclo, tipo) e ids únicos | Pydantic |
| 5. Dataset | `cursos.csv` y `fragmentos.jsonl` | Pandas |
| 6. Indexación | Embeddings y colecciones `cursos` y `fragmentos` (con copia de respaldo previa) | Sentence Transformers, ChromaDB |

El reporte de calidad y consumo (conteos por plan, tiempos, RAM) queda en `logs/ingesta.json`. Qué documento cumple qué rol se define en [ingesta/config.py](ingesta/config.py).

La malla escaneada de Investigación Operativa se lee por OCR ([ingesta/ocr.py](ingesta/ocr.py): cuadrícula con OpenCV + EasyOCR). La primera vez tarda ≈ 3.5 min; luego usa la caché de `data/processed/ocr/`.

## Estado

- [x] Recolección de datos: 19 PDF (≈420 páginas), 4 escuelas
- [x] Arquitectura
- [ ] Investigación sobre RAG aplicado al tema
- [x] Pipeline de ingesta: 378 cursos (6 planes, 4 escuelas) y 1018 fragmentos (19 PDF)
- [ ] Motor RAG y API
- [ ] Evaluación
