# Seedream 5.0 Pro 适配器

仅当选择器指定 `豆包`、`豆包生图`、`Seedream`、`Seedream 5.0 Pro` 或 `seedream5.0pro` 时使用。官方资料：[教程](https://console.volcengine.com/ark/region:cn-beijing/docs/82379/2582774?lang=zh)、[API](https://console.volcengine.com/ark/region:cn-beijing/docs/82379/1541523?lang=zh)、[错误码](https://console.volcengine.com/ark/region:cn-beijing/docs/82379/1299023?lang=zh)。

## 固定调用

- 直接运行 `<ecom-img-skill-dir>\scripts\seedream5_pro.py`，其中 `<ecom-img-skill-dir>` 使用当前 skill 的绝对路径。
- 模型为 `doubao-seedream-5-0-pro-260628`，endpoint 为 `https://ark.cn-beijing.volces.com/api/v3/images/generations`。脚本固定 `output_format=png`、`response_format=url`、`watermark=false`、`optimize_prompt_options.mode=standard`。
- 默认 `--size 1K`；只有用户明确要求时才使用 `2K`。
- 命令形状：

```powershell
python <ecom-img-skill-dir>\scripts\seedream5_pro.py --prompt-file <absolute-utf8-file> --output <absolute-png-file> [--input "role=C:\path\image.jpg"]... [--size 1K|2K]
```

- `0` 图是文生图，`1` 图是图生图，`2-10` 图是有序多图；`--input` 角色顺序必须与提示词中的图 N 一致。
- 保持当前任务根目录为工作目录；有效 direct 图保存到该目录的 `./output/seedream5-pro-direct`。`--output` 使用该目录下目标 PNG 的绝对路径，脚本在同目录原子写入 `_records/<stem>.call.json`。

## 输入与产品真实性

- 所有输入先 `view_image`。只支持 JPEG/PNG；`.jpg/.jpeg` 文件中的 MPO 按 JPEG 输入处理。每张本地文件不超过 30 MB、3,600 万像素。
- 当前产品图继续强制使用 `2560px拍摄图/_manifest.json` 登记的实拍输入，禁止使用原始拍摄图路径，并遵守 [generation-workflow.md](generation-workflow.md) 的产品真实性规则；仅设计原则中的海绵纯场景默认分支按“目标画面不出现产品”处理，不传入海绵实拍。纯文生仅用于不涉及产品真实性的信息页及该默认分支。
- 不实现组图、流式、联网、交互编辑。

## 任务清单与调用

- 每次执行前列出固定任务清单：图号、`direct01`/`direct02`/`direct03`、提示词文件、输入角色、输出路径与尺寸。
- 按生成模块派发的每个单版生成 Subagent 只执行一次脚本调用；脚本内部符合条件的网络重试仍属于这一次业务调用。每项继续使用唯一输出路径和 `_records/<stem>.call.json` 原子记录。
- 脚本成功返回后，生成 Subagent、主 Agent 和其他 Agent 均不得查看生成图片；只按生成模块完成非视觉文件确认并标记 `SAVED`。

## 恢复与记录

- 每个 direct 的 `attempt_count` 是累计 POST 次数，包含脚本内部自动重试，最多为 2；所有恢复和技术替补沿用同一输出路径及 `_records/<stem>.call.json`，不得删除记录或更换路径重置计数。只有脚本识别为官方建议重试的结构化 `429`/`500` 才在同一次脚本调用内自动重试一次。
- 其他明确失败只有在记录为 `failed`、`retry_eligible=true`、`attempt_count=1` 且修正后的请求指纹发生变化时，才允许由全新技术替补执行剩余一次 POST；已达到 2 次时不得追加生成。文件确认失败也须先检查记录，不因缺图或损坏直接重做；图片内容不得触发重新生成。官方未标注不扣费错误，不预设白名单。
- 未知超时、断连或截断的 `unresolved`，以及中断后遗留、结果未明的 `calling`，均保留待核实状态并按生成模块暂停当前图号，不重新 POST，不标记整套完成；保留提示词编写前已读取或创建的 `DESIGN.md`。
- `download_pending` 只恢复剩余 GET 下载机会，累计最多 2 次 GET（含首次），不重新 POST；URL 仅 24 小时有效，完成后立即下载。下载机会耗尽或无法恢复时记录最终技术失败，不以新生成替代下载恢复。
- 记录包含提交、生成完成及耗时、下载时序、HTTP/错误码、输出尺寸/字节/SHA256。`ARK_API_KEY` 先从进程环境读取，再读取 Windows Machine；密钥、Authorization 和 Base64 不得落盘。
