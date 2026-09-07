#!/usr/bin/env python3
"""Join relation and entity tables, then export one table per group."""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from pathlib import Path

import pandas as pd


SUPPORTED_SUFFIXES = {".csv", ".tsv", ".xlsx", ".xls"}
OUTPUT_SUFFIXES = {"csv": ".csv", "tsv": ".tsv", "xlsx": ".xlsx"}


def parse_sheet(value: str) -> str | int:
    stripped = value.strip()
    return int(stripped) if stripped.isdigit() else stripped


def read_table(path: Path, sheet: str | int = 0) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        supported = ", ".join(sorted(SUPPORTED_SUFFIXES))
        raise ValueError(f"Unsupported table type {suffix!r}; expected one of: {supported}")
    if suffix in {".xlsx", ".xls"}:
        frame = pd.read_excel(path, sheet_name=sheet, dtype=str)
    else:
        separator = "\t" if suffix == ".tsv" else ","
        frame = pd.read_csv(path, sep=separator, dtype=str, keep_default_na=False)
    frame = frame.fillna("")
    frame.columns = [str(column) for column in frame.columns]
    return frame


def write_table(frame: pd.DataFrame, path: Path, output_format: str) -> None:
    if output_format == "csv":
        frame.to_csv(path, index=False, encoding="utf-8-sig")
    elif output_format == "tsv":
        frame.to_csv(path, index=False, sep="\t", encoding="utf-8-sig")
    else:
        frame.to_excel(path, index=False)


def require_columns(frame: pd.DataFrame, columns: list[str], label: str) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise ValueError(
            f"{label} is missing column(s): {', '.join(missing)}. "
            f"Available columns: {', '.join(frame.columns)}"
        )


