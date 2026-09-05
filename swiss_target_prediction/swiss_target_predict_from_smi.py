#!/usr/bin/env python3
"""批量提交 SMILES 到 SwissTargetPrediction 并下载 CSV 结果。

Input format:
    SMILES MOL_ID

Example:
    c1ccccc1 MOL000001
    CCO Ethanol

The script keeps a progress manifest so it can resume interrupted runs.
It is designed for running on a local desktop with a real browser, not on a
headless server.
"""

from __future__ import annotations

import argparse
import csv
import re
import shutil
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable

import pandas as pd

SWISS_URL = "https://swisstargetprediction.ch/index.php"
SUPPORTED_SUFFIXES = {".smi", ".txt", ".csv", ".tsv", ".xlsx", ".xls", ".json", ".jsonl"}
SMILES_COLUMN_ALIASES = {
    "smiles",
    "canonical_smiles",
    "isomeric_smiles",
    "pubchem_canonical_smiles",
    "pubchem_isomeric_smiles",
}
ID_COLUMN_ALIASES = {"mol_id", "molecule_id", "compound_id", "id", "name", "cid", "pubchem_cid"}
SMILES_BOX_ID = "smilesBox"
SUBMIT_BUTTON_ID = "submitButton"
ORGANISM_VALUES = {
    "human": "Homo_sapiens",
    "mouse": "Mus_musculus",
    "rat": "Rattus_norvegicus",
}
MANIFEST_FIELDS = [
    "line_number",
    "mol_id",
    "smiles",
    "predict_status",
    "fail_reason",
    "result_file",
    "started_at",
    "finished_at",
    "last_attempt_at",
]


@dataclass
class Record:
    line_number: int
    mol_id: str
    smiles: str
    predict_status: str = "pending"
    fail_reason: str = ""
    result_file: str = ""
    started_at: str = ""
    finished_at: str = ""
    last_attempt_at: str = ""

    def to_row(self) -> dict[str, str]:
        return {
            "line_number": str(self.line_number),
            "mol_id": self.mol_id,
            "smiles": self.smiles,
            "predict_status": self.predict_status,
            "fail_reason": self.fail_reason,
            "result_file": self.result_file,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "last_attempt_at": self.last_attempt_at,
        }


def timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def sanitize_identifier(value: str, fallback: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z._-]+", "_", value.strip())
    cleaned = cleaned.strip("._-")
    return cleaned or fallback


def normalize_column_key(value: str) -> str:
    return re.sub(r"[^0-9a-z]+", "_", value.strip().lower()).strip("_")


def resolve_column(
    columns: list[str],
    requested: str | None,
    aliases: set[str],
    label: str,
    *,
    required: bool,
) -> str | None:
    if requested:
        for column in columns:
            if column == requested or column.strip().lower() == requested.strip().lower():
                return column
        raise ValueError(f"{label}列不存在: {requested}；可用列: {', '.join(columns)}")
    for column in columns:
        if normalize_column_key(column) in aliases:
            return column
    if required:
        raise ValueError(f"无法自动识别{label}列，请显式指定。可用列: {', '.join(columns)}")
    return None


def make_records(rows: Iterable[tuple[int, str, str]]) -> list[Record]:
    seen_ids: dict[str, int] = {}
    records: list[Record] = []

    for line_number, raw_smiles, raw_identifier in rows:
        smiles = str(raw_smiles).strip()
        if not smiles or smiles.lower() == "nan":
            continue
        fallback = f"row_{line_number}"
        mol_id = sanitize_identifier(str(raw_identifier), fallback)

        if mol_id in seen_ids:
            seen_ids[mol_id] += 1
            mol_id = f"{mol_id}_{seen_ids[mol_id]}"
        else:
            seen_ids[mol_id] = 1

        records.append(Record(line_number=line_number, mol_id=mol_id, smiles=smiles))

    if not records:
        raise ValueError("输入中没有有效的 SMILES")
    return records


def ensure_unique_ids(records: list[Record]) -> list[Record]:
    used: set[str] = set()
    for record in records:
        base = record.mol_id
        candidate = base
        suffix = 2
        while candidate in used:
            candidate = f"{base}_{suffix}"
            suffix += 1
        record.mol_id = candidate
        used.add(candidate)
    return records


