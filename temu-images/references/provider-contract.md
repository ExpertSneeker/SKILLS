# 生图渠道适配器协议

## 1. 适配器存在性

`provider` 的值必须对应 `references/provider-<provider>.md`。适配器必须在调用前完整读取；文件不存在、工具不可用或能力无法满足本协议时立即阻塞，禁止临时猜测参数、返回路径、编辑能力或失败语义。

未来新增渠道只新增一个适配器文件并通过本协议的评估场景，不复制或改写 TEMU 业务规则。适配器只描述渠道差异。

## 2. 适配器必须声明的能力

每个适配器必须明确：

- 渠道名、所需 Skill/工具及运行时读取要求。
- 支持的新生成、带参考生成和渠道内编辑能力。
- 输入图片传递方法、角色表达方法、输入数量或格式限制。
- 调用是否必须串行，以及如何隔离一个图号的上下文。
- 如何把候选路径交给独立检查 Subagent，并保证检查 Session 不等于生成 Session。
- 成功时是否返回明确源路径；无路径时是否允许唯一快照差异兜底。
- 渠道生成目录、任务 direct/temp/final 目录和清单路径。
- 超时、失败、多候选、不可读输出和内容污染的处理。
- 英文文字错误能够使用的渠道内重生或编辑方式。
- 产物交回主 Session 时需要的字段。

为使新增渠道不修改脚本，适配器路径必须落在产品文件夹的共同骨架：清单位于 `output/<渠道直出目录>`，有效 direct 与清单同目录，rejected 位于 `output/temp/rejected-<provider>`，revision 位于 `output/temp/<task-id>/<image-id>`，final 位于 `output/final`。适配器只决定渠道直出目录名、清单名和渠道全局源目录。

## 3. 调用生命周期

每次调用必须按这个顺序完成：

1. 确认任务已获批、当前图号拥有独立子 Session、渠道适配器已读取。
2. 重新核对本图输入角色，并逐张完成适配器要求的可视检查。
3. 保存不可覆盖、非空且可按 UTF-8 读取的 `.txt` 提示词文件；`attempt_no` 对本图每次调用严格递增，包括无产物超时。
4. 按适配器建立本次调用专用且不可复用的快照，先记录快照路径/哈希和 UTC 调用开始时间，在任务 JSON 追加状态为 `calling` 的当前尝试，再发起唯一一次渠道调用；上一次调用未归档前不得开始下一次。
5. 优先接收渠道明确返回的源路径；没有明确路径时只执行适配器允许的来源兜底。
6. 将候选交给同时不同于生成 Session 和 `_temu_job.json.main_session_id` 的检查 Subagent；检查 Subagent 逐张执行 `view_image`，返回身份、时间、非空结论和全部视觉检查。生成 Subagent 与主 Session 均不得代检。
7. 用 `artifact_tracker.py capture` 传入独立检查字段，排他保存并追加清单。只有已通过独立检查的正方形 `direct` 才分配 `direct_index`。
8. 把产物编号、来源模式、状态、拒绝原因和下一步写回 `_temu_job.json`。

## 4. 来源模式

清单只允许三种 `provenance_mode`：

- `tool_return`：渠道明确返回本次调用的一张可读源图片路径，优先使用。
- `snapshot_diff`：渠道未返回路径，调用前后图片状态差异恰好只有一个候选。
- `derivation`：`final` 从清单中已通过验收的 `direct` 或 `revision` 派生。

零候选、多候选、路径不存在、图片不可读或调用归属不明都不能通过视觉相似、文件名、最新时间、最大文件或时间窗口补判。

## 5. 产物类型与状态

- `direct`：渠道一次完整 PNG 直出。通过验收时才能占 `direct01`、`direct02` 或 `direct03`。
- `revision`：三个当前审批范围的有效 direct 齐全后，渠道内编辑产生的版本。必须指向同一任务、渠道、产品、图型、图号和审批范围下的合法父级；父级可以是已通过验收的 `direct/revision`，也可以是仅 `text_correct=false`、其余视觉检查均通过且文件完整的正方形 PNG `rejected direct/revision`。不占三版直出。
- `final`：只做格式/尺寸派生的最终 PNG，来源必须是已通过验收的 `direct` 或 `revision`。

状态只允许 `accepted` 或 `rejected`。`accepted direct/revision` 的 `rejection_reason` 必须为 `null`；`rejected` 必须有去空白后非空的具体原因且 `direct_index` 为 `null`。两种状态的 `visual_checks` 都必须包含七个必需键且所有值为严格布尔值；accepted 七项全为 `true`，rejected 至少一项为 `false`。超时且没有可归属文件时在任务 JSON 记录失败，不伪造清单产物。

