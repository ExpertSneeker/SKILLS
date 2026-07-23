# 交付、恢复与验收

## 目录

1. [允许的本地处理](#1-允许的本地处理)
2. [命名与路径](#2-命名与路径)
3. [尝试号与直出序号](#3-尝试号与直出序号)
4. [产物工具用法](#4-产物工具用法)
5. [中断恢复](#5-中断恢复)
6. [业务验收](#6-业务验收)
7. [完成条件](#7-完成条件)

## 1. 允许的本地处理

本地工具只允许复制、格式转换、尺寸调整、哈希计算和文件保存，不得改变画面内容。最终尺寸调整由 `artifact_tracker.py finalize` 执行。任何重绘、抠改产品、合成新内容、本地排版或文字覆盖都不属于技术处理，必须回到生图渠道。

## 2. 命名与路径

所有目标目录从所选渠道适配器和 `_temu_job.json.target_paths` 读取并转换为绝对路径；通用交付规则不硬编码渠道目录名。文件名使用：

- 首个有效直出：`<产品名>_<图型>_<图号>_direct01.png` 至 `direct03.png`
- 后验替代直出：`<产品名>_<图型>_<图号>_direct02_replacement04.png`，其中序号沿用被替换 direct，末尾为本次 `attempt_no`
- 渠道内修订：`<产品名>_<图型>_<图号>_revision01.png`
- 作废尝试：`<产品名>_<图型>_<图号>_attempt<尝试号>_rejected.png`
- 最终图：`<产品名>_<图型>_<图号>_v01.png`；旧 final 因上游替换失效时使用下一个 `_vNN`

文件名中的产品名应稳定且适合 Windows 文件系统。同一路径禁止覆盖；重做时增加尝试号、replacement、修订号或最终版本号，保留旧文件和血缘。

## 3. 尝试号与直出序号

每个图号的 `attempt_no` 随每次渠道调用严格递增，包括超时和作废调用；不同图号各自从 1 开始。`direct_index` 只在直出通过全部检查后分配，按当前缺失项填 1、2、3。作废版本、渠道内 `revision` 和 `final` 的 `direct_index` 必须为空。

每个图号完成三版的条件是：恰好拥有 `direct01`、`direct02`、`direct03` 三条有效记录；三张目标图片 SHA256 两两不同；三个提示词 SHA256 两两不同；三张均为正方形；每张都由非生成者的检查 Subagent 执行 `view_image`，且七项视觉检查全部通过。调用三次或生成者自检不等于完成三版。

若已有有效 direct 后验失效或审批范围发生变化，以追加式 replacement 取代：新记录沿用其 `direct_index`，指向 `supersedes_artifact_id` 并填写原因。验证时只有当前审批范围且位于替换链末端的记录有效；旧文件和清单行保留，不覆盖、不删除、不改状态。

## 4. 产物工具用法

统一使用 Skill 自带脚本；先运行 `--help` 获取中文参数说明：

```powershell
python <skill目录>/scripts/artifact_tracker.py --help
python <skill目录>/scripts/artifact_tracker.py snapshot --source-dir <渠道生成目录> --snapshot-path <唯一快照.json>
python <skill目录>/scripts/artifact_tracker.py reserve --job <_temu_job.json> --image-id <图号> --attempt-no <尝试号> --dispatch-mode <parallel|serial> --artifact-kind <direct|revision> [--direct-index <1|2|3>] --prompt-id <编号> --prompt-path <提示词.txt> --source-dir <渠道生成目录> --snapshot-path <快照.json>
python <skill目录>/scripts/artifact_tracker.py stage --job <_temu_job.json> --image-id <图号> --attempt-no <尝试号> --source <渠道明确路径>
python <skill目录>/scripts/artifact_tracker.py fail --job <_temu_job.json> --image-id <图号> --attempt-no <尝试号> --failure-type <类型> --reason <具体原因> [--termination-confirmed]
python <skill目录>/scripts/artifact_tracker.py capture <按帮助提供全部字段>
python <skill目录>/scripts/artifact_tracker.py finalize --manifest <清单.jsonl> --source-artifact-id <产物编号> --destination <最终.png>
python <skill目录>/scripts/artifact_tracker.py verify --manifest <清单.jsonl>
```

`reserve` 只接受严格递增且由主 Session 显式提供的 `attempt_no`，原子校验固定并发策略、同图未终结 attempt、calling 上限和 pending 上限；`call_started_at` 只由脚本生成。最新 attempt 为 `completed_without_path` 时，下一次 `reserve` 强制使用全局排空后的 serial，parallel 会失败。job v2 的 `stage --source` 必填，parallel 与 serial 都只接受渠道明确路径，禁止用唯一快照差异认领共享目录图片。暂存目标固定为 `output/temp/<task-id>/<image-id>/staged/<attempt-no>.png`；复制前临时写入同目录 `<attempt-no>.identity.json`，中断收养必须同时匹配 attempt、规范来源路径、来源哈希和 staged 哈希，无身份日志的孤儿失败关闭。job v1/清单 v5 的旧 `capture snapshot_diff` 仅用于兼容原任务。

`fail` 使用 [provider-contract.md](provider-contract.md) 的固定 `failure_type` 和 `--reason`。终止不明的 `timeout/interrupted` 进入 `unresolved`；已确认终止时传 `--termination-confirmed`，从 calling 或 unresolved 进入 `failed`。不要把 unresolved 改回 pending、删除 attempt 或用租约过期释放槽位。

job v2 的 `capture` 只读取 staged 副本，调用方不得传 `--source` 或 `--call-started-at`；脚本从 attempt 读取 `reserve` 生成的规范调用时间，传入任何外部值都会阻塞。每次仍必须传 `--inspection-session-id`、`--inspection-checked-at` 和 `--inspection-notes`；检查 Session 不得等于生成或主 Session，检查时间不得早于 `staged_at`。`revision` 必须提供 `--parent-artifact-id`；replacement direct 必须提供 `--supersedes-artifact-id` 和 `--supersession-reason`。job v1/v5 继续使用原来的串行来源行为，并要求显式传 `--call-started-at`。

`stage/capture/finalize` 对目标使用排他创建，并在关闭前 `flush + fsync` 文件内容。同 attempt、同身份和同哈希的中断孤儿可由重跑命令收养；任一身份或哈希不同立即阻塞，禁止覆盖。`capture` 串行提交目标、清单 v6 和 attempt 终态；同步失败恢复进入命令前的完整清单字节，并只删除本次新建目标。`finalize` 使用相同的孤儿收养、幂等重放和精确回滚规则，只在当前图号排空且三个当前有效 direct 齐全后接受通过验收的正方形 `direct/revision`，固定输出 `1000x1000` PNG。v6 final 清单固定写 `visual_checks: null`，终检结果只写入 job；v5 final 保留旧兼容字段。

状态命令使用持久 `.lock` 文件上的操作系统句柄锁，锁顺序固定为 `manifest -> job`。进程退出会释放锁；锁文件本身可以保留，不代表任务仍被占用，也不得靠删除锁文件抢占写入。

`capture`、`finalize` 和 `verify` 会从清单位置定位对应 job，重算审批哈希并核对当前确认与 Session 查看记录。`finalize` 只因当前图号存在 calling/staged/unresolved 而阻塞，其他图号可继续；`verify` 和任务 complete 要求全任务没有未终结 attempt。不要手工写清单、attempt 或 staged 元数据。

## 5. 中断恢复

恢复任务时按以下顺序进行：

1. 读取 `_temu_job.json`、清单、staged 文件和提示词，不依赖聊天记忆；不得删除或重编号历史 attempt。
2. 逐图核对未终结状态：0 个可正常继续；1 至 3 个不同图号 calling 逐项等待；staged 继续独立检查/capture；非法上限、同图多个或 serial 混存立即阻塞。
3. `completed_without_path` 只有在全任务 calling/staged/unresolved 全部为 0 后，才可用新 attempt、新提示词/快照执行全局独占 serial 重试；重试仍须返回明确路径。
4. `timeout/interrupted` 且无法确认终止时保持 unresolved；迟到明确路径只归原 attempt 并可 `stage`。没有路径则继续阻塞，不重派同图；确认调用已终止后使用同一 attempt 和 `--termination-confirmed` 转为 failed。
5. 当前有效 direct 缺失、哈希变化、视觉误判或审批范围变化时，保留证据并生成带 supersession 的 replacement；不能重写旧清单哈希。失效 direct 的 revision/final 血缘不再计入完成度。
6. 从缺失或失效的 `direct_index` 继续；每次新调用使用严格递增 attempt、新提示词和新快照。同图仍由原生成 Subagent 串行完成。
7. 三版齐全后才允许 revision、选版和 final。final 由独立检查 Subagent 终检；主 Session 把返回的 `final_inspections` 原样写入 job，再运行 `verify`。final 文件名按未占用的 `_vNN` 递增。

## 6. 业务验收

finalize 完成后，主 Session 必须把每张 final 分派给同时不同于对应生成 Session 和 `main_session_id` 的检查 Subagent。检查 Subagent 逐图执行最终 `view_image`，并对照任务 JSON、素材基准和设计合规文件检查：

- 图号、输出类型、逐图目标、卖点和需求表英文原文一致。
- 尺寸文案优先使用美国市场常用的 `inch`；需求表已有明确单位时按原要求执行，整套单位表达必须自然、统一且换算可追溯。
- 产品/面料/颜色/结构/尺寸、场景比例和售卖数量真实。
- 主图不裁切或误导；副图信息准确，整套视觉一致。
- 无中文、乱码、错拼、遮挡、溢出、跨图污染或第三方侵权内容。
- 无新增认证、医疗功效、排名、绝对承诺、价格优惠或其他无依据内容。
- 每个图号三个有效直出、选中来源、必要的渠道内修订和最终图均有完整血缘。

检查 Subagent 回传 `artifact_id`、`inspection_session_id`、带时区时间、非空结论和七项严格布尔检查，主 Session 原样写入 `execution.final_inspections`。主 Session 只负责分派、汇总和机械 `verify`，不得代替检查或修改检查结论。若视觉检查发现错误，把相应产物登记或保留为不合格，回到渠道重生/渠道内编辑；不得本地修补后交付。

## 7. 完成条件

只有同时满足以下条件才能把图号和任务写为 `complete`：

- 清单 `verify` 返回 `ok: true` 且退出码为 0。
- 每个图号有三个有效直出，并且当前审批范围恰好有一个合法 `1000x1000` final。
- 每个 direct/revision 具备独立产物检查记录，每个 final 恰好具备一条独立终检记录；最终业务验收全部通过，所有阻塞和冲突已解决。
- final 文件位于 `output/final`，不是 Codex 默认生成目录或临时目录。
- 已向用户报告最终绝对路径、所选来源产物、最终提示词路径、渠道和验证结果。
