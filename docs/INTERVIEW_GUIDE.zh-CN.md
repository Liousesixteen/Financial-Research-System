# Financial Research System：项目完整解析与面试讲解稿

这份文档按照当前代码中的真实实现编写。面试时应把“我负责”替换成自己真实完成的模块，不要把尚未实现的能力描述成已经上线。

## 一、30 秒项目介绍

我做的是一个金融深度研究系统。用户输入公司、股票、行业或宏观研究目标后，系统通过多个专门 Agent 自动完成资料采集、联网搜索、数据分析、图表生成和研报撰写，最后输出 Markdown、DOCX 或 PDF。系统的核心是一个自定义 Agent Loop：Agent 可以调用金融数据工具、搜索工具和 Python 代码执行器，并把结果写入共享 VariableMemory。后来我又接入了一个 RAG 知识库，支持 PDF、DOCX、Markdown、TXT 入库、混合检索、证据快照和稳定引用，让研报中的结论可以回溯到具体文档、页面或章节。

## 二、两分钟项目介绍

这个项目解决的是金融研究中资料分散、分析过程重复、报告格式不统一和结论难以追溯的问题。系统入口可以是命令行，也可以是 FastAPI + React 的 Web 界面。

执行时，`run_report.py` 先读取 YAML/JSON 配置和环境变量，创建共享的 `Memory`，然后根据研究目标生成采集任务和分析任务。任务被分为三个优先级：第一阶段由 `DataCollector` 获取股票、财务、宏观、行业数据，并通过 `DeepSearchAgent` 搜索和抓取公开资料；第二阶段由 `DataAnalyzer` 读取 Memory 中的数据，使用 pandas、NumPy 和受限 Python 执行器计算指标、生成图表，并可调用 VLM 检查图表；第三阶段由 `ReportGenerator` 先生成大纲，再按章节写作，最后统一润色、补充摘要和公司基本面、解析引用并导出报告。

每个 Agent 都继承自 `BaseAgent`。模型返回动作标签后，BaseAgent 解析动作、调用工具或执行代码，把结果追加到对话历史和 Memory，并在每轮保存 Checkpoint。这样任务中断后可以从 Agent 的 `latest.pkl` 和代码执行器状态恢复，而不是从头重新调用所有接口。

知识库部分以 SQLite 和 FTS5 为权威存储，保留文档、切片、元数据、任务状态和证据；如果配置 Embedding，可以使用本地 NumPy 向量检索或 Qdrant。研究开始时系统固定一个证据快照，Agent 每次检索返回带稳定 ID 的 `[KB:evidence_id]`，报告润色和后处理都保留并解析这些 ID，最终生成参考文献和知识库审计 JSON。

## 三、系统要解决的具体问题

传统金融研究流程通常有四个痛点：

1. 数据源多且格式不统一，需要分别调用行情、财务、宏观和网页来源。
2. 研究任务需要先收集资料，再分析数据，最后写报告，单个大模型很容易混淆阶段和上下文。
3. LLM 生成的数字和结论必须能够追溯到来源，普通 RAG 只返回文本片段，资料删除或更新后还可能影响历史任务。
4. 数据分析需要运行 Python 代码和生成图表，必须限制执行范围，并保留中间状态以便失败恢复。

因此项目的目标不是只做一个聊天机器人，而是把“计划、工具、状态、分析、写作和证据”组织成一条可以恢复的研究流水线。

## 四、总体架构

```text
React + Ant Design
        │ REST / WebSocket
        ▼
FastAPI Demo Backend / CLI run_report.py
        │
        ▼
Priority Orchestrator
  ├─ Priority 1: DataCollector × N
  │     ├─ Financial / Macro / Industry Tools
  │     └─ DeepSearchAgent
  ├─ Priority 2: DataAnalyzer × N
  │     ├─ pandas / NumPy
  │     ├─ AsyncCodeExecutor
  │     └─ VLM Chart Critique
  └─ Priority 3: ReportGenerator
        ├─ Outline
        ├─ Section Drafting
        ├─ Polish / Abstract / Cover
        ├─ Citation Resolution
        └─ Markdown / DOCX / PDF

Shared VariableMemory
  ├─ collected data
  ├─ analysis results
  ├─ logs and dependencies
  ├─ generated tasks
  ├─ checkpoints
  └─ knowledge evidence snapshot

Knowledge Base
  ├─ SQLite metadata and originals
  ├─ SQLite FTS5 lexical index
  ├─ NumPy local vectors
  └─ Optional Qdrant vectors
```

