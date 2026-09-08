# SKILLS

Codex Skill集合。

## `ecom-img`

面向 TEMU 与 Amazon 商品图：根据需求表、产品实拍图、尺寸和品牌素材，先确定唯一平台，再按该平台规范规划并生成受支持的商品图片。

使用前需提供需求表、产品尺寸、JPG/JPEG/PNG 实拍图和输出类型；详细工作流见 [ecom-img/SKILL.md](ecom-img/SKILL.md)。

## 自定义 SubAgent

定义统一维护在 [agents/](agents/)，通过 Codex 个人目录加载，可供不同商品任务使用：

| Agent | 模型 | 推理强度 |
| --- | --- | --- |
| `product_image_creator` | `gpt-5.6-luna` | `max` |
| `product_image_inspector` | `gpt-5.6-luna` | `max` |

克隆仓库后，在仓库根目录执行以下命令安装。若目标 `agents` 目录已存在，先备份并合并其中的定义，再移开原目录；以下命令不会覆盖现有目录。

Windows PowerShell 使用目录联接（Junction），无需管理员权限：

```powershell
$agentSource = (Resolve-Path .\agents).Path
$codexRoot = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE '.codex' }
New-Item -ItemType Directory -Path $codexRoot -Force | Out-Null
New-Item -ItemType Junction -Path (Join-Path $codexRoot 'agents') -Target $agentSource
```

macOS / Linux 使用目录软链接：

```sh
codex_root="${CODEX_HOME:-$HOME/.codex}"
mkdir -p "$codex_root"
if [ ! -e "$codex_root/agents" ] && [ ! -L "$codex_root/agents" ]; then
  ln -s "$PWD/agents" "$codex_root/agents"
else
  printf '%s\n' 'agents 已存在，请先备份、合并并移开原目录。' >&2
fi
```

安装后开启新的 Codex 会话加载角色。后续直接编辑仓库中的 TOML；通过个人目录修改也会写入同一份文件。整个个人 `agents` 目录均指向此仓库，新增定义也会保存在这里；仓库移动或删除后需要重建链接。分发时提交 TOML 源文件，接收者在本机创建链接。

## 维护

- 待办：[TODO.md](TODO.md)
- 归档Skill：[Archive/](Archive/)
