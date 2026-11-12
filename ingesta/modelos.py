"""Esquemas de los registros que produce la ingesta (validados con Pydantic)."""

from typing import Literal

from pydantic import BaseModel, Field

from .texto import clave


class Curso(BaseModel):
    carrera: str
    plan: str
    codigo: str = ""
    curso: str = Field(min_length=3)
    ciclo: int = Field(0, ge=0, le=10)  # 0 = sin ciclo fijo (electivo)
    creditos: float | None = Field(None, ge=0, le=12)
    tipo: Literal["obligatorio", "electivo"]
    prerrequisitos: list[str] = []  # códigos (o nombres) de cursos del mismo plan
    prerrequisitos_texto: str = ""  # texto original del documento
    documento: str
    pagina: int
    modificado_por: str = ""  # resoluciones que cambiaron el registro
    estado: Literal["oficial", "no_oficial"] = "oficial"
    sumilla: str = ""
    sumilla_documento: str = ""
    sumilla_pagina: int = 0

    @property
    def id(self) -> str:
        ident = self.codigo or clave(self.curso).replace(" ", "_")
        return f"{clave(self.carrera).replace(' ', '_')}-{self.plan}-{ident}".lower()


class Fragmento(BaseModel):
    id: str
    texto: str
    carrera: str
    plan: str
    documento: str
    pagina: int
    tipo_documento: str
    estado: Literal["oficial", "no_oficial"]
    calidad: Literal["texto_nativo", "ocr"]
