"""Object-store abstraction for CADVerify blob persistence.

Import-safe with or without boto3: importing this package never imports boto3.
See ``base`` (interface), ``local`` (default adapter), ``s3`` (lazy boto3
adapter), and ``factory`` (env-driven selection).
"""
from __future__ import annotations

from src.storage.base import (
    ObjectNotFoundError,
    ObjectStore,
    ObjectStoreError,
    ObjectStoreProtocol,
    Payload,
)
from src.storage.factory import get_object_store, selected_backend
from src.storage.local import LocalObjectStore
from src.storage.s3 import S3ObjectStore

__all__ = [
    "ObjectStore",
    "ObjectStoreProtocol",
    "ObjectStoreError",
    "ObjectNotFoundError",
    "Payload",
    "LocalObjectStore",
    "S3ObjectStore",
    "get_object_store",
    "selected_backend",
]
