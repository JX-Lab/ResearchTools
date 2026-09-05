# SwissTargetPrediction 批量预测脚本

`swiss_target_predict_from_smi.py` 使用 Selenium 控制本机 Edge 或 Chrome，将 SMILES 逐条提交到 SwissTargetPrediction，并把每个化合物的预测结果保存为独立 CSV。脚本支持常见文本、表格和 JSON 输入，维护进度清单，并可在任务中断后继续运行。

## 使用前提

- Python 3.10 或更高版本。
- 已安装最新版 Microsoft Edge 或 Google Chrome，运行环境必须能显示真实浏览器窗口。
- 能访问 `swisstargetprediction.ch`。
- 使用过程应遵守 SwissTargetPrediction 的服务条款，不要高并发或过快提交。

安装：

```bash
cd /mnt/disk1/yanganqi/compound_batch_tools/swiss_target_prediction
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Selenium 4 通常会通过 Selenium Manager 自动匹配驱动。离线环境或自动匹配失败时，手动下载与浏览器版本一致的 `msedgedriver`/`chromedriver`，然后使用 `--driver-path`。

## 支持的输入

- `.smi`、`.txt`：每个非注释行格式为 `SMILES ID`；ID 可省略。以 `#` 开头的行会跳过。
- `.csv`、`.tsv`：有表头时自动识别 SMILES 和 ID 列；也可显式指定列名。
- `.xlsx`、`.xls`：可选择工作表。
- `.json`、`.jsonl`：字段规则与表格列相同。
- 一个或多个 `--smiles`：无需输入文件，自动生成 `direct_1` 等 ID。

可自动识别的 SMILES 列名包括 `smiles`、`canonical_smiles`、`isomeric_smiles`、`pubchem_canonical_smiles`、`pubchem_isomeric_smiles`。可自动识别的 ID 列名包括 `mol_id`、`molecule_id`、`compound_id`、`id`、`name`、`cid` 和 `pubchem_cid`。

标准 SMI 示例：

```text
# SMILES ID
CCO ethanol
CC(=O)OC1=CC=CC=C1C(=O)O aspirin
```

CSV 示例：

```csv
compound_id,smiles
CMP001,CCO
CMP002,CC(=O)OC1=CC=CC=C1C(=O)O
```

ID 会用于结果文件名，因此脚本会把空格和特殊字符替换为下划线；重复 ID 会依次追加 `_2`、`_3`。

## 快速使用

从 SMI 文件运行人类靶点预测：

```bash
python swiss_target_predict_from_smi.py \
  --input compounds.smi \
  --output-dir swiss_results \
  --browser edge \
  --organism human
```

从 Excel 指定列和工作表：

```bash
python swiss_target_predict_from_smi.py \
  --input pubchem_results.xlsx \
  --sheet Sheet1 \
  --smiles-column pubchem_isomeric_smiles \
  --id-column pubchem_cid \
  --output-dir swiss_results \
  --browser chrome
```

直接输入 SMILES：

```bash
python swiss_target_predict_from_smi.py \
  --smiles 'CCO' \
  --smiles 'CC(=O)OC1=CC=CC=C1C(=O)O' \
  --output-dir direct_results
```

无表头 CSV/TSV 使用 `--no-header`，脚本把第 1 列视为 SMILES、第 2 列视为 ID。自定义分隔符可用 `--delimiter ';'`，制表符可写为 `--delimiter '\t'`。

支持的物种参数：`human`、`mouse`、`rat`，默认 `human`。

## 输出与断点续跑

输出目录主要包含：

- `<mol_id>.csv`：每个成功化合物的 SwissTargetPrediction 导出结果。
- `<输入文件名>_swiss_progress.csv`：进度清单。
- `_download_staging/`：浏览器下载暂存目录，可在任务结束后保留用于排查。

进度清单记录原始行号、ID、SMILES、状态、失败原因、结果文件和时间。再次用相同输入与相同输出目录运行时：

- 只要对应结果 CSV 存在，该分子会自动跳过。
- 没有结果文件的 `no_result`、`failed`、`blocked` 默认会重试。
- 增加 `--skip-known-status` 后，上述已有终态也会跳过。
- 同一 ID 的 SMILES 发生变化时，不会继承旧状态，会重新预测。

常见状态：`pending`（待处理）、`success`（成功）、`no_result`（超时或页面无结果）、`failed`（其他错误）、`blocked`（浏览器或网络可能被阻断）。清单在每个分子完成后立即更新。

## 稳定运行建议

- 默认每个化合物之间等待 10 秒。遇到限流或页面不稳定时增大 `--request-delay`。
- 页面计算或下载较慢时增大 `--download-timeout`，普通元素加载较慢时增大 `--wait-timeout`。
- 连续 WebDriver 阻断达到 `--max-blocks-before-quit` 后，脚本会保存进度并退出，避免持续失败。
- 运行期间不要关闭或手动频繁操作自动化浏览器窗口。
- 本工具依赖网页结构。SwissTargetPrediction 更新按钮、元素 ID 或下载方式后，选择器可能需要同步调整。

## 常用参数

```text
--input PATH                 输入文件
--smiles VALUE               直接输入 SMILES，可重复
--smiles-column NAME         SMILES 列
--id-column NAME             结果文件名所用 ID 列
--output-dir PATH            输出目录
--browser edge|chrome        浏览器
--driver-path PATH           浏览器驱动路径
--organism human|mouse|rat   预测物种
--request-delay SECONDS      相邻任务间隔
--wait-timeout SECONDS       普通页面等待上限
--download-timeout SECONDS   计算和下载等待上限
--skip-known-status          跳过清单中已有终态
```

完整参数以 `python swiss_target_predict_from_smi.py --help` 为准。SwissTargetPrediction 当前页面及物种选项请参考 [官方网站](https://www.swisstargetprediction.ch/)。
