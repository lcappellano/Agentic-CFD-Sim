"""File and JSON content hashes; the single implementation for the project."""
import hashlib
import json
from pathlib import Path


def digest(path):
    """SHA-256 of a file, streamed so large meshes do not load into memory."""
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def content_hash(value):
    """Stable SHA-256 of a JSON-serialisable value (sorted keys, no NaN)."""
    text = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(text.encode()).hexdigest()


def short(hash_text, length=8):
    return hash_text[:length]
