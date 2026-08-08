# Seedream 5.0 Pro 适配器

仅当选择器指定 `豆包`、`豆包生图`、`Seedream`、`Seedream 5.0 Pro` 或 `seedream5.0pro` 时使用。官方资料：[教程](https://console.volcengine.com/ark/region:cn-beijing/docs/82379/2582774?lang=zh)、[API](https://console.volcengine.com/ark/region:cn-beijing/docs/82379/1541523?lang=zh)、[错误码](https://console.volcengine.com/ark/region:cn-beijing/docs/82379/1299023?lang=zh)。

## 固定调用

- 直接运行 `<temu-img-skill-dir>\scripts\seedream5_pro.py`，其中 `<temu-img-skill-dir>` 使用当前 skill 的绝对路径。
- 模型为 `doubao-seedream-5-0-pro-260628`，endpoint 为 `https://ark.cn-beijing.volces.com/api/v3/images/generations`。脚本固定 `output_format=png`、`response_format=url`、`watermark=false`、`optimize_prompt_options.mode=standard`。
- 默认 `--size 1K`；只有用户明确要求时才使用 `2K`。
- 命令形状：

```powershell
python <temu-img-skill-dir>\scripts\seedream5_pro.py --prompt-file <absolute-utf8-file> --output <absolute-png-file> [--input "role=C:\path\image.jpg"]... [--size 1K|2K]
```

- `0` 图是文生图，`1` 图是图生图，`2-10` 图是有序多图；`--input` 角色顺序必须与提示词中的图 N 一致。
- 保持当前 TEMU 产品目录为工作目录；有效 direct 图保存到该目录的 `./output/seedream5-pro-direct`。`--output` 使用该目录下目标 PNG 的绝对路径，脚本在同目录原子写入 `_records/<stem>.call.json`。

## 输入与产品真实性

- 所有输入先 `view_image`。只支持 JPEG/PNG；`.jpg/.jpeg` 文件中的 MPO 按 JPEG 输入处理。每张本地文件不超过 30 MB、3,600 万像素。
- TEMU 产品图继续强制使用 `2560px拍摄图/_manifest.json` 登记的实拍输入，禁止使用原始拍摄图路径，并遵守 [generation-workflow.md](generation-workflow.md) 的产品真实性规则。纯文生仅用于不涉及产品真实性的信息页。
- 不实现组图、流式、联网、交互编辑。

## 任务清单与调用

- 每次执行前列出固定任务清单：图号、`direct01`/`direct02`/`direct03`、提示词文件、输入角色、输出路径与尺寸；预留由合并验收触发的可选 `repair01`，未触发时不执行。
- 按生成模块派发的每个单版生成 Subagent 只执行一次脚本调用；脚本内部符合条件的网络重试仍属于这一次业务调用。每项继续使用唯一输出路径和 `_records/<stem>.call.json` 原子记录。

## 恢复与记录

- 每任务 `attempt_count <= 2`。只有脚本识别为官方建议重试的结构化 `429`/`500` 才在同一次脚本调用内自动重试一次。其他明确失败必须先修正输入或原因，再由一个新的技术替补 Subagent 手动重试同一 direct 一次；未知超时、断连或截断标为 `unresolved`，禁止重试。官方未标注不扣费错误，不预设白名单。
- API 恢复或未产出图片不占用业务 `repair01`；`repair01` 只由三版合并验收的硬错误触发。
- 下载失败只恢复一次 GET，不重新 POST。URL 仅 24 小时有效，完成后立即下载。
- 记录包含提交、生成完成及耗时、下载时序、HTTP/错误码、输出尺寸/字节/SHA256。`ARK_API_KEY` 先从进程环境读取，再读取 Windows Machine；密钥、Authorization 和 Base64 不得落盘。
