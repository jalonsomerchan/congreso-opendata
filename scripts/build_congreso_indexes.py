#!/usr/bin/env python3
"""Genera índices derivados por legislatura y por año.

Este script no descarga datos. Lee los índices principales generados por los
crawlers en data/congreso/*/index.json y crea vistas estáticas adicionales:

- data/congreso/legislaturas.json
- data/congreso/{bloque}/legislaturas/index.json
- data/congreso/{bloque}/legislaturas/{legislatura}/index.json
- data/congreso/{bloque}/legislaturas/{legislatura}/latest.json
- data/congreso/{bloque}/legislaturas/{legislatura}/lastest.json
- data/congreso/{bloque}/anios/index.json
- data/congreso/{bloque}/anios/{anio}/index.json
- data/congreso/{bloque}/anios/{anio}/latest.json
- data/congreso/{bloque}/anios/{anio}/lastest.json

El alias lastest.json se genera para tolerar la errata frecuente, pero la ruta
canónica sigue siendo latest.json.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT_DIR = Path("data/congreso")
GENERATED_BY = "scripts/build_congreso_indexes.py"

SECTIONS: dict[str, dict[str, str]] = {
    "votaciones": {
        "records_key": "votes",
        "total_key": "total_votes",
        "record_label": "votaciones",
    },
    "iniciativas": {
        "records_key": "datasets",
        "total_key": "total_datasets",
        "record_label": "datasets",
    },
    "intervenciones": {
        "records_key": "resources",
        "total_key": "total_resources",
        "record_label": "recursos",
    },
    "diputados": {
        "records_key": "datasets",
        "total_key": "total_datasets",
        "record_label": "datasets",
    },
}

EXPLICIT_LEGISLATURE_RE = re.compile(
    r"\b(?:leg|legislatura)\.?\s*(?P<value>[ivxlcdm]+|\d{1,2})\b",
    re.IGNORECASE,
)
YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")
DATE_RE = re.compile(r"^(19\d{2}|20\d{2})\d{4}$")
LATEST_LIMIT = max(1, int(os.getenv("GROUP_LATEST_LIMIT", "20")))


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_json(path: Path) -> Any | None:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = normalized.lower()
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    return normalized or "unknown"


def roman_to_int(value: str) -> int | None:
    value = value.upper().strip()
    if not value or not re.fullmatch(r"[IVXLCDM]+", value):
        return None

    values = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    total = 0
    previous = 0
    for char in reversed(value):
        current = values[char]
        if current < previous:
            total -= current
        else:
            total += current
            previous = current
    return total if 0 < total < 100 else None


def normalize_legislature(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None

    if isinstance(value, int):
        return f"Leg{value}" if 0 < value < 100 else None

    text = str(value).strip()
    if not text:
        return None

    explicit = EXPLICIT_LEGISLATURE_RE.search(text)
    if explicit:
        raw = explicit.group("value")
        if raw.isdigit():
            return f"Leg{int(raw)}"
        roman = roman_to_int(raw)
        if roman:
            return f"Leg{roman}"

    if text.isdigit():
        number = int(text)
        return f"Leg{number}" if 0 < number < 100 else None

    roman = roman_to_int(text)
    if roman:
        return f"Leg{roman}"

    compact = re.fullmatch(r"Leg(\d{1,2})", text, flags=re.IGNORECASE)
    if compact:
        return f"Leg{int(compact.group(1))}"

    return None


def extract_legislatures_from_text(text: str) -> set[str]:
    legislatures: set[str] = set()
    for match in EXPLICIT_LEGISLATURE_RE.finditer(text):
        normalized = normalize_legislature(match.group("value"))
        if normalized:
            legislatures.add(normalized)
    return legislatures


def extract_legislatures(payload: Any) -> set[str]:
    legislatures: set[str] = set()

    def walk(value: Any, key: str = "") -> None:
        key_lower = key.lower()

        if isinstance(value, dict):
            for child_key, child_value in value.items():
                walk(child_value, str(child_key))
            return

        if isinstance(value, list):
            for item in value:
                walk(item, key)
            return

        if value is None:
            return

        text = str(value)

        if "legislatura" in key_lower or "legislature" in key_lower:
            normalized = normalize_legislature(value)
            if normalized:
                legislatures.add(normalized)

        legislatures.update(extract_legislatures_from_text(text))

    walk(payload)
    return legislatures


def extract_years(payload: Any) -> set[str]:
    years: set[str] = set()

    def add_year(value: Any) -> None:
        if value is None:
            return
        text = str(value)
        match = DATE_RE.match(text)
        if match:
            years.add(match.group(1))
            return

        compact_match = re.match(r"^(19\d{2}|20\d{2})\d{4,10}$", text)
        if compact_match:
            years.add(compact_match.group(1))
            return

        for compact_year in re.findall(r"(19\d{2}|20\d{2})\d{4,10}", text):
            years.add(compact_year)

        for year in YEAR_RE.findall(text):
            years.add(year)

    if isinstance(payload, dict):
        for key in (
            "date",
            "fecha",
            "export_timestamp",
            "captured_at",
            "first_seen_at",
            "updated_at",
            "official_filename",
            "source_url",
            "path",
        ):
            add_year(payload.get(key))

        metadata = payload.get("metadata")
        if isinstance(metadata, dict):
            for key in (
                "date",
                "fecha",
                "export_timestamp",
                "captured_at",
                "official_filename",
                "source_url",
                "path",
            ):
                add_year(metadata.get(key))
    else:
        add_year(payload)

    return years


def sort_value(record: dict[str, Any]) -> str:
    values = [
        record.get("date"),
        record.get("export_timestamp"),
        record.get("captured_at"),
        record.get("updated_at"),
        record.get("first_seen_at"),
        record.get("id"),
    ]
    for value in values:
        if value:
            return str(value)
    return ""


def load_detail(record: dict[str, Any]) -> Any | None:
    path_value = record.get("path")
    if not isinstance(path_value, str) or not path_value:
        return None
    return load_json(Path(path_value))


def legislature_sort_key(value: str) -> tuple[int, str]:
    normalized = normalize_legislature(value)
    if normalized:
        return (int(normalized[3:]), normalized)
    return (9999, value)


def enrich_record(record_id: str, record: dict[str, Any]) -> dict[str, Any]:
    detail = load_detail(record)
    legislatures = set(extract_legislatures(record))
    years = set(extract_years(record))

    if detail is not None:
        legislatures.update(extract_legislatures(detail))
        years.update(extract_years(detail))

    if not legislatures:
        legislatures.add("unknown")

    if not years:
        years.add("unknown")

    enriched = dict(record)
    enriched.setdefault("id", record_id)
    enriched["grouping"] = {
        "legislatures": sorted(legislatures, key=legislature_sort_key),
        "years": sorted(years),
    }
    return enriched


def write_group_files(
    *,
    section: str,
    group_type: str,
    group_id: str,
    records: list[dict[str, Any]],
    generated_at: str,
    records_key: str,
) -> dict[str, Any]:
    group_slug = slugify(group_id)
    base_dir_name = "legislaturas" if group_type == "legislature" else "anios"
    group_dir = ROOT_DIR / section / base_dir_name / group_slug
    records_sorted = sorted(records, key=sort_value, reverse=True)
    records_map = {record["id"]: record for record in sorted(records, key=lambda item: item["id"])}

    group_info = {
        "id": group_id,
        "slug": group_slug,
        "type": group_type,
    }

    index_payload = {
        "generated_at": generated_at,
        "generated_by": GENERATED_BY,
        "section": section,
        "group": group_info,
        "total_records": len(records_sorted),
        records_key: records_map,
    }

    latest_payload = {
        "generated_at": generated_at,
        "generated_by": GENERATED_BY,
        "section": section,
        "group": group_info,
        "total_records": len(records_sorted),
        "limit": LATEST_LIMIT,
        "latest_records": records_sorted[:LATEST_LIMIT],
    }

    index_path = group_dir / "index.json"
    latest_path = group_dir / "latest.json"
    lastest_path = group_dir / "lastest.json"

    write_json(index_path, index_payload)
    write_json(latest_path, latest_payload)
    write_json(lastest_path, latest_payload)

    return {
        "id": group_id,
        "slug": group_slug,
        "type": group_type,
        "total_records": len(records_sorted),
        "index_path": str(index_path),
        "latest_path": str(latest_path),
        "lastest_path": str(lastest_path),
    }


def write_collection_index(
    *,
    section: str,
    group_type: str,
    groups: list[dict[str, Any]],
    generated_at: str,
) -> None:
    base_dir_name = "legislaturas" if group_type == "legislature" else "anios"
    key = "legislatures" if group_type == "legislature" else "years"
    collection_path = ROOT_DIR / section / base_dir_name / "index.json"
    write_json(
        collection_path,
        {
            "generated_at": generated_at,
            "generated_by": GENERATED_BY,
            "section": section,
            "group_type": group_type,
            f"total_{key}": len(groups),
            key: groups,
        },
    )


def process_section(section: str, config: dict[str, str], generated_at: str) -> dict[str, Any]:
    index_path = ROOT_DIR / section / "index.json"
    section_index = load_json(index_path)

    if not isinstance(section_index, dict):
        return {
            "section": section,
            "available": False,
            "total_records": 0,
            "legislatures": [],
            "years": [],
        }

    records_key = config["records_key"]
    raw_records = section_index.get(records_key, {})
    if not isinstance(raw_records, dict):
        raw_records = {}

    records: list[dict[str, Any]] = []
    for record_id, record in raw_records.items():
        if isinstance(record, dict):
            records.append(enrich_record(str(record_id), record))

    by_legislature: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_year: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for record in records:
        grouping = record.get("grouping", {})
        for legislature in grouping.get("legislatures", ["unknown"]):
            by_legislature[legislature].append(record)
        for year in grouping.get("years", ["unknown"]):
            by_year[year].append(record)

    legislature_groups = [
        write_group_files(
            section=section,
            group_type="legislature",
            group_id=legislature,
            records=records_for_group,
            generated_at=generated_at,
            records_key=records_key,
        )
        for legislature, records_for_group in sorted(by_legislature.items(), key=lambda item: legislature_sort_key(item[0]))
    ]

    year_groups = [
        write_group_files(
            section=section,
            group_type="year",
            group_id=year,
            records=records_for_group,
            generated_at=generated_at,
            records_key=records_key,
        )
        for year, records_for_group in sorted(by_year.items())
    ]

    write_collection_index(
        section=section,
        group_type="legislature",
        groups=legislature_groups,
        generated_at=generated_at,
    )
    write_collection_index(
        section=section,
        group_type="year",
        groups=year_groups,
        generated_at=generated_at,
    )

    return {
        "section": section,
        "available": True,
        "total_records": len(records),
        "legislatures": legislature_groups,
        "years": year_groups,
    }


def write_global_legislatures(sections_summary: list[dict[str, Any]], generated_at: str) -> None:
    global_map: dict[str, dict[str, Any]] = {}

    for summary in sections_summary:
        section = summary["section"]
        for legislature in summary.get("legislatures", []):
            legislature_id = legislature["id"]
            if legislature_id == "unknown":
                continue

            item = global_map.setdefault(
                legislature_id,
                {
                    "id": legislature_id,
                    "slug": slugify(legislature_id),
                    "sections": {},
                    "total_records": 0,
                },
            )
            item["sections"][section] = {
                "total_records": legislature["total_records"],
                "index_path": legislature["index_path"],
                "latest_path": legislature["latest_path"],
                "lastest_path": legislature["lastest_path"],
            }
            item["total_records"] += legislature["total_records"]

    legislatures = sorted(global_map.values(), key=lambda item: legislature_sort_key(item["id"]))

    write_json(
        ROOT_DIR / "legislaturas.json",
        {
            "generated_at": generated_at,
            "generated_by": GENERATED_BY,
            "total_legislatures": len(legislatures),
            "legislatures": legislatures,
            "sections": sections_summary,
        },
    )


def main() -> int:
    generated_at = utc_now()
    sections_summary = [
        process_section(section, config, generated_at)
        for section, config in SECTIONS.items()
    ]
    write_global_legislatures(sections_summary, generated_at)

    for summary in sections_summary:
        print(
            f"{summary['section']}: "
            f"{summary['total_records']} registros, "
            f"{len(summary.get('legislatures', []))} legislaturas, "
            f"{len(summary.get('years', []))} años"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
