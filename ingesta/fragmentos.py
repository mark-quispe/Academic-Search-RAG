"""Fragmentación del texto general de cada documento (colección `fragmentos`)."""

from . import config
from .lectura import Documento
from .modelos import Fragmento


def fragmentar(doc: Documento, paginas: list[tuple[int, str]]) -> list[Fragmento]:
    """Ventanas de palabras con solapamiento, sin cruzar páginas (así la cita de página es exacta)."""
    paso = config.PALABRAS_POR_FRAGMENTO - config.SOLAPAMIENTO
    fragmentos = []
    for num, texto in paginas:
        palabras = texto.split()
        if len(palabras) < config.MIN_PALABRAS_PAGINA:
            continue  # páginas vacías o de solo imagen
        inicio, k = 0, 0
        while True:
            ventana = palabras[inicio : inicio + config.PALABRAS_POR_FRAGMENTO]
            fragmentos.append(
                Fragmento(
                    id=f"{doc.ruta.stem}-p{num}-{k}",
                    texto=" ".join(ventana),
                    carrera=doc.carrera,
                    plan=doc.plan,
                    documento=doc.archivo,
                    pagina=num,
                    tipo_documento=doc.tipo,
                    estado=doc.estado,
                    calidad=doc.calidad,
                )
            )
            if inicio + config.PALABRAS_POR_FRAGMENTO >= len(palabras):
                break
            inicio += paso
            k += 1
    return fragmentos
