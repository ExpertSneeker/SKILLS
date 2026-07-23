---
name: temu-images
description: 规划、生成、追踪并验收 美国 TEMU 平台商品图片。适用于根据产品文件夹、需求表、产品实拍图、真实尺寸、VI、面料或色卡及版式参考，制作主图、副图、SKU、颜色、规格、尺寸或卖点图片；也用于在关键依据不全、素材不可读、用户催促跳过门槛或指定未知渠道时给出强制阻塞。执行开工确认、一个图号一个独立子 Session、渠道适配器、三版直出、来源追踪和 1000x1000 终验。
---

# TEMU 美国站图片

## 目标

制作符合 TEMU 美国站要求的商品图片。确保产品真实性和平台合规；原始产品文件只读，所有工作产物写入产品文件夹下的 `output`。

## 强制门槛

开始任何生图前，必须同时满足以下条件：

1. 任务是 TEMU 商品图片，主副图或详情页。
2. **必需素材**均已取得并读取：需求表、真实产品尺寸、清晰产品实拍图、输出类型。缺少任意一项立即阻塞。
3. **条件性素材**已完成盘点：VI/brand guide、logo 规范、面料图、色卡图、颜色代号图、细节图、版式/场景参考、禁用信息等缺失本身不阻塞；一旦存在就必须读取、检查、登记并按适用范围使用，不得因其“可选”而跳过。无法判断内容的 WPS `DISPIMG` 在成功查看前按关键素材处理。
4. 所有素材图片均已由素材检查 Subagent 执行 `view_image`，并登记检查 Session、时间和结论；主 Session、后续生成 Session 的查看均不能替代该记录。
5. 已建立产品/面料基准和整套统一视觉基准，且没有依靠猜测补全产品信息。
6. 已生成 `output/temp/<task-id>/_temu_job.json`，并获得用户对本次任务范围和方案的明确确认。
7. 当前环境能够为每个图号建立独立生成子 Session，并能为素材和产物建立检查 Subagent。生成者不得检查或验收自己的产物，主 Session 不得代替检查 Subagent。
8. 所选渠道已有可读的 `references/provider-<渠道>.md` 适配器，且它要求的工具当前可用。

任一项不满足时，只报告阻塞项、缺失证据和恢复条件；不得生成预览、模板、假定版本或“仅供内部”的替代图片，也不得用责任转移绕过真实性或合规要求。

## 绝对禁止

- 不得用文生图凭空生成产品；含产品的生成必须提供对应实拍图作为强制输入。
- 不得在提示词中重新描述、推测或设计产品外观；产品结构、面料、纹理和比例只由垫图定义。颜色也由垫图定义，除非逐图 `allowed_product_changes` 已用需求表/色卡证据明确批准颜色变化。
- 不得按最新、最大、最像或时间窗口猜测全局生成目录中的来源图片。
- 不得在本地重绘画面、排版或覆盖文字。文字错误只能通过渠道重生或渠道内编辑修正。
- 不得并行生成同一图号的三个版本。同一图号固定由同一生成子 Session 串行完成；不同图号最多三个渠道调用并行，且必须通过产物工具占用调用槽。
- 生成 Subagent 和检查 Subagent 都不得写 `_temu_job.json`、JSONL 清单或产物文件；生成者不得自检，检查者不得提交产物状态。
- 不得将超时、中断、来源不明、非正方形、内容污染、未经独立检查或视觉检查失败的产物计入三个有效直出版本。

## 主流程

