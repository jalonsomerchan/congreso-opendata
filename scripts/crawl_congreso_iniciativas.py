#!/usr/bin/env python3
"""Descarga cambios en los datasets JSON de iniciativas del Congreso.

La página de Open Data de iniciativas publica varios ficheros JSON de la
legislatura actual. El nombre oficial puede cambiar porque incluye una marca
temporal, así que el script compara el hash del contenido antes de guardar una
nueva instantánea.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urljoin, urlsplit
from urllib.request import Request, urlopen

SOURCE_PAGE = "https://www.congreso.es/es/opendata/iniciativas"
OUT_DIR = Path("data/congreso/iniciativas")
INDEX_FILE = OUT_DIR / "index.json"
LATEST_FILE = OUT_DIR / "latest.json"

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
)
USER_AGENT = os.getenv("CONGRESO_USER_AGENT", DEFAULT_USER_AGENT)
TIMEOUT_SECONDS = 45

HREF_RE = re.compile(r"href=[\'\"](?P<href>[^\'\"]+)[\'\"]", re.IGNORECASE)
INITIATIVE_URL_RE = re.compile(
    r"/opendata/iniciativas/(?P<filename>[^/?#]+\.json)",
    re.IGNORECASE,
)
EXPORT_NAME_RE = re.compile(
    r"^(?P<name>.+?)__(?P<timestamp>\d{14})\.json$",
    re.IGNORECASE,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def request_headers(accept: str, referer: str | None = None) -> dict[str, str]:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": accept,
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.7",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "DNT": "1",
        "Upgrade-Insecure-Requests": "1",
    }
    if referer:
        headers["Referer"] = referer
    return headers


def fetch_text(url: str, *, accept: str | None = None, referer: str | None = None) -> str:
    request = Request(
        url,
        headers=request_headers(
            accept or "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            referer,
        ),
    )
    with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        raw = response.read()
        charset = response.headers.get_content_charset() or "utf-8"
        return raw.decode(charset, errors="replace")


def fetch_json(url: str) -> Any:
    text = fetch_text(
        url,
        accept="application/json,text/plain,*/*;q=0.8",
        referer=SOURCE_PAGE,
    ).lstrip("\ufeff")
    return json.loads(text)


def load_index() -> dict[str, Any]:
    if not INDEX_FILE.exists():
        return {
            "source": SOURCE_PAGE,
            "generated_at": None,
            "total_datasets": 0,
            "datasets": {},
        }
    with INDEX_FILE.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")


def slugify(value: str) -> str:
    value = unquote(value).replace("ñ", "n").replace("Ñ", "n")
    value = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "-", value)
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value or "dataset"


def payload_hash(payload: Any) -> str:
    normalized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def discover_json_links() -> list[str]:
    html = fetch_text(SOURCE_PAGE, referer="https://www.congreso.es/")
    links: set[str] = set()

    for match in HREF_RE.finditer(html):
        href = urljoin(SOURCE_PAGE, match.group("href"))
        parsed = urlsplit(href)
        path = parsed.path.lower()
        if path.endswith(".json") and "/opendata/iniciativas/" in path:
            links.add(href)

    return sorted(links, key=sort_key_for_url)


def parse_initiative_url(url: str) -> dict[str, str]:
    parsed = urlsplit(url)
    match = INITIATIVE_URL_RE.search(parsed.path)
    filename = unquote(match.group("filename")) if match else Path(parsed.path).name
    export_match = EXPORT_NAME_RE.match(filename)

    if export_match:
        official_name = export_match.group("name")
        export_timestamp = export_match.group("timestamp")
    else:
        official_name = Path(filename).stem
        export_timestamp = "unknown"

    dataset_id = slugify(official_name)
    snapshot_name = export_timestamp if export_timestamp != "unknown" else hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
    output_path = OUT_DIR / dataset_id / f"{snapshot_name}.json"

    return {
        "id": dataset_id,
        "official_name": official_name,
        "export_timestamp": export_timestamp,
        "official_filename": filename,
        "path": str(output_path),
    }


def sort_key_for_url(url: str) -> tuple[str, str, str]:
    info = parse_initiative_url(url)
    return (info["id"], info["export_timestamp"], url)


def as_int_env(name: str, default: int = 0) -> int:
    raw = os.getenv(name, str(default)).strip()
    if not raw:
        return default
    try:
        return max(0, int(raw))
    except ValueError:
        print(f"Valor inválido para {name}: {raw!r}. Se usa {default}.", file=sys.stderr)
        return default


def save_dataset(url: str, info: dict[str, str], official_payload: Any, content_hash: str) -> dict[str, Any]:
    captured_at = utc_now()
    output_path = Path(info["path"])

    stored_payload = {
        "metadata": {
            "id": info["id"],
            "source_url": url,
            "captured_at": captured_at,
            "official_name": info["official_name"],
            "export_timestamp": info["export_timestamp"],
            "official_filename": info["official_filename"],
            "content_hash": content_hash,
        },
        "data": official_payload,
    }

    write_json(output_path, stored_payload)
    write_json(output_path.parent / "latest.json", stored_payload)

    return {
        "id": info["id"],
        "source_url": url,
        "path": str(output_path),
        "latest_path": str(output_path.parent / "latest.json"),
        "captured_at": captured_at,
        "official_name": info["official_name"],
        "export_timestamp": info["export_timestamp"],
        "official_filename": info["official_filename"],
        "content_hash": content_hash,
    }


def main() -> int:
    max_new_datasets = as_int_env("MAX_NEW_INITIATIVES", 0)
    index = load_index()
    datasets: dict[str, Any] = index.setdefault("datasets", {})

    try:
        links = discover_json_links()
    except (HTTPError, URLError, TimeoutError) as exc:
        print(f"No se pudo leer la página de iniciativas: {exc}", file=sys.stderr)
        return 1

    changed_records: list[dict[str, Any]] = []

    for url in links:
        info = parse_initiative_url(url)
        dataset_id = info["id"]
        previous = datasets.get(dataset_id)

        if max_new_datasets and len(changed_records) >= max_new_datasets:
            break

        try:
            official_payload = fetch_json(url)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            print(f"No se pudo descargar {url}: {exc}", file=sys.stderr)
            continue

        content_hash = payload_hash(official_payload)
        output_path = Path(info["path"])
        needs_save = (
            previous is None
            or previous.get("content_hash") != content_hash
            or not output_path.exists()
            or not (output_path.parent / "latest.json").exists()
        )

        if not needs_save:
            continue

        record = save_dataset(url, info, official_payload, content_hash)
        if previous is None:
            record["first_seen_at"] = record["captured_at"]
        else:
            record["first_seen_at"] = previous.get("first_seen_at", record["captured_at"])
            record["updated_at"] = record["captured_at"]

        datasets[dataset_id] = record
        changed_records.append(record)
        print(f"Guardado dataset de iniciativas: {dataset_id}")

    if changed_records:
        sorted_datasets = dict(sorted(datasets.items()))
        index["datasets"] = sorted_datasets
        index["source"] = SOURCE_PAGE
        index["generated_at"] = utc_now()
        index["total_datasets"] = len(sorted_datasets)
        index["last_run"] = {
            "checked_at": index["generated_at"],
            "discovered_links": len(links),
            "changed_datasets": len(changed_records),
        }

        write_json(INDEX_FILE, index)
        write_json(
            LATEST_FILE,
            {
                "generated_at": index["generated_at"],
                "source": SOURCE_PAGE,
                "changed_datasets": changed_records,
            },
        )

    print(f"Enlaces descubiertos: {len(links)}")
    print(f"Datasets nuevos o actualizados: {len(changed_records)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
