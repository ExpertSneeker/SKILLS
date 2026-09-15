---
name: init-2560px-images
description: 仅在明确调用 $init-2560px-images 时，将 JPG/JPEG/PNG 初始化为长边不超过 2560px 的副本。
---

# 初始化 2560px 图片

仅在用户明确调用本 Skill 后执行；保持 `allow_implicit_invocation: false`。ecom-img 缺少 manifest 不构成自动初始化的授权。

```powershell
python -X utf8 "<skill-dir>\scripts\prepare_product_photos.py" --task-root "<任务根目录绝对路径>" [--source "<原始拍摄图目录绝对路径>"]
```

- 只允许脚本读取原图；Agent、view_image 和其他工具不得读取或接收原图。脚本仅处理 JPG/JPEG/PNG，不处理 RAW，不修改原图；小图原样复制，大图修正 EXIF 后等比缩至长边 2560px。
- 未指定 --source 时由脚本按固定名称发现来源；多个候选需明确来源，不扫描整个任务目录。目录仅含文件夹快捷方式也可处理，不启动快捷方式。来源歧义、快捷方式及清单迁移细节见 [输入说明](references/inputs.md)。失效、循环、越界或输出冲突不得静默跳过。
- 执行工具返回 session_id 或仍在运行时，使用同一会话 write_stdin 等待最终退出；中间 Script completed、部分文件、空输出或锁文件均不是完成。进程结束前不检查 manifest、不启动下一条校验命令，不重复启动初始化。
- 仅当最终 exit_code 为 0，输出含 prepared、reused、manifest，且 `<任务根目录>\2560px拍摄图\_manifest.json` 的绝对路径存在、至少登记一张图片时报告成功。失败或空清单时报告阻塞，不绕过脚本使用原图。
