# 生图渠道适配器协议

## 目录

1. [适配器存在性](#1-适配器存在性)
2. [适配器能力声明](#2-适配器能力声明)
3. [并发与写入边界](#3-并发与写入边界)
4. [调用与暂存生命周期](#4-调用与暂存生命周期)
5. [来源模式](#5-来源模式)
6. [产物、清单与检查](#6-产物清单与检查)
7. [失败与交接](#7-失败与交接)

## 1. 适配器存在性

`provider` 必须对应 `references/provider-<provider>.md`。调用前完整读取适配器；文件不存在、工具不可用或能力不满足本协议时立即阻塞，禁止临时猜测参数、返回路径、编辑能力或失败语义。

未来新增渠道只增加一个适配器并通过本协议的评估场景，不复制 TEMU 业务规则。适配器只描述渠道差异。

## 2. 适配器能力声明

每个适配器必须明确：

- 渠道名、所需 Skill/工具和运行时读取要求。
- 新生成、带参考生成和渠道内编辑能力。
- 输入图片传递、角色表达、数量与格式限制。
- 是否支持不同图号并发；若不支持，实际并发降为 1，不修改 job 固定策略。
- 如何隔离图号上下文，并保证同图三版由同一生成 Subagent 串行完成。
- 成功时如何返回当前调用的唯一绝对源路径；不能稳定返回明确路径的渠道不满足 job v2 协议。
- 渠道源目录、direct/temp/final 目录和清单路径。
- 超时、中断、多候选、不可读输出、内容污染和英文错误的处理。
- 生成 Subagent 向主 Session 返回的结构化字段。

所有渠道使用共同路径骨架：清单位于 `output/<渠道直出目录>`，有效 direct 与清单同目录，rejected 位于 `output/temp/rejected-<provider>`，revision 位于 `output/temp/<task-id>/<image-id>`，final 位于 `output/final`。

## 3. 并发与写入边界

- 全任务最多三个 `calling`，且必须属于不同 `image_id`。
- 全任务 `calling + staged + unresolved` 最多三个；同图存在任一未终结 attempt 时禁止新调用。
- 同图三个版本固定由同一生成 Subagent 串行调用；不得把 V1/V2/V3 分给不同代理抢占三个槽。
- `serial` attempt 必须全任务独占；存在其他未终结 attempt 时不得建立。
- 生成 Subagent 只查看本图输入、调用渠道并返回结果；检查 Subagent 只执行 `view_image` 和七项检查。两者都不得写 job、JSONL 或产物文件。
- 只有主 Session 串行运行 `reserve/stage/fail/capture/finalize/verify`。`reserve/stage/fail/capture` 原子更新 attempt、staged 元数据或清单状态，不得手工补写这些字段。

环境资源不足时只降低实际并发数。负责人要求赶进度、允许同图并发、允许自检或允许子代理加锁写 JSON，都不能放宽上述边界。

## 4. 调用与暂存生命周期

每次渠道调用按以下顺序执行：

1. 主 Session 确认任务已获批、图号有独立生成 Session，并保存新的提示词和专用快照。快照只用于调用审计，不用于 job v2 来源认领。
2. 主 Session 用 `reserve` 显式登记 `attempt_no`、`dispatch_mode`、产物目标、提示词、快照和渠道源目录。命令成功后才占用调用槽并允许分派。
3. 生成 Subagent 发起一次渠道调用，只返回 `image_id`、`attempt_no`、调用结果、明确源路径或缺失原因和提示词信息，不写任务文件。`call_started_at` 只由 `reserve` 生成，Subagent 返回值不得覆盖。
4. 主 Session 收到明确路径后立即运行 `stage --source`。脚本先排他写入 attempt 专属 `staged/<attempt-no>.identity.json` 来源身份，再把来源排他复制到 `staged/<attempt-no>.png`；复制前后原来源哈希和 staged 哈希必须一致。job 成功写回后清理身份 sidecar；中断恢复必须同时匹配同一 attempt、规范来源路径、来源哈希和 staged 哈希，无可验证 sidecar 的孤儿一律拒绝。
5. 检查 Subagent 只读取 staged 副本，逐张执行 `view_image`，返回身份、时间、非空结论、七项布尔检查和拒绝原因。
6. 主 Session 用 `capture` 消费 staged attempt，排他保存产物、追加清单并把 attempt 原子更新为 `accepted` 或 `rejected`。
7. 无产物或渠道错误由主 Session 用 `fail` 记录；不得删除、覆盖或重编号历史 attempt。

attempt 合法流转为：

```text
calling -> staged -> accepted | rejected
calling -> failed
calling -> unresolved -> staged -> accepted | rejected
                      -> failed
staged  -> failed
```

`accepted/rejected/failed` 是终态。`timeout/interrupted` 且无法确认渠道已终止时必须进入 `unresolved`，继续占用同图和 pending 槽；只有渠道迟到的明确路径能由 `stage` 把原 attempt 转为 `staged`，否则保持阻塞。

## 5. 来源模式

job v2/清单 v6 只允许：

- `tool_return`：direct/revision 的渠道调用明确返回当前 attempt 的唯一绝对源路径。
- `derivation`：final 从已通过验收的 direct/revision 派生。

parallel 与 serial 都必须提供明确路径。即使快照后只有一个新增文件，也不能证明共享目录中的图片属于当前调用；job v2 禁止 `snapshot_diff`。job v1/清单 v5 的既有串行 `snapshot_diff` 只为旧任务兼容保留，不得迁移到新 task。

调用完成但没有明确路径时，以 `completed_without_path` 终结。脚本强制其下一 attempt 只能在全任务排空后用新提示词、新快照执行全局独占的 serial 重试；parallel reserve 必须失败。重试仍须返回明确路径。原渠道来源的规范绝对路径和 SHA256 都必须全任务唯一；越界路径、不可读图片或归属不明都不能按文件名、最新时间、大小、时间窗口、唯一快照差异或视觉相似度补判。

## 6. 产物、清单与检查

- `direct`：一次完整 PNG 直出；通过独立检查后才占 `direct01` 至 `direct03`。
- `revision`：三个当前有效 direct 齐全后，由渠道内编辑产生；按既有父级和文字专用修订规则登记，不占三版。
- `final`：只做格式/尺寸派生，来源必须是通过验收的 direct/revision。

job v2 的 direct/revision 使用清单 schema v6：`source_path/source_sha256` 指向稳定 staged 副本，`provider_source_path/provider_source_sha256` 保存渠道原来源，并记录 `dispatch_mode`、`staged_at` 和 `provenance_mode: tool_return`。v6 final 使用 `provenance_mode: derivation`，从父级推导调度模式，不重复写 `dispatch_mode`，并固定写 `visual_checks: null`；独立终检只登记在 job 的 `execution.final_inspections`。job v1 继续按串行语义写 schema v5，v5 final 保留复制父级 `visual_checks` 的兼容行为；同一 task 不得混用版本。

direct/revision 的检查者必须同时不同于生成 Session 和 `main_session_id`。检查时间不得早于 `staged_at`；`visual_checks` 固定包含：

- `current_product`、`english_only`、`no_pollution`
- `product_preserved`、`scale_correct`、`text_correct`
- `platform_compliant`

accepted 七项必须全为 `true`；rejected 至少一项为 `false`，必须有具体 `rejection_reason` 且不占 direct 序号。final 清单不复制来源检查结果；其独立终检仍由主 Session 将检查 Subagent 回传内容原样写入 `execution.final_inspections`。

清单和 attempt 保存绝对路径、SHA256、审批范围、Session、提示词、快照、来源、目标、检查和血缘字段。具体 job 字段见 [task-and-prompt-contract.md](task-and-prompt-contract.md)，命令与恢复见 [delivery-and-validation.md](delivery-and-validation.md)。

## 7. 失败与交接

生成 Subagent 不给出验收结论；检查 Subagent 不提交状态。`failure_type` 只使用下表七项：

| `failure_type` | 使用条件 | attempt 结果 |
|---|---|---|
| `completed_without_path` | 渠道已结束，但没有返回明确路径 | `failed` |
| `timeout` | 超时且无法确认调用终止 | `unresolved` |
| `interrupted` | 中断且无法确认调用终止 | `unresolved` |
| `timeout` / `interrupted` | 已确认调用终止，并传 `termination_confirmed=true` | `failed` |
| `provider_error` | 渠道明确报错且调用已结束 | `failed` |
| `source_invalid` | 明确路径越界、不可读、非 PNG、重复或不属于当前 attempt | `failed` |
| `stage_error` | 调用已结束，但暂存无法完成且没有可恢复的同哈希孤儿 | `failed` |
| `other` | 其他已确定、无法归入以上类别的失败；原因必须具体 | `failed` |

`fail` 必须记录 `failure_reason`、`failure_recorded_at` 和 `termination_confirmed`。终止不明时只等待原 attempt 的迟到明确路径；确认终止后可把原 unresolved attempt 转为 failed。检查 Subagent 暂时不可用时保留 `staged` 等待恢复，不得用失败分类释放槽位。已暂存但视觉不合格时仍用 `capture` 登记 rejected，保留证据。

已接受 direct 后验失效时，不改旧记录或覆盖路径；用更大 `attempt_no` 追加 replacement，沿用 `direct_index`，填写 supersession 关系，再重建失效血缘的 final。
