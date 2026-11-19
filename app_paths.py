"""Paths are resolved beside the app, so the whole folder can be moved."""
import hashlib
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def data_directory():
    return Path(os.environ.get('PAPER_DESK_DATA', str(ROOT / 'data'))).resolve()


def instance_identity():
    path = os.path.normcase(str(data_directory()))
    return hashlib.sha256(path.encode('utf-8')).hexdigest()[:24]
