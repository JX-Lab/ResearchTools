# GEO metadata tagger

用于把 GEO 的 GSE/GSM 元数据整理成可筛选的标签，服务于“先搜索 → 自动判断 → 人工复核/筛选 → 再下载表达矩阵”的工作流。

## 目前做什么

第一版**只处理元数据，不下载表达矩阵**。

自动整理：

- organism：物种
- disease：疾病/健康状态
- tissue：组织
- technology：RNA-seq、Microarray、scRNA-seq、snRNA-seq、Spatial
- study_type：bulk / scRNA / snRNA / spatial
- group：COPD、Healthy、Treatment 等
- confidence：规则置信度
- evidence：触发标签的原始字段、文本和匹配词

输出：

- `study.tsv`：一个 GSE 一行
- `sample.tsv`：一个 GSM 一行

## 为什么保留 evidence

自动标签不能只给一个“结论”。例如：

`disease = COPD`

还应该能看到它是从哪个 GEO 字段、哪段原文、哪个关键词判断出来的。

`confidence` 是规则系统对证据强弱的评分，不是统计学概率。

## 安装

```bash
cd geo_metadata_tagger
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## 最快开始

对一个已经找到的 GSE：

```bash
python geo_tagger.py annotate GSE57148 --out output/GSE57148
```

得到：

```text
output/GSE57148/
├── study.tsv
├── sample.tsv
└── geo_cache/
```

## 当前规则

`rules/` 中的 YAML 是可编辑词表：

- `diseases.yaml`
- `tissues.yaml`
- `technologies.yaml`
- `groups.yaml`

第一版不把疾病、组织和技术全部写死在 Python 代码里。

## 下一步

1. GEO 搜索：输入自然语言搜索词，获得候选 GSE。
2. 批量元数据解析。
3. 更完整的结构化字段解析。
4. 人工过滤配置。
5. 输出待下载 manifest。
6. 独立的表达矩阵/原始数据下载模块。

### 注意

自动标注必须人工抽查。尤其是一个 GSE 同时包含多个疾病、组织或技术时，不能只看 GSE 标题；应以 GSM/sample 层面的标签为主要筛选依据。