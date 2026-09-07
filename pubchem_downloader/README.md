# 批量查询 PubChem 化合物信息

这个工具可以把一列化合物名称或编号拿到 PubChem 中查询，再把查到的信息补到原表后面。它还可以下载化合物结构文件。

例如，你有一张只包含“阿司匹林、布洛芬”等名称的 Excel 表，运行后可以得到它们的 PubChem CID、标准名称、分子式、分子量、SMILES、InChIKey 等信息。

## 最快开始

如果不熟悉命令行参数，直接运行：

```bash
python fetch_pubchem_structures_from_table.py
```

脚本会依次询问输入文件、查询列、查询内容类型和保存位置。

## 使用前准备

需要 Python 3.10 或更高版本，并且电脑能够访问 PubChem。

第一次使用时安装依赖：

```bash
cd pubchem_downloader
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## 输入表怎么准备？

最简单的做法是准备一个 Excel 或 CSV 文件，把要查询的内容放在同一列。例如：

| compound_name |
| --- |
| aspirin |
| ibuprofen |

常用输入包括：

| 你手里的信息 | 参数名称 | 示例 |
| --- | --- | --- |
| PubChem 数字编号 | `cid` | `2244` |
| CAS 登记号 | `cas` | `50-78-2` |
| 化合物名称 | `name` | `aspirin` |
| 化学结构字符串 | `smiles` | `CC(=O)OC1=CC=CC=C1C(=O)O` |
| InChI | `inchi` | `InChI=1S/...` |
| InChIKey | `inchikey` | `BSYNRYMUTXBXSQ-UHFFFAOYSA-N` |
| 分子式 | `formula` | `C9H8O4` |

工具支持 CSV、TSV、TXT、SMI、XLSX、XLS、JSON 和 JSONL。对于常见列名，例如 `cid`、`cas`、`name`、`smiles`、`inchi`，通常可以自动判断类型。

不知道 CID、SMILES 或 InChI 是什么也没关系。如果表里只有普通化合物名称，就选择 `name`。

## 常用示例

从 Excel 的 `compound_name` 列查询名称，并把结果保存到 `results.xlsx`：

```bash
python fetch_pubchem_structures_from_table.py \
  --input compounds.xlsx \
  --column compound_name \
  --query-type name \
  --output results.xlsx
```

从 CSV 的 `CAS` 列查询：

```bash
python fetch_pubchem_structures_from_table.py \
  --input compounds.csv \
  --column CAS \
  --query-type cas \
  --output results
```

不准备表格，直接查询两个名称：

```bash
python fetch_pubchem_structures_from_table.py \
  --identifier aspirin \
  --identifier ibuprofen \
  --query-type name \
  --output direct_results
```

如果只要信息表、不需要结构文件，加上 `--no-sdf`：

```bash
python fetch_pubchem_structures_from_table.py \
  --input compounds.xlsx \
  --column compound_name \
  --query-type name \
  --no-sdf \
  --output results.xlsx
```

## 会生成什么？

结果表会保留原来的所有列，并增加 PubChem 信息。最常看的列是：

- `pubchem_cid`：PubChem 数字编号。
- `pubchem_title`、`pubchem_iupac_name`：化合物名称。
- `pubchem_molecular_formula`、`pubchem_molecular_weight`：分子式和分子量。
- `pubchem_canonical_smiles`、`pubchem_isomeric_smiles`：结构字符串。
- `pubchem_inchi`、`pubchem_inchikey`：另一组标准结构标识。
- `pubchem_status`：这一行是否查询成功。
- `pubchem_message`：失败或特殊情况的原因。

默认还会建立一个 `_sdf` 文件夹。SDF 是分子结构文件，可以用 ChemDraw、PyMOL、RDKit 等化学软件读取。脚本优先下载三维结构；没有三维结构时会改用二维结构。

## 怎么判断查询结果？

`pubchem_status` 可能出现：

- `ok`：查询成功。
- `not_found`：PubChem 没找到。
- `error`：网络或服务请求失败，可以稍后重试。
- `empty`：输入单元格是空的。

用名称、CAS 或分子式查询时，有时会找到多个候选。脚本会记录候选数量并选择一个结果，但正式分析前应人工核对 `pubchem_cid` 和名称。仅凭分子式通常无法唯一确定化合物。

## 常见问题

**表中有很多列，脚本不知道用哪一列**

使用 `--column 列名` 明确指定，例如 `--column compound_name`。

**自动判断的查询类型不对**

使用 `--query-type name`、`--query-type cid` 或其他明确类型。

**请求经常失败**

网络不稳定或查询量较大时，可以增加请求间隔，例如 `--delay 1`。不要同时运行多个批量下载任务。

**输入表没有标题行**

加上 `--no-header`。对于 SMI 文件，默认第一列是 SMILES。

## 进阶参数

```text
-i, --input PATH          输入文件
--identifier VALUE        直接输入查询内容，可重复使用
-o, --output PATH         输出目录或 CSV/TSV/XLSX 文件
--column NAME             要查询的列名
--type-column NAME        每一行单独写查询类型时使用
--query-type TYPE         cid、cas、name、smiles 等类型
--sheet NAME_OR_INDEX     Excel 工作表名称或序号
--no-header               输入文件没有标题行
--record-type auto|2d|3d  下载二维或三维 SDF
--no-sdf                  不下载 SDF
--retries N               请求失败后的尝试次数
--timeout SECONDS         单次请求最多等待多久
--delay SECONDS           两次查询之间等待多久
```

完整参数可运行 `python fetch_pubchem_structures_from_table.py --help` 查看。PubChem 查询规则以 [PubChem PUG REST 官方说明](https://pubchem.ncbi.nlm.nih.gov/docs/pug-rest)为准。
