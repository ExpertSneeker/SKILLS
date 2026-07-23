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
- 渠道结果暂存：`output/temp/<task-id>/<image-id>/staged/<attempt-no>.png`
- 作废/污染图片：`output/temp/rejected-imagegen`
- 最终交付：`output/final`
- imagegen 全局生成目录：运行时 `$CODEX_HOME/generated_images`

全局目录可能同时包含其他 Session、产品、平台和语言的图片，不能视为当前任务专用目录。

## 3. 输入与 `view_image`

每个子 Session 从 Image 1 重新编号。所有准备提供给 imagegen 的产品、面料、细节、版式、风格、场景和插入素材，必须在本 Session 中逐张执行 `view_image`，核对可读性与角色，并把查看事件结构化返回主 Session；生成 Subagent 不直接写任务 JSON。

产品实拍图必须作为强制输入。layout/style/scene 参考只影响其登记角色；提示词明确产品外观以产品/面料垫图为准，不得使用文字重新描述结构、纹理、缝线、厚度或形状。只有本图 `allowed_product_changes` 明确批准颜色变化时，才能按 `color_evidence` 的证据和精度表达目标颜色；其他颜色保持垫图。输入传递方式严格采用运行时 `$imagegen` 支持的机制。

## 4. 跨图调用与来源定位

`imagegen` 采用 `cross_image_only`：最多三个不同图号并行；同图的三个版本由同一生成 Subagent 串行调用。每次调用执行：

1. 主 Session 保存新的 `.txt` 提示词，并用 `snapshot` 对全局目录建立不可复用的调用前快照；快照只用于审计，不用于认领 job v2 来源。
2. 主 Session 运行 `reserve` 原子登记 attempt；成功后才把一次调用分派给对应图号的生成 Subagent。生成者不得写 job 或清单。
3. 生成 Subagent 重新 `view_image` 本图输入，执行一次 `$imagegen`，返回明确源路径或缺失原因。
4. 主 Session 立即运行 `stage --source`。parallel 与 serial 都必须传渠道明确路径；脚本将源图排他固化到本图固定 staged 路径。

任一调用完成但没有路径时，用 `fail --failure-type completed_without_path` 终结原 attempt；排空后可用新 attempt、新快照串行重试，但重试仍须返回明确路径。timeout/interrupted 且无法确认工具已终止时进入 `unresolved`，继续占槽；不得建立同图新 attempt。若工具后来返回明确路径，只能用该路径 `stage` 原 attempt；若已确认工具终止，传 `--termination-confirmed` 把原 attempt 记为 failed。

全局目录可能同时混入其他任务。即使快照后恰好只有一张新增图片，也不能证明它属于当前调用；禁止扫描或按时间窗口、最新文件、大小、唯一差异或视觉相似度选择。明确返回路径越界、不可读、非 PNG 或已归属其他 attempt 时立即失败。

## 5. 输出检查与登记

生成 Subagent 不得验收自己的输出。主 Session 只把 staged 副本分派给不同于生成 Session 的检查 Subagent；检查 Subagent 先执行 `view_image`，再逐项填写渠道协议中的七个 `visual_checks`。无法创建检查 Subagent 时阻塞，不得由主 Session 或生成 Subagent 补填。

- 合格、PNG、正方形且与已有有效直出的图片/提示词哈希不同：保存到 direct 目录，以缺失的 `direct_index` 登记 `accepted direct`。
- 非正方形、产品不符、其他语言/品牌/Session 混入、文字错误或任一视觉检查失败：保存到 rejected 目录，登记 `rejected direct`，填写原因，不传 `--direct-index`。
- 来源无法唯一确认：不暂存、不登记虚构产物，按第 4 节进入 failed/unresolved；受控串行重试也必须取得明确路径。

检查 Subagent 必须返回 `inspection_session_id`、带时区的检查时间和非空检查结论，不写 job/清单。`capture` 通过检查参数消费 staged 副本，原子追加清单并归档 attempt；job v2 禁止传渠道 `--source` 或外部 `--call-started-at`，调用时间只从 attempt 读取。不要手工复制或补写 attempt、staged 元数据和清单状态。

## 6. 三版与文字修正

三个有效直出必须来自三次串行调用和三个实质不同的提示词；作废尝试可以使 `attempt_no` 大于 3，但不占 `direct01` 至 `direct03`。

画面英文有错误时只能：

1. 修改提示词后重新调用 imagegen，得到新的完整直出；或
2. 三个有效 direct 已齐全后，使用运行时 `$imagegen` 明确支持的渠道内编辑，仅修正目标文字并重复产品不可变项。错字源图必须已登记为“仅 `text_correct=false`、其他检查全通过”的正方形 PNG rejected 产物；修正结果以 `revision` 登记并关联该父级。

三版未齐时只能继续完整重生，不能先登记 revision 再补三版。禁止用 Pillow、HTML/CSS、画布、Office、图像编辑器或其他本地工具覆盖文字。渠道内 `revision` 不能代替缺失的三个有效 `direct`。

## 7. 终稿

三个有效直出齐全后，优先选择产品还原最准、比例最合理、英文最准确、构图最稳定且最符合美国站设计规则的版本。若选择渠道内 `revision`，先确保其父级和验收记录完整。最终只用 `artifact_tracker.py finalize` 从选中产物派生 `1000x1000` PNG。

每个 final 生成后必须交给同时不同于对应生成 Session 和 `main_session_id` 的检查 Subagent 执行 `view_image` 和七项检查；把 `artifact_id`、检查 Session、时间、非空结论及七项结果写入 `_temu_job.json.execution.final_inspections`。v6 final 清单的 `visual_checks` 固定为 `null`，不能复制父级检查。只有该 final 恰好有一条独立且全部通过的终检记录时才运行 `verify` 并计入交付。

已接受的 direct 后验失效时，按渠道协议生成 replacement direct；imagegen 的替代文件名为 `<基础名>_direct<序号>_replacement<attempt_no>.png`，`capture` 同时传 `--supersedes-artifact-id` 和 `--supersession-reason`。不得覆盖原 direct；旧血缘的 final 失效后使用下一个 `_vNN` 名称重新派生。