核心文件对应关系：

- Agent 基类：[src/agents/base_agent.py](../src/agents/base_agent.py)
- 任务调度：[run_report.py](../run_report.py)
- 共享状态：[src/memory/variable_memory.py](../src/memory/variable_memory.py)
- 工具系统：[src/tools/base.py](../src/tools/base.py) 和 [src/tools/__init__.py](../src/tools/__init__.py)
- LLM 封装：[src/utils/llm.py](../src/utils/llm.py)
- 代码执行器：[src/utils/code_executor_async.py](../src/utils/code_executor_async.py)
- 知识库服务：[src/knowledge/service.py](../src/knowledge/service.py)
- RAG 运行时：[src/knowledge/runtime.py](../src/knowledge/runtime.py)
- API：[src/knowledge/api.py](../src/knowledge/api.py) 和 [demo/backend/app.py](../demo/backend/app.py)

## 五、从用户输入到最终报告的完整流程

### 1. 加载配置

`Config` 先加载 `src/config/default_config.yaml`，再合并用户 YAML/JSON 配置，最后解析 `${ENV_VAR}` 环境变量。配置内容包括研究目标、股票代码、目标类型、输出目录、LLM/VLM/Embedding 模型、速率限制和知识库设置。

系统通常使用三个模型角色：

- DS/LLM：任务规划、数据采集、数据分析和报告写作。
- VLM：检查生成的图表，生成图表标题和说明。
- Embedding：知识库切片和查询向量化。

项目通过 OpenAI Python SDK 调用 OpenAI-compatible 接口，因此实际可以接入不同模型服务，模型名称和 URL 不写死在业务代码中。

### 2. 创建 Memory 和任务

`Memory` 保存以下状态：

- `data`：`ToolResult`、搜索结果、财务数据和分析结果。
- `log`：每次工具调用和 Agent 调用的输入、输出及错误。
- `dependency`：Agent 与工具之间的依赖关系。
- `task_mapping`：任务、Agent 类、输入参数、Agent ID 和优先级。
- `generated_collect_tasks` / `generated_analysis_tasks`：模型补充生成的任务。
- `knowledge_state`：知识库配置签名、证据快照、查询结果和证据表。

系统把配置中的固定任务和模型生成的任务合并，并去重。每个任务通过 `get_or_create_agent` 创建或复用对应 Agent，并记录到 `task_mapping`。

### 3. 按优先级调度

调度器先执行所有优先级为 1 的采集任务，全部结束后执行优先级为 2 的分析任务，最后执行优先级为 3 的报告任务。同一优先级内使用 `asyncio.gather` 并发执行，并通过 `asyncio.Semaphore` 控制最大并发数。

这种设计保证了阶段依赖：分析不会读取尚未采集的数据，报告不会读取尚未完成的分析结果；同时，同一阶段的不同研究子任务可以并行，提高整体吞吐。

### 4. DataCollector

`DataCollector` 默认挂载两类工具：

- `DeepSearchAgent`，负责搜索引擎检索和网页内容抓取。
- 金融、宏观和行业工具，包括 AkShare、efinance、yfinance 和 FRED 等数据源封装。

LLM 在 Prompt 中看到工具说明，然后返回搜索或执行动作。数据工具的返回值被包装为 `ToolResult`，其中包含名称、描述、数据和 source 字段，随后写入 Memory。

### 5. DeepSearchAgent

DeepSearchAgent 默认使用搜索工具和 Click 内容抓取工具，支持多轮搜索。它会记录：

