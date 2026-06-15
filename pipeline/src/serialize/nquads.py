"""N-Quads serializer with proper escaping."""
from __future__ import annotations

import re
from pathlib import Path


def _escape(text: str) -> str:
    text = text.replace("\\", "\\\\")
    text = text.replace('"', '\\"')
    text = text.replace("\n", "\\n")
    text = text.replace("\r", "\\r")
    text = text.replace("\t", "\\t")
    return text


def literal(text: str, lang: str | None = None, datatype: str | None = None) -> str:
    esc = _escape(str(text))
    if lang:
        return f'"{esc}"@{lang}'
    if datatype:
        return f'"{esc}"^^{datatype}'
    return f'"{esc}"'


def iri(uri: str) -> str:
    if uri.startswith("<") and uri.endswith(">"):
        return uri
    return f"<{uri}>"


XSD_INT = "<http://www.w3.org/2001/XMLSchema#integer>"
XSD_FLOAT = "<http://www.w3.org/2001/XMLSchema#float>"
XSD_GYEAR = "<http://www.w3.org/2001/XMLSchema#gYear>"
XSD_DATETIME = "<http://www.w3.org/2001/XMLSchema#dateTime>"
XSD_STRING = "<http://www.w3.org/2001/XMLSchema#string>"

RDF_TYPE = "<http://www.w3.org/1999/02/22-rdf-syntax-ns#type>"
RDFS_LABEL = "<http://www.w3.org/2000/01/rdf-schema#label>"
RDFS_COMMENT = "<http://www.w3.org/2000/01/rdf-schema#comment>"


class NQuadWriter:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.path.open("w", encoding="utf-8")
        self._count = 0

    def quad(self, s: str, p: str, o: str, g: str) -> None:
        self._fh.write(f"{s} {p} {o} {iri(g)} .\n")
        self._count += 1

    def close(self) -> None:
        self._fh.close()

    @property
    def count(self) -> int:
        return self._count
