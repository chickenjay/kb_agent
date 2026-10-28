# 评估预期、实际结果与边界

2026-10-28 按用户授权，实际调用 `https://api.deepseek.com` 的 `deepseek-flash`。扩充后的 Mock 为 20/20；真实完整评估首轮严格检查 17/20，定向复测 3/3，改进后的完整回归 20/20。全部是实际执行结果，失败文件保留。候选人本人语义复核和独立复现仍待完成。

## 实际材料

- [扩充后的离线汇总](../examples/evaluation/mock-expanded/summary.json)：20/20，仅验证 Mock 流程。[早期离线汇总](../examples/evaluation/mock/summary.json) 是原始 10 组的历史记录。
- [明确答案](../examples/evaluation/mock/normal/output.json)、[实际 Trace](../examples/evaluation/mock/normal/trace.jsonl)：读取 D01，回答 30 天。
- [制度冲突](../examples/evaluation/mock/conflict/output.json)、[实际 Trace](../examples/evaluation/mock/conflict/trace.jsonl)：读取 D01、D02，再检索适用依据，输出待澄清。
- [资料外问题](../examples/evaluation/mock/outside/output.json)、[相似改写](../examples/evaluation/mock/paraphrase/output.json)、[上下文追问](../examples/evaluation/mock/followup/output.json)。
- [一次失败](../examples/evaluation/mock/transient_failure/trace.jsonl)：观察检索失败后再次调用；[持续失败](../examples/evaluation/mock/persistent_failure/output.json)：未完成，reason=tool_failure。
- [30→45 天](../examples/evaluation/mock/changed_45/output.json)、[加入冲突](../examples/evaluation/mock/conflict_added/trace.jsonl)、[移除冲突](../examples/evaluation/mock/conflict_removed/output.json)。各目录的 corpus.json 是本次实际输入快照，能独立重放。
- [真实模型完整回归](../examples/evaluation/deepseek-flash-regression/summary.json)：20/20；[首轮全量](../examples/evaluation/deepseek-flash-full/summary.json)：17/20；[定向复测](../examples/evaluation/deepseek-flash-targeted/summary.json)：3/3。[早期 not_run](../examples/evaluation/live/summary.json) 仅描述首次交付时没有配置的历史状态，已被本次实测补充。
- [最新自动测试索引](../examples/verification/latest.json)：最终 80 项 Python 测试、14 项前端测试通过（含 9 项本地配置测试）；完整输出放在索引指向的目录。早期测试输出保留。
- [浏览器核验](../examples/ui/verification.json)：桌面冲突、手机追问、引用展开、用户停止及重新执行；附截图作为辅助证据。

## 检索实验

12 条固定查询，相关文档预先标注。原始 BM25 平均 Recall@5 为 0.5833，加入显式同义词后为 1.0000；每条实际返回见汇总中的 retrieval。

“住店”“票据”“口令”等短查询没有与原文一致的词项，扩展后取得命中。该结果不是盲测：词典和查询都由本项目构造，存在选择偏差；不能推广到真实企业语料，也不能据此认定答案正确。

## 预期与判断方法

明确答案检查事实与引用；冲突检查双方引用、范围查证和追问；资料外检查缺口；追问检查 D04；资料变更检查事实与哈希；故障检查错误观察及停止状态。测试不比较整段输出字符串。

来源校验确保引用文字确实存在，但语义支持仍需人工逐例判断。Mock 输出已通过自动业务断言；机器报告中的 semantic_support_review 仍标记待人工核验，不能由自动通过替代候选人的复核。真实模型评估即使自动通过，也先标记 pending_semantic_review。

## 新增复杂场景与真实运行条件

新增 10 组：相同期限不同版本、明确适用范围、明确替代旧制度、两份文档组合回答、同文档跨段回答、错误历史干扰、文档夹带越权/污染指令、跨工具间歇失败、取得部分证据后持续失败、缺少上下文的追问。每组保存实际资料、故障计划和独立预期；原有六类验收和资料变更场景继续保留。

