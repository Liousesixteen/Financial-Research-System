# Financial Research System 知识库使用说明

已实现：资料库创建/改名，PDF/DOCX/MD/TXT 上传与去重、解析状态、失败重试、重新索引、删除检索记录、原文预览、中文关键词与语义混合检索、资料范围和截止日期过滤；CLI/Web 研报接入、按章节检索、稳定引用、任务证据快照和报告证据展开查看。

## 1. 启动

本项目要求 Python 3.10+，建议 3.11。本次验证环境是项目根目录 `.venv-kb`，不修改系统 Python。

仅体验知识库，不需要模型密钥：

```bash
python3.11 -m venv .venv-kb
.venv-kb/bin/python -m pip install -r requirements-knowledge.txt
.venv-kb/bin/python -m uvicorn demo.backend.knowledge_app:app --host 127.0.0.1 --port 8000
```

另开一个终端：

```bash
npm ci --prefix demo/frontend
npm run dev --prefix demo/frontend -- --host 127.0.0.1
```

打开 http://127.0.0.1:3000/#knowledge 。独立知识库服务只提供资料管理与检索，系统配置、执行与报告页面需完整后端。

完整研报服务：

```bash
.venv-kb/bin/python -m pip install -r requirements.txt -r requirements-knowledge.txt
.venv-kb/bin/python -m uvicorn demo.backend.app:app --host 127.0.0.1 --port 8000
```

二者使用相同资料目录，不要同时占用 8000 端口。开发时必须单个后端 worker：入库恢复为单进程设计。运行环境若限制用户缓存目录写入，可为 `CRAWL4_AI_BASE_DIRECTORY` 与 `MPLCONFIGDIR` 指定可写的临时目录。

## 2. 首次体验

1. 新建资料库，上传年报或公告。`docs/examples/knowledge/demo-company.md` 是明确标注的虚构演示资料，不能当作真实投资证据。
2. 填写公司、证券代码及市场、行业、公开披露日期和报告期。日期格式为 YYYY-MM-DD；公开披露日期与财报覆盖期间分开记录。
3. 等待“可检索”。扫描 PDF 会显示“待 OCR”；损坏文件会显示失败原因，不会作为空文档入库。
4. 查询“毛利率下降的原因”，打开命中项查看原文及其稳定证据编号。PDF 定位为一基物理页码；DOCX/MD/TXT 使用章节和段落，不伪造页码。
5. 筛选采用精确匹配；指定截止日期后，之后披露和未标注披露日期的资料都不参与检索。AI 生成资料默认排除。

文档标题目前采用文件名。重新上传相同文件与元数据会返回重复提示；更改内容或元数据会生成独立不可变文档记录。重新索引同一记录保留稳定片段 ID（在解析器版本及片段顺序不变时）。

“删除”含义是从新研究和在线检索中移除，原件与既有报告证据快照保留以供审计。它不是物理擦除功能；当前不提供资料库整库删除。

## 3. 接入研报

在“系统配置 → 知识库与证据”启用知识库并选择资料库，然后保存配置。完整后端沿用已有生成、视觉和 Embedding 模型设置；资料管理本身不要求生成模型密钥。

- **知识库 + 联网**：各 Agent 在现有任务资料之外获得相关原文证据，可继续调用原有联网/财务工具。
- **仅知识库（文字研究）**：禁用外部数据工具及生成的 Python，并关闭分析图表生成；模型仍使用配置的模型服务，因此不等于所有网络连接断开。
- 各章节根据任务自动检索，也可以输出 `<knowledge_search>查询</knowledge_search>` 获取补充证据。
- 证据使用 `[KB:稳定编号]`，后处理直接查表生成参考文献编号，缺失 ID 显示未验证，不以语义近似来源替代。
- 同时存在旧式 `[Source:...]` 时仅精确匹配来源名称/来源字符串；不能唯一解析的旧式引用也显示未验证。
- 润色如果丢失或新增证据编号，会保留该章节润色前的草稿。编号一致并不意味着语义一定正确，关键主张仍需研究者核对。
- 报告旁保存 `<报告标题>.knowledge.json`，包含引用映射与原文证据。报告预览下方可展开“引用证据 · 本次研究快照”，核对原文、定位、日期与版本。

命令行示例（加入现有 YAML，不要替换原研究任务配置）：

```yaml
knowledge_base:
  enabled: true
  kb_ids: ['从页面 API 或下面 list 命令获取的资料库 ID']
  mode: hybrid
  as_of: '2026-06-30'
  top_k: 8
  vector_backend: local
  embedding_model: '与 llm_config_list 对应的模型名称'
  embedding_version: '1'
  filters:
    ticker: '600001'
    market: 'A'
```

