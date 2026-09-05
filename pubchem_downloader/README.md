# PubChem 通用化合物批量下载脚本

`fetch_pubchem_structures_from_table.py` 用于批量解析化合物标识符，通过 PubChem PUG REST 查询化合物，输出原表与 PubChem 注释合并后的结果表，并按唯一 CID 下载 SDF。脚本保留无参数交互模式，也提供适合自动化任务的完整命令行参数。

## 环境安装

需要 Python 3.10 或更高版本，并能访问 `pubchem.ncbi.nlm.nih.gov`。

```bash
cd /mnt/disk1/yanganqi/compound_batch_tools/pubchem_downloader
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

`openpyxl` 用于 `.xlsx`，`xlrd` 用于旧式 `.xls`。只处理文本文件时它们不会参与读取。

## 支持的输入

文件格式包括：

- `.csv`、`.tsv`、`.txt`
- `.smi`（默认无表头，第 1 列作为 SMILES）
- `.xlsx`、`.xls`
- `.json`（记录数组或 Pandas 可读取的表结构）、`.jsonl`
- 使用一个或多个 `--identifier` 直接传值，不需要输入文件

查询类型包括：

| 类型 | `--query-type` | 示例 |
| --- | --- | --- |
| PubChem CID | `cid` | `2244` 或 `CID:2244` |
| CAS 登记号 | `cas` | `50-78-2` |
| 化合物名称/同义词 | `name` | `aspirin` |
| SMILES | `smiles` | `CC(=O)OC1=CC=CC=C1C(=O)O` |
| InChI | `inchi` | `InChI=1S/...` |
| InChIKey | `inchikey` | `BSYNRYMUTXBXSQ-UHFFFAOYSA-N` |
| 分子式 | `formula` | `C9H8O4` |
| 外部数据库标识符 | `identifier` | `CHEBI:15365` 等 PubChem 可识别值 |

自动模式会先依据列名判断类型。可识别的典型列名包括 `cid`、`pubchem_cid`、`cas`、`name`、`smiles`、`inchi`、`inchikey`、`formula` 和 `identifier`。列名无法表明类型时，脚本只自动识别 CAS、`CID:`、InChI、InChIKey 和纯数字 CID，其余按名称查询。SMILES 与分子式可能和普通名称产生歧义，建议用明确列名或 `--query-type`。

一张表内可以混合不同标识符：增加类型列，每行填写 `cid/cas/name/smiles/inchi/inchikey/formula/identifier`，并用 `--type-column` 指定。

## 快速使用

无参数启动交互模式：

```bash
python fetch_pubchem_structures_from_table.py
```

从 CSV 的 `CAS` 列查询并输出到指定目录：

```bash
python fetch_pubchem_structures_from_table.py \
  --input compounds.csv \
  --column CAS \
  --query-type cas \
  --output results
```

从 Excel 的 `SMILES` 列查询，只输出信息表，不下载 SDF：

```bash
python fetch_pubchem_structures_from_table.py \
  --input compounds.xlsx \
  --sheet Sheet1 \
  --column SMILES \
  --query-type smiles \
  --no-sdf \
  --output results.xlsx
```

直接查询不同类型的单个或多个值：

```bash
python fetch_pubchem_structures_from_table.py \
  --identifier aspirin \
  --identifier ibuprofen \
  --query-type name \
  --output direct_results
```

混合类型表格示例：

```csv
query,type,source
2244,cid,example
50-78-2,cas,example
aspirin,name,example
BSYNRYMUTXBXSQ-UHFFFAOYSA-N,inchikey,example
```

```bash
python fetch_pubchem_structures_from_table.py \
  -i mixed.csv --column query --type-column type -o mixed_results
```

无表头文件使用 `--no-header`，此时第 1 列命名为 `identifier`。自定义分隔符可用 `--delimiter ';'`；制表符可写为 `--delimiter '\t'`。

## SDF 下载策略

- 默认 `--record-type auto`：先下载 3D，PubChem 没有 3D 构象时自动回退到 2D。
- `--record-type 2d` 或 `--record-type 3d`：只请求指定维度。
- `--no-sdf`：完全关闭 SDF 下载，只保留查询和性质结果。
- 同一 CID 在一次任务中只下载一次，文件名为 `<CID>.sdf`。

## 输出说明

输出结果保留输入的全部列，并追加以下信息：

- 查询状态：`pubchem_query_type`、`pubchem_lookup_route`、`pubchem_status`、`pubchem_message`、候选数量。
- 基本标识：CID、标题、IUPAC 名、PubChem 页面链接。
- 结构标识：Connectivity/Canonical SMILES、Isomeric SMILES、InChI、InChIKey。
- 理化性质：分子式、分子量、精确质量、单同位素质量、XLogP、TPSA、氢键供受体数、可旋转键、净电荷和复杂度。
- SDF 状态：实际下载维度、状态、消息、本地绝对路径和请求 URL。

`pubchem_status` 常见值：

- `ok`：查询成功。
- `not_found`：PubChem 没有匹配项。
- `error`：网络、HTTP 或响应解析错误。
- `empty`：输入单元格为空。

名称、CAS 或分子式可能返回多个候选。脚本记录候选数量并默认选择 PubChem 返回的第一个 CID；CAS 在候选较多时会额外检查前五个 CID 的同义词。分子式检索尤其可能产生大量异构体，结果用于正式分析前应检查 CID 是否符合预期。

## 常用参数

```text
-i, --input PATH          输入文件
--identifier VALUE        直接输入标识符，可重复
-o, --output PATH         输出目录或 CSV/TSV/XLSX 文件
--column NAME             标识符列
--type-column NAME        逐行查询类型列
--query-type TYPE         统一类型，默认 auto
--sheet NAME_OR_INDEX     Excel 工作表
--no-header               输入没有表头
--record-type auto|2d|3d  SDF 坐标类型
--no-sdf                  不下载 SDF
--retries N               最大尝试次数
--timeout SECONDS         单次请求超时
--delay SECONDS           查询之间的等待时间
```

完整参数以 `python fetch_pubchem_structures_from_table.py --help` 为准。

## 注意事项

- 请控制请求频率。批量量较大时增加 `--delay`，并避免并行启动多个实例。
- 结果表会在任务结束时写入；中途强制终止不会产生完整结果表。
- 输出文件不能与输入文件相同。
- PUG REST 的输入命名空间和输出格式以 [PubChem 官方文档](https://pubchem.ncbi.nlm.nih.gov/docs/pug-rest) 为准。
