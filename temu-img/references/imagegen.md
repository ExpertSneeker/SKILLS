# imagegen 适配器

选择 `$imagegen` 时，先完整读取其 skill，只使用内置 `image_gen` 工具；不要调用 `scripts/image_gen.py`、CLI/API 回退模式或要求 `OPENAI_API_KEY`。本适配器只补充 TEMU 工作流的来源追踪和防串图要求。

## 调用与来源

- 涉及 TEMU 产品实拍时，`referenced_image_paths` 只允许使用 `2560px拍摄图/_manifest.json` 登记的目标路径；禁止使用原始拍摄图。
- `$CODEX_HOME/generated_images` 是全局生成目录，可能混入其他 Session、产品、平台或语言的图片；禁止按“最新时间”“最新文件”或“最大文件”猜测复制。
- 每次调用前记录任务 ID、平台、产品名、图片编号、版本号、目标文件名、提示词编号和调用开始时间，并对全局生成目录建立文件快照。
- 调用后优先使用本次工具返回的明确源文件路径。没有明确路径时，只允许用调用前后快照差异定位，且候选必须唯一。
- 候选不唯一、路径不明、时间异常、尺寸异常或内容不符时，判定为污染风险，不得复制或计入 direct 三版。
- 每次调用只接受可唯一归属的一张源图。

## 保存与清单

- 有效 direct 图立即复制到 `./output/gpt-images-2-direct`。
- 每张 direct 图复制后立即记录：源文件绝对路径、源文件 SHA256、目标文件 SHA256、尺寸、复制时间、提示词编号和校验结果。
- 每张有效 direct 图逐行写入 `./output/gpt-images-2-direct/_imagegen_manifest.jsonl`。
- 污染文件如已复制，移入 `./output/temp/rejected-imagegen` 或在清单中标记为 `rejected`，不得进入最终交付或计入三版。
- direct 图必须属于当前 TEMU 产品，使用英文画面并符合目标比例；出现其他产品、品牌、语言或 Session 内容时立即作废并重新生成。

## 中断恢复

- 每生成一张就立即保存到直接生成目录，不等三版全部完成。
- 调用或 Session 中断、超时或未稳定进入下一次生成时，核对直接生成目录的文件数量、大小和时间戳。
- 从缺失的图型与 `direct` 序号继续生成；未补齐前不得标记完成。
