#!/usr/bin/env python3
"""Download processed expression data from GEO after candidate filtering."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from urllib.parse import urljoin

import pandas as pd
import requests

GEO_ROOT = "https://ftp.ncbi.nlm.nih.gov/geo/series"
TIMEOUT = 60
MATRIX_EXTENSIONS = (".txt", ".txt.gz", ".tsv", ".tsv.gz", ".csv", ".csv.gz")


def series_bucket(gse: str) -> str:
    match = re.fullmatch(r"GSE(\d+)", gse.upper())
    if not match:
        raise ValueError(f"Invalid GEO Series accession: {gse}")
    number = int(match.group(1))
    return f"GSE{number // 1000}nnn"


def base_url(gse: str, kind: str) -> str:
    bucket = series_bucket(gse)
    gse = gse.upper()
    return f"{GEO_ROOT}/{bucket}/{gse}/{kind}/"


def url_exists(url: str) -> bool:
    try:
        response = requests.head(url, allow_redirects=True, timeout=TIMEOUT)
        if response.status_code < 400:
            return True
    except requests.RequestException:
        pass
    try:
        response = requests.get(url, stream=True, allow_redirects=True, timeout=TIMEOUT)
        ok = response.status_code < 400
        response.close()
        return ok
    except requests.RequestException:
        return False


def download(url: str, destination: Path) -> tuple[str, str]:
    try:
        with requests.get(url, stream=True, timeout=TIMEOUT) as response:
            response.raise_for_status()
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        handle.write(chunk)
        return "ok", ""
    except requests.RequestException as exc:
        if destination.exists():
            destination.unlink()
        return "error", str(exc)


def series_matrix_candidates(gse: str) -> list[str]:
    folder = base_url(gse, "matrix")
    return [
        urljoin(folder, f"{gse}_series_matrix.txt.gz"),
        urljoin(folder, f"{gse}_series_matrix.txt"),
    ]


def supplementary_candidates(gse: str) -> list[str]:
    # The GEO accession page lists exact supplementary filenames. This fallback
    # uses the common GEO supplementary directory and candidate filenames when
    # a filename is supplied by the user/listing.
    return []


def looks_like_expression(name: str) -> bool:
    text = name.lower()
    return any(
        term in text
        for term in ("matrix", "expression", "counts", "fpkm", "tpm", "normalized")
    ) and text.endswith(MATRIX_EXTENSIONS)


def get_supplementary_listing(gse: str) -> list[str]:
    # GEO's supplementary directory exposes an index that can be parsed as HTML.
    url = base_url(gse, "suppl")
    try:
        response = requests.get(url, timeout=TIMEOUT)
        response.raise_for_status()
    except requests.RequestException:
        return []

    names = re.findall(r'href=["\']([^"\']+)["\']', response.text, flags=re.I)
    result = []
    for name in names:
        filename = name.rsplit("/", 1)[-1]
        if filename and filename not in (".", "..") and looks_like_expression(filename):
            result.append(urljoin(url, filename))
    return sorted(set(result))


def choose_files(gse: str) -> list[tuple[str, str]]:
    for url in series_matrix_candidates(gse):
        if url_exists(url):
            return [("series_matrix", url)]

    supplementary = get_supplementary_listing(gse)
    if supplementary:
        return [("supplementary_expression", url) for url in supplementary]

    return []


def download_gse(gse: str, output: Path) -> pd.DataFrame:
    gse = gse.upper()
    destination_dir = output / gse
    destination_dir.mkdir(parents=True, exist_ok=True)

    chosen = choose_files(gse)
    rows = []

    if not chosen:
        rows.append({
            "gse": gse,
            "file_type": "expression",
            "file_name": "",
            "url": "",
            "status": "not_found",
            "message": "No Series Matrix or expression-like supplementary file was found.",
        })
    else:
        for file_type, url in chosen:
            file_name = url.rstrip("/").rsplit("/", 1)[-1]
            status, message = download(url, destination_dir / file_name)
            rows.append({
                "gse": gse,
                "file_type": file_type,
                "file_name": file_name,
                "url": url,
                "status": status,
                "message": message,
            })

    manifest = pd.DataFrame(rows)
    manifest.to_csv(destination_dir / "manifest.tsv", sep="\t", index=False)
    return manifest


def read_gse_list(path: Path) -> list[str]:
    df = pd.read_csv(path, sep="\t")
    if "gse" not in df.columns:
        raise ValueError("Input TSV must contain a 'gse' column.")
    return sorted({
        str(x).strip().upper()
        for x in df["gse"].dropna()
        if re.fullmatch(r"GSE\d+", str(x).strip().upper())
    })


def main():
    parser = argparse.ArgumentParser(description="Download processed GEO expression data")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("download", help="download one GSE")
    p.add_argument("--gse", required=True)
    p.add_argument("--output", default="geo_data")

    p = sub.add_parser("download-from-gse-list", help="download GSEs from a TSV")
    p.add_argument("--input", required=True)
    p.add_argument("--output", default="geo_data")

    p = sub.add_parser("download-from-samples", help="download unique GSEs from sample.tsv")
    p.add_argument("--input", required=True)
    p.add_argument("--output", default="geo_data")

    args = parser.parse_args()

    if args.command == "download":
        manifest = download_gse(args.gse, Path(args.output))
        print(manifest.to_string(index=False))
        return

    if args.command == "download-from-gse-list":
        gses = read_gse_list(Path(args.input))
    else:
        df = pd.read_csv(args.input, sep="\t")
        if "gse" not in df.columns:
            raise ValueError("Input TSV must contain a 'gse' column.")
        gses = sorted({
            str(x).strip().upper()
            for x in df["gse"].dropna()
            if re.fullmatch(r"GSE\d+", str(x).strip().upper())
        })

    all_manifests = []
    for gse in gses:
        all_manifests.append(download_gse(gse, Path(args.output)))

    if all_manifests:
        combined = pd.concat(all_manifests, ignore_index=True)
        combined.to_csv(Path(args.output) / "manifest.tsv", sep="\t", index=False)
        print(combined.to_string(index=False))


if __name__ == "__main__":
    main()
