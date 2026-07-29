from __future__ import annotations

import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
required = [
    "Dockerfile", "render.yaml", "requirements.txt", ".env.example", ".dockerignore",
    "README.md", "DEPLOYMENT.md", "FROZEN_PROTOCOL.md", "BUILD_VALIDATION.md",
    "docs/ARCHITECTURE.md", "app/main.py", "app/worker.py", "app/protocol.py",
    "app/reporting.py", "migrations/001_initial.sql",
]
missing = [item for item in required if not (root / item).exists()]
if missing:
    raise SystemExit(f"Missing required package files: {missing}")

manifest_path = root / "PACKAGE_MANIFEST.json"
if manifest_path.exists():
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("version") != "1.0.0":
        raise SystemExit("Unexpected package version")
    listed = {item["path"]: item for item in manifest["files"]}
    actual = {
        path.relative_to(root).as_posix(): path
        for path in root.rglob("*")
        if path.is_file()
        and path.name != "PACKAGE_MANIFEST.json"
        and "__pycache__" not in path.parts
        and ".pytest_cache" not in path.parts
    }
    if set(listed) != set(actual):
        missing_from_manifest = sorted(set(actual) - set(listed))
        missing_from_package = sorted(set(listed) - set(actual))
        raise SystemExit(
            f"Manifest file-set mismatch: unlisted={missing_from_manifest}, missing={missing_from_package}"
        )
    for rel, path in actual.items():
        payload = path.read_bytes()
        expected = listed[rel]
        if len(payload) != expected["size_bytes"]:
            raise SystemExit(f"Manifest size mismatch: {rel}")
        if hashlib.sha256(payload).hexdigest() != expected["sha256"]:
            raise SystemExit(f"Manifest hash mismatch: {rel}")

print("Package structure and manifest: OK")
