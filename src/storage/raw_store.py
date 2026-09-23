"""Raw layer: immutable, append-only JSONL.gz files partitioned by source and date."""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Fields we try, in order, to identify a posting. Falls back to a content hash.
_KEY_FIELDS = ("url", "job_url", "source_url", "link", "id", "job_id", "identifier")

# Fields that change on every fetch and must not count as "the posting changed"
VOLATILE_FIELDS = {"fetched_at", "scraped_at"}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def content_hash(payload: dict) -> str:
    stable = {k: v for k, v in payload.items() if k not in VOLATILE_FIELDS}
    blob = json.dumps(stable, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def job_key(payload: dict) -> str:
    for field in _KEY_FIELDS:
        value = payload.get(field)
        if isinstance(value, dict):  # e.g. JSON-LD identifier: {"value": "123"}
            value = value.get("value") or value.get("@id")
        if value:
            return str(value).strip()
    return content_hash(payload)[:32]


def wrap(payload: dict, source: str, run_id: str, scraped_at: datetime) -> dict:
    """Envelope: metadata about the scrape + the untouched original payload."""
    return {
        "source": source,
        "job_key": job_key(payload),
        "content_hash": content_hash(payload),
        "scraped_at": scraped_at.isoformat(),
        "run_id": run_id,
        "payload": payload,
    }


class RawStore(ABC):
    @abstractmethod
    def write(self, key: str, data: bytes) -> str: ...

    @abstractmethod
    def read(self, key: str) -> bytes: ...

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    @abstractmethod
    def list_keys(self, prefix: str) -> list[str]: ...


class LocalRawStore(RawStore):
    def __init__(self, base_dir: str | Path):
        self.base = Path(base_dir)

    def write(self, key: str, data: bytes) -> str:
        path = self.base / key
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)  # no half-written files if we crash mid-write
        return str(path)

    def read(self, key: str) -> bytes:
        return (self.base / key).read_bytes()

    def exists(self, key: str) -> bool:
        return (self.base / key).exists()

    def list_keys(self, prefix: str) -> list[str]:
        root = self.base / prefix
        if not root.exists():
            return []
        return sorted(p.relative_to(self.base).as_posix() for p in root.rglob("*.jsonl.gz"))


class S3RawStore(RawStore):
    def __init__(self, bucket: str, profile: str | None = None, region: str | None = None):
        import boto3  # imported here so local-only use doesn't need AWS set up

        session = boto3.Session(profile_name=profile, region_name=region)
        self.s3 = session.client("s3")
        self.bucket = bucket

    def write(self, key: str, data: bytes) -> str:
        self.s3.put_object(Bucket=self.bucket, Key=key, Body=data)
        return f"s3://{self.bucket}/{key}"

    def read(self, key: str) -> bytes:
        return self.s3.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self.s3.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
                return False
            raise

    def list_keys(self, prefix: str) -> list[str]:
        keys: list[str] = []
        for page in self.s3.get_paginator("list_objects_v2").paginate(
            Bucket=self.bucket, Prefix=prefix
        ):
            keys += [o["Key"] for o in page.get("Contents", []) if o["Key"].endswith(".jsonl.gz")]
        return sorted(keys)


def get_store(backend: str | None = None) -> RawStore:
    backend = (backend or os.getenv("RAW_BACKEND", "local")).lower()
    if backend == "local":
        return LocalRawStore(os.getenv("RAW_LOCAL_DIR", "data"))
    if backend == "s3":
        return S3RawStore(
            bucket=os.environ["S3_BUCKET"],
            profile=os.getenv("AWS_PROFILE"),
            region=os.getenv("AWS_REGION"),
        )
    raise ValueError(f"Unknown RAW_BACKEND: {backend!r} (use 'local' or 's3')")


def write_batch(
    store: RawStore,
    source: str,
    records: list[dict],
    run_id: str | None = None,
    scraped_at: datetime | None = None,
) -> tuple[str, str, list[dict]]:
    """Write one scrape run as one file. Returns (key, uri, envelopes)."""
    if not records:
        raise ValueError("No records to write")
    scraped_at = scraped_at or utcnow()
    run_id = run_id or f"{scraped_at:%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}"
    envelopes = [wrap(r, source, run_id, scraped_at) for r in records]
    text = "\n".join(json.dumps(e, ensure_ascii=False, default=str) for e in envelopes) + "\n"
    key = f"raw/source={source}/dt={scraped_at:%Y-%m-%d}/{run_id}.jsonl.gz"
    uri = store.write(key, gzip.compress(text.encode("utf-8")))
    return key, uri, envelopes


def read_batch(store: RawStore, key: str) -> list[dict]:
    text = gzip.decompress(store.read(key)).decode("utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]