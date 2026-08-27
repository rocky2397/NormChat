"""Bulk-load a corpus directory into a deployed NormChat project.

The upload endpoint ingests synchronously inside the request: it parses,
chunks and embeds every file before responding, then runs the enrichment
pass. For the 137-file DIN corpus that is far longer than any load balancer
will hold a connection open, so this uploads in small batches instead.

Batching is safe for correctness. `enrich_project_references` recomputes
from each chunk's original `raw_text` on every run, so a reference that only
becomes resolvable once its parent norm arrives is picked up by a later
pass -- upload order does not matter, and the pass that follows the final
batch sees the complete project. Re-running never appends twice.

Resumable by design: a 137-file run that dies at file 90 must not re-ingest
the first 89. `ingest_document` renames rather than rejects a duplicate
filename (`foo.pdf` -> `foo_1.pdf`), so a naive re-run would silently double
the corpus and corrupt retrieval. This skips filenames the project already
holds instead.

Usage:
    export NORMCHAT_USERNAME=... NORMCHAT_PASSWORD=...
    python -m scripts.ingest_corpus \
        --base-url https://normchat.onrender.com \
        --project-name "DIN Deutschland" \
        --dir "../example_data/Normen-2"
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import unicodedata
from pathlib import Path
from typing import Iterator, Sequence

import httpx

# Ingestion is CPU-bound and synchronous, and a single DIN part can run to
# several hundred pages, so a batch legitimately takes minutes. The read
# timeout is per-request, not for the whole run.
DEFAULT_READ_TIMEOUT = 900.0
DEFAULT_BATCH_SIZE = 4


def discover_pdfs(root: Path) -> list[Path]:
    """Every real PDF under `root`, sorted, with macOS metadata excluded.

    The corpora live on an exFAT volume, where macOS writes an AppleDouble
    sidecar (`._Foo.pdf`) next to each file. They match *.pdf, are not PDFs,
    and doubled the apparent file count of both corpora. Uploading one would
    create a document that parses to nothing.
    """
    return sorted(
        path
        for path in root.rglob("*.pdf")
        if not path.name.startswith("._") and not path.name.startswith(".")
    )


def pending(local: Sequence[Path], already_uploaded: set[str]) -> list[Path]:
    """The files not yet in the project, matched on filename.

    Filename is the only identifier shared between a local path and a stored
    document. That is sound for these corpora, whose basenames are unique
    across subdirectories, and it is what makes a resumed run idempotent.

    Compared under NFC because the two sides disagree on Unicode form: macOS
    returns decomposed (NFC "ü" as "u" + U+0308) filenames from the corpus
    volume, while a name that reached the server as a composed literal comes
    back composed. The raw strings differ, so a byte comparison re-uploads a
    file that is already there -- which is how the DIN corpus ended up with a
    138th document that was really `DIN EN 1992-1-1/NA/A1` a second time.
    """
    seen = {unicodedata.normalize("NFC", name) for name in already_uploaded}
    return [
        path for path in local if unicodedata.normalize("NFC", path.name) not in seen
    ]


def batched(items: Sequence[Path], size: int) -> Iterator[list[Path]]:
    for start in range(0, len(items), size):
        yield list(items[start : start + size])


def resolve_credentials(environ: dict[str, str]) -> tuple[str, str]:
    """Credentials from the environment, falling back to the local .env.

    NORMCHAT_* wins so a run can target an instance whose credentials differ
    from the developer's. Otherwise this reuses AUTH_USERNAME/AUTH_PASSWORD
    that `Settings` already read from `backend/.env` -- the same gitignored
    file the app reads locally -- so the common case needs no password typed
    anywhere. Falls back to empty, which `login` reads as "gate is off".
    """
    username = environ.get("NORMCHAT_USERNAME")
    password = environ.get("NORMCHAT_PASSWORD")
    if username and password:
        return username, password
    from config import settings

    return settings.auth_username, settings.auth_password


def login(client: httpx.Client, username: str, password: str) -> None:
    """Authenticate, unless the deployment has the gate switched off.

    The server treats empty credentials as "no auth", so an unconfigured
    instance rejects any login. Missing credentials here therefore mean
    "assume the gate is off" rather than an error, and a real 401 with
    credentials supplied is still fatal.
    """
    if not username or not password:
        print("No credentials supplied; assuming authentication is disabled.")
        return
    response = client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    if response.status_code == 401:
        raise SystemExit("Login rejected: check NORMCHAT_USERNAME / NORMCHAT_PASSWORD.")
    response.raise_for_status()
    print("Authenticated.")


def resolve_project(
    client: httpx.Client, project_id: str | None, project_name: str | None
) -> str:
    """Return the id of the target project, creating it only if needed."""
    if project_id:
        response = client.get("/api/projects")
        response.raise_for_status()
        if not any(project["id"] == project_id for project in response.json()):
            raise SystemExit(f"No project with id {project_id} on this instance.")
        return project_id

    response = client.get("/api/projects")
    response.raise_for_status()
    for project in response.json():
        if project["name"] == project_name:
            print(f"Reusing existing project {project['name']} ({project['id']}).")
            return project["id"]

    response = client.post("/api/projects", json={"name": project_name})
    response.raise_for_status()
    project = response.json()
    print(f"Created project {project['name']} ({project['id']}).")
    return project["id"]


def uploaded_filenames(client: httpx.Client, project_id: str) -> set[str]:
    response = client.get(f"/api/projects/{project_id}/documents")
    response.raise_for_status()
    return {document["filename"] for document in response.json()}


def upload_batch(
    client: httpx.Client, project_id: str, paths: list[Path], attempts: int
) -> list[dict]:
    """Upload one batch, retrying only what is safe to retry.

    A 4xx is a verdict on the files themselves and repeating it just wastes
    a long round trip; a transport error or 5xx is worth another attempt.
    """
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        files = [
            ("file", (path.name, path.read_bytes(), "application/pdf"))
            for path in paths
        ]
        try:
            response = client.post(
                f"/api/projects/{project_id}/documents", files=files
            )
        except httpx.TransportError as exc:
            last_error = exc
        else:
            if response.status_code < 400:
                return response.json()
            if response.status_code < 500:
                raise SystemExit(
                    f"Upload rejected ({response.status_code}): {response.text[:400]}"
                )
            last_error = httpx.HTTPStatusError(
                f"{response.status_code}: {response.text[:200]}",
                request=response.request,
                response=response,
            )
        if attempt < attempts:
            backoff = 5 * attempt
            print(f"  attempt {attempt} failed ({last_error}); retrying in {backoff}s")
            time.sleep(backoff)
    raise SystemExit(f"Batch failed after {attempts} attempts: {last_error}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="https://normchat.onrender.com")
    parser.add_argument("--dir", required=True, type=Path)
    parser.add_argument("--project-id")
    parser.add_argument("--project-name")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=DEFAULT_READ_TIMEOUT)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List what would be uploaded, contacting the server read-only.",
    )
    args = parser.parse_args(argv)

    if not args.project_id and not args.project_name:
        parser.error("one of --project-id or --project-name is required")
    if not args.dir.is_dir():
        parser.error(f"not a directory: {args.dir}")

    local = discover_pdfs(args.dir)
    if not local:
        print(f"No PDFs under {args.dir}.")
        return 1
    print(f"Found {len(local)} PDFs under {args.dir}.")

    timeout = httpx.Timeout(30.0, read=args.timeout, write=args.timeout)
    with httpx.Client(base_url=args.base_url, timeout=timeout) as client:
        login(client, *resolve_credentials(dict(os.environ)))
        project_id = resolve_project(client, args.project_id, args.project_name)
        already = uploaded_filenames(client, project_id)
        todo = pending(local, already)

        if already:
            print(f"Project already holds {len(already)} documents; {len(todo)} to go.")
        if not todo:
            print("Nothing to upload; corpus is already complete.")
            return 0
        if args.dry_run:
            for path in todo:
                print(f"  would upload {path.name}")
            return 0

        done = 0
        started = time.monotonic()
        for batch in batched(todo, args.batch_size):
            names = ", ".join(path.name[:60] for path in batch)
            print(f"[{done}/{len(todo)}] uploading {len(batch)}: {names}")
            documents = upload_batch(client, project_id, batch, args.attempts)
            done += len(batch)
            chunks = sum(document.get("chunk_count", 0) for document in documents)
            elapsed = time.monotonic() - started
            print(f"  ok, {chunks} chunks, {elapsed / 60:.1f} min elapsed")

        final = uploaded_filenames(client, project_id)
        print(f"Done. Project holds {len(final)} documents.")
        missing = [path.name for path in local if path.name not in final]
        if missing:
            print(f"WARNING: {len(missing)} file(s) still missing: {missing[:5]}")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
