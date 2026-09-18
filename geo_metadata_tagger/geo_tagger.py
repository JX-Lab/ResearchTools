#!/usr/bin/env python3
"""Search, annotate, and filter GEO studies with auditable metadata tags."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import GEOparse
import pandas as pd
import requests
import yaml

ROOT = Path(__file__).resolve().parent
RULE_DIR = ROOT / "rules"
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


def load_yaml(name: str) -> dict[str, list[str]]:
    with open(RULE_DIR / name, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def norm(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def flatten(value: Any) -> str:
    if isinstance(value, list):
        return "; ".join(str(x) for x in value)
    if isinstance(value, dict):
        return "; ".join(f"{k}: {v}" for k, v in value.items())
    return str(value or "")


def collect_field(meta: dict[str, Any], prefix: str) -> str:
    parts = []
    for key, value in meta.items():
        if key == prefix or key.startswith(prefix + "_"):
            parts.append(f"{key}: {flatten(value)}")
    return " | ".join(parts)


def find_hits(text: str, rules: dict[str, list[str]]) -> list[tuple[str, str]]:
    text_n = norm(text)
    hits = []
    for label, terms in rules.items():
        for term in terms:
            if norm(term) and norm(term) in text_n:
                hits.append((label, term))
    return hits


def infer(text: str, rules: dict[str, list[str]], source: str, strength: float) -> dict[str, Any]:
    hits = find_hits(text, rules)
    if not hits:
        return {"value": "unknown", "confidence": 0.0, "evidence": [], "source": "auto"}
    label, term = hits[0]
    return {
        "value": label,
        "confidence": strength,
        "evidence": [{"source": source, "matched_term": term, "text": text}],
        "source": "auto",
    }


def infer_technology(meta: dict[str, Any], rules: dict[str, list[str]]) -> dict[str, Any]:
    library = collect_field(meta, "library_strategy")
    if library:
        result = infer(library, rules, "library_strategy", 1.0)
        if result["value"] != "unknown":
            return result
    text = " | ".join([
        collect_field(meta, "title"),
        collect_field(meta, "source_name_ch1"),
        collect_field(meta, "characteristics_ch1"),
        collect_field(meta, "platform_id"),
    ])
    return infer(text, rules, "sample_metadata", 0.85)


def study_type_from_technology(technology: str) -> tuple[str, float]:
    return {
        "scRNA-seq": ("scRNA", 1.0),
        "snRNA-seq": ("snRNA", 1.0),
        "Spatial": ("spatial", 1.0),
        "RNA-seq": ("bulk", 0.80),
        "Microarray": ("bulk", 0.70),
    }.get(technology, ("unknown", 0.0))


def sample_metadata(gsm, disease_rules, tissue_rules, tech_rules, group_rules):
    meta = getattr(gsm, "metadata", {}) or {}
    title = collect_field(meta, "title")
    source = collect_field(meta, "source_name_ch1")
    characteristics = collect_field(meta, "characteristics_ch1")
    text = " | ".join(x for x in [title, source, characteristics] if x)

    disease = infer(text, disease_rules, "sample_metadata", 0.90)
    tissue = infer(text, tissue_rules, "sample_metadata", 0.90)
    technology = infer_technology(meta, tech_rules)
    group = infer(text, group_rules, "sample_metadata", 0.85)
    study_type, study_conf = study_type_from_technology(technology["value"])

    return {
        "gsm": gsm.name,
        "title": title,
        "organism": collect_field(meta, "organism_ch1") or "unknown",
        "disease": disease["value"],
        "disease_confidence": disease["confidence"],
        "disease_evidence": json.dumps(disease["evidence"], ensure_ascii=False),
        "disease_source": disease["source"],
        "tissue": tissue["value"],
        "tissue_confidence": tissue["confidence"],
        "tissue_evidence": json.dumps(tissue["evidence"], ensure_ascii=False),
        "tissue_source": tissue["source"],
        "technology": technology["value"],
        "technology_confidence": technology["confidence"],
        "technology_evidence": json.dumps(technology["evidence"], ensure_ascii=False),
        "technology_source": technology["source"],
        "study_type": study_type,
        "study_type_confidence": study_conf,
        "group": group["value"],
        "group_confidence": group["confidence"],
        "group_evidence": json.dumps(group["evidence"], ensure_ascii=False),
        "group_source": group["source"],
        "source_name": source,
        "library_strategy": collect_field(meta, "library_strategy"),
        "molecule": collect_field(meta, "molecule_ch1"),
    }


def search_geo(query: str, max_results: int = 50) -> pd.DataFrame:
    params = {"db": "gds", "term": query, "retmax": max_results, "retmode": "json",
              "tool": "ResearchTools_geo_metadata_tagger"}
    response = requests.get(f"{EUTILS}/esearch.fcgi", params=params, timeout=30)
    response.raise_for_status()
    ids = response.json()["esearchresult"]["idlist"]
    if not ids:
        return pd.DataFrame(columns=["gse", "uid", "title", "summary"])

    response = requests.get(
        f"{EUTILS}/esummary.fcgi",
        params={"db": "gds", "id": ",".join(ids), "retmode": "json",
                "tool": "ResearchTools_geo_metadata_tagger"},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()["result"]
    rows = []
    for uid in ids:
        item = data.get(str(uid), {})
        accession = item.get("accession", "")
        if accession.startswith("GSE"):
            rows.append({"gse": accession, "uid": uid, "title": item.get("title", ""),
                         "summary": item.get("summary", "")})
    return pd.DataFrame(rows)


def annotate_gse(gse_id: str, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    gse = GEOparse.get_GEO(geo=gse_id, destdir=str(out_dir / "geo_cache"), silent=True)

    disease_rules = load_yaml("diseases.yaml")
    tissue_rules = load_yaml("tissues.yaml")
    tech_rules = load_yaml("technologies.yaml")
    group_rules = load_yaml("groups.yaml")

    samples = pd.DataFrame([
        sample_metadata(gsm, disease_rules, tissue_rules, tech_rules, group_rules)
        for gsm in gse.gsms.values()
    ])

    study_text = " | ".join([
        collect_field(gse.metadata, "title"),
        collect_field(gse.metadata, "summary"),
        collect_field(gse.metadata, "overall_design"),
    ])
    disease = infer(study_text, disease_rules, "GSE metadata", 0.75)
    tissue = infer(study_text, tissue_rules, "GSE metadata", 0.75)
    technology = infer_technology(gse.metadata, tech_rules)
    study_type, study_conf = study_type_from_technology(technology["value"])

    supplementary = []
    for key, value in gse.metadata.items():
        if key.startswith("supplementary_file"):
            supplementary.extend(value if isinstance(value, list) else [value])
    matrix_hits = [
        x for x in supplementary
        if any(term in norm(x) for term in ("series_matrix", "matrix", "expression", ".txt", ".tsv", ".csv"))
    ]

    study = pd.DataFrame([{
        "gse": gse_id,
        "title": collect_field(gse.metadata, "title"),
        "organism": samples["organism"].mode().iat[0] if not samples.empty else "unknown",
        "disease": disease["value"],
        "disease_confidence": disease["confidence"],
        "disease_evidence": json.dumps(disease["evidence"], ensure_ascii=False),
        "tissue": tissue["value"],
        "tissue_confidence": tissue["confidence"],
        "technology": technology["value"],
        "technology_confidence": technology["confidence"],
        "study_type": study_type,
        "study_type_confidence": study_conf,
        "matrix_available": "true" if matrix_hits else "unknown",
        "matrix_confidence": 0.95 if matrix_hits else 0.0,
        "matrix_evidence": json.dumps(matrix_hits, ensure_ascii=False),
        "sample_count": len(samples),
    }])

    study.to_csv(out_dir / "study.tsv", sep="\t", index=False)
    samples.to_csv(out_dir / "sample.tsv", sep="\t", index=False)
    return study, samples


def matches(value: str, rule: Any) -> bool:
    if rule is None:
        return True
    if isinstance(rule, str):
        return value == rule
    if isinstance(rule, list):
        return value in rule
    if isinstance(rule, dict):
        include, exclude = rule.get("include"), rule.get("exclude", [])
        return (not include or value in include) and value not in exclude
    return True


def filter_samples(df: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    out = df.copy()
    for column in ("organism", "disease", "tissue", "study_type", "technology", "group"):
        if column in config and column in out:
            out = out[out[column].map(lambda x: matches(str(x), config[column]))]

    required = config.get("groups", {}).get("require", [])
    if required and "gse" in out and "group" in out:
        grouped = out.groupby("gse")["group"].apply(set)
        valid = grouped[grouped.map(lambda s: set(required).issubset(s))].index
        out = out[out["gse"].isin(valid)]
    return out


def main():
    parser = argparse.ArgumentParser(description="GEO search, metadata tagging and filtering")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("search", help="search GEO DataSets")
    p.add_argument("query")
    p.add_argument("--max-results", type=int, default=50)
    p.add_argument("--output", default="geo_search.tsv")

    p = sub.add_parser("annotate", help="annotate one GSE")
    p.add_argument("gse")
    p.add_argument("--out", default="geo_output")

    p = sub.add_parser("filter", help="filter a sample.tsv with YAML")
    p.add_argument("--input", required=True)
    p.add_argument("--config", required=True)
    p.add_argument("--output", default="filtered_samples.tsv")

    args = parser.parse_args()

    if args.command == "search":
        result = search_geo(args.query, args.max_results)
        result.to_csv(args.output, sep="\t", index=False)
        print(f"Found {len(result)} GSE candidates.")
        print(result.to_string(index=False))
    elif args.command == "annotate":
        study, samples = annotate_gse(args.gse, Path(args.out))
        print(f"Annotated {args.gse}: {len(samples)} samples")
        print(study.to_string(index=False))
    else:
        with open(args.config, encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
        samples = pd.read_csv(args.input, sep="\t")
        result = filter_samples(samples, config)
        result.to_csv(args.output, sep="\t", index=False)
        print(f"Kept {len(result)} samples.")


if __name__ == "__main__":
    main()
