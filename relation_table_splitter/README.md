# 关系表合并与分组导出

`join_and_split_relations.py` 将“关系表、分组实体表、条目实体表”按指定键做左连接，生成完整关系表，并按分组拆成独立文件。它适合中药-化合物、药物-靶点、样本-特征等多对多数据，不绑定特定数据库的列名。

## 安装

```bash
cd relation_table_splitter
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## 输入约束

- 支持 CSV、TSV、XLSX 和 XLS。
- 关系表中的分组键和条目键允许重复。
- 两张实体表的连接键在去除首尾空白后必须唯一，否则脚本会停止，避免静默放大关系数。
- 所有连接均为左连接，未匹配关系不会被丢弃。

## 示例

以 TCMIO 风格的中药、化合物和关系表为例：

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
  --output-dir output/tcmio \
  --format xlsx
```

工作表可用名称或从 0 开始的序号指定：

```bash
python join_and_split_relations.py ... \
  --relations-sheet Relations \
  --groups-sheet 0 \
  --items-sheet Compounds
```

## 输出

- `merged_relations.*`：保留全部关系的合并总表。
- `groups/`：按分组名称和分组键导出的独立文件。
- `group_summary.csv`：每组关系数、未匹配条目数和输出文件。
- `unmatched_group_relations.csv`：未匹配到分组实体的关系。
- `unmatched_item_relations.csv`：未匹配到条目实体的关系。
- `audit_summary.csv`：总关系数、分组数及未匹配统计。

如果实体表与关系表存在同名非键字段，实体字段会自动增加 `group_` 或 `item_` 前缀，避免覆盖原始关系字段。