def normalized_key(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip()


def prepare_lookup(
    lookup: pd.DataFrame,
    *,
    key: str,
    occupied_columns: set[str],
    prefix: str,
    internal_key: str,
) -> tuple[pd.DataFrame, dict[str, str]]:
    prepared = lookup.copy()
    prepared[internal_key] = normalized_key(prepared[key])
    prepared = prepared[prepared[internal_key] != ""].copy()
    duplicates = prepared[prepared[internal_key].duplicated(keep=False)][internal_key].unique()
    if len(duplicates):
        examples = ", ".join(map(str, duplicates[:5]))
        raise ValueError(
            f"Lookup key {key!r} must be unique after trimming; duplicate example(s): {examples}"
        )

    rename_map: dict[str, str] = {}
    used = set(occupied_columns) | {internal_key}
    for column in prepared.columns:
        if column in {key, internal_key}:
            continue
        candidate = column if column not in used else f"{prefix}{column}"
        suffix = 2
        while candidate in used:
            candidate = f"{prefix}{column}_{suffix}"
            suffix += 1
        rename_map[column] = candidate
        used.add(candidate)
    prepared = prepared.drop(columns=[key]).rename(columns=rename_map)
    return prepared, rename_map


def safe_filename(value: str, fallback: str = "unknown", max_length: int = 120) -> str:
    text = unicodedata.normalize("NFKC", str(value)).strip()
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    return (text or fallback)[:max_length].rstrip(" .") or fallback


def first_nonempty(series: pd.Series) -> str:
    for value in series:
        stripped = str(value).strip()
        if stripped:
            return stripped
    return ""


def join_relations(
    relations: pd.DataFrame,
    groups: pd.DataFrame,
    items: pd.DataFrame,
    *,
    relation_group_key: str,
    group_key: str,
    group_name_column: str,
    relation_item_key: str,
    item_key: str,
) -> tuple[pd.DataFrame, str]:
    require_columns(relations, [relation_group_key, relation_item_key], "Relation table")
    require_columns(groups, [group_key, group_name_column], "Group table")
    require_columns(items, [item_key], "Item table")

    merged = relations.copy()
    merged["__relation_row"] = range(2, len(merged) + 2)
    merged["__relation_group_key"] = normalized_key(merged[relation_group_key])
    merged["__relation_item_key"] = normalized_key(merged[relation_item_key])

    group_lookup, group_renames = prepare_lookup(
        groups,
        key=group_key,
        occupied_columns=set(merged.columns),
        prefix="group_",
        internal_key="__group_lookup_key",
    )
    output_group_name = group_renames.get(group_name_column, group_name_column)
    merged = merged.merge(
        group_lookup,
        left_on="__relation_group_key",
        right_on="__group_lookup_key",
        how="left",
        validate="many_to_one",
        indicator="__group_merge",
    )

    item_lookup, _ = prepare_lookup(
        items,
        key=item_key,
        occupied_columns=set(merged.columns),
        prefix="item_",
        internal_key="__item_lookup_key",
    )
    merged = merged.merge(
        item_lookup,
        left_on="__relation_item_key",
        right_on="__item_lookup_key",
        how="left",
        validate="many_to_one",
        indicator="__item_merge",
    )
    merged["group_match_status"] = merged["__group_merge"].map(
        {"both": "matched", "left_only": "unmatched"}
    ).astype(str)
    merged["item_match_status"] = merged["__item_merge"].map(
        {"both": "matched", "left_only": "unmatched"}
    ).astype(str)
    return merged, output_group_name


def public_frame(frame: pd.DataFrame) -> pd.DataFrame:
    return frame[[column for column in frame.columns if not column.startswith("__")]].copy()


def export_results(
    merged: pd.DataFrame,
    *,
    output_dir: Path,
    output_format: str,
    group_name_column: str,
) -> dict[str, int]:
    output_dir.mkdir(parents=True, exist_ok=True)
    groups_dir = output_dir / "groups"
    groups_dir.mkdir(parents=True, exist_ok=True)
    suffix = OUTPUT_SUFFIXES[output_format]
    write_table(public_frame(merged), output_dir / f"merged_relations{suffix}", output_format)

    unmatched_groups = merged[merged["__group_merge"] == "left_only"]
    unmatched_items = merged[merged["__item_merge"] == "left_only"]
    public_frame(unmatched_groups).to_csv(
        output_dir / "unmatched_group_relations.csv", index=False, encoding="utf-8-sig"
    )
    public_frame(unmatched_items).to_csv(
        output_dir / "unmatched_item_relations.csv", index=False, encoding="utf-8-sig"
    )

    summaries: list[dict[str, object]] = []
    used_names: set[str] = set()
    groups = merged.groupby("__relation_group_key", sort=True, dropna=False).groups
    for group_key, indexes in groups.items():
        group = merged.loc[indexes]
        display_name = first_nonempty(group[group_name_column]) or "unknown"
        base_name = safe_filename(f"{display_name}_{group_key}" if group_key else display_name)
        file_name = f"{base_name}{suffix}"
        counter = 2
        while file_name.casefold() in used_names:
            file_name = f"{base_name}_{counter}{suffix}"
            counter += 1
        used_names.add(file_name.casefold())
        write_table(public_frame(group), groups_dir / file_name, output_format)
        summaries.append(
            {
                "group_key": group_key,
                "group_name": display_name,
                "relation_count": len(group),
                "unmatched_item_count": int((group["__item_merge"] == "left_only").sum()),
                "output_file": f"groups/{file_name}",
            }
        )

    pd.DataFrame(summaries).to_csv(
        output_dir / "group_summary.csv", index=False, encoding="utf-8-sig"
    )
    counts = {
        "relations": len(merged),
        "groups": len(summaries),
        "unmatched_groups": len(unmatched_groups),
        "unmatched_items": len(unmatched_items),
    }
    pd.DataFrame([counts]).to_csv(
        output_dir / "audit_summary.csv", index=False, encoding="utf-8-sig"
    )
    return counts


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Join a relation table to group/item lookup tables and export one file per group."
    )
    parser.add_argument("--relations", required=True, type=Path, help="Relation table path")
    parser.add_argument("--groups", required=True, type=Path, help="Group/entity table path")
    parser.add_argument("--items", required=True, type=Path, help="Item/entity table path")
    parser.add_argument("--relation-group-key", required=True)
    parser.add_argument("--group-key", required=True)
    parser.add_argument("--group-name-column", required=True)
    parser.add_argument("--relation-item-key", required=True)
    parser.add_argument("--item-key", required=True)
    parser.add_argument("--relations-sheet", default="0", type=parse_sheet)
    parser.add_argument("--groups-sheet", default="0", type=parse_sheet)
    parser.add_argument("--items-sheet", default="0", type=parse_sheet)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--format", choices=sorted(OUTPUT_SUFFIXES), default="xlsx")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        for path in (args.relations, args.groups, args.items):
            if not path.is_file():
                raise FileNotFoundError(f"Input table does not exist: {path}")
        relations = read_table(args.relations, args.relations_sheet)
        groups = read_table(args.groups, args.groups_sheet)
        items = read_table(args.items, args.items_sheet)
        merged, group_name_column = join_relations(
            relations,
            groups,
            items,
            relation_group_key=args.relation_group_key,
            group_key=args.group_key,
            group_name_column=args.group_name_column,
            relation_item_key=args.relation_item_key,
            item_key=args.item_key,
        )
        counts = export_results(
            merged,
            output_dir=args.output_dir,
            output_format=args.format,
            group_name_column=group_name_column,
        )
    except (FileNotFoundError, OSError, ValueError, KeyError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(
        "Completed: "
        f"{counts['relations']} relations, {counts['groups']} groups, "
        f"{counts['unmatched_groups']} unmatched group rows, "
        f"{counts['unmatched_items']} unmatched item rows."
    )
    print(f"Output: {args.output_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
