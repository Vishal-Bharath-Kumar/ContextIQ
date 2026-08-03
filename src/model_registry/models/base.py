"""Isolated DeclarativeBase for the model_registry module.

A dedicated Base is required because ``src.data.models.base.Base`` already
maps a ``ModelRegistry`` class to the ``model_registry`` table under the
0020 migration schema.  Using the same MetaData instance would raise
``InvalidRequestError: Table 'model_registry' is already defined``.
"""
from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
