# SKILLS

Codex Skill集合。

## Skill 路由

- [ecom-img](ecom-img/SKILL.md)：用需求表与登记的产品实拍，规划／编写提示词、生成 Amazon 或 TEMU 成套商品图片，或恢复已有调用。仅规划不调用生图、不初始化、不创建或修改生产状态；事实不完整的提示词是草案。
- [init-2560px-images](init-2560px-images/SKILL.md)：用户明确调用时，使用预处理脚本从 JPG/JPEG/PNG 原图建立 2560px 副本与清单。它保持显式调用；ecom-img 缺清单时不得自动补建或读取原图。

生成模式需具备需求表、真实尺寸、有效清单及适用的颜色、平台、视觉与工具合同。三版分别直出交付，不验图、不选 FINAL；来源与文件完整性仍须确认。TODO 仅作历史决策与未决事项记录，不作为运行指令。

## Skill 安装位置

两个 Skill 分别链接到 `~/.agents/skills/ecom-img` 和 `~/.agents/skills/init-2560px-images`，目标是本仓库对应目录；不再在 `~/.codex/skills` 中建立这两个入口。

Windows PowerShell 在仓库根目录执行，使用目录联接（Junction）。若目标已存在，先核对内容与链接指向，不覆盖真实目录：

```powershell
$skillRoot = Join-Path $env:USERPROFILE '.agents\skills'
New-Item -ItemType Directory -Path $skillRoot -Force | Out-Null
New-Item -ItemType Junction -Path (Join-Path $skillRoot 'ecom-img') -Target (Resolve-Path .\ecom-img).Path
New-Item -ItemType Junction -Path (Join-Path $skillRoot 'init-2560px-images') -Target (Resolve-Path .\init-2560px-images).Path
```

macOS / Linux 对应建立 `~/.agents/skills/<Skill 名称>` 到仓库同名目录的软链接。迁移旧安装时，将 `.codex/skills` 中这两个旧链接移出加载目录；不要删除其指向的 Skill 源文件。

## 自定义 SubAgent

定义统一维护在 [agents/codex/](agents/codex/)，通过 `~/.codex/agents` 加载，可供不同商品任务使用：

| Agent | 模型 | 推理强度 |
| --- | --- | --- |
| `product_image_creator` | `gpt-5.6-luna` | `max` |
| `product_image_inspector` | `gpt-5.6-luna` | `max` |

克隆仓库后，在仓库根目录执行以下命令安装。若目标 `agents` 目录已存在，先备份并合并其中的定义，再移开原目录；以下命令不会覆盖现有目录。

Windows PowerShell 使用目录联接（Junction），无需管理员权限：

```powershell
$agentSource = (Resolve-Path .\agents\codex).Path
$codexRoot = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE '.codex' }
New-Item -ItemType Directory -Path $codexRoot -Force | Out-Null
New-Item -ItemType Junction -Path (Join-Path $codexRoot 'agents') -Target $agentSource
```

macOS / Linux 使用目录软链接：

```sh
codex_root="${CODEX_HOME:-$HOME/.codex}"
mkdir -p "$codex_root"
if [ ! -e "$codex_root/agents" ] && [ ! -L "$codex_root/agents" ]; then
  ln -s "$PWD/agents/codex" "$codex_root/agents"
else
  printf '%s\n' 'agents 已存在，请先备份、合并并移开原目录。' >&2
fi
```

安装后开启新的 Codex 会话加载角色。后续直接编辑仓库中的 TOML；通过个人目录修改也会写入同一份文件。整个个人 `agents` 目录均指向此仓库，新增定义也会保存在这里；仓库移动或删除后需要重建链接。分发时提交 TOML 源文件，接收者在本机创建链接。

## 维护

- 待办：[TODO.md](TODO.md)
- 归档Skill：[Archive/](Archive/)
