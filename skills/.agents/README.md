# Skill 编排约定

`.agents/` 用于保存 Skill 编排层的角色说明、路由规则和上下文契约，不承载具体业务计算。

编排层由一个 Supervisor 和五个专业 Agent 组成：

- `Supervisor Agent`：选择专业 Agent、维护共享状态、控制重试、退回、终止和人工确认；
- `数据治理 Agent`：调用解析与标准化 Skill；
- `判据与规范 Agent`：调用阈值判断与规范检索 Skill；
- `风险归因 Agent`：调用案例检索与工况分析 Skill；
- `报告交付 Agent`：调用报告生成 Skill；
- `审计 Agent`：调用报告校验 Skill并将问题退回责任 Agent。

这些角色在同一个 Next.js 应用进程中运行，不要求多个模型或独立服务。角色之间只传递经过 Schema 校验的共享状态；每个角色必须声明职责、可用 Skill、输入输出、失败边界和终止条件。

编排层不得：

- 自行计算监测数值或报警阈值；
- 修改 Skill 返回的结构化事实；
- 使用案例结论覆盖规范判据；
- 自动签发报告或发布正式预警。

后续可在此目录增加：

- `supervisor.md`：Supervisor 角色与终止控制；
- `agents.md`：专业 Agent 职责和工具白名单；
- `routing.md`：Skill 路由和依赖顺序；
- `context-schema.md`：跨 Skill 上下文字段；
- `error-policy.md`：失败、重试、降级和终止策略。