1. **读取与建档。** 完整读取 [intake-and-baseline.md](references/intake-and-baseline.md) 和 [design-and-compliance.md](references/design-and-compliance.md)。主 Session 读取需求表和结构化信息；素材检查 Subagent 逐张查看素材图片并回传记录，主 Session 据此建立证据基准。
2. **规划任务。** 按 [task-and-prompt-contract.md](references/task-and-prompt-contract.md) 登记 `main_session_id` 和完整 `material_inventory`，拆分图号、编写逐图目标与三版提示词策略，并创建 `_temu_job.json`。
3. **等待确认。** 向用户展示任务范围、输出顺序、原文文案、最小修正、颜色依据、人物选择和阻塞/冲突。只有 `approval.status` 为 `approved` 才能继续；范围变化后确认自动失效。
4. **选择渠道。** 先读 [provider-contract.md](references/provider-contract.md)，再读对应适配器。当前 `imagegen` 必须读 [provider-imagegen.md](references/provider-imagegen.md)，并在运行时完整读取 `$imagegen` Skill。
5. **跨图调度。** 每个图号建立一个独立生成子 Session，同图三版始终在该 Session 内串行；按 [provider-contract.md](references/provider-contract.md) 用 `reserve` 最多放行三个不同图号。生成 Session 只查看本图输入、执行一次渠道调用并返回结构化结果，不写任务或清单。
6. **暂存、独立检查与登记。** 主 Session 收到渠道明确路径后立即用 `stage` 排他暂存，再把 staged 副本交给独立检查 Subagent。检查者逐张执行 `view_image`，只返回检查身份、时间、非空结论、七项布尔检查和失败时的具体拒绝原因；主 Session 随后执行 `capture`。作废尝试保留记录，但不占 `direct01` 至 `direct03`。
7. **选版与终稿。** 每个图号取得三个提示词哈希不同、图片哈希不同、正方形且全部通过独立检查的有效直出后，选出最佳 `direct` 或渠道内 `revision`，再用 `finalize` 派生 `1000x1000` 最终 PNG。
8. **独立终检。** 将每个 final 交给同时不同于对应生成 Session 和 `main_session_id` 的检查 Subagent 执行 `view_image` 和七项检查，把唯一终检记录写入 `_temu_job.json.execution.final_inspections`；主 Session 只运行机械验证和汇总结果。
9. **完整验收。** 按 [delivery-and-validation.md](references/delivery-and-validation.md) 运行 `verify` 并交付明确路径。任何错误未清零都不得声称完成。

## 状态与阻塞

以下情况立即把任务或图号标为 `blocked`：必需素材缺失、关键素材不可读、证据相互冲突无法裁决、需求与平台规则冲突、用户尚未确认或确认已失效、独立生成 Session 或检查 Subagent 不可用、渠道适配器或依赖工具不存在、来源候选无法唯一归属。条件性素材仅因不存在不阻塞。无法确认渠道已终止的超时/中断保持 `unresolved` 并继续占槽；不得通过重派同图或快照猜测释放。恢复方法见交付参考文件。

## 产物工具

使用 `scripts/artifact_tracker.py` 执行机械性高风险操作：

- `snapshot`：记录调用前的图片状态。
- `reserve`：原子登记调用并占用槽位。
- `stage`：排他暂存唯一渠道来源。
- `fail`：原子登记失败分类；终止不明时保留 `unresolved`。
- `capture`：从 staged 副本排他保存 `direct/revision`、追加清单并归档 attempt。
- `finalize`：从通过验收的 `direct` 或 `revision` 派生 `1000x1000` 最终 PNG。
- `verify`：检查字段、路径、SHA256、尺寸、派生关系、三版完整性和最终图。

命令参数、路径和验收顺序见 [delivery-and-validation.md](references/delivery-and-validation.md)。不要手工修改所选适配器的 JSONL 清单。

## 参考文件路由

- [intake-and-baseline.md](references/intake-and-baseline.md)：素材盘点、需求表与 WPS 嵌图、颜色证据、产品/面料和视觉基准。
- [design-and-compliance.md](references/design-and-compliance.md)：美国站设计、人物与真实比例、文案、主副图和合规边界。
- [task-and-prompt-contract.md](references/task-and-prompt-contract.md)：确认、`_temu_job.json`、Session 分工、图片角色和提示词契约。
- [provider-contract.md](references/provider-contract.md)：所有生图渠道必须满足的能力、来源、失败与产物协议。
- [provider-imagegen.md](references/provider-imagegen.md)：当前 `$imagegen` 渠道的专用执行步骤和固定路径。
- [delivery-and-validation.md](references/delivery-and-validation.md)：命名、三版、修订、恢复、最终尺寸和完整验收。
- [evaluation-cases.md](references/evaluation-cases.md)：维护本 Skill 时使用的无 Skill 基线与有 Skill 回归场景。
