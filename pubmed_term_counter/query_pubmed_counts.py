#!/usr/bin/env python3
"""Count PubMed records for terms supplied directly or from a table."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from urllib.error import HTTPError, URLError

import pandas as pd


ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
SUPPORTED_SUFFIXES = {".csv", ".tsv", ".xlsx", ".xls"}
OUTPUT_SUFFIXES = {".csv", ".tsv", ".xlsx"}
OUTPUT_COLUMNS = [
    "term", "pubmed_query", "pubmed_count", "pubmed_status", "pubmed_message", "pubmed_url"
]


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
        frame = pd.read_csv(
            path,
            sep="\t" if suffix == ".tsv" else ",",
            dtype=str,
            keep_default_na=False,
        )
    frame = frame.fillna("")
    frame.columns = [str(column) for column in frame.columns]
    return frame


def write_table(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    suffix = path.suffix.lower()
    if suffix == ".csv":
        frame.to_csv(path, index=False, encoding="utf-8-sig")
    elif suffix == ".tsv":
        frame.to_csv(path, index=False, sep="\t", encoding="utf-8-sig")
    elif suffix == ".xlsx":
        frame.to_excel(path, index=False)
    else:
        raise ValueError("Output path must end with .csv, .tsv, or .xlsx")


def resolve_column(columns: list[str], requested: str | None) -> str:
    if requested:
        if requested in columns:
            return requested
        folded = {column.casefold(): column for column in columns}
        match = folded.get(requested.casefold())
        if match:
            return match
        raise ValueError(
            f"Column {requested!r} was not found. Available columns: {', '.join(columns)}"
        )
    if len(columns) == 1:
        return columns[0]
    raise ValueError("--column is required when the input table has more than one column")


def unique_terms(values: list[object]) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for value in values:
        term = str(value).strip()
        if not term or term.casefold() == "nan" or term in seen:
            continue
        seen.add(term)
        terms.append(term)
    return terms


def build_query(term: str, template: str, context: str) -> str:
    try:
        query = template.format(term=term, context=context).strip()
    except (KeyError, ValueError) as exc:
        raise ValueError(f"Invalid --query-template: {exc}") from exc
    if context and "{context}" not in template:
        query = f"({query}) AND ({context})"
    if not query:
        raise ValueError("The generated PubMed query is empty")
    return query


def fetch_count(
    query: str,
    *,
    email: str,
    api_key: str | None,
    timeout: float,
    retries: int,
) -> int:
    parameters = {
        "db": "pubmed",
        "term": query,
        "retmode": "json",
        "retmax": "0",
        "tool": "research-tools-pubmed-counter",
        "email": email,
    }
    if api_key:
        parameters["api_key"] = api_key
    url = f"{ESEARCH_URL}?{urllib.parse.urlencode(parameters)}"
    request = urllib.request.Request(
        url,
        headers={"User-Agent": f"research-tools-pubmed-counter/1.0 ({email})"},
    )
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.load(response)
            return int(payload["esearchresult"]["count"])
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, KeyError, ValueError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(min(2**attempt, 8))
    raise RuntimeError(str(last_error) if last_error else "Unknown PubMed request error")


def pubmed_url(query: str) -> str:
    return "https://pubmed.ncbi.nlm.nih.gov/?" + urllib.parse.urlencode({"term": query})


def load_cached_results(path: Path) -> dict[str, dict[str, object]]:
    if not path.is_file():
        return {}
    cached = read_table(path)
    if not set(OUTPUT_COLUMNS).issubset(cached.columns):
        return {}
    return {
        str(row["pubmed_query"]): {column: row[column] for column in OUTPUT_COLUMNS}
        for _, row in cached.iterrows()
        if str(row["pubmed_status"]) == "ok"
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Count PubMed records for genes or other terms using NCBI E-utilities."
    )
    parser.add_argument("--input", type=Path, help="CSV, TSV, XLSX, or XLS input table")
    parser.add_argument("--column", help="Input column containing terms")
    parser.add_argument("--sheet", default="0", type=parse_sheet, help="Excel sheet name or index")
    parser.add_argument("--term", action="append", default=[], help="Direct term; may be repeated")
    parser.add_argument(
        "--query-template",
        default="{term}[Gene]",
        help="PubMed query template with {term} and optional {context}",
    )
    parser.add_argument("--context", default="", help="Additional PubMed query expression")
    parser.add_argument("--email", default=os.getenv("NCBI_EMAIL"), help="NCBI contact email")
    parser.add_argument("--api-key", default=os.getenv("NCBI_API_KEY"), help="NCBI API key")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--delay", type=float, help="Delay between requests in seconds")
    parser.add_argument("--checkpoint-every", type=int, default=10)
    parser.add_argument("--force", action="store_true", help="Ignore successful cached output rows")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.input and not args.term:
        parser.error("provide --input and/or at least one --term")
    if not args.email:
        parser.error("provide --email or set NCBI_EMAIL")
    if args.output.suffix.lower() not in OUTPUT_SUFFIXES:
        parser.error("--output must end with .csv, .tsv, or .xlsx")
    if args.retries < 0 or args.timeout <= 0 or args.checkpoint_every < 1:
        parser.error("--retries must be >= 0, --timeout > 0, and --checkpoint-every >= 1")

    try:
        values: list[object] = list(args.term)
        if args.input:
            if not args.input.is_file():
                raise FileNotFoundError(f"Input table does not exist: {args.input}")
            frame = read_table(args.input, args.sheet)
            column = resolve_column(list(frame.columns), args.column)
            values = frame[column].tolist() + values
        terms = unique_terms(values)
        if not terms:
            raise ValueError("No non-empty terms were found")
        if args.input and args.input.resolve() == args.output.resolve():
            raise ValueError("Output path must differ from input path")
    except (FileNotFoundError, OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    cached = {} if args.force else load_cached_results(args.output)
    results: list[dict[str, object]] = []
    delay = args.delay if args.delay is not None else (0.11 if args.api_key else 0.34)
    completed_since_write = 0

    try:
        for index, term in enumerate(terms, 1):
            query = build_query(term, args.query_template, args.context)
            if query in cached:
                result = cached[query]
                print(f"[{index}/{len(terms)}] cached: {term} = {result['pubmed_count']}")
            else:
                try:
                    count = fetch_count(
                        query,
                        email=args.email,
                        api_key=args.api_key,
                        timeout=args.timeout,
                        retries=args.retries,
                    )
                    result = {
                        "term": term,
                        "pubmed_query": query,
                        "pubmed_count": count,
                        "pubmed_status": "ok",
                        "pubmed_message": "",
                        "pubmed_url": pubmed_url(query),
                    }
                    print(f"[{index}/{len(terms)}] {term}: {count}")
                except RuntimeError as exc:
                    result = {
                        "term": term,
                        "pubmed_query": query,
                        "pubmed_count": "",
                        "pubmed_status": "error",
                        "pubmed_message": str(exc),
                        "pubmed_url": pubmed_url(query),
                    }
                    print(f"[{index}/{len(terms)}] error: {term}: {exc}", file=sys.stderr)
                completed_since_write += 1
                if delay > 0:
                    time.sleep(delay)
            results.append(result)
            if completed_since_write >= args.checkpoint_every:
                write_table(pd.DataFrame(results, columns=OUTPUT_COLUMNS), args.output)
                completed_since_write = 0
    except KeyboardInterrupt:
        write_table(pd.DataFrame(results, columns=OUTPUT_COLUMNS), args.output)
        print(f"Interrupted; partial results saved to {args.output}", file=sys.stderr)
        return 130
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    write_table(pd.DataFrame(results, columns=OUTPUT_COLUMNS), args.output)
    failures = sum(result["pubmed_status"] != "ok" for result in results)
    print(f"Saved {len(results)} result(s), including {failures} error(s), to {args.output.resolve()}")
    return 0 if failures == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
