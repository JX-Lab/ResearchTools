#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError

import pandas as pd

SUPPORTED_SUFFIXES = {".csv", ".tsv", ".txt", ".smi", ".xlsx", ".xls", ".json", ".jsonl"}
OUTPUT_TABLE_SUFFIXES = {".csv", ".tsv", ".xlsx"}
CAS_PATTERN = re.compile(r"^\d{2,7}-\d{2}-\d$")
INCHIKEY_PATTERN = re.compile(r"^[A-Z]{14}-[A-Z]{10}-[A-Z]$")

QUERY_TYPES = {"auto", "cid", "cas", "name", "smiles", "inchi", "inchikey", "formula", "identifier"}
QUERY_TYPE_ALIASES = {
    "pubchem_cid": "cid",
    "compound_cid": "cid",
    "cas_rn": "cas",
    "casrn": "cas",
    "canonical_smiles": "smiles",
    "isomeric_smiles": "smiles",
    "inchi_key": "inchikey",
    "molecular_formula": "formula",
}
AUTO_COLUMN_TYPES = {
    "cid": "cid",
    "pubchem_cid": "cid",
    "compound_cid": "cid",
    "cas": "cas",
    "cas_rn": "cas",
    "casrn": "cas",
    "name": "name",
    "compound_name": "name",
    "chemical_name": "name",
    "smiles": "smiles",
    "canonical_smiles": "smiles",
    "isomeric_smiles": "smiles",
    "inchi": "inchi",
    "inchikey": "inchikey",
    "inchi_key": "inchikey",
    "formula": "formula",
    "molecular_formula": "formula",
    "identifier": "identifier",
    "compound_id": "identifier",
}

RN_TO_CID_URL = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/xref/RN/{query}/cids/JSON"
NAME_TO_CID_URL = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{query}/cids/JSON"
NAMESPACE_TO_CID_URL = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/{namespace}/{query}/cids/JSON"
POST_TO_CID_URL = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/{namespace}/cids/JSON"
PROPERTY_URL = (
    "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/"
    "{cid}/property/Title,IUPACName,MolecularFormula,MolecularWeight,"
    "ConnectivitySMILES,SMILES,InChI,InChIKey,ExactMass,MonoisotopicMass,"
    "XLogP,TPSA,HBondDonorCount,HBondAcceptorCount,RotatableBondCount,"
    "Charge,Complexity/JSON"
)
SYNONYM_URL = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cid}/synonyms/JSON"
LISTKEY_TO_CID_URL = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/listkey/{listkey}/cids/JSON"

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; PubChemStructureFetcher/1.0)",
    "Accept": "application/json",
}

OUTPUT_COLUMNS = [
    "pubchem_query",
    "pubchem_query_type",
    "pubchem_lookup_route",
    "pubchem_status",
    "pubchem_message",
    "pubchem_candidate_count",
    "pubchem_cid",
    "pubchem_title",
    "pubchem_iupac_name",
    "pubchem_molecular_formula",
    "pubchem_molecular_weight",
    "pubchem_exact_mass",
    "pubchem_monoisotopic_mass",
    "pubchem_xlogp",
    "pubchem_tpsa",
    "pubchem_hbond_donor_count",
    "pubchem_hbond_acceptor_count",
    "pubchem_rotatable_bond_count",
    "pubchem_charge",
    "pubchem_complexity",
    "pubchem_canonical_smiles",
    "pubchem_isomeric_smiles",
    "pubchem_inchi",
    "pubchem_inchikey",
    "pubchem_compound_url",
    "pubchem_sdf_record_type",
    "pubchem_sdf_download_status",
    "pubchem_sdf_message",
    "pubchem_sdf_local_path",
    "pubchem_sdf_url",
]


class PubChemError(RuntimeError):
    """Raised when a PubChem request fails."""


class PubChemNotFoundError(PubChemError):
    """Raised when PubChem has no match for the query."""


@dataclass(frozen=True)
class OutputTargets:
    table_path: Path
    sdf_dir: Path


def prompt_nonempty(message: str) -> str:
    while True:
        value = input(message).strip()
        if value:
            return value
        print("输入不能为空，请重新输入。")