## 6. 清单字段

每行 JSONL 使用 `schema_version: 5`，固定包含：

- 身份：`schema_version`、`artifact_id`、`task_id`、`provider`、`platform`、`product_name`、`image_id`、`image_type`、`immutable_identity_sha256`、`approval_scope_version`、`approval_scope_sha256`。
- 调用：`session_id`、`attempt_no`、`direct_index`、`artifact_kind`、`prompt_id`、`prompt_path`、`prompt_sha256`、`call_started_at`、`captured_at`、`snapshot_path`、`snapshot_sha256`。
- 来源与目标：`provenance_mode`、`source_path`、`source_sha256`、`target_path`、`target_sha256`、`width`、`height`。
- 验收与血缘：`status`、`visual_checks`、`inspection_session_id`、`inspection_checked_at`、`inspection_notes`、`rejection_reason`、`derived_from_artifact_id`、`supersedes_artifact_id`、`supersession_reason`。

`visual_checks` 对通过验收的 `direct` 和 `revision` 必须把以下键全部设为 `true`：

- `current_product`：当前任务产品和 SKU。
- `english_only`：无中文、乱码或其他错误语言。
- `no_pollution`：无其他图号、Session、产品、品牌或平台内容。
- `product_preserved`：结构、面料、纹理和比例符合垫图；颜色符合垫图或本图已批准的 `allowed_product_changes`，不存在其他变化。
- `scale_correct`：尺寸与场景参照真实。
- `text_correct`：英文文案准确、完整、可读。
- `platform_compliant`：符合需求表和 TEMU 美国站合规规则。

提示词、快照、来源和目标均记录绝对路径与 SHA256。`prompt_id` 必须是去空白后非空的字符串。`capture` 在读取来源和复制之前解析 `call_started_at` 并固定一次 UTC `captured_at`，必须满足快照创建时间 ≤ `call_started_at` ≤ `captured_at`，清单使用同一个已固定的 `captured_at`。同一快照只能登记一次；`tool_return` 也不能省略快照。清单只能由产物工具追加，不能人工删改以制造通过结果。

`direct/revision` 的三个检查字段必须来自实际执行 `view_image` 的独立检查 Subagent；`inspection_session_id` 不得等于生成 `session_id` 或顶层 `main_session_id`，检查时间必须位于调用开始与捕获之间，结论不得为空。`final` 清单行的三个字段固定为 `null`，其独立终检写入 `_temu_job.json.execution.final_inspections` 并由 `verify` 对账；不得把来源 direct 的检查结果复制成 final 终检。

`immutable_identity_sha256` 对 `task_id`、`provider`、`platform`、`product_name` 和按 `(image_id, image_type)` 排序的完整图片身份集合使用规范 JSON 计算。首条产物把当前 job 的完整身份绑定到清单；后续 direct/revision/final 必须使用同一值。当前 job 与任一历史清单行不一致时，`capture`、`finalize`、`verify` 全部阻塞，并要求建立新 task 和独立输出根目录/清单。

## 7. 失败与交接

渠道超时、中断或工具未稳定进入下一次调用时，本次不算完成。把提示词、快照、调用时间和失败原因追加到任务 JSON 的 `attempts`，再从缺失的图号和 `direct_index` 继续。任何已复制但来源或内容不合格的图片必须隔离并登记 `rejected`；不得进入最终目录。

已登记的 `accepted direct` 若后验发现文件损坏、哈希变化、视觉误判或审批范围已变化，不能删改旧记录、覆盖旧路径或把旧状态原地改成 rejected。用更大的 `attempt_no` 生成替代 direct，保持同一 `direct_index`，并通过 `supersedes_artifact_id` 指向当前有效旧记录、填写 `supersession_reason`。替代文件名追加 `_replacement<attempt_no>`；验证器只把当前审批范围且位于替换链末端的版本计入三版，并把从旧记录派生的 revision/final 视为失效，随后生成新 final。

生成 Subagent 向主 Session 交回候选路径和调用信息，不给出验收结论。检查 Subagent 单独交回：`inspection_session_id`、检查时间、非空结论、七项视觉检查及拒绝原因。主 Session 完成 `capture` 后汇总 `task_id`、图号、渠道、每次尝试号、提示词路径及哈希、产物编号、`direct_index`、状态、拒绝原因、源/目标路径与哈希、尺寸和仍缺版本。
