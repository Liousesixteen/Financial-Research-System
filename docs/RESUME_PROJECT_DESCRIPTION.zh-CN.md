# Financial Research System：简历项目描述

以下内容按照当前仓库已经实现的功能编写。简历中的“负责”应替换成你实际完成的工作；如果项目是团队协作，请把“独立完成”改成“参与/负责”。

## 推荐版本：AI Agent / 后端方向

**Financial Research System｜多 Agent 金融研报生成与知识库系统**  
项目类型：AI Agent / RAG / 金融数据分析｜技术栈：Python、FastAPI、asyncio、OpenAI-compatible API、React、Vite、pandas、NumPy、Matplotlib、SQLite FTS5、Qdrant、pytest

- 面向股票、公司、行业和宏观研究场景，设计并实现“数据采集—数据分析—报告生成”的多 Agent 研究流水线，支持联网搜索、金融数据 API、Python 数据分析、图表生成以及 Markdown/DOCX/PDF 报告导出。
- 基于自定义 `BaseAgent` 构建 Agent Loop、工具注册、动作解析、异步执行和 Checkpoint 恢复机制；通过 `DataCollector`、`DeepSearchAgent`、`DataAnalyzer`、`ReportGenerator` 分工协作，并使用共享 `VariableMemory` 传递数据、日志、依赖和任务状态。
- 实现 PDF/DOCX/Markdown/TXT 知识库：使用 SQLite + FTS5 作为权威存储，结合 NumPy 本地向量检索和可选 Qdrant，支持文档去重、版本管理、元数据过滤、混合检索、证据快照和稳定引用。
- 将知识库检索接入 Agent 上下文，在研报生成过程中保留 `[KB:evidence_id]` 证据编号，并在后处理阶段解析为参考文献和审计 JSON，降低资料更新、删除或润色导致的引用漂移。
- 使用受限 Python 执行器支撑 LLM 生成分析代码和图表：限制高风险模块、限制工作目录外写入、设置执行超时，并通过 `AsyncBridge` 在同步代码执行环境中安全调用异步工具。
- 使用 FastAPI 提供配置、任务、执行状态、报告预览/下载和知识库 REST API，通过 WebSocket 推送 Agent 日志；前端使用 React + Ant Design 实现研究配置、运行监控、报告查看和知识库管理。
- 增加 pytest/pytest-asyncio/Hypothesis 测试，覆盖知识库解析、去重、检索、过滤、证据快照、Agent 接入、恢复逻辑和沙箱行为；当前仓库知识库/接入测试及选定回归测试累计通过 101 项。

## 一句话版本

设计并实现一个基于自定义多 Agent Loop 的金融深度研究系统，将金融数据 API、联网搜索、Python 数据分析、VLM 图表审查和 RAG 知识库串成可恢复的异步研报生成流水线，并通过 FastAPI + React 提供可视化操作和实时日志。

## 适合一页简历的精简版本

- 构建 Python 异步多 Agent 金融研究流水线，完成数据采集、深度搜索、数据分析、图表生成、研报撰写和 DOCX/PDF 导出。
- 设计共享 VariableMemory、工具注册和优先级调度机制，实现 Agent 依赖管理、并发执行、Checkpoint 保存与断点恢复。
- 实现基于 SQLite FTS5 + 本地向量/Qdrant 的混合检索知识库，支持 PDF/DOCX/Markdown/TXT 入库、元数据过滤、证据快照和可追溯引用。
- 使用 FastAPI、WebSocket、React、Ant Design 完成配置管理、任务控制、执行日志流、报告预览和知识库管理界面。
- 使用受限异步 Python 执行器处理 LLM 生成代码，结合模块/路径/超时限制，并通过 pytest 完成核心流程测试。

## 偏 Agent Engineer 的版本

负责构建金融研究场景的 Agent 基础设施：实现带有异步 Tool Calling、动作解析、共享状态、依赖图、Checkpoint 恢复和代码执行能力的自定义 `BaseAgent`；设计 DataCollector、DeepSearchAgent、DataAnalyzer、ReportGenerator 四类 Agent 的协作协议；将知识库检索结果注入每轮 Agent 上下文，并通过证据快照和稳定 ID 保证报告引用可追溯；使用 FastAPI/WebSocket 暴露执行控制和实时日志。

## 偏后端 / RAG 的版本

负责实现知识库服务和 Agent RAG 接入：以 SQLite/FTS5 保存文档、切片、任务和证据状态，以内容哈希和解析器版本实现幂等入库与版本隔离；支持 PDF/DOCX/Markdown/TXT 解析、页面/章节定位、关键词与 Embedding 混合召回、Qdrant 可选后端、截止日期和实体过滤；在研究启动时固定证据快照，输出 `[KB:evidence_id]` 引用，并在报告后处理中生成引用审计文件。

## 面试中可以量化的事实

- 支持 PDF、DOCX、Markdown、TXT 四种知识库文档格式。
- 单文件上传限制为 50 MB。
- 知识库检索 `top_k` 支持 1–30，默认 8。
- 代码执行器默认超时时间为 120 秒。
- Agent 默认按采集、分析、报告三个优先级阶段执行。
- Qdrant 为可选向量后端，默认使用 SQLite FTS5 + 本地向量检索。
- 当前代码测试覆盖知识库、Agent 接入、解析、检索、恢复和沙箱等模块。

不要在没有实际数据支撑时写“准确率提升 XX%”“节省 XX% 成本”“达到生产级 QPS”或“完全消除幻觉”。这些指标当前仓库没有经过完整线上基准验证。
