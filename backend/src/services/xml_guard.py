"""XML read from a customer's file never carries a DTD.

An office or 3MF package (OPC) has no DOCTYPE, entity or notation declarations,
so ScaleCAD refuses any part that has one before a parser expands or fetches
anything. The check is made by expat itself, so it holds in whatever encoding
the part declares or starts with (UTF-8, UTF-16 with or without a byte-order
mark, ...); a byte search for "<!DOCTYPE" doesn't.
"""
from __future__ import annotations

from typing import NoReturn
from xml.parsers import expat


class _DeclarationFound(Exception):
    pass


def _stop(*_args: object) -> NoReturn:
    raise _DeclarationFound()


def declares_dtd(raw: bytes) -> bool:
    """True when ``raw`` is XML with a DOCTYPE, or any entity or notation declaration.

    Expat stops at the DOCTYPE, before any entity in it is declared, so nothing
    is ever expanded or fetched here. Bytes that aren't well-formed XML (or
    aren't XML at all, like a PNG thumbnail) are False: the real parse refuses
    them, reading the same bytes with the same expat or with libxml2.
    """
    parser = expat.ParserCreate()
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    parser.StartDoctypeDeclHandler = _stop
    parser.EntityDeclHandler = _stop
    parser.UnparsedEntityDeclHandler = _stop
    parser.NotationDeclHandler = _stop
    parser.ExternalEntityRefHandler = _stop
    try:
        parser.Parse(raw, True)
    except _DeclarationFound:
        return True
    except expat.ExpatError:
        return False
    return False
