#!/usr/bin/env python3
"""记录、恢复并验收 TEMU 生图产物。"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from PIL import Image, UnidentifiedImageError
except ModuleNotFoundError:
    Image = None

    class UnidentifiedImageError(OSError):
        """Pillow 不可用时保留统一异常类型。"""


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


class TrackerError(ValueError):
    """表示可预期的产物追踪或验收错误。"""


class ChineseHelpFormatter(argparse.HelpFormatter):
    """将 argparse 的用法前缀统一为中文。"""

    def add_usage(self, usage: str | None, actions: Any, groups: Any, prefix: str | None = None) -> None:
        super().add_usage(usage, actions, groups, prefix="用法：" if prefix is None else prefix)


class ChineseArgumentParser(argparse.ArgumentParser):
    """将 argparse 的帮助分组和常见错误统一为中文。"""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("formatter_class", ChineseHelpFormatter)
        super().__init__(*args, **kwargs)
        self._optionals.title = "选项"
        for action in self._actions:
            if isinstance(action, argparse._HelpAction):
                action.help = "显示本帮助并退出"

    def error(self, message: str) -> None:
        replacements = (
            ("the following arguments are required:", "缺少必填参数："),
            ("invalid choice:", "无效选项："),
            ("invalid int value:", "整数值无效："),
            ("choose from", "可选值"),
            ("expected one argument", "需要一个参数值"),
            ("unrecognized arguments:", "无法识别的参数："),
            ("argument ", "参数 "),
        )
        for source, target in replacements:
            message = message.replace(source, target)
        self.print_usage(sys.stderr)
        self.exit(2, f"参数错误：{message}\n")


REQUIRED_VISUAL_CHECKS = {
    "current_product",
    "english_only",
    "no_pollution",
    "product_preserved",
    "scale_correct",
    "text_correct",
    "platform_compliant",
}
VALID_KINDS = {"direct", "revision", "final"}
VALID_STATUSES = {"accepted", "rejected"}
VALID_PROVENANCE = {"tool_return", "snapshot_diff", "derivation"}
VALID_REFERENCE_ROLES = {
    "edit_target", "product_identity", "fabric_material", "detail",
    "layout", "style", "scene", "insert",
}
REQUIRED_MATERIAL_CATEGORIES = {
    "requirements_table": "需求表",
    "real_dimensions": "真实尺寸",
    "product_photos": "清晰产品实拍图",
    "output_types": "输出类型",
}
CONDITIONAL_MATERIAL_CATEGORIES = {
    "vi_brand_guide": "VI/brand guide",
    "logo_spec": "logo 规范",
    "fabric_color": "面料/色卡/颜色代号",
    "product_detail": "产品细节图",
    "layout_scene_reference": "版式/场景参考",
    "prohibited_information": "禁用信息",
    "wps_dispimg": "WPS DISPIMG",
    "other_materials": "其他素材",
}
VALID_EVIDENCE_MEDIA_TYPES = {"document", "image", "text"}
VALID_EXECUTION_STATUSES = {
    "planned", "approved", "dispatched", "generating",
    "awaiting_review", "blocked", "complete",
}
VALID_ATTEMPT_STATUSES = {"calling", "accepted", "rejected", "failed"}
ARTIFACT_SCHEMA_VERSION = 5
JOB_SCHEMA_VERSION = 1
REQUIRED_RECORD_FIELDS = {
    "schema_version",
    "artifact_id",
    "task_id",
    "provider",
    "platform",
    "product_name",
    "image_id",
    "image_type",
    "immutable_identity_sha256",
    "approval_scope_version",
    "approval_scope_sha256",
    "session_id",
    "attempt_no",
    "direct_index",
    "artifact_kind",
    "prompt_id",
    "prompt_path",
    "prompt_sha256",
    "call_started_at",
    "captured_at",
    "provenance_mode",
    "source_path",
    "source_sha256",
    "target_path",
    "target_sha256",
    "width",
    "height",
    "status",
    "visual_checks",
    "inspection_session_id",
    "inspection_checked_at",
    "inspection_notes",
    "rejection_reason",
    "derived_from_artifact_id",
    "snapshot_path",
    "snapshot_sha256",
    "supersedes_artifact_id",
    "supersession_reason",
}

SCOPE_REFERENCE_FIELDS = (
    "reference_id", "evidence_id", "path", "role", "applies_to", "source_location",
)
SCOPE_IMAGE_FIELDS = (
    "image_id", "image_type", "output_type_original", "goal", "copy_original",
    "copy_corrections", "selling_points", "color_evidence", "allowed_product_changes",
    "person_scene_basis", "reference_ids", "target_paths",
)


def _absolute(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def _sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _approval_scope_payload(job: dict[str, Any]) -> dict[str, Any]:
    references = job.get("references")
    images = job.get("images")
    if not isinstance(references, list) or not all(isinstance(item, dict) for item in references):
        raise TrackerError("任务 JSON 的 references 必须是对象数组")
    if not isinstance(images, list) or not all(isinstance(item, dict) for item in images):
        raise TrackerError("任务 JSON 的 images 必须是对象数组")
    return {
        "provider": job.get("provider"),
        "platform": job.get("platform"),
        "product_name": job.get("product_name"),
        "product_folder": job.get("product_folder"),
        "main_session_id": job.get("main_session_id"),
        "material_inventory": job.get("material_inventory"),
        "evidence_sources": job.get("evidence_sources"),
        "product_baseline": job.get("product_baseline"),
        "fabric_baseline": job.get("fabric_baseline"),
        "visual_baseline": job.get("visual_baseline"),
        "references": [
            {key: reference.get(key) for key in SCOPE_REFERENCE_FIELDS}
            for reference in references
        ],
        "images": [
            {key: image.get(key) for key in SCOPE_IMAGE_FIELDS}
            for image in images
        ],
    }


def _immutable_identity_payload(job: dict[str, Any]) -> dict[str, Any]:
    images = job.get("images")
    if not isinstance(images, list) or not images or not all(isinstance(item, dict) for item in images):
        raise TrackerError("任务 JSON 的 images 必须是非空对象数组")
    image_identity: list[tuple[str, str]] = []
    for image in images:
        image_id = image.get("image_id")
        image_type = image.get("image_type")
        if not isinstance(image_id, str) or not image_id.strip():
            raise TrackerError("任务 JSON 的 image_id 必须为非空字符串")
        if not isinstance(image_type, str) or not image_type.strip():
            raise TrackerError(f"图号 {image_id} 的 image_type 必须为非空字符串")
        image_identity.append((image_id, image_type))
    return {
        "task_id": job.get("task_id"),
        "provider": job.get("provider"),
        "platform": job.get("platform"),
        "product_name": job.get("product_name"),
        "images": sorted(image_identity),
    }


def _immutable_identity_sha256(job: dict[str, Any]) -> str:
    return _canonical_sha256(_immutable_identity_payload(job))


def _require_pillow() -> None:
    if Image is None:
        raise TrackerError("缺少 Pillow，无法读取或调整图片；请在运行本脚本的 Python 环境安装 Pillow")


def _image_size(path: str | Path) -> tuple[int, int]:
    _require_pillow()
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            return image.size
    except (OSError, UnidentifiedImageError) as error:
        raise TrackerError(f"无法读取图片：{_absolute(path)}") from error


def _image_format(path: str | Path) -> str | None:
    _require_pillow()
    try:
        with Image.open(path) as image:
            return image.format
    except (OSError, UnidentifiedImageError) as error:
        raise TrackerError(f"无法读取图片：{_absolute(path)}") from error


def _validate_path_component(value: str, label: str) -> None:
    if not value or value in {".", ".."} or re.search(r'[<>:"/\\|?*]', value) or value.endswith((" ", ".")):
        raise TrackerError(f"{label} 不能包含路径分隔符、Windows 保留字符或结尾空格/点")


def _artifact_base_name(product_name: str, image_type: str, image_id: str) -> str:
    _validate_path_component(product_name, "产品名称")
    _validate_path_component(image_type, "图型")
    _validate_path_component(image_id, "图号")
    match = re.search(r"(\d+)$", image_id)
    if match is None:
        raise TrackerError("图号必须以数字序号结尾，才能校验产物命名")
    return f"{product_name}_{image_type}_{match.group(1)}"


def _validate_capture_filename(
    path: str | Path, *, product_name: str, image_type: str, image_id: str,
    attempt_no: int, direct_index: int | None, artifact_kind: str, status: str,
    supersedes_artifact_id: str | None = None,
) -> None:
    base = _artifact_base_name(product_name, image_type, image_id)
    name = _absolute(path).name
    if status == "rejected":
        expected = f"{base}_attempt{attempt_no:02d}_rejected.png"
        if name != expected:
            raise TrackerError(f"作废产物命名无效，应为：{expected}")
        return
    if artifact_kind == "direct":
        suffix = f"_replacement{attempt_no:02d}" if supersedes_artifact_id else ""
        expected = f"{base}_direct{direct_index:02d}{suffix}.png"
        if name != expected:
            raise TrackerError(f"有效直出命名无效，应为：{expected}")
        return
    pattern = re.compile(rf"{re.escape(base)}_revision\d{{2,}}\.png")
    if pattern.fullmatch(name) is None:
        raise TrackerError(f"渠道内修订命名无效，应使用：{base}_revision01.png")


def _validate_final_filename(path: str | Path, record: dict[str, Any]) -> None:
    base = _artifact_base_name(
        str(record.get("product_name", "")),
        str(record.get("image_type", "")),
        str(record.get("image_id", "")),
    )
    name = _absolute(path).name
    if re.fullmatch(rf"{re.escape(base)}_v\d{{2,}}\.png", name) is None:
        raise TrackerError(f"最终图命名无效，应使用：{base}_v01.png")


def _provider_output_root(manifest_path: str | Path, provider: str) -> Path:
    manifest = _absolute(manifest_path)
    if provider == "imagegen" and (
        manifest.name != "_imagegen_manifest.jsonl" or manifest.parent.name != "gpt-images-2-direct"
    ):
        raise TrackerError("imagegen 清单必须位于 output/gpt-images-2-direct/_imagegen_manifest.jsonl")
    if manifest.parent.parent.name != "output":
        raise TrackerError("渠道清单目录必须位于产品文件夹的 output 下")
    return manifest.parent.parent


def _validate_capture_directory(
    destination: str | Path, manifest_path: str | Path, *, provider: str, task_id: str,
    image_id: str, artifact_kind: str, status: str,
) -> None:
    _validate_path_component(task_id, "任务编号")
    _validate_path_component(image_id, "图号")
    output_root = _provider_output_root(manifest_path, provider)
    if status == "rejected":
        expected = output_root / "temp" / f"rejected-{provider}"
    elif artifact_kind == "direct":
        expected = _absolute(manifest_path).parent
    else:
        expected = output_root / "temp" / task_id / image_id
    if _absolute(destination).parent != expected.resolve():
        raise TrackerError(f"产物目录无效，应保存到：{expected.resolve()}")


def _validate_call_files_directory(
    snapshot_path: str | Path, prompt_path: str | Path, manifest_path: str | Path, *,
    provider: str, task_id: str, image_id: str,
) -> None:
    expected = _provider_output_root(manifest_path, provider) / "temp" / task_id / image_id
    expected = expected.resolve()
    if _absolute(snapshot_path).parent != expected:
        raise TrackerError(f"调用前快照目录无效，应保存到：{expected}")
    if _absolute(prompt_path).parent != expected:
        raise TrackerError(f"提示词目录无效，应保存到：{expected}")


def _validate_final_directory(destination: str | Path, manifest_path: str | Path, provider: str) -> None:
    expected = _provider_output_root(manifest_path, provider) / "final"
    if _absolute(destination).parent != expected.resolve():
        raise TrackerError(f"最终图目录无效，应保存到：{expected.resolve()}")


def _image_state(path: Path) -> dict[str, Any] | None:
    try:
        width, height = _image_size(path)
        stat = path.stat()
        return {
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
            "sha256": _sha256(path),
            "width": width,
            "height": height,
        }
    except (TrackerError, OSError):
        return None


def _copy_exclusive(source_path: str | Path, target_path: str | Path) -> None:
    """用排他创建复制文件；目标已存在时绝不覆盖。"""
    source = _absolute(source_path)
    target = _absolute(target_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0))
    except FileExistsError:
        raise
    try:
        with source.open("rb") as input_file, os.fdopen(descriptor, "wb") as output_file:
            descriptor = -1
            shutil.copyfileobj(input_file, output_file, length=1024 * 1024)
    except Exception:
        if descriptor != -1:
            os.close(descriptor)
        try:
            target.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _write_exclusive(path: str | Path, content: bytes) -> None:
    target = _absolute(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0))
    except FileExistsError:
        raise
    try:
        with os.fdopen(descriptor, "wb") as output_file:
            descriptor = -1
            output_file.write(content)
    except Exception:
        if descriptor != -1:
            os.close(descriptor)
        try:
            target.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _load_manifest(manifest_path: str | Path) -> list[dict[str, Any]]:
    path = _absolute(manifest_path)
    if not path.exists():
        return []
    try:
        records: list[dict[str, Any]] = []
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise TrackerError(f"清单第 {line_no} 行不是对象")
            records.append(value)
        return records
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise TrackerError(f"无法读取清单：{path}") from error


def _append_manifest(manifest_path: str | Path, record: dict[str, Any]) -> None:
    path = _absolute(manifest_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as manifest:
        manifest.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _restore_manifest(manifest_path: str | Path, existed: bool, byte_count: int) -> None:
    """在追加失败时恢复本次调用前的清单长度。"""
    path = _absolute(manifest_path)
    try:
        if existed and path.exists():
            with path.open("r+b") as manifest:
                manifest.truncate(byte_count)
        elif not existed:
            path.unlink(missing_ok=True)
    except OSError:
        pass


def _read_prompt(prompt_path: str | Path) -> tuple[Path, str]:
    path = _absolute(prompt_path)
    if not path.is_file():
        raise TrackerError(f"提示词文件不存在：{path}")
    if path.suffix.lower() != ".txt":
        raise TrackerError("提示词文件必须使用 .txt 扩展名")
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeError as error:
        raise TrackerError(f"提示词文件必须是有效 UTF-8：{path}") from error
    except OSError as error:
        raise TrackerError(f"提示词文件无法读取：{path}") from error
    if not content.strip():
        raise TrackerError("提示词内容不能为空")
    try:
        return path, _sha256(path)
    except OSError as error:
        raise TrackerError(f"提示词文件无法读取：{path}") from error


def _same_image_group(record: dict[str, Any], task_id: str, image_id: str) -> bool:
    return record.get("task_id") == task_id and record.get("image_id") == image_id


BASE_GROUP_FIELDS = ("task_id", "image_id", "provider", "platform", "product_name", "image_type")
GROUP_FIELDS = BASE_GROUP_FIELDS + ("approval_scope_version", "approval_scope_sha256")


def _same_artifact_group(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return all(left.get(field) == right.get(field) for field in GROUP_FIELDS)


def _same_base_artifact_group(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return all(left.get(field) == right.get(field) for field in BASE_GROUP_FIELDS)


def _record_matches_approval(record: dict[str, Any], approval_context: dict[str, Any]) -> bool:
    return (
        record.get("approval_scope_version") == approval_context.get("scope_version")
        and record.get("approval_scope_sha256") == approval_context.get("scope_sha256")
    )


def _require_matching_immutable_identity(
    records: list[dict[str, Any]], *, immutable_identity_sha256: str,
) -> None:
    mismatched = [
        item for item in records
        if item.get("immutable_identity_sha256") != immutable_identity_sha256
    ]
    if mismatched:
        raise TrackerError(
            "当前 job 与历史清单的不可变任务身份不一致；必须建立新 task 并使用独立输出根目录和清单"
        )


def _inactive_artifact_ids(records: list[dict[str, Any]]) -> set[str]:
    inactive = {
        item["supersedes_artifact_id"]
        for item in records
        if isinstance(item.get("supersedes_artifact_id"), str) and item.get("supersedes_artifact_id")
    }
    changed = True
    while changed:
        changed = False
        for item in records:
            identifier = item.get("artifact_id")
            parent_id = item.get("derived_from_artifact_id")
            if isinstance(identifier, str) and parent_id in inactive and identifier not in inactive:
                inactive.add(identifier)
                changed = True
    return inactive


def _all_visual_checks_pass(record: dict[str, Any]) -> bool:
    checks = record.get("visual_checks")
    return isinstance(checks, dict) and all(checks.get(key) is True for key in REQUIRED_VISUAL_CHECKS)


def _is_text_only_rejected(record: dict[str, Any]) -> bool:
    checks = record.get("visual_checks")
    if (
        record.get("status") != "rejected"
        or record.get("artifact_kind") not in {"direct", "revision"}
        or not isinstance(checks, dict)
        or checks.get("text_correct") is not False
        or not record.get("rejection_reason")
    ):
        return False
    return all(checks.get(key) is True for key in REQUIRED_VISUAL_CHECKS - {"text_correct"})


def _is_valid_revision_parent(record: dict[str, Any]) -> bool:
    if record.get("artifact_kind") not in {"direct", "revision"}:
        return False
    semantically_allowed = (
        record.get("status") == "accepted" and _all_visual_checks_pass(record)
    ) or _is_text_only_rejected(record)
    if not semantically_allowed or record.get("source_sha256") != record.get("target_sha256"):
        return False
    if not all(
        _record_file_matches(record, path_key, hash_key)
        for path_key, hash_key in (
            ("prompt_path", "prompt_sha256"),
            ("source_path", "source_sha256"),
            ("target_path", "target_sha256"),
        )
    ):
        return False
    try:
        target = Path(record["target_path"])
        dimensions = _image_size(target)
        return (
            _image_format(target) == "PNG"
            and dimensions[0] == dimensions[1]
            and dimensions == (record.get("width"), record.get("height"))
        )
    except (KeyError, TrackerError, OSError):
        return False


def write_snapshot(source_dir: str | Path, snapshot_path: str | Path) -> dict[str, Any]:
    """排他写入调用前图片状态快照。"""
    _require_pillow()
    directory = _absolute(source_dir)
    destination = _absolute(snapshot_path)
    if not directory.is_dir():
        raise TrackerError(f"来源目录不存在：{directory}")
    images: dict[str, dict[str, Any]] = {}
    for candidate in directory.rglob("*"):
        if not candidate.is_file() or candidate.resolve() == destination:
            continue
        state = _image_state(candidate)
        if state is not None:
            images[str(candidate.resolve())] = state
    snapshot = {
        "schema_version": 2,
        "source_dir": str(directory),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "files": sorted(images),
        "images": {path: images[path] for path in sorted(images)},
    }
    try:
        _write_exclusive(destination, (json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    except FileExistsError as error:
        raise TrackerError(f"快照文件已存在，拒绝覆盖：{destination}") from error
    return snapshot


def _parse_datetime(value: str, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as error:
        raise TrackerError(f"{field_name} 必须是带时区的 ISO 8601 时间") from error
    if parsed.tzinfo is None:
        raise TrackerError(f"{field_name} 必须包含时区")
    return parsed


def _validate_absolute_hashed_file(
    value: dict[str, Any], path_key: str, hash_key: str, label: str,
) -> tuple[Path, str]:
    path_text = value.get(path_key)
    expected_hash = value.get(hash_key)
    if not isinstance(path_text, str) or not path_text.strip() or not Path(path_text).is_absolute():
        raise TrackerError(f"{label}的 {path_key} 必须是非空绝对路径")
    if not isinstance(expected_hash, str) or re.fullmatch(r"[0-9a-f]{64}", expected_hash) is None:
        raise TrackerError(f"{label}的 {hash_key} 必须是 64 位小写 SHA256")
    path = Path(path_text)
    if not path.is_file():
        raise TrackerError(f"{label}的文件不存在：{path}")
    try:
        actual_hash = _sha256(path)
    except OSError as error:
        raise TrackerError(f"{label}的文件无法读取：{path}") from error
    if actual_hash != expected_hash:
        raise TrackerError(f"{label}的 {path_key} 哈希不匹配")
    return path, expected_hash


def _validate_inspection_record(
    value: Any, *, label: str, main_session_id: str,
) -> str:
    if not isinstance(value, dict) or value.get("status") != "completed":
        raise TrackerError(f"{label}的 view_image 尚未 completed")
    inspector = value.get("inspection_session_id")
    if not isinstance(inspector, str) or not inspector.strip():
        raise TrackerError(f"{label}缺少素材检查 Subagent 编号")
    if inspector == main_session_id:
        raise TrackerError(f"{label}的素材检查 Subagent 必须与主 Session 不同")
    _parse_datetime(value.get("checked_at"), f"{label}的 view_image.checked_at")
    if not isinstance(value.get("notes"), str) or not value["notes"].strip():
        raise TrackerError(f"{label}的 view_image 查看记录缺少 notes")
    return inspector


def _validate_material_inventory(job: dict[str, Any]) -> dict[str, Any]:
    main_session_id = job.get("main_session_id")
    if not isinstance(main_session_id, str) or not main_session_id.strip():
        raise TrackerError("任务 JSON 缺少非空 main_session_id")

    sources = job.get("evidence_sources")
    if not isinstance(sources, list) or not sources or not all(isinstance(item, dict) for item in sources):
        raise TrackerError("任务 JSON 的 evidence_sources 必须是非空对象数组")
    evidence_ids = [item.get("evidence_id") for item in sources]
    if any(not isinstance(item, str) or not item.strip() for item in evidence_ids):
        raise TrackerError("素材证据的 evidence_id 必须为非空字符串")
    if len(evidence_ids) != len(set(evidence_ids)):
        raise TrackerError("素材证据的 evidence_id 必须唯一")
    sources_by_id = dict(zip(evidence_ids, sources))
    material_inspection_ids: set[str] = set()
    for source in sources:
        evidence_id = source["evidence_id"]
        kind = source.get("kind")
        if not isinstance(kind, str) or not kind.strip():
            raise TrackerError(f"素材证据 {evidence_id} 缺少 kind")
        media_type = source.get("media_type")
        if media_type not in VALID_EVIDENCE_MEDIA_TYPES:
            raise TrackerError(f"素材证据 {evidence_id} 的 media_type 无效")
        path = source.get("path")
        if not isinstance(path, str) or not path.strip() or not Path(path).is_absolute():
            raise TrackerError(f"素材证据 {evidence_id} 的 path 必须是非空绝对路径")
        digest = source.get("sha256")
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise TrackerError(f"素材证据 {evidence_id} 的 sha256 必须是 64 位小写 SHA256")
        verified_path, _ = _validate_absolute_hashed_file(
            source, "path", "sha256", f"素材证据 {evidence_id}",
        )
        if media_type == "image":
            _image_size(verified_path)
            material_inspection_ids.add(_validate_inspection_record(
                source.get("view_image"), label=f"素材证据 {evidence_id}",
                main_session_id=main_session_id,
            ))

    inventory = job.get("material_inventory")
    if not isinstance(inventory, dict):
        raise TrackerError("任务 JSON 缺少 material_inventory 素材盘点")
    required = inventory.get("required")
    conditional = inventory.get("conditional")
    if not isinstance(required, dict):
        raise TrackerError("必需素材盘点必须是对象")
    if not isinstance(conditional, dict):
        raise TrackerError("条件性素材盘点必须是对象")

    claimed_ids: set[str] = set()
    required_evidence: dict[str, list[str]] = {}
    for category, display_name in REQUIRED_MATERIAL_CATEGORIES.items():
        item = required.get(category)
        if not isinstance(item, dict):
            raise TrackerError(f"必需素材盘点缺少{display_name}")
        if item.get("status") != "ready":
            raise TrackerError(f"必需素材{display_name}尚未 ready")
        if category == "output_types":
            image_ids = item.get("image_ids")
            expected_ids = [image.get("image_id") for image in job.get("images", []) if isinstance(image, dict)]
            if (
                not isinstance(image_ids, list)
                or any(not isinstance(value, str) or not value.strip() for value in image_ids)
                or len(image_ids) != len(set(image_ids))
                or set(image_ids) != set(expected_ids)
            ):
                raise TrackerError("必需素材输出类型必须覆盖全部图号且不能重复")
            continue
        ids = item.get("evidence_ids")
        if not isinstance(ids, list) or not ids or any(value not in sources_by_id for value in ids):
            raise TrackerError(f"必需素材{display_name}缺少有效 evidence_ids")
        required_evidence[category] = ids
        claimed_ids.update(ids)
        if category == "requirements_table" and not any(
            sources_by_id[value].get("kind") == "requirements_table" for value in ids
        ):
            raise TrackerError("必需素材需求表没有 requirements_table 证据")
        if category == "product_photos" and not all(
            sources_by_id[value].get("media_type") == "image" for value in ids
        ):
            raise TrackerError("必需素材清晰产品实拍图必须引用图片证据")

    product_baseline = job.get("product_baseline")
    if not isinstance(product_baseline, dict):
        raise TrackerError("任务 JSON 缺少 product_baseline")
    dimensions_original = product_baseline.get("dimensions_original")
    if not isinstance(dimensions_original, str) or not dimensions_original.strip():
        raise TrackerError("真实尺寸缺少非空 dimensions_original 内容")
    dimensions_source = product_baseline.get("dimensions_source")
    if (
        not isinstance(dimensions_source, dict)
        or dimensions_source.get("evidence_id") not in required_evidence.get("real_dimensions", [])
    ):
        raise TrackerError("真实尺寸 dimensions_source 未绑定 real_dimensions 证据")
    base_images = product_baseline.get("base_images")
    product_paths = {
        str(_absolute(sources_by_id[value]["path"]))
        for value in required_evidence.get("product_photos", [])
    }
    if (
        not isinstance(base_images, list) or not base_images
        or any(not isinstance(value, str) or str(_absolute(value)) not in product_paths for value in base_images)
    ):
        raise TrackerError("product_baseline.base_images 必须绑定已登记的产品实拍图")
    images = job.get("images")
    if not isinstance(images, list) or any(
        not isinstance(item, dict)
        or not isinstance(item.get("output_type_original"), str)
        or not item["output_type_original"].strip()
        for item in images
    ):
        raise TrackerError("必需素材输出类型缺少逐图原始值")

    missing_conditional = [
        display_name for category, display_name in CONDITIONAL_MATERIAL_CATEGORIES.items()
        if category not in conditional
    ]
    if missing_conditional:
        raise TrackerError(f"条件性素材盘点缺少：{', '.join(missing_conditional)}")
    for category, item in conditional.items():
        display_name = CONDITIONAL_MATERIAL_CATEGORIES.get(category, category)
        if not isinstance(item, dict) or item.get("status") not in {"available", "not_available"}:
            raise TrackerError(f"条件性素材 {display_name} 的状态必须是 available 或 not_available")
        ids = item.get("evidence_ids")
        if not isinstance(ids, list) or any(value not in sources_by_id for value in ids):
            raise TrackerError(f"条件性素材 {display_name} 的 evidence_ids 无效")
        if item["status"] == "available" and not ids:
            raise TrackerError(f"条件性素材 {display_name} 标为 available 时必须提供证据")
        if item["status"] == "not_available" and ids:
            raise TrackerError(f"条件性素材 {display_name} 标为 not_available 时不能提供证据")
        claimed_ids.update(ids)
    unclaimed = sorted(set(evidence_ids) - claimed_ids)
    if unclaimed:
        raise TrackerError(f"素材证据未进入必需或条件性盘点：{', '.join(unclaimed)}")
    return {
        "main_session_id": main_session_id,
        "sources_by_id": sources_by_id,
        "inspection_session_ids": material_inspection_ids,
    }


def _validate_job_contract(job: dict[str, Any], image: dict[str, Any]) -> dict[str, Any]:
    image_id = image.get("image_id")
    material_context = _validate_material_inventory(job)
    main_session_id = material_context["main_session_id"]
    evidence_sources = material_context["sources_by_id"]
    references = job.get("references")
    if not isinstance(references, list) or not all(isinstance(item, dict) for item in references):
        raise TrackerError("任务 JSON 的 references 必须是对象数组")
    reference_ids = [item.get("reference_id") for item in references]
    if any(not isinstance(item, str) or not item.strip() for item in reference_ids):
        raise TrackerError("顶层 references 的 reference_id 必须为非空字符串")
    if len(reference_ids) != len(set(reference_ids)):
        raise TrackerError("顶层 references 的 reference_id 必须唯一")
    references_by_id = dict(zip(reference_ids, references))
    material_inspection_ids = set(material_context["inspection_session_ids"])
    for reference in references:
        reference_id = reference["reference_id"]
        if reference.get("role") not in VALID_REFERENCE_ROLES:
            raise TrackerError(f"引用 {reference_id} 的角色不在契约枚举中")
        applies_to = reference.get("applies_to")
        if not isinstance(applies_to, list) or not applies_to or not all(
            isinstance(item, str) and item.strip() for item in applies_to
        ):
            raise TrackerError(f"引用 {reference_id} 的 applies_to 必须是非空图号数组")
        evidence_id = reference.get("evidence_id")
        evidence = evidence_sources.get(evidence_id)
        if evidence is None or evidence.get("media_type") != "image":
            raise TrackerError(f"引用 {reference_id} 未绑定已登记的图片素材证据")
        if reference.get("path") != evidence.get("path"):
            raise TrackerError(f"引用 {reference_id} 的路径与素材证据不一致")
        view_image = reference.get("view_image")
        inspection_session_id = _validate_inspection_record(
            view_image, label=f"引用 {reference_id} ", main_session_id=main_session_id,
        )
        evidence_view = evidence.get("view_image")
        if any(
            view_image.get(field) != evidence_view.get(field)
            for field in ("status", "inspection_session_id", "checked_at", "notes")
        ):
            raise TrackerError(f"引用 {reference_id} 的素材检查记录与 evidence_sources 不一致")
        material_inspection_ids.add(inspection_session_id)

    selected_ids = image.get("reference_ids")
    if not isinstance(selected_ids, list) or not selected_ids:
        raise TrackerError(f"图号 {image_id} 缺少强制产品输入引用")
    if any(not isinstance(item, str) or not item.strip() for item in selected_ids):
        raise TrackerError(f"图号 {image_id} 的 reference_ids 必须是非空字符串数组")
    if len(selected_ids) != len(set(selected_ids)):
        raise TrackerError(f"图号 {image_id} 的 reference_ids 不能重复")
    missing_ids = [item for item in selected_ids if item not in references_by_id]
    if missing_ids:
        raise TrackerError(f"图号 {image_id} 的引用不存在：{', '.join(missing_ids)}")
    for reference_id in selected_ids:
        if image_id not in references_by_id[reference_id]["applies_to"]:
            raise TrackerError(f"引用 {reference_id} 的适用图号不包含当前图号 {image_id}")
    if not any(references_by_id[item].get("role") in {"edit_target", "product_identity"} for item in selected_ids):
        raise TrackerError(f"图号 {image_id} 至少需要一个 edit_target 或 product_identity 产品依据")

    session = image.get("session")
    if not isinstance(session, dict) or session.get("status") not in {
        "dispatched", "generating", "awaiting_review", "complete",
    }:
        raise TrackerError(f"图号 {image_id} 尚未进入独立子 Session")
    session_id = session.get("session_id")
    if not isinstance(session_id, str) or not session_id.strip():
        raise TrackerError(f"图号 {image_id} 缺少独立子 Session 编号")
    if session_id == main_session_id:
        raise TrackerError(f"图号 {image_id} 的生成 Session 必须与主 Session 不同")
    if session_id in material_inspection_ids:
        raise TrackerError(f"图号 {image_id} 的素材检查 Subagent 必须与生成 Session 不同")
    view_events = session.get("view_events")
    if not isinstance(view_events, list) or not view_events:
        raise TrackerError(f"图号 {image_id} 的本 Session 尚未查看输入，缺少 view_image 查看记录")
    viewed: set[str] = set()
    for event in view_events:
        if not isinstance(event, dict):
            raise TrackerError(f"图号 {image_id} 的 view_image 查看记录必须是对象")
        reference_id = event.get("reference_id")
        if event.get("session_id") != session_id:
            raise TrackerError(f"图号 {image_id} 的查看记录未绑定当前 session_id")
        if reference_id not in selected_ids:
            raise TrackerError(f"图号 {image_id} 的查看记录使用了非法 reference_id")
        if not isinstance(event.get("image_label"), str) or not event["image_label"].strip():
            raise TrackerError(f"图号 {image_id} 的查看记录缺少 image_label")
        _parse_datetime(event.get("checked_at"), f"图号 {image_id} 的查看记录 checked_at")
        if not isinstance(event.get("notes"), str) or not event["notes"].strip():
            raise TrackerError(f"图号 {image_id} 的查看记录缺少 notes")
        viewed.add(reference_id)
    missing_views = [item for item in selected_ids if item not in viewed]
    if missing_views:
        raise TrackerError(f"图号 {image_id} 的本 Session 尚未查看全部输入：{', '.join(missing_views)}")

    execution = image.get("execution")
    if not isinstance(execution, dict) or execution.get("status") not in VALID_EXECUTION_STATUSES:
        raise TrackerError(f"图号 {image_id} 的 execution.status 不在契约枚举中")
    attempts = execution.get("attempts")
    if not isinstance(attempts, list) or not all(isinstance(item, dict) for item in attempts):
        raise TrackerError(f"图号 {image_id} 的执行尝试记录无效")
    attempt_numbers = [item.get("attempt_no") for item in attempts]
    if any(type(item) is not int or item < 1 for item in attempt_numbers):
        raise TrackerError(f"图号 {image_id} 的执行尝试号无效")
    if attempt_numbers != sorted(set(attempt_numbers)):
        raise TrackerError(f"图号 {image_id} 的执行尝试号必须严格递增且不能重复")
    final_inspections = execution.get("final_inspections")
    if not isinstance(final_inspections, list) or not all(isinstance(item, dict) for item in final_inspections):
        raise TrackerError(f"图号 {image_id} 的 final_inspections 必须是对象数组")
    for inspection in final_inspections:
        if not isinstance(inspection.get("artifact_id"), str) or not inspection["artifact_id"].strip():
            raise TrackerError(f"图号 {image_id} 的最终图检查缺少 artifact_id")
        inspector = inspection.get("inspection_session_id")
        if not isinstance(inspector, str) or not inspector.strip():
            raise TrackerError(f"图号 {image_id} 的最终图检查缺少检查 Subagent 编号")
        _parse_datetime(inspection.get("checked_at"), f"图号 {image_id} 的最终图检查时间")
        if not isinstance(inspection.get("notes"), str) or not inspection["notes"].strip():
            raise TrackerError(f"图号 {image_id} 的最终图检查缺少检查结论")
        checks = inspection.get("visual_checks")
        if not isinstance(checks, dict) or set(checks) != REQUIRED_VISUAL_CHECKS or not all(
            type(value) is bool for value in checks.values()
        ):
            raise TrackerError(f"图号 {image_id} 的最终图检查必须包含七项严格布尔 visual_checks")
    approval = job.get("approval") if isinstance(job.get("approval"), dict) else {}
    current_scope_version = approval.get("scope_version")
    current_scope_sha256 = approval.get("scope_sha256")
    for attempt in attempts:
        attempt_no = attempt["attempt_no"]
        label = f"图号 {image_id} 的 attempt {attempt_no}"
        status = attempt.get("status")
        if status not in VALID_ATTEMPT_STATUSES:
            raise TrackerError(f"{label} 的尝试状态不在契约枚举中")
        attempt_scope_version = attempt.get("approval_scope_version")
        attempt_scope_sha256 = attempt.get("approval_scope_sha256")
        if type(attempt_scope_version) is not int or attempt_scope_version < 1:
            raise TrackerError(f"{label} 的 approval_scope_version 必须是正整数")
        if (
            not isinstance(attempt_scope_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", attempt_scope_sha256) is None
        ):
            raise TrackerError(f"{label} 的 approval_scope_sha256 必须是 64 位小写 SHA256")
        attempt_session_id = attempt.get("session_id")
        if not isinstance(attempt_session_id, str) or not attempt_session_id.strip():
            raise TrackerError(f"{label} 缺少历史 session_id")
        attempt_reference_ids = attempt.get("input_reference_ids")
        if (
            not isinstance(attempt_reference_ids, list) or not attempt_reference_ids
            or any(not isinstance(item, str) or not item.strip() for item in attempt_reference_ids)
            or len(attempt_reference_ids) != len(set(attempt_reference_ids))
        ):
            raise TrackerError(f"{label} 的历史 input_reference_ids 无效")
        attempt_view_events = attempt.get("view_events")
        if not isinstance(attempt_view_events, list) or not attempt_view_events:
            raise TrackerError(f"{label} 缺少历史 view_events")
        viewed_attempt_references: set[str] = set()
        for event in attempt_view_events:
            if not isinstance(event, dict):
                raise TrackerError(f"{label} 的历史 view_events 必须是对象数组")
            reference_id = event.get("reference_id")
            if event.get("session_id") != attempt_session_id:
                raise TrackerError(f"{label} 的历史 view_events 与历史 session_id 不一致")
            if reference_id not in attempt_reference_ids:
                raise TrackerError(f"{label} 的历史 view_events 使用了未登记引用")
            if not isinstance(event.get("image_label"), str) or not event["image_label"].strip():
                raise TrackerError(f"{label} 的历史 view_events 缺少 image_label")
            _parse_datetime(event.get("checked_at"), f"{label} 的历史 view_events.checked_at")
            if not isinstance(event.get("notes"), str) or not event["notes"].strip():
                raise TrackerError(f"{label} 的历史 view_events 缺少 notes")
            viewed_attempt_references.add(reference_id)
        if set(attempt_reference_ids) - viewed_attempt_references:
            raise TrackerError(f"{label} 的历史 view_events 未覆盖全部 input_reference_ids")
        binds_current_scope = (
            status == "calling"
            or (
                status in {"accepted", "rejected"}
                and attempt_scope_version == current_scope_version
                and attempt_scope_sha256 == current_scope_sha256
            )
        )
        if binds_current_scope:
            if attempt_scope_version != current_scope_version or attempt_scope_sha256 != current_scope_sha256:
                raise TrackerError(f"{label} 的 calling 未绑定当前审批范围")
            if attempt_session_id != session_id:
                raise TrackerError(f"{label} 未绑定当前 session_id")
            if attempt_reference_ids != selected_ids:
                raise TrackerError(f"{label} 的 input_reference_ids 与本图 reference_ids 不一致")
            if attempt_view_events != view_events:
                raise TrackerError(f"{label} 未保存完整的当前 Session view_events")
        if not isinstance(attempt.get("prompt_id"), str) or not attempt["prompt_id"].strip():
            raise TrackerError(f"{label} 缺少 prompt_id")
        _validate_absolute_hashed_file(attempt, "prompt_path", "prompt_sha256", label)
        _validate_absolute_hashed_file(attempt, "snapshot_path", "snapshot_sha256", label)
        _parse_datetime(attempt.get("call_started_at"), f"{label} 的 call_started_at")
        artifact_id = attempt.get("artifact_id")
        if status == "failed":
            if not isinstance(attempt.get("failure_reason"), str) or not attempt["failure_reason"].strip():
                raise TrackerError(f"{label} 的 failed 状态缺少失败原因")
            if artifact_id is not None:
                raise TrackerError(f"{label} 的 failed 状态不能包含 artifact_id")
        elif status in {"accepted", "rejected"}:
            if not isinstance(artifact_id, str) or not artifact_id.strip():
                raise TrackerError(f"{label} 的 {status} 状态缺少 artifact_id")
            failure_reason = attempt.get("failure_reason")
            if status == "rejected" and (
                not isinstance(failure_reason, str) or not failure_reason.strip()
            ):
                raise TrackerError(f"{label} 的 rejected 状态缺少失败原因")
            if status == "accepted" and failure_reason is not None:
                raise TrackerError(f"{label} 的 accepted 状态不能包含失败原因")
        elif artifact_id is not None:
            raise TrackerError(f"{label} 的 calling 状态不能提前包含 artifact_id")
    calling_attempts = [item for item in attempts if item.get("status") == "calling"]
    if len(calling_attempts) > 1:
        raise TrackerError(f"图号 {image_id} 同时存在多个未归档渠道调用")
    return {
        "session_id": session_id,
        "main_session_id": main_session_id,
        "reference_ids": selected_ids,
        "view_events": view_events,
        "execution": execution,
        "job_attempts": attempts,
        "calling_attempts": calling_attempts,
        "final_inspections": final_inspections,
    }


def _task_job_path(manifest_path: str | Path, provider: str, task_id: str) -> Path:
    _validate_path_component(task_id, "任务编号")
    return (_provider_output_root(manifest_path, provider) / "temp" / task_id / "_temu_job.json").resolve()


def _load_current_immutable_identity(
    manifest_path: str | Path, *, task_id: str, provider: str,
) -> str:
    job_path = _task_job_path(manifest_path, provider, task_id)
    if not job_path.is_file():
        raise TrackerError(f"任务 JSON 不存在：{job_path}")
    try:
        job = json.loads(job_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise TrackerError(f"任务 JSON 无法读取：{job_path}") from error
    if not isinstance(job, dict) or job.get("schema_version") != JOB_SCHEMA_VERSION:
        raise TrackerError(f"任务 JSON 版本无效：{job_path}")
    return _immutable_identity_sha256(job)


def _load_approved_job(
    manifest_path: str | Path, *, task_id: str, provider: str, platform: str,
    product_name: str, image_id: str, image_type: str, allow_calling: bool = False,
) -> dict[str, Any]:
    job_path = _task_job_path(manifest_path, provider, task_id)
    if not job_path.is_file():
        raise TrackerError(f"任务 JSON 不存在：{job_path}")
    try:
        job = json.loads(job_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise TrackerError(f"任务 JSON 无法读取：{job_path}") from error
    if not isinstance(job, dict) or job.get("schema_version") != JOB_SCHEMA_VERSION:
        raise TrackerError(f"任务 JSON 版本无效：{job_path}")
    expected_product_folder = _provider_output_root(manifest_path, provider).parent.resolve()
    identity = (
        ("task_id", task_id),
        ("provider", provider),
        ("platform", platform),
        ("product_name", product_name),
    )
    if any(job.get(field) != expected for field, expected in identity):
        raise TrackerError(
            "任务 JSON 与历史不可变任务身份不一致；必须建立新 task 并使用独立输出根目录和清单"
        )
    product_folder = job.get("product_folder")
    if not isinstance(product_folder, str) or _absolute(product_folder) != expected_product_folder:
        raise TrackerError("任务 JSON 的产品文件夹与清单位置不一致")

    approval = job.get("approval")
    if not isinstance(approval, dict) or approval.get("status") != "approved":
        raise TrackerError("当前任务范围尚未获得用户明确批准")
    if job.get("job_status") not in {"approved", "in_progress", "ready_for_validation", "complete"}:
        raise TrackerError("任务状态与已批准范围不一致")
    scope_version = approval.get("scope_version")
    scope_sha256 = approval.get("scope_sha256")
    approved_sha256 = approval.get("approved_scope_sha256")
    if type(scope_version) is not int or scope_version < 1:
        raise TrackerError("审批范围版本必须是大于 0 的整数")
    if not isinstance(scope_sha256, str) or re.fullmatch(r"[0-9a-f]{64}", scope_sha256) is None:
        raise TrackerError("审批范围 SHA256 无效")
    computed_sha256 = _canonical_sha256(_approval_scope_payload(job))
    if computed_sha256 != scope_sha256:
        raise TrackerError("任务内容与审批范围 SHA256 不一致，必须重新确认")
    if approved_sha256 != scope_sha256:
        raise TrackerError("当前任务范围尚未获得用户明确批准")
    confirmation_text = approval.get("confirmation_text")
    if not isinstance(confirmation_text, str) or not confirmation_text.strip():
        raise TrackerError("已批准任务缺少用户确认原文")
    _parse_datetime(approval.get("confirmed_at"), "用户确认时间")

    images = job.get("images")
    if not isinstance(images, list) or not images or not all(isinstance(item, dict) for item in images):
        raise TrackerError("任务 JSON 的 images 必须是非空对象数组")
    image_ids = [item.get("image_id") for item in images]
    if any(not isinstance(item, str) or not item.strip() for item in image_ids):
        raise TrackerError("任务 JSON 的 image_id 必须为非空字符串")
    if len(image_ids) != len(set(image_ids)):
        raise TrackerError("任务 JSON 的 image_id 必须唯一")
    image = next(
        (item for item in images if isinstance(item, dict) and item.get("image_id") == image_id),
        None,
    )
    if image is None:
        raise TrackerError(f"任务 JSON 中不存在图号：{image_id}")
    if image.get("image_type") != image_type:
        raise TrackerError(f"任务 JSON 中图号 {image_id} 的图型与清单不一致")
    target_paths = image.get("target_paths")
    if not isinstance(target_paths, dict):
        raise TrackerError(f"任务 JSON 中图号 {image_id} 缺少目标路径")
    expected_direct = _absolute(manifest_path).parent
    expected_final = _provider_output_root(manifest_path, provider) / "final"
    direct_directory = target_paths.get("direct_directory")
    final_directory = target_paths.get("final_directory")
    if not isinstance(direct_directory, str) or _absolute(direct_directory) != expected_direct:
        raise TrackerError(f"图号 {image_id} 的已批准直出目录与清单位置不一致")
    if not isinstance(final_directory, str) or _absolute(final_directory) != expected_final.resolve():
        raise TrackerError(f"图号 {image_id} 的已批准最终目录与交付位置不一致")
    expected_stem = _artifact_base_name(product_name, image_type, image_id)
    if target_paths.get("final_stem") != expected_stem:
        raise TrackerError(f"图号 {image_id} 的已批准最终文件名前缀无效，应为：{expected_stem}")
    contract = _validate_job_contract(job, image)
    calling_attempts = contract["calling_attempts"]
    if calling_attempts and not allow_calling:
        raise TrackerError(f"图号 {image_id} 的渠道调用尚未归档")
    return {
        "job_path": str(job_path),
        "job": job,
        "image": image,
        "scope_version": scope_version,
        "scope_sha256": scope_sha256,
        "immutable_identity_sha256": _immutable_identity_sha256(job),
        "session_id": contract["session_id"],
        "main_session_id": contract["main_session_id"],
        "reference_ids": contract["reference_ids"],
        "view_events": contract["view_events"],
        "execution": contract["execution"],
        "job_attempts": contract["job_attempts"],
        "calling_attempts": calling_attempts,
        "final_inspections": contract["final_inspections"],
    }


def _load_snapshot(snapshot_path: str | Path, source_dir: str | Path) -> tuple[Path, dict[str, Any]]:
    path = _absolute(snapshot_path)
    directory = _absolute(source_dir)
    if not path.is_file():
        raise TrackerError(f"调用前快照不存在：{path}")
    try:
        snapshot = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise TrackerError(f"调用前快照不可读：{path}") from error
    if not isinstance(snapshot, dict) or snapshot.get("schema_version") != 2:
        raise TrackerError(f"调用前快照版本无效：{path}")
    snapshot_dir = snapshot.get("source_dir")
    if not isinstance(snapshot_dir, str) or _absolute(snapshot_dir) != directory:
        raise TrackerError("调用前快照与当前渠道生成目录不一致")
    if not isinstance(snapshot.get("images"), dict):
        raise TrackerError(f"调用前快照缺少图片状态：{path}")
    _parse_datetime(snapshot.get("created_at"), "快照创建时间")
    return path, snapshot


def resolve_source(
    snapshot_path: str | Path,
    source_dir: str | Path,
    explicit_source: str | Path | None,
) -> tuple[Path, str]:
    """优先返回渠道明确路径；否则仅接受一个新增或发生变化的图片。"""
    _require_pillow()
    directory = _absolute(source_dir)
    if not directory.is_dir():
        raise TrackerError(f"来源目录不存在：{directory}")
    path, snapshot = _load_snapshot(snapshot_path, directory)
    if explicit_source is not None:
        source = _absolute(explicit_source)
        if not source.is_file() or _image_state(source) is None:
            raise TrackerError(f"工具返回的来源图片不存在或不可读：{source}")
        return source, "tool_return"

    before = snapshot["images"]

    candidates: list[Path] = []
    for candidate in directory.rglob("*"):
        if not candidate.is_file() or candidate.resolve() == path:
            continue
        state = _image_state(candidate)
        if state is None:
            continue
        previous = before.get(str(candidate.resolve()))
        if previous != state:
            candidates.append(candidate.resolve())
    if not candidates:
        raise TrackerError("快照差异没有发现新的或变更的来源图片")
    if len(candidates) != 1:
        raise TrackerError(f"快照差异发现多个候选来源图片（{len(candidates)} 个），无法确认归属")
    return candidates[0], "snapshot_diff"


def _check_capture_inputs(
    *, artifact_kind: str, status: str, direct_index: int | None,
    visual_checks: dict[str, bool] | None, rejection_reason: str | None,
) -> None:
    if artifact_kind not in {"direct", "revision"}:
        raise TrackerError("产物类型必须是 direct 或 revision")
    if status not in VALID_STATUSES:
        raise TrackerError("验收状态必须是 accepted 或 rejected")
    checks = visual_checks
    if not isinstance(checks, dict) or REQUIRED_VISUAL_CHECKS - set(checks):
        raise TrackerError("visual_checks 必须包含七个必需键")
    if not all(isinstance(key, str) and type(value) is bool for key, value in checks.items()):
        raise TrackerError("visual_checks 的所有值必须是严格布尔值")
    if status == "accepted":
        if rejection_reason is not None:
            raise TrackerError("accepted 产物的拒绝原因必须为 null")
        if not all(checks.get(key) is True for key in REQUIRED_VISUAL_CHECKS):
            raise TrackerError("通过验收的产物必须全部通过视觉检查")
    if status == "rejected":
        if not isinstance(rejection_reason, str) or not rejection_reason.strip():
            raise TrackerError("rejected 产物的拒绝原因必须是去空白后的非空字符串")
        if all(checks.get(key) is True for key in REQUIRED_VISUAL_CHECKS):
            raise TrackerError("rejected 产物的 visual_checks 至少一项为 false")
    if artifact_kind == "direct" and status == "accepted":
        if type(direct_index) is not int or direct_index not in {1, 2, 3}:
            raise TrackerError("有效直出版本的 direct_index 必须为 1、2 或 3")
    elif direct_index is not None:
        raise TrackerError("只有通过验收的直出版本可以填写 direct_index")


def _validate_parent(
    records: list[dict[str, Any]], parent_artifact_id: str | None, *,
    current_identity: dict[str, Any],
) -> dict[str, Any]:
    if not parent_artifact_id:
        raise TrackerError("修订产物必须提供父级产物编号")
    parent = next((item for item in records if item.get("artifact_id") == parent_artifact_id), None)
    if parent is None:
        raise TrackerError("修订产物的父级不存在")
    if not _is_valid_revision_parent(parent):
        raise TrackerError("修订产物的父级必须通过验收，或是仅文字检查失败的 rejected direct/revision")
    if not _same_artifact_group(parent, current_identity):
        raise TrackerError("修订产物的父级与当前任务、图号、渠道或审批范围不一致")
    return parent


def capture_artifact(
    *, snapshot_path: str | Path, source_dir: str | Path, explicit_source: str | Path | None,
    destination: str | Path, manifest_path: str | Path, task_id: str, provider: str,
    platform: str, product_name: str, image_id: str, image_type: str, attempt_no: int,
    direct_index: int | None, artifact_kind: str, prompt_id: str, prompt_path: str | Path,
    call_started_at: str, status: str, visual_checks: dict[str, bool] | None,
    inspection_session_id: str, inspection_checked_at: str, inspection_notes: str,
    rejection_reason: str | None, parent_artifact_id: str | None = None,
    supersedes_artifact_id: str | None = None, supersession_reason: str | None = None,
) -> dict[str, Any]:
    """复制一次渠道产物，并在清单成功追加后保留目标文件。"""
    _check_capture_inputs(
        artifact_kind=artifact_kind, status=status, direct_index=direct_index,
        visual_checks=visual_checks, rejection_reason=rejection_reason,
    )
    if not isinstance(prompt_id, str) or not prompt_id.strip():
        raise TrackerError("prompt_id 必须是去空白后的非空字符串")
    if not isinstance(inspection_session_id, str) or not inspection_session_id.strip():
        raise TrackerError("检查 Subagent 编号必须是非空字符串")
    if not isinstance(inspection_notes, str) or not inspection_notes.strip():
        raise TrackerError("检查结论必须是去空白后的非空字符串")
    if not all((task_id, provider, platform, product_name, image_id, image_type, prompt_id, call_started_at)):
        raise TrackerError("任务、渠道、产品、图号、提示词和调用时间不能为空")
    started_at = _parse_datetime(call_started_at, "渠道调用开始时间")
    captured_at = datetime.now(timezone.utc)
    inspected_at = _parse_datetime(inspection_checked_at, "检查时间")
    if started_at > captured_at:
        raise TrackerError("渠道调用开始时间不能晚于本次捕获时间")
    if inspected_at < started_at or inspected_at > captured_at:
        raise TrackerError("检查时间必须位于渠道调用开始时间与本次捕获时间之间")
    if type(attempt_no) is not int or attempt_no < 1:
        raise TrackerError("尝试号必须是大于 0 的整数")
    if supersedes_artifact_id and not supersession_reason:
        raise TrackerError("替换已有直出时必须填写替换原因")
    if supersession_reason and not supersedes_artifact_id:
        raise TrackerError("填写替换原因时必须提供被替换产物编号")
    if supersedes_artifact_id and (artifact_kind != "direct" or status != "accepted"):
        raise TrackerError("只有通过验收的 direct 可以替换已有直出")
    _validate_capture_filename(
        destination, product_name=product_name, image_type=image_type, image_id=image_id,
        attempt_no=attempt_no, direct_index=direct_index, artifact_kind=artifact_kind, status=status,
        supersedes_artifact_id=supersedes_artifact_id,
    )
    _validate_capture_directory(
        destination, manifest_path, provider=provider, task_id=task_id, image_id=image_id,
        artifact_kind=artifact_kind, status=status,
    )
    _validate_call_files_directory(
        snapshot_path, prompt_path, manifest_path, provider=provider, task_id=task_id, image_id=image_id,
    )

    approval_context = _load_approved_job(
        manifest_path, task_id=task_id, provider=provider, platform=platform,
        product_name=product_name, image_id=image_id, image_type=image_type, allow_calling=True,
    )
    if inspection_session_id == approval_context["session_id"]:
        raise TrackerError("检查 Subagent 必须与生成 Session 不同")
    if inspection_session_id == approval_context["main_session_id"]:
        raise TrackerError("检查 Subagent 必须与主 Session 不同，主 Session 不得代检")
    if (
        approval_context["calling_attempts"]
        and approval_context["calling_attempts"][0].get("attempt_no") != attempt_no
    ):
        raise TrackerError("上一渠道调用尚未归档，不能开始或捕获新的尝试")

    snapshot, snapshot_data = _load_snapshot(snapshot_path, source_dir)
    try:
        snapshot_sha256 = _sha256(snapshot)
    except OSError as error:
        raise TrackerError(f"调用前快照无法读取：{snapshot}") from error
    if started_at < _parse_datetime(
        snapshot_data.get("created_at"), "快照创建时间"
    ):
        raise TrackerError("渠道调用开始时间不能早于调用前快照")

    source, provenance_mode = resolve_source(snapshot_path, source_dir, explicit_source)
    prompt, prompt_sha256 = _read_prompt(prompt_path)
    if approval_context["calling_attempts"]:
        calling = approval_context["calling_attempts"][0]
        calling_matches = (
            calling.get("attempt_no") == attempt_no
            and calling.get("session_id") == approval_context["session_id"]
            and calling.get("input_reference_ids") == approval_context["reference_ids"]
            and calling.get("view_events") == approval_context["view_events"]
            and calling.get("prompt_id") == prompt_id
            and _absolute(str(calling.get("prompt_path", ""))) == prompt
            and calling.get("prompt_sha256") == prompt_sha256
            and _absolute(str(calling.get("snapshot_path", ""))) == snapshot
            and calling.get("snapshot_sha256") == snapshot_sha256
            and _parse_datetime(calling.get("call_started_at"), "calling 的 call_started_at")
            == _parse_datetime(call_started_at, "渠道调用开始时间")
        )
        if not calling_matches:
            raise TrackerError("当前 calling 调用记录与实际参数、提示词或快照不一致")
    width, height = _image_size(source)
    if status == "accepted" and _image_format(source) != "PNG":
        raise TrackerError("通过验收的 direct 或 revision 必须是 PNG 图片")
    if status == "accepted" and artifact_kind == "direct" and width != height:
        raise TrackerError("通过验收的直出图必须为正方形")
    target = _absolute(destination)
    if target.exists():
        raise TrackerError(f"目标文件已存在，拒绝覆盖：{target}")
    records = _load_manifest(manifest_path)
    _require_matching_immutable_identity(
        records,
        immutable_identity_sha256=approval_context["immutable_identity_sha256"],
    )
    if any(item.get("snapshot_path") and _absolute(item["snapshot_path"]) == snapshot for item in records):
        raise TrackerError("同一调用前快照已被使用，必须为每次渠道调用建立唯一快照")
    if any(item.get("target_path") and _absolute(item["target_path"]) == target for item in records):
        raise TrackerError(f"目标路径已在清单中登记，拒绝覆盖：{target}")
    current_identity = {
        "task_id": task_id, "image_id": image_id, "provider": provider, "platform": platform,
        "product_name": product_name, "image_type": image_type,
        "approval_scope_version": approval_context["scope_version"],
        "approval_scope_sha256": approval_context["scope_sha256"],
    }
    if any(
        _same_image_group(item, task_id, image_id) and not _same_base_artifact_group(item, current_identity)
        for item in records
    ):
        raise TrackerError("产物出现后不可变任务身份发生变化；必须建立新 task 并使用独立输出根目录和清单")
    prior_attempts = [
        item.get("attempt_no") for item in records
        if _same_base_artifact_group(item, current_identity) and item.get("artifact_kind") in {"direct", "revision"}
    ]
    active_job_attempts = approval_context["calling_attempts"]
    if active_job_attempts and (
        len(active_job_attempts) != 1 or active_job_attempts[0].get("attempt_no") != attempt_no
    ):
        raise TrackerError("上一渠道调用尚未归档，不能开始或捕获新的尝试")
    completed_job_attempts = [
        item.get("attempt_no")
        for item in approval_context["job_attempts"]
        if item.get("status") != "calling"
    ]
    numeric_attempts = [
        item for item in prior_attempts + completed_job_attempts if type(item) is int
    ]
    if numeric_attempts and attempt_no <= max(numeric_attempts):
        raise TrackerError(f"尝试号必须递增，下一次至少为 {max(numeric_attempts) + 1}")
    if artifact_kind == "revision" and not _has_complete_direct_set(records, current_identity):
        raise TrackerError("登记渠道内 revision 前必须先取得三个有效直出版本")
    parent = _validate_parent(
        records, parent_artifact_id, current_identity=current_identity,
    ) if artifact_kind == "revision" else None

    inactive_ids = _inactive_artifact_ids(records)
    superseded = None
    if supersedes_artifact_id:
        superseded = next((item for item in records if item.get("artifact_id") == supersedes_artifact_id), None)
        if (
            superseded is None
            or supersedes_artifact_id in inactive_ids
            or superseded.get("artifact_kind") != "direct"
            or superseded.get("status") != "accepted"
            or superseded.get("direct_index") != direct_index
            or not _same_base_artifact_group(superseded, current_identity)
        ):
            raise TrackerError("被替换产物必须是同一图号和直出序号下当前有效的 accepted direct")
        old_scope_version = superseded.get("approval_scope_version")
        old_scope_sha256 = superseded.get("approval_scope_sha256")
        scope_is_current = (
            old_scope_version == approval_context["scope_version"]
            and old_scope_sha256 == approval_context["scope_sha256"]
        )
        scope_is_older = (
            type(old_scope_version) is int
            and old_scope_version < approval_context["scope_version"]
        )
        if not scope_is_current and not scope_is_older:
            raise TrackerError("被替换直出的审批范围不是当前范围或更早版本")

    try:
        source_sha256_before = _sha256(source)
    except OSError as error:
        raise TrackerError(f"来源图片无法读取：{source}") from error
    if status == "accepted" and artifact_kind == "direct":
        accepted_directs = [
            item for item in records
            if _same_artifact_group(item, current_identity)
            and item.get("artifact_kind") == "direct" and item.get("status") == "accepted"
            and item.get("artifact_id") not in inactive_ids
        ]
        existing_index = [item for item in accepted_directs if item.get("direct_index") == direct_index]
        if existing_index and (superseded is None or existing_index != [superseded]):
            raise TrackerError(f"direct{direct_index:02d} 已有有效直出版本")
        all_accepted_directs = [
            item for item in records
            if _same_base_artifact_group(item, current_identity)
            and item.get("artifact_kind") == "direct" and item.get("status") == "accepted"
        ]
        if any(item.get("target_sha256") == source_sha256_before for item in all_accepted_directs):
            raise TrackerError("图片哈希重复，不能作为新的有效直出版本")
        if any(item.get("prompt_sha256") == prompt_sha256 for item in all_accepted_directs):
            raise TrackerError("提示词哈希重复，不能作为新的有效直出版本")

    try:
        _copy_exclusive(source, target)
    except FileExistsError as error:
        raise TrackerError(f"目标文件已存在，拒绝覆盖：{target}") from error
    except OSError as error:
        raise TrackerError(f"无法保存产物：{target}") from error
    manifest = _absolute(manifest_path)
    manifest_existed = manifest.exists()
    manifest_size = manifest.stat().st_size if manifest_existed else 0
    try:
        source_sha256_after = _sha256(source)
        target_sha256 = _sha256(target)
        if source_sha256_before != source_sha256_after or target_sha256 != source_sha256_before:
            raise TrackerError("来源图片在复制期间发生变化，已撤销本次产物")
        if _sha256(prompt) != prompt_sha256:
            raise TrackerError("提示词文件在捕获期间发生变化，已撤销本次产物")
        if _sha256(snapshot) != snapshot_sha256:
            raise TrackerError("调用前快照在捕获期间发生变化，已撤销本次产物")
        record = {
            "schema_version": ARTIFACT_SCHEMA_VERSION,
            "artifact_id": str(uuid.uuid4()),
            "task_id": task_id,
            "provider": provider,
            "platform": platform,
            "product_name": product_name,
            "image_id": image_id,
            "image_type": image_type,
            "immutable_identity_sha256": approval_context["immutable_identity_sha256"],
            "approval_scope_version": approval_context["scope_version"],
            "approval_scope_sha256": approval_context["scope_sha256"],
            "session_id": approval_context["session_id"],
            "attempt_no": attempt_no,
            "direct_index": direct_index,
            "artifact_kind": artifact_kind,
            "prompt_id": prompt_id,
            "prompt_path": str(prompt),
            "prompt_sha256": prompt_sha256,
            "call_started_at": call_started_at,
            "captured_at": captured_at.isoformat(),
            "provenance_mode": provenance_mode,
            "source_path": str(source),
            "source_sha256": source_sha256_before,
            "target_path": str(target),
            "target_sha256": target_sha256,
            "width": width,
            "height": height,
            "status": status,
            "visual_checks": dict(visual_checks or {}),
            "inspection_session_id": inspection_session_id,
            "inspection_checked_at": inspected_at.isoformat(),
            "inspection_notes": inspection_notes,
            "rejection_reason": rejection_reason,
            "derived_from_artifact_id": parent_artifact_id if parent else None,
            "snapshot_path": str(snapshot),
            "snapshot_sha256": snapshot_sha256,
            "supersedes_artifact_id": supersedes_artifact_id,
            "supersession_reason": supersession_reason,
        }
        _append_manifest(manifest_path, record)
    except Exception as error:
        _restore_manifest(manifest, manifest_existed, manifest_size)
        try:
            target.unlink(missing_ok=True)
        except OSError:
            pass
        if isinstance(error, OSError):
            raise TrackerError("捕获产物期间文件发生变化或无法读取，已撤销本次产物") from error
        raise
    return record


def _verify_hash_field(record: dict[str, Any], path_key: str, hash_key: str, errors: list[str]) -> None:
    identifier = record.get("artifact_id", "未知产物")
    path_text = record.get(path_key)
    expected = record.get(hash_key)
    if not isinstance(path_text, str) or not path_text:
        errors.append(f"产物 {identifier} 缺少必填字段 {path_key}")
        return
    if not isinstance(expected, str) or re.fullmatch(r"[0-9a-f]{64}", expected) is None:
        errors.append(f"产物 {identifier} 的 {hash_key} 必须是 64 位小写 SHA256")
        return
    path = Path(path_text)
    if not path.is_file():
        errors.append(f"产物 {identifier} 的文件不存在：{path}")
        return
    try:
        actual = _sha256(path)
    except OSError:
        errors.append(f"产物 {identifier} 的文件无法读取：{path}")
        return
    if actual != expected:
        errors.append(f"产物 {identifier} 的 {path_key} 哈希不匹配")


def _verify_inactive_file_readable(record: dict[str, Any], path_key: str, errors: list[str]) -> None:
    identifier = record.get("artifact_id", "未知产物")
    path_text = record.get(path_key)
    if not isinstance(path_text, str) or not path_text:
        errors.append(f"inactive 产物 {identifier} 缺少必填字段 {path_key}")
        return
    path = Path(path_text)
    if not path.is_file():
        errors.append(f"inactive 产物 {identifier} 的文件不存在：{path}")
        return
    try:
        _image_size(path)
    except TrackerError:
        errors.append(f"inactive 产物 {identifier} 的文件无法读取：{path}")


def _verify_record_semantics(
    record: dict[str, Any], approval_context: dict[str, Any] | None, errors: list[str],
) -> None:
    identifier = record.get("artifact_id", "未知产物")
    for field in (
        "task_id", "provider", "platform", "product_name", "image_id", "image_type",
        "session_id", "prompt_id", "prompt_path", "source_path", "target_path", "snapshot_path",
    ):
        if not isinstance(record.get(field), str) or not record[field].strip():
            errors.append(f"产物 {identifier} 的身份或提示词字段不能为空：{field}")
    for field in ("prompt_path", "source_path", "target_path", "snapshot_path"):
        value = record.get(field)
        if isinstance(value, str) and value and not Path(value).is_absolute():
            errors.append(f"产物 {identifier} 的 {field} 必须是绝对路径")
    if type(record.get("attempt_no")) is not int or record.get("attempt_no") < 1:
        errors.append(f"产物 {identifier} 的 attempt_no 必须是正整数")
    if (
        type(record.get("width")) is not int or record.get("width") < 1
        or type(record.get("height")) is not int or record.get("height") < 1
    ):
        errors.append(f"产物 {identifier} 的宽高必须是正整数")
    for field in ("prompt_sha256", "source_sha256", "target_sha256", "snapshot_sha256"):
        value = record.get(field)
        if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
            errors.append(f"产物 {identifier} 的 {field} 必须是 64 位小写 SHA256")
    immutable_identity = record.get("immutable_identity_sha256")
    if not isinstance(immutable_identity, str) or re.fullmatch(r"[0-9a-f]{64}", immutable_identity) is None:
        errors.append(f"产物 {identifier} 的 immutable_identity_sha256 必须是 64 位小写 SHA256")
    started = captured = None
    try:
        started = _parse_datetime(record.get("call_started_at"), "渠道调用开始时间")
    except TrackerError as error:
        errors.append(f"产物 {identifier} 的时间无效：{error}")
    try:
        captured = _parse_datetime(record.get("captured_at"), "捕获时间")
    except TrackerError as error:
        errors.append(f"产物 {identifier} 的时间无效：{error}")
    if started is not None and captured is not None and captured < started:
        errors.append(f"产物 {identifier} 的捕获时间不能早于调用时间")
    if record.get("artifact_kind") in {"direct", "revision"}:
        for field in ("inspection_session_id", "inspection_checked_at", "inspection_notes"):
            if not isinstance(record.get(field), str) or not record[field].strip():
                errors.append(f"产物 {identifier} 的独立检查字段不能为空：{field}")
        if record.get("inspection_session_id") == record.get("session_id"):
            errors.append(f"产物 {identifier} 的检查 Subagent 必须与生成 Session 不同")
        if (
            approval_context is not None
            and record.get("inspection_session_id") == approval_context.get("main_session_id")
        ):
            errors.append(f"产物 {identifier} 的检查 Subagent 必须与主 Session 不同")
        try:
            inspection_time = _parse_datetime(record.get("inspection_checked_at"), "检查时间")
            if started is not None and inspection_time < started:
                errors.append(f"产物 {identifier} 的检查时间不能早于调用时间")
            if captured is not None and inspection_time > captured:
                errors.append(f"产物 {identifier} 的检查时间不能晚于捕获时间")
        except TrackerError as error:
            errors.append(f"产物 {identifier} 的检查时间无效：{error}")
    elif record.get("artifact_kind") == "final":
        for field in ("inspection_session_id", "inspection_checked_at", "inspection_notes"):
            if record.get(field) is not None:
                errors.append(f"最终图 {identifier} 的 {field} 必须为空；独立终检只登记在任务 JSON")
    checks = record.get("visual_checks")
    if not isinstance(checks, dict) or not all(
        isinstance(key, str) and type(value) is bool for key, value in checks.items()
    ) or REQUIRED_VISUAL_CHECKS - set(checks):
        errors.append(f"产物 {identifier} 的 visual_checks 必须是完整布尔字典")
    status = record.get("status")
    kind = record.get("artifact_kind")
    if status == "accepted" and kind == "direct" and (
        type(record.get("direct_index")) is not int or record.get("direct_index") not in {1, 2, 3}
    ):
        errors.append(f"有效直出 {identifier} 的 direct_index 必须是整数 1、2 或 3")
    rejection_reason = record.get("rejection_reason")
    if status == "accepted" and kind in {"direct", "revision"} and rejection_reason is not None:
        errors.append(f"通过验收的产物 {identifier} 的拒绝原因必须为 null")
    if status == "accepted" and isinstance(checks, dict) and not all(
        checks.get(key) is True for key in REQUIRED_VISUAL_CHECKS
    ):
        errors.append(f"通过验收的产物 {identifier} 的 visual_checks 与 accepted 状态不相符")
    if status == "rejected":
        if not isinstance(rejection_reason, str) or not rejection_reason.strip():
            errors.append(f"作废产物 {identifier} 的拒绝原因必须是非空字符串")
        if isinstance(checks, dict) and all(checks.get(key) is True for key in REQUIRED_VISUAL_CHECKS):
            errors.append(f"作废产物 {identifier} 的 visual_checks 与 rejected 状态不相符")
    if (
        approval_context is not None
        and _record_matches_approval(record, approval_context)
        and record.get("session_id") != approval_context.get("session_id")
    ):
        errors.append(f"产物 {identifier} 的 session_id 与当前审批上下文不一致")
    if (
        approval_context is not None
        and record.get("immutable_identity_sha256") != approval_context.get("immutable_identity_sha256")
    ):
        errors.append(
            f"产物 {identifier} 与当前 job 的不可变任务身份不一致；必须建立新 task 并使用独立输出根目录和清单"
        )


ATTEMPT_RECORD_FIELDS = (
    "attempt_no", "approval_scope_version", "approval_scope_sha256", "session_id",
    "prompt_id", "prompt_path", "prompt_sha256", "snapshot_path", "snapshot_sha256",
    "call_started_at", "artifact_kind", "direct_index", "rejection_reason",
    "provenance_mode", "source_path", "source_sha256", "target_path", "target_sha256",
    "width", "height", "inspection_session_id", "inspection_checked_at", "inspection_notes",
)


def _verify_execution_reconciliation(
    context: dict[str, Any], records: list[dict[str, Any]], errors: list[str],
) -> None:
    image = context["image"]
    image_id = image.get("image_id")
    execution = context["execution"]
    artifact_records = [
        item for item in records
        if item.get("artifact_kind") in {"direct", "revision"}
        and item.get("task_id") == context["job"].get("task_id")
        and item.get("image_id") == image_id
        and item.get("provider") == context["job"].get("provider")
        and item.get("platform") == context["job"].get("platform")
        and item.get("product_name") == context["job"].get("product_name")
        and item.get("image_type") == image.get("image_type")
    ]
    if artifact_records and execution.get("status") == "planned":
        errors.append(f"图号 {image_id} 已有产物，execution.status 不能仍为 planned")
    attempts = context["job_attempts"]
    for attempt in attempts:
        if attempt.get("status") not in {"accepted", "rejected"}:
            continue
        artifact_id = attempt.get("artifact_id")
        matches = [item for item in artifact_records if item.get("artifact_id") == artifact_id]
        if len(matches) != 1:
            errors.append(f"图号 {image_id} 的 attempt {attempt.get('attempt_no')} 未与唯一清单产物对账")
            continue
        record = matches[0]
        if attempt.get("status") != record.get("status"):
            errors.append(f"图号 {image_id} 的 attempt {attempt.get('attempt_no')} 状态与清单不一致")
        if (
            attempt.get("status") == "rejected"
            and attempt.get("failure_reason") != record.get("rejection_reason")
        ):
            errors.append(f"图号 {image_id} 的 attempt {attempt.get('attempt_no')} 失败原因与清单不一致")
        for field in ATTEMPT_RECORD_FIELDS:
            if attempt.get(field) != record.get(field):
                errors.append(
                    f"图号 {image_id} 的 attempt {attempt.get('attempt_no')} 字段 {field} 与清单不一致"
                )
        if _record_matches_approval(record, context):
            if attempt.get("session_id") != context.get("session_id"):
                errors.append(f"图号 {image_id} 的当前范围 attempt 未绑定当前 session_id")
            if attempt.get("input_reference_ids") != context.get("reference_ids"):
                errors.append(f"图号 {image_id} 的当前范围 attempt 未绑定当前 reference_ids")
            if attempt.get("view_events") != context.get("view_events"):
                errors.append(f"图号 {image_id} 的当前范围 attempt 未保存完整当前 view_events")
    for record in artifact_records:
        matches = [
            attempt for attempt in attempts
            if attempt.get("status") in {"accepted", "rejected"}
            and attempt.get("artifact_id") == record.get("artifact_id")
        ]
        if len(matches) != 1:
            errors.append(f"清单产物 {record.get('artifact_id', '未知产物')} 未反向找到唯一 attempt")

    final_records = [
        item for item in records
        if item.get("artifact_kind") == "final"
        and item.get("task_id") == context["job"].get("task_id")
        and item.get("image_id") == image_id
        and item.get("provider") == context["job"].get("provider")
        and item.get("platform") == context["job"].get("platform")
        and item.get("product_name") == context["job"].get("product_name")
        and item.get("image_type") == image.get("image_type")
    ]
    for inspection in context.get("final_inspections", []):
        matches = [
            item for item in final_records
            if item.get("artifact_id") == inspection.get("artifact_id")
        ]
        if len(matches) != 1:
            errors.append(
                f"图号 {image_id} 的最终图检查未与唯一清单 final 产物对账："
                f"{inspection.get('artifact_id', '未知产物')}"
            )


def _verify_final_inspection(
    record: dict[str, Any], context: dict[str, Any] | None, errors: list[str],
) -> bool:
    """验证当前 final 是否由独立检查 Subagent 完成终检。"""
    identifier = record.get("artifact_id", "未知产物")
    if context is None:
        errors.append(f"最终图 {identifier} 缺少可验证的独立检查 Subagent 上下文")
        return False
    inspections = context.get("final_inspections")
    if not isinstance(inspections, list):
        errors.append(f"最终图 {identifier} 缺少独立检查 Subagent 记录")
        return False
    matches = [item for item in inspections if item.get("artifact_id") == identifier]
    if len(matches) != 1:
        errors.append(f"最终图 {identifier} 必须且只能有一条独立检查 Subagent 记录")
        return False

    inspection = matches[0]
    valid = True
    inspector = inspection.get("inspection_session_id")
    if not isinstance(inspector, str) or not inspector.strip():
        errors.append(f"最终图 {identifier} 的独立检查 Subagent 编号不能为空")
        valid = False
    elif inspector == record.get("session_id"):
        errors.append(f"最终图 {identifier} 的检查 Subagent 必须与生成 Session 不同")
        valid = False
    elif inspector == context.get("main_session_id"):
        errors.append(f"最终图 {identifier} 的检查 Subagent 必须与主 Session 不同")
        valid = False
    notes = inspection.get("notes")
    if not isinstance(notes, str) or not notes.strip():
        errors.append(f"最终图 {identifier} 的独立检查结论不能为空")
        valid = False
    try:
        checked_at = _parse_datetime(inspection.get("checked_at"), "最终图检查时间")
        captured_at = _parse_datetime(record.get("captured_at"), "最终图捕获时间")
        if checked_at < captured_at:
            errors.append(f"最终图 {identifier} 的独立检查时间不能早于最终图生成时间")
            valid = False
    except TrackerError as error:
        errors.append(f"最终图 {identifier} 的独立检查时间无效：{error}")
        valid = False
    checks = inspection.get("visual_checks")
    if (
        not isinstance(checks, dict)
        or set(checks) != REQUIRED_VISUAL_CHECKS
        or not all(type(value) is bool for value in checks.values())
    ):
        errors.append(f"最终图 {identifier} 的独立检查必须包含七项严格布尔 visual_checks")
        valid = False
    elif not all(checks.get(key) is True for key in REQUIRED_VISUAL_CHECKS):
        errors.append(f"最终图 {identifier} 未通过独立检查 Subagent 的全部视觉检查")
        valid = False
    return valid


def _record_group(record: dict[str, Any]) -> tuple[str, ...]:
    return tuple(str(record.get(field, "")) for field in GROUP_FIELDS)


def _record_base_group(record: dict[str, Any]) -> tuple[str, ...]:
    return tuple(str(record.get(field, "")) for field in BASE_GROUP_FIELDS)


def _record_file_matches(record: dict[str, Any], path_key: str, hash_key: str) -> bool:
    path_text = record.get(path_key)
    expected = record.get(hash_key)
    if not isinstance(path_text, str) or not isinstance(expected, str) or len(expected) != 64:
        return False
    path = Path(path_text)
    try:
        return path.is_file() and _sha256(path) == expected
    except OSError:
        return False


def _has_complete_direct_set(records: list[dict[str, Any]], group_record: dict[str, Any]) -> bool:
    inactive_ids = _inactive_artifact_ids(records)
    accepted = [
        item for item in records
        if _same_artifact_group(item, group_record)
        and item.get("artifact_kind") == "direct" and item.get("status") == "accepted"
        and item.get("artifact_id") not in inactive_ids
    ]
    indexes = [item.get("direct_index") for item in accepted]
    if len(accepted) != 3 or any(type(item) is not int for item in indexes) or sorted(indexes) != [1, 2, 3]:
        return False
    image_hashes = [item.get("target_sha256") for item in accepted]
    prompt_hashes = [item.get("prompt_sha256") for item in accepted]
    if (
        any(not isinstance(item, str) for item in image_hashes + prompt_hashes)
        or len(set(image_hashes)) != 3 or len(set(prompt_hashes)) != 3
    ):
        return False
    for item in accepted:
        if not _all_visual_checks_pass(item) or item.get("width") != item.get("height"):
            return False
        if item.get("source_sha256") != item.get("target_sha256"):
            return False
        if not all(
            _record_file_matches(item, path_key, hash_key)
            for path_key, hash_key in (
                ("prompt_path", "prompt_sha256"),
                ("source_path", "source_sha256"),
                ("target_path", "target_sha256"),
            )
        ):
            return False
        try:
            target = Path(item["target_path"])
            if _image_format(target) != "PNG" or _image_size(target) != (item.get("width"), item.get("height")):
                return False
            _validate_capture_filename(
                target,
                product_name=str(item.get("product_name", "")),
                image_type=str(item.get("image_type", "")),
                image_id=str(item.get("image_id", "")),
                attempt_no=int(item.get("attempt_no", 0)),
                direct_index=item.get("direct_index"),
                artifact_kind="direct",
                status="accepted",
                supersedes_artifact_id=item.get("supersedes_artifact_id"),
            )
        except (TrackerError, TypeError, ValueError):
            return False
    return True


def verify_manifest(manifest_path: str | Path) -> dict[str, Any]:
    """验证字段、文件、三版直出、最终图和完整派生链。"""
    try:
        records = _load_manifest(manifest_path)
    except TrackerError as error:
        return {"ok": False, "errors": [str(error)], "records": 0}
    errors: list[str] = []
    if not records:
        errors.append("清单没有任何产物记录")
    by_id: dict[str, dict[str, Any]] = {}
    for record in records:
        identifier = record.get("artifact_id", "未知产物")
        if not isinstance(identifier, str) or not identifier:
            errors.append("发现缺少 artifact_id 的清单记录")
        elif identifier in by_id:
            errors.append(f"artifact_id 重复：{identifier}")
        else:
            by_id[identifier] = record

    valid_superseded_ids: set[str] = set()
    for record in records:
        replacement_id = record.get("artifact_id", "未知产物")
        superseded_id = record.get("supersedes_artifact_id")
        if superseded_id is None:
            if record.get("supersession_reason") is not None:
                errors.append(f"产物 {replacement_id} 有替换原因但缺少被替换产物编号")
            continue
        target = by_id.get(superseded_id) if isinstance(superseded_id, str) else None
        valid = (
            target is not None
            and record.get("artifact_kind") == "direct"
            and record.get("status") == "accepted"
            and bool(record.get("supersession_reason"))
            and target.get("artifact_kind") == "direct"
            and target.get("status") == "accepted"
            and target.get("direct_index") == record.get("direct_index")
            and _same_base_artifact_group(target, record)
            and (
                (
                    target.get("approval_scope_version") == record.get("approval_scope_version")
                    and target.get("approval_scope_sha256") == record.get("approval_scope_sha256")
                )
                or (
                    type(target.get("approval_scope_version")) is int
                    and type(record.get("approval_scope_version")) is int
                    and target.get("approval_scope_version") < record.get("approval_scope_version")
                )
            )
            and superseded_id not in valid_superseded_ids
        )
        if not valid:
            errors.append(f"产物 {replacement_id} 的直出替换关系无效")
        else:
            valid_superseded_ids.add(superseded_id)

    inactive_ids = set(valid_superseded_ids)
    changed = True
    while changed:
        changed = False
        for record in records:
            identifier = record.get("artifact_id")
            if (
                isinstance(identifier, str)
                and record.get("derived_from_artifact_id") in inactive_ids
                and identifier not in inactive_ids
            ):
                inactive_ids.add(identifier)
                changed = True

    checked_task_identities: set[tuple[str, str]] = set()
    for record in records:
        task_id = str(record.get("task_id", ""))
        provider = str(record.get("provider", ""))
        identity_key = (task_id, provider)
        if identity_key in checked_task_identities:
            continue
        checked_task_identities.add(identity_key)
        try:
            current_identity_sha256 = _load_current_immutable_identity(
                manifest_path, task_id=task_id, provider=provider,
            )
            _require_matching_immutable_identity(
                records,
                immutable_identity_sha256=current_identity_sha256,
            )
        except TrackerError as error:
            errors.append(f"任务 {task_id} 的不可变任务身份校验失败：{error}")

    groups: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    task_image_groups: dict[tuple[str, str], set[tuple[str, ...]]] = {}
    approval_contexts: dict[tuple[str, ...], dict[str, Any] | None] = {}
    current_required_groups: set[tuple[str, ...]] = set()
    processed_tasks: set[tuple[str, str, str, str]] = set()
    for record in records:
        base_group = _record_base_group(record)
        task_identity = (
            str(record.get("task_id", "")), str(record.get("provider", "")),
            str(record.get("platform", "")), str(record.get("product_name", "")),
        )
        if task_identity in processed_tasks:
            continue
        processed_tasks.add(task_identity)
        try:
            context = _load_approved_job(
                manifest_path,
                task_id=str(record.get("task_id", "")),
                provider=str(record.get("provider", "")),
                platform=str(record.get("platform", "")),
                product_name=str(record.get("product_name", "")),
                image_id=str(record.get("image_id", "")),
                image_type=str(record.get("image_type", "")),
            )
        except TrackerError as error:
            approval_contexts[base_group] = None
            errors.append(f"任务 {record.get('task_id', '')} 图号 {record.get('image_id', '')} 的审批校验失败：{error}")
        else:
            for image in context["job"]["images"]:
                required_base = (
                    task_identity[0], str(image.get("image_id", "")), task_identity[1],
                    task_identity[2], task_identity[3], str(image.get("image_type", "")),
                )
                try:
                    image_context = _load_approved_job(
                        manifest_path,
                        task_id=task_identity[0], provider=task_identity[1],
                        platform=task_identity[2], product_name=task_identity[3],
                        image_id=str(image.get("image_id", "")),
                        image_type=str(image.get("image_type", "")),
                    )
                except TrackerError as error:
                    approval_contexts[required_base] = None
                    errors.append(
                        f"任务 {task_identity[0]} 图号 {image.get('image_id', '')} 的审批校验失败：{error}"
                    )
                else:
                    approval_contexts[required_base] = image_context
                    current_required_groups.add(required_base + (
                        str(image_context["scope_version"]), str(image_context["scope_sha256"]),
                    ))
    used_snapshots: set[str] = set()
    last_attempt_by_group: dict[tuple[str, str, str, str, str, str], int] = {}
    for record in records:
        identifier = record.get("artifact_id", "未知产物")
        missing = sorted(field for field in REQUIRED_RECORD_FIELDS if field not in record)
        if missing:
            errors.append(f"产物 {identifier} 缺少必填字段：{', '.join(missing)}")
        if record.get("schema_version") != ARTIFACT_SCHEMA_VERSION:
            errors.append(f"产物 {identifier} 的 schema_version 无效")
        kind = record.get("artifact_kind")
        status = record.get("status")
        provenance = record.get("provenance_mode")
        if kind not in VALID_KINDS:
            errors.append(f"产物 {identifier} 的未知产物类型：{kind}")
        if status not in VALID_STATUSES:
            errors.append(f"产物 {identifier} 的未知验收状态：{status}")
        if provenance not in VALID_PROVENANCE:
            errors.append(f"产物 {identifier} 的未知来源模式：{provenance}")
        if status == "accepted" and kind in {"direct", "revision"}:
            checks = record.get("visual_checks") or {}
            if REQUIRED_VISUAL_CHECKS - set(checks) or not all(checks.get(key) is True for key in REQUIRED_VISUAL_CHECKS):
                errors.append(f"通过验收的产物 {identifier} 的视觉检查不完整")
        if status == "rejected" and not record.get("rejection_reason"):
            errors.append(f"作废产物 {identifier} 缺少拒绝原因")

        if kind == "direct":
            if provenance not in {"tool_return", "snapshot_diff"}:
                errors.append(f"直出 {identifier} 的来源模式违反状态机")
            if record.get("derived_from_artifact_id") is not None:
                errors.append(f"直出 {identifier} 的状态机不允许派生父级")
            if status == "accepted" and (
                type(record.get("direct_index")) is not int
                or record.get("direct_index") not in {1, 2, 3}
            ):
                errors.append(f"有效直出 {identifier} 的 direct_index 必须是整数 1、2 或 3")
            if status == "rejected" and record.get("direct_index") is not None:
                errors.append(f"作废直出 {identifier} 的状态机要求 direct_index 为空")
        elif kind == "revision":
            if provenance not in {"tool_return", "snapshot_diff"}:
                errors.append(f"修订产物 {identifier} 的来源模式违反状态机")
            if record.get("direct_index") is not None:
                errors.append(f"修订产物 {identifier} 的状态机要求 direct_index 为空")
            if not record.get("derived_from_artifact_id"):
                errors.append(f"修订产物 {identifier} 的状态机缺少父级")
        elif kind == "final":
            if provenance != "derivation":
                errors.append(f"最终图 {identifier} 的来源模式必须是 derivation")
            if record.get("direct_index") is not None or status != "accepted" or record.get("rejection_reason") is not None:
                errors.append(f"最终图 {identifier} 的状态机字段无效")
            if record.get("supersedes_artifact_id") is not None:
                errors.append(f"最终图 {identifier} 不能替换 direct")

        group = _record_group(record)
        base_group = _record_base_group(record)
        groups.setdefault(group, []).append(record)
        task_image_groups.setdefault((base_group[0], base_group[1]), set()).add(base_group)
        approval_context = approval_contexts.get(base_group)
        _verify_record_semantics(record, approval_context, errors)
        if (
            approval_context is not None
            and not _record_matches_approval(record, approval_context)
            and identifier not in inactive_ids
            and status == "accepted"
            and kind in {"direct", "revision", "final"}
        ):
            errors.append(f"产物 {identifier} 的审批范围已失效，必须由当前范围产物替代")
        if kind in {"direct", "revision"}:
            attempt = record.get("attempt_no")
            previous = last_attempt_by_group.get(group, 0)
            if type(attempt) is not int or attempt <= previous:
                errors.append(f"产物 {identifier} 的尝试号未按调用顺序递增")
            else:
                last_attempt_by_group[group] = attempt
            snapshot_text = record.get("snapshot_path")
            if isinstance(snapshot_text, str):
                normalized_snapshot = str(_absolute(snapshot_text))
                if normalized_snapshot in used_snapshots:
                    errors.append(f"产物 {identifier} 重复使用调用前快照")
                used_snapshots.add(normalized_snapshot)

        _verify_hash_field(record, "prompt_path", "prompt_sha256", errors)
        _verify_hash_field(record, "snapshot_path", "snapshot_sha256", errors)
        is_inactive = isinstance(identifier, str) and identifier in inactive_ids
        if not is_inactive:
            _verify_hash_field(record, "source_path", "source_sha256", errors)
            _verify_hash_field(record, "target_path", "target_sha256", errors)
        else:
            _verify_inactive_file_readable(record, "source_path", errors)
            _verify_inactive_file_readable(record, "target_path", errors)
        if kind in {"direct", "revision"} and record.get("source_sha256") != record.get("target_sha256"):
            errors.append(f"产物 {identifier} 的来源与目标哈希不一致")
        target_text = record.get("target_path")
        if not is_inactive and isinstance(target_text, str) and Path(target_text).is_file():
            try:
                dimensions = _image_size(target_text)
                if dimensions != (record.get("width"), record.get("height")):
                    errors.append(f"产物 {identifier} 的图片尺寸不匹配")
                if status == "accepted" and _image_format(target_text) != "PNG":
                    errors.append(f"通过验收的产物 {identifier} 不是 PNG 图片")
            except TrackerError as error:
                errors.append(str(error))
        try:
            if kind in {"direct", "revision"}:
                _validate_capture_filename(
                    str(record.get("target_path", "")),
                    product_name=str(record.get("product_name", "")),
                    image_type=str(record.get("image_type", "")),
                    image_id=str(record.get("image_id", "")),
                    attempt_no=int(record.get("attempt_no", 0)),
                    direct_index=record.get("direct_index"),
                    artifact_kind=str(kind),
                    status=str(status),
                    supersedes_artifact_id=record.get("supersedes_artifact_id"),
                )
                _validate_capture_directory(
                    str(record.get("target_path", "")), manifest_path,
                    provider=str(record.get("provider", "")), task_id=str(record.get("task_id", "")),
                    image_id=str(record.get("image_id", "")), artifact_kind=str(kind), status=str(status),
                )
                _validate_call_files_directory(
                    str(record.get("snapshot_path", "")), str(record.get("prompt_path", "")), manifest_path,
                    provider=str(record.get("provider", "")), task_id=str(record.get("task_id", "")),
                    image_id=str(record.get("image_id", "")),
                )
            elif kind == "final":
                _validate_final_filename(str(record.get("target_path", "")), record)
                _validate_final_directory(
                    str(record.get("target_path", "")), manifest_path, str(record.get("provider", ""))
                )
        except (TrackerError, TypeError, ValueError) as error:
            errors.append(f"产物 {identifier} 的命名或目录校验失败：{error}")

    for task_image, identities in task_image_groups.items():
        if len(identities) > 1:
            errors.append(
                f"任务 {task_image[0]} 图号 {task_image[1]} 的不可变任务身份发生变化，必须建立新 task"
            )

    for context in approval_contexts.values():
        if context is not None:
            _verify_execution_reconciliation(context, records, errors)

    for record in records:
        identifier = record.get("artifact_id")
        seen: set[str] = set()
        current = record
        while current.get("artifact_kind") in {"revision", "final"}:
            current_id = current.get("artifact_id")
            if not isinstance(current_id, str) or current_id in seen:
                errors.append(f"产物 {identifier} 的派生血缘存在循环")
                break
            seen.add(current_id)
            parent_id = current.get("derived_from_artifact_id")
            if not isinstance(parent_id, str) or parent_id not in by_id:
                break
            current = by_id[parent_id]

    final_counts: dict[tuple[str, ...], int] = {}
    for record in records:
        if record.get("artifact_kind") != "final":
            continue
        base_group = _record_base_group(record)
        expected_version = final_counts.get(base_group, 0) + 1
        final_counts[base_group] = expected_version
        try:
            base_name = _artifact_base_name(
                str(record.get("product_name", "")),
                str(record.get("image_type", "")),
                str(record.get("image_id", "")),
            )
            expected_name = f"{base_name}_v{expected_version:02d}.png"
            actual_name = _absolute(str(record.get("target_path", ""))).name
            if actual_name != expected_name:
                errors.append(
                    f"最终版本必须按清单历史连续递增：产物 {record.get('artifact_id', '未知产物')} 应为 {expected_name}"
                )
        except TrackerError as error:
            errors.append(f"最终版本命名无法校验：{error}")

    legal_finals: dict[tuple[str, ...], list[str]] = {}
    for record in records:
        kind = record.get("artifact_kind")
        identifier = record.get("artifact_id", "未知产物")
        if kind == "direct" and record.get("status") == "accepted" and identifier not in inactive_ids:
            if record.get("width") != record.get("height"):
                errors.append(f"有效直出 {identifier} 不是正方形")
        if kind not in {"revision", "final"}:
            continue
        parent_id = record.get("derived_from_artifact_id")
        parent = by_id.get(parent_id) if isinstance(parent_id, str) else None
        if parent is None:
            errors.append(f"产物 {identifier} 的派生关系缺少有效父级")
            continue
        same_lineage = _same_artifact_group(record, parent)
        same_source = record.get("source_path") == parent.get("target_path") and record.get("source_sha256") == parent.get("target_sha256")
        if not same_lineage:
            errors.append(f"产物 {identifier} 的派生关系字段不一致")
        if kind == "revision" and identifier not in inactive_ids and (
            parent_id in inactive_ids or not _is_valid_revision_parent(parent)
        ):
            errors.append(f"修订产物 {identifier} 的派生关系父级不可用")
        if kind == "final":
            if identifier in inactive_ids:
                continue
            inspection_ok = _verify_final_inspection(
                record, approval_contexts.get(_record_base_group(record)), errors,
            )
            if (
                parent_id in inactive_ids or parent.get("status") != "accepted"
                or parent.get("artifact_kind") not in {"direct", "revision"}
            ):
                errors.append(f"最终图 {identifier} 的派生关系父级不可用")
            if not same_source:
                errors.append(f"最终图 {identifier} 的派生关系来源哈希不一致")
            if record.get("status") != "accepted" or (record.get("width"), record.get("height")) != (1000, 1000):
                errors.append(f"最终图 {identifier} 必须为通过验收的 1000x1000 图片")
            elif (
                same_lineage and same_source and parent_id not in inactive_ids
                and parent.get("status") == "accepted" and parent.get("artifact_kind") in {"direct", "revision"}
                and inspection_ok
            ):
                legal_finals.setdefault(_record_group(record), []).append(str(identifier))

    for group in sorted(current_required_groups):
        group_records = groups.get(group, [])
        task_id, image_id = group[0], group[1]
        accepted = [
            item for item in group_records
            if item.get("artifact_kind") == "direct" and item.get("status") == "accepted"
            and item.get("artifact_id") not in inactive_ids
        ]
        indexes = [item.get("direct_index") for item in accepted]
        for index in (1, 2, 3):
            if indexes.count(index) != 1:
                errors.append(f"任务 {task_id} 图号 {image_id} 缺少有效直出 direct{index:02d}")
        hashes = [item.get("target_sha256") for item in accepted]
        prompts = [item.get("prompt_sha256") for item in accepted]
        if any(not isinstance(item, str) for item in hashes) or len(hashes) != len(set(hashes)):
            errors.append(f"任务 {task_id} 图号 {image_id} 的有效直出图片哈希重复")
        if any(not isinstance(item, str) for item in prompts) or len(prompts) != len(set(prompts)):
            errors.append(f"任务 {task_id} 图号 {image_id} 的有效直出提示词哈希重复")
        final_ids = legal_finals.get(group, [])
        if not final_ids:
            errors.append(f"任务 {task_id} 图号 {image_id} 缺少最终图")
        elif len(final_ids) > 1:
            errors.append(
                f"任务 {task_id} 图号 {image_id} 当前只能有一个合法最终图，"
                f"实际有 {len(final_ids)} 个"
            )
    return {"ok": not errors, "errors": errors, "records": len(records)}


def finalize_artifact(
    *, manifest_path: str | Path, source_artifact_id: str, destination: str | Path,
    size: int = 1000,
) -> dict[str, Any]:
    """从通过验收的 direct 或 revision 排他派生最终 PNG。"""
    if size != 1000:
        raise TrackerError("TEMU 最终图尺寸必须为 1000x1000")
    manifest = _absolute(manifest_path)
    records = _load_manifest(manifest_path)
    manifest_existed = manifest.exists()
    manifest_size = manifest.stat().st_size if manifest_existed else 0
    source_record = next((item for item in records if item.get("artifact_id") == source_artifact_id), None)
    if source_record is None:
        raise TrackerError(f"找不到来源产物：{source_artifact_id}")
    if source_artifact_id in _inactive_artifact_ids(records):
        raise TrackerError("不能从已被替换或已失效血缘中的产物生成最终图")
    if source_record.get("artifact_kind") not in {"direct", "revision"} or source_record.get("status") != "accepted":
        raise TrackerError("最终图只能从通过验收的 direct 或 revision 派生")
    approval_context = _load_approved_job(
        manifest_path,
        task_id=str(source_record.get("task_id", "")),
        provider=str(source_record.get("provider", "")),
        platform=str(source_record.get("platform", "")),
        product_name=str(source_record.get("product_name", "")),
        image_id=str(source_record.get("image_id", "")),
        image_type=str(source_record.get("image_type", "")),
    )
    _require_matching_immutable_identity(
        records,
        immutable_identity_sha256=approval_context["immutable_identity_sha256"],
    )
    reconciliation_errors: list[str] = []
    _verify_execution_reconciliation(approval_context, records, reconciliation_errors)
    if reconciliation_errors:
        raise TrackerError(f"当前图号 attempt 与清单对账失败：{reconciliation_errors[0]}")
    if not _record_matches_approval(source_record, approval_context):
        raise TrackerError("不能从已失效的审批范围产物生成最终图")
    if not _has_complete_direct_set(records, source_record):
        raise TrackerError("生成最终图前必须具备三个有效直出及完整可验证文件")
    source = _absolute(source_record["target_path"])
    try:
        source_hash_before = _sha256(source) if source.is_file() else None
    except OSError as error:
        raise TrackerError(f"来源产物无法读取：{source}") from error
    if source_hash_before != source_record.get("target_sha256"):
        raise TrackerError("来源产物不存在或哈希不匹配")
    target = _absolute(destination)
    _validate_final_filename(target, source_record)
    base_name = _artifact_base_name(
        str(source_record.get("product_name", "")),
        str(source_record.get("image_type", "")),
        str(source_record.get("image_id", "")),
    )
    final_history = [
        item for item in records
        if item.get("artifact_kind") == "final" and _same_base_artifact_group(item, source_record)
    ]
    for version, item in enumerate(final_history, start=1):
        expected_name = f"{base_name}_v{version:02d}.png"
        if _absolute(str(item.get("target_path", ""))).name != expected_name:
            raise TrackerError(f"清单中的最终版本历史不连续，应先修复：{expected_name}")
    final_version = len(final_history) + 1
    expected_final_name = (
        f"{base_name}_v{final_version:02d}.png"
    )
    if target.name != expected_final_name:
        raise TrackerError(f"最终版本必须连续递增，本次应为：{expected_final_name}")
    _validate_final_directory(target, manifest_path, str(source_record.get("provider", "")))
    if target.exists() or any(item.get("target_path") and _absolute(item["target_path"]) == target for item in records):
        raise TrackerError(f"最终图目标已存在，拒绝覆盖：{target}")
    try:
        with Image.open(source) as image:
            if image.size[0] != image.size[1]:
                raise TrackerError("来源产物必须为正方形")
            converted = image.convert("RGBA") if image.mode in {"RGBA", "LA", "P"} else image.convert("RGB")
            result = converted.resize((size, size), Image.Resampling.LANCZOS)
            buffer = io.BytesIO()
            result.save(buffer, format="PNG")
        _write_exclusive(target, buffer.getvalue())
    except FileExistsError as error:
        raise TrackerError(f"最终图目标已存在，拒绝覆盖：{target}") from error
    except (OSError, UnidentifiedImageError) as error:
        raise TrackerError(f"无法生成最终图：{target}") from error
    try:
        if _sha256(source) != source_hash_before:
            raise TrackerError("来源图片在复制期间发生变化，已撤销最终图")
        width, height = _image_size(target)
        record = {
            "schema_version": ARTIFACT_SCHEMA_VERSION,
            "artifact_id": str(uuid.uuid4()),
            "task_id": source_record.get("task_id"),
            "provider": source_record.get("provider"),
            "platform": source_record.get("platform"),
            "product_name": source_record.get("product_name"),
            "image_id": source_record.get("image_id"),
            "image_type": source_record.get("image_type"),
            "immutable_identity_sha256": approval_context["immutable_identity_sha256"],
            "approval_scope_version": approval_context["scope_version"],
            "approval_scope_sha256": approval_context["scope_sha256"],
            "session_id": source_record.get("session_id"),
            "attempt_no": source_record.get("attempt_no"),
            "direct_index": None,
            "artifact_kind": "final",
            "prompt_id": source_record.get("prompt_id"),
            "prompt_path": source_record.get("prompt_path"),
            "prompt_sha256": source_record.get("prompt_sha256"),
            "call_started_at": source_record.get("call_started_at"),
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "provenance_mode": "derivation",
            "source_path": str(source),
            "source_sha256": source_hash_before,
            "target_path": str(target),
            "target_sha256": _sha256(target),
            "width": width,
            "height": height,
            "status": "accepted",
            "visual_checks": dict(source_record.get("visual_checks") or {}),
            "inspection_session_id": None,
            "inspection_checked_at": None,
            "inspection_notes": None,
            "rejection_reason": None,
            "derived_from_artifact_id": source_artifact_id,
            "snapshot_path": source_record.get("snapshot_path"),
            "snapshot_sha256": source_record.get("snapshot_sha256"),
            "supersedes_artifact_id": None,
            "supersession_reason": None,
        }
        _append_manifest(manifest_path, record)
    except Exception as error:
        _restore_manifest(manifest, manifest_existed, manifest_size)
        try:
            target.unlink(missing_ok=True)
        except OSError:
            pass
        if isinstance(error, OSError):
            raise TrackerError("生成最终图期间文件发生变化或无法读取，已撤销最终图") from error
        raise
    return record


def _parse_checks(value: str) -> dict[str, bool]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as error:
        raise TrackerError("视觉检查必须是 JSON 对象") from error
    if not isinstance(parsed, dict) or not all(isinstance(key, str) and isinstance(item, bool) for key, item in parsed.items()):
        raise TrackerError("视觉检查必须是键和值均有效的 JSON 对象")
    return parsed


def _print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def _build_parser() -> argparse.ArgumentParser:
    parser = ChineseArgumentParser(description="TEMU 生图产物追踪与验收工具")
    subparsers = parser.add_subparsers(dest="command", required=True, title="命令", parser_class=ChineseArgumentParser)
    snapshot = subparsers.add_parser("snapshot", help="写入调用前快照")
    snapshot.add_argument("--source-dir", required=True, help="渠道生成目录")
    snapshot.add_argument("--snapshot-path", required=True, help="新快照的保存路径")
    capture = subparsers.add_parser("capture", help="登记一次直出或修订产物")
    capture.add_argument("--snapshot-path", required=True, help="调用前快照路径")
    capture.add_argument("--source-dir", required=True, help="渠道生成目录")
    capture.add_argument("--source", help="渠道明确返回的来源图片路径")
    capture.add_argument("--destination", required=True, help="产物保存路径")
    capture.add_argument("--manifest", required=True, help="JSONL 清单路径")
    for flag, help_text in (("task-id", "任务编号"), ("provider", "渠道名称"), ("platform", "平台名称"), ("product-name", "产品名称"), ("image-id", "图号"), ("image-type", "图型"), ("prompt-id", "提示词编号"), ("prompt-path", "提示词文件路径"), ("call-started-at", "渠道调用开始时间")):
        capture.add_argument(f"--{flag}", required=True, help=help_text)
    capture.add_argument("--attempt-no", required=True, type=int, help="尝试号")
    capture.add_argument("--direct-index", type=int, choices=(1, 2, 3), help="有效直出序号")
    capture.add_argument("--artifact-kind", default="direct", choices=("direct", "revision"), help="产物类型")
    capture.add_argument("--parent-artifact-id", help="修订产物的父级编号")
    capture.add_argument("--supersedes-artifact-id", help="被替换的当前有效直出产物编号")
    capture.add_argument("--supersession-reason", help="替换已有直出的原因")
    capture.add_argument("--status", required=True, choices=("accepted", "rejected"), help="验收状态")
    capture.add_argument("--visual-checks", required=True, help="视觉检查 JSON 对象")
    capture.add_argument("--inspection-session-id", required=True, help="独立检查 Subagent 编号")
    capture.add_argument("--inspection-checked-at", required=True, help="独立检查完成时间")
    capture.add_argument("--inspection-notes", required=True, help="独立检查结论")
    capture.add_argument("--rejection-reason", help="作废原因")
    finalize = subparsers.add_parser("finalize", help="派生最终 1000x1000 图片")
    finalize.add_argument("--manifest", required=True, help="JSONL 清单路径")
    finalize.add_argument("--source-artifact-id", required=True, help="通过验收的直出或修订产物编号")
    finalize.add_argument("--destination", required=True, help="最终图保存路径")
    finalize.add_argument("--size", type=int, default=1000, help="最终图边长，固定为 1000")
    verify = subparsers.add_parser("verify", help="验收清单、直出版本和最终图")
    verify.add_argument("--manifest", required=True, help="JSONL 清单路径")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "snapshot":
            _print_json(write_snapshot(arguments.source_dir, arguments.snapshot_path))
        elif arguments.command == "capture":
            _print_json(capture_artifact(
                snapshot_path=arguments.snapshot_path, source_dir=arguments.source_dir,
                explicit_source=arguments.source, destination=arguments.destination,
                manifest_path=arguments.manifest, task_id=arguments.task_id,
                provider=arguments.provider, platform=arguments.platform,
                product_name=arguments.product_name, image_id=arguments.image_id,
                image_type=arguments.image_type, attempt_no=arguments.attempt_no,
                direct_index=arguments.direct_index, artifact_kind=arguments.artifact_kind,
                prompt_id=arguments.prompt_id, prompt_path=arguments.prompt_path,
                call_started_at=arguments.call_started_at, status=arguments.status,
                visual_checks=_parse_checks(arguments.visual_checks),
                inspection_session_id=arguments.inspection_session_id,
                inspection_checked_at=arguments.inspection_checked_at,
                inspection_notes=arguments.inspection_notes,
                rejection_reason=arguments.rejection_reason,
                parent_artifact_id=arguments.parent_artifact_id,
                supersedes_artifact_id=arguments.supersedes_artifact_id,
                supersession_reason=arguments.supersession_reason,
            ))
        elif arguments.command == "finalize":
            _print_json(finalize_artifact(
                manifest_path=arguments.manifest, source_artifact_id=arguments.source_artifact_id,
                destination=arguments.destination, size=arguments.size,
            ))
        else:
            report = verify_manifest(arguments.manifest)
            _print_json(report)
            return 0 if report["ok"] else 1
    except TrackerError as error:
        print(f"错误：{error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
