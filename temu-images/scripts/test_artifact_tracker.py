from __future__ import annotations

import importlib.util
import inspect
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from PIL import Image


SCRIPT_PATH = Path(__file__).with_name("artifact_tracker.py")

VISUAL_CHECKS_OK = {
    "current_product": True,
    "english_only": True,
    "no_pollution": True,
    "product_preserved": True,
    "scale_correct": True,
    "text_correct": True,
    "platform_compliant": True,
}


class ArtifactTrackerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="temu-images-测试-")
        self.root = Path(self.temp_dir.name)
        self.source_dir = self.root / "全局生成目录"
        self.direct_dir = self.root / "output" / "gpt-images-2-direct"
        self.rejected_dir = self.root / "output" / "temp" / "rejected-imagegen"
        self.final_dir = self.root / "output" / "final"
        self.job_temp_dir = self.root / "output" / "temp" / "temu-20260721-测试" / "副图-01"
        self.job_file = self.job_temp_dir.parent / "_temu_job.json"
        self.prompt_dir = self.job_temp_dir
        self.manifest = self.direct_dir / "_imagegen_manifest.jsonl"
        self.snapshot_file = self.root / "调用前快照.json"
        self.snapshot_counter = 0
        self.source_dir.mkdir(parents=True)
        self.prompt_dir.mkdir(parents=True)
        self.evidence_dir = self.root / "证据"
        self.evidence_dir.mkdir(parents=True)
        self.requirements_evidence = self.evidence_dir / "需求表.xlsx"
        self.requirements_evidence.write_bytes(b"synthetic requirements workbook")
        self.product_evidence = self.png(
            self.evidence_dir / "产品.png", (1200, 1200), (90, 100, 110),
        )
        self.write_job()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def tracker(self):
        self.assertTrue(SCRIPT_PATH.exists(), "artifact_tracker.py 尚未实现")
        spec = importlib.util.spec_from_file_location("artifact_tracker", SCRIPT_PATH)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module

    def png(self, path: Path, size: tuple[int, int], color: tuple[int, int, int]) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", size, color).save(path, format="PNG")
        return path

    def prompt(self, name: str, content: str) -> Path:
        path = self.prompt_dir / name
        path.write_text(content, encoding="utf-8")
        return path

    def sha256(self, path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def approval_scope_payload(self, job: dict) -> dict:
        reference_scope = [
            {
                key: reference.get(key)
                for key in ("reference_id", "evidence_id", "path", "role", "applies_to", "source_location")
            }
            for reference in job["references"]
        ]
        image_scope = [
            {
                key: image.get(key)
                for key in (
                    "image_id", "image_type", "output_type_original", "goal", "copy_original",
                    "copy_corrections", "selling_points", "color_evidence", "allowed_product_changes",
                    "person_scene_basis", "reference_ids", "target_paths",
                )
            }
            for image in job["images"]
        ]
        return {
            "provider": job["provider"],
            "platform": job["platform"],
            "product_name": job["product_name"],
            "product_folder": job["product_folder"],
            "main_session_id": job["main_session_id"],
            "material_inventory": job["material_inventory"],
            "evidence_sources": job["evidence_sources"],
            "product_baseline": job["product_baseline"],
            "fabric_baseline": job["fabric_baseline"],
            "visual_baseline": job["visual_baseline"],
            "references": reference_scope,
            "images": image_scope,
        }

    def write_job(
        self, *, status: str = "approved", scope_version: int = 1, color: str = "Navy",
        product_name: str = "定制沙发坐垫", preserve_attempts: bool = False,
    ) -> dict:
        previous_job = None
        if preserve_attempts and self.job_file.is_file():
            previous_job = json.loads(self.job_file.read_text(encoding="utf-8"))
        job = {
            "schema_version": 1,
            "task_id": "temu-20260721-测试",
            "provider": "imagegen",
            "platform": "temu-us",
            "product_name": product_name,
            "product_folder": str(self.root.resolve()),
            "main_session_id": "session-main-01",
            "job_status": "approved" if status == "approved" else "awaiting_approval",
            "approval": {
                "status": status,
                "scope_version": scope_version,
                "scope_sha256": "",
                "approved_scope_sha256": None,
                "confirmed_at": "2026-07-21T08:00:00+00:00" if status == "approved" else None,
                "confirmation_text": "确认按当前完整范围制作" if status == "approved" else None,
            },
            "material_inventory": {
                "required": {
                    "requirements_table": {"status": "ready", "evidence_ids": ["requirements-01"]},
                    "real_dimensions": {"status": "ready", "evidence_ids": ["requirements-01"]},
                    "product_photos": {"status": "ready", "evidence_ids": ["product-photo-01"]},
                    "output_types": {"status": "ready", "image_ids": ["副图-01"]},
                },
                "conditional": {
                    "vi_brand_guide": {"status": "not_available", "evidence_ids": []},
                    "logo_spec": {"status": "not_available", "evidence_ids": []},
                    "fabric_color": {"status": "not_available", "evidence_ids": []},
                    "product_detail": {"status": "not_available", "evidence_ids": []},
                    "layout_scene_reference": {"status": "not_available", "evidence_ids": []},
                    "prohibited_information": {"status": "not_available", "evidence_ids": []},
                    "wps_dispimg": {"status": "not_available", "evidence_ids": []},
                    "other_materials": {"status": "not_available", "evidence_ids": []},
                },
            },
            "evidence_sources": [
                {
                    "evidence_id": "requirements-01",
                    "kind": "requirements_table",
                    "media_type": "document",
                    "path": str(self.requirements_evidence.resolve()),
                    "sha256": self.sha256(self.requirements_evidence),
                    "view_image": None,
                },
                {
                    "evidence_id": "product-photo-01",
                    "kind": "product_photo",
                    "media_type": "image",
                    "path": str(self.product_evidence.resolve()),
                    "sha256": self.sha256(self.product_evidence),
                    "view_image": {
                        "status": "completed",
                        "inspection_session_id": "inspection-素材-01",
                        "checked_at": "2026-07-21T08:01:00+00:00",
                        "notes": "已确认产品结构、面料和比例",
                    },
                },
            ],
            "product_baseline": {
                "base_images": [str(self.product_evidence.resolve())],
                "dimensions_source": {"evidence_id": "requirements-01"},
                "dimensions_original": "24 inch",
            },
            "fabric_baseline": {"status": "not_available"},
            "visual_baseline": {"layout": "统一布局"},
            "references": [
                {
                    "reference_id": "ref-product-01",
                    "evidence_id": "product-photo-01",
                    "path": str(self.product_evidence.resolve()),
                    "role": "edit_target",
                    "applies_to": ["副图-01"],
                    "source_location": None,
                    "view_image": {
                        "status": "completed",
                        "inspection_session_id": "inspection-素材-01",
                        "checked_at": "2026-07-21T08:01:00+00:00",
                        "notes": "已确认产品结构、面料和比例",
                    },
                }
            ],
            "images": [
                {
                    "image_id": "副图-01",
                    "image_type": "副图",
                    "output_type_original": "详情页",
                    "goal": "展示颜色与适配比例",
                    "copy_original": ["CUSTOM FIT"],
                    "copy_corrections": [],
                    "selling_points": ["按需求表制作"],
                    "color_evidence": {"mode": "requirements_text", "value_original": color},
                    "allowed_product_changes": [{"attribute": "color", "scope": color}],
                    "person_scene_basis": {"person_required": False, "decision": "不加入人物"},
                    "reference_ids": ["ref-product-01"],
                    "target_paths": {
                        "direct_directory": str(self.direct_dir.resolve()),
                        "final_directory": str(self.final_dir.resolve()),
                        "final_stem": f"{product_name}_副图_01",
                    },
                    "session": {
                        "status": "generating",
                        "session_id": "session-副图-01",
                        "view_events": [
                            {
                                "session_id": "session-副图-01",
                                "reference_id": "ref-product-01",
                                "image_label": "Image 1",
                                "checked_at": "2026-07-21T08:02:00+00:00",
                                "notes": "本 Session 已查看产品输入",
                            }
                        ],
                    },
                    "execution": {"status": "generating", "attempts": [], "final_inspections": []},
                }
            ],
        }
        if previous_job is not None:
            previous_images = {
                image.get("image_id"): image
                for image in previous_job.get("images", [])
                if isinstance(image, dict)
            }
            for image in job["images"]:
                previous = previous_images.get(image["image_id"])
                if isinstance(previous, dict) and isinstance(previous.get("execution"), dict):
                    image["execution"] = previous["execution"]
        canonical = json.dumps(
            self.approval_scope_payload(job), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        scope_sha256 = hashlib.sha256(canonical).hexdigest()
        job["approval"]["scope_sha256"] = scope_sha256
        if status == "approved":
            job["approval"]["approved_scope_sha256"] = scope_sha256
        self.job_file.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
        return job

    def fresh_capture_snapshot(self) -> Path:
        self.snapshot_counter += 1
        path = self.job_temp_dir / f"调用快照-{self.snapshot_counter:03d}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 2,
            "source_dir": str(self.source_dir.resolve()),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "files": [],
            "images": {},
        }
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def capture_kwargs(
        self,
        *,
        source: Path | None,
        destination: Path,
        prompt_path: Path,
        attempt_no: int = 1,
        direct_index: int | None = 1,
        artifact_kind: str = "direct",
        status: str = "accepted",
        visual_checks: dict[str, bool] | None = None,
        rejection_reason: str | None = None,
        parent_artifact_id: str | None = None,
        supersedes_artifact_id: str | None = None,
        supersession_reason: str | None = None,
        snapshot_path: Path | None = None,
        call_started_at: str | None = None,
    ) -> dict:
        kwargs = {
            "snapshot_path": snapshot_path or self.fresh_capture_snapshot(),
            "source_dir": self.source_dir,
            "explicit_source": source,
            "destination": destination,
            "manifest_path": self.manifest,
            "task_id": "temu-20260721-测试",
            "provider": "imagegen",
            "platform": "temu-us",
            "product_name": "定制沙发坐垫",
            "image_id": "副图-01",
            "image_type": "副图",
            "attempt_no": attempt_no,
            "direct_index": direct_index,
            "artifact_kind": artifact_kind,
            "prompt_id": f"副图-01-p{attempt_no:02d}",
            "prompt_path": prompt_path,
            "call_started_at": call_started_at or datetime.now(timezone.utc).isoformat(),
            "status": status,
            "visual_checks": visual_checks if visual_checks is not None else VISUAL_CHECKS_OK,
            "inspection_session_id": "inspection-产物-01",
            "inspection_checked_at": datetime.now(timezone.utc).isoformat(),
            "inspection_notes": "独立检查 Subagent 已逐项查看产物",
            "rejection_reason": rejection_reason,
        }
        if parent_artifact_id is not None:
            kwargs["parent_artifact_id"] = parent_artifact_id
        if supersedes_artifact_id is not None:
            kwargs["supersedes_artifact_id"] = supersedes_artifact_id
        if supersession_reason is not None:
            kwargs["supersession_reason"] = supersession_reason
        return kwargs

    def read_manifest(self) -> list[dict]:
        return [json.loads(line) for line in self.manifest.read_text(encoding="utf-8").splitlines()]

    def read_job(self) -> dict:
        return json.loads(self.job_file.read_text(encoding="utf-8"))

    def write_job_data(self, job: dict, *, refresh_scope: bool = False) -> None:
        if refresh_scope:
            canonical = json.dumps(
                self.approval_scope_payload(job),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            scope_sha256 = hashlib.sha256(canonical).hexdigest()
            job["approval"]["scope_sha256"] = scope_sha256
            job["approval"]["approved_scope_sha256"] = scope_sha256
        self.job_file.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")

    def archive_attempt(self, record: dict) -> None:
        job = self.read_job()
        image = next(item for item in job["images"] if item["image_id"] == record["image_id"])
        attempt = {
            "attempt_no": record["attempt_no"],
            "approval_scope_version": record["approval_scope_version"],
            "approval_scope_sha256": record["approval_scope_sha256"],
            "session_id": record["session_id"],
            "input_reference_ids": list(image["reference_ids"]),
            "view_events": json.loads(json.dumps(image["session"]["view_events"], ensure_ascii=False)),
            "prompt_id": record["prompt_id"],
            "prompt_path": record["prompt_path"],
            "prompt_sha256": record["prompt_sha256"],
            "snapshot_path": record["snapshot_path"],
            "snapshot_sha256": record["snapshot_sha256"],
            "call_started_at": record["call_started_at"],
            "status": record["status"],
            "artifact_id": record["artifact_id"],
            "artifact_kind": record["artifact_kind"],
            "direct_index": record["direct_index"],
            "rejection_reason": record["rejection_reason"],
            "provenance_mode": record["provenance_mode"],
            "source_path": record["source_path"],
            "source_sha256": record["source_sha256"],
            "target_path": record["target_path"],
            "target_sha256": record["target_sha256"],
            "width": record["width"],
            "height": record["height"],
            "inspection_session_id": record["inspection_session_id"],
            "inspection_checked_at": record["inspection_checked_at"],
            "inspection_notes": record["inspection_notes"],
            "failure_reason": record["rejection_reason"] if record["status"] == "rejected" else None,
        }
        image["execution"]["attempts"].append(attempt)
        image["execution"]["status"] = "awaiting_review"
        self.write_job_data(job)

    def capture_and_archive(self, tracker, **kwargs) -> dict:
        record = tracker.capture_artifact(**kwargs)
        self.archive_attempt(record)
        return record

    def calling_attempt(self, kwargs: dict) -> dict:
        job = self.read_job()
        image = next(item for item in job["images"] if item["image_id"] == kwargs["image_id"])
        return {
            "attempt_no": kwargs["attempt_no"],
            "approval_scope_version": job["approval"]["scope_version"],
            "approval_scope_sha256": job["approval"]["scope_sha256"],
            "session_id": image["session"]["session_id"],
            "input_reference_ids": list(image["reference_ids"]),
            "view_events": json.loads(json.dumps(image["session"]["view_events"], ensure_ascii=False)),
            "prompt_id": kwargs["prompt_id"],
            "prompt_path": str(Path(kwargs["prompt_path"]).resolve()),
            "prompt_sha256": self.sha256(Path(kwargs["prompt_path"])),
            "snapshot_path": str(Path(kwargs["snapshot_path"]).resolve()),
            "snapshot_sha256": self.sha256(Path(kwargs["snapshot_path"])),
            "call_started_at": kwargs["call_started_at"],
            "status": "calling",
        }

    def record_final_inspection(self, record: dict, *, session_id: str = "inspection-final-01") -> None:
        job = self.read_job()
        image = next(item for item in job["images"] if item["image_id"] == record["image_id"])
        image["execution"].setdefault("final_inspections", []).append({
            "artifact_id": record["artifact_id"],
            "inspection_session_id": session_id,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "notes": "独立检查 Subagent 已查看最终图",
            "visual_checks": dict(VISUAL_CHECKS_OK),
        })
        self.write_job_data(job)

    def test_snapshot_round_trips_unicode_paths(self) -> None:
        tracker = self.tracker()
        image = self.png(self.source_dir / "中文产品图.png", (1024, 1024), (10, 20, 30))
        snapshot = tracker.write_snapshot(self.source_dir, self.snapshot_file)

        self.assertEqual(Path(snapshot["source_dir"]), self.source_dir.resolve())
        self.assertIn(str(image.resolve()), snapshot["files"])
        loaded = json.loads(self.snapshot_file.read_text(encoding="utf-8"))
        self.assertEqual(loaded["files"], snapshot["files"])

    def test_snapshot_diff_requires_exactly_one_candidate(self) -> None:
        tracker = self.tracker()
        tracker.write_snapshot(self.source_dir, self.snapshot_file)

        with self.assertRaisesRegex(tracker.TrackerError, "没有发现"):
            tracker.resolve_source(self.snapshot_file, self.source_dir, None)

        self.png(self.source_dir / "候选一.png", (1024, 1024), (1, 2, 3))
        self.png(self.source_dir / "候选二.png", (1024, 1024), (4, 5, 6))
        with self.assertRaisesRegex(tracker.TrackerError, "多个候选"):
            tracker.resolve_source(self.snapshot_file, self.source_dir, None)

    def test_explicit_source_has_precedence_over_multiple_candidates(self) -> None:
        tracker = self.tracker()
        tracker.write_snapshot(self.source_dir, self.snapshot_file)
        first = self.png(self.source_dir / "候选一.png", (1024, 1024), (1, 2, 3))
        self.png(self.source_dir / "候选二.png", (1024, 1024), (4, 5, 6))

        resolved, mode = tracker.resolve_source(self.snapshot_file, self.source_dir, first)

        self.assertEqual(resolved, first.resolve())
        self.assertEqual(mode, "tool_return")

    def test_snapshot_is_bound_to_source_directory_time_and_one_capture(self) -> None:
        tracker = self.tracker()
        tracker.write_snapshot(self.source_dir, self.snapshot_file)
        other_source_dir = self.root / "其他生成目录"
        other_source_dir.mkdir()
        with self.assertRaisesRegex(tracker.TrackerError, "目录不一致"):
            tracker.resolve_source(self.snapshot_file, other_source_dir, None)

        source1 = self.png(self.source_dir / "版本一.png", (1024, 1024), (10, 20, 30))
        prompt1 = self.prompt("副图-01-p01.txt", "第一版")
        shared_snapshot = self.fresh_capture_snapshot()
        tracker.capture_artifact(**self.capture_kwargs(
            source=source1,
            destination=self.direct_dir / "定制沙发坐垫_副图_01_direct01.png",
            prompt_path=prompt1,
            snapshot_path=shared_snapshot,
        ))

        source2 = self.png(self.source_dir / "版本二.png", (1024, 1024), (40, 50, 60))
        prompt2 = self.prompt("副图-01-p02.txt", "第二版")
        with self.assertRaisesRegex(tracker.TrackerError, "快照已被使用"):
            tracker.capture_artifact(**self.capture_kwargs(
                source=source2,
                destination=self.direct_dir / "定制沙发坐垫_副图_01_direct02.png",
                prompt_path=prompt2,
                attempt_no=2,
                direct_index=2,
                snapshot_path=shared_snapshot,
            ))

        with self.assertRaisesRegex(tracker.TrackerError, "不能早于"):
            tracker.capture_artifact(**self.capture_kwargs(
                source=source2,
                destination=self.direct_dir / "定制沙发坐垫_副图_01_direct02.png",
                prompt_path=prompt2,
                attempt_no=2,
                direct_index=2,
                call_started_at="2000-01-01T00:00:00+00:00",
            ))

    def test_snapshot_diff_detects_changed_image_and_ignores_non_images(self) -> None:
        tracker = self.tracker()
        changed = self.png(self.source_dir / "固定名称.png", (1024, 1024), (1, 2, 3))
        snapshot_inside_source = self.source_dir / "调用前快照.json"
        tracker.write_snapshot(self.source_dir, snapshot_inside_source)

        self.png(changed, (1024, 1024), (9, 8, 7))
        (self.source_dir / "运行日志.txt").write_text("不是图片", encoding="utf-8")
        try:
            resolved, mode = tracker.resolve_source(snapshot_inside_source, self.source_dir, None)
        except tracker.TrackerError as error:
            self.fail(f"同名图片变更应成为唯一候选：{error}")

        self.assertEqual(resolved, changed.resolve())
        self.assertEqual(mode, "snapshot_diff")

    def test_capture_records_hashes_dimensions_and_chinese_paths(self) -> None:
        tracker = self.tracker()
        tracker.write_snapshot(self.source_dir, self.snapshot_file)
        source = self.png(self.source_dir / "本次返回.png", (1024, 1024), (10, 20, 30))
        prompt = self.prompt("副图-01-p01.txt", "第一版提示词：保持参考图产品不变。")
        destination = self.direct_dir / "定制沙发坐垫_副图_01_direct01.png"

        record = tracker.capture_artifact(**self.capture_kwargs(
            source=source,
            destination=destination,
            prompt_path=prompt,
        ))

        self.assertEqual(record["width"], 1024)
        self.assertEqual(record["height"], 1024)
        self.assertEqual(record["source_sha256"], record["target_sha256"])
        self.assertEqual(record["provenance_mode"], "tool_return")
        self.assertEqual(record["status"], "accepted")
        self.assertEqual(record["approval_scope_version"], 1)
        self.assertEqual(record["approval_scope_sha256"], json.loads(
            self.job_file.read_text(encoding="utf-8")
        )["approval"]["scope_sha256"])
        self.assertEqual(record["session_id"], "session-副图-01")
        self.assertTrue(destination.exists())
        self.assertEqual(self.read_manifest(), [record])

    def test_capture_requires_current_user_approval(self) -> None:
        tracker = self.tracker()
        self.write_job(status="pending")
        source = self.png(self.source_dir / "未批准来源.png", (1024, 1024), (10, 20, 30))
        prompt = self.prompt("副图-01-p01.txt", "未批准时不得捕获")

        with self.assertRaisesRegex(tracker.TrackerError, "批准|确认"):
            tracker.capture_artifact(**self.capture_kwargs(
                source=source,
                destination=self.direct_dir / "定制沙发坐垫_副图_01_direct01.png",
                prompt_path=prompt,
            ))

        self.assertFalse((self.direct_dir / "定制沙发坐垫_副图_01_direct01.png").exists())

    def test_capture_rejects_scope_tampering_and_missing_session_views(self) -> None:
        tracker = self.tracker()
        source = self.png(self.source_dir / "审批校验来源.png", (1024, 1024), (10, 20, 30))
        prompt = self.prompt("副图-01-p01.txt", "审批范围与查看记录校验")
        job = json.loads(self.job_file.read_text(encoding="utf-8"))
        job["images"][0]["goal"] = "未经重新确认的新目标"
        self.job_file.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")

        with self.assertRaisesRegex(tracker.TrackerError, "SHA256|重新确认"):
            tracker.capture_artifact(**self.capture_kwargs(
                source=source,
                destination=self.direct_dir / "定制沙发坐垫_副图_01_direct01.png",
                prompt_path=prompt,
            ))

        job = self.write_job()
        job["images"][0]["session"]["view_events"] = []
        self.job_file.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
        with self.assertRaisesRegex(tracker.TrackerError, "尚未查看"):
            tracker.capture_artifact(**self.capture_kwargs(
                source=source,
                destination=self.direct_dir / "定制沙发坐垫_副图_01_direct01.png",
                prompt_path=prompt,
            ))

    def test_capture_rejects_approved_target_paths_that_do_not_match_manifest(self) -> None:
        tracker = self.tracker()
        job = self.write_job()
        job["images"][0]["target_paths"]["direct_directory"] = str(
            (self.root / "output" / "错误直出目录").resolve()
        )
        scope_sha256 = hashlib.sha256(json.dumps(
            self.approval_scope_payload(job),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        job["approval"]["scope_sha256"] = scope_sha256
        job["approval"]["approved_scope_sha256"] = scope_sha256
        self.job_file.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
        source = self.png(self.source_dir / "目标路径校验.png", (1024, 1024), (10, 20, 30))
        prompt = self.prompt("副图-01-p01.txt", "目标路径校验")

        with self.assertRaisesRegex(tracker.TrackerError, "目标路径|直出目录"):
            tracker.capture_artifact(**self.capture_kwargs(
                source=source,
                destination=self.direct_dir / "定制沙发坐垫_副图_01_direct01.png",
                prompt_path=prompt,
            ))

    def test_capture_does_not_reuse_attempt_recorded_without_artifact(self) -> None:
        tracker = self.tracker()
        source = self.png(self.source_dir / "超时后的新来源.png", (1024, 1024), (10, 20, 30))
        prompt = self.prompt("副图-01-p01.txt", "不得复用超时尝试号")
        kwargs = self.capture_kwargs(
            source=source,
            destination=self.direct_dir / "定制沙发坐垫_副图_01_direct01.png",
            prompt_path=prompt,
            attempt_no=1,
        )
        job = self.read_job()
        failed = self.calling_attempt(kwargs)
        failed["status"] = "failed"
        failed["failure_reason"] = "渠道超时且没有唯一来源"
        job["images"][0]["execution"]["attempts"] = [failed]
        self.write_job_data(job)

        with self.assertRaisesRegex(tracker.TrackerError, "尝试号.*递增|下一次至少"):
            tracker.capture_artifact(**kwargs)

    def test_capture_accepts_only_the_current_calling_attempt(self) -> None:
        tracker = self.tracker()
        source = self.png(self.source_dir / "调用中来源.png", (1024, 1024), (10, 20, 30))
        prompt = self.prompt("副图-01-p01.txt", "当前调用尝试")
        current_kwargs = self.capture_kwargs(
            source=source,
            destination=self.direct_dir / "定制沙发坐垫_副图_01_direct01.png",
            prompt_path=prompt,
            attempt_no=1,
        )
        job = self.read_job()
        job["images"][0]["execution"]["attempts"] = [self.calling_attempt(current_kwargs)]
        self.write_job_data(job)

        with self.assertRaisesRegex(tracker.TrackerError, "尚未归档"):
            tracker.capture_artifact(**self.capture_kwargs(
                source=source,
                destination=self.direct_dir / "定制沙发坐垫_副图_01_direct01.png",
                prompt_path=prompt,
                attempt_no=2,
            ))
        record = tracker.capture_artifact(**current_kwargs)
        self.assertEqual(record["attempt_no"], 1)
        report = tracker.verify_manifest(self.manifest)
        self.assertTrue(any("尚未归档" in error for error in report["errors"]))

    def test_finalize_and_verify_reject_expired_approval(self) -> None:
        tracker = self.tracker()
        records = self.create_three_directs(tracker)
        self.write_job(status="pending")

        with self.assertRaisesRegex(tracker.TrackerError, "批准|确认"):
            tracker.finalize_artifact(
                manifest_path=self.manifest,
                source_artifact_id=records[0]["artifact_id"],
                destination=self.final_dir / "定制沙发坐垫_副图_01_v01.png",
            )
        report = tracker.verify_manifest(self.manifest)
        self.assertFalse(report["ok"])
        self.assertTrue(any("审批校验失败" in error for error in report["errors"]))

    def test_capture_refuses_non_square_accepted_direct(self) -> None:
        tracker = self.tracker()
        tracker.write_snapshot(self.source_dir, self.snapshot_file)
        source = self.png(self.source_dir / "非正方形.png", (1200, 800), (10, 20, 30))
        prompt = self.prompt("副图-01-p01.txt", "非正方形测试")
        destination = self.direct_dir / "定制沙发坐垫_副图_01_direct01.png"

        with self.assertRaisesRegex(tracker.TrackerError, "正方形"):
            tracker.capture_artifact(**self.capture_kwargs(
                source=source,
                destination=destination,
                prompt_path=prompt,
            ))

        self.assertFalse(destination.exists())

    def test_capture_requires_png_and_canonical_name_for_accepted_direct(self) -> None:
        tracker = self.tracker()
        tracker.write_snapshot(self.source_dir, self.snapshot_file)
        source = self.png(self.source_dir / "本次返回.png", (1024, 1024), (10, 20, 30))
        prompt = self.prompt("副图-01-p01.txt", "命名检查")

        with self.assertRaisesRegex(tracker.TrackerError, "命名"):
            tracker.capture_artifact(**self.capture_kwargs(
                source=source,
                destination=self.direct_dir / "随意文件名.png",
                prompt_path=prompt,
            ))

        jpeg_source = self.source_dir / "错误格式.jpg"
        Image.new("RGB", (1024, 1024), (20, 30, 40)).save(jpeg_source, format="JPEG")
        with self.assertRaisesRegex(tracker.TrackerError, "PNG"):
            tracker.capture_artifact(**self.capture_kwargs(
                source=jpeg_source,
                destination=self.direct_dir / "定制沙发坐垫_副图_01_direct01.png",
                prompt_path=prompt,
            ))

    def test_capture_requires_nonempty_utf8_txt_prompt(self) -> None:
        tracker = self.tracker()
        source = self.png(self.source_dir / "提示词格式来源.png", (1024, 1024), (10, 20, 30))
        wrong_extension = self.prompt_dir / "副图-01-p01.bin"
        wrong_extension.write_bytes(b"prompt")
        with self.assertRaisesRegex(tracker.TrackerError, r"TXT|\.txt"):
            tracker.capture_artifact(**self.capture_kwargs(
                source=source,
                destination=self.direct_dir / "定制沙发坐垫_副图_01_direct01.png",
                prompt_path=wrong_extension,
            ))

        invalid_utf8 = self.prompt_dir / "副图-01-p01.txt"
        invalid_utf8.write_bytes(b"\xff\xfe")
        with self.assertRaisesRegex(tracker.TrackerError, "UTF-8"):
            tracker.capture_artifact(**self.capture_kwargs(
                source=source,
                destination=self.direct_dir / "定制沙发坐垫_副图_01_direct01.png",
                prompt_path=invalid_utf8,
            ))

        invalid_utf8.write_text("   \n", encoding="utf-8")
        with self.assertRaisesRegex(tracker.TrackerError, "不能为空"):
            tracker.capture_artifact(**self.capture_kwargs(
                source=source,
                destination=self.direct_dir / "定制沙发坐垫_副图_01_direct01.png",
                prompt_path=invalid_utf8,
            ))

    def test_rejected_artifact_does_not_consume_direct_index(self) -> None:
        tracker = self.tracker()
        tracker.write_snapshot(self.source_dir, self.snapshot_file)
        source = self.png(self.source_dir / "错误文字.png", (1024, 1024), (10, 20, 30))
        prompt = self.prompt("副图-01-p01.txt", "错误文字测试")
        destination = self.rejected_dir / "定制沙发坐垫_副图_01_attempt01_rejected.png"
        checks = dict(VISUAL_CHECKS_OK)
        checks["text_correct"] = False

        record = tracker.capture_artifact(**self.capture_kwargs(
            source=source,
            destination=destination,
            prompt_path=prompt,
            direct_index=None,
            status="rejected",
            visual_checks=checks,
            rejection_reason="英文标题拼写错误",
        ))

        self.assertIsNone(record["direct_index"])
        self.assertEqual(record["status"], "rejected")
        report = tracker.verify_manifest(self.manifest)
        self.assertFalse(report["ok"])
        self.assertTrue(any("缺少有效直出" in error for error in report["errors"]))

    def test_capture_refuses_overwrite(self) -> None:
        tracker = self.tracker()
        tracker.write_snapshot(self.source_dir, self.snapshot_file)
        source = self.png(self.source_dir / "本次返回.png", (1024, 1024), (10, 20, 30))
        prompt = self.prompt("副图-01-p01.txt", "覆盖测试")
        destination = self.png(
            self.direct_dir / "定制沙发坐垫_副图_01_direct01.png",
            (1024, 1024),
            (99, 99, 99),
        )

        with self.assertRaisesRegex(tracker.TrackerError, "已存在"):
            tracker.capture_artifact(**self.capture_kwargs(
                source=source,
                destination=destination,
                prompt_path=prompt,
            ))

    def test_capture_enforces_output_directories_attempt_order_and_group_identity(self) -> None:
        tracker = self.tracker()
        source1 = self.png(self.source_dir / "版本一.png", (1024, 1024), (10, 20, 30))
        prompt1 = self.prompt("副图-01-p01.txt", "第一版")
        with self.assertRaisesRegex(tracker.TrackerError, "目录"):
            tracker.capture_artifact(**self.capture_kwargs(
                source=source1,
                destination=self.root / "错误目录" / "定制沙发坐垫_副图_01_direct01.png",
                prompt_path=prompt1,
            ))

        tracker.capture_artifact(**self.capture_kwargs(
            source=source1,
            destination=self.direct_dir / "定制沙发坐垫_副图_01_direct01.png",
            prompt_path=prompt1,
        ))
        source2 = self.png(self.source_dir / "版本二.png", (1024, 1024), (40, 50, 60))
        prompt2 = self.prompt("副图-01-p02.txt", "第二版")
        with self.assertRaisesRegex(tracker.TrackerError, "递增"):
            tracker.capture_artifact(**self.capture_kwargs(
                source=source2,
                destination=self.direct_dir / "定制沙发坐垫_副图_01_direct02.png",
                prompt_path=prompt2,
                attempt_no=1,
                direct_index=2,
            ))

        mixed = self.capture_kwargs(
            source=source2,
            destination=self.direct_dir / "另一个产品_副图_01_direct02.png",
            prompt_path=prompt2,
            attempt_no=2,
            direct_index=2,
        )
        mixed["product_name"] = "另一个产品"
        self.write_job(scope_version=2, product_name="另一个产品")
        with self.assertRaisesRegex(tracker.TrackerError, "不可变任务身份.*新 task"):
            tracker.capture_artifact(**mixed)
        self.write_job()

        checks = dict(VISUAL_CHECKS_OK)
        checks["text_correct"] = False
        with self.assertRaisesRegex(tracker.TrackerError, "目录"):
            tracker.capture_artifact(**self.capture_kwargs(
                source=source2,
                destination=self.final_dir / "定制沙发坐垫_副图_01_attempt02_rejected.png",
                prompt_path=prompt2,
                attempt_no=2,
                direct_index=None,
                status="rejected",
                visual_checks=checks,
                rejection_reason="文字错误",
            ))

    def test_capture_rolls_back_orphan_when_manifest_append_fails(self) -> None:
        tracker = self.tracker()
        tracker.write_snapshot(self.source_dir, self.snapshot_file)
        source = self.png(self.source_dir / "本次返回.png", (1024, 1024), (10, 20, 30))
        prompt = self.prompt("副图-01-p01.txt", "中断恢复测试")
        destination = self.direct_dir / "定制沙发坐垫_副图_01_direct01.png"
        kwargs = self.capture_kwargs(source=source, destination=destination, prompt_path=prompt)

        with mock.patch.object(tracker, "_append_manifest", side_effect=tracker.TrackerError("模拟清单写入失败")):
            with self.assertRaisesRegex(tracker.TrackerError, "模拟清单写入失败"):
                tracker.capture_artifact(**kwargs)

        self.assertFalse(destination.exists(), "清单失败后不得遗留未登记目标文件")
        record = tracker.capture_artifact(**kwargs)
        self.assertEqual(record["status"], "accepted")

    def test_capture_rejects_source_changed_during_copy(self) -> None:
        tracker = self.tracker()
        tracker.write_snapshot(self.source_dir, self.snapshot_file)
        source = self.png(self.source_dir / "本次返回.png", (1024, 1024), (10, 20, 30))
        prompt = self.prompt("副图-01-p01.txt", "复制竞态测试")
        destination = self.direct_dir / "定制沙发坐垫_副图_01_direct01.png"
        self.assertTrue(hasattr(tracker, "_copy_exclusive"), "必须提供排他复制以避免覆盖竞态")
        original_copy = tracker._copy_exclusive

        def mutate_then_copy(source_path, target_path):
            self.png(Path(source_path), (1024, 1024), (99, 88, 77))
            return original_copy(source_path, target_path)

        with mock.patch.object(tracker, "_copy_exclusive", side_effect=mutate_then_copy):
            with self.assertRaisesRegex(tracker.TrackerError, "复制期间发生变化"):
                tracker.capture_artifact(**self.capture_kwargs(
                    source=source,
                    destination=destination,
                    prompt_path=prompt,
                ))

        self.assertFalse(destination.exists())

    def test_capture_refuses_duplicate_image_or_prompt_for_direct_variants(self) -> None:
        tracker = self.tracker()
        tracker.write_snapshot(self.source_dir, self.snapshot_file)
        source1 = self.png(self.source_dir / "版本一.png", (1024, 1024), (10, 20, 30))
        source2 = self.png(self.source_dir / "版本二.png", (1024, 1024), (10, 20, 30))
        prompt1 = self.prompt("副图-01-p01.txt", "相同提示词")
        prompt2 = self.prompt("副图-01-p02.txt", "相同提示词")
        tracker.capture_artifact(**self.capture_kwargs(
            source=source1,
            destination=self.direct_dir / "定制沙发坐垫_副图_01_direct01.png",
            prompt_path=prompt1,
        ))

        with self.assertRaisesRegex(tracker.TrackerError, "图片哈希重复"):
            tracker.capture_artifact(**self.capture_kwargs(
                source=source2,
                destination=self.direct_dir / "定制沙发坐垫_副图_01_direct02.png",
                prompt_path=prompt2,
                attempt_no=2,
                direct_index=2,
            ))

        source3 = self.png(self.source_dir / "版本三.png", (1024, 1024), (40, 50, 60))
        with self.assertRaisesRegex(tracker.TrackerError, "提示词哈希重复"):
            tracker.capture_artifact(**self.capture_kwargs(
                source=source3,
                destination=self.direct_dir / "定制沙发坐垫_副图_01_direct02.png",
                prompt_path=prompt2,
                attempt_no=2,
                direct_index=2,
            ))

    def test_accepted_artifact_requires_all_visual_checks(self) -> None:
        tracker = self.tracker()
        tracker.write_snapshot(self.source_dir, self.snapshot_file)
        source = self.png(self.source_dir / "比例错误.png", (1024, 1024), (10, 20, 30))
        prompt = self.prompt("副图-01-p01.txt", "比例检查")
        checks = dict(VISUAL_CHECKS_OK)
        checks["scale_correct"] = False

        with self.assertRaisesRegex(tracker.TrackerError, "视觉检查"):
            tracker.capture_artifact(**self.capture_kwargs(
                source=source,
                destination=self.direct_dir / "定制沙发坐垫_副图_01_direct01.png",
                prompt_path=prompt,
                visual_checks=checks,
            ))

    def create_three_directs(self, tracker) -> list[dict]:
        tracker.write_snapshot(self.source_dir, self.snapshot_file)
        records = []
        for index, color in enumerate(((10, 20, 30), (40, 50, 60), (70, 80, 90)), start=1):
            source = self.png(self.source_dir / f"版本{index}.png", (1024, 1024), color)
            prompt = self.prompt(f"副图-01-p{index:02d}.txt", f"第{index}版提示词，调整构图层级 {index}")
            records.append(self.capture_and_archive(tracker, **self.capture_kwargs(
                source=source,
                destination=self.direct_dir / f"定制沙发坐垫_副图_01_direct{index:02d}.png",
                prompt_path=prompt,
                attempt_no=index,
                direct_index=index,
            )))
        return records

    def test_verify_reports_interrupted_generation_and_tampering(self) -> None:
        tracker = self.tracker()
        tracker.write_snapshot(self.source_dir, self.snapshot_file)
        for index, color in enumerate(((10, 20, 30), (40, 50, 60)), start=1):
            source = self.png(self.source_dir / f"版本{index}.png", (1024, 1024), color)
            prompt = self.prompt(f"副图-01-p{index:02d}.txt", f"第{index}版提示词")
            tracker.capture_artifact(**self.capture_kwargs(
                source=source,
                destination=self.direct_dir / f"定制沙发坐垫_副图_01_direct{index:02d}.png",
                prompt_path=prompt,
                attempt_no=index,
                direct_index=index,
            ))

        interrupted = tracker.verify_manifest(self.manifest)
        self.assertFalse(interrupted["ok"])
        self.assertTrue(any("direct03" in error for error in interrupted["errors"]))

        first_target = self.direct_dir / "定制沙发坐垫_副图_01_direct01.png"
        first_target.write_bytes(b"tampered")
        tampered = tracker.verify_manifest(self.manifest)
        self.assertTrue(any("哈希不匹配" in error for error in tampered["errors"]))

    def test_replacement_direct_supersedes_tampered_version_without_overwrite(self) -> None:
        tracker = self.tracker()
        records = self.create_three_directs(tracker)
        old_target = Path(records[1]["target_path"])
        self.png(old_target, (1024, 1024), (1, 1, 1))
        replacement_source = self.png(self.source_dir / "版本二替换.png", (1024, 1024), (101, 102, 103))
        replacement_prompt = self.prompt("副图-01-p04.txt", "替换损坏的第二版，采用新的信息层级")
        replacement_path = self.direct_dir / "定制沙发坐垫_副图_01_direct02_replacement04.png"

        with self.assertRaisesRegex(tracker.TrackerError, "替换原因"):
            tracker.capture_artifact(**self.capture_kwargs(
                source=replacement_source,
                destination=replacement_path,
                prompt_path=replacement_prompt,
                attempt_no=4,
                direct_index=2,
                supersedes_artifact_id=records[1]["artifact_id"],
            ))

        replacement = self.capture_and_archive(tracker, **self.capture_kwargs(
            source=replacement_source,
            destination=replacement_path,
            prompt_path=replacement_prompt,
            attempt_no=4,
            direct_index=2,
            supersedes_artifact_id=records[1]["artifact_id"],
            supersession_reason="原 direct02 文件哈希被篡改",
        ))
        self.assertEqual(replacement["supersedes_artifact_id"], records[1]["artifact_id"])
        self.assertTrue(old_target.exists(), "被替换的证据文件不得删除或覆盖")
        self.assertTrue(replacement_path.exists())

        final = tracker.finalize_artifact(
            manifest_path=self.manifest,
            source_artifact_id=replacement["artifact_id"],
            destination=self.final_dir / "定制沙发坐垫_副图_01_v01.png",
        )
        self.record_final_inspection(final)
        report = tracker.verify_manifest(self.manifest)
        self.assertTrue(report["ok"], "\n".join(report["errors"]))

    def test_scope_change_requires_replacing_old_directs_before_new_final(self) -> None:
        tracker = self.tracker()
        old_directs = self.create_three_directs(tracker)
        tracker.finalize_artifact(
            manifest_path=self.manifest,
            source_artifact_id=old_directs[0]["artifact_id"],
            destination=self.final_dir / "定制沙发坐垫_副图_01_v01.png",
        )
        new_job = self.write_job(scope_version=2, color="Gray", preserve_attempts=True)

        stale_report = tracker.verify_manifest(self.manifest)
        self.assertFalse(stale_report["ok"])
        self.assertTrue(any("审批范围" in error for error in stale_report["errors"]))

        replacements = []
        for attempt_no, (direct_index, old_record) in enumerate(enumerate(old_directs, start=1), start=4):
            source = self.png(
                self.source_dir / f"范围二版本{direct_index}.png",
                (1024, 1024),
                (100 + direct_index, 110 + direct_index, 120 + direct_index),
            )
            prompt = self.prompt(
                f"副图-01-scope02-p{attempt_no:02d}.txt",
                f"范围二第{direct_index}版提示词，Gray 语义色相与新布局 {direct_index}",
            )
            replacements.append(self.capture_and_archive(tracker, **self.capture_kwargs(
                source=source,
                destination=self.direct_dir /
                f"定制沙发坐垫_副图_01_direct{direct_index:02d}_replacement{attempt_no:02d}.png",
                prompt_path=prompt,
                attempt_no=attempt_no,
                direct_index=direct_index,
                supersedes_artifact_id=old_record["artifact_id"],
                supersession_reason="审批范围从版本 1 变更为版本 2",
            )))

        final = tracker.finalize_artifact(
            manifest_path=self.manifest,
            source_artifact_id=replacements[0]["artifact_id"],
            destination=self.final_dir / "定制沙发坐垫_副图_01_v02.png",
        )
        self.assertEqual(final["approval_scope_version"], 2)
        self.assertEqual(final["approval_scope_sha256"], new_job["approval"]["scope_sha256"])
        self.record_final_inspection(final)
        report = tracker.verify_manifest(self.manifest)
        self.assertTrue(report["ok"], "\n".join(report["errors"]))

    def test_finalize_creates_1000_square_and_records_derivation(self) -> None:
        tracker = self.tracker()
        records = self.create_three_directs(tracker)
        final_path = self.final_dir / "定制沙发坐垫_副图_01_v01.png"

        final_record = tracker.finalize_artifact(
            manifest_path=self.manifest,
            source_artifact_id=records[0]["artifact_id"],
            destination=final_path,
            size=1000,
        )

        self.assertEqual((final_record["width"], final_record["height"]), (1000, 1000))
        self.assertEqual(final_record["artifact_kind"], "final")
        self.assertEqual(final_record["derived_from_artifact_id"], records[0]["artifact_id"])
        self.assertTrue(final_path.exists())
        self.record_final_inspection(final_record)
        self.assertTrue(tracker.verify_manifest(self.manifest)["ok"])

    def test_finalize_requires_three_directs_and_canonical_name(self) -> None:
        tracker = self.tracker()
        tracker.write_snapshot(self.source_dir, self.snapshot_file)
        records = []
        for index, color in enumerate(((10, 20, 30), (40, 50, 60), (70, 80, 90)), start=1):
            source = self.png(self.source_dir / f"版本{index}.png", (1024, 1024), color)
            prompt = self.prompt(f"副图-01-p{index:02d}.txt", f"第{index}版提示词")
            records.append(self.capture_and_archive(tracker, **self.capture_kwargs(
                source=source,
                destination=self.direct_dir / f"定制沙发坐垫_副图_01_direct{index:02d}.png",
                prompt_path=prompt,
                attempt_no=index,
                direct_index=index,
            )))
            if index == 1:
                with self.assertRaisesRegex(tracker.TrackerError, "三个有效直出"):
                    tracker.finalize_artifact(
                        manifest_path=self.manifest,
                        source_artifact_id=records[0]["artifact_id"],
                        destination=self.final_dir / "定制沙发坐垫_副图_01_v01.png",
                    )

        with self.assertRaisesRegex(tracker.TrackerError, "命名"):
            tracker.finalize_artifact(
                manifest_path=self.manifest,
                source_artifact_id=records[0]["artifact_id"],
                destination=self.final_dir / "随意终稿.png",
            )
        with self.assertRaisesRegex(tracker.TrackerError, "目录"):
            tracker.finalize_artifact(
                manifest_path=self.manifest,
                source_artifact_id=records[0]["artifact_id"],
                destination=self.direct_dir / "定制沙发坐垫_副图_01_v01.png",
            )

    def test_finalize_rolls_back_target_and_partial_manifest_append(self) -> None:
        tracker = self.tracker()
        records = self.create_three_directs(tracker)
        final_path = self.final_dir / "定制沙发坐垫_副图_01_v01.png"
        manifest_before = self.manifest.read_bytes()

        def append_partial_then_fail(manifest_path, record):
            with Path(manifest_path).open("ab") as manifest:
                manifest.write(b'{"partial"')
            raise tracker.TrackerError("模拟最终清单写入失败")

        with mock.patch.object(tracker, "_append_manifest", side_effect=append_partial_then_fail):
            with self.assertRaisesRegex(tracker.TrackerError, "模拟最终清单写入失败"):
                tracker.finalize_artifact(
                    manifest_path=self.manifest,
                    source_artifact_id=records[0]["artifact_id"],
                    destination=final_path,
                )

        self.assertFalse(final_path.exists())
        self.assertEqual(self.manifest.read_bytes(), manifest_before)

    def test_verify_requires_final_after_three_valid_directs(self) -> None:
        tracker = self.tracker()
        self.create_three_directs(tracker)

        report = tracker.verify_manifest(self.manifest)

        self.assertFalse(report["ok"])
        self.assertTrue(any("缺少最终图" in error for error in report["errors"]))

    def test_revision_requires_valid_parent_and_can_be_final_source(self) -> None:
        tracker = self.tracker()
        self.assertIn(
            "parent_artifact_id",
            inspect.signature(tracker.capture_artifact).parameters,
            "revision 必须接受并验证父级产物编号",
        )
        direct_records = self.create_three_directs(tracker)
        source = self.png(self.source_dir / "渠道修订.png", (1024, 1024), (15, 25, 35))
        prompt = self.prompt("副图-01-revision01.txt", "仅修正英文文字，保持产品不变")
        revision_path = self.job_temp_dir / "定制沙发坐垫_副图_01_revision01.png"

        with self.assertRaisesRegex(tracker.TrackerError, "父级"):
            tracker.capture_artifact(**self.capture_kwargs(
                source=source,
                destination=revision_path,
                prompt_path=prompt,
                attempt_no=4,
                direct_index=None,
                artifact_kind="revision",
            ))

        revision = self.capture_and_archive(tracker, **self.capture_kwargs(
            source=source,
            destination=revision_path,
            prompt_path=prompt,
            attempt_no=4,
            direct_index=None,
            artifact_kind="revision",
            parent_artifact_id=direct_records[0]["artifact_id"],
        ))
        self.assertEqual(revision["derived_from_artifact_id"], direct_records[0]["artifact_id"])

        final_path = self.final_dir / "定制沙发坐垫_副图_01_v01.png"
        final_record = tracker.finalize_artifact(
            manifest_path=self.manifest,
            source_artifact_id=revision["artifact_id"],
            destination=final_path,
        )
        self.assertEqual(final_record["derived_from_artifact_id"], revision["artifact_id"])
        self.record_final_inspection(final_record)
        self.assertTrue(tracker.verify_manifest(self.manifest)["ok"])

    def test_revision_accepts_only_text_failed_rejected_parent(self) -> None:
        tracker = self.tracker()
        self.create_three_directs(tracker)
        bad_text_source = self.png(self.source_dir / "错字直出.png", (1024, 1024), (10, 20, 30))
        bad_text_prompt = self.prompt("副图-01-p04.txt", "带错字的直出")
        text_checks = dict(VISUAL_CHECKS_OK)
        text_checks["text_correct"] = False
        rejected = tracker.capture_artifact(**self.capture_kwargs(
            source=bad_text_source,
            destination=self.rejected_dir / "定制沙发坐垫_副图_01_attempt04_rejected.png",
            prompt_path=bad_text_prompt,
            attempt_no=4,
            direct_index=None,
            status="rejected",
            visual_checks=text_checks,
            rejection_reason="英文标题拼写错误",
        ))

        revision_source = self.png(self.source_dir / "渠道修正错字.png", (1024, 1024), (20, 30, 40))
        revision_prompt = self.prompt("副图-01-revision01.txt", "仅修正英文标题")
        revision = tracker.capture_artifact(**self.capture_kwargs(
            source=revision_source,
            destination=self.job_temp_dir / "定制沙发坐垫_副图_01_revision01.png",
            prompt_path=revision_prompt,
            attempt_no=5,
            direct_index=None,
            artifact_kind="revision",
            parent_artifact_id=rejected["artifact_id"],
        ))
        self.assertEqual(revision["derived_from_artifact_id"], rejected["artifact_id"])

        wrong_product_source = self.png(self.source_dir / "产品错误.png", (1024, 1024), (50, 60, 70))
        wrong_product_prompt = self.prompt("副图-01-p06.txt", "产品错误的直出")
        product_checks = dict(VISUAL_CHECKS_OK)
        product_checks["product_preserved"] = False
        other_rejected = tracker.capture_artifact(**self.capture_kwargs(
            source=wrong_product_source,
            destination=self.rejected_dir / "定制沙发坐垫_副图_01_attempt06_rejected.png",
            prompt_path=wrong_product_prompt,
            attempt_no=6,
            direct_index=None,
            status="rejected",
            visual_checks=product_checks,
            rejection_reason="产品结构发生变化",
        ))
        another_revision_source = self.png(self.source_dir / "不合法修订.png", (1024, 1024), (80, 90, 100))
        another_revision_prompt = self.prompt("副图-01-revision02.txt", "试图修订产品错误")
        with self.assertRaisesRegex(tracker.TrackerError, "仅文字"):
            tracker.capture_artifact(**self.capture_kwargs(
                source=another_revision_source,
                destination=self.job_temp_dir / "定制沙发坐垫_副图_01_revision02.png",
                prompt_path=another_revision_prompt,
                attempt_no=7,
                direct_index=None,
                artifact_kind="revision",
                parent_artifact_id=other_rejected["artifact_id"],
            ))

    def test_revision_requires_three_valid_directs_first(self) -> None:
        tracker = self.tracker()
        bad_text_source = self.png(self.source_dir / "先修订的错字图.png", (1024, 1024), (10, 20, 30))
        bad_text_prompt = self.prompt("副图-01-p01.txt", "带错字的直出")
        checks = dict(VISUAL_CHECKS_OK)
        checks["text_correct"] = False
        rejected = tracker.capture_artifact(**self.capture_kwargs(
            source=bad_text_source,
            destination=self.rejected_dir / "定制沙发坐垫_副图_01_attempt01_rejected.png",
            prompt_path=bad_text_prompt,
            direct_index=None,
            status="rejected",
            visual_checks=checks,
            rejection_reason="英文标题拼写错误",
        ))
        revision_source = self.png(self.source_dir / "过早修订.png", (1024, 1024), (20, 30, 40))
        revision_prompt = self.prompt("副图-01-revision01.txt", "仅修正英文标题")

        with self.assertRaisesRegex(tracker.TrackerError, "三个有效直出|三版"):
            tracker.capture_artifact(**self.capture_kwargs(
                source=revision_source,
                destination=self.job_temp_dir / "定制沙发坐垫_副图_01_revision01.png",
                prompt_path=revision_prompt,
                attempt_no=2,
                direct_index=None,
                artifact_kind="revision",
                parent_artifact_id=rejected["artifact_id"],
            ))

    def test_text_failed_revision_parent_must_be_square_png_and_intact(self) -> None:
        tracker = self.tracker()
        self.create_three_directs(tracker)
        non_square = self.png(self.source_dir / "非正方形错字.png", (1200, 800), (10, 20, 30))
        prompt = self.prompt("副图-01-p04.txt", "非正方形错字")
        checks = dict(VISUAL_CHECKS_OK)
        checks["text_correct"] = False
        rejected = tracker.capture_artifact(**self.capture_kwargs(
            source=non_square,
            destination=self.rejected_dir / "定制沙发坐垫_副图_01_attempt04_rejected.png",
            prompt_path=prompt,
            attempt_no=4,
            direct_index=None,
            status="rejected",
            visual_checks=checks,
            rejection_reason="只有文字错误但画布非正方形",
        ))
        revision_source = self.png(self.source_dir / "修订.png", (1024, 1024), (40, 50, 60))
        revision_prompt = self.prompt("副图-01-revision01.txt", "修正文字")
        with self.assertRaisesRegex(tracker.TrackerError, "仅文字"):
            tracker.capture_artifact(**self.capture_kwargs(
                source=revision_source,
                destination=self.job_temp_dir / "定制沙发坐垫_副图_01_revision01.png",
                prompt_path=revision_prompt,
                attempt_no=5,
                direct_index=None,
                artifact_kind="revision",
                parent_artifact_id=rejected["artifact_id"],
            ))

    def test_verify_rejects_missing_fields_unknown_values_and_broken_lineage(self) -> None:
        tracker = self.tracker()
        records = self.create_three_directs(tracker)
        final = tracker.finalize_artifact(
            manifest_path=self.manifest,
            source_artifact_id=records[0]["artifact_id"],
            destination=self.final_dir / "定制沙发坐垫_副图_01_v01.png",
        )
        manifest_records = self.read_manifest()
        del manifest_records[0]["provider"]
        manifest_records[1]["artifact_kind"] = "unknown"
        manifest_records[2]["status"] = "unknown"
        manifest_records[-1]["task_id"] = "另一个任务"
        manifest_records[-1]["source_sha256"] = "0" * 64
        self.manifest.write_text(
            "\n".join(json.dumps(item, ensure_ascii=False) for item in manifest_records) + "\n",
            encoding="utf-8",
        )

        report = tracker.verify_manifest(self.manifest)

        self.assertFalse(report["ok"])
        combined = "\n".join(report["errors"])
        self.assertIn("缺少必填字段", combined)
        self.assertIn("未知产物类型", combined)
        self.assertIn("未知验收状态", combined)
        self.assertIn("派生关系", combined)
        self.assertIn(final["artifact_id"], combined)

    def test_verify_rejects_wrong_name_non_png_and_broken_copy_hash(self) -> None:
        tracker = self.tracker()
        records = self.create_three_directs(tracker)
        tracker.finalize_artifact(
            manifest_path=self.manifest,
            source_artifact_id=records[0]["artifact_id"],
            destination=self.final_dir / "定制沙发坐垫_副图_01_v01.png",
        )
        manifest_records = self.read_manifest()
        original_target = Path(manifest_records[0]["target_path"])
        wrong_target = original_target.with_name("随意文件名.png")
        Image.new("RGB", (1024, 1024), (111, 112, 113)).save(wrong_target, format="JPEG")
        original_target.unlink()
        manifest_records[0]["target_path"] = str(wrong_target.resolve())
        manifest_records[0]["target_sha256"] = self.sha256(wrong_target)
        self.manifest.write_text(
            "\n".join(json.dumps(item, ensure_ascii=False) for item in manifest_records) + "\n",
            encoding="utf-8",
        )

        report = tracker.verify_manifest(self.manifest)

        self.assertFalse(report["ok"])
        combined = "\n".join(report["errors"])
        self.assertIn("命名", combined)
        self.assertIn("PNG", combined)
        self.assertIn("来源与目标哈希不一致", combined)

    def test_verify_rejects_invalid_artifact_state_machine(self) -> None:
        tracker = self.tracker()
        records = self.create_three_directs(tracker)
        tracker.finalize_artifact(
            manifest_path=self.manifest,
            source_artifact_id=records[0]["artifact_id"],
            destination=self.final_dir / "定制沙发坐垫_副图_01_v01.png",
        )
        manifest_records = self.read_manifest()
        manifest_records[0]["derived_from_artifact_id"] = records[1]["artifact_id"]
        manifest_records[-1]["provenance_mode"] = "tool_return"
        manifest_records[-1]["direct_index"] = 1
        self.manifest.write_text(
            "\n".join(json.dumps(item, ensure_ascii=False) for item in manifest_records) + "\n",
            encoding="utf-8",
        )

        report = tracker.verify_manifest(self.manifest)
        combined = "\n".join(report["errors"])
        self.assertFalse(report["ok"])
        self.assertIn("状态机", combined)
        self.assertIn("来源模式", combined)

    def test_两图任务只有一图完整时仍报告全部缺失产物(self) -> None:
        tracker = self.tracker()
        job = self.read_job()
        second = json.loads(json.dumps(job["images"][0], ensure_ascii=False))
        second["image_id"] = "副图-02"
        second["target_paths"]["final_stem"] = "定制沙发坐垫_副图_02"
        second["session"]["session_id"] = "session-副图-02"
        second["session"]["view_events"][0]["session_id"] = "session-副图-02"
        second["execution"] = {"status": "generating", "attempts": [], "final_inspections": []}
        job["images"].append(second)
        job["material_inventory"]["required"]["output_types"]["image_ids"].append("副图-02")
        job["references"][0]["applies_to"].append("副图-02")
        self.write_job_data(job, refresh_scope=True)
        records = self.create_three_directs(tracker)
        final = tracker.finalize_artifact(
            manifest_path=self.manifest,
            source_artifact_id=records[0]["artifact_id"],
            destination=self.final_dir / "定制沙发坐垫_副图_01_v01.png",
        )
        self.record_final_inspection(final)

        report = tracker.verify_manifest(self.manifest)

        combined = "\n".join(report["errors"])
        self.assertFalse(report["ok"])
        for expected in ("图号 副图-02", "direct01", "direct02", "direct03", "缺少最终图"):
            self.assertIn(expected, combined)

    def test_已有产物后新增图号时capture要求新task(self) -> None:
        tracker = self.tracker()
        source1 = self.png(self.source_dir / "身份图一.png", (1024, 1024), (10, 20, 30))
        prompt1 = self.prompt("副图-01-p01.txt", "建立首条身份记录")
        self.capture_and_archive(tracker, **self.capture_kwargs(
            source=source1,
            destination=self.direct_dir / "定制沙发坐垫_副图_01_direct01.png",
            prompt_path=prompt1,
        ))
        job = self.read_job()
        second = json.loads(json.dumps(job["images"][0], ensure_ascii=False))
        second["image_id"] = "副图-02"
        second["target_paths"]["final_stem"] = "定制沙发坐垫_副图_02"
        second["session"]["session_id"] = "session-副图-02"
        second["session"]["view_events"][0]["session_id"] = "session-副图-02"
        second["execution"] = {"status": "generating", "attempts": [], "final_inspections": []}
        job["images"].append(second)
        job["material_inventory"]["required"]["output_types"]["image_ids"].append("副图-02")
        job["references"][0]["applies_to"].append("副图-02")
        job["approval"]["scope_version"] = 2
        self.write_job_data(job, refresh_scope=True)
        source2 = self.png(self.source_dir / "身份图二.png", (1024, 1024), (40, 50, 60))
        prompt2 = self.prompt("副图-01-p02.txt", "原任务新增图号后的调用")
        destination = self.direct_dir / "定制沙发坐垫_副图_01_direct02.png"

        with self.assertRaisesRegex(tracker.TrackerError, "不可变任务身份.*新 task.*独立输出"):
            tracker.capture_artifact(**self.capture_kwargs(
                source=source2,
                destination=destination,
                prompt_path=prompt2,
                attempt_no=2,
                direct_index=2,
            ))
        self.assertFalse(destination.exists())

    def test_job身份与历史清单身份不一致时verify失败(self) -> None:
        tracker = self.tracker()
        source = self.png(self.source_dir / "身份校验.png", (1024, 1024), (10, 20, 30))
        prompt = self.prompt("副图-01-p01.txt", "建立身份校验记录")
        self.capture_and_archive(tracker, **self.capture_kwargs(
            source=source,
            destination=self.direct_dir / "定制沙发坐垫_副图_01_direct01.png",
            prompt_path=prompt,
        ))
        job = self.read_job()
        second = json.loads(json.dumps(job["images"][0], ensure_ascii=False))
        second["image_id"] = "副图-02"
        second["target_paths"]["final_stem"] = "定制沙发坐垫_副图_02"
        second["session"]["session_id"] = "session-副图-02"
        second["session"]["view_events"][0]["session_id"] = "session-副图-02"
        second["execution"] = {"status": "generating", "attempts": [], "final_inspections": []}
        job["images"].append(second)
        job["material_inventory"]["required"]["output_types"]["image_ids"].append("副图-02")
        job["references"][0]["applies_to"].append("副图-02")
        job["approval"]["scope_version"] = 2
        self.write_job_data(job, refresh_scope=True)

        report = tracker.verify_manifest(self.manifest)

        self.assertFalse(report["ok"])
        self.assertRegex("\n".join(report["errors"]), "不可变任务身份.*新 task.*独立输出")

    def test_新task不能复用旧输出根和清单(self) -> None:
        tracker = self.tracker()
        old_source = self.png(self.source_dir / "旧任务身份.png", (1024, 1024), (10, 20, 30))
        old_prompt = self.prompt("副图-01-p01.txt", "建立旧任务身份")
        self.capture_and_archive(tracker, **self.capture_kwargs(
            source=old_source,
            destination=self.direct_dir / "定制沙发坐垫_副图_01_direct01.png",
            prompt_path=old_prompt,
        ))
        old_records = self.read_manifest()

        new_task_id = "temu-20260721-新任务"
        new_job = self.read_job()
        new_job["task_id"] = new_task_id
        new_job["images"][0]["execution"] = {
            "status": "generating", "attempts": [], "final_inspections": [],
        }
        new_task_dir = self.root / "output" / "temp" / new_task_id
        new_image_dir = new_task_dir / "副图-01"
        new_image_dir.mkdir(parents=True)
        new_job_path = new_task_dir / "_temu_job.json"
        new_job_path.write_text(json.dumps(new_job, ensure_ascii=False, indent=2), encoding="utf-8")
        new_prompt = new_image_dir / "副图-01-p02.txt"
        new_prompt.write_text("新任务尝试复用旧清单", encoding="utf-8")
        new_snapshot = new_image_dir / "调用前快照.json"
        tracker.write_snapshot(self.source_dir, new_snapshot)
        new_source = self.png(self.source_dir / "新任务身份.png", (1024, 1024), (40, 50, 60))
        destination = self.direct_dir / "定制沙发坐垫_副图_01_direct02.png"
        kwargs = self.capture_kwargs(
            source=new_source,
            destination=destination,
            prompt_path=new_prompt,
            snapshot_path=new_snapshot,
            attempt_no=2,
            direct_index=2,
        )
        kwargs["task_id"] = new_task_id

        capture_error = None
        with mock.patch.object(tracker, "_copy_exclusive", wraps=tracker._copy_exclusive) as copy_exclusive:
            try:
                tracker.capture_artifact(**kwargs)
            except tracker.TrackerError as error:
                capture_error = str(error)
        capture_called_copy = copy_exclusive.called
        destination_existed_after_capture = destination.exists()
        manifest_count_after_capture = len(self.read_manifest())

        if destination.exists():
            destination.unlink()
        self.manifest.write_text(
            "\n".join(json.dumps(item, ensure_ascii=False) for item in old_records) + "\n",
            encoding="utf-8",
        )
        manual_new_identity = json.loads(json.dumps(old_records[0], ensure_ascii=False))
        manual_new_identity["artifact_id"] = "manual-new-task-record"
        manual_new_identity["task_id"] = new_task_id
        manual_new_identity["immutable_identity_sha256"] = tracker._immutable_identity_sha256(new_job)
        self.manifest.write_text(
            "\n".join(
                json.dumps(item, ensure_ascii=False)
                for item in [*old_records, manual_new_identity]
            ) + "\n",
            encoding="utf-8",
        )
        report = tracker.verify_manifest(self.manifest)
        verify_errors = "\n".join(report["errors"])

        failures = []
        if capture_error is None or not all(
            text in capture_error for text in ("不可变任务身份", "独立输出根目录和清单")
        ):
            failures.append(f"capture 未报身份隔离错误：{capture_error!r}")
        if capture_called_copy:
            failures.append("capture 在身份隔离失败前已尝试复制")
        if destination_existed_after_capture:
            failures.append("capture 失败后目标仍存在")
        if manifest_count_after_capture != len(old_records):
            failures.append("capture 失败后清单行数发生变化")
        if report["ok"] or not all(
            text in verify_errors for text in ("不可变任务身份", "独立输出根目录和清单")
        ):
            failures.append(f"verify 未报多身份隔离错误：{verify_errors}")
        self.assertEqual(failures, [], "\n".join(failures))

    def test_capture拒绝未来调用时间且不落盘(self) -> None:
        tracker = self.tracker()
        source = self.png(self.source_dir / "未来调用.png", (1024, 1024), (10, 20, 30))
        prompt = self.prompt("副图-01-p01.txt", "未来调用时间测试")
        destination = self.direct_dir / "定制沙发坐垫_副图_01_direct01.png"

        with self.assertRaisesRegex(tracker.TrackerError, "调用开始时间.*不能晚于.*捕获时间"):
            tracker.capture_artifact(**self.capture_kwargs(
                source=source,
                destination=destination,
                prompt_path=prompt,
                call_started_at="2999-01-01T00:00:00+00:00",
            ))
        self.assertFalse(destination.exists())
        self.assertFalse(self.manifest.exists())

    def test_capture拒绝纯空白prompt_id且不落盘(self) -> None:
        tracker = self.tracker()
        source = self.png(self.source_dir / "空白提示词编号.png", (1024, 1024), (10, 20, 30))
        prompt = self.prompt("副图-01-p01.txt", "空白提示词编号测试")
        destination = self.direct_dir / "定制沙发坐垫_副图_01_direct01.png"
        kwargs = self.capture_kwargs(source=source, destination=destination, prompt_path=prompt)
        kwargs["prompt_id"] = " \t "

        with self.assertRaisesRegex(tracker.TrackerError, "prompt_id.*去空白.*非空字符串"):
            tracker.capture_artifact(**kwargs)
        self.assertFalse(destination.exists())
        self.assertFalse(self.manifest.exists())

    def test_历史attempt不受当前引用和Session变化误伤(self) -> None:
        tracker = self.tracker()
        old_directs = self.create_three_directs(tracker)
        tracker.finalize_artifact(
            manifest_path=self.manifest,
            source_artifact_id=old_directs[0]["artifact_id"],
            destination=self.final_dir / "定制沙发坐垫_副图_01_v01.png",
        )
        job = self.read_job()
        old_attempts = json.loads(json.dumps(job["images"][0]["execution"]["attempts"], ensure_ascii=False))
        job["approval"]["scope_version"] = 2
        layout_evidence = self.png(
            self.evidence_dir / "新版式.png",
            (1200, 1200),
            (120, 130, 140),
        )
        layout_view = {
            "status": "completed",
            "inspection_session_id": "inspection-素材-02",
            "checked_at": "2026-07-21T09:00:00+00:00",
            "notes": "已确认新版式只提供信息组织依据",
        }
        job["evidence_sources"].append({
            "evidence_id": "layout-02",
            "kind": "layout_reference",
            "media_type": "image",
            "path": str(layout_evidence.resolve()),
            "sha256": self.sha256(layout_evidence),
            "view_image": layout_view,
        })
        job["material_inventory"]["conditional"]["layout_scene_reference"] = {
            "status": "available", "evidence_ids": ["layout-02"],
        }
        job["references"].append({
            "reference_id": "ref-layout-02",
            "evidence_id": "layout-02",
            "path": str(layout_evidence.resolve()),
            "role": "layout",
            "applies_to": ["副图-01"],
            "source_location": None,
            "view_image": layout_view,
        })
        image = job["images"][0]
        image["reference_ids"] = ["ref-product-01", "ref-layout-02"]
        image["session"] = {
            "status": "generating",
            "session_id": "session-副图-01-scope02",
            "view_events": [
                {
                    "session_id": "session-副图-01-scope02",
                    "reference_id": "ref-product-01",
                    "image_label": "Image 1",
                    "checked_at": "2026-07-21T09:01:00+00:00",
                    "notes": "新 Session 重新查看产品输入",
                },
                {
                    "session_id": "session-副图-01-scope02",
                    "reference_id": "ref-layout-02",
                    "image_label": "Image 2",
                    "checked_at": "2026-07-21T09:02:00+00:00",
                    "notes": "新 Session 查看新版式输入",
                },
            ],
        }
        image["execution"]["status"] = "generating"
        self.write_job_data(job, refresh_scope=True)

        replacements = []
        for attempt_no, (direct_index, old_record) in enumerate(enumerate(old_directs, start=1), start=4):
            source = self.png(
                self.source_dir / f"引用变化替换{direct_index}.png",
                (1024, 1024),
                (120 + direct_index, 130 + direct_index, 140 + direct_index),
            )
            prompt = self.prompt(
                f"副图-01-scope02-ref-p{attempt_no:02d}.txt",
                f"使用新 layout 引用的第 {direct_index} 版替换提示词",
            )
            replacements.append(self.capture_and_archive(tracker, **self.capture_kwargs(
                source=source,
                destination=self.direct_dir /
                f"定制沙发坐垫_副图_01_direct{direct_index:02d}_replacement{attempt_no:02d}.png",
                prompt_path=prompt,
                attempt_no=attempt_no,
                direct_index=direct_index,
                supersedes_artifact_id=old_record["artifact_id"],
                supersession_reason="范围二合法新增 layout 引用并更换 Session",
            )))
        final = tracker.finalize_artifact(
            manifest_path=self.manifest,
            source_artifact_id=replacements[0]["artifact_id"],
            destination=self.final_dir / "定制沙发坐垫_副图_01_v02.png",
        )
        self.record_final_inspection(final)
        report = tracker.verify_manifest(self.manifest)

        self.assertTrue(report["ok"], "\n".join(report["errors"]))
        self.assertEqual(self.read_job()["images"][0]["execution"]["attempts"][:3], old_attempts)

    def test_capture拒绝accepted携带拒绝原因且不落盘(self) -> None:
        tracker = self.tracker()
        source = self.png(self.source_dir / "accepted拒绝原因.png", (1024, 1024), (10, 20, 30))
        prompt = self.prompt("副图-01-p01.txt", "accepted 拒绝原因测试")
        destination = self.direct_dir / "定制沙发坐垫_副图_01_direct01.png"

        with self.assertRaisesRegex(tracker.TrackerError, "accepted.*拒绝原因.*null"):
            tracker.capture_artifact(**self.capture_kwargs(
                source=source, destination=destination, prompt_path=prompt,
                rejection_reason="不应写入",
            ))
        self.assertFalse(destination.exists())
        self.assertFalse(self.manifest.exists())

    def test_capture拒绝rejected空白原因且不落盘(self) -> None:
        tracker = self.tracker()
        source = self.png(self.source_dir / "rejected空白原因.png", (1024, 1024), (10, 20, 30))
        prompt = self.prompt("副图-01-p01.txt", "rejected 空白原因测试")
        destination = self.rejected_dir / "定制沙发坐垫_副图_01_attempt01_rejected.png"
        checks = dict(VISUAL_CHECKS_OK)
        checks["text_correct"] = False

        with self.assertRaisesRegex(tracker.TrackerError, "rejected.*拒绝原因.*非空"):
            tracker.capture_artifact(**self.capture_kwargs(
                source=source, destination=destination, prompt_path=prompt,
                direct_index=None, status="rejected", visual_checks=checks,
                rejection_reason="   ",
            ))
        self.assertFalse(destination.exists())
        self.assertFalse(self.manifest.exists())

    def test_capture拒绝rejected视觉检查缺键且不落盘(self) -> None:
        tracker = self.tracker()
        source = self.png(self.source_dir / "rejected缺键.png", (1024, 1024), (10, 20, 30))
        prompt = self.prompt("副图-01-p01.txt", "rejected 缺键测试")
        destination = self.rejected_dir / "定制沙发坐垫_副图_01_attempt01_rejected.png"
        checks = dict(VISUAL_CHECKS_OK)
        del checks["text_correct"]

        with self.assertRaisesRegex(tracker.TrackerError, "visual_checks.*七个必需键"):
            tracker.capture_artifact(**self.capture_kwargs(
                source=source, destination=destination, prompt_path=prompt,
                direct_index=None, status="rejected", visual_checks=checks,
                rejection_reason="文字检查缺失",
            ))
        self.assertFalse(destination.exists())
        self.assertFalse(self.manifest.exists())

    def test_capture拒绝rejected视觉检查非布尔且不落盘(self) -> None:
        tracker = self.tracker()
        source = self.png(self.source_dir / "rejected非布尔.png", (1024, 1024), (10, 20, 30))
        prompt = self.prompt("副图-01-p01.txt", "rejected 非布尔测试")
        destination = self.rejected_dir / "定制沙发坐垫_副图_01_attempt01_rejected.png"
        checks = dict(VISUAL_CHECKS_OK)
        checks["text_correct"] = 0

        with self.assertRaisesRegex(tracker.TrackerError, "visual_checks.*严格布尔"):
            tracker.capture_artifact(**self.capture_kwargs(
                source=source, destination=destination, prompt_path=prompt,
                direct_index=None, status="rejected", visual_checks=checks,
                rejection_reason="文字检查失败",
            ))
        self.assertFalse(destination.exists())
        self.assertFalse(self.manifest.exists())

    def test_capture拒绝rejected视觉检查全true且不落盘(self) -> None:
        tracker = self.tracker()
        source = self.png(self.source_dir / "rejected全通过.png", (1024, 1024), (10, 20, 30))
        prompt = self.prompt("副图-01-p01.txt", "rejected 全通过测试")
        destination = self.rejected_dir / "定制沙发坐垫_副图_01_attempt01_rejected.png"

        with self.assertRaisesRegex(tracker.TrackerError, "rejected.*至少一项为 false"):
            tracker.capture_artifact(**self.capture_kwargs(
                source=source, destination=destination, prompt_path=prompt,
                direct_index=None, status="rejected", visual_checks=dict(VISUAL_CHECKS_OK),
                rejection_reason="状态与检查矛盾",
            ))
        self.assertFalse(destination.exists())
        self.assertFalse(self.manifest.exists())

    def test_verify拒绝direct_index布尔值冒充整数(self) -> None:
        tracker = self.tracker()
        records = self.create_three_directs(tracker)
        tracker.finalize_artifact(
            manifest_path=self.manifest,
            source_artifact_id=records[0]["artifact_id"],
            destination=self.final_dir / "定制沙发坐垫_副图_01_v01.png",
        )
        manifest_records = self.read_manifest()
        manifest_records[0]["direct_index"] = True
        self.manifest.write_text(
            "\n".join(json.dumps(item, ensure_ascii=False) for item in manifest_records) + "\n",
            encoding="utf-8",
        )

        report = tracker.verify_manifest(self.manifest)

        self.assertFalse(report["ok"])
        self.assertIn("direct_index 必须是整数 1、2 或 3", "\n".join(report["errors"]))

    def test_finalize在清单三版但attempts为空时失败且不落盘(self) -> None:
        tracker = self.tracker()
        records = self.create_three_directs(tracker)
        job = self.read_job()
        job["images"][0]["execution"]["attempts"] = []
        self.write_job_data(job)
        destination = self.final_dir / "定制沙发坐垫_副图_01_v01.png"

        with self.assertRaisesRegex(tracker.TrackerError, "attempt|尝试.*对账|对账.*尝试"):
            tracker.finalize_artifact(
                manifest_path=self.manifest,
                source_artifact_id=records[0]["artifact_id"],
                destination=destination,
            )
        self.assertFalse(destination.exists())

    def test_伪造引用会被阻塞(self) -> None:
        tracker = self.tracker()
        job = self.read_job()
        job["images"][0]["reference_ids"] = ["ref-fake"]
        self.write_job_data(job, refresh_scope=True)
        source = self.png(self.source_dir / "伪造引用.png", (1024, 1024), (10, 20, 30))
        prompt = self.prompt("副图-01-p01.txt", "伪造引用测试")

        with self.assertRaisesRegex(tracker.TrackerError, "引用.*不存在"):
            tracker.capture_artifact(**self.capture_kwargs(
                source=source,
                destination=self.direct_dir / "定制沙发坐垫_副图_01_direct01.png",
                prompt_path=prompt,
            ))

    def test_重复引用编号会被阻塞(self) -> None:
        tracker = self.tracker()
        job = self.read_job()
        duplicate = json.loads(json.dumps(job["references"][0], ensure_ascii=False))
        job["references"].append(duplicate)
        self.write_job_data(job, refresh_scope=True)
        source = self.png(self.source_dir / "重复引用.png", (1024, 1024), (10, 20, 30))
        prompt = self.prompt("副图-01-p01.txt", "重复引用编号测试")

        with self.assertRaisesRegex(tracker.TrackerError, "reference_id.*唯一"):
            tracker.capture_artifact(**self.capture_kwargs(
                source=source,
                destination=self.direct_dir / "定制沙发坐垫_副图_01_direct01.png",
                prompt_path=prompt,
            ))

    def test_非法引用角色会被阻塞(self) -> None:
        tracker = self.tracker()
        job = self.read_job()
        job["references"][0]["role"] = "伪造角色"
        self.write_job_data(job, refresh_scope=True)
        source = self.png(self.source_dir / "错误角色.png", (1024, 1024), (10, 20, 30))
        prompt = self.prompt("副图-01-p01.txt", "错误角色测试")

        with self.assertRaisesRegex(tracker.TrackerError, "角色不在契约枚举"):
            tracker.capture_artifact(**self.capture_kwargs(
                source=source,
                destination=self.direct_dir / "定制沙发坐垫_副图_01_direct01.png",
                prompt_path=prompt,
            ))

    def test_引用适用图号不包含当前图号会被阻塞(self) -> None:
        tracker = self.tracker()
        job = self.read_job()
        job["references"][0]["applies_to"] = ["副图-02"]
        self.write_job_data(job, refresh_scope=True)
        source = self.png(self.source_dir / "错误适用图号.png", (1024, 1024), (10, 20, 30))
        prompt = self.prompt("副图-01-p01.txt", "错误适用图号测试")

        with self.assertRaisesRegex(tracker.TrackerError, "适用图号不包含当前图号"):
            tracker.capture_artifact(**self.capture_kwargs(
                source=source,
                destination=self.direct_dir / "定制沙发坐垫_副图_01_direct01.png",
                prompt_path=prompt,
            ))

    def test_顶层查看记录缺少notes会被阻塞(self) -> None:
        tracker = self.tracker()
        job = self.read_job()
        job["references"][0]["view_image"]["notes"] = ""
        self.write_job_data(job)
        source = self.png(self.source_dir / "顶层备注缺失.png", (1024, 1024), (10, 20, 30))
        prompt = self.prompt("副图-01-p01.txt", "顶层查看备注测试")

        with self.assertRaisesRegex(tracker.TrackerError, "view_image.*notes"):
            tracker.capture_artifact(**self.capture_kwargs(
                source=source,
                destination=self.direct_dir / "定制沙发坐垫_副图_01_direct01.png",
                prompt_path=prompt,
            ))

    def test_当前子Session查看时间无时区会被阻塞(self) -> None:
        tracker = self.tracker()
        job = self.read_job()
        job["images"][0]["session"]["view_events"][0]["checked_at"] = "2026-07-21T08:02:00"
        self.write_job_data(job)
        source = self.png(self.source_dir / "Session时间无时区.png", (1024, 1024), (10, 20, 30))
        prompt = self.prompt("副图-01-p01.txt", "Session查看时间测试")

        with self.assertRaisesRegex(tracker.TrackerError, "查看记录 checked_at.*时区"):
            tracker.capture_artifact(**self.capture_kwargs(
                source=source,
                destination=self.direct_dir / "定制沙发坐垫_副图_01_direct01.png",
                prompt_path=prompt,
            ))

    def test_当前子Session查看记录缺少notes会被阻塞(self) -> None:
        tracker = self.tracker()
        job = self.read_job()
        job["images"][0]["session"]["view_events"][0]["notes"] = ""
        self.write_job_data(job)
        source = self.png(self.source_dir / "Session备注缺失.png", (1024, 1024), (10, 20, 30))
        prompt = self.prompt("副图-01-p01.txt", "Session查看备注测试")

        with self.assertRaisesRegex(tracker.TrackerError, "查看记录缺少 notes"):
            tracker.capture_artifact(**self.capture_kwargs(
                source=source,
                destination=self.direct_dir / "定制沙发坐垫_副图_01_direct01.png",
                prompt_path=prompt,
            ))

    def test_当前calling必须与实际调用参数完全一致(self) -> None:
        tracker = self.tracker()
        source = self.png(self.source_dir / "调用参数不一致.png", (1024, 1024), (10, 20, 30))
        prompt = self.prompt("副图-01-p01.txt", "真实调用提示词")
        kwargs = self.capture_kwargs(
            source=source,
            destination=self.direct_dir / "定制沙发坐垫_副图_01_direct01.png",
            prompt_path=prompt,
        )
        job = self.read_job()
        attempt = self.calling_attempt(kwargs)
        attempt["prompt_id"] = "伪造提示词编号"
        job["images"][0]["execution"]["attempts"] = [attempt]
        self.write_job_data(job)

        with self.assertRaisesRegex(tracker.TrackerError, "calling.*提示词|调用记录.*不一致"):
            tracker.capture_artifact(**kwargs)

    def test_execution尝试与清单必须双向唯一对账(self) -> None:
        tracker = self.tracker()
        records = self.create_three_directs(tracker)
        tracker.finalize_artifact(
            manifest_path=self.manifest,
            source_artifact_id=records[0]["artifact_id"],
            destination=self.final_dir / "定制沙发坐垫_副图_01_v01.png",
        )
        job = self.read_job()
        job["images"][0]["execution"]["attempts"][0]["artifact_id"] = "伪造产物编号"
        self.write_job_data(job)

        report = tracker.verify_manifest(self.manifest)

        self.assertFalse(report["ok"])
        self.assertRegex("\n".join(report["errors"]), "attempt|尝试.*清单|清单.*尝试")

    def test_execution尝试状态必须使用枚举(self) -> None:
        tracker = self.tracker()
        records = self.create_three_directs(tracker)
        tracker.finalize_artifact(
            manifest_path=self.manifest,
            source_artifact_id=records[0]["artifact_id"],
            destination=self.final_dir / "定制沙发坐垫_副图_01_v01.png",
        )
        job = self.read_job()
        job["images"][0]["execution"]["attempts"][0]["status"] = "complete"
        self.write_job_data(job)

        report = tracker.verify_manifest(self.manifest)

        self.assertFalse(report["ok"])
        self.assertIn("尝试状态不在契约枚举", "\n".join(report["errors"]))

    def test_已有产物时execution不能仍为planned(self) -> None:
        tracker = self.tracker()
        records = self.create_three_directs(tracker)
        tracker.finalize_artifact(
            manifest_path=self.manifest,
            source_artifact_id=records[0]["artifact_id"],
            destination=self.final_dir / "定制沙发坐垫_副图_01_v01.png",
        )
        job = self.read_job()
        job["images"][0]["execution"]["status"] = "planned"
        self.write_job_data(job)

        report = tracker.verify_manifest(self.manifest)

        self.assertFalse(report["ok"])
        self.assertIn("已有产物，execution.status 不能仍为 planned", "\n".join(report["errors"]))

    def test_calling存在时finalize和verify都失败(self) -> None:
        tracker = self.tracker()
        records = self.create_three_directs(tracker)
        prompt = self.prompt("副图-01-p04.txt", "尚未归档的第四次调用")
        kwargs = self.capture_kwargs(
            source=None,
            destination=self.direct_dir / "定制沙发坐垫_副图_01_direct01_replacement04.png",
            prompt_path=prompt,
            attempt_no=4,
            direct_index=1,
        )
        job = self.read_job()
        job["images"][0]["execution"]["attempts"].append(self.calling_attempt(kwargs))
        self.write_job_data(job)

        with self.assertRaisesRegex(tracker.TrackerError, "尚未归档"):
            tracker.finalize_artifact(
                manifest_path=self.manifest,
                source_artifact_id=records[0]["artifact_id"],
                destination=self.final_dir / "定制沙发坐垫_副图_01_v01.png",
            )
        report = tracker.verify_manifest(self.manifest)
        self.assertFalse(report["ok"])
        self.assertIn("尚未归档", "\n".join(report["errors"]))

    def test_删除inactive旧证据的来源或目标后verify失败(self) -> None:
        tracker = self.tracker()
        records = self.create_three_directs(tracker)
        old = records[1]
        self.png(Path(old["target_path"]), (1024, 1024), (1, 1, 1))
        source = self.png(self.source_dir / "replacement.png", (1024, 1024), (101, 102, 103))
        prompt = self.prompt("副图-01-p04.txt", "替换损坏的第二版")
        replacement = self.capture_and_archive(tracker, **self.capture_kwargs(
            source=source,
            destination=self.direct_dir / "定制沙发坐垫_副图_01_direct02_replacement04.png",
            prompt_path=prompt,
            attempt_no=4,
            direct_index=2,
            supersedes_artifact_id=old["artifact_id"],
            supersession_reason="原 direct02 后验损坏",
        ))
        tracker.finalize_artifact(
            manifest_path=self.manifest,
            source_artifact_id=replacement["artifact_id"],
            destination=self.final_dir / "定制沙发坐垫_副图_01_v01.png",
        )
        Path(old["target_path"]).unlink()
        Path(old["source_path"]).unlink()

        report = tracker.verify_manifest(self.manifest)

        self.assertFalse(report["ok"])
        combined = "\n".join(report["errors"])
        self.assertIn(old["artifact_id"], combined)
        self.assertIn("文件不存在", combined)

    def test_清单字段的Session时间拒绝原因和布尔检查必须合法(self) -> None:
        tracker = self.tracker()
        records = self.create_three_directs(tracker)
        tracker.finalize_artifact(
            manifest_path=self.manifest,
            source_artifact_id=records[0]["artifact_id"],
            destination=self.final_dir / "定制沙发坐垫_副图_01_v01.png",
        )
        manifest_records = self.read_manifest()
        manifest_records[0]["session_id"] = "伪造-session"
        manifest_records[0]["call_started_at"] = "2026-07-21T08:00:00"
        manifest_records[0]["captured_at"] = "2026-07-20T08:00:00+00:00"
        manifest_records[0]["rejection_reason"] = "不应存在"
        manifest_records[0]["visual_checks"]["text_correct"] = 1
        manifest_records[1]["prompt_sha256"] = "A" * 64
        manifest_records[2]["width"] = 0
        self.manifest.write_text(
            "\n".join(json.dumps(item, ensure_ascii=False) for item in manifest_records) + "\n",
            encoding="utf-8",
        )

        report = tracker.verify_manifest(self.manifest)

        combined = "\n".join(report["errors"])
        self.assertFalse(report["ok"])
        for expected in ("session_id", "时间", "拒绝原因", "布尔", "SHA256", "宽高"):
            self.assertIn(expected, combined)

    def test_首次finalize拒绝跳到v99(self) -> None:
        tracker = self.tracker()
        records = self.create_three_directs(tracker)

        with self.assertRaisesRegex(tracker.TrackerError, "v01|连续"):
            tracker.finalize_artifact(
                manifest_path=self.manifest,
                source_artifact_id=records[0]["artifact_id"],
                destination=self.final_dir / "定制沙发坐垫_副图_01_v99.png",
            )

    def test_verify识别人工篡改的final跳号(self) -> None:
        tracker = self.tracker()
        records = self.create_three_directs(tracker)
        final = tracker.finalize_artifact(
            manifest_path=self.manifest,
            source_artifact_id=records[0]["artifact_id"],
            destination=self.final_dir / "定制沙发坐垫_副图_01_v01.png",
        )
        wrong_path = Path(final["target_path"]).with_name("定制沙发坐垫_副图_01_v99.png")
        Path(final["target_path"]).rename(wrong_path)
        manifest_records = self.read_manifest()
        manifest_records[-1]["target_path"] = str(wrong_path.resolve())
        manifest_records[-1]["target_sha256"] = self.sha256(wrong_path)
        self.manifest.write_text(
            "\n".join(json.dumps(item, ensure_ascii=False) for item in manifest_records) + "\n",
            encoding="utf-8",
        )

        report = tracker.verify_manifest(self.manifest)

        self.assertFalse(report["ok"])
        self.assertRegex("\n".join(report["errors"]), "final.*连续|最终版本.*v01")

    def test_产物出现后改变图型会阻塞并要求新task(self) -> None:
        tracker = self.tracker()
        source1 = self.png(self.source_dir / "原图型.png", (1024, 1024), (10, 20, 30))
        prompt1 = self.prompt("副图-01-p01.txt", "原图型")
        tracker.capture_artifact(**self.capture_kwargs(
            source=source1,
            destination=self.direct_dir / "定制沙发坐垫_副图_01_direct01.png",
            prompt_path=prompt1,
        ))
        job = self.read_job()
        job["images"][0]["image_type"] = "主图"
        job["images"][0]["target_paths"]["final_stem"] = "定制沙发坐垫_主图_01"
        self.write_job_data(job, refresh_scope=True)
        source2 = self.png(self.source_dir / "新图型.png", (1024, 1024), (40, 50, 60))
        prompt2 = self.prompt("副图-01-p02.txt", "试图在原任务改变图型")
        kwargs = self.capture_kwargs(
            source=source2,
            destination=self.direct_dir / "定制沙发坐垫_主图_01_direct02.png",
            prompt_path=prompt2,
            attempt_no=2,
            direct_index=2,
        )
        kwargs["image_type"] = "主图"

        with self.assertRaisesRegex(tracker.TrackerError, "不可变任务身份.*新 task"):
            tracker.capture_artifact(**kwargs)

    def test_snapshot_scan_tolerates_file_disappearing_mid_scan(self) -> None:
        tracker = self.tracker()
        image = self.png(self.source_dir / "即将消失.png", (1024, 1024), (1, 2, 3))
        with mock.patch.object(tracker, "_sha256", side_effect=FileNotFoundError("模拟并发删除")):
            self.assertIsNone(tracker._image_state(image))

    def test_cli_help_and_errors_are_chinese(self) -> None:
        self.tracker()
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--help"],
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0)
        self.assertIn("TEMU 生图产物", result.stdout)
        self.assertIn("快照", result.stdout)
        self.assertIn("验收", result.stdout)
        self.assertIn("选项:", result.stdout)
        self.assertIn("显示本帮助并退出", result.stdout)
        self.assertNotIn("options:", result.stdout.lower())
        self.assertNotIn("show this help message", result.stdout.lower())

        no_site_help = subprocess.run(
            [sys.executable, "-S", str(SCRIPT_PATH), "--help"],
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )
        self.assertEqual(no_site_help.returncode, 0)
        self.assertIn("TEMU 生图产物", no_site_help.stdout)

        no_pillow = subprocess.run(
            [
                sys.executable, "-S", str(SCRIPT_PATH), "snapshot",
                "--source-dir", str(self.source_dir),
                "--snapshot-path", str(self.root / "无依赖快照.json"),
            ],
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )
        self.assertEqual(no_pillow.returncode, 2)
        self.assertIn("缺少 Pillow", no_pillow.stderr)
        self.assertNotIn("Traceback", no_pillow.stderr)

        invalid = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "不存在的命令"],
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(invalid.returncode, 0)
        self.assertIn("参数错误", invalid.stderr)
        self.assertNotIn("error:", invalid.stderr.lower())

        invalid_number = subprocess.run(
            [
                sys.executable, str(SCRIPT_PATH), "finalize",
                "--manifest", "x", "--source-artifact-id", "y",
                "--destination", "z", "--size", "abc",
            ],
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(invalid_number.returncode, 0)
        self.assertIn("整数值无效", invalid_number.stderr)
        self.assertNotIn("invalid int value", invalid_number.stderr.lower())

    def test_capture要求独立检查Subagent且失败不落盘(self) -> None:
        tracker = self.tracker()
        required = {"inspection_session_id", "inspection_checked_at", "inspection_notes"}
        self.assertTrue(
            required <= set(inspect.signature(tracker.capture_artifact).parameters),
            "capture 尚未定义独立检查 Subagent 参数",
        )
        source = self.png(self.source_dir / "待独立检查.png", (1024, 1024), (10, 20, 30))
        prompt = self.prompt("副图-01-独立检查.txt", "独立检查 Subagent 测试")
        destination = self.direct_dir / "定制沙发坐垫_副图_01_direct01.png"
        kwargs = self.capture_kwargs(source=source, destination=destination, prompt_path=prompt)
        kwargs["inspection_session_id"] = "session-副图-01"

        with self.assertRaisesRegex(tracker.TrackerError, "检查 Subagent.*生成 Session.*不同"):
            tracker.capture_artifact(**kwargs)

        self.assertFalse(destination.exists())
        self.assertFalse(self.manifest.exists())

    def test_capture记录独立检查身份并拒绝缺失检查结论(self) -> None:
        tracker = self.tracker()
        required = {"inspection_session_id", "inspection_checked_at", "inspection_notes"}
        self.assertTrue(required <= set(inspect.signature(tracker.capture_artifact).parameters))
        source = self.png(self.source_dir / "独立检查合格.png", (1024, 1024), (10, 20, 30))
        prompt = self.prompt("副图-01-检查合格.txt", "独立检查合格测试")
        destination = self.direct_dir / "定制沙发坐垫_副图_01_direct01.png"
        kwargs = self.capture_kwargs(source=source, destination=destination, prompt_path=prompt)
        kwargs["inspection_notes"] = "   "

        with self.assertRaisesRegex(tracker.TrackerError, "检查结论.*非空"):
            tracker.capture_artifact(**kwargs)
        self.assertFalse(destination.exists())

        kwargs["inspection_notes"] = "独立检查 Subagent 已确认七项检查"
        record = tracker.capture_artifact(**kwargs)
        self.assertEqual(record["inspection_session_id"], "inspection-产物-01")
        self.assertEqual(record["inspection_notes"], "独立检查 Subagent 已确认七项检查")

    def test_素材检查Subagent必须存在且不同于生成Session(self) -> None:
        tracker = self.tracker()
        required = {"inspection_session_id", "inspection_checked_at", "inspection_notes"}
        self.assertTrue(required <= set(inspect.signature(tracker.capture_artifact).parameters))
        source = self.png(self.source_dir / "素材检查.png", (1024, 1024), (10, 20, 30))
        prompt = self.prompt("副图-01-素材检查.txt", "素材检查 Subagent 测试")
        destination = self.direct_dir / "定制沙发坐垫_副图_01_direct01.png"
        job = self.read_job()
        job["references"][0]["view_image"].pop("inspection_session_id")
        self.write_job_data(job)
        kwargs = self.capture_kwargs(source=source, destination=destination, prompt_path=prompt)

        with self.assertRaisesRegex(tracker.TrackerError, "素材检查 Subagent"):
            tracker.capture_artifact(**kwargs)

        job = self.read_job()
        job["references"][0]["view_image"]["inspection_session_id"] = "session-副图-01"
        job["evidence_sources"][1]["view_image"]["inspection_session_id"] = "session-副图-01"
        self.write_job_data(job, refresh_scope=True)
        with self.assertRaisesRegex(tracker.TrackerError, "素材检查 Subagent.*生成 Session.*不同"):
            tracker.capture_artifact(**kwargs)

    def test_verify要求最终图独立检查Subagent(self) -> None:
        tracker = self.tracker()
        required = {"inspection_session_id", "inspection_checked_at", "inspection_notes"}
        self.assertTrue(required <= set(inspect.signature(tracker.capture_artifact).parameters))
        records = []
        for index, color in enumerate(((10, 20, 30), (40, 50, 60), (70, 80, 90)), start=1):
            source = self.png(self.source_dir / f"最终检查-{index}.png", (1024, 1024), color)
            prompt = self.prompt(f"最终检查-{index}.txt", f"最终检查提示词 {index}")
            records.append(self.capture_and_archive(tracker, **self.capture_kwargs(
                source=source,
                destination=self.direct_dir / f"定制沙发坐垫_副图_01_direct{index:02d}.png",
                prompt_path=prompt,
                attempt_no=index,
                direct_index=index,
            )))
        final = tracker.finalize_artifact(
            manifest_path=self.manifest,
            source_artifact_id=records[0]["artifact_id"],
            destination=self.final_dir / "定制沙发坐垫_副图_01_v01.png",
        )

        report = tracker.verify_manifest(self.manifest)
        self.assertFalse(report["ok"])
        self.assertRegex("\n".join(report["errors"]), "最终图.*独立检查 Subagent")

        self.record_final_inspection(final, session_id="session-副图-01")
        report = tracker.verify_manifest(self.manifest)
        self.assertFalse(report["ok"])
        self.assertRegex("\n".join(report["errors"]), "最终图.*检查 Subagent.*生成 Session.*不同")

        job = self.read_job()
        job["images"][0]["execution"]["final_inspections"] = []
        self.write_job_data(job)
        self.record_final_inspection(final, session_id="session-main-01")
        report = tracker.verify_manifest(self.manifest)
        self.assertFalse(report["ok"])
        self.assertRegex("\n".join(report["errors"]), "最终图.*检查 Subagent.*主 Session.*不同")

        job = self.read_job()
        job["images"][0]["execution"]["final_inspections"] = []
        self.write_job_data(job)
        self.record_final_inspection(final)
        report = tracker.verify_manifest(self.manifest)
        self.assertTrue(report["ok"], "\n".join(report["errors"]))

    def test_必需素材和条件性素材盘点必须进入任务契约(self) -> None:
        tracker = self.tracker()
        source = self.png(self.source_dir / "素材契约.png", (1024, 1024), (10, 20, 30))
        prompt = self.prompt("副图-01-素材契约.txt", "素材契约测试")
        destination = self.direct_dir / "定制沙发坐垫_副图_01_direct01.png"
        job = self.read_job()
        del job["material_inventory"]["required"]["real_dimensions"]
        self.write_job_data(job, refresh_scope=True)

        with self.assertRaisesRegex(tracker.TrackerError, "必需素材.*真实尺寸|真实尺寸.*必需素材"):
            tracker.capture_artifact(**self.capture_kwargs(
                source=source, destination=destination, prompt_path=prompt,
            ))

        job = self.write_job()
        job["material_inventory"]["conditional"]["vi_brand_guide"] = {
            "status": "available", "evidence_ids": [],
        }
        self.write_job_data(job, refresh_scope=True)
        with self.assertRaisesRegex(tracker.TrackerError, "条件性素材.*VI|VI.*证据"):
            tracker.capture_artifact(**self.capture_kwargs(
                source=source, destination=destination, prompt_path=prompt,
            ))

        job = self.write_job()
        job["product_baseline"]["dimensions_original"] = "   "
        self.write_job_data(job, refresh_scope=True)
        with self.assertRaisesRegex(tracker.TrackerError, "真实尺寸.*内容|dimensions_original"):
            tracker.capture_artifact(**self.capture_kwargs(
                source=source, destination=destination, prompt_path=prompt,
            ))

        self.write_job()
        self.requirements_evidence.write_bytes(b"tampered after approval")
        with self.assertRaisesRegex(tracker.TrackerError, "requirements-01.*哈希|哈希.*requirements-01"):
            tracker.capture_artifact(**self.capture_kwargs(
                source=source, destination=destination, prompt_path=prompt,
            ))

    def test_主Session不得冒充素材或产物检查Subagent(self) -> None:
        tracker = self.tracker()
        source = self.png(self.source_dir / "主Session代检.png", (1024, 1024), (10, 20, 30))
        prompt = self.prompt("副图-01-主Session代检.txt", "主 Session 代检测试")
        destination = self.direct_dir / "定制沙发坐垫_副图_01_direct01.png"
        kwargs = self.capture_kwargs(source=source, destination=destination, prompt_path=prompt)
        kwargs["inspection_session_id"] = "session-main-01"
        with self.assertRaisesRegex(tracker.TrackerError, "主 Session.*不得.*检查|检查 Subagent.*主 Session.*不同"):
            tracker.capture_artifact(**kwargs)

        job = self.read_job()
        job["references"][0]["view_image"]["inspection_session_id"] = "session-main-01"
        job["evidence_sources"][1]["view_image"]["inspection_session_id"] = "session-main-01"
        self.write_job_data(job, refresh_scope=True)
        kwargs["inspection_session_id"] = "inspection-产物-01"
        with self.assertRaisesRegex(tracker.TrackerError, "素材检查 Subagent.*主 Session.*不同"):
            tracker.capture_artifact(**kwargs)

    def test_verify拒绝同图多个当前合法final(self) -> None:
        tracker = self.tracker()
        records = self.create_three_directs(tracker)
        final1 = tracker.finalize_artifact(
            manifest_path=self.manifest,
            source_artifact_id=records[0]["artifact_id"],
            destination=self.final_dir / "定制沙发坐垫_副图_01_v01.png",
        )
        self.record_final_inspection(final1)
        final2 = tracker.finalize_artifact(
            manifest_path=self.manifest,
            source_artifact_id=records[1]["artifact_id"],
            destination=self.final_dir / "定制沙发坐垫_副图_01_v02.png",
        )
        self.record_final_inspection(final2, session_id="inspection-final-02")

        report = tracker.verify_manifest(self.manifest)
        self.assertFalse(report["ok"])
        self.assertRegex("\n".join(report["errors"]), "只能有一个.*最终图|多个.*最终图")


if __name__ == "__main__":
    unittest.main(verbosity=2)
