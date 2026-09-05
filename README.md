# 科研数据处理工具

本目录包含三个相互独立的命令行工具：

1. `pubchem_downloader/`：按 CID、CAS、名称、SMILES、InChI、InChIKey、分子式或外部数据库标识符查询 PubChem，导出结构/性质表并下载 SDF。
2. `swiss_target_prediction/`：从 SMI、常见表格或命令行读取 SMILES，通过本机 Edge/Chrome 批量运行 SwissTargetPrediction，并保存逐分子 CSV 和断点进度。
3. `pdf_batch_extractor/`：从原生文字型单栏/双栏 PDF 批量提取 Markdown 和结构化条目，支持跨页条目、可配置识别规则及按名称回填表格。

各子目录包含独立脚本、中文说明和依赖文件。建议分别建立虚拟环境，避免不同工具的依赖互相影响。

化合物工具的典型串联方式：先用 PubChem 工具生成结果表，再将其中的 `pubchem_isomeric_smiles` 列作为 SwissTargetPrediction 的 `--smiles-column` 输入。具体命令见各子目录的 `README.md`。