def read_smi_file(path: Path, encoding: str = "utf-8-sig") -> list[Record]:
    rows: list[tuple[int, str, str]] = []

    with path.open("r", encoding=encoding) as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue

            parts = line.split()
            if not parts:
                continue

            raw_id = "_".join(parts[1:]) if len(parts) > 1 else f"line_{line_number}"
            rows.append((line_number, parts[0], raw_id))
    return make_records(rows)


def parse_sheet(value: str) -> str | int:
    stripped = value.strip()
    return int(stripped) if stripped.isdigit() else stripped


def read_tabular_file(
    path: Path,
    *,
    smiles_column: str | None,
    id_column: str | None,
    delimiter: str | None,
    encoding: str,
    no_header: bool,
    sheet: str | int,
) -> list[Record]:
    suffix = path.suffix.lower()
    header = None if no_header else 0
    if suffix in {".xlsx", ".xls"}:
        df = pd.read_excel(path, dtype=str, header=header, sheet_name=sheet)
    elif suffix in {".json", ".jsonl"}:
        df = pd.read_json(path, dtype=str, lines=suffix == ".jsonl")
    else:
        sep = delimiter if delimiter is not None else ("\t" if suffix == ".tsv" else ",")
        df = pd.read_csv(
            path,
            dtype=str,
            sep=sep,
            header=header,
            encoding=encoding,
            keep_default_na=False,
        )

    df = df.fillna("")
    if no_header:
        df.columns = [
            "smiles"
            if index == 0
            else "mol_id"
            if index == 1
            else f"column_{index + 1}"
            for index in range(len(df.columns))
        ]
    else:
        df.columns = [str(column) for column in df.columns]
    columns = [str(column) for column in df.columns]
    smiles_header = resolve_column(columns, smiles_column, SMILES_COLUMN_ALIASES, "SMILES", required=True)
    id_header = resolve_column(columns, id_column, ID_COLUMN_ALIASES, "ID", required=False)

    rows = []
    line_offset = 1 if no_header else 2
    for position, (_, row) in enumerate(df.iterrows(), start=line_offset):
        raw_id = row[id_header] if id_header else f"row_{position}"
        rows.append((position, row[smiles_header], raw_id))
    return make_records(rows)


def read_input_records(
    path: Path,
    *,
    smiles_column: str | None = None,
    id_column: str | None = None,
    delimiter: str | None = None,
    encoding: str = "utf-8-sig",
    no_header: bool = False,
    sheet: str | int = 0,
) -> list[Record]:
    if path.suffix.lower() in {".smi", ".txt"} and not smiles_column:
        return read_smi_file(path, encoding=encoding)
    return read_tabular_file(
        path,
        smiles_column=smiles_column,
        id_column=id_column,
        delimiter=delimiter,
        encoding=encoding,
        no_header=no_header,
        sheet=sheet,
    )


def load_manifest(path: Path) -> dict[str, Record]:
    if not path.exists():
        return {}

    manifest: dict[str, Record] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            mol_id = row.get("mol_id", "").strip()
            if not mol_id:
                continue
            manifest[mol_id] = Record(
                line_number=int(row.get("line_number", 0) or 0),
                mol_id=mol_id,
                smiles=row.get("smiles", "").strip(),
                predict_status=row.get("predict_status", "").strip() or "pending",
                fail_reason=row.get("fail_reason", "").strip(),
                result_file=row.get("result_file", "").strip(),
                started_at=row.get("started_at", "").strip(),
                finished_at=row.get("finished_at", "").strip(),
                last_attempt_at=row.get("last_attempt_at", "").strip(),
            )
    return manifest


def merge_records(input_records: list[Record], old_manifest: dict[str, Record]) -> list[Record]:
    merged: list[Record] = []
    for record in input_records:
        previous = old_manifest.get(record.mol_id)
        if previous and previous.smiles == record.smiles:
            record.predict_status = previous.predict_status
            record.fail_reason = previous.fail_reason
            record.result_file = previous.result_file
            record.started_at = previous.started_at
            record.finished_at = previous.finished_at
            record.last_attempt_at = previous.last_attempt_at
        merged.append(record)
    return merged


def write_manifest(path: Path, records: Iterable[Record]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        for record in records:
            writer.writerow(record.to_row())


def require_selenium() -> SimpleNamespace:
    try:
        from selenium import webdriver
        from selenium.common.exceptions import (
            TimeoutException,
            UnexpectedAlertPresentException,
            WebDriverException,
        )
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Selenium is not installed. Install it first with `pip install selenium`."
        ) from exc

    return SimpleNamespace(
        webdriver=webdriver,
        TimeoutException=TimeoutException,
        UnexpectedAlertPresentException=UnexpectedAlertPresentException,
        WebDriverException=WebDriverException,
        By=By,
        EC=EC,
        WebDriverWait=WebDriverWait,
    )


