#!/usr/bin/env python3
"""Extract structured entries from text-based PDFs and export Markdown/tables."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import sys
import tempfile
import unicodedata
from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import pdfplumber


TABLE_INPUT_SUFFIXES = {".csv", ".tsv", ".xlsx", ".xls"}
TABLE_OUTPUT_SUFFIXES = {".csv", ".tsv", ".xlsx"}

GENERIC_PROFILE: dict[str, Any] = {
    "profile_name": "generic",
    "layout": {
        "columns": "auto",
        "column_split_ratio": 0.5,
        "top_margin_ratio": 0.0,
        "bottom_margin_ratio": 0.0,
        "y_tolerance": 3.0,
        "x_tolerance": 3.0,
        "join_gap_ratio": 0.45,
        "auto_min_gap_ratio": 0.025,
        "auto_min_aligned_row_ratio": 0.25,
    },
    "text": {
        "unicode_normalization": "NFKC",
        "collapse_whitespace": True,
        "regex_replacements": [],
        "ignore_line_patterns": [],
    },
    "entry": {
        "mode": "page",
        "title_sequence": [],
        "name_field": "display_name",
        "include_preface": False,
        "normalization": {
            "unicode_normalization": "NFKC",
            "remove_parenthetical": False,
            "remove_chars": [],
            "remove_whitespace": False,
            "casefold": False,
        },
    },
    "fields": {
        "capture_bracket_fields": True,
        "include": [],
        "exclude": [],
        "join_wrapped_lines": False,
        "duplicate_separator": "\n\n",
        "default_merge_fields": [],
    },
    "markdown": {
        "emit_title_fields": [],
        "section_separator": "---",
    },
}


@dataclass(frozen=True)
class TextLine:
    text: str
    source_file: str
    page_number: int
    top: float
    column: int


@dataclass
class Section:
    title: dict[str, str]
    title_lines: list[TextLine]
    body_lines: list[TextLine]
    normalized_name: str = ""
    fields: dict[str, str] = field(default_factory=dict)

    @property
    def display_name(self) -> str:
        return self.title.get("display_name") or next(iter(self.title.values()), "Untitled")

    @property
    def all_lines(self) -> list[TextLine]:
        return [*self.title_lines, *self.body_lines]


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def load_profile(config_path: str | None) -> dict[str, Any]:
    profile = deepcopy(GENERIC_PROFILE)
    if config_path:
        path = Path(config_path).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"Configuration file does not exist: {path}")
        with path.open("r", encoding="utf-8") as file:
            custom = json.load(file)
        if not isinstance(custom, dict):
            raise ValueError("The top level of a configuration file must be a JSON object.")
        profile = deep_merge(profile, custom)

    validate_profile(profile)
    return profile


def validate_profile(profile: dict[str, Any]) -> None:
    layout = profile["layout"]
    if str(layout["columns"]) not in {"auto", "1", "2"}:
        raise ValueError("layout.columns must be auto, 1, or 2.")
    for key in ("column_split_ratio", "top_margin_ratio", "bottom_margin_ratio"):
        value = float(layout[key])
        if not 0 <= value < 1:
            raise ValueError(f"layout.{key} must be between 0 and 1.")
    if float(layout["top_margin_ratio"]) + float(layout["bottom_margin_ratio"]) >= 1:
        raise ValueError("The top and bottom margins leave no usable page area.")
    if profile["entry"]["mode"] not in {"page", "sequence"}:
        raise ValueError("entry.mode must be page or sequence.")
    if profile["entry"]["mode"] == "sequence" and not profile["entry"]["title_sequence"]:
        raise ValueError("entry.title_sequence is required in sequence mode.")
    for rule in profile["entry"]["title_sequence"]:
        if not rule.get("field") or not rule.get("pattern"):
            raise ValueError("Each title sequence rule requires field and pattern.")
        re.compile(rule["pattern"])
    for item in profile["text"]["regex_replacements"]:
        re.compile(item["pattern"])
    for pattern in profile["text"]["ignore_line_patterns"]:
        re.compile(pattern)


def natural_key(value: str) -> list[tuple[int, Any]]:
    return [
        (1, int(part)) if part.isdigit() else (0, part.casefold())
        for part in re.split(r"(\d+)", value)
        if part
    ]


def discover_pdf_files(
    input_path: Path,
    pattern: str,
    recursive: bool,
    start_file: str | None,
    end_file: str | None,
) -> list[Path]:
    input_path = input_path.expanduser().resolve()
    if not input_path.exists():
        raise FileNotFoundError(f"Input path does not exist: {input_path}")
    if input_path.is_file():
        if input_path.suffix.lower() != ".pdf":
            raise ValueError("A file input must have a .pdf extension.")
        files = [input_path]
        root = input_path.parent
    else:
        iterator = input_path.rglob(pattern) if recursive else input_path.glob(pattern)
        files = [path.resolve() for path in iterator if path.is_file() and path.suffix.lower() == ".pdf"]
        root = input_path

    files.sort(key=lambda path: natural_key(path.relative_to(root).as_posix()))
    if not files:
        raise ValueError(f"No PDF files matched {pattern!r} under {input_path}.")

    start_index = find_boundary_index(files, root, start_file, "start") if start_file else 0
    end_index = find_boundary_index(files, root, end_file, "end") if end_file else len(files) - 1
    if start_index > end_index:
        raise ValueError("--start-file occurs after --end-file in natural file order.")
    return files[start_index : end_index + 1]


def find_boundary_index(files: list[Path], root: Path, value: str, label: str) -> int:
    matches = [
        index
        for index, path in enumerate(files)
        if path.name == value or path.relative_to(root).as_posix() == value
    ]
    if not matches:
        raise ValueError(f"The {label} file was not found among selected PDFs: {value}")
    if len(matches) > 1:
        raise ValueError(f"The {label} file name is ambiguous; use its relative path: {value}")
    return matches[0]


def parse_page_spec(spec: str | None) -> list[tuple[int, int | None]] | None:
    if not spec:
        return None
    ranges: list[tuple[int, int | None]] = []
    for raw_part in spec.split(","):
        part = raw_part.strip()
        if not part:
            raise ValueError(f"Invalid page selection: {spec}")
        if "-" not in part:
            number = int(part)
            if number < 1:
                raise ValueError("Page numbers start at 1.")
            ranges.append((number, number))
            continue
        start_raw, end_raw = part.split("-", 1)
        start = int(start_raw) if start_raw else 1
        end = int(end_raw) if end_raw else None
        if start < 1 or (end is not None and end < start):
            raise ValueError(f"Invalid page range: {part}")
        ranges.append((start, end))
    return ranges


def page_selected(page_number: int, ranges: list[tuple[int, int | None]] | None) -> bool:
    if ranges is None:
        return True
    return any(page_number >= start and (end is None or page_number <= end) for start, end in ranges)


def cluster_rows(words: list[dict[str, Any]], y_tolerance: float) -> list[list[dict[str, Any]]]:
    rows: list[list[dict[str, Any]]] = []
    anchors: list[float] = []
    for word in sorted(words, key=lambda item: (float(item["top"]), float(item["x0"]))):
        top = float(word["top"])
        if not rows or abs(top - anchors[-1]) > y_tolerance:
            rows.append([word])
            anchors.append(top)
        else:
            rows[-1].append(word)
            anchors[-1] = sum(float(item["top"]) for item in rows[-1]) / len(rows[-1])
    for row in rows:
        row.sort(key=lambda item: float(item["x0"]))
    return rows


def looks_latin_or_numeric(character: str) -> bool:
    normalized = unicodedata.normalize("NFKC", character)
    return bool(re.fullmatch(r"[A-Za-z0-9]", normalized))


def looks_cjk(character: str) -> bool:
    return "\u3400" <= character <= "\u9fff"


def join_words(words: list[dict[str, Any]], join_gap_ratio: float) -> str:
    if not words:
        return ""
    result = str(words[0]["text"])
    previous = words[0]
    for current in words[1:]:
        previous_text = str(previous["text"])
        current_text = str(current["text"])
        gap = float(current["x0"]) - float(previous["x1"])
        previous_width = max(float(previous["x1"]) - float(previous["x0"]), 0.1)
        current_width = max(float(current["x1"]) - float(current["x0"]), 0.1)
        previous_char_width = previous_width / max(len(previous_text), 1)
        current_char_width = current_width / max(len(current_text), 1)
        gap_threshold = max(1.0, min(previous_char_width, current_char_width) * join_gap_ratio)
        latin_boundary = (
            previous_text
            and current_text
            and looks_latin_or_numeric(previous_text[-1])
            and looks_latin_or_numeric(current_text[0])
        )
        cjk_boundary = (
            previous_text
            and current_text
            and looks_cjk(previous_text[-1])
            and looks_cjk(current_text[0])
        )
        if not cjk_boundary and (gap > gap_threshold or (gap > 0 and latin_boundary)):
            result += " "
        result += current_text
        previous = current
    return result


def detect_column_count(rows: list[list[dict[str, Any]]], page_width: float, layout: dict[str, Any]) -> int:
    split_x = page_width * float(layout["column_split_ratio"])
    min_gap = page_width * float(layout["auto_min_gap_ratio"])
    informative_rows = 0
    aligned_rows = 0
    for row in rows:
        left = [word for word in row if (float(word["x0"]) + float(word["x1"])) / 2 < split_x]
        right = [word for word in row if (float(word["x0"]) + float(word["x1"])) / 2 >= split_x]
        if not left or not right:
            continue
        informative_rows += 1
        left_edge = max(float(word["x1"]) for word in left)
        right_edge = min(float(word["x0"]) for word in right)
        if right_edge - left_edge >= min_gap:
            aligned_rows += 1
    required = max(4, math.ceil(max(len(rows), 1) * float(layout["auto_min_aligned_row_ratio"])))
    return 2 if informative_rows >= required and aligned_rows >= required else 1


def clean_text(text: str, text_config: dict[str, Any]) -> str:
    normalization = text_config.get("unicode_normalization")
    if normalization:
        text = unicodedata.normalize(normalization, text)
    for item in text_config.get("regex_replacements", []):
        text = re.sub(item["pattern"], item.get("replacement", ""), text)
    if text_config.get("collapse_whitespace", True):
        text = re.sub(r"\s+", " ", text)
    return text.strip()


def extract_page_lines(
    page: Any,
    source_file: Path,
    page_number: int,
    profile: dict[str, Any],
) -> tuple[list[TextLine], int]:
    layout = profile["layout"]
    words = page.extract_words(
        use_text_flow=False,
        keep_blank_chars=False,
        x_tolerance=float(layout["x_tolerance"]),
        y_tolerance=float(layout["y_tolerance"]),
    ) or []
    page_height = float(page.height)
    page_width = float(page.width)
    top_limit = page_height * float(layout["top_margin_ratio"])
    bottom_limit = page_height * (1 - float(layout["bottom_margin_ratio"]))
    words = [
        word
        for word in words
        if float(word["top"]) >= top_limit and float(word["bottom"]) <= bottom_limit
    ]
    if not words:
        return [], 1

    rows = cluster_rows(words, float(layout["y_tolerance"]))
    configured_columns = str(layout["columns"])
    column_count = detect_column_count(rows, page_width, layout) if configured_columns == "auto" else int(configured_columns)
    split_x = page_width * float(layout["column_split_ratio"])
    column_rows: list[list[tuple[float, list[dict[str, Any]]]]] = [[] for _ in range(column_count)]

    for row in rows:
        if column_count == 1:
            column_rows[0].append((min(float(word["top"]) for word in row), row))
            continue
        for column_index in range(2):
            selected = [
                word
                for word in row
                if (((float(word["x0"]) + float(word["x1"])) / 2 < split_x) == (column_index == 0))
            ]
            if selected:
                column_rows[column_index].append((min(float(word["top"]) for word in selected), selected))

    ignore_patterns = [re.compile(pattern) for pattern in profile["text"].get("ignore_line_patterns", [])]
    lines: list[TextLine] = []
    for column_index, positioned_rows in enumerate(column_rows):
        for top, row_words in sorted(positioned_rows, key=lambda item: item[0]):
            raw_text = join_words(row_words, float(layout["join_gap_ratio"]))
            text = clean_text(raw_text, profile["text"])
            if not text or any(pattern.fullmatch(text) for pattern in ignore_patterns):
                continue
            lines.append(TextLine(text, str(source_file), page_number, top, column_index + 1))
    return lines, 0


def extract_document_lines(
    files: list[Path],
    page_ranges: list[tuple[int, int | None]] | None,
    profile: dict[str, Any],
    strict: bool,
    verbose: bool,
) -> tuple[list[TextLine], dict[str, Any]]:
    all_lines: list[TextLine] = []
    stats: dict[str, Any] = {
        "files_selected": len(files),
        "files_processed": 0,
        "pages_selected": 0,
        "pages_without_text": [],
        "errors": [],
    }
    for path in files:
        if verbose:
            print(f"Reading {path}")
        try:
            with pdfplumber.open(path) as pdf:
                for page_number, page in enumerate(pdf.pages, start=1):
                    if not page_selected(page_number, page_ranges):
                        continue
                    stats["pages_selected"] += 1
                    try:
                        lines, empty = extract_page_lines(page, path, page_number, profile)
                        all_lines.extend(lines)
                        if empty:
                            stats["pages_without_text"].append(
                                {"file": str(path), "page": page_number}
                            )
                    except Exception as exc:  # Keep other PDFs usable in non-strict mode.
                        error = {"file": str(path), "page": page_number, "message": str(exc)}
                        stats["errors"].append(error)
                        if strict:
                            raise
            stats["files_processed"] += 1
        except Exception as exc:
            if strict:
                raise
            if not any(item["file"] == str(path) and item.get("page") for item in stats["errors"]):
                stats["errors"].append({"file": str(path), "page": None, "message": str(exc)})
    return all_lines, stats


def normalize_key(value: Any, config: dict[str, Any]) -> str:
    text = "" if value is None else str(value).strip()
    normalization = config.get("unicode_normalization")
    if normalization:
        text = unicodedata.normalize(normalization, text)
    if config.get("remove_parenthetical"):
        text = re.sub(r"（[^（）]*）|\([^()]*\)", "", text)
    for character in config.get("remove_chars", []):
        text = text.replace(character, "")
    if config.get("remove_whitespace"):
        text = re.sub(r"\s+", "", text)
    if config.get("casefold"):
        text = text.casefold()
    return text.strip()


def segment_by_page(lines: list[TextLine], profile: dict[str, Any]) -> tuple[list[Section], int]:
    grouped: dict[tuple[str, int], list[TextLine]] = {}
    for line in lines:
        grouped.setdefault((line.source_file, line.page_number), []).append(line)
    sections: list[Section] = []
    for (source_file, page_number), page_lines in grouped.items():
        title = f"{Path(source_file).stem} - page {page_number}"
        section = Section({"display_name": title}, [], page_lines)
        section.normalized_name = normalize_key(title, profile["entry"]["normalization"])
        sections.append(section)
    return sections, 0


def match_title_sequence(
    lines: list[TextLine],
    index: int,
    rules: list[dict[str, str]],
) -> dict[str, str] | None:
    if index + len(rules) > len(lines):
        return None
    values: dict[str, str] = {}
    for offset, rule in enumerate(rules):
        match = re.fullmatch(rule["pattern"], lines[index + offset].text)
        if not match:
            return None
        value = match.groupdict().get("value") or match.group(0)
        if rule.get("remove_whitespace"):
            value = re.sub(r"\s+", "", value)
        values[rule["field"]] = value.strip()
    return values


def segment_by_sequence(lines: list[TextLine], profile: dict[str, Any]) -> tuple[list[Section], int]:
    entry_config = profile["entry"]
    rules = entry_config["title_sequence"]
    sections: list[Section] = []
    preface: list[TextLine] = []
    current: Section | None = None
    index = 0
    while index < len(lines):
        title = match_title_sequence(lines, index, rules)
        if title is not None:
            for field_name, replacements in entry_config.get("value_replacements", {}).items():
                if field_name in title:
                    title[field_name] = replacements.get(title[field_name], title[field_name])
            if current is not None:
                sections.append(current)
            title_lines = lines[index : index + len(rules)]
            current = Section(title, title_lines, [])
            index += len(rules)
            continue
        if current is None:
            preface.append(lines[index])
        else:
            current.body_lines.append(lines[index])
        index += 1
    if current is not None:
        sections.append(current)

    if entry_config.get("include_preface") and preface:
        sections.insert(0, Section({"display_name": "Preface"}, [], preface))
    normalization = entry_config["normalization"]
    name_field = entry_config["name_field"]
    for section in sections:
        section.normalized_name = normalize_key(section.title.get(name_field, section.display_name), normalization)
    return sections, len(preface)


def segment_lines(lines: list[TextLine], profile: dict[str, Any]) -> tuple[list[Section], int]:
    if profile["entry"]["mode"] == "page":
        return segment_by_page(lines, profile)
    return segment_by_sequence(lines, profile)


def extract_bracket_fields(section: Section, config: dict[str, Any]) -> dict[str, str]:
    if not config.get("capture_bracket_fields", True):
        return {}
    text = "\n".join(line.text for line in section.body_lines)
    markers = list(re.finditer(r"【([^】\n]{1,80})】", text))
    included = set(config.get("include", []))
    excluded = set(config.get("exclude", []))
    values: dict[str, list[str]] = defaultdict(list)
    for index, marker in enumerate(markers):
        name = marker.group(1).strip()
        if (included and name not in included) or name in excluded:
            continue
        end = markers[index + 1].start() if index + 1 < len(markers) else len(text)
        value = text[marker.end() : end].strip()
        if config.get("join_wrapped_lines"):
            value = re.sub(r"\s*\n\s*", "", value)
        if value:
            values[name].append(value)
    separator = config.get("duplicate_separator", "\n\n")
    return {name: separator.join(items) for name, items in values.items()}


def populate_fields(sections: list[Section], profile: dict[str, Any]) -> None:
    for section in sections:
        section.fields = extract_bracket_fields(section, profile["fields"])


def section_source(section: Section, first: bool) -> tuple[str, int]:
    lines = section.all_lines
    if not lines:
        return "", 0
    line = lines[0] if first else lines[-1]
    return line.source_file, line.page_number


def records_dataframe(sections: list[Section], profile: dict[str, Any]) -> pd.DataFrame:
    title_fields = [
        rule["field"]
        for rule in profile["entry"].get("title_sequence", [])
        if rule["field"] != "display_name"
    ]
    field_names: list[str] = []
    seen_fields: set[str] = set()
    for section in sections:
        for name in section.fields:
            if name not in seen_fields:
                seen_fields.add(name)
                field_names.append(name)

    rows: list[dict[str, Any]] = []
    for section in sections:
        start_file, start_page = section_source(section, True)
        end_file, end_page = section_source(section, False)
        row: dict[str, Any] = {
            "name": section.display_name,
            "normalized_name": section.normalized_name,
        }
        for name in title_fields:
            row[name] = section.title.get(name, "")
        row.update(
            {
                "source_start_file": start_file,
                "source_start_page": start_page,
                "source_end_file": end_file,
                "source_end_page": end_page,
                "text": "\n".join(line.text for line in section.body_lines),
            }
        )
        for name in field_names:
            row[name] = section.fields.get(name, "")
        rows.append(row)
    return pd.DataFrame(rows)


def ensure_output_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def write_markdown(path: Path, sections: list[Section], profile: dict[str, Any], heading_level: int) -> None:
    ensure_output_parent(path)
    emit_fields = profile["markdown"].get("emit_title_fields", [])
    separator = profile["markdown"].get("section_separator", "---")
    with path.open("w", encoding="utf-8", newline="\n") as file:
        for section in sections:
            file.write(f"{'#' * heading_level} {section.display_name}\n\n")
            for name in emit_fields:
                value = section.title.get(name, "")
                if value and value != section.display_name:
                    file.write(value + "\n")
            if emit_fields and any(section.title.get(name) for name in emit_fields):
                file.write("\n")
            for line in section.body_lines:
                file.write(line.text + "\n")
            if separator:
                file.write(f"\n{separator}\n\n")
            else:
                file.write("\n")


def write_dataframe(path: Path, dataframe: pd.DataFrame) -> None:
    suffix = path.suffix.lower()
    if suffix not in TABLE_OUTPUT_SUFFIXES:
        raise ValueError("Table output must be .csv, .tsv, or .xlsx.")
    ensure_output_parent(path)
    if suffix == ".xlsx":
        dataframe.to_excel(path, index=False)
    else:
        dataframe.to_csv(path, sep="\t" if suffix == ".tsv" else ",", index=False, encoding="utf-8-sig")


def parse_sheet(value: str) -> str | int:
    return int(value) if value.isdigit() else value


def read_dataframe(path: Path, sheet: str | int) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix not in TABLE_INPUT_SUFFIXES:
        raise ValueError("Merge input must be .csv, .tsv, .xlsx, or .xls.")
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path, dtype=str, sheet_name=sheet).fillna("")
    return pd.read_csv(path, dtype=str, sep="\t" if suffix == ".tsv" else ",", keep_default_na=False)


def parse_merge_fields(raw_fields: list[str] | None, profile: dict[str, Any]) -> list[tuple[str, str]]:
    values = raw_fields or profile["fields"].get("default_merge_fields", [])
    result: list[tuple[str, str]] = []
    for value in values:
        source, separator, target = value.partition(":")
        source = source.strip()
        target = target.strip() if separator else source
        if not source or not target:
            raise ValueError(f"Invalid --merge-field value: {value}")
        result.append((source, target))
    if not result:
        raise ValueError("At least one --merge-field is required for table merging.")
    return result


def choose_duplicate_section(sections: list[Section], policy: str) -> Section:
    if policy == "first":
        return sections[0]
    return sections[-1]


def merge_records_into_table(
    dataframe: pd.DataFrame,
    sections: list[Section],
    key_column: str,
    merge_fields: list[tuple[str, str]],
    duplicate_policy: str,
    normalization: dict[str, Any],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    if key_column not in dataframe.columns:
        raise ValueError(f"Merge key column does not exist: {key_column}")
    grouped: dict[str, list[Section]] = defaultdict(list)
    for section in sections:
        if section.normalized_name:
            grouped[section.normalized_name].append(section)
    duplicates = {name: items for name, items in grouped.items() if len(items) > 1}
    if duplicates and duplicate_policy == "error":
        preview = ", ".join(list(duplicates)[:10])
        raise ValueError(f"Duplicate extracted names prevent an unambiguous merge: {preview}")

    for _, target in merge_fields:
        if target not in dataframe.columns:
            dataframe[target] = ""

    normalized_keys = dataframe[key_column].map(lambda value: normalize_key(value, normalization))
    matched_rows = 0
    updated_cells = 0
    unmatched_table_keys: set[str] = set()
    matched_extracted_keys: set[str] = set()
    for row_index, normalized in normalized_keys.items():
        candidates = grouped.get(normalized, [])
        if not candidates:
            if normalized:
                unmatched_table_keys.add(normalized)
            continue
        matched_rows += 1
        matched_extracted_keys.add(normalized)
        for source, target in merge_fields:
            if duplicate_policy == "join" and len(candidates) > 1:
                field_values = [item.fields.get(source, "") for item in candidates]
                value = "\n".join(dict.fromkeys(item for item in field_values if item))
            else:
                value = choose_duplicate_section(candidates, duplicate_policy).fields.get(source, "")
            if value:
                dataframe.at[row_index, target] = value
                updated_cells += 1

    missing_fields = sorted(
        source for source, _ in merge_fields if not any(source in section.fields for section in sections)
    )
    merge_report = {
        "table_rows": len(dataframe),
        "matched_rows": matched_rows,
        "updated_cells": updated_cells,
        "unmatched_table_keys": sorted(unmatched_table_keys, key=natural_key),
        "unmatched_extracted_keys": sorted(set(grouped) - matched_extracted_keys, key=natural_key),
        "missing_extracted_fields": missing_fields,
    }
    return dataframe, merge_report


def write_in_place_with_backup(path: Path, dataframe: pd.DataFrame) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(f"{path.stem}.backup-{timestamp}{path.suffix}")
    shutil.copy2(path, backup)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.stem}.", suffix=path.suffix, dir=path.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        write_dataframe(temporary, dataframe)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return backup


def duplicate_name_report(sections: list[Section]) -> list[dict[str, Any]]:
    counts = Counter(section.normalized_name for section in sections if section.normalized_name)
    return [
        {"normalized_name": name, "count": count}
        for name, count in sorted(counts.items(), key=lambda item: natural_key(item[0]))
        if count > 1
    ]


def derive_report_path(args: argparse.Namespace) -> Path | None:
    if args.report_output:
        return Path(args.report_output).expanduser()
    candidates = [args.markdown_output, args.records_output, args.merge_output]
    if args.in_place and args.merge_input:
        candidates.append(args.merge_input)
    for candidate in candidates:
        if candidate:
            path = Path(candidate).expanduser()
            return path.with_name(f"{path.stem}_report.json")
    return None


def validate_args(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    if not args.dry_run and not any(
        [args.markdown_output, args.records_output, args.report_output, args.merge_output, args.in_place]
    ):
        parser.error("Specify at least one output, or use --dry-run.")
    if args.merge_input:
        if not args.merge_key_column:
            parser.error("--merge-key-column is required with --merge-input.")
        if bool(args.merge_output) == bool(args.in_place):
            parser.error("Choose exactly one of --merge-output and --in-place with --merge-input.")
    elif args.merge_output or args.in_place or args.merge_field or args.merge_key_column:
        parser.error("Merge options require --merge-input.")
    if not 1 <= args.markdown_heading_level <= 6:
        parser.error("--markdown-heading-level must be from 1 to 6.")


def validate_output_paths(args: argparse.Namespace, files: list[Path]) -> None:
    named_outputs = {
        name: Path(value).expanduser().resolve()
        for name, value in {
            "markdown output": args.markdown_output,
            "records output": args.records_output,
            "report output": args.report_output,
            "merge output": args.merge_output,
        }.items()
        if value
    }
    paths_to_names: dict[Path, list[str]] = defaultdict(list)
    for name, path in named_outputs.items():
        paths_to_names[path].append(name)
    collisions = [names for names in paths_to_names.values() if len(names) > 1]
    if collisions:
        raise ValueError(f"Output paths must be distinct: {', '.join(collisions[0])}")

    input_files = {path.resolve() for path in files}
    for name, path in named_outputs.items():
        if path in input_files:
            raise ValueError(f"The {name} cannot overwrite an input PDF: {path}")

    if args.records_output and named_outputs["records output"].suffix.lower() not in TABLE_OUTPUT_SUFFIXES:
        raise ValueError("--records-output must be .csv, .tsv, or .xlsx.")
    if args.report_output and named_outputs["report output"].suffix.lower() != ".json":
        raise ValueError("--report-output must have a .json extension.")
    if args.merge_output and named_outputs["merge output"].suffix.lower() not in TABLE_OUTPUT_SUFFIXES:
        raise ValueError("--merge-output must be .csv, .tsv, or .xlsx.")

    if args.merge_input:
        merge_input = Path(args.merge_input).expanduser().resolve()
        for name, path in named_outputs.items():
            if name != "merge output" and path == merge_input:
                raise ValueError(f"The {name} cannot overwrite --merge-input.")
        if args.in_place and merge_input.suffix.lower() not in TABLE_OUTPUT_SUFFIXES:
            raise ValueError("--in-place supports only .csv, .tsv, and .xlsx merge inputs.")


def apply_cli_layout_overrides(profile: dict[str, Any], args: argparse.Namespace) -> None:
    mapping = {
        "columns": args.columns,
        "column_split_ratio": args.column_split,
        "top_margin_ratio": args.top_margin,
        "bottom_margin_ratio": args.bottom_margin,
        "y_tolerance": args.y_tolerance,
    }
    for key, value in mapping.items():
        if value is not None:
            profile["layout"][key] = value
    if args.include_preface:
        profile["entry"]["include_preface"] = True
    validate_profile(profile)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Batch-extract text or structured entries from text-based PDF files."
    )
    parser.add_argument("--input", required=True, help="A PDF file or a directory containing PDFs")
    parser.add_argument("--pattern", default="*.pdf", help="Directory input glob, default: *.pdf")
    parser.add_argument("--recursive", action="store_true", help="Search input directories recursively")
    parser.add_argument("--start-file", help="Inclusive first file name or relative path after natural sorting")
    parser.add_argument("--end-file", help="Inclusive last file name or relative path after natural sorting")
    parser.add_argument("--pages", help="Pages within every PDF, for example 1-3,5,8-")
    parser.add_argument("--config", help="JSON configuration merged over the default configuration")
    parser.add_argument("--columns", choices=["auto", "1", "2"], help="Override page column mode")
    parser.add_argument("--column-split", type=float, help="Two-column split as a page-width ratio")
    parser.add_argument("--top-margin", type=float, help="Ignored top margin as a page-height ratio")
    parser.add_argument("--bottom-margin", type=float, help="Ignored bottom margin as a page-height ratio")
    parser.add_argument("--y-tolerance", type=float, help="Word-to-line vertical tolerance in PDF points")
    parser.add_argument("--include-preface", action="store_true", help="Keep text before the first detected entry")
    parser.add_argument("--markdown-output", help="Markdown output path")
    parser.add_argument("--records-output", help="Structured .csv, .tsv, or .xlsx output path")
    parser.add_argument("--report-output", help="JSON processing report path; otherwise derived from an output")
    parser.add_argument("--markdown-heading-level", type=int, default=2, help="Markdown heading level, default: 2")
    parser.add_argument("--merge-input", help="Existing CSV/TSV/Excel table to enrich")
    parser.add_argument("--merge-output", help="New CSV/TSV/XLSX path for the enriched table")
    parser.add_argument("--merge-key-column", help="Existing table column matched against extracted entry names")
    parser.add_argument(
        "--merge-field",
        action="append",
        help="Extracted field, optionally FIELD:TARGET_COLUMN; may be repeated",
    )
    parser.add_argument("--merge-sheet", default="0", help="Excel sheet name or zero-based index, default: 0")
    parser.add_argument(
        "--duplicate-policy",
        choices=["error", "first", "last", "join"],
        default="error",
        help="How duplicate normalized entry names are handled during merge",
    )
    parser.add_argument(
        "--in-place", action="store_true", help="Replace --merge-input after creating a timestamped backup"
    )
    parser.add_argument("--strict", action="store_true", help="Stop at the first unreadable PDF or page")
    parser.add_argument("--dry-run", action="store_true", help="Parse and report a summary without writing files")
    parser.add_argument("--verbose", action="store_true", help="Print each PDF as it is read")
    return parser


def run(args: argparse.Namespace) -> dict[str, Any]:
    profile = load_profile(args.config)
    apply_cli_layout_overrides(profile, args)
    files = discover_pdf_files(
        Path(args.input), args.pattern, args.recursive, args.start_file, args.end_file
    )
    validate_output_paths(args, files)
    page_ranges = parse_page_spec(args.pages)
    lines, extraction_stats = extract_document_lines(files, page_ranges, profile, args.strict, args.verbose)
    sections, preface_line_count = segment_lines(lines, profile)
    populate_fields(sections, profile)

    report: dict[str, Any] = {
        "profile": profile.get("profile_name", "generic"),
        "input": str(Path(args.input).expanduser().resolve()),
        "selected_files": [str(path) for path in files],
        **extraction_stats,
        "line_count": len(lines),
        "entry_count": len(sections),
        "preface_line_count": preface_line_count,
        "duplicate_names": duplicate_name_report(sections),
        "field_counts": dict(
            sorted(Counter(name for section in sections for name in section.fields).items())
        ),
        "merge": None,
        "outputs": {},
    }

    if not args.dry_run:
        if args.markdown_output:
            markdown_path = Path(args.markdown_output).expanduser().resolve()
            write_markdown(markdown_path, sections, profile, args.markdown_heading_level)
            report["outputs"]["markdown"] = str(markdown_path)
        if args.records_output:
            records_path = Path(args.records_output).expanduser().resolve()
            write_dataframe(records_path, records_dataframe(sections, profile))
            report["outputs"]["records"] = str(records_path)
        if args.merge_input:
            merge_input = Path(args.merge_input).expanduser().resolve()
            if not merge_input.is_file():
                raise FileNotFoundError(f"Merge input does not exist: {merge_input}")
            dataframe = read_dataframe(merge_input, parse_sheet(args.merge_sheet))
            merge_fields = parse_merge_fields(args.merge_field, profile)
            dataframe, merge_report = merge_records_into_table(
                dataframe,
                sections,
                args.merge_key_column,
                merge_fields,
                args.duplicate_policy,
                profile["entry"]["normalization"],
            )
            if args.in_place:
                backup = write_in_place_with_backup(merge_input, dataframe)
                report["outputs"]["merged_table"] = str(merge_input)
                report["outputs"]["backup"] = str(backup)
            else:
                merge_output = Path(args.merge_output).expanduser().resolve()
                if merge_output == merge_input:
                    raise ValueError("--merge-output cannot equal --merge-input; use --in-place explicitly.")
                write_dataframe(merge_output, dataframe)
                report["outputs"]["merged_table"] = str(merge_output)
            report["merge"] = merge_report

        report_path = derive_report_path(args)
        if report_path:
            report_path = report_path.resolve()
            ensure_output_parent(report_path)
            report["outputs"]["report"] = str(report_path)
            with report_path.open("w", encoding="utf-8") as file:
                json.dump(report, file, ensure_ascii=False, indent=2)
                file.write("\n")

    print(
        f"Selected {len(files)} PDF(s), processed {extraction_stats['pages_selected']} page(s), "
        f"extracted {len(sections)} section(s)."
    )
    if extraction_stats["pages_without_text"]:
        print(f"Pages without extractable text: {len(extraction_stats['pages_without_text'])}")
    if extraction_stats["errors"]:
        print(f"PDF/page errors: {len(extraction_stats['errors'])}")
    if report["duplicate_names"]:
        print(f"Duplicate normalized names: {len(report['duplicate_names'])}")
    if args.dry_run:
        print("Dry run: no files were written.")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    validate_args(args, parser)
    try:
        run(args)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
