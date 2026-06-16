#!/usr/bin/env python3
"""Descubre y descarga recursos OpenData de intervenciones del Congreso.

La pantalla de intervenciones funciona como buscador y no siempre expone enlaces
estáticos en el HTML inicial. Este crawler recorre los enlaces de recursos
OpenData disponibles en la página y permite añadir URLs concretas mediante la
variable INTERVENCIONES_EXTRA_URLS si el Congreso genera enlaces de exportación
tras aplicar filtros en el navegador.
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

SOURCE_PAGE = "https://www.congreso.es/es/busqueda-de-intervenciones"
OUT_DIR = Path("data/congreso/intervenciones")
INDEX_FILE = OUT_DIR / "index.json"
LATEST_FILE = OUT_DIR / "latest.json"

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
)
USER_AGENT = os.getenv("CONGRESO_USER_AGENT", DEFAULT_USER_AGENT)
TIMEOUT_SECONDS = 45
RESOURCE_EXTENSIONS = {".json", ".csv", ".xml"}

HREF_RE = re.compile(r"href=[\'\"](?P<href>[^\'\"]+)[\'\"]", re.IGNORECASE)
EXPORT_NAME_RE = re.compile(
    r"^(?P<name>.+?)__(?P<timestamp>\d{14})(?P<extension>\.[a-z0-9]+)$",
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


def load_index() -> dict[str, Any]:
    if not INDEX_FILE.exists():
        return {
            "source": SOURCE_PAGE,
            "generated_at": None,
            "total_resources": 0,
            "resources": {},
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
    return value or "recurso"


def parse_extra_urls() -> list[str]:
    raw = os.getenv("INTERVENCIONES_EXTRA_URLS", "")
    if not raw.strip():
        return []
    urls: list[str] = []
    for item in re.split(r"[\n, ]+", raw):
        value = item.strip()
        if value:
            urls.append(value)
    return urls


def looks_like_interventions_resource(url: str) -> bool:
    parsed = urlsplit(url)
    path = unquote(parsed.path)
    lower_url = unquote(url).lower()
    suffix = Path(path).suffix.lower()

    if suffix not in RESOURCE_EXTENSIONS:
        return False

    if "intervencion" in lower_url or "intervenciones" in lower_url:
        return True

    return "/opendata/" in lower_url and "busqueda-de-intervenciones" not in lower_url


def discover_resource_links() -> list[str]:
    html = fetch_text(SOURCE_PAGE, referer="https://www.congreso.es/")
    links: set[str] = set(parse_extra_urls())

    for match in HREF_RE.finditer(html):
        href = urljoin(SOURCE_PAGE, match.group("href"))
        if looks_like_interventions_resource(href):
            links.add(href)

    return sorted(links, key=sort_key_for_url)


def parse_resource_url(url: str) -> dict[str, str]:
    parsed = urlsplit(url)
    filename = unquote(Path(parsed.path).name) or hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
    extension = Path(filename).suffix.lower() or ".txt"
    export_match = EXPORT_NAME_RE.match(filename)

    if export_match:
        official_name = export_match.group("name")
        export_timestamp = export_match.group("timestamp")
    else:
        official_name = Path(filename).stem or "intervenciones"
        export_timestamp = "unknown"

    resource_id = slugify(official_name)
    snapshot_name = export_timestamp if export_timestamp != "unknown" else hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
    output_path = OUT_DIR / resource_id / f"{snapshot_name}.json"

    return {
        "id": resource_id,
        "official_name": official_name,
        "export_timestamp": export_timestamp,
        "official_filename": filename,
        "extension": extension.lstrip("."),
        "path": str(output_path),
    }


def sort_key_for_url(url: str) -> tuple[str, str, str]:
    info = parse_resource_url(url)
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


def decode_resource(url: str, extension: str) -> tuple[Any, str, str]:
    accept_by_extension = {
        "json": "application/json,text/plain,*/*;q=0.8",
        "csv": "text/csv,text/plain,*/*;q=0.8",
        "xml": "application/xml,text/xml,text/plain,*/*;q=0.8",
    }
    text = fetch_text(
        url,
        accept=accept_by_extension.get(extension, "text/plain,*/*;q=0.8"),
        referer=SOURCE_PAGE,
    ).lstrip("\ufeff")
    content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()

    if extension == "json":
        return json.loads(text), "json", content_hash

    return text, extension, content_hash


def save_resource(url: str, info: dict[str, str], payload: Any, payload_format: str, content_hash: str) -> dict[str, Any]:
    captured_at = utc_now()
    output_path = Path(info["path"])

    stored_payload: dict[str, Any] = {
        "metadata": {
            "id": info["id"],
            "source_url": url,
            "captured_at": captured_at,
            "official_name": info["official_name"],
            "export_timestamp": info["export_timestamp"],
            "official_filename": info["official_filename"],
            "format": payload_format,
            "content_hash": content_hash,
        }
    }

    if payload_format == "json":
        stored_payload["data"] = payload
    else:
        stored_payload["data_raw"] = payload

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
        "format": payload_format,
        "content_hash": content_hash,
    }


def write_empty_discovery_index_if_needed(index: dict[str, Any], discovered_links: int) -> bool:
    if INDEX_FILE.exists():
        return False

    generated_at = utc_now()
    index["source"] = SOURCE_PAGE
    index["generated_at"] = generated_at
    index["total_resources"] = 0
    index["last_run"] = {
        "checked_at": generated_at,
        "discovered_links": discovered_links,
        "changed_resources": 0,
        "note": (
            "La página de intervenciones no expuso enlaces estáticos OpenData "
            "en esta ejecución. El crawler seguirá comprobándolo en cada run."
        ),
    }
    write_json(INDEX_FILE, index)
    write_json(
        LATEST_FILE,
        {
            "generated_at": generated_at,
            "source": SOURCE_PAGE,
            "changed_resources": [],
            "discovered_links": discovered_links,
        },
    )
    return True


def main() -> int:
    max_new_resources = as_int_env("MAX_NEW_INTERVENTIONS", 0)
    index = load_index()
    resources: dict[str, Any] = index.setdefault("resources", {})

    try:
        links = discover_resource_links()
    except (HTTPError, URLError, TimeoutError) as exc:
        print(f"No se pudo leer la página de intervenciones: {exc}", file=sys.stderr)
        return 1

    changed_records: list[dict[str, Any]] = []

    for url in links:
        info = parse_resource_url(url)
        resource_id = info["id"]
        previous = resources.get(resource_id)

        if max_new_resources and len(changed_records) >= max_new_resources:
            break

        try:
            payload, payload_format, content_hash = decode_resource(url, info["extension"])
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            print(f"No se pudo descargar {url}: {exc}", file=sys.stderr)
            continue

        output_path = Path(info["path"])
        needs_save = (
            previous is None
            or previous.get("content_hash") != content_hash
            or previous.get("source_url") != url
            or not output_path.exists()
            or not (output_path.parent / "latest.json").exists()
        )

        if not needs_save:
            continue

        record = save_resource(url, info, payload, payload_format, content_hash)
        if previous is None:
            record["first_seen_at"] = record["captured_at"]
        else:
            record["first_seen_at"] = previous.get("first_seen_at", record["captured_at"])
            record["updated_at"] = record["captured_at"]

        resources[resource_id] = record
        changed_records.append(record)
        print(f"Guardado recurso de intervenciones: {resource_id}")

    wrote_empty_index = False
    if not links:
        wrote_empty_index = write_empty_discovery_index_if_needed(index, len(links))

    if changed_records:
        sorted_resources = dict(sorted(resources.items()))
        index["resources"] = sorted_resources
        index["source"] = SOURCE_PAGE
        index["generated_at"] = utc_now()
        index["total_resources"] = len(sorted_resources)
        index["last_run"] = {
            "checked_at": index["generated_at"],
            "discovered_links": len(links),
            "changed_resources": len(changed_records),
        }

        write_json(INDEX_FILE, index)
        write_json(
            LATEST_FILE,
            {
                "generated_at": index["generated_at"],
                "source": SOURCE_PAGE,
                "changed_resources": changed_records,
            },
        )

    print(f"Enlaces descubiertos: {len(links)}")
    print(f"Recursos nuevos o actualizados: {len(changed_records)}")
    if wrote_empty_index:
        print("Creado índice inicial sin recursos estáticos de intervenciones")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
