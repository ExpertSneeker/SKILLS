---
name: init-2560px-images
description: 仅在用户明确调用 $init-2560px-images，并要求把 JPG、JPEG 或 PNG 图片初始化为长边不超过 2560px 的副本时使用。
---

# 初始化 2560px 图片

## 执行

在用户明确调用本 Skill 后运行：

```powershell
python <skill-dir>\scripts\prepare_product_photos.py --task-root <任务根目录绝对路径> [--source <原始拍摄图目录绝对路径>]
```

- 未传 `--source` 时，只解析任务根目录下的 `产品拍摄原图.lnk`。
- 只允许脚本读取原始图片；不得对原图执行 `view_image`，也不得把原图交给 Agent 或其他工具。
- 脚本仅递归处理 JPG、JPEG 和 PNG。长边不超过 2560px 时原样复制，超过时修正 EXIF 方向并等比缩放。

## 成功条件

仅当命令返回零，且 `2560px拍摄图/_manifest.json` 存在并至少登记一张图片时继续任务。命令失败、清单缺失或清单为空时停止，不得绕过脚本直接使用原图。
