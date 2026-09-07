# 科研数据处理工具

这里收集了 5 个可以单独使用的小工具。它们主要处理 Excel、CSV、PDF 和化合物数据。

不需要先读懂全部代码。先根据自己的任务选择工具，再进入对应文件夹，按照其中 README 的“最快开始”操作即可。

## 我应该用哪个工具？

| 你现在有什么 | 你想得到什么 | 使用的工具 |
| --- | --- | --- |
| 化合物名称、CID、CAS 或 SMILES | 化合物名称、分子式、结构文件等 PubChem 信息 | `pubchem_downloader/` |
| 化合物的 SMILES | 可能与化合物作用的蛋白质靶点 | `swiss_target_prediction/` |
| 可以选中文字的 PDF | Markdown 文本或 Excel 表格 | `pdf_batch_extractor/` |
| 一张关系表和两张信息表 | 合并后的总表，以及按中药/样本拆开的表 | `relation_table_splitter/` |
| 一列基因名或关键词 | 每个词在 PubMed 中能检索到多少篇文献 | `pubmed_term_counter/` |

## 第一次使用

每个工具文件夹里都有三个重要文件：

- `README.md`：使用说明。
- `.py`：真正运行的脚本。
- `requirements.txt`：脚本需要安装的 Python 软件包。

通常按下面的方式准备环境。把 `<工具文件夹>` 换成实际名称：

```bash
cd <工具文件夹>
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

安装只需进行一次。以后再次使用时，进入工具文件夹并运行 `source .venv/bin/activate` 即可。

## 几个常见名词

- **CSV/TSV**：和 Excel 表格类似的文本表格，可以用 Excel 打开。
- **CID**：PubChem 给化合物分配的数字编号。
- **SMILES**：用一串字符表示化学结构的方法。
- **SDF**：保存化合物二维或三维结构的文件。
- **靶点**：可能与药物或化合物发生作用的蛋白质。

## 常见工作顺序

如果只有化合物名称，可以先用 `pubchem_downloader` 查找 PubChem 信息和 SMILES，再把结果中的 `pubchem_isomeric_smiles` 列交给 `swiss_target_prediction` 预测靶点。

每个工具默认把结果写入新文件或新目录。正式分析前仍应人工抽查结果，尤其是同名化合物匹配、网页预测和自动提取的 PDF 内容。
