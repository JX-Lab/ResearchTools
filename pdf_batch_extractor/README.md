# 结构化 PDF 批量提取工具

`extract_structured_pdf.py` 从原生文字型 PDF 中按阅读顺序提取文本，可生成 Markdown、逐条目结构表，并可按名称把指定字段回填到已有表格。工具支持单栏/双栏、多页 PDF、跨栏和跨文件条目，并允许用 JSON 配置版面和解析规则。

本工具不执行 OCR。扫描件、复杂表格、任意混排杂志和需要图文对应的 PDF 不属于当前支持范围。

## 安装

需要 Python 3.10 或更高版本。

```bash
cd pdf_batch_extractor
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## 快速使用

处理一个 PDF，并生成 Markdown、逐页结构表和 JSON 报告：

```bash
python extract_structured_pdf.py --input /path/to/report.pdf --columns auto --markdown-output report.md --records-output report.xlsx
```

默认配置会自动判断单栏或双栏，并把每个 PDF 页面作为一个 Markdown 小节。也可以传入目录，按自然顺序批量处理其中的 PDF：

```bash
python extract_structured_pdf.py --input /path/to/reports --pattern "report_*.pdf" --start-file report_51.pdf --markdown-output reports.md
```

## 回填已有表格

使用结构化条目配置时，可按明确列名匹配并将提取字段写入新文件。例如使用下文的 `custom.json`：

```bash
python extract_structured_pdf.py --input /path/to/reports --config custom.json --merge-input 项目清单.xlsx --merge-key-column 项目 --merge-field 摘要:项目摘要 --merge-output 项目清单_已回填.xlsx
```

`--merge-field` 可重复，例如同时回填摘要和负责人。未匹配行原值保持不变，空的提取值也不会覆盖已有内容。

名称规范化由 `entry.normalization` 配置；默认只做 Unicode 规范化和首尾空白清理。提取结果出现同名条目时，回填默认停止并报告歧义；可显式选择 `--duplicate-policy first|last|join`。

工具不会默认覆盖输入表。确需原地更新时使用 `--in-place`，脚本会先在同一目录生成带时间戳的备份。

## 通用文本模式

默认配置会自动判断单栏或双栏，并把每个 PDF 页面作为一个 Markdown 小节：

```bash
python extract_structured_pdf.py \
  --input /path/to/book.pdf \
  --columns auto \
  --pages '1-3,8,10-' \
  --markdown-output book.md
```

自动分栏属于启发式判断。版式已知时应使用 `--columns 1` 或 `--columns 2`；不在页面正中分栏时再指定 `--column-split 0.48` 等比例。

## 自定义 JSON 配置

`--config custom.json` 会递归覆盖默认配置。列表字段整体替换，不与内置列表合并。以下配置把通用模式改为按两行标题切分条目：

```json
{
  "layout": {
    "columns": "2",
    "top_margin_ratio": 0.05,
    "bottom_margin_ratio": 0.04
  },
  "entry": {
    "mode": "sequence",
    "title_sequence": [
      {"field": "display_name", "pattern": "(?P<value>项目\\S+)"},
      {"field": "code", "pattern": "(?P<value>REPORT-[A-Z]+-\\d+)"}
    ],
    "name_field": "display_name"
  },
  "markdown": {
    "emit_title_fields": ["code"]
  }
}
```

标题规则使用 Python 正则表达式并对整行匹配。命名捕获组 `value` 存在时，其内容作为字段值；否则使用整行。规则增加 `"remove_whitespace": true` 时会移除该标题字段中的排版空格。`entry.value_replacements` 可按标题字段配置精确纠错映射。`entry.mode` 可为 `page` 或 `sequence`。

`fields.capture_bracket_fields` 控制是否提取 `【字段】`；`fields.include` 非空时只保留列出的字段，`fields.exclude` 用于排除字段。

## 输出与检查

- Markdown：每个条目或页面一个标题，保持抽取后的正文行。
- CSV/TSV/XLSX：每个条目一行，包含标题字段、起止来源、正文以及检测到的 `【字段】`。
- JSON 报告：默认与第一个输出文件同目录，文件名以 `_report.json` 结尾。

报告包含选中文件和页数、无文字页、解析错误、条目数、重复规范化名称、字段出现次数以及表格匹配情况。先检查而不写文件可使用：

```bash
python extract_structured_pdf.py --input /path/to/report.pdf --dry-run
```

## 常用参数

```text
--input PATH                  PDF 文件或 PDF 目录
--pattern GLOB                目录文件模式，默认 *.pdf
--recursive                   递归查找 PDF
--start-file NAME             自然排序后的起始文件（包含）
--end-file NAME               自然排序后的结束文件（包含）
--pages RANGE                 每个 PDF 内的页码，如 1-3,5,8-
--config JSON                 覆盖默认配置的 JSON 文件
--columns auto|1|2            覆盖分栏模式
--column-split RATIO          双栏分割位置
--top-margin RATIO            忽略的顶部比例
--bottom-margin RATIO         忽略的底部比例
--markdown-output PATH        Markdown 输出
--records-output PATH         CSV/TSV/XLSX 条目表
--report-output PATH          JSON 报告
--strict                      遇到第一个 PDF/页面错误即停止
--dry-run                     只解析和显示摘要
```

完整参数以 `python extract_structured_pdf.py --help` 为准。
