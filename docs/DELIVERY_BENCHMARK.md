# 真实用户对照的预先设计

这套工具准备评估 Tessera 与普通多轮对话完成同一展示页任务的差别。目前没有招募参与者，也没有真实效果结论。

`research/fixtures/delivery_tasks.json` 提供20个明确标为设计性素材的任务，覆盖不同受众、项目描述、局部保留、联系信息和响应布局。两组使用相同初始资料、起始设计、模型以及费用、调用次数和时间上限；按任务分配交叉顺序。默认的 planned 参与者 ID 只是待招募位置，不是已参与人数。交叉设计仍存在熟悉任务带来的迁移效应，正式实施须记录并报告。

生成空记录：

```powershell
python -B scripts/assess_delivery.py plan
```

每次写入新 experiments/runs 目录，输出 protocol.json、records.pending.json、score.json。模型未配置、缺少事件或证据、只有一组完成时，指标保持 pending/null，不填成0，也不计作成功或失败。默认预算只是试验设计，不构成付费调用授权。

收集后评分：

```powershell
python -B scripts/assess_delivery.py score --plan <protocol.json> --log <记录.json> --evidence-root <证据目录>
```

记录包含开始/结束、修正、模型调用费用、保留违例事件，以及人工验收表和成品文件；所有证据绑定 SHA-256。脚本从事件推导耗时、调用、费用、修正次数，只有完整且符合协议的配对进入均值。预算超限单列 protocol_deviation；模型/材料/预算失配、伪造字段、证据哈希不匹配拒绝评分。

哈希验证文件身份，无法证明观察者判断真实、账单准确或记录没有遗漏。实施时仍需知情参与、完整日志和独立核对；不能从这份计划宣称优于对话、节省时间或提升完成率。
