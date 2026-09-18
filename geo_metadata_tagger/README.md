# GEO 数据集搜索与元数据标注

这个工具用于从 GEO 中搜索候选研究，并自动整理 GSE/GSM 的物种、疾病、组织、技术和实验分组信息，方便后续筛选和下载。

它的目标不是直接替你判断“哪个数据集最好”，而是先把 GEO 的原始元数据整理成结构化标签，并保留判断证据。

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

搜索结果会保存为 TSV，并包含候选 GSE 的编号、标题和摘要。

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

准备一个 YAML，例如：

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

## 自动标注什么

目前主要整理：

- **organism**：物种。
- **disease**：疾病或健康状态。
- **tissue**：组织。
- **technology**：RNA-seq、Microarray、scRNA-seq、snRNA-seq、Spatial。
- **study_type**：bulk、scRNA、snRNA、spatial。
- **group**：如 COPD、Healthy、Treatment。
- **matrix_available**：是否从 GEO 的补充文件元数据中找到明显的表达矩阵线索。

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

## 工作流程

这个工具对应下面的流程：

```text
人工输入搜索词
      ↓
GEO 搜索
      ↓
候选 GSE
      ↓
读取 GSM/GSE 元数据
      ↓
自动标签
      ↓
value + confidence + evidence
      ↓
人工/配置筛选
      ↓
待下载候选
      ↓
后续独立下载工具
```

当前版本暂时不下载表达矩阵。这样搜索、判断和下载三个环节可以独立维护。

## 注意事项

自动标签必须人工抽查。特别是一个 GSE 同时包含多个疾病、组织或技术时，不应只根据 GSE 标题判断；应该检查 GSM/sample 层面的标签和 evidence。

另外，`study_type=bulk` 对普通 RNA-seq 是规则推断，并不等于 GEO 原始字段明确写了“bulk”。正式分析前应检查样本描述和实验设计。
