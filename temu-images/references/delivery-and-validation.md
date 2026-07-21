# 交付、恢复与验收

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

`attempt_no` 每次渠道调用递增，包括超时和作废调用。`direct_index` 只在直出通过全部检查后分配，按当前缺失项填 1、2、3。作废版本、渠道内 `revision` 和 `final` 的 `direct_index` 必须为空。

每个图号完成三版的条件是：恰好拥有 `direct01`、`direct02`、`direct03` 三条有效记录；三张目标图片 SHA256 两两不同；三个提示词 SHA256 两两不同；三张均为正方形；每张都由非生成者的检查 Subagent 执行 `view_image`，且七项视觉检查全部通过。调用三次或生成者自检不等于完成三版。

若已有有效 direct 后验失效或审批范围发生变化，以追加式 replacement 取代：新记录沿用其 `direct_index`，指向 `supersedes_artifact_id` 并填写原因。验证时只有当前审批范围且位于替换链末端的记录有效；旧文件和清单行保留，不覆盖、不删除、不改状态。

## 4. 产物工具用法

统一使用 Skill 自带脚本；先运行 `--help` 获取中文参数说明：

```powershell
python <skill目录>/scripts/artifact_tracker.py --help
python <skill目录>/scripts/artifact_tracker.py snapshot --source-dir <渠道生成目录> --snapshot-path <唯一快照.json>
python <skill目录>/scripts/artifact_tracker.py capture <按帮助提供全部字段>
python <skill目录>/scripts/artifact_tracker.py finalize --manifest <清单.jsonl> --source-artifact-id <产物编号> --destination <最终.png>
python <skill目录>/scripts/artifact_tracker.py verify --manifest <清单.jsonl>
```

`capture` 对目标文件使用排他创建，绑定一次性快照，验证复制前后来源哈希，并在清单追加失败时撤销孤立目标。每次必须传 `--inspection-session-id`、`--inspection-checked-at` 和 `--inspection-notes`，检查 Session 不得等于生成 Session。`revision` 必须提供 `--parent-artifact-id`；replacement direct 必须提供 `--supersedes-artifact-id` 和 `--supersession-reason`。`finalize` 只在三个当前有效 direct 齐全后接受已通过的正方形 `direct/revision`，固定输出 `1000x1000` PNG。不要绕过脚本手工写清单或覆盖文件。

`capture`、`finalize` 和 `verify` 会从清单位置自动定位 `output/temp/<task-id>/_temu_job.json`，重新计算审批范围哈希，并核对当前确认与独立 Session 查看记录；不需要额外传任务 JSON 参数。`approval.status` 不是 `approved`、哈希变化、确认原文缺失、Session 未分派或输入未在本 Session 查看时，工具必须失败。

## 5. 中断恢复

恢复任务时按以下顺序进行：

1. 读取 `_temu_job.json`、清单和现有提示词，不依赖聊天记忆判断完成度。
2. 运行 `verify`；同时核对任务 JSON 中每图的 `attempt_no`、产物编号和状态。
3. 当前有效 direct 文件缺失、哈希变化、视觉误判或审批范围已变化时视为后验失效，保留证据并生成带 supersession 关系的 replacement；不能重写旧清单哈希来掩盖。失效 direct 的 revision/final 血缘不再计入完成度。
4. 从缺失或失效的图号和 `direct_index` 继续；新调用使用严格递增的 `attempt_no`、新提示词文件和新快照文件。
5. 超时、工具中断或未稳定进入下一次调用的尝试不得标记完成。没有唯一来源时重新调用。
6. 三版齐全后才允许渠道内 revision、选版和派生 final。final 必须由非生成者的检查 Subagent 独立终检并写入 `execution.final_inspections`，再运行 `verify`。具体 final 文件名按未占用的 `_vNN` 递增，任务审批只绑定稳定的 final 目录和文件名前缀，不因技术版本号递增而失效。

## 6. 业务验收

finalize 完成后，主 Session 必须把每张 final 分派给不同于生成 Session 的检查 Subagent。检查 Subagent 逐图执行最终 `view_image`，并对照任务 JSON、素材基准和设计合规文件检查：

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
