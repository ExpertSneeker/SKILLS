# imagegen 适配器

选择 `$imagegen` 时，先完整读取其 skill，只使用内置 `image_gen` 工具；不要调用 `scripts/image_gen.py`、CLI/API 回退模式或要求 `OPENAI_API_KEY`。本适配器只补充 TEMU 工作流的来源追踪和防串图要求。

## 调用与来源

- 每个 direct 使用一个全新单版生成 Subagent，并且只允许调用一次内置 `image_gen`；同一图号的三个 Subagent 必须串行执行，同时调用 `image_gen` 的单版生成 Subagent 最多三个，其他 Subagent 不计入此上限。
- 所有输入必须有本地路径，并使用 `referenced_image_paths` 显式传入，不得依赖“最近图片”或其他 direct 的会话上下文。
- `referenced_image_paths` 中的产品实拍只允许使用 `2560px拍摄图/_manifest.json` 登记的目标路径；禁止使用原始拍摄图。当前任务中已执行 `view_image` 并记录角色的面料、颜色、结构、版式或场景参考可以作为非产品参考路径。
- 禁止使用 `num_last_images_to_include`；任何输入缺少本地路径时阻塞当前 direct，取得准确路径并重新执行 `view_image` 后再生成。
- 禁止把其他 direct 作为输入、参考图或上下文；调用失败或结果作废时，使用新的替补 Subagent 重做同一 direct 编号。
- `$CODEX_HOME/generated_images` 是全局生成目录，可能混入其他 Session、产品、平台或语言的图片；禁止按“最新时间”“最新文件”或“最大文件”猜测复制。
- 每次调用前记录任务 ID、平台、产品名、图片编号、版本号、目标文件名、提示词编号和调用开始时间，并对全局生成目录建立文件快照。
- 并行调用只接受当前工具为本次调用返回的明确源文件路径，不得通过排除其他调用文件、完成时间、文件名或跨调用快照差异认领来源；没有明确路径的并行结果立即作废。
- 并行结果缺少明确源路径时，等待所有当前生成调用结束，由全新替补 Subagent 单独重做当前 direct；只有该独占调用允许用调用前后快照差异定位，且候选必须唯一，恢复期间不得派发其他生成调用。
- 候选不唯一、路径不明、时间异常、尺寸异常或内容不符时，判定为污染风险，不得复制或计入 direct 三版。
- 每次调用只接受可唯一归属的一张源图。

## 保存与清单

- 并行生成 Subagent 只向主 Agent 返回明确源文件路径和完整来源记录，不直接复制文件或写共享 manifest；主 Agent 收到结果后按返回顺序逐张处理。
- 主 Agent 将有效 direct 图串行复制到 `./output/gpt-images-2-direct`，并记录源文件绝对路径、源文件 SHA256、目标文件 SHA256、尺寸、复制时间、提示词编号和校验结果。
- 主 Agent 是 `./output/gpt-images-2-direct/_imagegen_manifest.jsonl` 的唯一写入者，每张有效 direct 逐行串行写入；完成复制和登记后才派发当前 direct 的独立验收。
- 污染文件如已复制，移入 `./output/temp/rejected-imagegen` 或在清单中标记为 `rejected`，不得进入最终交付或计入三版。
- direct 图必须属于当前 TEMU 产品，使用英文画面并符合目标比例；出现其他产品、品牌、语言或 Session 内容时立即作废并重新生成。

## 中断恢复

- 每生成一张就立即保存到直接生成目录，不等三版全部完成。
- 调用或 Session 中断、超时或未稳定进入下一次生成时，核对直接生成目录的文件数量、大小和时间戳。
- 从缺失的图型与 `direct` 序号继续生成；未补齐前不得标记完成。