- `valid_links`：搜索结果中出现过的合法 URL。
- `used_sources`：真正被点击和读取的来源。
- `link2name`：URL 与标题的映射。

点击动作只能使用之前搜索结果中出现过的 URL，这是一层输入约束，也能避免模型凭空构造链接。搜索失败会记录错误并要求模型重试；达到最大轮次后会根据已有对话生成总结。

### 6. DataAnalyzer

DataAnalyzer 从 Memory 读取采集数据，向代码执行器注入：

- 已采集数据列表。
- `get_existed_data` 数据读取函数。
- `get_data_from_deep_search` 搜索函数。
- 当前图表输出目录和配色方案。

Agent 可以生成 Python 代码完成数据清洗、同比/环比、趋势、相关性和财务指标计算，并把图表保存到 Agent 工作目录。分析阶段还可以生成报告草稿。对于需要图表的任务，系统会先生成图表，再通过 VLM 进行“生成代码—执行—看图—修改”的迭代，最多执行配置的轮数。

### 7. ReportGenerator

ReportGenerator 采用分阶段生成，避免一次性让模型写完整长报告：

1. 读取分析结果和大纲模板，生成报告大纲。
2. 按章节单独写作，每个章节只拿到相关的数据和分析结果。
3. 替换图表占位符，把 `@import` 映射到真实图像。
4. 生成摘要和标题。
5. 公司类报告补充三大财务报表、股东结构和股价趋势。
6. 解析 `[Source: ...]` 或 `[KB:...]` 引用。
7. 写出 Markdown，使用 Pandoc 和参考 DOCX 模板生成 DOCX，再尝试转换为 PDF。

每个阶段都有自己的 Checkpoint，例如大纲、章节、图表和报告后处理阶段可以分别恢复。

## 六、BaseAgent 的核心执行机制

一个 Agent 的核心循环可以简化为：

```python
messages = await prepare_init_prompt(input_data)
messages += await evidence_context(memory, query)

for round in range(max_iterations):
    response = await llm.generate(messages, stop=stop_words)
    action, content = parse_llm_response(response)
    result = await execute_action(action, content)
    messages += [assistant(response), user(result)]
    await save_checkpoint(messages, round, extra_state)
    if not result["continue"]:
        break
```

BaseAgent 还负责：

- Agent 类注册和从 Checkpoint 恢复。
- Agent 工作目录和缓存目录创建。
- Tool/Agent 依赖记录。
- LLM 调用和日志上下文设置。
- 同步代码环境中的工具调用。
- 最大迭代次数和最终结果处理。

项目使用的是自定义文本动作协议，常见动作包括 `<execute>`、`<search>`、`<final_result>`；报告 Agent 还使用 outline、draft、report 等阶段动作。它不是 OpenAI 原生 function calling 的完整实现，而是通过 Prompt 约定标签格式，再由 Python 解析和路由。

## 七、为什么需要 AsyncBridge

LLM 生成的代码在 `AsyncCodeExecutor` 中以同步 `exec()` 方式运行，但外层 Agent 又处于 asyncio 事件循环中。如果直接在执行器里调用 `asyncio.run()`，会遇到“event loop already running”错误，甚至死锁。

项目的处理方式是：

1. 主 Agent 保持 asyncio 事件循环。
2. 代码执行器通过 `call_tool` 暴露工具调用函数。
3. `call_tool` 把协程交给 `AsyncBridge` 管理的后台事件循环。
4. 执行器同步等待结果，但不会嵌套启动当前事件循环。

这使 LLM 生成的代码可以访问异步金融 API、搜索 Agent 和速率限制器。

## 八、Memory、依赖图和 Checkpoint

### Memory 为什么采用共享对象

采集、分析和报告是强依赖流程。与其通过多个文件手工传递数据，项目让所有 Agent 持有同一个 Memory 引用。采集结果一写入，后续 Agent 就能按照数据类型读取；日志和依赖图也集中保存，便于恢复和调试。

### Checkpoint 保存什么

Agent 的 Checkpoint 使用 dill，主要保存：

