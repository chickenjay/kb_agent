# 调用流程与技术取舍

页面通过 fetch POST 接收 SSE，CLI 直接调用同一 AgentRunner。每轮由模型生成一个 JSON 动作，LangGraph StateGraph 的 decide/act 节点负责调用与执行。工具结果和校验错误重新放入消息，供下一轮判断。图只负责循环与终止，不内置“检索不到就固定做某步骤”的真实模型策略。

LangGraph 固定 1.2.18，实际使用 StateGraph、START/END、条件边和递归上限。未使用其托管服务、持久化检查点、预置 Agent、多 Agent 或 LangSmith 跟踪。FastAPI、Uvicorn、Pydantic 与全部传递依赖的实测版本在 requirements.lock.txt；Tailwind CSS 实测版本以 package-lock.json 为准。

选择轻量词法检索是为了让小规模资料变更可复现、无需 embedding 服务。字符二元组避免额外中文分词依赖；BM25 排序后由模型判断是否真的相关。同义词仅扩展查询，未写入业务答案。日期仅展示，不作为默认优先级。代价是语义召回有限，且“看见的引用真实”不能保证“没有漏掉另一份资料”。

程序验证引用必须已经读取、原文连续匹配、日期一致，然后从证据集合补充完整片段。它不声称能验证任意自然语言蕴含关系。测试中专门保留一个任意答案能通过来源校验的边界例子，以免把校验器误当语义裁判。

真实模型适配器把系统协议、问题、历史及工具观察发送给用户配置的服务。每次 HTTP 超时 30 秒，不自动重试或回退。认证来自服务端环境或被 Git 忽略的本地配置，不发给浏览器，错误正文不写入记录。JSON 格式错误会形成反馈，格式修正也消耗决策预算。

SSE 的统一事件源同时用于文件 Trace 与 Web。每请求独立队列和 runner；同步图在线程中运行。取消标志在动作前检查，已发出的 HTTP 不保证立即撤回。Mock Web 的 250 ms 停顿仅使演示可见；CLI 和评估无延时。

前端用原生模块，Tailwind CLI 预编译 CSS；不用运行时 CDN。所有动态文本以 textContent 插入，避免把资料作为 HTML。没有自动重连，以免重复花费模型调用。没有数据库；页面历史刷新即消失，服务端运行记录在忽略目录中。

MockModel 的少量规则明确标记为测试替身，它根据当前搜索/读取结果生成动作，无法证明真实模型能力，也不覆盖任意企业问题。后续真实模型评估必须使用 live 模式，不能将本地替身包装成模型 Trace。

## 扩充测试与 DeepSeek 接入

高级资料和独立预期由 advanced 模块构造，复用同一图。Mock 的显式范围、替代和数值规则仅作为测试替身；真实模式没有这些 Python 业务决策规则。

故障注入在原“前 N 次失败／一直失败”之外，支持按某个工具的第几次调用失败，例如 search_documents=[1]、read_snippet=[1]。这揭示并修正了 Mock 把跨工具历史失败误算为连续失败的问题。

指定 DeepSeek 测试启用 response_format=json_object、thinking=disabled、temperature=0、max_tokens=2048。接口及参数依据 [Chat Completions 官方文档](https://api-docs.deepseek.com/api/create-chat-completion/) 和 [Thinking Mode](https://api-docs.deepseek.com/guides/thinking_mode/)。不是在全局把其他兼容服务强制改为 DeepSeek 协议；测试启动器显式传入允许的请求选项，不能覆盖 model 或 messages。

真实测试中模型仍曾拼接两个 JSON 对象。现在校验反馈包含 Extra data 位置、长度和可公开 content 的限长摘要；只给模型反馈结构错误，不执行其中任一部分。reasoning_content 从不保存。模型收到反馈后重新选择单一动作，修正消耗决策预算。

所有新运行保存 prompt.txt 和提示哈希，以便比较提示改动。Token 记录只包含供应商返回的用量字段；早期未记录格式错误调用的用量，因此早期总量可能低估，不能据此算精确费用。
