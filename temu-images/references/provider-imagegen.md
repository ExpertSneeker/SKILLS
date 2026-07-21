# `$imagegen` 渠道适配器

本文件只定义 TEMU 工作流对 `$imagegen` 的渠道差异。通用生图参数、输入语义和工具行为以运行时安装的 `$imagegen` Skill 为准，不在这里复制。

## 1. 依赖与能力

- `provider` 固定写 `imagegen`。
- 每个图号的子 Session 在任何调用前必须完整读取 `$imagegen` Skill，并按它当时声明的默认工具与编辑语义执行。
- `$imagegen` Skill 或其要求的工具不可用时阻塞，不得换成未登记渠道。
- 新生成、参考图生成和渠道内编辑是否可用，以运行时 `$imagegen` 为准；本适配器不承诺不存在的参数。
- `artifact_tracker.py` 运行环境必须有 Pillow。缺失时脚本会用中文报错；在当前 Python 环境安装 Pillow 或改用已具备 Pillow 的运行时，禁止把依赖写入 Skill 目录。

## 2. 固定路径

以下路径均相对于产品文件夹，并在执行时转换为 Unicode 安全的绝对路径：

- 有效直出：`output/gpt-images-2-direct`
- 清单：`output/gpt-images-2-direct/_imagegen_manifest.jsonl`
- 任务状态、提示词和快照：`output/temp/<task-id>/<image-id>`
- 作废/污染图片：`output/temp/rejected-imagegen`
- 最终交付：`output/final`
- imagegen 全局生成目录：运行时 `$CODEX_HOME/generated_images`

全局目录可能同时包含其他 Session、产品、平台和语言的图片，不能视为当前任务专用目录。

## 3. 输入与 `view_image`

每个子 Session 从 Image 1 重新编号。所有准备提供给 imagegen 的产品、面料、细节、版式、风格、场景和插入素材，必须在本 Session 中逐张执行 `view_image`，核对可读性与角色并写回任务 JSON。

产品实拍图必须作为强制输入。layout/style/scene 参考只影响其登记角色；提示词明确产品外观以产品/面料垫图为准，不得使用文字重新描述结构、纹理、缝线、厚度或形状。只有本图 `allowed_product_changes` 明确批准颜色变化时，才能按 `color_evidence` 的证据和精度表达目标颜色；其他颜色保持垫图。输入传递方式严格采用运行时 `$imagegen` 支持的机制。

## 4. 串行调用与来源定位

本任务同一时间只允许一个未归档的 imagegen 调用。每次调用执行：

1. 将最终提示词保存为新的 `.txt` 文件，不覆盖旧提示词。
2. 在调用前用 `artifact_tracker.py snapshot` 对全局生成目录建立本次调用专用快照；快照文件名包含图号和 `attempt_no`，不得覆盖或复用于其他调用，并把路径与 SHA256 追加到任务 `attempts`。
3. 快照完成后记录 UTC `call_started_at`，再发起一次 imagegen 调用。一个调用只服务一个图号和一个提示词。
4. 调用返回后，若工具给出明确文件路径，`capture` 使用 `--source`，来源模式为 `tool_return`。
5. 若没有明确路径，`capture` 不传 `--source`，只允许脚本从调用前后快照中找到唯一新增或变更图片，来源模式为 `snapshot_diff`。
6. 差异为零或大于一、路径异常、图片不可读或调用超时无可归属文件时，本次失败；禁止按时间、大小或视觉相似度选择。

明确返回路径始终优先于快照差异，即使全局目录同时出现其他候选。

## 5. 输出检查与登记

生成 Subagent 不得验收自己的输出。对定位到的每张候选，主 Session 必须分派给不同于生成 Session 的检查 Subagent；检查 Subagent 先执行 `view_image`，再逐项填写渠道协议中的七个 `visual_checks`，检查当前产品、语言、跨图污染、产品还原、实际比例、英文文字和平台合规。无法创建检查 Subagent 时阻塞，不得由主 Session 或生成 Subagent 补填。

- 合格、PNG、正方形且与已有有效直出的图片/提示词哈希不同：保存到 direct 目录，以缺失的 `direct_index` 登记 `accepted direct`。
- 非正方形、产品不符、其他语言/品牌/Session 混入、文字错误或任一视觉检查失败：保存到 rejected 目录，登记 `rejected direct`，填写原因，不传 `--direct-index`。
- 来源无法唯一确认：不复制、不登记虚构产物，只在 `_temu_job.json` 记录失败并重新调用。

检查 Subagent 必须返回 `inspection_session_id`、带时区的检查时间和非空检查结论。`capture` 必须通过 `--inspection-session-id`、`--inspection-checked-at`、`--inspection-notes` 传入这些值；脚本会拒绝检查 Session 与生成 Session 或顶层 `main_session_id` 相同的产物。每次捕获成功后立即读取脚本返回的 JSON，回写 `artifact_id`、路径、哈希、尺寸、来源模式、状态和检查字段。不要手工复制后补写清单。

## 6. 三版与文字修正

三个有效直出必须来自三次串行调用和三个实质不同的提示词；作废尝试可以使 `attempt_no` 大于 3，但不占 `direct01` 至 `direct03`。

画面英文有错误时只能：

1. 修改提示词后重新调用 imagegen，得到新的完整直出；或
2. 三个有效 direct 已齐全后，使用运行时 `$imagegen` 明确支持的渠道内编辑，仅修正目标文字并重复产品不可变项。错字源图必须已登记为“仅 `text_correct=false`、其他检查全通过”的正方形 PNG rejected 产物；修正结果以 `revision` 登记并关联该父级。

三版未齐时只能继续完整重生，不能先登记 revision 再补三版。禁止用 Pillow、HTML/CSS、画布、Office、图像编辑器或其他本地工具覆盖文字。渠道内 `revision` 不能代替缺失的三个有效 `direct`。

## 7. 终稿

三个有效直出齐全后，优先选择产品还原最准、比例最合理、英文最准确、构图最稳定且最符合美国站设计规则的版本。若选择渠道内 `revision`，先确保其父级和验收记录完整。最终只用 `artifact_tracker.py finalize` 从选中产物派生 `1000x1000` PNG。

每个 final 生成后必须交给非生成者的检查 Subagent 执行 `view_image` 和七项检查；把 `artifact_id`、检查 Session、时间、非空结论及七项结果写入 `_temu_job.json.execution.final_inspections`。只有该 final 恰好有一条独立且全部通过的终检记录时才运行 `verify` 并计入交付。不得把 direct/revision 的检查记录复制成 final 终检。

已接受的 direct 后验失效时，按渠道协议生成 replacement direct；imagegen 的替代文件名为 `<基础名>_direct<序号>_replacement<attempt_no>.png`，`capture` 同时传 `--supersedes-artifact-id` 和 `--supersession-reason`。不得覆盖原 direct；旧血缘的 final 失效后使用下一个 `_vNN` 名称重新派生。
