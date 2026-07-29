from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import httpx

from app.config import get_settings


class StorageClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.base = self.settings.supabase_url.rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {self.settings.service_key}",
            "apikey": self.settings.service_key,
        }

    def ensure_bucket(self) -> None:
        with httpx.Client(timeout=30) as client:
            response = client.get(f"{self.base}/storage/v1/bucket/{self.settings.storage_bucket}", headers=self.headers)
            if response.status_code == 200:
                return
            response = client.post(
                f"{self.base}/storage/v1/bucket",
                headers={**self.headers, "Content-Type": "application/json"},
                json={"id": self.settings.storage_bucket, "name": self.settings.storage_bucket, "public": False},
            )
            if response.status_code not in {200, 201, 409}:
                raise RuntimeError(f"Storage bucket creation failed: {response.status_code} {response.text[:500]}")

    def upload_bytes(self, object_path: str, payload: bytes, content_type: str) -> tuple[int, str]:
        self.ensure_bucket()
        url = f"{self.base}/storage/v1/object/{self.settings.storage_bucket}/{object_path.lstrip('/')}"
        headers = {**self.headers, "Content-Type": content_type, "x-upsert": "true"}
        with httpx.Client(timeout=120) as client:
            response = client.post(url, headers=headers, content=payload)
            if response.status_code not in {200, 201}:
                raise RuntimeError(f"Storage upload failed: {response.status_code} {response.text[:500]}")
        return len(payload), hashlib.sha256(payload).hexdigest()

    def upload_file(self, object_path: str, path: Path, content_type: str) -> tuple[int, str]:
        return self.upload_bytes(object_path, path.read_bytes(), content_type)

    def download_bytes(self, object_path: str) -> bytes:
        url = f"{self.base}/storage/v1/object/authenticated/{self.settings.storage_bucket}/{object_path.lstrip('/')}"
        with httpx.Client(timeout=120) as client:
            response = client.get(url, headers=self.headers)
            if response.status_code != 200:
                raise RuntimeError(f"Storage download failed: {response.status_code} {response.text[:500]}")
            return response.content

    def signed_url(self, object_path: str, expires_in: int | None = None) -> str:
        expires = expires_in or self.settings.signed_url_seconds
        url = f"{self.base}/storage/v1/object/sign/{self.settings.storage_bucket}/{object_path.lstrip('/')}"
        with httpx.Client(timeout=30) as client:
            response = client.post(
                url,
                headers={**self.headers, "Content-Type": "application/json"},
                json={"expiresIn": expires},
            )
            if response.status_code != 200:
                raise RuntimeError(f"Signed URL failed: {response.status_code} {response.text[:500]}")
            signed = response.json().get("signedURL") or response.json().get("signedUrl")
            if not signed:
                raise RuntimeError("Supabase did not return a signed URL")
            return signed if signed.startswith("http") else f"{self.base}/storage/v1{signed}"
