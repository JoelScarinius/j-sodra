from __future__ import annotations

import json
import mimetypes
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd

try:
    import boto3
    from botocore.config import Config as BotoConfig
except Exception:
    boto3 = None
    BotoConfig = None

from .common import normalize_s3_part


def write_json(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return path


def write_dataframe(path: Path, df: pd.DataFrame) -> Path | None:
    if isinstance(df, pd.DataFrame) and not df.empty:
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(path, index=False)
        return path
    return None


def guess_public_base_url(settings) -> str:
    configured = str(settings.supabase_public_base_url or "").strip().rstrip("/")
    if configured:
        return configured
    try:
        parsed = urlparse(settings.supabase_function_url)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
    except Exception:
        pass
    return ""


def relative_output_path(settings, path: Path | str) -> Path:
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(settings.output_dir)
    except ValueError:
        return Path(resolved.name)


def storage_key_for_path(settings, path: Path | str) -> str:
    relative = relative_output_path(settings, path).as_posix()
    prefix = normalize_s3_part(settings.supabase_s3_prefix)
    return f"{prefix}/{relative}" if prefix else relative


def public_url_for_path(settings, path: Path | str) -> str:
    base = guess_public_base_url(settings)
    bucket = normalize_s3_part(settings.supabase_s3_bucket)
    if not base or not bucket:
        return ""
    key = normalize_s3_part(storage_key_for_path(settings, path))
    if not key:
        return ""
    return f"{base}/storage/v1/object/public/{bucket}/{key}"


def build_ref(settings, path: Path | str | None) -> dict:
    if not path:
        return {"path": None, "url": ""}
    relative = relative_output_path(settings, path).as_posix()
    return {"path": relative, "url": public_url_for_path(settings, path)}


def _supabase_storage_client(settings):
    if not settings.upload_to_supabase_storage:
        return None
    if not boto3:
        print("Upload skipped: boto3 is not available.")
        return None
    if (
        not settings.supabase_s3_bucket
        or not settings.supabase_s3_access_key
        or not settings.supabase_s3_secret_key
    ):
        print("Upload skipped: missing Supabase S3 credentials.")
        return None

    return boto3.client(
        "s3",
        endpoint_url=settings.supabase_s3_endpoint,
        aws_access_key_id=settings.supabase_s3_access_key,
        aws_secret_access_key=settings.supabase_s3_secret_key,
        region_name="us-east-1",
        config=BotoConfig(signature_version="s3v4") if BotoConfig else None,
    )


def delete_files_from_supabase(settings, relative_paths: list[str | Path]) -> list[str]:
    client = _supabase_storage_client(settings)
    if client is None:
        return []

    deleted = []
    for relative_path in relative_paths:
        relative = Path(relative_path).as_posix().lstrip("/")
        if not relative:
            continue
        object_key = storage_key_for_path(settings, settings.output_dir / relative)
        try:
            client.delete_object(
                Bucket=settings.supabase_s3_bucket,
                Key=object_key,
            )
            deleted.append(object_key)
        except Exception as exc:
            print(f"Delete failed for {relative}: {exc}")

    return deleted


def upload_files_to_supabase(settings, file_paths: list[Path]) -> list[dict]:
    client = _supabase_storage_client(settings)
    if client is None:
        return []

    uploaded = []
    for file_path in file_paths:
        if not file_path.exists() or not file_path.is_file():
            continue
        object_key = storage_key_for_path(settings, file_path)
        content_type, _ = mimetypes.guess_type(file_path.name)
        if not content_type:
            content_type = "application/octet-stream"

        try:
            with open(file_path, "rb") as handle:
                client.put_object(
                    Bucket=settings.supabase_s3_bucket,
                    Key=object_key,
                    Body=handle,
                    ContentType=content_type,
                )
            uploaded.append(
                {
                    "local_path": str(file_path),
                    "relative_path": relative_output_path(
                        settings, file_path
                    ).as_posix(),
                    "object_key": object_key,
                    "public_url": public_url_for_path(settings, file_path),
                }
            )
        except Exception as exc:
            print(f"Upload failed for {file_path.name}: {exc}")

    return uploaded
