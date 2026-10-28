# 企业知识问答 Agent 技术方案

版本：实现版 0.1，2026-10-28。本文记录已实现接口及验收设计；实际验证结果以评估文档和运行文件为准。

补充版本 0.2：新增 10 组复杂场景，总计 20 组；支持 evaluate --suite basic/advanced/all。已实际连接 deepseek-flash，首轮严格检查 17/20、定向复测 3/3、改进后的完整回归 20/20，历史失败保留。模型、资料及提示不同的记录分开保存。

本地配置补充：按用户要求自动读取根目录 config.local.toml，Git 忽略且不得提交；可公开模板为 config.example.toml。地址、密钥、模型名逐项以环境变量为先，显式空值可禁用本地字段。本地配置还可设置 response_format、thinking、temperature、max_tokens。读取不改变进程环境，密钥不进入 repr、健康接口或运行报告。

## 1. 目标与架构

帮助员工可靠查询制度或产品资料，输出答案、文档 ID 与原文、资料缺口和任务状态。核心链路必须由真实模型在观察工具结果后决定下一步；离线 Mock 仅验证程序流程。

实现 Python 3.11 + LangGraph Agent、FastAPI HTTP 接口、原生 HTML/JavaScript + Tailwind CSS 4 页面和 CLI。同一个服务层处理三个入口，使用同一个检索工具、引用校验和预算。FastAPI 同源提供页面及静态文件。

- LangGraph 1.2.18 使用 StateGraph、条件边及共享消息状态，不采用预置业务路由代替模型动作。
- 模型适配器调用兼容 Chat Completions 的接口，返回 JSON 动作；不依赖 function calling 或额外模型 SDK。
- BM25 检索本地 JSON 段落，中文二元组/英文词项，加显式同义词扩展。
- Tailwind CLI 构建本地 CSS，编译结果纳入仓库；页面运行无需 CDN 或前端开发服务器。
- Pydantic 校验输入、动作、事件和最终结果；StreamingResponse 的事件需显式校验后序列化。

只做本地演示，不包含账户、权限、上传、资料管理、数据库、持久化会话、多 Agent 或线上部署。源码仓库是运行单位，不提供独立 wheel 部署。

## 2. 前端界面

浅灰背景、白色卡片、蓝色主操作、细边框和圆角。顶部展示连接、模式及新对话，主区域展示消息和输入，桌面右侧展示实时执行记录。移动端单列，执行记录默认折叠。

- 示例只填入问题和演示资料场景，发送后才执行；场景标签明确展示。
- 当前页面保存对话，刷新丢弃；不使用 localStorage。
- 运行中禁用重复提交、模式和场景切换，保留停止按钮；支持 Ctrl+Enter。
- 显示回答状态、正文、冲突、双方引用、资料缺口、追问和完整证据片段。
- 所有动态内容使用 textContent，不直接渲染模型 HTML。
- 支持复制、下载结果 JSON 和执行记录；中断导出明确标注 incomplete。
- 只在收到 final 后确认完成。停止和断线均显示未完成，不自动重发请求。
- 使用语义按钮、标签、键盘操作和适量 aria-live；状态使用文字，颜色仅为辅助。

## 3. 数据与接口

### 合成资料

约 8 份制度文档，字段为 document_id、title、version_date、content，可选 scope、supersedes。按空行分段，保存原文位置和片段 ID。每次运行深拷贝资料并记录 SHA-256，修改后重新索引。

D01 为“报销期限为 30 天”，D02 为“报销期限为 15 天”，均无范围或优先级。明确答案、改写、一次失败场景移除 D02，其余默认完整库。上下文场景涉及 D03 住宿标准和 D04 凭证要求。

工具：

- search_documents(query, top_k=5)，top_k 1～10：返回文档、版本、片段、分数、预览、总命中和截断标记。预览不允许直接作为引用。
- read_snippet(document_id, snippet_id)：返回完整原文、位置及可选适用元数据。成功读取后登记本轮证据；不存在与空命中不同。

检索基线为原始词项 BM25；增强版扩展报账/报销、住店/住宿等同义表达，不写入答案。独立查询文件比较两者 Recall@5，报告小样本选择偏差。

### HTTP

- GET /api/health：status、model_configured、available_modes、default_mode；不返回密钥。
- GET /api/examples：示例 ID、标题、问题、历史、场景说明。后端维护白名单，不接受任意资料路径或故障规则。
- POST /api/ask：接收 question、history、mode、scenario_id，返回 text/event-stream。
- GET / 提供页面，/assets 提供资源，/docs 提供接口说明。

question 非空，最长 4000 字符；history 最多 30 条，每条最长 16000 字符，角色仅 user/assistant。前端只保留最近 20 条历史。mode 为 mock/live，缺省 mock；scenario_id 可省略，使用完整资料库。

