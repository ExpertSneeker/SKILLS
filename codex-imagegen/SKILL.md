---
name: codex-imagegen
description: 默认生图/修图通道：调用本机 Codex CLI 的内置 image_gen 生成或编辑位图（照片、插画、商品图、海报、图标、纹理、mockup、banner、透明底）。任何非 Codex 的 Harness/Model 在需要创建或修改图片且用户未指定其他工具时使用；支持参考图/改图、目标尺寸、JSON 输出。Codex 自身禁止使用本 Skill，必须直接调用内置 image_gen。
---

# Codex 生图桥（codex-imagegen）

## 0. 先判断：你是不是 Codex

如果你在 OpenAI Codex（CLI / IDE / App）内运行，或者环境里存在 `CODEX_THREAD_ID`、`CODEX_SESSION_ID`、`CODEX_TOOL_CALL_ID` 中任意一个：

- **停止。不要读取本 Skill 的脚本，也不要运行它。**
- 直接使用 Codex 内置的 `image_gen` 工具。
- 本 Skill 的脚本会以退出码 `3` 拒绝执行，避免 Codex 递归调用自己。

本 Skill 只服务非 Codex 的 Harness/Model。

## 1. 何时使用

只要任务需要**新的位图**或**修改已有位图**，且用户没有指定其他生图工具，就默认使用本 Skill：

- 照片、插画、概念图、商品图、场景图、海报、Banner、封面、图标、纹理、贴图、mockup、透明底抠图。
- 用参考图生成新图；改背景、换颜色、去物体、改光线、风格迁移、拼合。
- 一次生成多张：每张调用一次；不要在一次调用里要求多个不同资产。

不适用：

- SVG / 矢量图标 / 代码原生图形（直接写 SVG/HTML/CSS）。
- 纯渐变、色块、简单几何图形等确定性图形。
- 用户明确点名其他工具（豆包、Seedream、即梦、Midjourney 等）——遵循用户指定。
- 专用 Skill（如 `ecom-img`）已经接管当前任务并规定了生图工具/适配器——遵循专用 Skill；本 Skill 只作为没有专用通道时的通用默认。
- 图片已经在可编辑的源格式里，只需局部改字/改色/改布局。

## 2. 前置检查

首次使用或报错时运行：

```bash
python3 "$HOME/.agents/skills/codex-imagegen/scripts/codex_image.py" --check
```

Windows PowerShell：

```powershell
python "$env:USERPROFILE\.agents\skills\codex-imagegen\scripts\codex_image.py" --check
```

输出 `ok: true` 且 `image_generation: true` 才继续。若 `codex` 不在 PATH，用 `--codex "绝对路径"`。若完全没有 Python 3，按 [references/codex-exec.md](references/codex-exec.md) 的原始 `codex exec` 回退；不要因此改用 SVG 占位图。

Unix 通常用 `python3`，Windows PowerShell 用 `python`；下面示例按此区分。

## 3. 生成（最常用）

Bash：

```bash
python3 "$HOME/.agents/skills/codex-imagegen/scripts/codex_image.py" \
  --prompt "A minimal product photo of a matte ceramic mug on a stone surface, soft studio light, no text, no logo" \
  --out "./output/hero.png" \
  --size 1536x1024 \
  --json
```

PowerShell：

```powershell
python "$env:USERPROFILE\.agents\skills\codex-imagegen\scripts\codex_image.py" `
  --prompt "A minimal product photo of a matte ceramic mug on a stone surface, soft studio light, no text, no logo" `
  --out ".\output\hero.png" `
  --size 1536x1024 `
  --json
```

成功时 stdout 只有一个 JSON 对象（`--json`），关键字段：

```json
{
  "ok": true,
  "out": "C:\\...\\hero.png",
  "source": "C:\\Users\\...\\.codex\\generated_images\\<thread>\\exec-....png",
  "thread_id": "01a...",
  "width": 1536,
  "height": 1024,
  "size_match": true,
  "sha256": "...",
  "duration_ms": 46000
}
```

`--out` 是最终交付文件；`source` 是 Codex 的原始文件，默认保留（不移动、不删除）。

## 4. 改图 / 参考图

```bash
python3 "$HOME/.agents/skills/codex-imagegen/scripts/codex_image.py" \
  --prompt "Change only the background to deep navy. Keep the product, its edges, and its shadow unchanged. No text, no watermark." \
  --image "./input/product.png" \
  --out "./output/product-navy.png" \
  --json
```

- `--image` 可重复；顺序就是提示词里的 Image 1、Image 2……
- 在提示词里逐张写明角色（改图目标 / 风格参考 / 合成素材）。
- 改图必须写不变量：`change only X; keep Y unchanged`。
- 建议不超过 5 张参考图；更多时先拼版或分批。

