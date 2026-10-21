# 安装到各 Harness 的全局 Skill 目录

本 Skill 的源目录：

```text
C:\Users\Lenovo\Desktop\SKILLS\codex-imagegen
```

通过目录联接（Windows Junction）暴露给各 Harness。源文件只维护一份，修改后所有入口同步生效。

## 已安装的入口

| 入口 | 读取它的 Harness |
| --- | --- |
| `%USERPROFILE%\.agents\skills\codex-imagegen` | DSH、OpenCode、通用 Agent Skills（Codex 可发现，但已用 config 屏蔽） |
| `%USERPROFILE%\.claude\skills\codex-imagegen` | Claude Code、OpenCode |
| `%USERPROFILE%\.gemini\config\skills\codex-imagegen` | Gemini / Antigravity（本机路径） |

**故意不安装到 `%USERPROFILE%\.codex\skills`。** Codex 也能通过 `~/.agents/skills` 发现本 Skill，所以下面用 `~/.codex/config.toml` 把它对 Codex 禁用；内容首节和脚本退出码 3 是第二道防线。

## Windows 安装命令

```powershell
$source = (Resolve-Path "C:\Users\Lenovo\Desktop\SKILLS\codex-imagegen").Path
$targets = @(
  (Join-Path $env:USERPROFILE ".agents\skills"),
  (Join-Path $env:USERPROFILE ".claude\skills"),
  (Join-Path $env:USERPROFILE ".gemini\config\skills")
)
foreach ($root in $targets) {
  New-Item -ItemType Directory -Path $root -Force | Out-Null
  $link = Join-Path $root "codex-imagegen"
  if (Test-Path $link) {
    Write-Host "已存在，跳过: $link"
  } else {
    New-Item -ItemType Junction -Path $link -Target $source | Out-Null
    Write-Host "已链接: $link -> $source"
  }
}
```

## macOS / Linux 安装命令

```sh
source="$HOME/Desktop/SKILLS/codex-imagegen"   # 按实际路径修改
for root in "$HOME/.agents/skills" "$HOME/.claude/skills" "$HOME/.gemini/config/skills"; do
  mkdir -p "$root"
  link="$root/codex-imagegen"
  if [ -e "$link" ] || [ -L "$link" ]; then
    printf '%s\n' "已存在，跳过: $link"
  else
    ln -s "$source" "$link"
    printf '%s\n' "已链接: $link -> $source"
  fi
done
```

## Codex 专属屏蔽（重要）

Codex 也读 `~/.agents/skills`。为防止 Codex 误选本 Skill，在 `~/.codex/config.toml` 增加以下条目（路径按实际安装位置替换）：

```toml
# codex-imagegen 只服务非 Codex Harness；Codex 必须用内置 image_gen。
[[skills.config]]
path = 'C:\Users\Lenovo\.agents\skills\codex-imagegen\SKILL.md'
enabled = false

[[skills.config]]
path = 'C:\Users\Lenovo\Desktop\SKILLS\codex-imagegen\SKILL.md'
enabled = false
```

第一条按入口路径匹配，第二条按目录联接的真实路径匹配；保留两条以防 Codex 的技能发现方式变化。

验证（只读，不消耗生图额度）：

```powershell
codex debug prompt-input "test" 1> "$env:TEMP\codex-prompt-input.json"
Select-String -Path "$env:TEMP\codex-prompt-input.json" -Pattern 'codex-imagegen'
# 应无匹配；同一份输出里应仍能看到 imagegen 和 ecom-img
```

这样 Codex 不会加载本 Skill；脚本的退出码 `3` 仍是第二道防线。DSH、Claude Code、Gemini/Antigravity 不读 `~/.codex/config.toml`，不受这条屏蔽影响。

## 验证

```bash
python3 "$HOME/.agents/skills/codex-imagegen/scripts/codex_image.py" --check
```

应输出 `"ok": true`、`"image_generation": true`、Codex 版本和登录状态。

再做一次最小生成（会消耗一次 Codex 额度）：

```bash
python3 "$HOME/.agents/skills/codex-imagegen/scripts/codex_image.py" \
  --prompt "A flat red circle centered on a plain white background, no text." \
  --out "/tmp/codex-image-smoke.png" \
  --json
```

## 为什么放在 `~/.agents/skills`

`~/.agents/skills` 是跨 Agent 的通用 Skill 目录：

- DSH 从它加载全局 Skill（本机 `ecom-img`、`init-2560px-images` 也在这里）。
- Codex 0.163 会扫描它；本机已在 `~/.codex/config.toml` 中屏蔽本 Skill，首节与退出码 3 仍是第二道防线。
- OpenCode 文档明确列出 `~/.agents/skills/<name>/SKILL.md` 为全局发现路径。
- Claude Code 读 `~/.claude/skills`，所以再做一份联结。
- Gemini / Antigravity 在本机读 `~/.gemini/config/skills`，所以再做一份联结。

如果某个 Harness 使用别的目录（例如项目级 `.opencode/skills`、`.claude/skills`、`.agents/skills`），把同样的目录联接/软链接建到该项目即可，不需要复制文件。

## 更新与卸载

- 更新：直接改源目录里的 `SKILL.md`、`scripts/`、`references/`；所有入口立即生效。
- 卸载：删除各入口的链接即可，不要删除源目录。
- 源目录移动后，链接会失效；按上面的命令重建。