def build_edge_driver(download_dir: Path, driver_path: str | None) -> Any:
    from selenium import webdriver
    from selenium.webdriver.edge.options import Options
    from selenium.webdriver.edge.service import Service

    options = Options()
    options.add_argument("--start-maximized")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_experimental_option(
        "prefs",
        {
            "download.default_directory": str(download_dir),
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "safebrowsing.enabled": True,
        },
    )

    if driver_path:
        driver = webdriver.Edge(service=Service(driver_path), options=options)
    else:
        driver = webdriver.Edge(options=options)

    driver.execute_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    return driver


def build_chrome_driver(download_dir: Path, driver_path: str | None) -> Any:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service

    options = Options()
    options.add_argument("--start-maximized")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_experimental_option(
        "prefs",
        {
            "download.default_directory": str(download_dir),
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "safebrowsing.enabled": True,
        },
    )

    if driver_path:
        driver = webdriver.Chrome(service=Service(driver_path), options=options)
    else:
        driver = webdriver.Chrome(options=options)

    driver.execute_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    return driver


def init_driver(browser: str, download_dir: Path, driver_path: str | None) -> Any:
    if browser == "edge":
        return build_edge_driver(download_dir, driver_path)
    if browser == "chrome":
        return build_chrome_driver(download_dir, driver_path)
    raise ValueError(f"Unsupported browser: {browser}")


def select_organism(driver: Any, organism: str) -> None:
    from selenium.webdriver.common.by import By

    value = ORGANISM_VALUES[organism]
    selector = f"input[name='organism'][value='{value}']"
    button = driver.find_element(By.CSS_SELECTOR, selector)
    if not button.is_selected():
        driver.execute_script("arguments[0].click();", button)


def wait_for_download_button(driver: Any, timeout: int) -> None:
    from selenium.common.exceptions import TimeoutException
    from selenium.webdriver.common.by import By

    end_time = time.time() + timeout
    locators = [
        (By.XPATH, "//div[@id='exportButtons']//button[contains(., 'CSV') or contains(., 'csv')]"),
        (By.XPATH, "//*[@id='exportButtons']//button[2]"),
        (By.XPATH, "//*[@id='exportButtons']//button[last()]"),
    ]

    while time.time() < end_time:
        for by, selector in locators:
            elements = driver.find_elements(by, selector)
            for element in elements:
                if element.is_displayed() and element.is_enabled():
                    return
        time.sleep(1)

    raise TimeoutException("CSV download button did not appear in time")


def click_download_button(driver: Any) -> None:
    from selenium.common.exceptions import TimeoutException
    from selenium.webdriver.common.by import By

    locators = [
        (By.XPATH, "//div[@id='exportButtons']//button[contains(., 'CSV') or contains(., 'csv')]"),
        (By.XPATH, "//*[@id='exportButtons']//button[2]"),
        (By.XPATH, "//*[@id='exportButtons']//button[last()]"),
    ]

    for by, selector in locators:
        elements = driver.find_elements(by, selector)
        for element in elements:
            if element.is_displayed() and element.is_enabled():
                driver.execute_script("arguments[0].click();", element)
                return

    raise TimeoutException("Could not find a clickable CSV download button")


def wait_for_download(download_dir: Path, previous_files: set[str], timeout: int) -> Path:
    from selenium.common.exceptions import TimeoutException

    deadline = time.time() + timeout
    while time.time() < deadline:
        current = {path.name for path in download_dir.iterdir() if path.is_file()}
        new_files = current - previous_files

        csv_candidates = [download_dir / name for name in new_files if name.lower().endswith(".csv")]
        for path in csv_candidates:
            if path.exists() and path.stat().st_size > 0:
                return path

        # Skip still-downloading temporary files.
        if any(name.endswith((".crdownload", ".tmp", ".part")) for name in new_files):
            time.sleep(1)
            continue

        time.sleep(1)

    raise TimeoutException("Timed out while waiting for the Swiss CSV download")


def should_skip(record: Record, results_dir: Path, skip_known_status: bool) -> bool:
    if record.result_file:
        result_path = results_dir / record.result_file
        if result_path.exists():
            return True

    if skip_known_status:
        return record.predict_status in {"success", "no_result", "failed", "blocked"}

    return False