- Agent 类名和 Agent ID。
- 当前任务输入和当前轮数。
- 对话历史。
- Tool/Agent 依赖关系。
- 初始化参数，例如模型名称和是否启用代码。
- 子 Agent 的额外状态，例如已采集数据、已验证 URL、报告阶段进度。
- 代码执行器的轻量状态。

Memory 使用 `memory.pkl` 保存全局状态；Agent 使用各自工作目录下的 `latest.pkl`、`charts.pkl`、`outline_latest.pkl` 或 `report_latest.pkl`。

### 如何避免恢复时混用旧数据

知识库启用时，系统对知识库设置计算签名。恢复 Memory 时，如果当前配置签名与保存的签名不同，就拒绝继续恢复，要求新建研究任务。这样可以避免用户换了资料库、截止日期或过滤条件后，仍然沿用旧证据快照。

## 九、知识库和 Agentic RAG

### 文档入库

支持 PDF、DOCX、Markdown 和 TXT。解析流程是：

```text
上传文件
  ↓
校验格式、大小和元数据
  ↓
SHA-256 内容哈希去重
  ↓
queued → parsing → indexing → ready
  ↓
保存原件、文档记录、切片和 FTS5 索引
```

PDF 使用 pdfplumber 按物理页解析文本和表格；DOCX 解析段落、Heading 和表格；Markdown/TXT 按段落和标题解析。每个切片记录 `doc_id`、文本、定位信息、页码和类型。长文本按最大长度切分并保留重叠，表格切分时重复表头。

如果 PDF 没有可提取文本，文档会进入 `needs_ocr` 状态。项目目前识别 OCR 需求，但没有集成 OCR 引擎。

### 去重和版本

文档唯一性由资料库、内容哈希、元数据和解析器版本共同决定。相同内容和元数据会返回重复结果；删除后重新导入会生成新的不可变文档记录。切片 ID 使用文档 ID、切片序号和解析器版本生成，因此在版本和切片顺序不变时保持稳定。

### 混合检索

检索分为两路：

- 关键词路：SQLite FTS5；中文会生成二元词组，也尝试使用 jieba 分词。
- 语义路：调用 Embedding 模型生成向量；默认在本地使用 NumPy 计算余弦相似度，也可以写入 Qdrant。

两路结果使用倒数排名融合，最终限制每份文档最多返回一定数量的片段，以避免一个文档占满全部结果。没有 Embedding 模型时显式降级到关键词检索，并返回 warning。

### Agentic RAG 的关键点

普通 RAG 是“固定检索一次再回答”。本项目中，Agent 每一轮都会根据任务、分析任务或章节标题触发知识检索；如果证据不足，可以输出 `<knowledge_search>查询</knowledge_search>` 继续检索。因此检索是 Agent 行为的一部分，而不是单独的前置步骤。

### 证据快照和引用

研究开始时，系统把符合资料库、公司、证券代码、市场、行业、报告期和截止日期条件的切片保存到 `memory.knowledge_state['corpus']`。后续检索只在这个快照上执行，即使在线资料被删除或重新索引，已开始的研究也不会改变。

模型看到的证据格式类似：

```text
[KB:abc123] 2024 年度报告 — PDF p.38
Metadata: {"company": "...", "published_at": "..."}
原文片段...
```

后处理只接受真实存在的证据 ID；不存在的 ID 会输出“未验证来源”。润色前后如果证据 ID 集合发生变化，系统会保留润色前草稿，避免模型在润色时丢掉引用或凭空增加来源。

## 十、代码执行器和安全边界

LLM 生成代码是项目的重要能力，但不能直接把模型代码当作可信代码执行。`AsyncCodeExecutor` 做了几层限制：

- 禁止导入 `subprocess`、`shutil`、`ctypes`、`socket`、`multiprocessing` 等高风险模块。
- `open()` 的写入只能落在当前 Agent 工作目录。
- 默认执行超时为 120 秒。
- 捕获 stdout、stderr 和异常堆栈。
- 代码执行器状态单独保存和恢复。
- 知识库 `knowledge_only` 模式会关闭外部工具和生成 Python。

