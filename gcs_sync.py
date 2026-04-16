"""Pull and push the ``data/`` tree to a GCS bucket (object prefix ``data/``)."""

from __future__ import annotations

from pathlib import Path

_OBJECT_PREFIX = "data/"


def download_data_prefix(bucket_name: str, data_dir: Path) -> None:
    """Download ``gs://bucket/data/**`` into local ``data_dir`` (mirror of ``data/``)."""
    from google.cloud import storage

    client = storage.Client()
    data_dir.mkdir(parents=True, exist_ok=True)
    for blob in client.list_blobs(bucket_name, prefix=_OBJECT_PREFIX):
        name = blob.name
        if not name.startswith(_OBJECT_PREFIX) or name == _OBJECT_PREFIX:
            continue
        suffix = name[len(_OBJECT_PREFIX) :]
        if not suffix or name.endswith("/"):
            continue
        dest = data_dir / suffix
        dest.parent.mkdir(parents=True, exist_ok=True)
        blob.download_to_filename(str(dest))


def upload_data_tree(bucket_name: str, data_dir: Path) -> None:
    """Upload every file under local ``data_dir`` to ``gs://bucket/data/...``."""
    from google.cloud import storage

    if not data_dir.is_dir():
        return
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    for path in sorted(data_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(data_dir).as_posix()
        blob_name = f"{_OBJECT_PREFIX.rstrip('/')}/{rel}"
        bucket.blob(blob_name).upload_from_filename(str(path))