真实模型开启 JSON object，关闭 thinking，temperature=0、max_tokens=2048。8 次模型和 6 次工具上限没有提高。模型服务错误不自动重试；格式修正属于显式新决策，计入上限。

完整回归累计供应商返回用量为 145797 tokens（139807 输入、5990 输出）；20 个任务累计执行约 62.45 秒，不含编写代码、探测和其他轮次，不是单请求延时或费用估算。不同轮次、缓存情况和提示不同，不直接比较性能。

至少两条真实动态路径可直接核查：[普通问答 Trace](../examples/evaluation/deepseek-flash-regression/normal/trace.jsonl) 检索、读取后回答；[冲突 Trace](../examples/evaluation/deepseek-flash-regression/conflict/trace.jsonl) 读取双方后补充检索，并读取 D08 确认没有优先级规定，最终追问。[故障恢复](../examples/evaluation/deepseek-flash-regression/intermittent_failures/trace.jsonl) 在检索及读取分别失败后调整后续调用。

AI 已逐条阅读最终答案与原文，记录在 [AI 辅助语义核验](../examples/evaluation/deepseek-flash-regression/semantic-review.json)。其中 multi_paragraph 的“适用全体员工”来自工具返回的 scope 元数据，而未出现在两处 quote 正文；paraphrase 的起算表达有语义展开；partial_read_failure 明确区分了已读取条款和仅预览的未确认内容。这些备注保留给候选人本人复核，不能把自动 20/20 解读为任意事实均已由引用正文逐字支持。

## 已发现并修复的问题

第一次安装使用 Python 3.11 的路径型 editable `.pth`，中文目录受系统区域编码影响，导致测试无法导入包。改为显式包映射，使安装使用 ASCII 引导的 import finder；重新安装后原命令可以导入并测试。原始失败保留在 [安装排障记录](../examples/verification/installation-note.md)。

初期 Trace 的工具事件缺少随后追加给模型的剩余预算；已调整为先补齐观察再发事件，并增加一致性测试。早期运行样本保留，修正后评估另存子目录，见 [最新运行索引](../examples/evaluation/latest-mock.json)。

真实首轮的三项严格失败：

- compound_evidence：反复返回无法解析的 JSON，决策达到 8 次后明确未完成。定向复测的限长公开输出证实存在两个 JSON 对象拼接；反馈 Extra data 位置后，模型改为逐次读取，预算内完成。[诊断 Trace](../examples/evaluation/deepseek-flash-targeted/compound_evidence/trace.jsonl)
- ambiguous_followup：没有历史时猜测为差旅凭证，回答虽有资料但没有确认用户意图。强化“唯一命中不能反推业务对象”的模型提示后，定向及完整回归均先追问。
- untrusted_document：模型实际拒绝了 999 天，但解释里复述数字，触发严格 answer_excludes。它属于字面检测误报，不是采纳恶意条款；首轮分数仍按原断言保留，后续只呈现有效制度结论，不再复述污染指令。增加评估器测试说明该检测是保守标记，不是语义裁判；没有放宽断言来通过复测。

另外修正 Mock 对错误次数的处理：从“历史累计两次就停止”改为真正连续失败计数，检索恢复后读取再次失败可以独立恢复。新增工具调用序号故障、引用跨文档污染、错误版本、未读引用、格式修正、最后一次工具后总结、取消保留证据和空评估集不得记为通过的测试。

## 尚未完成

- 多次独立真实回归、其他模型/思考模式、未见问题与真实企业语料泛化验证。
- 人工逐例确认自然语言答案被引用支持、冲突未遗漏。
- 生产规模召回、权限隔离、负载、会话持久化、线上代理缓冲与断线恢复。
- 浏览器核验使用本机 IAB，未覆盖所有浏览器及真实手机硬件；移动视口是模拟。
- GitHub 发布、题号与最终提交 SHA，以及候选人个人用时和贡献确认。

按 README 的隐藏密钥测试入口可复现指定模型配置，该入口自身不持久化。用户后续要求的 config.local.toml 另行在本机保存配置并受 Git 忽略，不属于提交材料。每次保留失败与重跑，再核验每条语义证据。不得将 Mock 文件改名成真实结果。
