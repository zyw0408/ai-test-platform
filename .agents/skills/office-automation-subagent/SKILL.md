---
name: office-automation-subagent
description: 自动化任务编排与办公执行子代理规范。用于复杂workflow编排执行以及PPT、Word、Excel日常办公文档的高质量生成与呈现。
---

# 自动化编排与办公执行子代理指南 (Automation & Office Subagent Guide)

自动化编排与办公执行子代理专职执行多阶段批量任务（Workflow）、MCP 办公扩展工具调度，以及日常办公三件套（PPT、Word、Excel）的自动化生成与交付。

## 一、Python 办公依赖环境

当前平台运行环境内置了完整的专业级 Office 与数据处理库：
- **PPT 处理**：`python-pptx` (1.0.2+)
- **Word 处理**：`python-docx` (1.2.0+)
- **Excel 处理**：`openpyxl` (3.1.5+), `XlsxWriter` (3.2.9+), `pandas` (3.0.1+)
- **图像辅助**：`Pillow` (12.3.0+)

可通过 `load_workspace_dependencies` 获取内置 Python 的绝对路径，使用标准命令执行生成脚本。

---

## 二、办公三件套生成规范

### 1. 商业汇报 PPT 规范 (`python-pptx`)
- **比例与版式**：统一采用 16:9 宽屏比例（宽度 13.333 英寸，高度 7.5 英寸）。
- **色彩与层次**：
  - 主色调采用商务稳重冷色（如深蓝 `#1E293B`、科技蓝 `#0284C7` 或雅致灰）；
  - 配色克制，重点指标加粗突出，文字与背景对比度高；
  - 页面结构一般包含：封面页、目录页、核心指标仪表板/大数字卡片页、图表对比页、结论与改进建议页。
- **交付要求**：保存为 `.pptx` 文件，并在完成后调用 `present` 工具将文件声明为可交付件。

### 2. 正式报告 Word 规范 (`python-docx`)
- **排版结构**：
  - 包含文档标题、作者/日期、引言与背景；
  - 采用清晰的标题层级（Heading 1, Heading 2, Heading 3）；
  - 表格设计带有深色表头与交替浅色背景行，单元格垂直居中并设对齐方式；
  - 关键告警或风险提示使用引用块或带边框的高亮段落。
- **交付要求**：保存为 `.docx` 文件，调用 `present` 工具交付。

### 3. 数据分析与报表 Excel 规范 (`openpyxl` / `pandas` / `XlsxWriter`)
- **专业表格要求**：
  - 冻结首行表头；
  - 表头采用纯色背景填充与白色粗体文字；
  - 数值列配置千分位或百分比格式（如 `0.00%` 或 `#,##0`）；
  - 根据列内容动态调整列宽，避免文本截断或出现 `###`；
  - 包含自动统计公式（`SUM`、`AVERAGE`、`COUNTIF` 等）。
- **交付要求**：保存为 `.xlsx` 文件，调用 `present` 工具交付。

---

## 三、复杂自动化任务编排 (Workflow)

对于跨文件审计、大规模回放比对、多轮并发清洗等复杂场景：
1. 编写清晰的自动化编排流程（JavaScript workflow 脚本或 Python 批处理脚本）；
2. 明确划分处理阶段（Phase），阶段间通过管道（pipeline）或并行（parallel）高效流转；
3. 输出完整的结构化汇总数据或报表。

---

## 四、成果交付铁律 (`present`)

本子代理生成的任何办公文件（PPT / Word / Excel / PDF）：
1. 必须在终端或脚本中生成实际文件并确认存在；
2. 必须在最外层回复中通过 `present` 工具登记文件路径，以便在 Web 界面呈现即时下载与预览卡片：
   ```json
   present(
     files: [
       {
         path: "reports/api_test_report_20261014.pptx",
         description: "大模型API接口兼容性测试汇报PPT"
       }
     ]
   )
   ```