def predict_one(
    driver: Any,
    wait: Any,
    record: Record,
    organism: str,
    staging_dir: Path,
    results_dir: Path,
    download_timeout: int,
) -> None:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC

    record.last_attempt_at = timestamp()
    if not record.started_at:
        record.started_at = record.last_attempt_at

    driver.get(SWISS_URL)
    select_organism(driver, organism)

    smiles_box = wait.until(EC.presence_of_element_located((By.ID, SMILES_BOX_ID)))
    smiles_box.clear()
    smiles_box.send_keys(record.smiles)
    time.sleep(1.5)

    submit_button = wait.until(EC.element_to_be_clickable((By.ID, SUBMIT_BUTTON_ID)))
    driver.execute_script("arguments[0].click();", submit_button)

    wait_for_download_button(driver, timeout=download_timeout)

    before = {path.name for path in staging_dir.iterdir() if path.is_file()}
    click_download_button(driver)
    downloaded = wait_for_download(staging_dir, before, timeout=download_timeout)

    target_name = f"{record.mol_id}.csv"
    target_path = results_dir / target_name
    if target_path.exists():
        target_path.unlink()
    shutil.move(str(downloaded), str(target_path))

    record.predict_status = "success"
    record.fail_reason = ""
    record.result_file = target_name
    record.finished_at = timestamp()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="批量提交 SMILES 到 SwissTargetPrediction 并下载预测结果。",
    )
    parser.add_argument("--input", help="SMI/TXT/CSV/TSV/Excel/JSON/JSONL 输入文件")
    parser.add_argument(
        "--smiles",
        action="append",
        default=[],
        help="直接输入一个 SMILES；可重复使用",
    )
    parser.add_argument("--smiles-column", help="表格中的 SMILES 列名")
    parser.add_argument("--id-column", help="表格中的化合物 ID 列名")
    parser.add_argument("--delimiter", help=r"CSV/TSV 的自定义分隔符，例如 ';' 或 '\t'")
    parser.add_argument("--encoding", default="utf-8-sig", help="文本编码，默认 utf-8-sig")
    parser.add_argument("--no-header", action="store_true", help="表格没有表头，默认第 1/2 列为 SMILES/ID")
    parser.add_argument("--sheet", default="0", help="Excel 工作表序号或名称，默认 0")
    parser.add_argument(
        "--output-dir",
        help="结果和进度清单目录；默认 <输入名>_swiss_results",
    )
    parser.add_argument(
        "--browser",
        choices=["edge", "chrome"],
        default="edge",
        help="Selenium 使用的浏览器，默认 edge",
    )
    parser.add_argument(
        "--driver-path",
        help="可选的 msedgedriver/chromedriver 路径；省略时使用 Selenium Manager",
    )
    parser.add_argument(
        "--organism",
        choices=["human", "mouse", "rat"],
        default="human",
        help="预测物种，默认 human",
    )
    parser.add_argument(
        "--wait-timeout",
        type=int,
        default=60,
        help="普通页面等待秒数，默认 60",
    )
    parser.add_argument(
        "--download-timeout",
        type=int,
        default=120,
        help="等待结果按钮和 CSV 下载的秒数，默认 120",
    )
    parser.add_argument(
        "--request-delay",
        type=int,
        default=10,
        help="相邻化合物的间隔秒数，默认 10",
    )
    parser.add_argument(
        "--max-blocks-before-quit",
        type=int,
        default=5,
        help="连续发生浏览器/网络阻断达到此次数后停止，默认 5",
    )
    parser.add_argument(
        "--skip-known-status",
        action="store_true",
        help="除已有结果文件外，也跳过清单中已有终态的记录",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.input and not args.smiles:
        print("必须提供 --input 或至少一个 --smiles。", file=sys.stderr)
        return 1
    if (
        args.wait_timeout < 1
        or args.download_timeout < 1
        or args.request_delay < 0
        or args.max_blocks_before_quit < 1
    ):
        print("超时和阻断次数必须为正数，--request-delay 不能为负数。", file=sys.stderr)
        return 1

    if args.input:
        input_path = Path(args.input).expanduser().resolve()
        if not input_path.is_file():
            print(f"输入文件不存在: {input_path}", file=sys.stderr)
            return 1
        if input_path.suffix.lower() not in SUPPORTED_SUFFIXES:
            print(f"不支持的输入格式: {input_path.suffix}", file=sys.stderr)
            return 1
    else:
        input_path = Path.cwd() / "direct_smiles.smi"

    if args.output_dir:
        output_dir = Path(args.output_dir).expanduser().resolve()
    else:
        output_dir = input_path.with_name(f"{input_path.stem}_swiss_results")

    results_dir = output_dir
    staging_dir = output_dir / "_download_staging"
    manifest_path = output_dir / f"{input_path.stem}_swiss_progress.csv"

    results_dir.mkdir(parents=True, exist_ok=True)
    staging_dir.mkdir(parents=True, exist_ok=True)

    try:
        if args.input:
            delimiter = "\t" if args.delimiter == r"\t" else args.delimiter
            input_records = read_input_records(
                input_path,
                smiles_column=args.smiles_column,
                id_column=args.id_column,
                delimiter=delimiter,
                encoding=args.encoding,
                no_header=args.no_header,
                sheet=parse_sheet(args.sheet),
            )
        else:
            input_records = []
        if args.smiles:
            start = len(input_records) + 1
            direct_rows = [
                (start + index, smiles, f"direct_{start + index}")
                for index, smiles in enumerate(args.smiles)
            ]
            input_records.extend(make_records(direct_rows))
        input_records = ensure_unique_ids(input_records)
    except Exception as exc:
        print(f"读取输入失败: {exc}", file=sys.stderr)
        return 1
    manifest = load_manifest(manifest_path)
    records = merge_records(input_records, manifest)
    write_manifest(manifest_path, records)

    try:
        sel = require_selenium()
        driver = init_driver(args.browser, staging_dir, args.driver_path)
        wait = sel.WebDriverWait(driver, args.wait_timeout)
    except Exception as exc:
        print(f"浏览器初始化失败: {exc}", file=sys.stderr)
        return 1

    consecutive_blocks = 0
    total = len(records)
    print(f"已载入 {total} 个化合物: {input_path}")
    print(f"结果目录: {results_dir}")
    print(f"进度清单: {manifest_path}")

    try:
        for index, record in enumerate(records, start=1):
            if should_skip(record, results_dir, args.skip_known_status):
                print(f"[{index}/{total}] skip {record.mol_id} ({record.predict_status or 'existing_result'})")
                continue

            print(f"[{index}/{total}] run  {record.mol_id}")
            try:
                predict_one(
                    driver=driver,
                    wait=wait,
                    record=record,
                    organism=args.organism,
                    staging_dir=staging_dir,
                    results_dir=results_dir,
                    download_timeout=args.download_timeout,
                )
                consecutive_blocks = 0
                print(f"  saved -> {record.result_file}")

            except sel.TimeoutException as exc:
                record.predict_status = "no_result"
                record.fail_reason = f"timeout: {exc}"
                record.finished_at = timestamp()
                print(f"  no result / timeout: {exc}")

            except sel.UnexpectedAlertPresentException:
                try:
                    driver.switch_to.alert.accept()
                except Exception:
                    pass
                record.predict_status = "no_result"
                record.fail_reason = "unexpected_alert"
                record.finished_at = timestamp()
                print("  no result / alert")

            except sel.WebDriverException as exc:
                record.predict_status = "blocked"
                record.fail_reason = f"webdriver: {exc.__class__.__name__}"
                record.finished_at = timestamp()
                consecutive_blocks += 1
                print(f"  possible block ({consecutive_blocks}/{args.max_blocks_before_quit}): {exc}")
                write_manifest(manifest_path, records)

                if consecutive_blocks >= args.max_blocks_before_quit:
                    print("连续阻断次数过多，已保留进度并停止。", file=sys.stderr)
                    return 2

                try:
                    driver.quit()
                except Exception:
                    pass

                time.sleep(max(args.request_delay, 5))
                driver = init_driver(args.browser, staging_dir, args.driver_path)
                wait = sel.WebDriverWait(driver, args.wait_timeout)
                continue

            except Exception as exc:  # Keep unexpected errors visible in the manifest.
                record.predict_status = "failed"
                record.fail_reason = f"unexpected: {exc}"
                record.finished_at = timestamp()
                print(f"  failed: {exc}", file=sys.stderr)

            write_manifest(manifest_path, records)
            time.sleep(max(args.request_delay, 0))

    finally:
        try:
            driver.quit()
        except Exception:
            pass

    print("SwissTargetPrediction 批量预测完成。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