这是一层轻量级应用沙箱，不等同于容器级或操作系统级隔离。若部署到多租户或不可信代码环境，还需要独立容器、资源配额、网络隔离和更严格的系统调用控制。

## 十一、后端、前端和运行方式

后端使用 FastAPI：

- 配置管理：`/api/config`。
- 任务管理：`/api/tasks`。
- 执行控制：`/api/execution/start`、`/api/execution/stop`。
- 报告列表、预览和下载：`/api/reports`。
- 知识库：`/api/knowledge/libraries`、文档上传、任务状态和搜索接口。
- 实时日志：`/ws/logs`。

前端使用 React 18、Vite、React Router、Ant Design、Axios 和 React Markdown。用户可以编辑研究配置、选择知识库、上传资料、启动任务、查看执行日志、预览报告和展开知识库证据。

典型启动方式：

```bash
# 后端
python -m uvicorn demo.backend.app:app --host 127.0.0.1 --port 8000

# 前端
npm run dev --prefix demo/frontend -- --host 127.0.0.1

# CLI
python run_report.py --config my_config.yaml --fresh
```

Qdrant 是可选组件，通过 `compose.knowledge.yaml` 启动；默认知识库可以只使用 SQLite FTS5 和本地向量检索。

## 十二、测试和验证

当前测试覆盖：

- PDF/DOCX/Markdown/TXT 解析。
- 文档去重、删除、重试、版本和状态机。
- FTS5、Embedding、本地向量、Qdrant 适配和降级行为。
- 日期、实体、资料库和 AI 生成资料过滤。
- 知识库证据快照、引用解析和配置签名。
- Agent 检索、Memory 往返和后端配置接入。
- Python 执行器的模块、路径和超时限制。
- 原有 Memory、异步桥接、LLM 响应解析、工具注册和限流。

当前仓库已经通过 101 项自动测试的选定回归集合，前端 `npm run build` 也可以通过。真实模型生成质量仍取决于实际配置的模型服务；没有在本地验证环境中声称完成完整真实研报质量评测。

## 十三、项目中的主要难点和解决方案

### 难点 1：多个 Agent 如何共享结果又避免数据混乱

解决方案是使用统一的 `VariableMemory`，所有结果通过 `ToolResult` 结构保存，包含名称、描述、数据和来源；同时用 `task_mapping` 和依赖图记录任务关系。后续 Agent 不直接依赖前一个 Agent 的局部变量，而是从 Memory 读取可复用结果。

### 难点 2：异步 API 和 LLM 生成代码冲突

解决方案是 `AsyncBridge`。同步 `exec()` 环境只暴露 `call_tool`，真正的协程调用交给后台事件循环执行，避免在已有事件循环中嵌套 `asyncio.run()`。

### 难点 3：报告润色会破坏引用

解决方案是给每个知识证据分配稳定 ID，并在润色前后比较 `[KB:...]` 集合；如果集合改变，就保留润色前版本。最终引用解析只接受证据表中的精确 ID。

### 难点 4：资料更新后历史研究结果不稳定

解决方案是研究启动时固定证据快照。在线库的删除、重新索引和新文档不会改变已经开始的研究；恢复时再通过配置签名检查是否更换了检索条件。

### 难点 5：模型生成代码存在风险

解决方案是限制模块、文件写入目录和执行时间，并提供 knowledge-only 模式。面试时要主动说明这是轻量沙箱，不应直接当成生产级多租户隔离。

## 十四、为什么没有使用 LangChain 或 LangGraph

这个项目需要的核心能力主要是：动作循环、工具注册、共享变量空间、检查点和金融数据工具。项目选择自己实现 `BaseAgent`，可以直接控制状态结构、工具输入输出和恢复逻辑，减少框架抽象对现有代码的侵入。

代价是需要自己维护 Prompt 协议、动作解析、错误处理、可观测性和状态兼容。后续如果需要更复杂的条件分支、可视化工作流或分布式执行，可以考虑把调度层迁移到 LangGraph，或者保留自定义 Agent 内核、只引入专门的队列和追踪组件。

