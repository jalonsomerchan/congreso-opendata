#!/usr/bin/env python3
"""Descarga nuevas votaciones publicadas en el Open Data del Congreso.

El script lee la página oficial de votaciones, extrae enlaces JSON, guarda cada
votación en un fichero estable y mantiene un índice para evitar duplicados.
No usa dependencias externas para que pueda ejecutarse directamente en GitHub
Actions con Python 3.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

SOURCE_PAGE = "https://www.congreso.es/es/opendata/votaciones"
OUT_DIR = Path("data/congreso/votaciones")
INDEX_FILE = OUT_DIR / "index.json"
LATEST_FILE = OUT_DIR / "latest.json"

# El Congreso puede devolver 403 a user agents claramente automatizados desde
# GitHub Actions. Usamos cabeceras de navegador, sin dependencias externas, para
# acceder al mismo HTML público que se sirve a un usuario normal.
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
)
USER_AGENT = os.getenv("CONGRESO_USER_AGENT", DEFAULT_USER_AGENT)
TIMEOUT_SECONDS = 45

VOTE_URL_RE = re.compile(
    r"/opendata/votaciones/"
    r"(?P<legislature>Leg\d+)/"
    r"(?P<session>Sesion\d+)/"
    r"(?P<date>\d{8})/"
    r"(?P<vote>Votacion\d+)/"
    r"(?P<filename>[^/?#]+\.json)",
    re.IGNORECASE,
)

HREF_RE = re.compile(r"href=[\'\"](?P<href>[^\'\"]+)[\'\"]", re.IGNORECASE)


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
            "total_votes": 0,
            "votes": {},
        }

    with INDEX_FILE.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")


def discover_vote_links() -> list[str]:
    html = fetch_text(SOURCE_PAGE, referer="https://www.congreso.es/")
    links: set[str] = set()

    for match in HREF_RE.finditer(html):
        href = urljoin(SOURCE_PAGE, match.group("href"))
        parsed = urlsplit(href)
        path = parsed.path.lower()

        if path.endswith(".json") and "/opendata/votaciones/" in path:
            links.add(href)

    return sorted(links, key=sort_key_for_url)


def parse_vote_url(url: str) -> dict[str, str]:
    parsed = urlsplit(url)
    match = VOTE_URL_RE.search(parsed.path)

    if not match:
        safe_id = re.sub(r"[^a-z0-9]+", "-", parsed.path.lower()).strip("-")
        return {
            "id": safe_id,
            "legislature": "unknown",
            "session": "unknown",
            "date": "unknown",
            "vote": "unknown",
            "filename": f"{safe_id}.json",
            "path": str(OUT_DIR / "unknown" / f"{safe_id}.json"),
        }

    legislature = match.group("legislature")
    session = match.group("session")
    date = match.group("date")
    vote = match.group("vote")
    vote_id = f"{legislature}-{session}-{date}-{vote}".lower()
    output_path = OUT_DIR / legislature.lower() / session.lower() / date / f"{vote.lower()}.json"

    return {
        "id": vote_id,
        "legislature": legislature,
        "session": session,
        "date": date,
        "vote": vote,
        "filename": match.group("filename"),
        "path": str(output_path),
    }


def sort_key_for_url(url: str) -> tuple[str, str, str, str, str]:
    info = parse_vote_url(url)
    return (
        info["date"],
        info["legislature"],
        info["session"],
        info["vote"],
        url,
    )


def as_int_env(name: str, default: int = 0) -> int:
    raw = os.getenv(name, str(default)).strip()
    if not raw:
        return default
    try:
        return max(0, int(raw))
    except ValueError:
        print(f"Valor inválido para {name}: {raw!r}. Se usa {default}.", file=sys.stderr)
        return default


def save_vote(url: str, info: dict[str, str]) -> dict[str, Any]:
    official_payload = fetch_json(url)
    captured_at = utc_now()
    output_path = Path(info["path"])

    stored_payload = {
        "metadata": {
            "id": info["id"],
            "source_url": url,
            "captured_at": captured_at,
            "legislature": info["legislature"],
            "session": info["session"],
            "date": info["date"],
            "vote": info["vote"],
            "official_filename": info["filename"],
        },
        "data": official_payload,
    }

    write_json(output_path, stored_payload)

    return {
        "id": info["id"],
        "source_url": url,
        "path": str(output_path),
        "captured_at": captured_at,
        "legislature": info["legislature"],
        "session": info["session"],
        "date": info["date"],
        "vote": info["vote"],
        "official_filename": info["filename"],
    }


def main() -> int:
    max_new_votes = as_int_env("MAX_NEW_VOTES", 0)
    index = load_index()
    votes: dict[str, Any] = index.setdefault("votes", {})

    try:
        links = discover_vote_links()
    except (HTTPError, URLError, TimeoutError) as exc:
        print(f"No se pudo leer la página de votaciones: {exc}", file=sys.stderr)
        return 1

    changed_records: list[dict[str, Any]] = []

    for url in links:
        info = parse_vote_url(url)
        vote_id = info["id"]
        previous = votes.get(vote_id)
        output_path = Path(info["path"])

        needs_download = (
            previous is None
            or previous.get("source_url") != url
            or not output_path.exists()
        )

        if not needs_download:
            continue

        if max_new_votes and len(changed_records) >= max_new_votes:
            break

        try:
            record = save_vote(url, info)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            print(f"No se pudo descargar {url}: {exc}", file=sys.stderr)
            continue

        if previous is None:
            record["first_seen_at"] = record["captured_at"]
        else:
            record["first_seen_at"] = previous.get("first_seen_at", record["captured_at"])
            record["updated_at"] = record["captured_at"]

        votes[vote_id] = record
        changed_records.append(record)
        print(f"Guardada votación: {vote_id}")

    if changed_records:
        sorted_votes = dict(sorted(votes.items()))
        index["votes"] = sorted_votes
        index["source"] = SOURCE_PAGE
        index["generated_at"] = utc_now()
        index["total_votes"] = len(sorted_votes)
        index["last_run"] = {
            "checked_at": index["generated_at"],
            "discovered_links": len(links),
            "changed_votes": len(changed_records),
        }

        write_json(INDEX_FILE, index)
        write_json(
            LATEST_FILE,
            {
                "generated_at": index["generated_at"],
                "source": SOURCE_PAGE,
                "changed_votes": changed_records,
            },
        )

    print(f"Enlaces descubiertos: {len(links)}")
    print(f"Votaciones nuevas o actualizadas: {len(changed_records)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
