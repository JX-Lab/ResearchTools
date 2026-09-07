# 合并关系表，并按名称分成多个文件

这个工具用于处理三张相互关联的表。例如：

1. 中药表：每味中药的编号和名称。
2. 化合物表：每个化合物的编号和详细信息。
3. 关系表：记录“哪味中药包含哪个化合物”。

工具会把三张表合并成一张完整表，再给每味中药分别生成一个文件。它也可以用于药物-靶点、样本-特征等类似数据。

## 先理解“连接键”

连接键就是几张表中用来认出同一对象的编号。

中药表：

| herb_id | herb_name |
| --- | --- |
| H001 | 甘草 |
| H002 | 黄芪 |

化合物表：

| compound_id | compound_name |
| --- | --- |
| C001 | Glycyrrhizin |
| C002 | Quercetin |

关系表：

| herb_id | compound_id |
| --- | --- |
| H001 | C001 |
| H001 | C002 |

这里的 `herb_id` 和 `compound_id` 就是连接键。几张表的列名可以不同，只需在运行命令中分别告诉脚本实际列名。

## 安装

```bash
cd relation_table_splitter
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

支持 CSV、TSV、XLSX 和 XLS 文件。

## 最快开始

假设文件和列名与上面的示例一致：

```bash
python join_and_split_relations.py \
  --relations relations.xlsx \
  --groups herbs.xlsx \
  --items compounds.xlsx \
  --relation-group-key herb_id \
  --group-key herb_id \
  --group-name-column herb_name \
  --relation-item-key compound_id \
  --item-key compound_id \
  --output-dir output \
  --format xlsx
```

参数的含义是：

| 参数 | 应该填写什么 |
| --- | --- |
| `--relations` | 关系表文件 |
| `--groups` | 要按其拆分的对象表，例如中药表 |
| `--items` | 被关联对象的表，例如化合物表 |
| `--relation-group-key` | 关系表中的中药编号列 |
| `--group-key` | 中药表中的中药编号列 |
| `--group-name-column` | 中药表中的中药名称列 |
| `--relation-item-key` | 关系表中的化合物编号列 |
| `--item-key` | 化合物表中的化合物编号列 |
| `--output-dir` | 保存结果的目录 |

`groups` 和 `items` 只是脚本内部的通用叫法。它们可以分别表示药物和靶点、样本和特征，或者其他成对关系。

## 三张表的列名不一样怎么办？

例如关系表使用 `tcm_id`，中药表使用 `id`；关系表使用 `ingredient_id`，化合物表也使用 `id`：

```bash
python join_and_split_relations.py \
  --relations TCMIO_relations.xlsx \
  --groups tcm-TCMIO.xlsx \
  --items ingredient-TCMIO.xlsx \
  --relation-group-key tcm_id \
  --group-key id \
  --group-name-column chinese_name \
  --relation-item-key ingredient_id \
  --item-key id \
  --output-dir output/tcmio
```

## 会生成什么？

输出目录包含：

- `merged_relations.xlsx`：三张表合并后的完整结果。
- `groups/`：每味中药或每个分组各自的文件。
- `group_summary.csv`：每组有多少条关系，以及对应的文件名。
- `unmatched_group_relations.csv`：关系表中有编号，但中药表找不到该编号的记录。
- `unmatched_item_relations.csv`：关系表中有编号，但化合物表找不到该编号的记录。
- `audit_summary.csv`：总关系数和未匹配数量。

未匹配记录不会被删除。检查两个 `unmatched` 文件，可以发现编号拼写、缺失信息或表格版本不一致的问题。

## 为什么脚本会提示编号重复？

关系表中的编号可以重复，因为一味中药可以对应多个化合物。

但中药表中的 `herb_id` 应该一行一个，化合物表中的 `compound_id` 也应该一行一个。如果信息表中同一编号出现多次，脚本会停止，避免合并后凭空增加关系行数。请先检查并去重，再重新运行。

## 其他选项

默认输出 Excel。也可以使用：

```text
--format csv     输出 CSV
--format tsv     输出制表符分隔的文本表
--format xlsx    输出 Excel
```

Excel 有多个工作表时，可以指定名称或从 0 开始的序号：

```bash
python join_and_split_relations.py ... \
  --relations-sheet Relations \
  --groups-sheet 0 \
  --items-sheet Compounds
```

如果几张表中存在同名的非编号列，脚本会自动给后合并的列加上 `group_` 或 `item_`，防止原数据被覆盖。

完整参数可运行 `python join_and_split_relations.py --help` 查看。
