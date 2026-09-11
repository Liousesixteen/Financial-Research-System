# LangGraph 与 Agentic RAG 实现说明

## 1. 设计边界

系统把三类状态分开保存：

- LangGraph State 保存阶段、任务文本、Agent ID、Evidence ID、错误摘要和产物路径；
- Variable Memory 保存采集结果、分析对象、Agent 映射、依赖和任务知识快照；
- SQLite 知识库保存文档、片段、元数据、入库任务和 Embedding 缓存，Qdrant 是可重建的派生向量索引。

这种划分避免把 DataFrame、PDF 原文和报告对象写入每个图检查点。

## 2. 工作流

`src/workflow/research_graph.py` 定义以下节点：

1. `initialize`：恢复 Variable Memory，并固定本次任务的知识语料快照；
2. `plan`：合并 YAML 自定义任务与模型生成任务；
3. `retrieve`：针对总研究目标执行一次知识库预检索；
4. `assess_evidence`：判断首轮证据是否达到最低数量；
5. `expand_retrieval`：证据不足时把研究计划改写成多个定向查询并补充检索；
6. `collect`：并发运行 DataCollector；
7. `analyze`：在采集结果之上并发运行 DataAnalyzer；
8. `report`：运行 ReportGenerator，完成大纲、章节、润色和导出；
9. `audit`：读取知识审计文件，统计证据和未解析引用；
10. `finalize`：保存 Memory，写入最终状态和指标。

每个 BaseAgent 仍然保留自己的多轮 Agent Loop。模型可以输出：

```xml
<knowledge_search>需要补充检索的问题</knowledge_search>
```

Agent 会在固定语料快照中再次检索，因此 RAG 不限于工作流开始时的一次召回。

## 3. LangChain Retriever

`src/knowledge/langchain_retriever.py` 将现有 `KnowledgeBaseService` 适配成 LangChain `BaseRetriever`：

```python
retriever = retriever_for(memory)
documents = await retriever.ainvoke("公司毛利率下降的主要原因")
```

每个 `Document` 的 `page_content` 是原文片段，`metadata` 包含：

- `evidence_id`：报告使用的稳定引用编号；
- `document_id`、`knowledge_base_id` 和内容版本；
- 标题、页码、段落或章节定位；
- 公司、证券代码、市场、报告期和发布日期；
- 检索模式与 RRF 分数。

Retriever 使用任务开始时固定的 `snapshot`，并把检索结果注册回 `Memory.knowledge_state.evidence`。删除或更新在线知识库不会改变已开始任务的证据集合。

## 4. 混合检索

现有知识库继续负责检索语义：

```text
FTS5 中文二元词/jieba/英文词项召回
                     +
本地精确向量或 Qdrant 稠密向量召回
                     ↓
                 RRF 融合
                     ↓
       元数据、as_of 与来源多样性过滤
                     ↓
             KB:evidence_id
```

SQLite 是权威数据源，Qdrant 中的点可以重新生成。Embedding 未配置或在线服务失败时，检索会显式降级为关键词模式。

## 5. 运行与恢复

默认配置：

```yaml
workflow:
  engine: langgraph
  max_iterations: 20
  max_generated_tasks: 5
  generate_tasks: true
  min_initial_evidence: 3
  max_retrieval_queries: 4
  max_retrieval_rounds: 1
  fail_fast: false
  checkpoint_db: ''
```

`checkpoint_db` 为空时，图检查点位于：

```text
<working_dir>/workflow_checkpoints.sqlite3
```

CLI 和 Web 后端都调用同一个 `run_research_graph()`。Web 端使用页面中配置的任务，因此将 `generate_tasks` 设为 `false`；CLI 默认允许模型补充研究任务。

```bash
python run_report.py --config my_config.yaml --fresh
python run_report.py --config my_config.yaml
python run_report.py --config my_config.yaml --engine legacy
```

`--fresh` 使用新的图线程 ID 和新的 Agent 执行；不传时使用稳定线程 ID，并恢复图检查点、Memory 和 Agent 检查点。旧调度器作为迁移期回退入口保留。

## 6. 扩展方式

后续可以在状态图上增加条件边：

- 初始证据不足时执行查询改写与多查询检索；
- 数据源失败时切换备用工具；
- 引用审计失败时回到对应章节补证据；
- 发布报告前使用 `interrupt` 等待人工审核；
- 把采集、分析和章节写作分别拆成可复用子图；
- 生产环境把 SQLite Checkpointer 替换为 PostgreSQL Checkpointer。

扩展时仍应保持图状态轻量，只传可序列化引用，不直接传递大型业务对象。
