# 科研数据处理工具

这里收集了 6 个可以单独使用的小工具。它们主要处理 Excel、CSV、PDF、化合物和 GEO 公共组学数据。

不需要先读懂全部代码。先根据自己的任务选择工具，再进入对应文件夹，按照其中 README 的“最快开始”操作即可。

## 我应该用哪个工具？

| 你现在有什么 | 你想得到什么 | 使用的工具 |
| --- | --- | --- |
| 化合物名称、CID、CAS 或 SMILES | PubChem 信息 | `pubchem_downloader/` |
| 化合物的 SMILES | 可能作用的蛋白质靶点 | `swiss_target_prediction/` |
| 可以选中文字的 PDF | Markdown 文本或 Excel 表格 | `pdf_batch_extractor/` |
| 一张关系表和两张信息表 | 合并后的总表，以及按样本拆开的表 | `relation_table_splitter/` |
| 一列基因名或关键词 | PubMed 检索数量 | `pubmed_term_counter/` |
| GEO 中的候选 GSE/GSM | 搜索、自动标注、按条件筛选并下载处理后数据 | `geo_metadata_tagger/` |

## 第一次使用

每个工具文件夹里都有 README、Python 脚本和 requirements.txt。通常进入工具目录后运行：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

正式分析前仍应人工抽查自动标签，并检查下载后的表达矩阵中的基因 ID、样本名、表达值类型和分组信息。
