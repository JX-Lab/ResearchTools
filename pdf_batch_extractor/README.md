# 从 PDF 批量提取文字和表格

这个工具可以读取一个或一批 PDF，把其中的文字整理成 Markdown 文档或 Excel/CSV 表格。它还可以按名称把提取结果补回已有的项目清单。

最适合处理排版规律的报告、说明书、条目集和单栏/双栏文档。

## 先判断 PDF 能不能处理

打开 PDF，尝试用鼠标选中并复制一段文字：

- 能正常选中和复制：通常可以处理。
- 整页像一张图片，无法选中文字：这是扫描件，本工具不能直接处理，需要先用 OCR 软件识别文字。

复杂表格、文字绕图片排版、频繁变化的多栏版面，也可能需要人工整理。

## 最快开始

从一个 PDF 生成 Markdown 和 Excel：

```bash
python extract_structured_pdf.py \
  --input report.pdf \
  --markdown-output report.md \
  --records-output report.xlsx
```

脚本默认自动判断页面是单栏还是双栏。运行结束后：

- `report.md` 适合阅读、搜索和继续编辑。
- `report.xlsx` 每页或每个识别出的条目占一行。
- 同目录下还会生成一个 JSON 报告，记录处理页数、错误和匹配情况。

## 安装

需要 Python 3.10 或更高版本。

```bash
cd pdf_batch_extractor
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## 处理多个 PDF

把同类 PDF 放在一个目录中：

```bash
python extract_structured_pdf.py \
  --input reports \
  --pattern '*.pdf' \
  --markdown-output all_reports.md \
  --records-output all_reports.xlsx
```

只处理文件名从 `report_51.pdf` 开始的一段文件：

```bash
python extract_structured_pdf.py \
  --input reports \
  --start-file report_51.pdf \
  --end-file report_80.pdf \
  --markdown-output selected_reports.md
```

子目录中也有 PDF 时，加上 `--recursive`。

## 只处理指定页

```bash
python extract_structured_pdf.py \
  --input book.pdf \
  --pages '1-3,8,10-' \
  --markdown-output book.md
```

`1-3,8,10-` 表示第 1 到 3 页、第 8 页，以及第 10 页到最后一页。

如果自动分栏顺序不正确，可以明确指定：

- `--columns 1`：单栏。
- `--columns 2`：双栏。
- `--columns auto`：自动判断。

## 先检查，不生成结果

不确定版面是否能正确识别时，先运行：

```bash
python extract_structured_pdf.py --input report.pdf --dry-run
```

这会显示识别摘要，但不会写出正式结果文件。

## 按条目提取

默认情况下，工具把每一页当成一个条目。如果文档由重复的“名称 + 编号 + 正文”组成，可以写一个 JSON 配置，告诉工具如何识别每个条目的开头。

例如 `custom.json`：

```json
{
  "layout": {
    "columns": "2"
  },
  "entry": {
    "mode": "sequence",
    "title_sequence": [
      {"field": "display_name", "pattern": "(?P<value>项目\\S+)"},
      {"field": "code", "pattern": "(?P<value>REPORT-[A-Z]+-\\d+)"}
    ],
    "name_field": "display_name"
  }
}
```

然后运行：

```bash
python extract_structured_pdf.py \
  --input reports \
  --config custom.json \
  --records-output projects.xlsx
```

这里的 `pattern` 是文字匹配规则。只有不同条目的标题格式比较固定时，才需要使用这个进阶功能。

如果正文使用 `【摘要】`、`【负责人】` 这类标记，工具会自动把它们识别为表格字段。需要更复杂的规则时，再查看脚本中的默认配置 `GENERIC_PROFILE`。

## 把结果补回已有 Excel

假设提取结果中有项目名称和摘要，而原来的 `项目清单.xlsx` 也有“项目”列，可以这样生成补充后的新表：

```bash
python extract_structured_pdf.py \
  --input reports \
  --config custom.json \
  --merge-input 项目清单.xlsx \
  --merge-key-column 项目 \
  --merge-field 摘要:项目摘要 \
  --merge-output 项目清单_已回填.xlsx
```

`摘要:项目摘要` 表示：把 PDF 中识别出的“摘要”，写到原表的“项目摘要”列。

工具默认生成新文件，不覆盖原表。使用 `--in-place` 原地更新时，也会先建立带时间的备份。遇到重名条目时默认停止，避免把内容填错；确认处理方式后可用 `--duplicate-policy first|last|join`。

## 常见问题

**提取出来的阅读顺序不对**

先尝试 `--columns 1` 或 `--columns 2`。如果双栏中线不在正中间，可以用 `--column-split 0.48` 调整分割位置。

**页眉、页脚混进正文**

使用 `--top-margin` 和 `--bottom-margin` 忽略页面顶部或底部的一部分，例如 `--top-margin 0.05`。

**有些页没有文字**

检查 JSON 报告中的无文字页。如果这些页面是扫描图，需要先做 OCR。

**输出表里一个条目被拆成多段**

通常是标题匹配规则过宽或过窄。先对少量页面使用 `--dry-run`，再调整 JSON 配置。

## 常用参数

```text
--input PATH             一个 PDF 或包含 PDF 的目录
--pattern GLOB           目录中要处理的文件名规则
--recursive              同时查找子目录
--start-file NAME        从哪个文件开始
--end-file NAME          到哪个文件结束
--pages RANGE            页码范围，例如 1-3,5,8-
--columns auto|1|2       自动、单栏或双栏
--config JSON            条目识别配置
--markdown-output PATH   Markdown 保存位置
--records-output PATH    CSV、TSV 或 Excel 保存位置
--report-output PATH     处理报告保存位置
--dry-run                只检查，不生成正式结果
--strict                 遇到第一个错误就停止
```

完整参数可运行 `python extract_structured_pdf.py --help` 查看。
