# 实测的 `codex exec` 调用

测试环境：Windows 11，`codex-cli 0.163.0`，ChatGPT 登录（`codex login status` 返回 `Logged in using ChatGPT`），测试日期 2026-10-21。

## 最终命令形状

```text
codex exec --json --skip-git-repo-check --sandbox read-only --color never \
  -C <临时工作目录> \
  "<后端规则 + 用户提示词>" \
  --image <参考图1> --image <参考图2>
```

`scripts/codex_image.py` 生成的就是这个形状。关键点：

- `--json`：stdout 是 JSONL；首行附近有
  `{"type":"thread.started","thread_id":"01a..."}`。
- `--skip-git-repo-check`：`-C` 指向一次性临时目录，不是 git 仓库。
- `--sandbox read-only`：禁止 Codex 用 shell 改文件；内置 `image_gen` 仍可工作（服务端工具）。
- `--color never`：JSON 输出更干净。
- `-C <temp>`：隔离工作区，避免 Codex 读取当前项目、`AGENTS.md`、diff 等无关上下文。
- `--image`：把参考图作为附件传入；放在提示词之后。

## 为什么提示词要放在 `--image` 前面

`--image <FILE>...` 在 0.163 是可变参数。实测：

```text
codex exec ... -i ref.png "编辑这张图"
```

会把 `"编辑这张图"` 当成第二张图片路径，导致：

```text
Reading prompt from stdin...
No prompt provided via stdin.
```

正确写法是提示词在前、`--image` 在后：

```text
codex exec ... "编辑这张图" -i ref.png
```

脚本里的 `build_command()` 已按这个顺序生成，并在注释里标明原因。

## 生成文件在哪里

`codex exec --json` 的 `thread.started.thread_id` 就是生成目录名：

```text
%CODEX_HOME%\generated_images\<thread_id>\exec-<uuid>.png
```

`CODEX_HOME` 默认 `~/.codex`，可用环境变量覆盖。脚本据此定位文件，不依赖模型在回复里写的路径。

实测输出尺寸（内置 `image_gen`）：

| 提示 | 原生尺寸 |
| --- | --- |
| 1024×1024 红圆 | 1254×1254 |
| 16:9 高山湖 | 1672×941 |
| 明确写 `1536x1024` 的 3:2 高山湖 | 1536×1024 |

结论：`--size` 写进提示词后，原生尺寸可能正好匹配，也可能只是近似；需要精确像素时用 `--fit cover`（Pillow 等比裁切）。

## 耗时与额度

- 单张约 35–70 秒（含 Codex agent 读 skill、调用 image_gen、返回）。
- 不需要 `OPENAI_API_KEY`；走 Codex 账号额度。
- `--ignore-user-config` 实测可降低上下文（约 46k vs 114k tokens）并略快，但会忽略用户的 Codex 模型/代理配置；脚本仅在 `--isolated` 时使用。

## 自调用防护

Codex 执行 shell 命令时会给子进程注入：

```text
CODEX_THREAD_ID=<thread>
CODEX_SESSION_ID=<thread>
CODEX_TOOL_CALL_ID=exec-...
CODEX_CI=1
CODEX_SANDBOX_NETWORK_DISABLED=1
CODEX_VERSION=0.163.0
```

脚本检测前三个中的任意一个，直接以退出码 `3` 拒绝。这样即使 Codex 误加载本 Skill，也不会递归启动第二个 Codex。

Codex 自身应当直接调用内置 `image_gen`，不要运行本脚本。

## `codex exec` 不接受的参数

`-a/--ask-for-approval` 只属于顶层 `codex`，不属于 `codex exec`。实测：

```text
codex exec -a never ...
# error: unexpected argument '-a' found
```

`codex exec` 的沙箱用 `--sandbox read-only` 控制；审批策略读配置，非交互执行不会等待人工审批。

## stdin 提示

只要子进程 stdin 不是交互式终端，stderr 常会出现：

```text
Reading additional input from stdin...
```

脚本用 `stdin=subprocess.DEVNULL` 让它立即读到 EOF；这条消息仍可能出现，但无害，且被捕获进 `codex-exec.stderr.txt`。某些 harness 的 shell 工具会把 stdin 接成管道；同样不是错误。

## 原始命令回退（没有 Python 时）

不推荐，因为要自己解析 thread id 和复制文件；仅在 Python 不可用时使用。

PowerShell：

```powershell
$prompt = @"
Use your built-in image_gen tool exactly once. Do not move or copy the output.
Generate: a minimal product photo of a ceramic mug on stone, soft studio light, no text.
Reply with the absolute path of the generated PNG.
"@
codex exec --json --skip-git-repo-check --sandbox read-only -C $env:TEMP $prompt
# 从输出第一行取 thread_id，然后：
# Copy-Item "$env:USERPROFILE\.codex\generated_images\<thread_id>\*.png" .\out.png
```

Bash：

```bash
prompt='Use your built-in image_gen tool exactly once. ... Reply with the absolute path.'
codex exec --json --skip-git-repo-check --sandbox read-only -C /tmp "$prompt"
# 从 JSONL 取 thread_id，然后：
# cp "$HOME/.codex/generated_images/<thread_id>"/*.png ./out.png
```

## 常见故障

| 现象 | 原因 / 处理 |
| --- | --- |
| `No prompt provided via stdin` | 提示词被 `--image` 的可变参数吃掉；把提示词放在 `--image` 前面。 |
| `codex exec` 退出 0 但没有图 | 账号无生图额度、功能被禁用，或模型没调用工具；看 `log_dir` 的 JSONL。 |
| 生成目录里有多个文件 | 模型一次调用了多次 `image_gen`；脚本报退出码 9，改提示词后重试。 |
| 找不到 `generated_images/<thread>` | `CODEX_HOME` 被改过，或 Codex 版本目录结构变化；用 `--save-log` 查看 JSONL。 |
| 运行很久无输出 | 正常，单张 35–70 秒；不要重复启动，等 `--timeout`。 |
| 提示 `Refusing to run inside a Codex session` | 你在 Codex shell 里；直接用内置 `image_gen`。 |
| Windows 超时后进程残留 | 脚本用 `taskkill /T /F` 杀进程树；若仍残留，手动结束 `codex.exe`。 |