## 十五、常见面试问题与回答

### 1. 为什么要拆成多个 Agent？

采集、分析和写作的工具、上下文和评价标准不同。拆分后每个 Agent 的 Prompt 更短、工具边界更清晰，采集结果还能被多个分析任务复用。调度器再用优先级保证阶段依赖。

### 2. Agent 之间如何通信？

不是通过 HTTP 或消息队列，而是共享同一个 `Memory` 对象。数据通过 `ToolResult` 保存，任务和依赖通过 `task_mapping`、`dependency` 记录。这样适合当前单机异步场景，但还不是分布式 Agent 通信方案。

### 3. 这是原生 Function Calling 吗？

不是完整的原生 Function Calling。项目通过 Prompt 描述工具，模型返回动作标签或代码，BaseAgent 解析后调用工具。这个方案容易跨模型服务，但结构约束和错误反馈需要自己维护。

### 4. 如果模型返回了错误格式怎么办？

BaseAgent 会按标签解析；无法识别的动作会进入错误处理或作为最终结果返回。部分分析阶段使用 JSON response format 和 `json_repair` 做容错。进一步改进可以使用严格 JSON Schema、Pydantic 校验和重试策略。

### 5. 如何避免 Agent 无限循环？

每次运行都有 `max_iterations`，每轮都会保存状态；达到上限后，部分 Agent 会要求模型基于已有历史直接总结。搜索 Agent 还会把可用来源列表追加到最后几轮的上下文中。

### 6. 如何做断点恢复？

每轮保存对话历史、轮数、任务输入、工具依赖和额外状态；恢复时根据 Agent 名称从注册表找到类，再递归恢复依赖 Agent 和工具，同时加载代码执行器状态。

### 7. 为什么 Memory 用 dill？

dill 比标准 pickle 更容易序列化部分 Python 对象，适合保存执行器状态。项目仍使用临时文件加 `os.replace` 的方式原子写入，并在加载失败时尝试 pickle。生产环境需要考虑版本兼容、文件损坏和安全反序列化问题。

### 8. 知识库为什么同时使用 FTS5 和向量检索？

金融资料中公司名、指标名、证券代码和年份等精确词很重要，关键词检索对这些词稳定；语义检索可以覆盖同义表达。混合召回比只使用一种检索方式更稳，没有 Embedding 服务时还能降级到关键词模式。

### 9. 为什么 SQLite 作为权威库，Qdrant 作为可选后端？

当前目标是单机、本地、可审计的研究系统。SQLite 适合保存文档状态、元数据、切片和 FTS5；向量索引可以重建，所以 Qdrant 只作为可替换的派生索引。这样即使向量库不可用，文档和关键词检索仍然可用。

### 10. 文档删除后，历史报告会不会失效？

不会直接改变已经开始的任务，因为任务使用的是证据快照；删除只会让新研究和在线检索排除对应片段，原件和历史证据保留用于审计。向量点目前通过候选 ID 过滤，物理垃圾回收需要重建集合。

### 11. 如何保证引用没有被模型编造？

模型只能引用检索上下文中出现的稳定 ID。后处理会用证据表精确查找，找不到就标记为未验证，不会用语义近似替代来源。润色阶段还比较引用 ID 集合，发现丢失或新增就回退到原草稿。

### 12. 这个系统能完全防止幻觉吗？

不能。它能提高可追溯性，限制模型引用不存在的知识库 ID，并要求说明证据缺失，但不能保证模型对证据的解释完全正确。关键主张仍需要研究人员复核。

### 13. 代码执行器安全吗？

它提供模块限制、目录限制和超时控制，是轻量应用沙箱；但代码仍在同一应用进程的线程池中执行，不是强隔离。生产环境应该使用独立容器、网络策略、资源限制和更严格的系统调用拦截。

### 14. VLM 在哪里发挥作用？

DataAnalyzer 生成图表后，VLM 读取图表并检查可读性、标题和关键趋势；如果图表代码或结果有问题，就重新生成和执行。ReportGenerator 还使用 VLM/模型生成图表说明，最终把图片插入报告。

