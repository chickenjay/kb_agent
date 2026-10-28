# 提交仓库核对

仓库：[chickenjay/kb_agent](https://github.com/chickenjay/kb_agent)，按用户明确选择设为公开。最终 commit SHA 随交付信息提供，也可通过 `git rev-parse HEAD` 查询；不在同一提交中循环写入自身 SHA。

题号：**3**；题目：企业知识问答 Agent。AI 辅助内容：代码生成与测试；个人修改：修正技术方案。首个可提交版本用时 **1 小时 22 分钟**；含后续修订的累计时间及起止依据见 [用时统计](../examples/verification/project-time.json)。

## 已核对

- README、技术方案、五份规定文档、源码、测试、合成资料、依赖锁、环境变量说明和无密钥配置模板齐全。
- Git 实际候选文件中不含 config.local.toml、.env、.venv、node_modules、.runtime；本机密钥的精确值和常见密钥格式扫描均无可提交匹配。
- 对 106 组已保存运行检查输入、最终输出和 Trace 一致性，引用必须来自成功读取的原文，文档版本匹配；执行未超过 8 次模型、6 次工具。
- 保存的真实模型记录包含 14 种不同动作序列，覆盖成功、冲突查证、格式修正、故障恢复、澄清及未完成；不以 Mock 代替真实运行。
- 不包含私有配置的评审副本可以从副本源码导入，80 项 Python 测试和 14 项前端测试通过，全部 20 组 Mock 评估通过。
- 最终 DeepSeek 实测 20/20 自动检查通过；首轮 17/20、定向复测 3/3 和语义复核备注均保留。

## 对照要求的目录与材料

- README.md：环境、安装、Web/CLI 运行命令、模型配置和评审入口齐全。
- src/：Agent、模型适配、检索读取工具、引用校验和后端接口齐全。
- tests/：Python 与前端可执行测试齐全。
- examples/：正常、资料不足、工具失败等输入、实际输出和 Trace 齐全，保留真实模型失败与回归记录。
- data/：带文档 ID、版本日期的合成制度、同义词规则和检索查询集齐全。
- docs/01-requirements.md：用户、目标、范围与成功标准齐全。
- docs/02-solution.md：流程、动态决策、框架职责与技术取舍齐全。
- docs/03-evaluation.md：测试预期、实际结果、失败分析与限制齐全。
- docs/04-ai-usage.md：AI 辅助代码生成与测试、个人修正技术方案及验证结果已记录。
- docs/05-retrospective.md：难点、学习收获和下一步已记录。
- requirements.txt、requirements.lock.txt、pyproject.toml、package.json、package-lock.json：依赖和锁定版本齐全。
- .env.example：模型变量说明齐全，密钥留空；额外提供无密钥 config.example.toml。本机 config.local.toml 已排除提交。

所列代码、文档与验证材料均已具备。结构完整与自动验证通过不代替下述本人语义复核。

机器记录：[提交文件与副本核验](../examples/verification/submission/summary.json)。检查脚本只核对和离线执行，不上传或调用付费模型。副本测试复用本机已安装的锁定依赖，未宣称在新的操作系统重新下载并安装验证。

## 仍需候选人确认

- 本人逐例语义核验，尤其是起算解释、元数据范围和仅预览的未确认条款；自动检查通过不等于任意回答的蕴含关系已被证明。

这些事项保持诚实记录，不影响代码和材料进入公开仓库，但提交给考核方前应据实补全。
