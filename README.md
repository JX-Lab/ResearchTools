# 化合物批量下载与靶点预测工具

本目录包含两个相互独立、也可以串联使用的命令行工具：

1. `pubchem_downloader/`：按 CID、CAS、名称、SMILES、InChI、InChIKey、分子式或外部数据库标识符查询 PubChem，导出结构/性质表并下载 SDF。
2. `swiss_target_prediction/`：从 SMI、常见表格或命令行读取 SMILES，通过本机 Edge/Chrome 批量运行 SwissTargetPrediction，并保存逐分子 CSV 和断点进度。

两个子目录各自包含脚本、中文说明和依赖文件。建议为两个工具分别建立虚拟环境，以避免浏览器自动化依赖影响只使用 PubChem 的环境。

典型串联方式：先用 PubChem 工具生成结果表，再将其中的 `pubchem_isomeric_smiles` 列作为 SwissTargetPrediction 的 `--smiles-column` 输入。具体命令见各子目录的 `README.md`。