### 15. 为什么需要三个模型？

文本模型负责复杂推理和写作，视觉模型负责图表理解，Embedding 模型负责相似度检索。分离后可以根据成本、延迟和能力选择不同供应商，也避免把图像内容强行塞给纯文本模型。

### 16. 如何控制外部 API 的并发和频率？

全局 `RateLimiter` 按搜索引擎、金融 API、FRED 和 yfinance 等服务分类设置间隔；任务层使用 Semaphore 限制并发 Agent 数量。这样可以降低触发限流和服务端拒绝的概率。

### 17. 一个采集任务失败会怎样？

工具异常会写入 Memory 日志并返回错误结果；Agent 可以根据错误继续重试。任务级别有 Checkpoint，应用启动时知识库服务会把未完成的 queued/parsing/indexing 任务恢复为 queued。更复杂的分布式重试和死信队列尚未实现。

### 18. 前后端如何实时显示进度？

后端使用 WebSocket `/ws/logs` 推送 Agent 日志和执行事件，前端通过 React 状态更新任务进度、日志和报告状态。配置、任务、报告和知识库管理走 REST API。

### 19. 测试覆盖了什么？

测试覆盖解析、去重、状态机、检索、证据快照、Agent 接入、恢复、工具注册、异步桥接、LLM 响应解析和代码执行器限制。它验证的是可重复的逻辑行为，不代表真实模型在所有金融问题上的回答质量。

### 20. 当前最大的瓶颈是什么？

第一是外部 API 和模型调用延迟；第二是长资料解析和 Embedding 成本；第三是多个 Agent 的上下文会随着数据量变大；第四是本地向量检索适合小规模资料，还没有完成大规模性能基准。后续可以加入批量 Embedding、缓存、分布式队列、异步任务状态和更强的检索评测。

### 21. 如果让你继续改进，会先做什么？

我会先补充端到端评测集和可观测性，记录每个 Agent 的输入、工具调用、延迟、Token 和引用正确率；然后把任务执行拆成可持久化队列，加入 OCR、权限和多租户隔离；最后再考虑 LangGraph 或工作流可视化，而不是一开始就替换现有 Agent 内核。

## 十六、面试时的真实边界

可以明确说：

- 项目已实现的是单机异步多 Agent 研究流水线，不是分布式 Agent 平台。
- Qdrant 是可选向量后端，默认仍可使用 SQLite FTS5 和本地向量检索。
- 当前没有 MCP、A2A、正式 Agent Skills、Celery/Kafka、模型 Serving 和完整 OpenTelemetry Trace。
- OCR、复杂跨页表格重建、多用户权限和生产级队列属于后续工作。
- 测试验证了逻辑和接口，真实模型效果仍依赖模型服务、数据源和 Prompt 配置。

这种回答比声称“完全消除幻觉”“生产级安全沙箱”或“支持分布式多 Agent”更可信，也能体现你对系统边界的理解。

## 十七、面试现场三分钟讲解顺序

按照下面顺序讲，面试官通常可以快速理解项目：

1. 先说问题：金融研究资料分散，人工采集、分析和写作耗时，引用难追溯。
2. 再说结果：系统把采集、搜索、分析、图表、写作和知识库串成可恢复流水线。
3. 讲架构：`DataCollector → DataAnalyzer → ReportGenerator`，共享 `VariableMemory`，按优先级调度。
4. 讲 Agent 内核：`BaseAgent` 负责 Prompt、动作解析、工具调用、代码执行和 Checkpoint。
5. 讲一个难点：`AsyncBridge` 解决同步代码执行器调用异步工具时的事件循环冲突。
6. 讲 RAG：SQLite/FTS5 + Embedding/Qdrant，研究启动时固定证据快照，用稳定 ID 保证引用不漂移。
7. 讲安全和边界：限制模块、路径和超时，但不是强隔离；没有把未实现能力写成已经上线。
8. 最后讲验证：pytest 覆盖核心流程，前端构建通过，并说明真实模型质量仍需在目标模型和数据上继续评测。
