#!/usr/bin/env python3
"""Search and annotate GEO studies/samples with auditable metadata tags.

The first version intentionally uses structured GEO metadata + editable synonym
rules. Every inferred value keeps evidence and a rule-based confidence score.
It does not download expression matrices.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import GEOparse
import pandas as pd
import yaml


ROOT = Path(__file__).resolve().parent
RULE_DIR = ROOT / "rules"


def load_yaml(name: str) -> dict[str, list[str]]:
    with open(RULE_DIR / name, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def norm(text: Any) -> str:
    return re.sub(r"\\s+", " ", str(text or "")).strip().lower()


def evidence_match(text: str, rules: dict[str, list[str]]):
    text_n = norm(text)
    hits = []
    for label, terms in rules.items():
        for term in terms:
            if norm(term) in text_n:
                hits.append((label, term))
    return hits


def infer(text: str, rules: dict[str, list[str]], field: str) -> dict[str, Any]:
    hits = evidence_match(text, rules)
    if not hits:
        return {"value": "unknown", "confidence": 0.0, "evidence": []}
    # Structured metadata is the strongest source used by this version.
    label, term = hits[0]
    return {
        "value": label,
        "confidence": 0.95,
        "evidence": [{"field": field, "matched_term": term, "text": text}],
    }


def flatten_values(value: Any) -> str:
    if isinstance(value, list):
        return "; ".join(str(x) for x in value)
    if isinstance(value, dict):
        return "; ".join(f"{k}: {v}" for k, v in value.items())
    return str(value or "")


def sample_metadata(gsm, disease_rules, tissue_rules, tech_rules, group_rules):
    meta = getattr(gsm, "metadata", {}) or {}

    def first(key):
        v = meta.get(key, [""])
        return flatten_values(v)

    organism = first("organism_ch1")
    title = first("title")
    source = first("source_name_ch1")
    characteristics = " | ".join(
        f"{k}: {flatten_values(v)}"
        for k, v in meta.items()
        if k.startswith("characteristics_ch1")
    )
    library = first("library_strategy")
    molecule = first("molecule_ch1")
    text = " | ".join(x for x in [title, source, characteristics, library, molecule] if x)

    disease = infer(text, disease_rules, "sample_metadata")
    tissue = infer(text, tissue_rules, "sample_metadata")
    technology = infer(text, tech_rules, "sample_metadata")
    group = infer(text, group_rules, "sample_metadata")

    study_type = "unknown"
    study_conf = 0.0
    if technology["value"] == "scRNA-seq":
        study_type, study_conf = "scRNA", technology["confidence"]
    elif technology["value"] == "snRNA-seq":
        study_type, study_conf = "snRNA", technology["confidence"]
    elif technology["value"] == "Spatial":
        study_type, study_conf = "spatial", technology["confidence"]
    elif technology["value"] == "RNA-seq":
        study_type, study_conf = "bulk", 0.80
    elif technology["value"] == "Microarray":
        study_type, study_conf = "bulk", 0.70

    return {
        "gsm": gsm.name,
        "title": title,
        "organism": organism or "unknown",
        "disease": disease["value"],
        "disease_confidence": disease["confidence"],
        "disease_evidence": json.dumps(disease["evidence"], ensure_ascii=False),
        "tissue": tissue["value"],
        "tissue_confidence": tissue["confidence"],
        "tissue_evidence": json.dumps(tissue["evidence"], ensure_ascii=False),
        "technology": technology["value"],
        "technology_confidence": technology["confidence"],
        "technology_evidence": json.dumps(technology["evidence"], ensure_ascii=False),
        "study_type": study_type,
        "study_type_confidence": study_conf,
        "group": group["value"],
        "group_confidence": group["confidence"],
        "group_evidence": json.dumps(group["evidence"], ensure_ascii=False),
        "source_name": source,
        "library_strategy": library,
        "molecule": molecule,
    }


def fetch_and_annotate(gse_id: str, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    gse = GEOparse.get_GEO(geo=gse_id, destdir=str(out_dir / "geo_cache"), silent=True)

    disease_rules = load_yaml("diseases.yaml")
    tissue_rules = load_yaml("tissues.yaml")
    tech_rules = load_yaml("technologies.yaml")
    group_rules = load_yaml("groups.yaml")

    rows = [
        sample_metadata(gsm, disease_rules, tissue_rules, tech_rules, group_rules)
        for gsm in gse.gsms.values()
    ]
    samples = pd.DataFrame(rows)

    study_text = " ".join([
        str(gse.metadata.get("title", "")),
        str(gse.metadata.get("summary", "")),
        str(gse.metadata.get("overall_design", "")),
    ])
    disease = infer(study_text, disease_rules, "GSE metadata")
    tissue = infer(study_text, tissue_rules, "GSE metadata")
    technology = infer(study_text, tech_rules, "GSE metadata")

    matrix_files = []
    for key in ("supplementary_file", "supplementary_file_1", "supplementary_file_2"):
        vals = gse.metadata.get(key, [])
        matrix_files.extend(vals if isinstance(vals, list) else [vals])
    matrix_hits = [
        x for x in matrix_files
        if any(term in norm(x) for term in ("matrix", "series_matrix", ".txt", ".tsv", ".csv"))
    ]

    study = pd.DataFrame([{
        "gse": gse_id,
        "title": flatten_values(gse.metadata.get("title", "")),
        "organism": samples["organism"].mode().iat[0] if not samples.empty else "unknown",
        "disease": disease["value"],
        "disease_confidence": disease["confidence"],
        "disease_evidence": json.dumps(disease["evidence"], ensure_ascii=False),
        "tissue": tissue["value"],
        "tissue_confidence": tissue["confidence"],
        "technology": technology["value"],
        "technology_confidence": technology["confidence"],
        "study_type": (
            "scRNA" if technology["value"] == "scRNA-seq"
            else "snRNA" if technology["value"] == "snRNA-seq"
            else "spatial" if technology["value"] == "Spatial"
            else "bulk" if technology["value"] in ("RNA-seq", "Microarray")
            else "unknown"
        ),
        "matrix_available": bool(matrix_hits),
        "matrix_evidence": json.dumps(matrix_hits, ensure_ascii=False),
        "sample_count": len(samples),
    }])

    study.to_csv(out_dir / "study.tsv", sep="\t", index=False)
    samples.to_csv(out_dir / "sample.tsv", sep="\t", index=False)
    return study, samples


def main():
    p = argparse.ArgumentParser(description="GEO metadata search/annotation helper")
    sub = p.add_subparsers(dest="command", required=True)

    a = sub.add_parser("annotate", help="download one GSE metadata record and annotate samples")
    a.add_argument("gse")
    a.add_argument("--out", default="geo_output")

    args = p.parse_args()
    if args.command == "annotate":
        study, samples = fetch_and_annotate(args.gse, Path(args.out))
        print(f"Annotated {args.gse}: {len(samples)} samples")
        print(study.to_string(index=False))


if __name__ == "__main__":
    main()