## 5. 参数

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `--prompt` | 二选一 | 生图/改图请求。 |
| `--prompt-file` | 二选一 | UTF-8 文件；长提示词优先用它，避免 shell 引号问题。 |
| `--out` | 是 | 输出路径，`.png` / `.jpg` / `.jpeg` / `.webp`。已存在则报错，除非 `--force`。 |
| `-i, --image` | 否 | 参考图/改图输入，可重复。 |
| `--size WxH` | 否 | 目标尺寸或宽高比，如 `1536x1024`。会写进提示词；不保证原生像素完全一致。 |
| `--fit cover` | 否 | 需要精确像素时使用：等比放大后居中裁切到 `--size`。需 Pillow。 |
| `--fit contain` | 否 | 等比缩放到框内，留白居中；PNG/WebP 透明留白，JPEG 白色留白。需 Pillow。 |
| `--fit none` | 否 | 默认。保留 Codex 原生尺寸。 |
| `--model` | 否 | 覆盖 Codex agent 模型，传给 `codex exec -m`。一般不用。 |
| `--timeout` | 否 | 秒，默认 300。单张通常 35–70 秒。 |
| `--cwd` | 否 | `codex exec` 的工作目录；默认用一次性临时目录。 |
| `--codex` | 否 | Codex 可执行文件路径；默认 `codex`。 |
| `--isolated` | 否 | 给 `codex exec` 加 `--ignore-user-config`，减少上下文与耗时（实测约 31–36 秒），但忽略用户 Codex 模型/代理配置。默认关闭。 |
| `--json` | 否 | stdout 只输出一个 JSON 对象；推荐 Agent 使用。 |
| `--force` | 否 | 覆盖已存在的 `--out`。 |
| `--dry-run` | 否 | 只打印最终 `codex` 命令和提示词，不调用、不花钱。 |
| `--save-log` | 否 | 把 `codex-exec.jsonl`、stderr、`prompt.txt` 保存到目录，便于排查。 |
| `--check` | 否 | 检查 Codex 是否安装、登录并启用 `image_generation`。 |

## 6. 行为与限制

- 每张图启动一次独立的 `codex exec`，使用独立 thread；并行调用不会串图，但 Codex 可能限流，建议同时最多 2–3 个。
- 单张约 35–70 秒；不要因为“看起来没输出”就重复启动。超时后用更大 `--timeout` 重试一次。
- 使用 Codex 账号额度；不需要 `OPENAI_API_KEY`，不要设置/索要它。
- 原生尺寸通常约 1.25MP（方形 1254×1254）或 1.5–1.7MP（横/竖）；`--size` 会尽量影响构图，精确像素用 `--fit cover`。
- 透明底：在提示词里明确写 `transparent background, preserve alpha`；生成后检查 alpha 通道，不保证一次成功。
- 文字：把要出现的文字用引号逐字写出，并说明字体/位置；生成后必须检查拼写。
- 源文件留在 `$CODEX_HOME/generated_images/<thread_id>/`；脚本只复制，不移动。需要清理时由用户决定。

## 7. 失败处理

| 退出码 | 含义 | 处理 |
| --- | --- | --- |
| `2` | 参数错误 | 按提示修正。 |
| `3` | 检测到 Codex 环境，拒绝自调用 | 你就在 Codex 里：改用内置 `image_gen`。 |
| `4` | 找不到 Codex、未登录或生图功能被禁用 | 安装 Codex CLI；`codex login`；`codex features enable image_generation`；再 `--check`。 |
| `5` | `codex exec` 失败 | 看 `log_dir` 里的 stderr；修好后重试一次。 |
| `6` | 超时 | `--timeout 600` 重试一次；不要并行重复。 |
| `7` | Codex 结束但没找到图片 | 确认账号有生图额度；重试一次；仍失败则报告。 |
| `8` | 输出文件已存在 | 换文件名，或 `--force`。 |
| `9` | 一次调用产出多张 | 查看 `images`，改提示词为“只生成一张”后重试。 |
| `10` | 图片损坏/格式不对 | 重试；持续失败则报告。 |
| `11` | 后处理失败 | 安装 Pillow，或去掉 `--fit` / 换 `.png`。 |
| `12` | 输入不合法 | 按提示修正。 |

失败时不要伪造图片、不要用 SVG 占位图冒充位图、不要把未验证的文件说成成功。

## 8. 提示词合同

生成提示词建议按这个顺序写；不要堆砌形容词：

```text
Use case: product-mockup
Asset type: Amazon main image / website hero / app icon
Primary request: <一句话主体>
Scene/backdrop: <环境>
Subject: <主体细节>
Style/medium: <照片/插画/3D/扁平>
Composition/framing: <广角/特写/俯视/留白位置>
Lighting/mood: <光线与氛围>
Color palette: <颜色>
Materials/textures: <材质>
Text (verbatim): "<必须逐字出现的文字>"
Constraints: <必须保留/必须避免>
```

改图时追加：

```text
Change only: <要改的部分>
Keep unchanged: <主体、边缘、构图、颜色、阴影、文字>
```

## 9. 验证与交付

1. 用当前 Harness 的图片查看工具打开 `out`；没有查看工具时至少确认文件存在、尺寸和哈希。
2. 检查：主体、构图、颜色、文字拼写、不变量、透明通道。
3. 交付时报告：最终路径、尺寸、使用的提示词、`source` 路径（可追溯）。
4. 迭代时一次只改一个变量；保留上一版，不覆盖，除非用户明确要求替换。

## 10. 参考

- [references/codex-exec.md](references/codex-exec.md)：实测的 `codex exec` 命令、参数、坑位与原始命令回退。
- [references/installation.md](references/installation.md)：安装到各 Harness 的全局 Skill 目录（Windows/macOS/Linux）。
