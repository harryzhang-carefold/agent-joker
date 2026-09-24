# 04-analysis — 系统分析（史强 / shiqiang）

现有系统的逆向分析文档输出目录。由系统分析师史强维护。

## 标准文档清单

| 文件 | 内容 |
|---|---|
| ANALYSIS-README.md | 系统概况 / 文档索引 / 差异清单 / 分析范围声明 |
| ANALYSIS-功能流程.md | 模块清单、功能点、业务流程（mermaid flowchart） |
| ANALYSIS-架构设计.md | 技术栈 / 分层 / 模块 / 数据流 / 部署 / 权限（mermaid 架构图） |
| ANALYSIS-数据库设计.md | 表结构 / 字段 / 关系 / 数据量（mermaid erDiagram） |
| ANALYSIS-接口设计.md | REST 接口清单（方法/路径/入参/出参/鉴权） |
| ANALYSIS-页面功能布局.md | 逐页布局、组件、数据绑定、角色可见性（附截图） |

要求：结论必须带证据（文件:行号 / API 响应 / 页面 URL）；推断标注"推测"；
来源冲突时按 运行系统 > 代码 > 文档 > 截图 裁定并记入差异清单。
