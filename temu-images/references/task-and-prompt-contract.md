# 任务、Session 与提示词契约

## 目录

1. [主 Session 与用户确认](#1-主-session-与用户确认)
2. [`_temu_job.json` 结构](#2-_temu_jobjson-结构)
3. [状态流转](#3-状态流转)
4. [独立生成与检查 Subagent](#4-独立生成与检查-subagent)
5. [图片角色和查看记录](#5-图片角色和查看记录)
6. [提示词结构](#6-提示词结构)
7. [三版提示词差异](#7-三版提示词差异)

## 1. 主 Session 与用户确认

主 Session 负责读取需求表和结构化信息，调度素材检查 Subagent，汇总证据，统一视觉基准，拆分整套图片并确定顺序、尺寸、文案、卖点和参考图角色。主 Session 不连续生成整套图片，也不代替检查 Subagent 查看或验收图片。

规划完成后先写入 `output/temp/<task-id>/_temu_job.json`，其中 `approval.status` 必须是 `pending`。向用户展示图号清单、逐图用途、原文文案与最小修正、颜色依据、人物/场景依据、参考图角色和目标路径。收到明确确认后才写 `approved`、确认时间和用户原话。

有效确认必须发生在用户看过当前 `scope_version`、`scope_sha256` 和完整范围摘要之后，且用户原话能明确表达批准这个范围。未关联当前范围的“先生成”“先做一张”“继续”或催促进度不算确认；不得代写、推断或补造用户确认原话。

尚无清单产物时，范围变化可以在当前任务内递增 `scope_version` 并重新确认。首条产物出现后，`task_id`、`provider`、`platform`、`product_name` 所代表的产品身份、既有 `image_id` 集合及每图 `image_type` 构成不可变任务身份。增加或删除图号、改变渠道/平台、改变产品身份或改变任一图号的图型时，立即阻塞当前任务；必须建立新 task，并使用独立的新输出根目录和清单，不能在原任务内通过 replacement 恢复。

产物工具对上述字段及按 `(image_id, image_type)` 排序的完整图片身份集合计算规范 JSON SHA256，并把结果作为 schema v5 清单每行必填的 `immutable_identity_sha256`。首条产物完成机械绑定；后续 `capture`、`finalize`、`verify` 必须把当前 job 计算值与全部历史任务记录逐行比较，不能只依赖当前 job 声明或当前图号。任一值不一致时不得在原任务继续。

不改变上述身份的文案、卖点、颜色依据、尺寸、人物、`output_type_original`、参考图角色等属于可变范围；同一产品身份内已批准的颜色或 SKU 表现变化也属于可变范围。这类变化必须把确认重置为 `pending`，停止分派并重新确认。若已经存在 accepted direct，重新批准后旧范围产物立即失效；三个旧 direct 必须分别用更大的 `attempt_no` 追加当前范围 replacement，沿用各自 `direct_index`，填写 `supersedes_artifact_id` 和原因。三个当前范围 replacement 齐全前不得生成新 final；旧 revision/final 随旧血缘失效。

## 2. `_temu_job.json` 结构

使用 UTF-8 JSON 和绝对路径。下面是必填结构；数组可以为空，但键不得省略。未取得的可选证据使用 `null` 或明确状态，禁止猜值。

```json
{
  "schema_version": 1,
  "task_id": "temu-us-20260721-001",
  "provider": "imagegen",
  "platform": "TEMU_US",
  "product_name": "产品稳定名称",
  "product_folder": "C:/absolute/product-folder",
  "main_session_id": "session-main-001",
  "job_status": "awaiting_approval",
  "approval": {
    "status": "pending",
    "scope_version": 1,
    "scope_sha256": "待按确认范围计算的 SHA256",
    "approved_scope_sha256": null,
    "confirmed_at": null,
    "confirmation_text": null
  },
  "material_inventory": {
    "required": {
      "requirements_table": {"status": "ready", "evidence_ids": ["requirements-01"]},
      "real_dimensions": {"status": "ready", "evidence_ids": ["requirements-01"]},
      "product_photos": {"status": "ready", "evidence_ids": ["product-photo-01"]},
      "output_types": {"status": "ready", "image_ids": ["01"]}
    },
    "conditional": {
      "vi_brand_guide": {"status": "not_available", "evidence_ids": []},
      "logo_spec": {"status": "not_available", "evidence_ids": []},
      "fabric_color": {"status": "not_available", "evidence_ids": []},
      "product_detail": {"status": "not_available", "evidence_ids": []},
      "layout_scene_reference": {"status": "not_available", "evidence_ids": []},
      "prohibited_information": {"status": "not_available", "evidence_ids": []},
      "wps_dispimg": {"status": "not_available", "evidence_ids": []},
      "other_materials": {"status": "not_available", "evidence_ids": []}
    }
  },
  "evidence_sources": [
    {
      "evidence_id": "requirements-01",
      "kind": "requirements_table",
      "media_type": "document",
      "path": "C:/absolute/requirements.xlsx",
      "sha256": "文件 SHA256",
      "view_image": null,
      "location": {
        "sheet": "Sheet1",
        "cell": "B7",
        "dispimg_id": null,
        "embedded_path": null
      }
    },
    {
      "evidence_id": "product-photo-01",
      "kind": "product_photo",
      "media_type": "image",
      "path": "C:/absolute/product.jpg",
      "sha256": "文件 SHA256",
      "view_image": {
        "status": "completed",
        "inspection_session_id": "inspection-intake-01",
        "checked_at": "2026-07-21T08:00:00Z",
        "notes": "已确认当前产品和可见细节"
      },
      "location": {
        "sheet": null,
        "cell": null,
        "dispimg_id": null,
        "embedded_path": null
      }
    }
  ],
  "product_baseline": {
    "base_images": ["C:/absolute/product.jpg"],
    "dimensions_source": {
      "evidence_id": "requirements-01",
      "sheet": "Sheet1",
      "cell": "B7"
    },
    "dimensions_original": "24 x 24 x 4 inch",
    "applicable_sku": ["SKU-01"],
    "must_preserve": ["以垫图确认的结构、面料、颜色、纹理和比例为准；逐图已批准变化除外"],
    "forbidden_changes": ["不得重设计产品或增加配件"]
  },
  "fabric_baseline": {
    "status": "not_available",
    "evidence": [],
    "applicable_color_or_sku": [],
    "forbidden_deviation": ["不得编造精确色值或纹理"]
  },
  "visual_baseline": {
    "evidence": [],
    "palette": "无 VI 时按任务确认的中性系列配色",
    "typography": "无 VI 时按任务确认的字体层级",
    "lighting": "统一光线规则",
    "layout": "统一信息层级",
    "fixed_elements": [],
    "variable_elements": []
  },
  "references": [
    {
      "reference_id": "ref-product-01",
      "evidence_id": "product-photo-01",
      "path": "C:/absolute/product.jpg",
      "role": "edit_target",
      "applies_to": ["01"],
      "source_location": {
        "sheet": null,
        "cell": null,
        "dispimg_id": null,
        "embedded_path": null
      },
      "view_image": {
        "status": "completed",
        "inspection_session_id": "inspection-intake-01",
        "checked_at": "2026-07-21T08:00:00Z",
        "notes": "已确认当前产品和可见细节"
      }
    }
  ],
  "images": [
    {
      "image_id": "01",
      "image_type": "副图",
      "output_type_original": "详情页",
      "goal": "解释一个明确销售任务",
      "copy_original": ["EXACT ENGLISH COPY"],
      "copy_corrections": [],
      "selling_points": ["需求表提供的卖点"],
      "color_evidence": {
        "mode": "requirements_text",
        "evidence_id": "requirements-01",
        "value_original": "Navy",
        "precision": "semantic_only",
        "applies_to_sku": ["SKU-01"]
      },
      "allowed_product_changes": [
        {
          "attribute": "color",
          "from_evidence_id": "product-photo-01",
          "to_evidence_id": "requirements-01",
          "scope": "只允许按 Navy 语义改色，不定义精确色值；其他外观不变"
        }
      ],
      "person_scene_basis": {
        "person_required": false,
        "target_user_evidence": "产品用途与美国目标用户",
        "scale_reference": "真实尺寸与适配载体",
        "decision": "本图不加入人物"
      },
      "reference_ids": ["ref-product-01"],
      "prompt_paths": [
        "C:/absolute/output/temp/temu-us-20260721-001/01/prompt-direct01.txt",
        "C:/absolute/output/temp/temu-us-20260721-001/01/prompt-direct02.txt",
        "C:/absolute/output/temp/temu-us-20260721-001/01/prompt-direct03.txt"
      ],
      "target_paths": {
        "direct_directory": "C:/absolute/output/gpt-images-2-direct",
        "final_directory": "C:/absolute/output/final",
        "final_stem": "product_副图_01"
      },
      "session": {
        "status": "not_dispatched",
        "session_id": null,
        "view_events": []
      },
      "execution": {
        "status": "planned",
        "next_attempt_no": 1,
        "accepted_direct_indexes": [],
        "selected_artifact_id": null,
        "final_artifact_ids": [],
        "last_error": null,
        "attempts": [],
        "final_inspections": []
      }
    }
  ]
}
```

`approval.scope_sha256` 对下列对象使用 UTF-8、键排序、紧凑分隔符的规范 JSON 计算 SHA256：任务级 `provider`、`platform`、`product_name`、`product_folder`、`main_session_id`、`material_inventory`、`evidence_sources`、产品/面料/视觉基准；每条参考的 `reference_id`、`evidence_id`、`path`、`role`、`applies_to`、`source_location`；每图的 `image_id`、`image_type`、`output_type_original`、目标、原文/修正、卖点、颜色证据、允许产品变化、人物/场景依据、`reference_ids` 和稳定 `target_paths`。批准时把同一值写入 `approved_scope_sha256`；范围变化时递增 `scope_version`、重算哈希、清空批准哈希并改回 `pending`。

`target_paths` 只保存稳定的 direct 目录、final 目录和 `final_stem`，不保存会从 `_v01` 递增到 `_v02` 的具体 final 文件名。`prompt_paths`、参考图的 intake `view_image` 状态、检查 Session、`session`、`execution` 和实际 final 产物编号都是运行状态，不进入审批哈希；它们的变化不能伪装成业务范围变化，也不能掩盖真实范围变化。

`material_inventory.required` 固定包含需求表、真实尺寸、清晰产品实拍和输出类型，状态都必须为 `ready`；前三项引用已登记证据，输出类型的 `image_ids` 必须完整覆盖全部图号。`material_inventory.conditional` 固定盘点 VI、logo、面料/颜色、细节、版式/场景、禁用信息、WPS `DISPIMG` 和其他素材；状态只用 `available` 或 `not_available`，前者必须有证据，后者不得伪挂证据。所有 `evidence_sources` 必须进入某个必需或条件性类别，不能留下未归类证据。

`evidence_sources` 保存需求表、WPS 嵌图、VI、实拍、色卡等来源及 SHA256，并用 `media_type` 区分 `document`、`image`、`text`。所有图片证据都必须保存素材检查 Subagent 的 `view_image` 身份、时间和非空结论；该身份不得等于 `main_session_id`。WPS 图片必须填工作表、单元格、`dispimg_id` 和导出后的 `embedded_path`。`references` 只保存会作为图片输入的证据；逐图通过 `reference_ids` 引用，避免复制和角色漂移。每条图片 reference 的路径和素材检查记录必须与对应 `evidence_sources` 一致。

`image_type` 是规范化后的 `主图` 或 `副图`，用于命名和清单；`output_type_original` 原样保存需求表中的详情、SKU、颜色图等称呼。`copy_original` 永远保存需求表原文；修正只写入 `copy_corrections`，每项包含 `from`、`to` 和 `reason`。

`execution.attempts` 是不可删除、不可覆盖且按 `attempt_no` 严格递增的调用历史。发起渠道调用前先追加状态为 `calling` 的当前尝试，至少写入：`attempt_no`、`approval_scope_version`、`approval_scope_sha256`、`session_id`、`input_reference_ids`、本 Session 的 `view_events`、`prompt_id`、提示词路径/哈希、快照路径/哈希和 `call_started_at`。`prompt_id` 必须是去空白后非空的字符串，`call_started_at` 不得早于快照创建时间或晚于 capture 固定的本次 UTC 捕获时间。调用归档后在该对象中写入渠道返回路径、结果 `artifact_id`、产物类型、直出序号、最终状态、拒绝/失败原因、来源模式、来源/目标路径与哈希、尺寸，以及检查 Subagent 编号、检查时间和检查结论；无产物的超时也必须改为 `failed` 并保留。`last_error` 只作为最新摘要。

`execution.final_inspections` 保存 final 的独立终检记录。每条固定包含 `artifact_id`、`inspection_session_id`、`checked_at`、非空 `notes` 和七项严格布尔 `visual_checks`。当前合法 final 必须且只能对应一条记录；检查 Session 不得等于该 final 来源的生成 `session_id`，检查时间不得早于 final 生成时间，七项必须全部为 `true`。`verify` 会把缺失、重复、自检、失败或无法与唯一 final 对账的记录判为错误。

历史 attempt 按自身 `approval_scope_version`/`approval_scope_sha256` 校验：其历史 `session_id`、`input_reference_ids` 和 `view_events` 必须互相一致，提示词/快照仍严格按路径和哈希验证；accepted/rejected 还必须与其 `artifact_id` 唯一绑定的清单行在审批范围和全部 provenance 字段上一致。只有当前 `calling`，以及绑定当前审批范围产物的 accepted/rejected attempt，必须等于当前 Session、`reference_ids` 和完整 `view_events`。重新批准后不得改写或删除旧 attempts 来迎合当前引用状态。

同一图号只能有一个 `calling` 尝试。产物工具只允许捕获这个当前调用，或在尚未写入当前对象时使用大于全部历史尝试号的新值；已经 `failed`、`rejected` 或完成的尝试号不得复用。`capture` 返回后必须立即归档该尝试；仍有 `calling` 时，`finalize` 和 `verify` 必须失败。

产物工具从清单位置自动定位本任务 JSON，重新计算审批哈希，并校验 `approval.status`、批准哈希、用户确认原文、图型、独立 `session_id` 以及本 Session 对全部 `reference_ids` 的 `view_events`。校验失败时，`capture`、`finalize` 和 `verify` 都不得给出可交付结果。

## 3. 状态流转

`job_status` 只使用：`intake`、`blocked`、`awaiting_approval`、`approved`、`in_progress`、`ready_for_validation`、`complete`。

逐图 `execution.status` 只使用：`planned`、`approved`、`dispatched`、`generating`、`awaiting_review`、`blocked`、`complete`。每次状态变化立即原子写回；错误追加到 `attempts` 并同步 `last_error`，不得删除已有尝试和产物清单。只有批准范围哈希仍一致、`verify` 成功且业务检查完成后才能写 `complete`。

## 4. 独立生成与检查 Subagent

每个图号必须创建全新的独立生成子 Session。主 Session 只传递该图号的最小任务包：

- `task_id`、批准范围版本/哈希、`provider`、`platform`、产品名、产品文件夹和图号。
- 已确认的逐图目标、图型、输出类型、卖点、英文原文和已批准的最小修正。
- 产品/面料基准、统一视觉基准中与本图有关的部分。
- 本图参考图的绝对路径、角色和 `view_image` 状态。
- 三个提示词文件路径、目标 direct/final 路径、当前 `attempt_no` 和缺失的 `direct_index`。
- 渠道适配器路径和产物清单路径。

不得传递上一图的临时对话、图片编号、人物、场景、文案或未被本图引用的参考图。生成子 Session 结束时只回写最终提示词、参考角色、渠道结果和候选路径，不得给自己的候选填写验收结论。

素材图片、每个 `direct/revision` 候选和每个 final 都必须交给检查 Subagent。产物检查 Subagent 必须同时不同于对应生成 Session 和顶层 `main_session_id`，逐张执行 `view_image` 后返回检查身份、时间、非空结论和七项检查；final 还要绑定 `artifact_id`。主 Session 只负责分派、接收结构化检查结果、执行 `capture/finalize/verify` 和汇总，不得自行补填检查结果。环境不能建立生成子 Session 或检查 Subagent 时立即阻塞。

## 5. 图片角色和查看记录

每张输入图片只能按当前图号显式登记下列角色之一：

- `edit_target`：当前产品图/编辑目标。
- `product_identity`：产品身份和外观依据。
- `fabric_material`：面料或材质依据。
- `detail`：细节依据。
- `layout`：仅版式和信息组织参考。
- `style`：仅视觉语言参考。
- `scene`：仅场景类型和氛围参考。
- `insert`：需求明确要求插入的辅助素材。

所有会提供给渠道的输入图都必须先由素材检查 Subagent 逐张执行 `view_image`。未查看的图不能标为 `completed`、不能进入最小任务包，也不能声称已传给模型。每个新生成子 Session 仍需重新查看自己的输入、重建 Image 编号，并在本图 `session.view_events` 追加 `session_id`、`reference_id`、当前 `image_label`、查看时间和观察结果；这是调用绑定记录，不能替代素材检查 Subagent 的 intake 检查。禁止沿用上一图的 Image 1、Image 2 等编号。

## 6. 提示词结构

每个提示词单独保存为 UTF-8 `.txt`，使用下列结构；不适用的段落写“无”，不要保留说明性占位符。

```text
【图片比例】
1:1 正方形构图。

【画面目标】
本图唯一销售任务和输出类型。

【画面构成】
产品位置、场景、人物选择及依据、背景、道具、留白、英文文字区域和信息层级。

【产品输入与不可变项】
列出 Image 编号及角色。产品外观以产品/面料垫图为准；保留产品结构、面料、颜色、纹理和比例，不重设计产品，不增加不存在的配件。若 `allowed_product_changes` 批准颜色变化，只写证据、目标 SKU 和允许范围，并明确除该颜色变化外其余外观不变。不要用文字重新定义未获批准的产品外观。

【颜色依据】
仅写 `color_evidence` 的证据来源、精度和展示方式；文字颜色证据不得扩展成精确色值，证据不足时写明颜色展示区域留白。

【view_image 输入记录】
列出本 Session 已查看的 Image 编号、绝对路径和角色。

【文案】
逐字列出获准英文文案；无文案时明确写“无文字”。禁止中文、乱码和新增卖点。

【风格与比例】
引用统一视觉基准；写明真实尺寸、载体/人物参照和透视约束。

【参考边界】
layout/style/scene 只定义相应角色，不得替换产品、照搬人物或第三方品牌内容。

【禁止项】
列出本图合规禁项、跨图污染项和不能出现的内容。
```

家居或家具类场景中含产品时，在不违反 VI 或需求表的前提下加入固定风格约束：“场景充满生活感，专业电商摄影风格，专业打光，保持产品透视角度正确，产品光影自然融入场景，looks like a premium furniture brand catalog photo。”其他品类保留相同摄影、透视和自然融合要求，但把 `furniture` 换成需求表可证明的真实品类，不能擅自把商品归为家具。这类风格描述不能覆盖实拍产品。人物不得默认写成“欧洲年轻女性”；只写本图依据支持的人物，没有依据或必要性时不加入。

## 7. 三版提示词差异

在首次调用前准备三个不同的提示词文件和 `prompt_id`。三版必须在不改变产品、文案事实和合规边界的前提下，对构图、镜头、场景组织、信息层级或留白作实质调整；只改标点、形容词顺序、随机种子或文件名不算实质差异。

每次失败后可以新增 `attempt` 提示词，但不得覆盖旧文件。有效直出由验收后分配 `direct_index`，不是按调用次数分配；提示词文件和 SHA256 由产物清单永久关联。
