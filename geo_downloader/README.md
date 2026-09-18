# GEO 数据下载

这个工具接在 `geo_metadata_tagger/` 后面使用：先搜索和筛选 GEO 数据集，再把最终保留的 GSE 下载为可用于后续分析的表达矩阵或 GEO 补充数据。

## 工作流程

```text
geo_metadata_tagger
        ↓
搜索候选 GSE
        ↓
自动标注 GSE/GSM
        ↓
按疾病 / 组织 / bulk / 技术 / 分组筛选
        ↓
得到最终 GSE
        ↓
geo_downloader
        ↓
优先下载 Series Matrix
        ↓
没有 Series Matrix 时检查 GEO supplementary files
        ↓
记录下载文件、来源和状态
        ↓
后续表达矩阵分析
```

这个工具只负责**下载**，不负责判断哪个数据集适合分析。

## 安装

```bash
cd geo_downloader
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## 最快开始

直接下载一个已经确认的 GSE：

```bash
python geo_downloader.py download \
  --gse GSE57148 \
  --output data/GSE57148
```

程序会优先检查：

1. GEO Series Matrix；
2. 如果没有可用的 Series Matrix，再检查 GSE 的 supplementary files；
3. 下载成功的文件写入输出目录；
4. 同时生成 `manifest.tsv`，记录 GSE、文件类型、URL、文件名和状态。

## 接在筛选工具后面

如果前一步已经得到 `sample.tsv`：

```bash
python geo_downloader.py download-from-samples \
  --input output/GSE57148/sample.tsv \
  --output data/
```

程序会按 `gse` 去重，然后逐个下载。

如果只想下载明确筛选出的 GSE，也可以准备一个 TSV：

```text
gse
GSE57148
GSE8581
```

然后：

```bash
python geo_downloader.py download-from-gse-list \
  --input selected_gse.tsv \
  --output data/
```

## 下载什么

对于 GEO 数据，优先级是：

### 1. Series Matrix

这是 GEO 官方提供的系列级处理数据入口，适合已经完成预处理、可以直接进入表达分析的情况。

### 2. Supplementary files

如果没有可用的 Series Matrix，程序会读取 GEO 的 supplementary file 列表，并优先选择看起来像表达矩阵的文件，例如：

- `matrix`
- `expression`
- `counts`
- `FPKM`
- `TPM`
- `normalized`

不会默认下载 SRA 原始 FASTQ。

## 结果

例如：

```text
data/
└── GSE57148/
    ├── GSE57148_series_matrix.txt.gz
    └── manifest.tsv
```

`manifest.tsv` 会保留：

- `gse`
- `file_type`
- `file_name`
- `url`
- `status`
- `message`

## 为什么默认不下载 SRA

GEO 的 RNA-seq 数据通常同时存在 processed data 和 SRA raw data。这个工具针对的是“先拿到可以进行表达分析的公共 bulk 转录组数据”，因此默认优先下载处理后的表达矩阵。

如果后续需要 FASTQ/raw reads，再单独增加 SRA 下载模块，避免第一次运行就把大量原始测序数据全部拉下来。

## 注意事项

下载前仍应检查 `geo_metadata_tagger` 的 `sample.tsv`，确认疾病、组织、技术和分组。

尤其是 bulk RNA-seq：

- `RNA-seq` 不自动等于 bulk；
- 一个 GSE 可能同时包含多个实验条件；
- Series Matrix 或 supplementary file 是否真正适合后续分析，需要检查文件中的行列含义、基因 ID、样本名和表达值类型。

程序会尽量保留下载来源，不会把“下载成功”解释成“数据适合分析”。
