# GEO 数据搜索、标注、筛选与下载

这个工具把 GEO 公共数据获取整合成一条完整流程：先根据需求搜索候选 GSE，再解析 GSE/GSM 元数据并自动打标签，按条件筛选，最后直接从 GEO 下载可用的处理后数据。

## 工作流程

```text
人工输入搜索词 / 研究需求
          ↓
       GEO 搜索
          ↓
      候选 GSE
          ↓
   GSE / GSM 元数据解析
          ↓
自动标签 + confidence + evidence
          ↓
      条件筛选
          ↓
      最终候选 GSE
          ↓
     GEO 下载页面
          ↓
识别 Series Matrix / 作者处理后矩阵 / NCBI RNA-seq counts
          ↓
      下载 + manifest
          ↓
    后续表达矩阵分析
```

搜索、标注、筛选和下载现在属于**同一个工具**，不再需要单独安装 `geo_downloader`。

## 安装

```bash
cd geo_metadata_tagger
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## 最快开始

### 1. 搜索 GEO

输入普通搜索词：

```bash
python geo_tagger.py search "COPD lung human" --max-results 50 --output candidates.tsv
```

### 2. 标注一个 GSE

```bash
python geo_tagger.py annotate GSE57148 --out output/GSE57148
```

输出：

```text
output/GSE57148/
├── study.tsv
├── sample.tsv
└── geo_cache/
```

其中：

- `study.tsv`：GSE 级别，一行一个研究。
- `sample.tsv`：GSM 级别，一行一个样本。

### 3. 按需求筛选

例如 COPD 患者 vs 健康人、肺组织、bulk RNA-seq：

```yaml
organism: Homo sapiens
disease:
  include: [COPD]
tissue:
  include: [lung]
study_type:
  include: [bulk]
technology:
  include: [RNA-seq]
groups:
  require: [COPD, Healthy]
```

然后：

```bash
python geo_tagger.py filter \
  --input output/GSE57148/sample.tsv \
  --config examples/filter.yaml \
  --output filtered_samples.tsv
```

### 4. 下载最终 GSE

直接下载一个已经确认的 GSE：

```bash
python geo_tagger.py download \
  --gse GSE57148 \
  --output data
```

默认 `auto` 会读取 GSE 的官方 Download data 页面，尽量下载：

1. Series Matrix；
2. 如果存在，作者提交的处理后表达矩阵；
3. 如果没有作者表达矩阵且该研究有 NCBI RNA-seq raw counts，则下载 NCBI raw counts。

例如 GSE57148 会识别到 Series Matrix 和作者提交的 `GSE57148_COPD_FPKM_Normalized.txt.gz`。NCBI-generated 的 FPKM/TPM 可以显式选择，不会在默认模式下把多套替代表达矩阵全部下载下来。

### 5. 批量下载

输入一个包含 `gse` 列的 TSV：

```text
gse
GSE57148
GSE8581
```

运行：

```bash
python geo_tagger.py download-from-list \
  --input selected_gse.tsv \
  --output data
```

也可以指定数据类型：

```bash
python geo_tagger.py download --gse GSE57148 --type ncbi_raw_counts --output data
python geo_tagger.py download --gse GSE57148 --type ncbi_fpkm --output data
python geo_tagger.py download --gse GSE57148 --type ncbi_tpm --output data
```

可选类型：

- `auto`：默认，下载 Series Matrix + 作者处理后表达矩阵；无作者表达矩阵时再尝试 NCBI raw counts。
- `series_matrix`：只下载 Series Matrix。
- `submitter`：只下载作者提交的表达相关 supplementary files。
- `ncbi_raw_counts`：只下载 NCBI-generated raw counts。
- `ncbi_fpkm`：只下载 NCBI-generated FPKM。
- `ncbi_tpm`：只下载 NCBI-generated TPM。
- `all`：下载页面上识别到的全部上述类型。

## 自动标注什么

目前主要整理：

- **organism**：物种。
- **disease**：疾病或健康状态。
- **tissue**：组织。
- **technology**：RNA-seq、Microarray、scRNA-seq、snRNA-seq、Spatial。
- **study_type**：bulk、scRNA、snRNA、spatial。
- **group**：如 COPD、Healthy、Treatment。
- **matrix_available**：是否从 GEO 元数据中找到明显的表达矩阵线索。

GSE 和 GSM 两个层级都会保留标签。因为一个 GSE 可能同时包含多个实验组，所以最终筛选时以 GSM 层面的信息更重要。

## confidence 和 evidence

每个自动识别的标签都尽量保留：

- **value**：识别出的标准标签。
- **confidence**：证据强度评分，不是统计学概率。
- **evidence**：触发判断的原始字段、文本和匹配词。
- **source**：`auto`；以后人工修正时可以保留人工来源。

confidence 描述的是**证据强弱**，不是“某个疾病本身有多容易识别”。因此不同疾病可以使用同一套评分规则。

没有找到证据时：

```text
value = unknown
confidence = 0
evidence = []
```

不会为了得到一个数字而强行猜测。

## 规则怎么修改

`rules/` 中的 YAML 可以直接编辑：

- `diseases.yaml`：疾病及同义词。
- `tissues.yaml`：组织及同义词。
- `technologies.yaml`：测序/检测技术关键词。
- `groups.yaml`：实验组关键词。
- `confidence.yaml`：不同证据来源的默认权重。

这些规则和 Python 主程序分开，因此以后换成其他疾病、组织或研究主题时，不需要重新写核心程序。

## 下载说明

下载模块不是简单拼一个固定文件名，而是先读取 GSE 的官方 Download data 页面，再识别页面中实际存在的下载项。这样可以处理不同 GEO Series 的文件组织差异。

GEO 的 RNA-seq processed data 可以包括 raw counts、FPKM、TPM 等定量矩阵；NCBI 也提供自动生成的 RNA-seq counts 下载入口。正式分析前仍应检查基因 ID、基因组版本、样本名、表达值类型和处理流程。

程序默认不下载 SRA/FASTQ 原始测序数据，因为本工具的目标是先获取可用于表达分析的 processed data。需要原始测序数据时，再单独处理 SRA。

## 注意事项

自动标签必须人工抽查。特别是一个 GSE 同时包含多个疾病、组织或技术时，不应只根据 GSE 标题判断；应该检查 GSM/sample 层面的标签和 evidence。

另外，`study_type=bulk` 对普通 RNA-seq 是规则推断，并不等于 GEO 原始字段明确写了“bulk”。正式分析前应检查样本描述和实验设计。