```bash
.venv-kb/bin/python -m src.knowledge list
.venv-kb/bin/python run_report.py --config my_config.yaml --fresh
```

默认关闭 KB 时维持原研报流程。`--fresh` 新建研究证据快照；不指定则沿用原有恢复行为。知识库设置改变后旧检查点会被拒绝恢复，避免混用条件。库内资料更新不会改变已有任务快照，开始新研究才能使用新资料。建议每份新研究使用新的 output_dir/save_note，避免相同标题覆盖旧产物。

## 4. 存储与检索

默认原件、SQLite、FTS5 和 Embedding 缓存位于项目根目录 `data/knowledge/`，已加入 Git 忽略。备份时停止写入后备份整个目录，并保留需要审计的报告输出目录。设置 `FRS_KB_DIR` 可以切换存储位置，CLI 与 Web 必须指向同一目录。

无 Embedding 配置时使用中文二元词组 + jieba/英文词项的关键词检索。有模型时使用关键词、语义两路召回与 RRF 融合，保留来源多样性；Embedding 失败的检索会显式降级。入库时若已配置的 Embedding 失败，任务标记失败，可重试，也可暂移除该配置后重新索引。

本地后端使用归一化向量精确计算。首版面向单机小规模资料，尚未做 100–500 文档的性能基准；语义查询首次遇到未嵌入的片段时会构建缓存，可能耗时较长。任务快照当前保存筛选后原文，因此大型库会增加检查点体积。

Qdrant 可选服务：

```bash
docker compose -f compose.knowledge.yaml up -d
```

然后在系统配置中选择 Qdrant，URL 为 `http://localhost:6333`，并设置有效 Embedding 模型。容器版本固定为 1.19.0，与本次验证的 qdrant-client 1.19.x 对齐。容器只绑定本机地址。

在线查询会按当前允许的片段 ID 过滤 Qdrant 结果，再检查 SQLite 状态。任务快照检索使用本地精确计算，避免文档删除/修订破坏历史研究。Embedding 缓存区分内容哈希、模型名称、服务地址及显式 embedding_version；模型改变维度或输出含义时应提升版本并重新索引。

删除后的 Qdrant 点目前通过主库状态及候选 ID 集合排除，未做物理垃圾回收；重建集合时可清理。SQLite 与原件是主数据，Qdrant 索引可重建。

## 5. 测试与已知边界

当前离线回归集已通过 106 项自动测试，覆盖知识库、LangChain Retriever、LangGraph 状态图与 SQLite Checkpoint，以及原有记忆、异步桥接、LLM 响应解析与重试、工具、日期、限流和执行器。Qdrant 适配使用官方客户端的本地内存引擎测试，尝试启动 Docker 服务时，本机 Docker/OrbStack 引擎未运行（docker.sock 不存在），尚未完成容器部署验收。前端 `npm run build` 通过，仍有包体较大的构建提示。

测试命令：

```bash
CRAWL4_AI_BASE_DIRECTORY=/tmp/financial-research-system-crawl MPLCONFIGDIR=/tmp/financial-research-system-mpl \
.venv-kb/bin/python -m pytest tests/knowledge tests/workflow tests/test_memory.py tests/test_async_bridge.py \
  tests/test_parse_llm.py tests/test_llm_retry.py tests/test_tool_base.py tests/test_tool_registry.py \
  tests/test_dynamic_date.py tests/test_rate_limiter.py tests/test_sandbox.py -q
npm run build --prefix demo/frontend
```

测试开发依赖另行安装：`pytest pytest-asyncio hypothesis httpx`。

浏览器验收覆盖新建资料库、上传演示 Markdown、解析完成、中文问题检索、原文抽屉与证据编号。PDF 解析/页码、DOCX 表格、重复上传、日期/资料库过滤、删除后在线不可检索、恢复任务保留快照均有自动测试。

本次未配置或调用真实生成/Embedding 模型，没有生成可用于研究的完整真实研报，也没有声称达到方案中的 Recall@5 或主张支持率目标。真实模型质量、真实表格数值口径和 MD/DOCX/PDF 全链路导出仍需在模型配置与样本文档就绪后验收。原项目 PDF 导出仍依赖 Pandoc/docx2pdf 及操作系统的文档转换环境。

OCR、复杂跨页表格重建、Excel 指标仓库、知识图谱、多用户权限与生产任务队列属于后续范围。当前服务用于本机单用户，知识库文件和模型文本不应直接公开暴露。