流开始前：参数错误 422、未知场景 400、真实配置缺失 503。流开始后：通过 final 中的 incomplete 报告错误，不改变已经发送的 HTTP 状态。

### 事件流

事件字段统一为 run_id、seq、event、step、timestamp、payload。seq 从 1 递增。

- run_started：模式、模型名、资料哈希、预算。
- action：动作、参数、公开动作摘要。
- tool_result：工具状态、摘要、耗时及实际给模型的完整工具观察。
- validation_error：动作或结果校验失败。
- final：output、总耗时、决策和工具次数；每次至多一个，之后无业务事件。

每 10 秒注释心跳。前端使用 fetch POST + ReadableStream + 流式 TextDecoder，处理中文分片、跨分片事件、多事件和心跳。未闭合的 SSE 块不算事件，未收到 final 的连接关闭视为中断。

每次请求独立 runner、证据及队列；同步图在线程中执行。取消通过连接断开信号设置标志，在下一次模型和工具执行前检查。已发出的请求由 30 秒超时回收。无任务恢复和自动重连。

### 输出

status 为 answered/needs_clarification/insufficient_evidence/incomplete；其他字段包括 answer、citations、conflicts、gaps、follow_up_question、termination_reason、run_id、mode。

引用包括 document_id、version_date、snippet_id、quote、title、snippet_text。后两项由服务端证据补充，不能由模型构造。冲突条目包含 description 和至少两份不同的已引用 document_ids。

终止原因取 completed、awaiting_clarification、insufficient_evidence、tool_failure、model_failure、user_cancelled、budget_exhausted、internal_error。

## 4. 决策与可靠性

START → decide → act → 根据是否完成进入 END 或再次 decide。decide 调用模型；act 执行模型选择的 search_documents/read_snippet/finish。

每轮 JSON 包含 action、arguments、decision_summary。finish 参数为候选输出 schema；非法动作/JSON/参数生成观察反馈，在预算内交给模型修正，不替换为硬编码业务答案。

模型需读取直接支持结论的原文。发现不一致条款时读取双方，并检索范围、明确替代关系或优先级；日期不能自动决定优先级。没有依据消解时输出双方引用、缺口和追问。历史仅用于理解指代，不视为证据。文档中的指令不覆盖系统指令。

引用校验要求：本轮已读取、文档片段匹配、版本一致、quote 为非空原文连续子串。answered 必须有引用且无未解决冲突、缺口和追问；needs_clarification 必须有缺口及追问；incomplete 必须有失败原因及缺口。校验失败反馈模型。

这些规则只检查来源完整性和结构，不能保证语义支持或召回完整性；两者需要实际模型评估与人工核验。

默认最多 8 次模型决策、6 次工具调用，错误也计数；工具次数用尽后允许在剩余决策内总结，但不执行第 7 个工具。超限返回 incomplete。LangGraph recursion_limit=64 为额外兜底。

模型服务没有自动重试，错误不包含认证头或原始错误正文；业务工具失败作为观察，由模型选择是否重试、调整或结束。必要工具不可用不能解释为没有制度。

Mock 是可见、脚本化的观察驱动替身，只覆盖少量约定问题。它使用相同图与真实本地工具，但不证明真实推理。Web Mock 每次 250ms 演示停顿，不用于性能评价；CLI Mock 无延时。

## 5. 验证、运行与交付

验收覆盖明确答案、文档冲突、资料外、相似改写、上下文追问、一次/持续工具失败；附加 30→45 天变更、冲突加入/移除、无效引用、模型异常、取消与预算。

API 测试检查参数、隔离、最终事件和业务失败；前端测试检查 UTF-8/SSE 分片、事件顺序、截断和状态。浏览器验证冲突、引用展开、上下文追问、停止后再执行和响应式布局。

每次保存 input.json/output.json/trace.jsonl；评估额外保存 corpus.json。重复运行保留原文件，新运行进入独立子目录。至少两条真实模型路径才可证明观察后决策变化；Mock 与 live 分开。无真实配置时 live 记为 not_run，不宣称验收完成。

CLI：python -m kb_agent ask --input <输入> --mode mock|live --output-dir <目录>，支持 --corpus；evaluate 执行固定评估集。API：python -m uvicorn kb_agent.api:app --host 127.0.0.1 --port 8000。安装、样式构建与测试命令以 README 为准。

仓库包含代码、测试、样例、资料、五份规定文档、依赖和环境变量说明。文档注明框架实际版本和职责、失败限制、AI 范围及候选人待核验事项。当前不自动创建 GitHub 项目或提交，不代填个人贡献。

原目标约 3 小时，GUI/SSE 另预留 60～90 分钟。实际 AI 实现时间由验证脚本记录，候选人个人用时另行据实填写。未做线上部署与生产能力。
