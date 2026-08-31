# imagegen 适配器

选择 `$imagegen` 时，先完整读取其 skill，只使用内置 `image_gen` 工具；不要调用 `scripts/image_gen.py`、CLI/API 回退模式或要求 `OPENAI_API_KEY`。本适配器只补充当前电商图片工作流的来源追踪和防串图要求。

## 调用与来源

- 按生成模块为每个 direct 派发一个全新单版生成 Subagent；该 Subagent 只允许调用一次内置 `image_gen`。
- 所有输入必须有本地路径，并使用 `referenced_image_paths` 显式传入，不得依赖“最近图片”或其他 direct 的会话上下文；调用前确认路径不超过 5 条。
- 输入超过 5 条时，在派发生成 Subagent 前把同一角色的辅助素材整理为已查看的拼版；主产品身份输入不得与其他角色合并，也不得用一次失败调用探测上限。
- `referenced_image_paths` 中的产品实拍只允许使用 `2560px拍摄图/_manifest.json` 登记的目标路径；禁止使用原始拍摄图。当前任务中已执行 `view_image` 并记录角色的颜色/面料、结构细节、插入或辅助素材可以作为其他实际生成输入。反推专用参考图禁止加入 `referenced_image_paths`。
- 禁止使用 `num_last_images_to_include`；任何输入缺少本地路径时阻塞当前 direct，取得准确路径并重新执行 `view_image` 后再生成。
- 禁止把其他 direct 作为输入、参考图或上下文；调用未产出文件或文件确认失败时，修正技术原因后可使用一个新的替补 Subagent 重做同一 direct 编号一次；第二次仍失败则按生成模块记录缺失并继续其他图号。
- `$CODEX_HOME/generated_images` 是全局生成目录，可能混入其他 Session、产品、平台或语言的图片；禁止按“最新时间”“最新文件”或“最大文件”猜测复制。
- 每次调用前记录任务 ID、平台、产品名、图片编号、版本号、目标文件名、提示词编号和调用开始时间，并对全局生成目录建立文件快照。
- 调用后优先使用本次工具返回的明确源文件路径。没有明确路径时，只允许用调用前后快照差异定位，且候选必须唯一。
- 结果不唯一、路径不明、时间异常、尺寸异常，或来源记录与当前任务、图号、direct 不一致时，判定为技术失败，不得作为有效 direct 保存。
- 每次调用只接受可唯一归属的一张源图。

## 保存与清单

- 通过非视觉文件确认的 direct 立即复制到 `./output/gpt-images-2-direct` 并标记为 `SAVED`；生成 Subagent、主 Agent 和其他 Agent 均不得查看生成图片。
- 每张 direct 图复制后立即记录：源文件绝对路径、源文件 SHA256、目标文件 SHA256、尺寸、复制时间、提示词编号和保存确认结果。
- 每张有效 direct 图逐行写入 `./output/gpt-images-2-direct/_imagegen_manifest.jsonl`。
- 技术失败文件如已复制，移入 `./output/temp/rejected-imagegen` 或在清单中标记为 `TECHNICAL_REJECT`，不得作为有效 direct 保存。
- 不检查产品细节、结构、颜色、文案或构图，不比较三版，也不因图片内容重新生成。

## 中断恢复

- 每生成一张就立即保存到直接生成目录，不等三版全部完成。
- 调用或 Session 中断、超时或未稳定进入下一次生成时，核对直接生成目录的文件数量、大小和时间戳。
- 从缺失的图型与 `direct` 序号继续生成，并遵守每个 direct 最多一次技术替补的上限；未补齐且未记录 `TECHNICAL_REJECT` 前不得标记完成。
