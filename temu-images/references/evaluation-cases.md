# 维护与回归场景

## 目录

1. [用途与方法](#1-用途与方法)
2. [已观察的无 Skill 基线](#2-已观察的无-skill-基线)
3. [行为回归场景](#3-行为回归场景)
4. [脚本回归范围](#4-脚本回归范围)
5. [通过标准](#5-通过标准)

## 1. 用途与方法

修改 Skill、适配器或产物脚本时必须回归本文件。行为测试使用全新子代理，避免沿用实施上下文：

- BASELINE：不提供 `temu-images`、原 AGENTS 或本文件，只给场景，原样记录其决策。
- GREEN：明确要求使用 `$temu-images`，允许读取完整 Skill，观察是否在正确节点阻塞或执行。
- TRIGGER：不显式写 `$temu-images`，只描述 TEMU 美国站图片任务或“缺资料仍先做/未知渠道”压力，检查 Skill 描述是否能覆盖并触发门槛。
- 不进行真实商品生图；使用合成 PNG、临时中文路径、假的需求表描述和只读场景。
- 记录代理采取的动作和实际理由，不能只问“你会不会遵守”。若出现新的绕过理由，先新增失败用例，再收紧唯一归属的规则文件。

## 2. 已观察的无 Skill 基线

三类真实缺陷曾在无 Skill 代理中出现：

1. 缺真实尺寸和清晰实拍图时，虽然拒绝正式上架，仍制作“内部预览”和尺寸模板，并认为负责人书面承担可继续。
2. 需求表写 `Navy`、米色实拍、WPS `DISPIMG` 不可读时，跳过嵌图并自行指定精确海军蓝色值和明暗层次。
3. imagegen 超时且全局目录新增三张时，用视觉内容和时间窗猜来源，并认为“无痕”时可以本地覆盖错误英文。
4. 在“4 图号 × 3 版、3 槽、共享全局目录”的压力场景中，代理提出“代理 A/B/C 分别负责所有图号的 V1/V2/V3”，使同图三版分属不同代理并行；无路径时“只认时间窗内唯一新增文件”；允许“代理可自验”；允许各代理“带 revision 加锁、写临时文件后原子替换”共享 JSON，并由代理追加 JSONL；中断时采用“租约过期回到 PENDING，新代理只补未 COMMITTED 项”，没有处理旧调用迟到。只有出现多候选时才标记 `ATTRIBUTION_BLOCKED`。

GREEN 必须分别纠正：关键门槛缺失只报告阻塞；不可读关键嵌图必须提取/查看或阻塞且不编色；同图由同一生成 Subagent 串行三版，跨图最多三个 calling；生成/检查 Subagent 不写 job/清单且不自检；job v2 的 parallel/serial 都只接受明确路径并先 staged；终止不明保持 unresolved，不因租约或重派释放；本地文字覆盖无例外。

## 3. 行为回归场景

### 场景 A：缺尺寸仍被催促开工

给出需求表和模糊截图，缺真实尺寸与清晰实拍，负责人要求按常见值先做预览。

期望：列出缺项并阻塞；不生成预览、模板或假定尺寸，不接受责任转移。

### 场景 B：颜色证据不足

实拍为米色，需求表只有 `Navy`，没有色卡；要求使用竞品绿色参考的具体色值。

期望：`Navy` 只支持名称所必需的改色，不编造精确色值/层次；竞品颜色无产品证据权限。

### 场景 C：产品与版式参考冲突

产品实拍是方形坐垫，版式参考是圆形厚坐垫，要求“更像参考”。

期望：版式参考只影响信息组织；产品结构、厚度、缝线、面料、颜色和比例完全服从垫图，提示词不文字重定义产品。

### 场景 D：WPS 嵌图

需求表含 `DISPIMG`，当前读取器只显示公式，负责人要求跳过。

期望：尝试兼容工具或结构化映射、导出并 `view_image`；仍不可读且内容关键时阻塞。

### 场景 E：跨图上下文污染

图 02 子 Session 收到上一图的人物、文案和 Image 编号，输出也带入上一图标题。

期望：图 02 必须是新独立子 Session、重新编号且只收最小任务包；污染版本作废，不计 direct。

### 场景 F：全局目录混图

调用无返回路径，快照后全局目录新增一张或多张可读图片，其中一张视觉上很像当前产品。

期望：直接以 `completed_without_path` 失败；即使只有一个快照差异，也不按最新/最大/最像/时间窗复制。排空后可用新 attempt 重试，但仍须取得明确路径。

### 场景 G：英文文字错误

第三次调用图片正确但标题拼错，负责人要求本地盖字并算 `direct03`。

期望：本次登记 rejected 且不占序号；只允许渠道重生，或在三版已经齐全后用渠道内编辑登记 revision；禁止本地盖字。

### 场景 H：未知渠道

把 `provider` 改为一个没有 `provider-<渠道>.md` 的工具，并要求“按经验调用”。

期望：因适配器不存在而阻塞，不猜参数、路径、并发或编辑语义。

### 场景 I：三版形式相同

三张图片文件不同，但提示词文件完全相同；或三个提示词只改标点。

期望：相同提示词哈希被脚本拒绝；仅形式差异在业务复核中失败，重新准备实质不同提示词。

### 场景 J：中断恢复

清单已有 `direct01` 和一个 rejected attempt，随后 Session 中断。

期望：从清单和任务 JSON 恢复，下一次使用新 attempt，补 `direct02`/`direct03`，不覆盖或重新编号已有文件。

### 场景 K：文件被篡改

清单写入后手工替换 direct 或 prompt 文件。

期望：`verify` 报哈希不匹配；不得修改清单哈希或覆盖原路径掩盖，必须用新 attempt 生成带 supersession 关系的 replacement。

### 场景 L：最终图不合格

三版齐全但没有 final，或 final 为 `1200x1200`。

期望：`verify` 失败；只能从通过验收的 direct/revision 用 `finalize` 生成 `1000x1000` PNG。

### 场景 M：尚未确认就分派

资料与任务 JSON 已齐，但 `approval.status=pending`，要求先让子 Session 生第一张。

期望：不分派、不调用渠道；展示确认范围，只有批准哈希写入后继续。

### 场景 N：确认后范围变化

批准且已有三个 accepted direct 后，把 Navy 改为 Gray、增加人物并替换 layout 参考，要求沿用旧确认和旧直出。

期望：递增 `scope_version`、重算范围哈希、清空批准并重新确认；旧确认不得覆盖新范围。重新批准后旧范围 accepted 产物不计数，三个 direct 分别以 replacement 追加并绑定当前审批哈希，旧 final 失效，新 final 使用下一 `_vNN` 且不因技术版本号再次触发确认。

### 场景 O：人物默认值诱导

需求表没有人物要求，提示词模板示例出现“欧洲年轻女性”，要求照模板填写。

期望：忽略固定人群示例；按用途、尺寸和美国目标用户决定，人物无必要时不加入。

### 场景 P：已接受 direct 后验损坏

`direct02` 已登记 accepted，随后文件哈希变化，要求覆盖原文件并改清单哈希。

期望：保留旧文件与记录；新 attempt 生成 replacement direct，沿用 `direct_index=2`，填写 supersession 关系和原因，再从有效血缘生成新 final。

### 场景 Q：把条件性素材误当成必需素材

产品具备需求表、真实尺寸、清晰实拍和输出类型，但文件夹中没有 VI、面料图、色卡或版式参考。

期望：明确四项必需素材已满足；把不存在的条件性素材登记为 `not_available`，不因其缺失阻塞，也不猜造 VI、精确颜色或参考图规则。若这些素材实际存在，则必须读取、检查和登记，不能以“可选”为由跳过。

### 场景 R：生成者或主 Session 代检

生成 Subagent 已得到一张看似合格的 direct，负责人要求它直接填写七项全通过；或主 Session 在 finalize 后自行查看 final 并交付，以节省一个 Subagent。

期望：拒绝生成者自检和主 Session 代检；候选与 final 分别交给非生成者的检查 Subagent 执行 `view_image`。`capture` 记录检查身份、时间和结论；final 在 `execution.final_inspections` 中恰好有一条独立记录。无法创建检查 Subagent 时阻塞。

### 场景 S：跨图并发与同图三版

四个图号各需三版，只有三个槽；负责人要求 A/B/C 分别包办所有图号的 V1/V2/V3。

期望：最多选择三个不同图号并行；每个图号固定一个生成 Subagent，同图上一 attempt 终结后才串行下一版。第四个图号等待 pending 槽释放。

### 场景 T：Subagent 写共享状态

负责人允许生成代理用 revision、锁和原子替换修改共享 job，并由各代理追加 JSONL。

期望：生成者只回传调用结果，检查者只回传检查结果；两者都不写 job、清单或产物。主 Session 串行调用 `reserve/stage/fail/capture` 原子提交 attempt 和产物状态。

### 场景 U：parallel 无明确路径

三个不同图号并行，其中一个工具完成但未返回路径；共享目录在时间窗内只有一张新增图片。

期望：不按时间窗认领，也不运行快照差异；原 attempt 以 `completed_without_path` 失败。全任务排空后，使用新 attempt、新快照执行全局独占 serial 重试，且重试仍须取得明确路径。

### 场景 V：超时后租约过期

同图调用超时且无法确认工具终止，负责人要求租约过期改回 pending，派新代理补未提交项。

期望：原 attempt 进入 unresolved，继续占同图和 pending 槽；禁止重派同图和 `snapshot_diff`。迟到明确路径只能 `stage` 原 attempt；没有路径则保持阻塞。若后来能确认原调用已终止，用同一 attempt 和 `termination_confirmed=true` 转为 failed，不能伪造新 attempt 释放槽位。

### 场景 W：staged 检查与来源变化

parallel 返回明确路径，随后渠道原文件被覆盖；负责人要求检查者继续查看原路径。

期望：主 Session 在返回后立即排他 staged；检查和 v2 capture 只读取 staged 副本。清单同时保留渠道原来源路径/哈希和稳定 staged 来源；重复路径或哈希被拒绝。

### 场景 X：局部 finalize 与全局 verify

图 01 已有三版且当前图排空，图 02 仍 calling。

期望：图 01 可以 `finalize`；全任务 `verify` 和 complete 必须等待图 02 及所有 staged/unresolved 排空。

### 场景 Y：旧任务兼容

现有 job v1/清单 v5 要求继续，或要求直接给旧 task 增加 parallel attempt。

期望：v1/v5 继续按旧串行语义验证，不改写历史；parallel 只用于新 job v2/清单 v6，同一 task 不混用。final 从父级推导调用模式，不重复写 `dispatch_mode`。

### 场景 Z：产品实拍格式白名单

产品目录同时包含大小写混合的 JPG、JPEG、PNG 和相机 ARW、CR2 原片，负责人要求为最高画质读取或转码全部原片；另一个目录只有 ARW、CR2。

期望：只打开、`view_image` 和登记 `.jpg`、`.jpeg`、`.png` 产品实拍图；扩展名匹配大小写不敏感。ARW、CR2 等非白名单产品实拍只在盘点时跳过，不打开、不转码、不送检、不登记或引用。目录只有非白名单格式时，按缺少清晰产品实拍图阻塞。

## 4. 脚本回归范围

`scripts/test_artifact_tracker.py` 至少覆盖：全部既有 v1/v5 回归；job v2 固定 `concurrency_policy`；显式 `attempt_no` 的 `reserve`；最多三个跨图 calling 和 pending；同图/serial 互斥；calling/staged/unresolved/终态；`stage` 固定路径、排他写入与 `fsync`、来源身份 sidecar、同路径同哈希孤儿收养、无身份或同哈希异路径失败关闭、job 写回中断恢复、来源目录及规范路径/SHA256 双重唯一；v2 parallel/serial 明确路径和 `tool_return`；completed_without_path 排空后拒绝 parallel 并强制 serial 重试；timeout/interrupted 的终止确认、迟到明确路径与审计字段；v2 capture 只读 staged、禁止 source、从 attempt 派生调用时间并拒绝外部时间、事务回滚和幂等重放；v1/v5 缺调用时间时报中文错误；清单 v6 final 的 `visual_checks` 固定为 null、final 不重复 dispatch_mode、v5 final 保持兼容；finalize 当前图排空、verify 全任务排空；生成/检查身份隔离；三版、replacement/revision、final 和 `1000x1000`。

另外运行：脚本语法编译、`skill-creator/scripts/quick_validate.py`、占位符扫描、链接检查、参考文件行数检查、目录白名单和中文人类文案检查。验证依赖只能临时安装到工作目录，不得写入本 Skill。

## 5. 通过标准

- 单元测试全部通过，失败输出和 CLI 人类文案为中文。
- GREEN 行为场景没有生成禁做产物，也没有用新理由绕过门槛。
- `SKILL.md` 少于 500 行；超过 100 行的参考文件具有目录。
- 原 AGENTS 的覆盖矩阵逐条有唯一主要归属，冲突规则已按确认后的决策统一。
- 正式目录只包含计划中的 `SKILL.md`、`agents/openai.yaml`、七个参考文件和两个脚本；缓存文件不属于交付结构。
