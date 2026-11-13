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

Requisitos: Git y Python. [uv](https://docs.astral.sh/uv/) instala por su cuenta Python 3.11 y las versiones exactas de `uv.lock` (PyTorch solo CPU).

## 1. Clonar
```bash
git clone https://github.com/mark-quispe/Academic-Search-RAG.git
cd Academic-Search-RAG
```
## 2. Instalar dependencias (crea .venv)
```bash
pip install uv
uv sync
```


## 3. Generar dataset y base vectorial (≈ 2 min; la primera vez descarga el modelo de embeddings)
```bash
uv run python -m ingesta --indexar   # solo `uv run python -m ingesta` si no se requiere la base
```

## 4. Consultar la base vectorial
```bash
uv run python -m ingesta.inspeccionar "¿En qué curso veré pilas y colas?" --carrera computacion --plan 2018 --sin-detalle -n 3
```

Si `uv` no se reconoce como comando, usar `python -m uv`.

El repositorio incluye los PDF, el dataset y la caché del OCR; la base vectorial (`data/chroma/`) no se versiona y se genera localmente con `--indexar`. Los parámetros de `inspeccionar` se describen en el anexo del [informe de avance](docs/informe_avance_01.md).

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