def prompt_input_path() -> Path:
    while True:
        raw = prompt_nonempty("请输入输入文件路径（支持 CSV/TSV/TXT/SMI/Excel/JSON/JSONL）: ")
        path = Path(raw).expanduser()
        if not path.exists():
            print(f"文件不存在: {path}")
            continue
        if not path.is_file():
            print(f"不是文件: {path}")
            continue
        if path.suffix.lower() not in SUPPORTED_SUFFIXES:
            print("不支持该文件类型，请查看 README 中的输入格式说明。")
            continue
        return path


def resolve_output_targets(input_path: Path, raw_output_path: str) -> OutputTargets:
    output_path = Path(raw_output_path).expanduser()
    if output_path.suffix.lower() in OUTPUT_TABLE_SUFFIXES:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        sdf_dir = output_path.parent / f"{output_path.stem}_sdf"
        sdf_dir.mkdir(parents=True, exist_ok=True)
        return OutputTargets(table_path=output_path, sdf_dir=sdf_dir)

    if output_path.exists() and output_path.is_file():
        raise ValueError("保存路径是文件，但后缀不是 .csv、.tsv 或 .xlsx。")

    output_path.mkdir(parents=True, exist_ok=True)
    table_path = output_path / f"{input_path.stem}_pubchem_structures.csv"
    sdf_dir = output_path / f"{input_path.stem}_sdf"
    sdf_dir.mkdir(parents=True, exist_ok=True)
    return OutputTargets(table_path=table_path, sdf_dir=sdf_dir)


def prompt_output_path(input_path: Path) -> OutputTargets:
    while True:
        raw = prompt_nonempty("请输入保存路径（可填目录或输出文件路径）: ")
        try:
            output_targets = resolve_output_targets(input_path, raw)
        except ValueError as exc:
            print(str(exc))
            continue
        if output_targets.table_path.resolve() == input_path.resolve():
            print("保存路径不能与输入文件相同，请换一个路径。")
            continue
        return output_targets


def read_table(
    path: Path,
    *,
    delimiter: str | None = None,
    encoding: str = "utf-8-sig",
    no_header: bool | None = None,
    sheet: str | int = 0,
) -> pd.DataFrame:
    suffix = path.suffix.lower()
    header = None if no_header else 0

    if suffix in {".xlsx", ".xls"}:
        df = pd.read_excel(path, dtype=str, sheet_name=sheet, header=header)
    elif suffix in {".json", ".jsonl"}:
        df = pd.read_json(path, dtype=str, lines=suffix == ".jsonl")
    elif suffix == ".smi":
        # SMILES files conventionally have no header and use whitespace separators.
        effective_header = None if no_header is not False else 0
        df = pd.read_csv(
            path,
            dtype=str,
            sep=delimiter or r"\s+",
            header=effective_header,
            comment="#",
            encoding=encoding,
            keep_default_na=False,
        )
    else:
        if delimiter is not None:
            sep = delimiter
        elif suffix == ".csv":
            sep = ","
        elif suffix == ".tsv":
            sep = "\t"
        else:
            sep = None
        try:
            df = pd.read_csv(
                path,
                dtype=str,
                sep=sep,
                engine="python" if sep is None else "c",
                header=header,
                comment="#",
                encoding=encoding,
                keep_default_na=False,
            )
        except (pd.errors.ParserError, csv.Error):
            if suffix != ".txt" or delimiter is not None:
                raise
            df = pd.read_csv(
                path,
                dtype=str,
                sep="\0",
                engine="python",
                header=header,
                comment="#",
                encoding=encoding,
                keep_default_na=False,
            )

    df = df.fillna("")
    if header is None or (suffix == ".smi" and no_header is not False):
        first_column = "smiles" if suffix == ".smi" else "identifier"
        df.columns = [first_column if index == 0 else f"column_{index + 1}" for index in range(len(df.columns))]
    else:
        df.columns = [str(column) for column in df.columns]
    return df


def write_table(df: pd.DataFrame, path: Path) -> None:
    if path.suffix.lower() == ".csv":
        df.to_csv(path, index=False, encoding="utf-8-sig")
        return
    if path.suffix.lower() == ".tsv":
        df.to_csv(path, index=False, sep="\t", encoding="utf-8-sig")
        return
    df.to_excel(path, index=False)


