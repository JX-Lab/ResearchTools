# 批量统计 PubMed 文献数量

这个工具读取一列基因名或关键词，然后告诉你：每个词在 PubMed 中能检索到多少篇文献。

例如，可以统计 `TP53`、`EGFR` 分别与胃溃疡相关的文献数量，帮助初步判断哪些基因研究得较多。

文献数量只表示“检索到了多少条记录”，不代表研究质量，也不能证明基因与疾病存在因果关系。正式分析时要保留并检查完整检索式。

## 安装

```bash
cd pubmed_term_counter
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## 为什么需要邮箱？

脚本使用美国国家生物技术信息中心（NCBI）的公开接口。NCBI 要求自动查询时提供联系邮箱，以便请求异常时联系使用者。

邮箱只随请求发送给 NCBI，不会写入结果表。可以每次运行时填写：

```text
--email your-name@example.org
```

也可以在当前终端设置一次：

```bash
export NCBI_EMAIL="your-name@example.org"
```

API key 不是必需的。只有查询量较大时，才需要在 NCBI 账户中申请并通过 `--api-key` 或 `NCBI_API_KEY` 提供。

## 输入表怎么准备？

准备一个 CSV 或 Excel 文件，把基因名放在同一列：

| 靶点 |
| --- |
| TP53 |
| EGFR |
| VEGFA |

支持 CSV、TSV、XLSX 和 XLS。

## 最快开始

统计 Excel 中每个基因与胃溃疡共同出现的文献数：

```bash
python query_pubmed_counts.py \
  --input targets.xlsx \
  --column 靶点 \
  --context '"gastric ulcer"[Title/Abstract]' \
  --email your-name@example.org \
  --output pubmed_counts.xlsx
```

这条命令中：

- `--input` 是输入表。
- `--column` 是基因所在列。
- `--context` 是附加检索条件，这里表示标题或摘要中出现“gastric ulcer”。
- `--output` 是结果文件。

不准备表格，也可以直接输入：

```bash
python query_pubmed_counts.py \
  --term TP53 \
  --term EGFR \
  --email your-name@example.org \
  --output gene_counts.csv
```

## 怎么写疾病或主题条件？

`--context` 后面填写 PubMed 能识别的检索词。推荐把固定词组放在英文双引号中：

```text
--context '"gastric ulcer"[Title/Abstract]'
--context 'cancer[Title/Abstract]'
--context '"type 2 diabetes"[Title/Abstract]'
```

默认情况下，脚本把 `TP53` 变成 `TP53[Gene]`，表示按基因字段检索，再用 `AND` 连接附加条件。

如果输入的不是基因，而是药名或普通关键词，可以改用：

```bash
python query_pubmed_counts.py \
  --term aspirin \
  --query-template '"{term}"[Title/Abstract]' \
  --email your-name@example.org \
  --output aspirin_counts.csv
```

## 结果怎么看？

输出表包含：

- `term`：原始基因名或关键词。
- `pubmed_query`：真正发送给 PubMed 的完整检索式。
- `pubmed_count`：检索到的文献数量。
- `pubmed_status`：是否成功。
- `pubmed_message`：失败原因。
- `pubmed_url`：可以在浏览器中打开并人工检查结果的链接。

`pubmed_status` 为 `ok` 表示查询成功；为 `error` 表示网络或接口请求失败。失败不等于文献数为 0，因此脚本会把失败原因保留下来，而不会错误地写成 0。

## 中断后怎么办？

使用相同输出文件再次运行。结果中状态为 `ok` 且检索式相同的项目会直接复用，只重新查询尚未成功的项目。

如果确实需要全部重新查询，加上 `--force`。PubMed 数据会更新，所以不同日期运行得到的数量可能略有变化。

## 常见问题

**提示必须提供 email**

在命令中加入 `--email 你的邮箱`，或者先设置 `NCBI_EMAIL`。

**表里有多列，脚本不知道读取哪一列**

使用 `--column 列名`。列名必须与 Excel 第一行显示的文字一致。

**查询结果明显太多或太少**

打开 `pubmed_url` 人工检查完整检索式。疾病同义词、字段范围和引号都会影响结果。

**运行过程中偶尔失败**

脚本默认会重试。网络不稳定时可增加 `--retries 5`，或用 `--delay 1` 放慢请求。

## 进阶参数

```text
--input PATH             输入表
--column NAME            基因或关键词所在列
--sheet NAME_OR_INDEX    Excel 工作表名称或序号
--term VALUE             直接输入关键词，可重复使用
--query-template TEXT    自定义 PubMed 检索模板
--context TEXT           疾病或主题条件
--email EMAIL            NCBI 联系邮箱
--api-key KEY            可选的 NCBI API key
--output PATH            CSV、TSV 或 Excel 结果文件
--retries N              请求失败后的重试次数
--delay SECONDS          两次查询之间的等待时间
--checkpoint-every N     每完成多少次新查询保存一次
--force                  忽略旧结果，全部重新查询
```

完整参数可运行 `python query_pubmed_counts.py --help` 查看。请求频率和接口要求以 [NCBI E-utilities 官方说明](https://www.ncbi.nlm.nih.gov/books/NBK25497/)为准。
