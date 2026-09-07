# 批量预测化合物靶点

这个工具把化合物的 SMILES 逐个提交到 SwissTargetPrediction 网站，并把网站给出的预测结果保存下来。

“靶点”通常指可能与化合物发生作用的蛋白质。预测结果适合用于筛选研究方向，不能代替实验验证，也不表示化合物一定具有某种治疗作用。

## 使用前要准备什么？

1. 化合物的 SMILES。它是一串表示化学结构的字符，可以先用本仓库的 PubChem 工具获得。
2. 最新版 Microsoft Edge 或 Google Chrome。
3. 能够打开 [SwissTargetPrediction](https://www.swisstargetprediction.ch/) 网站的网络。
4. Python 3.10 或更高版本。

第一次使用时安装依赖：

```bash
cd swiss_target_prediction
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

运行时会出现真实浏览器窗口，这是正常现象。不要在任务运行期间关闭或频繁操作这个窗口。

## 输入表怎么准备？

推荐准备一个 CSV 或 Excel 表，至少包含一列 SMILES。最好再准备一列容易辨认的化合物编号：

| compound_id | smiles |
| --- | --- |
| CMP001 | CCO |
| CMP002 | CC(=O)OC1=CC=CC=C1C(=O)O |

支持 SMI、TXT、CSV、TSV、XLSX、XLS、JSON 和 JSONL。常见的 `smiles`、`canonical_smiles`、`pubchem_isomeric_smiles` 等列名可以自动识别。

## 最快开始

从 Excel 读取 PubChem 工具生成的 SMILES，并预测人类靶点：

```bash
python swiss_target_predict_from_smi.py \
  --input pubchem_results.xlsx \
  --smiles-column pubchem_isomeric_smiles \
  --id-column pubchem_cid \
  --output-dir swiss_results \
  --browser edge \
  --organism human
```

从简单的 SMI 文件运行：

```bash
python swiss_target_predict_from_smi.py \
  --input compounds.smi \
  --output-dir swiss_results
```

也可以直接输入一个 SMILES，不准备表格：

```bash
python swiss_target_predict_from_smi.py \
  --smiles 'CCO' \
  --output-dir direct_results
```

可选物种为 `human`（人）、`mouse`（小鼠）和 `rat`（大鼠），默认是人。

## 会生成什么？

输出目录主要包含：

- `<化合物编号>.csv`：该化合物的靶点预测结果。
- `<输入文件名>_swiss_progress.csv`：整个任务的进度表。
- `_download_staging/`：浏览器下载时使用的临时目录，可用于排查失败原因。

进度表中的状态包括：

- `success`：预测成功，已有结果文件。
- `pending`：还没有处理。
- `no_result`：等待超时或网站没有返回结果。
- `failed`：处理失败，原因会写在进度表中。
- `blocked`：浏览器或网络可能被网站阻断。

## 中断后怎么办？

使用相同的输入和输出目录再次运行即可。已经存在结果 CSV 的化合物会自动跳过，没有成功的项目会重试。

如果希望连已经标记为失败的项目也跳过，可以增加 `--skip-known-status`。如果同一编号对应的 SMILES 发生变化，脚本会把它当作新任务重新预测。

## 常见问题

**浏览器打不开或提示找不到驱动**

Selenium 通常会自动匹配浏览器驱动。如果失败，需要下载与浏览器版本一致的 `msedgedriver` 或 `chromedriver`，再使用 `--driver-path` 指定文件。

**网站加载慢，很多项目显示 no_result**

增加等待时间，例如 `--download-timeout 180`。两次任务间隔可用 `--request-delay 20` 调大。

**输入表有 SMILES，但脚本没有识别**

明确指定列名，例如 `--smiles-column SMILES`。如果表格没有标题行，加上 `--no-header`。

**连续出现 blocked**

先停止任务，确认浏览器能手动访问网站，稍后再运行。不要开启多个脚本同时提交预测。

网页改版后，自动点击位置可能失效，这时需要更新脚本中的网页元素规则。

## 进阶参数

```text
--input PATH                 输入文件
--smiles VALUE               直接输入 SMILES，可重复使用
--smiles-column NAME         SMILES 所在列
--id-column NAME             化合物编号所在列
--output-dir PATH            保存目录
--browser edge|chrome        使用的浏览器
--driver-path PATH           手动指定浏览器驱动
--organism human|mouse|rat   预测物种
--request-delay SECONDS      两个化合物之间的等待时间
--wait-timeout SECONDS       页面普通操作的等待上限
--download-timeout SECONDS   预测和下载的等待上限
--skip-known-status          跳过进度表中已有最终状态的项目
```

完整参数可运行 `python swiss_target_predict_from_smi.py --help` 查看。使用时请遵守 SwissTargetPrediction 网站的服务规则，避免过快或并行提交。
