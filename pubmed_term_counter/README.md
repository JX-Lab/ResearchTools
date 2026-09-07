# PubMed 批量文献计数

`query_pubmed_counts.py` 从表格或命令行读取基因/关键词，通过 NCBI E-utilities 获取每条检索式的 PubMed 结果数。脚本支持附加疾病或主题条件、请求重试、断点结果复用及定期写入进度。

## 安装

```bash
cd pubmed_term_counter
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

NCBI 要求请求提供联系邮箱。可每次传入，也可设置环境变量：

```bash
export NCBI_EMAIL="your-name@example.org"
export NCBI_API_KEY="optional-api-key"
```

## 示例

从 Excel 的 `靶点` 列读取基因，并统计其与胃溃疡共同出现的文献：

```bash
python query_pubmed_counts.py \
  --input targets.xlsx \
  --column 靶点 \
  --context '"gastric ulcer"[Title/Abstract]' \
  --email your-name@example.org \
  --output pubmed_counts.xlsx
```

直接查询多个基因：

```bash
python query_pubmed_counts.py \
  --term TP53 \
  --term EGFR \
  --context 'cancer[Title/Abstract]' \
  --email your-name@example.org \
  --output gene_counts.csv
```

默认模板是 `{term}[Gene]`。对于非基因关键词，可替换整个检索模板：

```bash
python query_pubmed_counts.py \
  --term aspirin \
  --query-template '"{term}"[Title/Abstract]' \
  --context 'randomized controlled trial[Publication Type]' \
  --email your-name@example.org \
  --output aspirin_counts.csv
```

模板可同时使用 `{term}` 和 `{context}`。如果模板没有 `{context}`，但传入了 `--context`，脚本会自动以 `AND` 连接两部分。

## 断点和请求频率

- 输出文件中状态为 `ok` 且检索式完全相同的记录会在下次运行时复用；使用 `--force` 可重新查询。
- 默认每完成 10 次新请求写入一次输出，可用 `--checkpoint-every` 调整。
- 未提供 API key 时默认请求间隔为 0.34 秒；提供 API key 时为 0.11 秒。可用 `--delay` 设置更保守的频率。
- 网络错误会按 `--retries` 重试，失败记录会保留为 `error`，不会错误地写成计数 0。

正式分析时应同时保存 `pubmed_query` 列，因为数据库更新和检索式差异都会改变计数。