def parse_sheet(value: str) -> str | int:
    stripped = value.strip()
    return int(stripped) if stripped.isdigit() else stripped


def normalize_column_key(value: str) -> str:
    return re.sub(r"[^0-9a-z]+", "_", value.strip().lower()).strip("_")


def auto_select_header(columns: list[str]) -> str | None:
    for column in columns:
        if normalize_column_key(column) in AUTO_COLUMN_TYPES:
            return column
    return columns[0] if len(columns) == 1 else None


def resolve_header(columns: list[str], raw_header: str) -> str | None:
    if raw_header in columns:
        return raw_header

    stripped = raw_header.strip()
    for column in columns:
        if column.strip() == stripped:
            return column

    lowered = stripped.lower()
    for column in columns:
        if column.strip().lower() == lowered:
            return column
    return None


def prompt_target_header(columns: list[str]) -> str:
    print("当前表头如下:")
    print(", ".join(str(column) for column in columns))
    while True:
        raw = prompt_nonempty("请输入化合物标识符所在列名: ")
        header = resolve_header(columns, raw)
        if header is not None:
            return header
        print("未找到对应表头，请按上面显示的列名重新输入。")


def normalize_identifier(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return ""
    return text


def safe_json_error_message(exc: HTTPError) -> str:
    try:
        body = exc.read().decode("utf-8", errors="ignore").strip()
    except Exception:
        body = ""
    if not body:
        return exc.reason or f"HTTP {exc.code}"
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return body[:200]
    fault = payload.get("Fault", {})
    details = fault.get("Details", [])
    if details:
        return str(details[0])
    return body[:200]


class PubChemClient:
    def __init__(self, retries: int = 6, timeout: int = 30) -> None:
        self.retries = retries
        self.timeout = timeout
        self.cid_cache: dict[tuple[str, str], tuple[list[int], str]] = {}
        self.property_cache: dict[int, dict[str, Any]] = {}
        self.synonym_cache: dict[int, list[str]] = {}
        self.sdf_cache: dict[tuple[int, str], dict[str, str]] = {}

    def request_bytes(self, url: str, accept: str = "*/*", data: bytes | None = None) -> bytes:
        last_error: Exception | None = None
        headers = dict(HTTP_HEADERS)
        headers["Accept"] = accept
        if data is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        request = urllib.request.Request(url, headers=headers, data=data)
        for attempt in range(1, self.retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return response.read()
            except HTTPError as exc:
                message = safe_json_error_message(exc)
                if exc.code == 404:
                    raise PubChemNotFoundError(message or "PubChem 未找到匹配记录。") from exc
                if exc.code in {429, 500, 502, 503, 504}:
                    last_error = PubChemError(f"HTTP {exc.code}: {message}")
                    if attempt < self.retries:
                        time.sleep(min(2 ** (attempt - 1), 12))
                        continue
                raise PubChemError(f"HTTP {exc.code}: {message}") from exc
            except URLError as exc:
                last_error = exc
                if attempt < self.retries:
                    time.sleep(min(2 ** (attempt - 1), 12))
                    continue
                raise PubChemError(f"网络请求失败: {exc}") from exc
            except Exception as exc:
                last_error = exc
                if attempt < self.retries:
                    time.sleep(min(2 ** (attempt - 1), 12))
                    continue
                raise PubChemError(f"请求失败: {exc}") from exc
        raise PubChemError(f"请求失败: {last_error}")

    def request_json(self, url: str, data: bytes | None = None) -> dict[str, Any]:
        payload = self.request_bytes(url, accept="application/json", data=data)
        try:
            return json.loads(payload.decode("utf-8"))
        except Exception as exc:
            raise PubChemError(f"JSON 解析失败: {exc}") from exc

    def resolve_waiting_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        waiting = payload.get("Waiting", {})
        list_key = str(waiting.get("ListKey", "")).strip()
        if not list_key:
            return payload

        poll_url = LISTKEY_TO_CID_URL.format(listkey=urllib.parse.quote(list_key, safe=""))
        for attempt in range(1, 13):
            time.sleep(min(attempt, 5))
            polled = self.request_json(poll_url)
            if "IdentifierList" in polled:
                return polled
            if not polled.get("Waiting"):
                return polled
        raise PubChemError("PubChem 异步查询等待超时，请稍后重试。")

    def search_cids(self, identifier: str, query_type: str) -> tuple[list[int], str]:
        cache_key = (query_type, identifier)
        if cache_key in self.cid_cache:
            return self.cid_cache[cache_key]

        if query_type == "cid":
            if not identifier.isdigit() or int(identifier) <= 0:
                raise PubChemNotFoundError("CID 必须是正整数。")
            result = ([int(identifier)], "cid")
            self.cid_cache[cache_key] = result
            return result

        encoded = urllib.parse.quote(identifier, safe="")
        route_candidates: list[tuple[str, str, bytes | None]] = []
        if query_type == "cas":
            route_candidates.append(("xref_rn", RN_TO_CID_URL.format(query=encoded), None))
            route_candidates.append(("name_fallback_after_rn", NAME_TO_CID_URL.format(query=encoded), None))
        elif query_type == "name":
            route_candidates.append(("name", NAME_TO_CID_URL.format(query=encoded), None))
        elif query_type == "inchi":
            data = urllib.parse.urlencode({"inchi": identifier}).encode("utf-8")
            route_candidates.append(("inchi_post", POST_TO_CID_URL.format(namespace="inchi"), data))
        elif query_type in {"smiles", "inchikey", "formula", "identifier"}:
            url = NAMESPACE_TO_CID_URL.format(namespace=query_type, query=encoded)
            route_candidates.append((query_type, url, None))
        else:
            raise ValueError(f"不支持的查询类型: {query_type}")

        last_not_found: PubChemNotFoundError | None = None
        last_request_error: PubChemError | None = None
        for route, url, data in route_candidates:
            try:
                payload = self.request_json(url, data=data)
                payload = self.resolve_waiting_payload(payload)
            except PubChemNotFoundError as exc:
                last_not_found = exc
                continue
            except PubChemError as exc:
                last_request_error = exc
                continue

            cids = payload.get("IdentifierList", {}).get("CID", [])
            if not cids:
                continue

            parsed = [int(cid) for cid in cids]
            self.cid_cache[cache_key] = (parsed, route)
            return parsed, route

        if last_request_error is not None:
            raise last_request_error
        if last_not_found is not None:
            raise last_not_found
        raise PubChemNotFoundError("PubChem 未返回 CID。")

    def get_properties(self, cid: int) -> dict[str, Any]:
        if cid in self.property_cache:
            return self.property_cache[cid]

        payload = self.request_json(PROPERTY_URL.format(cid=cid))
        properties = payload.get("PropertyTable", {}).get("Properties", [])
        if not properties:
            raise PubChemNotFoundError(f"CID {cid} 未返回结构性质。")
        record = properties[0]
        self.property_cache[cid] = record
        return record

    def get_synonyms(self, cid: int) -> list[str]:
        if cid in self.synonym_cache:
            return self.synonym_cache[cid]

        payload = self.request_json(SYNONYM_URL.format(cid=cid))
        info_list = payload.get("InformationList", {}).get("Information", [])
        if not info_list:
            self.synonym_cache[cid] = []
            return []
        synonyms = info_list[0].get("Synonym", []) or []
        normalized = [str(item).strip() for item in synonyms if str(item).strip()]
        self.synonym_cache[cid] = normalized
        return normalized

    def choose_best_cid(self, identifier: str, query_type: str, cids: list[int]) -> tuple[int, str]:
        if len(cids) == 1 or query_type != "cas":
            return cids[0], ""

        for cid in cids[:5]:
            try:
                synonyms = self.get_synonyms(cid)
            except PubChemError:
                continue
            if any(synonym == identifier for synonym in synonyms):
                return cid, "CAS 精确匹配到同义词。"
        return cids[0], "CAS 未能精确确认候选，已采用 PubChem 返回的首个结果。"

    def download_sdf(self, cid: int, output_dir: Path, record_type: str = "auto") -> dict[str, str]:
        cache_key = (cid, record_type)
        if cache_key in self.sdf_cache:
            return dict(self.sdf_cache[cache_key])

        output_dir.mkdir(parents=True, exist_ok=True)
        file_path = output_dir / f"{cid}.sdf"
        all_attempts = [
            ("3d", f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cid}/SDF?record_type=3d"),
            ("2d", f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cid}/SDF?record_type=2d"),
        ]
        attempts = all_attempts if record_type == "auto" else [item for item in all_attempts if item[0] == record_type]
        last_error = ""

        for record_type, url in attempts:
            try:
                payload = self.request_bytes(url, accept="chemical/x-mdl-sdfile")
            except PubChemNotFoundError as exc:
                last_error = str(exc)
                continue
            except PubChemError as exc:
                last_error = str(exc)
                continue

            if b"M  END" not in payload and b"$$$$" not in payload:
                last_error = "PubChem 返回内容不是有效 SDF。"
                continue

            file_path.write_bytes(payload)
            result = {
                "pubchem_sdf_record_type": record_type,
                "pubchem_sdf_download_status": "ok",
                "pubchem_sdf_message": f"SDF 下载成功（{record_type.upper()}）。",
                "pubchem_sdf_local_path": str(file_path.resolve()),
                "pubchem_sdf_url": url,
            }
            self.sdf_cache[cache_key] = dict(result)
            return result

        result = {
            "pubchem_sdf_record_type": "",
            "pubchem_sdf_download_status": "error",
            "pubchem_sdf_message": last_error or "SDF 下载失败。",
            "pubchem_sdf_local_path": "",
            "pubchem_sdf_url": "",
        }
        self.sdf_cache[cache_key] = dict(result)
        return result


def build_result_template() -> dict[str, str]:
    return {column: "" for column in OUTPUT_COLUMNS}


def normalize_query_type(value: str) -> str:
    normalized = normalize_column_key(value)
    normalized = QUERY_TYPE_ALIASES.get(normalized, normalized)
    if normalized not in QUERY_TYPES:
        raise ValueError(f"未知查询类型: {value}")
    return normalized


def infer_query_type(identifier: str, header: str = "") -> str:
    column_type = AUTO_COLUMN_TYPES.get(normalize_column_key(header))
    if column_type and column_type != "identifier":
        return column_type
    if CAS_PATTERN.fullmatch(identifier):
        return "cas"
    if identifier.lower().startswith("cid:") and identifier[4:].strip().isdigit():
        return "cid"
    if identifier.startswith("InChI="):
        return "inchi"
    if INCHIKEY_PATTERN.fullmatch(identifier.upper()):
        return "inchikey"
    # Pure numbers are overwhelmingly likely to be PubChem CIDs in an identifier column.
    if identifier.isdigit():
        return "cid"
    return "name"


def clean_identifier_for_type(identifier: str, query_type: str) -> str:
    if query_type == "cid" and identifier.lower().startswith("cid:"):
        return identifier[4:].strip()
    return identifier


def stringify_property(properties: dict[str, Any], key: str) -> str:
    value = properties.get(key, "")
    return "" if value is None else str(value)


def lookup_structure(
    identifier: str,
    query_type: str,
    client: PubChemClient,
) -> dict[str, str]:
    result = build_result_template()
    resolved_type = infer_query_type(identifier) if query_type == "auto" else query_type
    cleaned_identifier = clean_identifier_for_type(identifier, resolved_type)
    result["pubchem_query"] = identifier
    result["pubchem_query_type"] = resolved_type

    try:
        cids, route = client.search_cids(cleaned_identifier, resolved_type)
        result["pubchem_lookup_route"] = route
        chosen_cid, message = client.choose_best_cid(cleaned_identifier, resolved_type, cids)
        properties = client.get_properties(chosen_cid)
    except PubChemNotFoundError as exc:
        result["pubchem_status"] = "not_found"
        result["pubchem_message"] = str(exc)
        return result
    except PubChemError as exc:
        result["pubchem_status"] = "error"
        result["pubchem_message"] = str(exc)
        return result

    result["pubchem_status"] = "ok"
    result["pubchem_message"] = message or "查询成功。"
    result["pubchem_candidate_count"] = str(len(cids))
    result["pubchem_cid"] = str(chosen_cid)
    result["pubchem_title"] = stringify_property(properties, "Title")
    result["pubchem_iupac_name"] = stringify_property(properties, "IUPACName")
    result["pubchem_molecular_formula"] = stringify_property(properties, "MolecularFormula")
    result["pubchem_molecular_weight"] = stringify_property(properties, "MolecularWeight")
    result["pubchem_exact_mass"] = stringify_property(properties, "ExactMass")
    result["pubchem_monoisotopic_mass"] = stringify_property(properties, "MonoisotopicMass")
    result["pubchem_xlogp"] = stringify_property(properties, "XLogP")
    result["pubchem_tpsa"] = stringify_property(properties, "TPSA")
    result["pubchem_hbond_donor_count"] = stringify_property(properties, "HBondDonorCount")
    result["pubchem_hbond_acceptor_count"] = stringify_property(properties, "HBondAcceptorCount")
    result["pubchem_rotatable_bond_count"] = stringify_property(properties, "RotatableBondCount")
    result["pubchem_charge"] = stringify_property(properties, "Charge")
    result["pubchem_complexity"] = stringify_property(properties, "Complexity")
    result["pubchem_canonical_smiles"] = stringify_property(
        properties, "ConnectivitySMILES"
    ) or stringify_property(properties, "CanonicalSMILES")
    result["pubchem_isomeric_smiles"] = stringify_property(
        properties, "SMILES"
    ) or stringify_property(properties, "IsomericSMILES")
    result["pubchem_inchi"] = stringify_property(properties, "InChI")
    result["pubchem_inchikey"] = stringify_property(properties, "InChIKey")
    result["pubchem_compound_url"] = f"https://pubchem.ncbi.nlm.nih.gov/compound/{chosen_cid}"
    return result


def download_sdf_files(
    result_df: pd.DataFrame,
    client: PubChemClient,
    sdf_dir: Path,
    record_type: str = "auto",
) -> pd.DataFrame:
    success_rows = result_df[result_df["pubchem_status"] == "ok"]
    unique_cids: list[int] = []
    seen: set[int] = set()

    for value in success_rows["pubchem_cid"].tolist():
        try:
            cid = int(str(value).strip())
        except ValueError:
            continue
        if cid not in seen:
            seen.add(cid)
            unique_cids.append(cid)

    print(f"共检测到 {len(unique_cids)} 个唯一 CID 需要下载 SDF。")

    sdf_cache: dict[str, dict[str, str]] = {}
    for index, cid in enumerate(unique_cids, start=1):
        print(f"[{index}/{len(unique_cids)}] 下载 SDF: CID={cid}")
        sdf_cache[str(cid)] = client.download_sdf(cid, sdf_dir, record_type=record_type)
        status = sdf_cache[str(cid)]["pubchem_sdf_download_status"]
        message = sdf_cache[str(cid)]["pubchem_sdf_message"]
        print(f"  {status}: {message}")
        time.sleep(0.2)

    output = result_df.copy()
    for row_index, row in output.iterrows():
        if row["pubchem_status"] != "ok":
            output.at[row_index, "pubchem_sdf_download_status"] = "skipped"
            output.at[row_index, "pubchem_sdf_message"] = "PubChem 查询未成功，未下载 SDF。"
            continue

        sdf_result = sdf_cache.get(str(row["pubchem_cid"]))
        if not sdf_result:
            output.at[row_index, "pubchem_sdf_download_status"] = "error"
            output.at[row_index, "pubchem_sdf_message"] = "缺少对应 CID 的 SDF 下载结果。"
            continue

        for key, value in sdf_result.items():
            output.at[row_index, key] = value

    return output


def process_table(
    df: pd.DataFrame,
    header: str,
    client: PubChemClient,
    sdf_dir: Path,
    *,
    query_type: str = "auto",
    type_column: str | None = None,
    record_type: str = "auto",
    download_sdf: bool = True,
    delay: float = 0.2,
) -> pd.DataFrame:
    identifiers = [normalize_identifier(value) for value in df[header].tolist()]
    query_types: list[str] = []
    for row_index, identifier in enumerate(identifiers):
        raw_type = normalize_identifier(df.iloc[row_index][type_column]) if type_column else query_type
        normalized_type = normalize_query_type(raw_type or query_type)
        query_types.append(infer_query_type(identifier, header) if normalized_type == "auto" else normalized_type)

    unique_queries: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for identifier, resolved_type in zip(identifiers, query_types):
        key = (identifier, resolved_type)
        if identifier and key not in seen:
            seen.add(key)
            unique_queries.append(key)

    print(f"共检测到 {len(identifiers)} 行，其中 {len(unique_queries)} 个非空唯一查询需要处理。")

    cache: dict[tuple[str, str], dict[str, str]] = {}
    for index, (identifier, resolved_type) in enumerate(unique_queries, start=1):
        print(f"[{index}/{len(unique_queries)}] 查询: {identifier} ({resolved_type})")
        key = (identifier, resolved_type)
        cache[key] = lookup_structure(identifier, resolved_type, client)
        if cache[key]["pubchem_status"] == "ok":
            print(
                f"  成功: CID={cache[key]['pubchem_cid']}, "
                f"Title={cache[key]['pubchem_title']}"
            )
        else:
            print(f"  失败: {cache[key]['pubchem_status']} - {cache[key]['pubchem_message']}")
        time.sleep(max(delay, 0))

    row_results: list[dict[str, str]] = []
    for identifier, resolved_type in zip(identifiers, query_types):
        if not identifier:
            empty_result = build_result_template()
            empty_result["pubchem_status"] = "empty"
            empty_result["pubchem_message"] = "单元格为空，未查询。"
            row_results.append(empty_result)
            continue
        row_results.append(cache[(identifier, resolved_type)])

    result_df = pd.DataFrame(row_results)
    if download_sdf:
        result_df = download_sdf_files(result_df, client, sdf_dir, record_type=record_type)
    else:
        result_df["pubchem_sdf_download_status"] = "disabled"
        result_df["pubchem_sdf_message"] = "已通过 --no-sdf 关闭 SDF 下载。"
    output_df = df.copy()
    for column in OUTPUT_COLUMNS:
        output_df[column] = result_df[column]
    return output_df


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="从 PubChem 批量检索化合物信息并下载 SDF 结构。",
    )
    parser.add_argument("-i", "--input", help="输入表格或文本文件路径")
    parser.add_argument(
        "--identifier",
        action="append",
        default=[],
        help="直接输入一个化合物标识符；可重复使用",
    )
    parser.add_argument("-o", "--output", help="输出目录，或 .csv/.tsv/.xlsx 结果文件")
    parser.add_argument("--column", help="化合物标识符列名；省略时按常见列名自动识别")
    parser.add_argument("--type-column", help="逐行指定查询类型的列名")
    parser.add_argument(
        "--query-type",
        choices=sorted(QUERY_TYPES),
        default="auto",
        help="统一查询类型，默认 auto",
    )
    parser.add_argument("--delimiter", help=r"文本分隔符，例如 ','、';' 或 '\t'")
    parser.add_argument("--encoding", default="utf-8-sig", help="文本编码，默认 utf-8-sig")
    parser.add_argument("--no-header", action="store_true", help="输入文件没有表头")
    parser.add_argument("--sheet", default="0", help="Excel 工作表序号或名称，默认 0")
    parser.add_argument(
        "--record-type",
        choices=["auto", "2d", "3d"],
        default="auto",
        help="SDF 坐标类型；auto 先尝试 3D，失败后回退 2D",
    )
    parser.add_argument("--no-sdf", action="store_true", help="只导出信息表，不下载 SDF")
    parser.add_argument("--retries", type=int, default=6, help="请求最大尝试次数，默认 6")
    parser.add_argument("--timeout", type=int, default=30, help="单次请求超时秒数，默认 30")
    parser.add_argument("--delay", type=float, default=0.2, help="相邻请求间隔秒数，默认 0.2")
    return parser


def resolve_cli_column(df: pd.DataFrame, requested: str | None, option_name: str) -> str:
    columns = [str(column) for column in df.columns]
    if requested:
        resolved = resolve_header(columns, requested)
        if resolved is None:
            raise ValueError(f"{option_name} 指定的列不存在: {requested}；可用列: {', '.join(columns)}")
        return resolved
    selected = auto_select_header(columns)
    if selected is None:
        raise ValueError(f"无法自动判断标识符列，请使用 --column 指定。可用列: {', '.join(columns)}")
    return selected


def summarize(output_df: pd.DataFrame, output_targets: OutputTargets, sdf_enabled: bool) -> None:
    print("\n处理完成。")
    print(f"结果表: {output_targets.table_path}")
    if sdf_enabled:
        print(f"SDF 目录: {output_targets.sdf_dir}")
    for status, label in [
        ("ok", "成功"),
        ("not_found", "未找到"),
        ("error", "请求报错"),
        ("empty", "空值跳过"),
    ]:
        print(f"{label}: {int((output_df['pubchem_status'] == status).sum())} 行")
    if sdf_enabled:
        print(f"SDF 下载成功: {int((output_df['pubchem_sdf_download_status'] == 'ok').sum())} 行")
        print(f"SDF 下载失败: {int((output_df['pubchem_sdf_download_status'] == 'error').sum())} 行")


def run_interactive() -> int:
    print("PubChem 通用化合物下载脚本")
    input_path = prompt_input_path()
    output_targets = prompt_output_path(input_path)
    try:
        df = read_table(input_path)
    except Exception as exc:
        print(f"读取文件失败: {exc}", file=sys.stderr)
        return 1
    if df.empty:
        print("输入文件为空，无法处理。", file=sys.stderr)
        return 1
    header = auto_select_header([str(column) for column in df.columns])
    if header is None:
        header = prompt_target_header([str(column) for column in df.columns])
    output_df = process_table(df, header, PubChemClient(), output_targets.sdf_dir)
    try:
        write_table(output_df, output_targets.table_path)
    except Exception as exc:
        print(f"保存文件失败: {exc}", file=sys.stderr)
        return 1
    summarize(output_df, output_targets, sdf_enabled=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    actual_argv = sys.argv[1:] if argv is None else argv
    if not actual_argv:
        return run_interactive()

    parser = build_parser()
    args = parser.parse_args(actual_argv)
    if not args.input and not args.identifier:
        parser.error("必须提供 --input 或至少一个 --identifier")
    if args.retries < 1 or args.timeout < 1 or args.delay < 0:
        parser.error("--retries/--timeout 必须为正数，--delay 不能为负数")

    input_path: Path
    if args.input:
        input_path = Path(args.input).expanduser().resolve()
        if not input_path.is_file():
            parser.error(f"输入文件不存在: {input_path}")
        if input_path.suffix.lower() not in SUPPORTED_SUFFIXES:
            parser.error(f"不支持的输入格式: {input_path.suffix}")
        delimiter = "\t" if args.delimiter == r"\t" else args.delimiter
        try:
            df = read_table(
                input_path,
                delimiter=delimiter,
                encoding=args.encoding,
                no_header=True if args.no_header else None,
                sheet=parse_sheet(args.sheet),
            )
        except Exception as exc:
            parser.error(f"读取输入文件失败: {exc}")
        if args.identifier:
            extra = pd.DataFrame({"identifier": args.identifier})
            if len(df.columns) != 1 or df.columns[0] != "identifier":
                parser.error("--input 与 --identifier 同时使用时，输入文件必须只有 identifier 一列")
            df = pd.concat([df, extra], ignore_index=True)
    else:
        input_path = Path.cwd() / "direct_identifiers.csv"
        df = pd.DataFrame({"identifier": args.identifier})

    if df.empty:
        parser.error("输入中没有可处理的数据行")
    try:
        header = resolve_cli_column(df, args.column, "--column")
        type_column = (
            resolve_cli_column(df, args.type_column, "--type-column")
            if args.type_column
            else None
        )
    except ValueError as exc:
        parser.error(str(exc))

    output_raw = args.output or str(input_path.with_name(f"{input_path.stem}_pubchem_results"))
    try:
        output_targets = resolve_output_targets(input_path, output_raw)
    except ValueError as exc:
        parser.error(str(exc))
    if args.input and output_targets.table_path.resolve() == input_path.resolve():
        parser.error("输出结果表不能覆盖输入文件")

    client = PubChemClient(retries=args.retries, timeout=args.timeout)
    try:
        output_df = process_table(
            df,
            header,
            client,
            output_targets.sdf_dir,
            query_type=args.query_type,
            type_column=type_column,
            record_type=args.record_type,
            download_sdf=not args.no_sdf,
            delay=args.delay,
        )
        write_table(output_df, output_targets.table_path)
    except (ValueError, PubChemError) as exc:
        print(f"处理失败: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"保存或处理失败: {exc}", file=sys.stderr)
        return 1

    summarize(output_df, output_targets, sdf_enabled=not args.no_sdf)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
