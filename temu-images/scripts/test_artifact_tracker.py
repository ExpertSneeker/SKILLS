from __future__ import annotations

import copy
import importlib.util
import inspect
import hashlib
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
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

CONCURRENCY_POLICY = {
    "scope": "cross_image_only",
    "max_calling_attempts": 3,
    "max_pending_attempts": 3,
    "parallel_provenance": "tool_return_only",
    "serial_fallback": "retry_after_drain",
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

    def image_temp_dir(self, image_id: str) -> Path:
        path = self.job_file.parent / image_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def prompt_for_image(self, image_id: str, attempt_no: int, content: str | None = None) -> Path:
        path = self.image_temp_dir(image_id) / f"{image_id}-p{attempt_no:02d}.txt"
        path.write_text(content or f"{image_id} 第 {attempt_no} 次提示词", encoding="utf-8")
        return path

    def fresh_snapshot_for_image(self, image_id: str, source_dir: Path | None = None) -> Path:
        self.snapshot_counter += 1
        directory = (source_dir or self.source_dir).resolve()
        directory.mkdir(parents=True, exist_ok=True)
        images = {}
        for candidate in directory.rglob("*"):
            if candidate.is_file() and candidate.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
                try:
                    with Image.open(candidate) as image:
                        images[str(candidate.resolve())] = {
                            "size": candidate.stat().st_size,
                            "mtime_ns": candidate.stat().st_mtime_ns,
                            "sha256": self.sha256(candidate),
                            "width": image.width,
                            "height": image.height,
                        }
                except OSError:
                    continue
        path = self.image_temp_dir(image_id) / f"调用快照-{self.snapshot_counter:03d}.json"
        payload = {
            "schema_version": 2,
            "source_dir": str(directory),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "files": sorted(images),
            "images": images,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def add_image(self, job: dict, image_id: str) -> dict:
        image = copy.deepcopy(job["images"][0])
        image["image_id"] = image_id
        image_number = image_id.rsplit("-", 1)[-1]
        image["target_paths"]["final_stem"] = f"{job['product_name']}_副图_{image_number}"
        image["session"]["session_id"] = f"session-{image_id}"
        for event in image["session"]["view_events"]:
            event["session_id"] = image["session"]["session_id"]
        image["execution"] = {
            "status": "generating",
            "attempts": [],
            "final_inspections": [],
        }
        job["images"].append(image)
        job["material_inventory"]["required"]["output_types"]["image_ids"].append(image_id)
        job["references"][0]["applies_to"].append(image_id)
        return image

    def write_job_v2(self, *additional_image_ids: str) -> dict:
        job = self.write_job()
        job["schema_version"] = 2
        job["concurrency_policy"] = copy.deepcopy(CONCURRENCY_POLICY)
        for image_id in additional_image_ids:
            self.add_image(job, image_id)
        self.write_job_data(job, refresh_scope=True)
        return job

    def reserve_kwargs(
        self, *, image_id: str = "副图-01", attempt_no: int = 1,
        dispatch_mode: str = "parallel", direct_index: int | None = 1,
        artifact_kind: str = "direct", prompt_path: Path | None = None,
        snapshot_path: Path | None = None, source_dir: Path | None = None,
    ) -> dict:
        prompt_path = prompt_path or self.prompt_for_image(image_id, attempt_no)
        snapshot_path = snapshot_path or self.fresh_snapshot_for_image(image_id, source_dir)
        result = {
            "job_path": self.job_file,
            "image_id": image_id,
            "attempt_no": attempt_no,
            "dispatch_mode": dispatch_mode,
            "artifact_kind": artifact_kind,
            "direct_index": direct_index,
            "prompt_id": f"{image_id}-p{attempt_no:02d}",
            "prompt_path": prompt_path,
            "source_dir": source_dir or self.source_dir,
            "snapshot_path": snapshot_path,
        }
        return result

    def find_attempt(self, image_id: str, attempt_no: int) -> dict:
        job = self.read_job()
        image = next(item for item in job["images"] if item["image_id"] == image_id)
        return next(item for item in image["execution"]["attempts"] if item["attempt_no"] == attempt_no)

    def require_api(self, tracker, *names: str) -> None:
        missing = [name for name in names if not hasattr(tracker, name)]
        self.assertEqual(missing, [], f"生产脚本尚未实现接口：{', '.join(missing)}")

    def capture_kwargs_v2(
        self, attempt: dict, *, image_id: str, destination: Path,
        status: str = "accepted", direct_index: int | None = 1,
        visual_checks: dict[str, bool] | None = None, rejection_reason: str | None = None,
    ) -> dict:
        kwargs = self.capture_kwargs(
            source=None,
            destination=destination,
            prompt_path=Path(attempt["prompt_path"]),
            attempt_no=attempt["attempt_no"],
            direct_index=direct_index,
            artifact_kind=attempt["artifact_kind"],
            status=status,
            visual_checks=visual_checks,
            rejection_reason=rejection_reason,
            snapshot_path=Path(attempt["snapshot_path"]),
            call_started_at=attempt["call_started_at"],
        )
        kwargs["image_id"] = image_id
        kwargs["prompt_id"] = attempt["prompt_id"]
        kwargs.pop("call_started_at")
        return kwargs

    def create_v2_direct(
        self, tracker, *, image_id: str = "副图-01", attempt_no: int = 1,
        direct_index: int = 1, color: tuple[int, int, int] = (10, 20, 30),
        dispatch_mode: str = "parallel",
    ) -> dict:
        self.require_api(tracker, "reserve_attempt", "stage_attempt")
        reserve = self.reserve_kwargs(
            image_id=image_id,
            attempt_no=attempt_no,
            direct_index=direct_index,
            dispatch_mode=dispatch_mode,
        )
        tracker.reserve_attempt(**reserve)
        source = self.png(
            self.source_dir / f"{image_id}-渠道返回-{attempt_no:02d}.png",
            (1024, 1024),
            color,
        )
        tracker.stage_attempt(
            job_path=self.job_file,
            image_id=image_id,
            attempt_no=attempt_no,
            source_path=source,
        )
        attempt = self.find_attempt(image_id, attempt_no)
        image_number = image_id.rsplit("-", 1)[-1]
        destination = self.direct_dir / (
            f"定制沙发坐垫_副图_{image_number}_direct{direct_index:02d}.png"
        )
        return tracker.capture_artifact(**self.capture_kwargs_v2(
            attempt,
            image_id=image_id,
            destination=destination,
            direct_index=direct_index,
        ))

    def prepare_v2_capture(self, tracker, *, color=(10, 20, 30)) -> tuple[dict, dict, Path]:
        self.write_job_v2()
        tracker.reserve_attempt(**self.reserve_kwargs())
        source = self.png(self.source_dir / "事务恢复来源.png", (1024, 1024), color)
        tracker.stage_attempt(
            job_path=self.job_file,
            image_id="副图-01",
            attempt_no=1,
            source_path=source,
        )
        attempt = copy.deepcopy(self.find_attempt("副图-01", 1))
        destination = self.direct_dir / "定制沙发坐垫_副图_01_direct01.png"
        kwargs = self.capture_kwargs_v2(
            attempt,
            image_id="副图-01",
            destination=destination,
        )
        return attempt, kwargs, destination

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

    def test_write_exclusive关闭前flush并fsync完整内容(self) -> None:
        tracker = self.tracker()
        target = self.root / "独占写刷新.bin"
        content = b"durable exclusive write"
        observed_sizes: list[int] = []

        def assert_flushed(descriptor: int) -> None:
            observed_sizes.append(tracker.os.fstat(descriptor).st_size)

        with mock.patch.object(tracker.os, "fsync", side_effect=assert_flushed) as fsync:
            tracker._write_exclusive(target, content)

        fsync.assert_called_once()
        self.assertEqual(observed_sizes, [len(content)])
        self.assertEqual(target.read_bytes(), content)

    def test_copy_exclusive关闭前flush并fsync完整内容(self) -> None:
        tracker = self.tracker()
        content = b"durable exclusive copy" * 1024
        source = self.root / "独占复制来源.bin"
        target = self.root / "独占复制刷新.bin"
        source.write_bytes(content)
        observed_sizes: list[int] = []

        def assert_flushed(descriptor: int) -> None:
            observed_sizes.append(tracker.os.fstat(descriptor).st_size)

        with mock.patch.object(tracker.os, "fsync", side_effect=assert_flushed) as fsync:
            tracker._copy_exclusive(source, target)

        fsync.assert_called_once()
        self.assertEqual(observed_sizes, [len(content)])
        self.assertEqual(target.read_bytes(), content)

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
        self.assertEqual(final_record["schema_version"], 5)
        self.assertEqual(final_record["visual_checks"], records[0]["visual_checks"])
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

    def test_v1任务和v5清单保持兼容且不写并发字段(self) -> None:
        tracker = self.tracker()
        source = self.png(self.source_dir / "v1兼容.png", (1024, 1024), (10, 20, 30))
        prompt = self.prompt("副图-01-v1兼容.txt", "v1 兼容路径")

        record = tracker.capture_artifact(**self.capture_kwargs(
            source=source,
            destination=self.direct_dir / "定制沙发坐垫_副图_01_direct01.png",
            prompt_path=prompt,
        ))

        self.assertEqual(record["schema_version"], 5)
        self.assertNotIn("dispatch_mode", record)
        self.assertNotIn("provider_source_path", record)
        self.assertNotIn("concurrency_policy", self.read_job())

    def test_v1_capture省略call_started_at时给中文TrackerError(self) -> None:
        tracker = self.tracker()
        source = self.png(self.source_dir / "v1缺少调用时间.png", (1024, 1024), (10, 20, 30))
        prompt = self.prompt("副图-01-v1缺少调用时间.txt", "v1 缺少调用时间")
        kwargs = self.capture_kwargs(
            source=source,
            destination=self.direct_dir / "定制沙发坐垫_副图_01_direct01.png",
            prompt_path=prompt,
        )
        kwargs.pop("call_started_at")

        try:
            with self.assertRaisesRegex(
                tracker.TrackerError, "v1|调用开始时间|call_started_at|不能为空|必须提供",
            ):
                tracker.capture_artifact(**kwargs)
        except TypeError as error:
            self.fail(f"capture 公共 API 仍把 call_started_at 设为必传参数：{error}")

        self.assertFalse(self.manifest.exists())

    def test_v2必须使用固定并发策略且不能靠刷新审批绕过(self) -> None:
        tracker = self.tracker()
        self.require_api(tracker, "reserve_attempt")
        invalid_policies = []
        for key in CONCURRENCY_POLICY:
            policy = copy.deepcopy(CONCURRENCY_POLICY)
            del policy[key]
            invalid_policies.append(policy)
        changed = copy.deepcopy(CONCURRENCY_POLICY)
        changed["max_calling_attempts"] = 4
        invalid_policies.append(changed)
        changed = copy.deepcopy(CONCURRENCY_POLICY)
        changed["max_pending_attempts"] = 99
        invalid_policies.append(changed)

        for index, policy in enumerate(invalid_policies, start=1):
            with self.subTest(index=index, policy=policy):
                job = self.write_job_v2()
                job["concurrency_policy"] = policy
                self.write_job_data(job, refresh_scope=True)
                before = self.job_file.read_bytes()
                kwargs = self.reserve_kwargs(
                    prompt_path=self.prompt_for_image("副图-01", index, f"非法策略 {index}"),
                    snapshot_path=self.fresh_snapshot_for_image("副图-01"),
                )
                with self.assertRaisesRegex(
                    tracker.TrackerError,
                    "并发策略|concurrency_policy|固定策略",
                ):
                    tracker.reserve_attempt(**kwargs)
                self.assertEqual(self.job_file.read_bytes(), before, "策略校验失败不得改写 job")

    def test_state_entry_requires_complete_approval_metadata(self) -> None:
        tracker = self.tracker()
        self.require_api(tracker, "reserve_attempt")
        cases = (
            ("缺少确认原文", "confirmation_text", None),
            ("缺少确认时间", "confirmed_at", None),
            ("确认时间无时区", "confirmed_at", "2026-07-21T08:00:00"),
            ("任务已阻塞", "job_status", "blocked"),
        )

        for index, (label, field, value) in enumerate(cases, start=1):
            with self.subTest(label=label):
                job = self.write_job_v2()
                if field == "job_status":
                    job[field] = value
                elif value is None:
                    job["approval"].pop(field, None)
                else:
                    job["approval"][field] = value
                self.write_job_data(job)
                kwargs = self.reserve_kwargs(
                    prompt_path=self.prompt_for_image("副图-01", index, label),
                    snapshot_path=self.fresh_snapshot_for_image("副图-01"),
                )
                before = self.job_file.read_bytes()

                with self.assertRaisesRegex(
                    tracker.TrackerError,
                    "确认|时区|批准|任务状态|job_status",
                ):
                    tracker.reserve_attempt(**kwargs)
                self.assertEqual(self.job_file.read_bytes(), before)

    def test_state_entry_requires_canonical_job_location(self) -> None:
        tracker = self.tracker()
        self.require_api(tracker, "reserve_attempt")
        cases = ("task_id", "product_folder")

        for index, field in enumerate(cases, start=1):
            with self.subTest(field=field):
                job = self.write_job_v2()
                if field == "task_id":
                    job[field] = "temu-错误任务编号"
                    self.write_job_data(job)
                else:
                    job[field] = str((self.root / "错误产品目录").resolve())
                    self.write_job_data(job, refresh_scope=True)
                kwargs = self.reserve_kwargs(
                    prompt_path=self.prompt_for_image("副图-01", index, field),
                    snapshot_path=self.fresh_snapshot_for_image("副图-01"),
                )
                before = self.job_file.read_bytes()

                with self.assertRaisesRegex(
                    tracker.TrackerError,
                    "任务编号|task_id|产品文件夹|product_folder|规范位置|_temu_job",
                ):
                    tracker.reserve_attempt(**kwargs)
                self.assertEqual(self.job_file.read_bytes(), before)

    def test_stage和fail入口拒绝非法审批与任务位置且完全不落盘(self) -> None:
        tracker = self.tracker()
        self.require_api(tracker, "reserve_attempt", "stage_attempt", "fail_attempt")
        cases = (
            "missing_confirmation_text",
            "confirmed_at_without_timezone",
            "invalid_job_status",
            "task_id_location_mismatch",
            "product_folder_location_mismatch",
        )

        for command in ("stage", "fail"):
            for case_index, case in enumerate(cases, start=1):
                with self.subTest(command=command, case=case):
                    self.write_job_v2()
                    tracker.reserve_attempt(**self.reserve_kwargs(attempt_no=case_index))
                    job = self.read_job()
                    refresh_scope = False
                    if case == "missing_confirmation_text":
                        job["approval"].pop("confirmation_text", None)
                    elif case == "confirmed_at_without_timezone":
                        job["approval"]["confirmed_at"] = "2026-07-21T08:00:00"
                    elif case == "invalid_job_status":
                        job["job_status"] = "blocked"
                    elif case == "task_id_location_mismatch":
                        job["task_id"] = "temu-错误任务编号"
                        refresh_scope = True
                    else:
                        job["product_folder"] = str((self.root / "错误产品目录").resolve())
                        refresh_scope = True
                    self.write_job_data(job, refresh_scope=refresh_scope)
                    before = self.job_file.read_bytes()
                    staged_path = (
                        self.job_file.parent / "副图-01" / "staged" / f"{case_index}.png"
                    )

                    with self.assertRaisesRegex(
                        tracker.TrackerError,
                        "确认|时区|job_status|task_id|product_folder|规范位置",
                    ):
                        if command == "stage":
                            source = self.png(
                                self.source_dir / f"入口拒绝-{case_index}.png",
                                (1024, 1024),
                                (case_index, 20, 30),
                            )
                            tracker.stage_attempt(
                                job_path=self.job_file,
                                image_id="副图-01",
                                attempt_no=case_index,
                                source_path=source,
                            )
                        else:
                            tracker.fail_attempt(
                                job_path=self.job_file,
                                image_id="副图-01",
                                attempt_no=case_index,
                                failure_type="provider_error",
                                reason="入口元数据非法时必须拒绝",
                            )

                    self.assertEqual(self.job_file.read_bytes(), before)
                    self.assertFalse(staged_path.exists())

    def test_reserve原子登记calling并拒绝重复和同图未终结(self) -> None:
        tracker = self.tracker()
        self.require_api(tracker, "reserve_attempt")
        self.write_job_v2()
        first_kwargs = self.reserve_kwargs()

        first = tracker.reserve_attempt(**first_kwargs)

        self.assertEqual(first["status"], "calling")
        self.assertEqual(first["dispatch_mode"], "parallel")
        self.assertEqual(first["artifact_kind"], "direct")
        self.assertEqual(first["direct_index"], 1)
        self.assertEqual(Path(first["prompt_path"]), Path(first_kwargs["prompt_path"]).resolve())
        self.assertEqual(Path(first["source_dir"]), self.source_dir.resolve())
        self.assertEqual(self.find_attempt("副图-01", 1), first)
        datetime.fromisoformat(first["call_started_at"])

        before = self.job_file.read_bytes()
        with self.assertRaisesRegex(tracker.TrackerError, "尝试号.*重复|attempt.*重复"):
            tracker.reserve_attempt(**first_kwargs)
        self.assertEqual(self.job_file.read_bytes(), before)

        second_kwargs = self.reserve_kwargs(image_id="副图-01", attempt_no=2, direct_index=2)
        with self.assertRaisesRegex(tracker.TrackerError, "同图|当前图号.*未终结|尚未终结"):
            tracker.reserve_attempt(**second_kwargs)
        self.assertEqual(self.job_file.read_bytes(), before)

    def test_reserve限制三个跨图calling和三个待处理attempt(self) -> None:
        tracker = self.tracker()
        self.require_api(tracker, "reserve_attempt", "stage_attempt", "fail_attempt")
        self.write_job_v2("副图-02", "副图-03", "副图-04")
        for image_id in ("副图-01", "副图-02", "副图-03"):
            tracker.reserve_attempt(**self.reserve_kwargs(image_id=image_id))

        before = self.job_file.read_bytes()
        fourth = self.reserve_kwargs(image_id="副图-04")
        with self.assertRaisesRegex(tracker.TrackerError, "最多.*3|calling.*上限"):
            tracker.reserve_attempt(**fourth)
        self.assertEqual(self.job_file.read_bytes(), before)

        source = self.png(self.source_dir / "已暂存仍占槽.png", (1024, 1024), (10, 20, 30))
        tracker.stage_attempt(
            job_path=self.job_file, image_id="副图-01", attempt_no=1, source_path=source,
        )
        before = self.job_file.read_bytes()
        with self.assertRaisesRegex(tracker.TrackerError, "待处理|pending.*3|calling.*staged"):
            tracker.reserve_attempt(**fourth)
        self.assertEqual(self.job_file.read_bytes(), before, "staged 在检查前必须继续占用待处理槽")

        tracker.fail_attempt(
            job_path=self.job_file,
            image_id="副图-02",
            attempt_no=1,
            failure_type="provider_error",
            reason="渠道明确返回失败",
        )
        reserved = tracker.reserve_attempt(**fourth)
        self.assertEqual(reserved["status"], "calling")

    def test_stage_rejects_corrupt_task_pending_invariants(self) -> None:
        tracker = self.tracker()
        self.require_api(tracker, "reserve_attempt", "stage_attempt")
        cases = ("非法调度模式", "同图多个pending", "pending超过上限", "serial未独占")

        for attempt_no, label in enumerate(cases, start=1):
            with self.subTest(label=label):
                self.write_job_v2("副图-02", "副图-03", "副图-04")
                tracker.reserve_attempt(**self.reserve_kwargs(
                    image_id="副图-01", attempt_no=attempt_no,
                ))
                job = self.read_job()
                images = {item["image_id"]: item for item in job["images"]}
                if label == "非法调度模式":
                    images["副图-02"]["execution"]["attempts"] = [
                        {"status": "calling", "dispatch_mode": "unknown"},
                    ]
                elif label == "同图多个pending":
                    images["副图-02"]["execution"]["attempts"] = [
                        {"status": "calling", "dispatch_mode": "parallel"},
                        {"status": "unresolved", "dispatch_mode": "parallel"},
                    ]
                elif label == "pending超过上限":
                    for image_id in ("副图-02", "副图-03", "副图-04"):
                        images[image_id]["execution"]["attempts"] = [
                            {"status": "calling", "dispatch_mode": "parallel"},
                        ]
                else:
                    images["副图-02"]["execution"]["attempts"] = [
                        {"status": "calling", "dispatch_mode": "serial"},
                    ]
                self.write_job_data(job)
                source = self.png(
                    self.source_dir / f"损坏pending-{attempt_no}.png",
                    (640, 480),
                    (10 * attempt_no, 20, 30),
                )
                staged_path = self.job_file.parent / "副图-01" / "staged" / f"{attempt_no}.png"
                before = self.job_file.read_bytes()

                with self.assertRaisesRegex(
                    tracker.TrackerError,
                    "dispatch_mode|调度|同图|pending|待处理|上限|serial|独占|并发",
                ):
                    tracker.stage_attempt(
                        job_path=self.job_file,
                        image_id="副图-01",
                        attempt_no=attempt_no,
                        source_path=source,
                    )
                self.assertEqual(self.job_file.read_bytes(), before)
                self.assertFalse(staged_path.exists())

    def test_fail_can_repair_target_when_other_pending_break_global_exclusivity(self) -> None:
        tracker = self.tracker()
        self.require_api(tracker, "reserve_attempt", "fail_attempt")
        self.write_job_v2("副图-02")
        tracker.reserve_attempt(**self.reserve_kwargs(image_id="副图-01"))
        tracker.reserve_attempt(**self.reserve_kwargs(image_id="副图-02"))
        job = self.read_job()
        job["images"][1]["execution"]["attempts"][0]["dispatch_mode"] = "serial"
        self.write_job_data(job)

        failed = tracker.fail_attempt(
            job_path=self.job_file,
            image_id="副图-01",
            attempt_no=1,
            failure_type="provider_error",
            reason="受控终结目标调用以修复全局状态",
        )

        self.assertEqual(failed["status"], "failed")
        self.assertEqual(self.find_attempt("副图-02", 1)["status"], "calling")

    def test_stage要求并发明确路径并排他保存固定暂存副本(self) -> None:
        tracker = self.tracker()
        self.require_api(tracker, "reserve_attempt", "stage_attempt")
        self.write_job_v2()
        tracker.reserve_attempt(**self.reserve_kwargs())

        before = self.job_file.read_bytes()
        with self.assertRaisesRegex(
            tracker.TrackerError, "明确.*路径|source_path|tool_return",
        ):
            tracker.stage_attempt(
                job_path=self.job_file, image_id="副图-01", attempt_no=1, source_path=None,
            )
        self.assertEqual(self.job_file.read_bytes(), before)

        source = self.png(self.source_dir / "明确返回.png", (1024, 1024), (10, 20, 30))
        staged = tracker.stage_attempt(
            job_path=self.job_file, image_id="副图-01", attempt_no=1, source_path=source,
        )
        expected = self.job_file.parent / "副图-01" / "staged" / "1.png"
        self.assertEqual(staged["status"], "staged")
        self.assertEqual(Path(staged["provider_source_path"]), source.resolve())
        self.assertEqual(staged["provider_source_sha256"], self.sha256(source))
        self.assertEqual(Path(staged["staged_path"]), expected.resolve())
        self.assertEqual(staged["staged_sha256"], self.sha256(expected))
        self.assertEqual(staged["provenance_mode"], "tool_return")

        before = self.job_file.read_bytes()
        with self.assertRaisesRegex(tracker.TrackerError, "同图|staged|尚未终结"):
            tracker.reserve_attempt(**self.reserve_kwargs(
                image_id="副图-01", attempt_no=2, direct_index=2,
            ))
        self.assertEqual(self.job_file.read_bytes(), before)

        original_bytes = expected.read_bytes()
        replacement = self.png(self.source_dir / "禁止覆盖.png", (1024, 1024), (40, 50, 60))
        before = self.job_file.read_bytes()
        with self.assertRaisesRegex(tracker.TrackerError, "staged|暂存.*已存在|拒绝覆盖|状态"):
            tracker.stage_attempt(
                job_path=self.job_file, image_id="副图-01", attempt_no=1,
                source_path=replacement,
            )
        self.assertEqual(expected.read_bytes(), original_bytes)
        self.assertEqual(self.job_file.read_bytes(), before)

    def test_stage复制前持久化完整身份sidecar且成功后清理(self) -> None:
        tracker = self.tracker()
        self.require_api(tracker, "reserve_attempt", "stage_attempt")
        self.write_job_v2()
        tracker.reserve_attempt(**self.reserve_kwargs())
        source = self.png(self.source_dir / "sidecar正常来源.png", (1024, 1024), (10, 20, 30))
        staged_path = self.job_file.parent / "副图-01" / "staged" / "1.png"
        sidecar_path = staged_path.with_suffix(".identity.json")
        original_copy = tracker._copy_exclusive
        observed: dict = {}

        def assert_identity_before_copy(source_path, target_path):
            self.assertTrue(sidecar_path.is_file(), "复制前必须先持久化 attempt 身份 sidecar")
            observed.update(json.loads(sidecar_path.read_text(encoding="utf-8")))
            return original_copy(source_path, target_path)

        with mock.patch.object(tracker, "_copy_exclusive", side_effect=assert_identity_before_copy):
            staged = tracker.stage_attempt(
                job_path=self.job_file,
                image_id="副图-01",
                attempt_no=1,
                source_path=source,
            )

        self.assertEqual(observed, {
            "schema_version": 1,
            "job_path": str(self.job_file.resolve()),
            "task_id": "temu-20260721-测试",
            "image_id": "副图-01",
            "attempt_no": 1,
            "provider_source_path": str(source.resolve()),
            "provider_source_sha256": self.sha256(source),
            "staged_path": str(staged_path.resolve()),
            "staged_sha256": self.sha256(source),
        })
        self.assertEqual(staged["staged_sha256"], observed["staged_sha256"])
        self.assertFalse(sidecar_path.exists())

    def test_v2_serial即使唯一快照差异也必须提供明确source_path(self) -> None:
        tracker = self.tracker()
        self.require_api(tracker, "reserve_attempt", "stage_attempt")
        self.write_job_v2()
        tracker.reserve_attempt(**self.reserve_kwargs(dispatch_mode="serial"))
        self.png(self.source_dir / "共享目录唯一差异.png", (1024, 1024), (10, 20, 30))
        before = self.job_file.read_bytes()
        staged_path = self.job_file.parent / "副图-01" / "staged" / "1.png"

        with self.assertRaisesRegex(
            tracker.TrackerError, "明确.*source_path|必须提供.*路径|tool_return",
        ):
            tracker.stage_attempt(
                job_path=self.job_file,
                image_id="副图-01",
                attempt_no=1,
                source_path=None,
            )

        self.assertEqual(self.job_file.read_bytes(), before)
        self.assertFalse(staged_path.exists())

    def test_stage_rejects_non_png_explicit_source_for_parallel_and_serial(self) -> None:
        tracker = self.tracker()
        self.require_api(tracker, "reserve_attempt", "stage_attempt")

        for attempt_no, dispatch_mode in ((1, "parallel"), (2, "serial")):
            with self.subTest(dispatch_mode=dispatch_mode):
                self.write_job_v2()
                tracker.reserve_attempt(**self.reserve_kwargs(
                    image_id="副图-01",
                    attempt_no=attempt_no,
                    dispatch_mode=dispatch_mode,
                ))
                source = self.source_dir / f"非PNG来源-{attempt_no}.png"
                Image.new("RGB", (640, 480), (10, 20, 30)).save(source, format="JPEG")
                staged_path = self.job_file.parent / "副图-01" / "staged" / f"{attempt_no}.png"
                before = self.job_file.read_bytes()

                with self.assertRaisesRegex(tracker.TrackerError, "PNG|图片格式|真实格式"):
                    tracker.stage_attempt(
                        job_path=self.job_file,
                        image_id="副图-01",
                        attempt_no=attempt_no,
                        source_path=source,
                    )
                self.assertEqual(self.job_file.read_bytes(), before)
                self.assertFalse(staged_path.exists())

    def test_stage_records_png_dimensions_and_contract_rejects_invalid_dimensions(self) -> None:
        tracker = self.tracker()
        self.require_api(tracker, "reserve_attempt", "stage_attempt")
        self.write_job_v2()
        tracker.reserve_attempt(**self.reserve_kwargs())
        source = self.png(self.source_dir / "记录尺寸.png", (640, 480), (10, 20, 30))

        staged = tracker.stage_attempt(
            job_path=self.job_file,
            image_id="副图-01",
            attempt_no=1,
            source_path=source,
        )

        self.assertEqual((staged["width"], staged["height"]), (640, 480))
        self.assertEqual(
            (self.find_attempt("副图-01", 1)["width"], self.find_attempt("副图-01", 1)["height"]),
            (640, 480),
        )
        job = self.read_job()
        job["images"][0]["execution"]["attempts"][0]["width"] = 0
        self.write_job_data(job)
        before = self.job_file.read_bytes()

        with self.assertRaisesRegex(tracker.TrackerError, "width|height|宽高|尺寸|正整数"):
            tracker.stage_attempt(
                job_path=self.job_file,
                image_id="副图-01",
                attempt_no=1,
                source_path=source,
            )
        self.assertEqual(self.job_file.read_bytes(), before)

    def test_stage拒绝绑定来源目录之外的明确路径(self) -> None:
        tracker = self.tracker()
        self.require_api(tracker, "reserve_attempt", "stage_attempt")
        self.write_job_v2()
        tracker.reserve_attempt(**self.reserve_kwargs())
        outside = self.png(
            self.root / "其他渠道目录" / "越界来源.png",
            (1024, 1024),
            (10, 20, 30),
        )

        with self.assertRaisesRegex(tracker.TrackerError, "来源目录|source_dir|目录之外"):
            tracker.stage_attempt(
                job_path=self.job_file, image_id="副图-01", attempt_no=1,
                source_path=outside,
            )

        self.assertEqual(self.find_attempt("副图-01", 1)["status"], "calling")
        self.assertFalse((self.job_file.parent / "副图-01" / "staged" / "1.png").exists())

    def test_stage复制竞态失败时不遗留文件也不改变calling(self) -> None:
        tracker = self.tracker()
        self.require_api(tracker, "reserve_attempt", "stage_attempt")
        self.write_job_v2()
        tracker.reserve_attempt(**self.reserve_kwargs())
        source = self.png(self.source_dir / "暂存竞态.png", (1024, 1024), (10, 20, 30))
        original_copy = tracker._copy_exclusive

        def mutate_then_copy(source_path, target_path):
            self.png(Path(source_path), (1024, 1024), (99, 88, 77))
            return original_copy(source_path, target_path)

        with mock.patch.object(tracker, "_copy_exclusive", side_effect=mutate_then_copy):
            with self.assertRaisesRegex(tracker.TrackerError, "复制期间.*变化|暂存.*变化"):
                tracker.stage_attempt(
                    job_path=self.job_file, image_id="副图-01", attempt_no=1,
                    source_path=source,
                )

        staged_path = self.job_file.parent / "副图-01" / "staged" / "1.png"
        self.assertFalse(staged_path.exists())
        self.assertEqual(self.find_attempt("副图-01", 1)["status"], "calling")

    def test_stage拒绝无sidecar的异哈希staged孤儿(self) -> None:
        tracker = self.tracker()
        self.require_api(tracker, "reserve_attempt", "stage_attempt")
        self.write_job_v2()
        tracker.reserve_attempt(**self.reserve_kwargs())
        source = self.png(
            self.source_dir / "异哈希来源.png", (1024, 1024), (40, 50, 60),
        )
        orphan = self.job_file.parent / "副图-01" / "staged" / "1.png"
        orphan.parent.mkdir(parents=True, exist_ok=True)
        self.png(orphan, (1024, 1024), (90, 90, 90))
        original = orphan.read_bytes()
        with self.assertRaisesRegex(tracker.TrackerError, "孤儿|staged.*哈希|拒绝覆盖"):
            tracker.stage_attempt(
                job_path=self.job_file, image_id="副图-01", attempt_no=1,
                source_path=source,
            )
        self.assertEqual(orphan.read_bytes(), original)
        self.assertEqual(self.find_attempt("副图-01", 1)["status"], "calling")

    def test_stage拒绝没有身份sidecar的同哈希staged孤儿(self) -> None:
        tracker = self.tracker()
        self.require_api(tracker, "reserve_attempt", "stage_attempt")
        self.write_job_v2()
        tracker.reserve_attempt(**self.reserve_kwargs())
        source = self.png(self.source_dir / "无身份孤儿来源.png", (1024, 1024), (10, 20, 30))
        orphan = self.job_file.parent / "副图-01" / "staged" / "1.png"
        orphan.parent.mkdir(parents=True, exist_ok=True)
        orphan.write_bytes(source.read_bytes())
        original = orphan.read_bytes()
        before = self.job_file.read_bytes()

        with self.assertRaisesRegex(
            tracker.TrackerError,
            "sidecar|身份|无法验证|孤儿.*拒绝",
        ):
            tracker.stage_attempt(
                job_path=self.job_file,
                image_id="副图-01",
                attempt_no=1,
                source_path=source,
            )

        self.assertEqual(self.job_file.read_bytes(), before)
        self.assertEqual(orphan.read_bytes(), original)
        self.assertEqual(self.find_attempt("副图-01", 1)["status"], "calling")

    def test_stage_job写回失败后以同路径同哈希和sidecar恢复(self) -> None:
        tracker = self.tracker()
        self.require_api(tracker, "reserve_attempt", "stage_attempt")
        self.write_job_v2()
        tracker.reserve_attempt(**self.reserve_kwargs())
        source = self.png(self.source_dir / "sidecar恢复来源.png", (1024, 1024), (10, 20, 30))
        staged_path = self.job_file.parent / "副图-01" / "staged" / "1.png"
        sidecar_path = staged_path.with_suffix(".identity.json")
        before = self.job_file.read_bytes()

        with mock.patch.object(
            tracker,
            "_write_job_atomic",
            side_effect=tracker.TrackerError("模拟 job 写回中断"),
        ):
            with self.assertRaisesRegex(tracker.TrackerError, "模拟 job 写回中断"):
                tracker.stage_attempt(
                    job_path=self.job_file,
                    image_id="副图-01",
                    attempt_no=1,
                    source_path=source,
                )

        self.assertEqual(self.job_file.read_bytes(), before)
        self.assertTrue(staged_path.is_file())
        self.assertTrue(sidecar_path.is_file())
        recovered = tracker.stage_attempt(
            job_path=self.job_file,
            image_id="副图-01",
            attempt_no=1,
            source_path=source,
        )
        self.assertEqual(recovered["status"], "staged")
        self.assertEqual(Path(recovered["provider_source_path"]), source.resolve())
        self.assertFalse(sidecar_path.exists())

    def test_stage恢复拒绝同哈希但不同provider来源路径(self) -> None:
        tracker = self.tracker()
        self.require_api(tracker, "reserve_attempt", "stage_attempt")
        self.write_job_v2()
        tracker.reserve_attempt(**self.reserve_kwargs())
        source = self.png(self.source_dir / "sidecar原始来源.png", (1024, 1024), (10, 20, 30))
        with mock.patch.object(
            tracker,
            "_write_job_atomic",
            side_effect=tracker.TrackerError("模拟 job 写回中断"),
        ):
            with self.assertRaisesRegex(tracker.TrackerError, "模拟 job 写回中断"):
                tracker.stage_attempt(
                    job_path=self.job_file,
                    image_id="副图-01",
                    attempt_no=1,
                    source_path=source,
                )
        same_hash = self.source_dir / "sidecar同哈希不同路径.png"
        same_hash.write_bytes(source.read_bytes())
        before = self.job_file.read_bytes()

        with self.assertRaisesRegex(
            tracker.TrackerError,
            "sidecar.*来源路径|provider_source_path|身份.*不一致",
        ):
            tracker.stage_attempt(
                job_path=self.job_file,
                image_id="副图-01",
                attempt_no=1,
                source_path=same_hash,
            )

        self.assertEqual(self.job_file.read_bytes(), before)
        self.assertEqual(self.find_attempt("副图-01", 1)["status"], "calling")

    def test_stage恢复拒绝sidecar中的其他attempt身份(self) -> None:
        tracker = self.tracker()
        self.require_api(tracker, "reserve_attempt", "stage_attempt")
        self.write_job_v2()
        tracker.reserve_attempt(**self.reserve_kwargs())
        source = self.png(self.source_dir / "sidecar-attempt来源.png", (1024, 1024), (10, 20, 30))
        sidecar_path = (
            self.job_file.parent / "副图-01" / "staged" / "1.identity.json"
        )
        with mock.patch.object(
            tracker,
            "_write_job_atomic",
            side_effect=tracker.TrackerError("模拟 job 写回中断"),
        ):
            with self.assertRaisesRegex(tracker.TrackerError, "模拟 job 写回中断"):
                tracker.stage_attempt(
                    job_path=self.job_file,
                    image_id="副图-01",
                    attempt_no=1,
                    source_path=source,
                )
        identity = json.loads(sidecar_path.read_text(encoding="utf-8"))
        identity["attempt_no"] = 99
        sidecar_path.write_text(json.dumps(identity, ensure_ascii=False), encoding="utf-8")
        before = self.job_file.read_bytes()

        with self.assertRaisesRegex(
            tracker.TrackerError,
            "sidecar.*attempt|attempt.*身份|身份.*不一致",
        ):
            tracker.stage_attempt(
                job_path=self.job_file,
                image_id="副图-01",
                attempt_no=1,
                source_path=source,
            )

        self.assertEqual(self.job_file.read_bytes(), before)
        self.assertEqual(self.find_attempt("副图-01", 1)["status"], "calling")

    def test_stage按规范路径和哈希拒绝跨图重复来源(self) -> None:
        tracker = self.tracker()
        self.require_api(tracker, "reserve_attempt", "stage_attempt")
        self.write_job_v2("副图-02")
        tracker.reserve_attempt(**self.reserve_kwargs(image_id="副图-01"))
        tracker.reserve_attempt(**self.reserve_kwargs(image_id="副图-02"))
        first = self.png(self.source_dir / "唯一来源.png", (1024, 1024), (10, 20, 30))
        tracker.stage_attempt(
            job_path=self.job_file, image_id="副图-01", attempt_no=1, source_path=first,
        )

        before = self.job_file.read_bytes()
        with self.assertRaisesRegex(tracker.TrackerError, "来源路径.*重复|已经归属"):
            tracker.stage_attempt(
                job_path=self.job_file, image_id="副图-02", attempt_no=1, source_path=first,
            )
        self.assertEqual(self.job_file.read_bytes(), before)

        same_hash = self.png(self.source_dir / "同哈希不同名.png", (1024, 1024), (10, 20, 30))
        with self.assertRaisesRegex(tracker.TrackerError, "来源哈希.*重复|图片哈希.*重复"):
            tracker.stage_attempt(
                job_path=self.job_file, image_id="副图-02", attempt_no=1,
                source_path=same_hash,
            )
        self.assertEqual(self.find_attempt("副图-02", 1)["status"], "calling")

    def test_fail原子记录失败分类并拒绝改写终态(self) -> None:
        tracker = self.tracker()
        self.require_api(tracker, "reserve_attempt", "fail_attempt")
        self.write_job_v2()
        tracker.reserve_attempt(**self.reserve_kwargs())
        before = self.job_file.read_bytes()

        with self.assertRaisesRegex(tracker.TrackerError, "失败分类|failure_type|未知"):
            tracker.fail_attempt(
                job_path=self.job_file,
                image_id="副图-01",
                attempt_no=1,
                failure_type="随意失败",
                reason="不能接受未知分类",
            )
        self.assertEqual(self.job_file.read_bytes(), before)

        failed = tracker.fail_attempt(
            job_path=self.job_file,
            image_id="副图-01",
            attempt_no=1,
            failure_type="provider_error",
            reason="渠道明确返回失败并确认调用已经终止",
        )
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["failure_type"], "provider_error")
        self.assertEqual(failed["failure_reason"], "渠道明确返回失败并确认调用已经终止")

        before = self.job_file.read_bytes()
        with self.assertRaisesRegex(tracker.TrackerError, "终态|已经.*failed|不能改写"):
            tracker.fail_attempt(
                job_path=self.job_file,
                image_id="副图-01",
                attempt_no=1,
                failure_type="provider_error",
                reason="不得覆盖第一次失败",
            )
        self.assertEqual(self.job_file.read_bytes(), before)

    def test_fail_failure_type枚举固定并以stage_error替换inspection_unavailable(self) -> None:
        tracker = self.tracker()
        self.require_api(tracker, "reserve_attempt", "fail_attempt")
        self.assertEqual(tracker.VALID_FAILURE_TYPES, {
            "completed_without_path",
            "timeout",
            "interrupted",
            "provider_error",
            "source_invalid",
            "stage_error",
            "other",
        })
        self.write_job_v2()
        tracker.reserve_attempt(**self.reserve_kwargs())
        before = self.job_file.read_bytes()

        with self.assertRaisesRegex(tracker.TrackerError, "失败分类|failure_type|未知"):
            tracker.fail_attempt(
                job_path=self.job_file,
                image_id="副图-01",
                attempt_no=1,
                failure_type="inspection_unavailable",
                reason="旧分类必须拒绝",
            )
        self.assertEqual(self.job_file.read_bytes(), before)

        failed = tracker.fail_attempt(
            job_path=self.job_file,
            image_id="副图-01",
            attempt_no=1,
            failure_type="stage_error",
            reason="暂存阶段发生确定失败",
        )
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["failure_type"], "stage_error")

    def test_fail_calling_records_failure_audit_and_last_error(self) -> None:
        tracker = self.tracker()
        self.require_api(tracker, "reserve_attempt", "fail_attempt")
        self.write_job_v2()
        tracker.reserve_attempt(**self.reserve_kwargs())

        failed = tracker.fail_attempt(
            job_path=self.job_file,
            image_id="副图-01",
            attempt_no=1,
            failure_type="provider_error",
            reason="渠道明确失败",
        )

        recorded_at = datetime.fromisoformat(failed["failure_recorded_at"])
        self.assertIsNotNone(recorded_at.utcoffset())
        execution = self.read_job()["images"][0]["execution"]
        self.assertEqual(execution["last_error"], {
            "attempt_no": 1,
            "status": "failed",
            "failure_type": "provider_error",
            "failure_reason": "渠道明确失败",
            "failure_recorded_at": failed["failure_recorded_at"],
            "termination_confirmed": False,
        })

    def test_fail_staged_rejects_uncertain_failure_without_mutation(self) -> None:
        tracker = self.tracker()
        self.require_api(tracker, "reserve_attempt", "stage_attempt", "fail_attempt")
        self.write_job_v2()
        tracker.reserve_attempt(**self.reserve_kwargs())
        source = self.png(self.source_dir / "已暂存待检查.png", (640, 480), (10, 20, 30))
        staged = tracker.stage_attempt(
            job_path=self.job_file, image_id="副图-01", attempt_no=1, source_path=source,
        )
        staged_path = Path(staged["staged_path"])
        staged_bytes = staged_path.read_bytes()
        before = self.job_file.read_bytes()

        with self.assertRaisesRegex(tracker.TrackerError, "staged|暂存|timeout|终止不明"):
            tracker.fail_attempt(
                job_path=self.job_file,
                image_id="副图-01",
                attempt_no=1,
                failure_type="timeout",
                reason="检查阶段不能倒退为终止不明",
            )
        self.assertEqual(self.job_file.read_bytes(), before)
        self.assertEqual(staged_path.read_bytes(), staged_bytes)

    def test_fail_staged_allows_deterministic_failure_without_confirmation(self) -> None:
        tracker = self.tracker()
        self.require_api(tracker, "reserve_attempt", "stage_attempt", "fail_attempt")
        self.write_job_v2()
        tracker.reserve_attempt(**self.reserve_kwargs())
        source = self.png(self.source_dir / "暂存后检查失败.png", (640, 480), (10, 20, 30))
        tracker.stage_attempt(
            job_path=self.job_file, image_id="副图-01", attempt_no=1, source_path=source,
        )

        failed = tracker.fail_attempt(
            job_path=self.job_file,
            image_id="副图-01",
            attempt_no=1,
            failure_type="source_invalid",
            reason="独立检查确认来源无效",
        )

        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["failure_type"], "source_invalid")
        self.assertIsNotNone(datetime.fromisoformat(failed["failure_recorded_at"]).utcoffset())

    def test_fail_unresolved_identical_retry_is_idempotent(self) -> None:
        tracker = self.tracker()
        self.require_api(tracker, "reserve_attempt", "fail_attempt")
        self.write_job_v2()
        tracker.reserve_attempt(**self.reserve_kwargs())
        kwargs = {
            "job_path": self.job_file,
            "image_id": "副图-01",
            "attempt_no": 1,
            "failure_type": "timeout",
            "reason": "渠道超时且无法确认终止",
        }
        first = tracker.fail_attempt(**kwargs)
        first_recorded_at = first["failure_recorded_at"]
        before = self.job_file.read_bytes()

        repeated = tracker.fail_attempt(**kwargs)

        self.assertEqual(repeated["status"], "unresolved")
        self.assertEqual(repeated["failure_recorded_at"], first_recorded_at)
        self.assertEqual(self.job_file.read_bytes(), before)

    def test_timeout和interrupted按终止确认进入unresolved或failed并记录审计(self) -> None:
        tracker = self.tracker()
        self.require_api(tracker, "reserve_attempt", "fail_attempt")

        for attempt_no, failure_type in enumerate(("timeout", "interrupted"), start=1):
            with self.subTest(failure_type=failure_type):
                self.write_job_v2()
                tracker.reserve_attempt(**self.reserve_kwargs(attempt_no=attempt_no))
                kwargs = {
                    "job_path": self.job_file,
                    "image_id": "副图-01",
                    "attempt_no": attempt_no,
                    "failure_type": failure_type,
                    "reason": f"{failure_type} 后尚未确认渠道终止",
                }

                unresolved = tracker.fail_attempt(**kwargs)
                self.assertEqual(unresolved["status"], "unresolved")
                self.assertIs(unresolved["termination_confirmed"], False)
                before = self.job_file.read_bytes()
                self.assertEqual(tracker.fail_attempt(**kwargs), unresolved)
                self.assertEqual(self.job_file.read_bytes(), before)

                failed = tracker.fail_attempt(**kwargs, termination_confirmed=True)
                self.assertEqual(failed["status"], "failed")
                self.assertIs(failed["termination_confirmed"], True)
                last_error = self.read_job()["images"][0]["execution"]["last_error"]
                self.assertIs(last_error["termination_confirmed"], True)

    def test_timeout和interrupted确认终止时可从calling直接进入failed(self) -> None:
        tracker = self.tracker()
        self.require_api(tracker, "reserve_attempt", "fail_attempt")

        for attempt_no, failure_type in enumerate(("timeout", "interrupted"), start=1):
            with self.subTest(failure_type=failure_type):
                self.write_job_v2()
                tracker.reserve_attempt(**self.reserve_kwargs(attempt_no=attempt_no))

                failed = tracker.fail_attempt(
                    job_path=self.job_file,
                    image_id="副图-01",
                    attempt_no=attempt_no,
                    failure_type=failure_type,
                    reason=f"{failure_type} 且已确认渠道终止",
                    termination_confirmed=True,
                )

                self.assertEqual(failed["status"], "failed")
                self.assertIs(failed["termination_confirmed"], True)

    def test_verify拒绝篡改timeout和interrupted的termination_confirmed(self) -> None:
        tracker = self.tracker()
        self.require_api(tracker, "reserve_attempt", "fail_attempt")
        cases = (
            ("timeout", False, "unresolved", True),
            ("interrupted", True, "failed", False),
        )

        for attempt_no, (failure_type, confirmed, expected_status, tampered) in enumerate(
            cases, start=1,
        ):
            with self.subTest(failure_type=failure_type, status=expected_status):
                self.manifest.unlink(missing_ok=True)
                (
                    self.direct_dir / "定制沙发坐垫_副图_01_direct01.png"
                ).unlink(missing_ok=True)
                for staged_name in ("1.png", "1.identity.json"):
                    (self.job_temp_dir / "staged" / staged_name).unlink(missing_ok=True)
                self.write_job_v2()
                self.create_v2_direct(tracker)
                tracker.reserve_attempt(**self.reserve_kwargs(
                    attempt_no=2,
                    direct_index=2,
                ))
                result = tracker.fail_attempt(
                    job_path=self.job_file,
                    image_id="副图-01",
                    attempt_no=2,
                    failure_type=failure_type,
                    reason=f"{failure_type} 审计状态",
                    termination_confirmed=confirmed,
                )
                self.assertEqual(result["status"], expected_status)
                job = self.read_job()
                job["images"][0]["execution"]["attempts"][1][
                    "termination_confirmed"
                ] = tampered
                self.write_job_data(job)

                report = tracker.verify_manifest(self.manifest)

                self.assertFalse(report["ok"])
                self.assertRegex(
                    "\n".join(report["errors"]),
                    "termination_confirmed|确认.*终止|unresolved.*false",
                )

    def test_fail_unresolved_rejects_uncertain_override(self) -> None:
        tracker = self.tracker()
        self.require_api(tracker, "reserve_attempt", "fail_attempt")
        overrides = (
            ("timeout", "同类但不同原因"),
            ("interrupted", "改写为另一种终止不明"),
        )

        for attempt_no, (failure_type, reason) in enumerate(overrides, start=1):
            with self.subTest(failure_type=failure_type, reason=reason):
                self.write_job_v2()
                tracker.reserve_attempt(**self.reserve_kwargs(attempt_no=attempt_no))
                tracker.fail_attempt(
                    job_path=self.job_file,
                    image_id="副图-01",
                    attempt_no=attempt_no,
                    failure_type="timeout",
                    reason="原始超时记录",
                )
                before = self.job_file.read_bytes()

                with self.assertRaisesRegex(
                    tracker.TrackerError, "unresolved|终止不明|覆盖|改写|幂等",
                ):
                    tracker.fail_attempt(
                        job_path=self.job_file,
                        image_id="副图-01",
                        attempt_no=attempt_no,
                        failure_type=failure_type,
                        reason=reason,
                    )
                self.assertEqual(self.job_file.read_bytes(), before)

    def test_fail_unresolved_requires_explicit_termination_confirmation(self) -> None:
        tracker = self.tracker()
        self.require_api(tracker, "reserve_attempt", "fail_attempt")
        self.write_job_v2()
        tracker.reserve_attempt(**self.reserve_kwargs())
        tracker.fail_attempt(
            job_path=self.job_file,
            image_id="副图-01",
            attempt_no=1,
            failure_type="interrupted",
            reason="中断后无法确认渠道终止",
        )
        before = self.job_file.read_bytes()

        with self.assertRaisesRegex(tracker.TrackerError, "termination_confirmed|确认.*终止"):
            tracker.fail_attempt(
                job_path=self.job_file,
                image_id="副图-01",
                attempt_no=1,
                failure_type="provider_error",
                reason="后续确认渠道已经终止",
            )
        self.assertEqual(self.job_file.read_bytes(), before)
        with self.assertRaisesRegex(tracker.TrackerError, "布尔|bool"):
            tracker.fail_attempt(
                job_path=self.job_file,
                image_id="副图-01",
                attempt_no=1,
                failure_type="provider_error",
                reason="非法确认值",
                termination_confirmed="yes",
            )
        self.assertEqual(self.job_file.read_bytes(), before)

        failed = tracker.fail_attempt(
            job_path=self.job_file,
            image_id="副图-01",
            attempt_no=1,
            failure_type="provider_error",
            reason="后续确认渠道已经终止",
            termination_confirmed=True,
        )
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["failure_type"], "provider_error")
        self.assertEqual(
            self.read_job()["images"][0]["execution"]["last_error"]["failure_recorded_at"],
            failed["failure_recorded_at"],
        )

    def test_job_contract_requires_timezone_failure_recorded_at(self) -> None:
        tracker = self.tracker()
        self.require_api(tracker, "reserve_attempt", "fail_attempt")

        for attempt_no, value in ((1, None), (2, "2026-07-21T08:00:00")):
            with self.subTest(value=value):
                self.write_job_v2()
                tracker.reserve_attempt(**self.reserve_kwargs(attempt_no=attempt_no))
                tracker.fail_attempt(
                    job_path=self.job_file,
                    image_id="副图-01",
                    attempt_no=attempt_no,
                    failure_type="timeout",
                    reason="等待渠道终止确认",
                )
                job = self.read_job()
                attempt = job["images"][0]["execution"]["attempts"][0]
                if value is None:
                    attempt.pop("failure_recorded_at", None)
                else:
                    attempt["failure_recorded_at"] = value
                self.write_job_data(job)
                before = self.job_file.read_bytes()

                with self.assertRaisesRegex(
                    tracker.TrackerError, "failure_recorded_at|失败记录时间|时区",
                ):
                    tracker.fail_attempt(
                        job_path=self.job_file,
                        image_id="副图-01",
                        attempt_no=attempt_no,
                        failure_type="timeout",
                        reason="等待渠道终止确认",
                    )
                self.assertEqual(self.job_file.read_bytes(), before)

    def test_fail_cli_exposes_termination_confirmation_flag(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "fail", "--help"],
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--termination-confirmed", result.stdout)
        self.assertRegex(result.stdout, "确认|终止")

    def test_completed_without_path排空后串行重试仍要求明确路径(self) -> None:
        tracker = self.tracker()
        self.require_api(tracker, "reserve_attempt", "stage_attempt", "fail_attempt")
        self.write_job_v2("副图-02")
        tracker.reserve_attempt(**self.reserve_kwargs(image_id="副图-01"))
        tracker.reserve_attempt(**self.reserve_kwargs(image_id="副图-02"))
        tracker.fail_attempt(
            job_path=self.job_file,
            image_id="副图-01",
            attempt_no=1,
            failure_type="completed_without_path",
            reason="渠道已完成但没有返回明确路径",
        )

        blocked = self.reserve_kwargs(
            image_id="副图-01", attempt_no=2, dispatch_mode="serial", direct_index=1,
        )
        before = self.job_file.read_bytes()
        with self.assertRaisesRegex(tracker.TrackerError, "全任务.*排空|仍有.*未终结|serial.*独占"):
            tracker.reserve_attempt(**blocked)
        self.assertEqual(self.job_file.read_bytes(), before)

        tracker.fail_attempt(
            job_path=self.job_file,
            image_id="副图-02",
            attempt_no=1,
            failure_type="provider_error",
            reason="另一图号调用已明确失败",
        )
        self.png(self.source_dir / "排空前无关旧图.png", (1024, 1024), (5, 6, 7))
        snapshot = self.fresh_snapshot_for_image("副图-01")
        retry = self.reserve_kwargs(
            image_id="副图-01", attempt_no=2, dispatch_mode="serial", direct_index=1,
            snapshot_path=snapshot,
        )
        tracker.reserve_attempt(**retry)
        candidate = self.png(self.source_dir / "排空后的唯一差异.png", (1024, 1024), (30, 40, 50))
        before = self.job_file.read_bytes()
        with self.assertRaisesRegex(tracker.TrackerError, "明确.*source_path|tool_return"):
            tracker.stage_attempt(
                job_path=self.job_file, image_id="副图-01", attempt_no=2, source_path=None,
            )
        self.assertEqual(self.job_file.read_bytes(), before)

        staged = tracker.stage_attempt(
            job_path=self.job_file, image_id="副图-01", attempt_no=2, source_path=candidate,
        )
        self.assertEqual(staged["status"], "staged")
        self.assertEqual(staged["provenance_mode"], "tool_return")
        self.assertEqual(Path(staged["provider_source_path"]), candidate.resolve())

    def test_completed_without_path后的下一attempt拒绝parallel并允许serial(self) -> None:
        tracker = self.tracker()
        self.require_api(tracker, "reserve_attempt", "fail_attempt")
        self.write_job_v2()
        tracker.reserve_attempt(**self.reserve_kwargs())
        tracker.fail_attempt(
            job_path=self.job_file,
            image_id="副图-01",
            attempt_no=1,
            failure_type="completed_without_path",
            reason="渠道完成但未返回明确路径",
        )
        parallel = self.reserve_kwargs(
            attempt_no=2,
            dispatch_mode="parallel",
            direct_index=1,
        )
        before = self.job_file.read_bytes()

        with self.assertRaisesRegex(
            tracker.TrackerError,
            "completed_without_path|明确路径.*serial|下一.*serial|必须.*串行",
        ):
            tracker.reserve_attempt(**parallel)

        self.assertEqual(self.job_file.read_bytes(), before)
        serial = dict(parallel)
        serial["dispatch_mode"] = "serial"
        reserved = tracker.reserve_attempt(**serial)
        self.assertEqual(reserved["status"], "calling")
        self.assertEqual(reserved["dispatch_mode"], "serial")

    def test_timeout和interrupted进入unresolved占槽且迟到明确路径只归原attempt(self) -> None:
        tracker = self.tracker()
        self.require_api(tracker, "reserve_attempt", "stage_attempt", "fail_attempt")
        self.write_job_v2("副图-02", "副图-03", "副图-04")
        for image_id, failure_type in (("副图-01", "timeout"), ("副图-02", "interrupted")):
            tracker.reserve_attempt(**self.reserve_kwargs(image_id=image_id))
            unresolved = tracker.fail_attempt(
                job_path=self.job_file,
                image_id=image_id,
                attempt_no=1,
                failure_type=failure_type,
                reason=f"{failure_type} 后无法确认渠道已经终止",
            )
            self.assertEqual(unresolved["status"], "unresolved")
            self.assertEqual(unresolved["failure_type"], failure_type)

            before = self.job_file.read_bytes()
            with self.assertRaisesRegex(tracker.TrackerError, "同图|unresolved|尚未终结"):
                tracker.reserve_attempt(**self.reserve_kwargs(
                    image_id=image_id, attempt_no=2, dispatch_mode="serial",
                ))
            self.assertEqual(self.job_file.read_bytes(), before)

            self.png(
                self.source_dir / f"{failure_type}-无明确归属的差异.png",
                (1024, 1024),
                (50, 60, 70),
            )
            with self.assertRaisesRegex(
                tracker.TrackerError,
                "unresolved|迟到.*串图|禁止.*快照|明确路径|source_path|tool_return",
            ):
                tracker.stage_attempt(
                    job_path=self.job_file,
                    image_id=image_id,
                    attempt_no=1,
                    source_path=None,
                )

            explicit = self.png(
                self.source_dir / f"{failure_type}-迟到明确返回.png",
                (1024, 1024),
                (80, 90, 100) if failure_type == "timeout" else (81, 91, 101),
            )
            staged = tracker.stage_attempt(
                job_path=self.job_file,
                image_id=image_id,
                attempt_no=1,
                source_path=explicit,
            )
            self.assertEqual(staged["status"], "staged")
            self.assertEqual(Path(staged["provider_source_path"]), explicit.resolve())

        tracker.reserve_attempt(**self.reserve_kwargs(image_id="副图-03"))
        before = self.job_file.read_bytes()
        with self.assertRaisesRegex(tracker.TrackerError, "待处理|pending.*3|上限"):
            tracker.reserve_attempt(**self.reserve_kwargs(image_id="副图-04"))
        self.assertEqual(self.job_file.read_bytes(), before)

    def test_v2_serial缺路径不扫描快照候选且失败保持calling(self) -> None:
        tracker = self.tracker()
        self.require_api(tracker, "reserve_attempt", "stage_attempt")
        self.write_job_v2()
        tracker.reserve_attempt(**self.reserve_kwargs(dispatch_mode="serial"))

        before = self.job_file.read_bytes()
        with self.assertRaisesRegex(tracker.TrackerError, "明确.*source_path|tool_return"):
            tracker.stage_attempt(
                job_path=self.job_file, image_id="副图-01", attempt_no=1, source_path=None,
            )
        self.assertEqual(self.job_file.read_bytes(), before)

        self.png(self.source_dir / "候选一.png", (1024, 1024), (10, 20, 30))
        self.png(self.source_dir / "候选二.png", (1024, 1024), (40, 50, 60))
        with self.assertRaisesRegex(tracker.TrackerError, "明确.*source_path|tool_return"):
            tracker.stage_attempt(
                job_path=self.job_file, image_id="副图-01", attempt_no=1, source_path=None,
            )
        self.assertEqual(self.find_attempt("副图-01", 1)["status"], "calling")

    def test_v2_capture必须消费staged且调用方不得再传source(self) -> None:
        tracker = self.tracker()
        self.require_api(tracker, "reserve_attempt", "stage_attempt")
        self.write_job_v2()
        reserve = self.reserve_kwargs()
        tracker.reserve_attempt(**reserve)
        calling = self.find_attempt("副图-01", 1)
        destination = self.direct_dir / "定制沙发坐垫_副图_01_direct01.png"

        with self.assertRaisesRegex(tracker.TrackerError, "staged|尚未暂存"):
            tracker.capture_artifact(**self.capture_kwargs_v2(
                calling, image_id="副图-01", destination=destination,
            ))
        self.assertFalse(destination.exists())
        self.assertFalse(self.manifest.exists())

        provider_source = self.png(self.source_dir / "capture来源.png", (1024, 1024), (10, 20, 30))
        tracker.stage_attempt(
            job_path=self.job_file, image_id="副图-01", attempt_no=1,
            source_path=provider_source,
        )
        staged = self.find_attempt("副图-01", 1)
        provider_hash_at_stage = staged["provider_source_sha256"]
        invalid = self.capture_kwargs_v2(staged, image_id="副图-01", destination=destination)
        invalid["explicit_source"] = provider_source
        with self.assertRaisesRegex(tracker.TrackerError, "v2.*source|不得.*来源|必须省略"):
            tracker.capture_artifact(**invalid)
        self.assertFalse(destination.exists())
        self.assertFalse(self.manifest.exists())

        self.png(provider_source, (1024, 1024), (99, 88, 77))
        record = tracker.capture_artifact(**self.capture_kwargs_v2(
            staged, image_id="副图-01", destination=destination,
        ))
        terminal = self.find_attempt("副图-01", 1)
        self.assertEqual(record["schema_version"], 6)
        self.assertEqual(record["dispatch_mode"], "parallel")
        self.assertEqual(record["provenance_mode"], "tool_return")
        self.assertEqual(Path(record["provider_source_path"]), provider_source.resolve())
        self.assertEqual(record["provider_source_sha256"], provider_hash_at_stage)
        self.assertEqual(Path(record["source_path"]), Path(staged["staged_path"]).resolve())
        self.assertEqual(record["source_sha256"], staged["staged_sha256"])
        self.assertEqual(terminal["status"], "accepted")
        self.assertEqual(terminal["artifact_id"], record["artifact_id"])
        self.assertEqual(self.read_manifest(), [record])

    def test_v2_capture省略call_started_at并只记录attempt规范时间(self) -> None:
        tracker = self.tracker()
        self.write_job_v2()
        tracker.reserve_attempt(**self.reserve_kwargs())
        source = self.png(self.source_dir / "v2省略调用时间.png", (1024, 1024), (10, 20, 30))
        tracker.stage_attempt(
            job_path=self.job_file,
            image_id="副图-01",
            attempt_no=1,
            source_path=source,
        )
        attempt = self.find_attempt("副图-01", 1)
        kwargs = self.capture_kwargs_v2(
            attempt,
            image_id="副图-01",
            destination=self.direct_dir / "定制沙发坐垫_副图_01_direct01.png",
        )
        self.assertIsNone(
            inspect.signature(tracker.capture_artifact).parameters["call_started_at"].default,
        )

        record = tracker.capture_artifact(**kwargs)

        self.assertEqual(record["call_started_at"], attempt["call_started_at"])
        self.assertEqual(self.find_attempt("副图-01", 1)["call_started_at"], attempt["call_started_at"])

    def test_v2_capture_cli省略call_started_at时成功(self) -> None:
        tracker = self.tracker()
        self.write_job_v2()
        tracker.reserve_attempt(**self.reserve_kwargs())
        source = self.png(self.source_dir / "v2-CLI省略调用时间.png", (1024, 1024), (20, 30, 40))
        tracker.stage_attempt(
            job_path=self.job_file,
            image_id="副图-01",
            attempt_no=1,
            source_path=source,
        )
        attempt = self.find_attempt("副图-01", 1)
        destination = self.direct_dir / "定制沙发坐垫_副图_01_direct01.png"
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "capture",
                "--snapshot-path", attempt["snapshot_path"],
                "--source-dir", attempt["source_dir"],
                "--destination", str(destination),
                "--manifest", str(self.manifest),
                "--task-id", "temu-20260721-测试",
                "--provider", "imagegen",
                "--platform", "temu-us",
                "--product-name", "定制沙发坐垫",
                "--image-id", "副图-01",
                "--image-type", "副图",
                "--prompt-id", attempt["prompt_id"],
                "--prompt-path", attempt["prompt_path"],
                "--attempt-no", "1",
                "--direct-index", "1",
                "--artifact-kind", "direct",
                "--status", "accepted",
                "--visual-checks", json.dumps(VISUAL_CHECKS_OK),
                "--inspection-session-id", "inspection-产物-CLI-01",
                "--inspection-checked-at", datetime.now(timezone.utc).isoformat(),
                "--inspection-notes", "CLI 独立检查已完成",
            ],
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.read_manifest()[0]["call_started_at"], attempt["call_started_at"])

    def test_v2_capture拒绝外部call_started_at即使与attempt等价(self) -> None:
        tracker = self.tracker()
        self.write_job_v2()
        tracker.reserve_attempt(**self.reserve_kwargs())
        source = self.png(self.source_dir / "v2拒绝外部调用时间.png", (1024, 1024), (30, 40, 50))
        tracker.stage_attempt(
            job_path=self.job_file,
            image_id="副图-01",
            attempt_no=1,
            source_path=source,
        )
        attempt = self.find_attempt("副图-01", 1)
        destination = self.direct_dir / "定制沙发坐垫_副图_01_direct01.png"
        kwargs = self.capture_kwargs_v2(
            attempt,
            image_id="副图-01",
            destination=destination,
        )
        kwargs["call_started_at"] = attempt["call_started_at"].replace("+00:00", "Z")
        before = self.job_file.read_bytes()

        with self.assertRaisesRegex(
            tracker.TrackerError,
            "v2.*call_started_at|v2.*调用时间|不得.*外部|必须省略",
        ):
            tracker.capture_artifact(**kwargs)

        self.assertEqual(self.job_file.read_bytes(), before)
        self.assertFalse(destination.exists())
        self.assertFalse(self.manifest.exists())

    def test_capture清单已写但job未终态时重试只修复对账不重复追加(self) -> None:
        tracker = self.tracker()
        self.require_api(tracker, "reserve_attempt", "stage_attempt")
        self.write_job_v2()
        tracker.reserve_attempt(**self.reserve_kwargs())
        source = self.png(self.source_dir / "清单后中断.png", (1024, 1024), (10, 20, 30))
        tracker.stage_attempt(
            job_path=self.job_file, image_id="副图-01", attempt_no=1, source_path=source,
        )
        staged_attempt = copy.deepcopy(self.find_attempt("副图-01", 1))
        destination = self.direct_dir / "定制沙发坐垫_副图_01_direct01.png"
        kwargs = self.capture_kwargs_v2(
            staged_attempt, image_id="副图-01", destination=destination,
        )
        first = tracker.capture_artifact(**kwargs)
        self.assertEqual(len(self.read_manifest()), 1)

        job = self.read_job()
        job["images"][0]["execution"]["attempts"] = [staged_attempt]
        self.write_job_data(job)
        recovered = tracker.capture_artifact(**kwargs)

        self.assertEqual(recovered["artifact_id"], first["artifact_id"])
        self.assertEqual(len(self.read_manifest()), 1)
        terminal = self.find_attempt("副图-01", 1)
        self.assertEqual(terminal["status"], "accepted")
        self.assertEqual(terminal["artifact_id"], first["artifact_id"])

    def test_v2_capture_rejected_clears_reserved_direct_index(self) -> None:
        tracker = self.tracker()
        self.require_api(tracker, "reserve_attempt", "stage_attempt")
        self.write_job_v2()
        tracker.reserve_attempt(**self.reserve_kwargs(direct_index=1))
        source = self.png(self.source_dir / "计划序号后检查失败.png", (1024, 1024), (10, 20, 30))
        tracker.stage_attempt(
            job_path=self.job_file, image_id="副图-01", attempt_no=1, source_path=source,
        )
        checks = dict(VISUAL_CHECKS_OK)
        checks["text_correct"] = False
        staged = self.find_attempt("副图-01", 1)
        record = tracker.capture_artifact(**self.capture_kwargs_v2(
            staged,
            image_id="副图-01",
            destination=self.rejected_dir / "定制沙发坐垫_副图_01_attempt01_rejected.png",
            status="rejected",
            direct_index=None,
            visual_checks=checks,
            rejection_reason="英文标题拼写错误",
        ))

        terminal = self.find_attempt("副图-01", 1)
        self.assertEqual(record["status"], "rejected")
        self.assertIsNone(record["direct_index"])
        self.assertEqual(terminal["status"], "rejected")
        self.assertIsNone(terminal["direct_index"])
        self.assertEqual(self.read_manifest(), [record])

    def test_v2_capture_accepted_assigns_missing_direct_index(self) -> None:
        tracker = self.tracker()
        self.require_api(tracker, "reserve_attempt", "stage_attempt")
        self.write_job_v2()
        tracker.reserve_attempt(**self.reserve_kwargs(direct_index=None))
        source = self.png(self.source_dir / "检查通过后分配序号.png", (1024, 1024), (10, 20, 30))
        tracker.stage_attempt(
            job_path=self.job_file, image_id="副图-01", attempt_no=1, source_path=source,
        )
        staged = self.find_attempt("副图-01", 1)
        record = tracker.capture_artifact(**self.capture_kwargs_v2(
            staged,
            image_id="副图-01",
            destination=self.direct_dir / "定制沙发坐垫_副图_01_direct01.png",
            status="accepted",
            direct_index=1,
        ))

        terminal = self.find_attempt("副图-01", 1)
        self.assertEqual(record["status"], "accepted")
        self.assertEqual(record["direct_index"], 1)
        self.assertEqual(terminal["status"], "accepted")
        self.assertEqual(terminal["direct_index"], 1)
        self.assertEqual(self.read_manifest(), [record])

    def test_v2_capture_accepted_cannot_change_reserved_direct_index(self) -> None:
        tracker = self.tracker()
        self.require_api(tracker, "reserve_attempt", "stage_attempt")
        self.write_job_v2()
        tracker.reserve_attempt(**self.reserve_kwargs(direct_index=1))
        source = self.png(self.source_dir / "不得改变计划序号.png", (1024, 1024), (10, 20, 30))
        tracker.stage_attempt(
            job_path=self.job_file, image_id="副图-01", attempt_no=1, source_path=source,
        )
        staged = self.find_attempt("副图-01", 1)
        destination = self.direct_dir / "定制沙发坐垫_副图_01_direct02.png"

        with self.assertRaises(tracker.TrackerError):
            tracker.capture_artifact(**self.capture_kwargs_v2(
                staged,
                image_id="副图-01",
                destination=destination,
                status="accepted",
                direct_index=2,
            ))
        self.assertFalse(destination.exists())
        self.assertFalse(self.manifest.exists())
        self.assertEqual(self.find_attempt("副图-01", 1)["status"], "staged")

    def test_capture拒绝项不占direct序号且后续有效版仍从direct01开始(self) -> None:
        tracker = self.tracker()
        self.require_api(tracker, "reserve_attempt", "stage_attempt")
        self.write_job_v2()
        tracker.reserve_attempt(**self.reserve_kwargs(direct_index=None))
        rejected_source = self.png(self.source_dir / "文字错误.png", (1024, 1024), (10, 20, 30))
        tracker.stage_attempt(
            job_path=self.job_file, image_id="副图-01", attempt_no=1,
            source_path=rejected_source,
        )
        checks = dict(VISUAL_CHECKS_OK)
        checks["text_correct"] = False
        rejected = self.find_attempt("副图-01", 1)
        rejected_record = tracker.capture_artifact(**self.capture_kwargs_v2(
            rejected,
            image_id="副图-01",
            destination=self.rejected_dir / "定制沙发坐垫_副图_01_attempt01_rejected.png",
            status="rejected",
            direct_index=None,
            visual_checks=checks,
            rejection_reason="英文标题拼写错误",
        ))
        self.assertIsNone(rejected_record["direct_index"])
        self.assertEqual(self.find_attempt("副图-01", 1)["status"], "rejected")

        accepted = self.create_v2_direct(
            tracker,
            attempt_no=2,
            direct_index=1,
            color=(40, 50, 60),
        )
        self.assertEqual(accepted["direct_index"], 1)
        self.assertEqual(
            [record["direct_index"] for record in self.read_manifest()],
            [None, 1],
        )

    def test_capture前staged被篡改时拒绝归档并保留待检查状态(self) -> None:
        tracker = self.tracker()
        self.require_api(tracker, "reserve_attempt", "stage_attempt")
        self.write_job_v2()
        tracker.reserve_attempt(**self.reserve_kwargs())
        source = self.png(self.source_dir / "暂存后篡改.png", (1024, 1024), (10, 20, 30))
        tracker.stage_attempt(
            job_path=self.job_file, image_id="副图-01", attempt_no=1, source_path=source,
        )
        attempt = self.find_attempt("副图-01", 1)
        self.png(Path(attempt["staged_path"]), (1024, 1024), (99, 99, 99))
        destination = self.direct_dir / "定制沙发坐垫_副图_01_direct01.png"

        with self.assertRaisesRegex(tracker.TrackerError, "staged.*哈希|暂存.*篡改|哈希不匹配"):
            tracker.capture_artifact(**self.capture_kwargs_v2(
                attempt, image_id="副图-01", destination=destination,
            ))
        self.assertFalse(destination.exists())
        self.assertFalse(self.manifest.exists())
        self.assertEqual(self.find_attempt("副图-01", 1)["status"], "staged")

    def test_v6清单同时校验渠道来源规范路径和哈希唯一性(self) -> None:
        tracker = self.tracker()
        self.write_job_v2("副图-02")
        self.create_v2_direct(tracker, image_id="副图-01", color=(10, 20, 30))
        self.create_v2_direct(tracker, image_id="副图-02", color=(40, 50, 60))
        records = self.read_manifest()
        records[1]["provider_source_path"] = records[0]["provider_source_path"]
        records[1]["provider_source_sha256"] = records[0]["provider_source_sha256"]
        self.manifest.write_text(
            "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n",
            encoding="utf-8",
        )

        report = tracker.verify_manifest(self.manifest)

        combined = "\n".join(report["errors"])
        self.assertFalse(report["ok"])
        self.assertRegex(combined, "渠道来源.*路径.*重复|provider_source_path.*重复")
        self.assertRegex(combined, "渠道来源.*哈希.*重复|provider_source_sha256.*重复")

    def test_verify_v6_direct和revision来源模式都只能是tool_return(self) -> None:
        tracker = self.tracker()
        self.write_job_v2()
        directs = []
        for index, (color, dispatch_mode) in enumerate((
            ((10, 20, 30), "parallel"),
            ((40, 50, 60), "serial"),
            ((70, 80, 90), "parallel"),
        ), start=1):
            directs.append(self.create_v2_direct(
                tracker,
                attempt_no=index,
                direct_index=index,
                color=color,
                dispatch_mode=dispatch_mode,
            ))
        tracker.reserve_attempt(**self.reserve_kwargs(
            attempt_no=4,
            artifact_kind="revision",
            direct_index=None,
            dispatch_mode="serial",
        ))
        revision_source = self.png(
            self.source_dir / "v6-revision-渠道返回.png", (1024, 1024), (15, 25, 35),
        )
        tracker.stage_attempt(
            job_path=self.job_file,
            image_id="副图-01",
            attempt_no=4,
            source_path=revision_source,
        )
        revision_attempt = self.find_attempt("副图-01", 4)
        revision_kwargs = self.capture_kwargs_v2(
            revision_attempt,
            image_id="副图-01",
            destination=self.job_temp_dir / "定制沙发坐垫_副图_01_revision01.png",
            direct_index=None,
        )
        revision_kwargs["parent_artifact_id"] = directs[0]["artifact_id"]
        revision = tracker.capture_artifact(**revision_kwargs)
        original_manifest = self.manifest.read_bytes()

        for artifact in (directs[0], directs[1], revision):
            with self.subTest(
                artifact_kind=artifact["artifact_kind"],
                dispatch_mode=artifact["dispatch_mode"],
            ):
                self.manifest.write_bytes(original_manifest)
                records = self.read_manifest()
                target = next(
                    item for item in records if item["artifact_id"] == artifact["artifact_id"]
                )
                target["provenance_mode"] = "snapshot_diff"
                self.manifest.write_text(
                    "\n".join(json.dumps(item, ensure_ascii=False) for item in records) + "\n",
                    encoding="utf-8",
                )

                try:
                    report = tracker.verify_manifest(self.manifest)

                    self.assertFalse(report["ok"])
                    self.assertRegex(
                        "\n".join(report["errors"]),
                        "v6.*tool_return|直出.*tool_return|修订.*tool_return",
                    )
                finally:
                    self.manifest.write_bytes(original_manifest)

    def test_verify即使清单与attempt一起篡改也拒绝source_dir外的provider_source_path(self) -> None:
        tracker = self.tracker()
        self.write_job_v2()
        record = self.create_v2_direct(tracker)
        outside = self.root / "其他共享目录" / "伪造归属.png"
        outside.parent.mkdir(parents=True, exist_ok=True)
        outside.write_bytes(Path(record["provider_source_path"]).read_bytes())

        job = self.read_job()
        attempt = job["images"][0]["execution"]["attempts"][0]
        attempt["provider_source_path"] = str(outside.resolve())
        self.write_job_data(job)
        records = self.read_manifest()
        records[0]["provider_source_path"] = str(outside.resolve())
        self.manifest.write_text(
            "\n".join(json.dumps(item, ensure_ascii=False) for item in records) + "\n",
            encoding="utf-8",
        )

        report = tracker.verify_manifest(self.manifest)

        self.assertFalse(report["ok"])
        self.assertRegex(
            "\n".join(report["errors"]),
            "provider_source_path.*source_dir|渠道来源.*绑定.*目录|来源路径.*目录之外",
        )

    def test_verify拒绝attempt单侧篡改为snapshot_diff(self) -> None:
        tracker = self.tracker()
        self.write_job_v2()
        self.create_v2_direct(tracker)
        job = self.read_job()
        job["images"][0]["execution"]["attempts"][0]["provenance_mode"] = "snapshot_diff"
        self.write_job_data(job)

        report = tracker.verify_manifest(self.manifest)

        self.assertFalse(report["ok"])
        self.assertRegex(
            "\n".join(report["errors"]),
            "attempt.*tool_return|provenance_mode.*tool_return|来源模式.*tool_return",
        )

    def test_verify拒绝清名单侧篡改到attempt绑定source_dir之外(self) -> None:
        tracker = self.tracker()
        self.write_job_v2()
        record = self.create_v2_direct(tracker)
        outside = self.root / "其他共享目录" / "仅清单伪造路径.png"
        outside.parent.mkdir(parents=True, exist_ok=True)
        outside.write_bytes(Path(record["provider_source_path"]).read_bytes())
        records = self.read_manifest()
        records[0]["provider_source_path"] = str(outside.resolve())
        self.manifest.write_text(
            "\n".join(json.dumps(item, ensure_ascii=False) for item in records) + "\n",
            encoding="utf-8",
        )

        report = tracker.verify_manifest(self.manifest)

        self.assertFalse(report["ok"])
        self.assertRegex(
            "\n".join(report["errors"]),
            "provider_source_path.*source_dir|渠道来源.*绑定.*目录|来源路径.*目录之外",
        )

    def test_finalize只要求当前图号排空而verify要求全任务排空(self) -> None:
        tracker = self.tracker()
        self.require_api(tracker, "reserve_attempt", "stage_attempt", "fail_attempt")
        self.write_job_v2("副图-02")
        records = [
            self.create_v2_direct(
                tracker,
                image_id="副图-01",
                attempt_no=index,
                direct_index=index,
                color=color,
            )
            for index, color in enumerate(
                ((10, 20, 30), (40, 50, 60), (70, 80, 90)), start=1,
            )
        ]
        tracker.reserve_attempt(**self.reserve_kwargs(image_id="副图-02"))

        final = tracker.finalize_artifact(
            manifest_path=self.manifest,
            source_artifact_id=records[0]["artifact_id"],
            destination=self.final_dir / "定制沙发坐垫_副图_01_v01.png",
        )

        self.assertEqual(final["schema_version"], 6)
        self.assertNotIn("dispatch_mode", final, "final 应从父级推导调用模式，不重复写字段")
        self.assertTrue(Path(final["target_path"]).is_file())
        report = tracker.verify_manifest(self.manifest)
        self.assertFalse(report["ok"])
        self.assertRegex("\n".join(report["errors"]), "全任务.*未终结|图号 副图-02.*calling|尚未排空")

        tracker.fail_attempt(
            job_path=self.job_file,
            image_id="副图-02",
            attempt_no=1,
            failure_type="provider_error",
            reason="明确结束待处理调用",
        )
        drained = tracker.verify_manifest(self.manifest)
        self.assertNotRegex("\n".join(drained["errors"]), "全任务.*未终结|calling.*未终结|尚未排空")

    def test_v6_finalize把visual_checks固定为null并只依赖job终检(self) -> None:
        tracker = self.tracker()
        self.write_job_v2()
        records = [
            self.create_v2_direct(
                tracker,
                attempt_no=index,
                direct_index=index,
                color=color,
            )
            for index, color in enumerate(
                ((10, 20, 30), (40, 50, 60), (70, 80, 90)), start=1,
            )
        ]

        final = tracker.finalize_artifact(
            manifest_path=self.manifest,
            source_artifact_id=records[0]["artifact_id"],
            destination=self.final_dir / "定制沙发坐垫_副图_01_v01.png",
        )

        self.assertEqual(final["schema_version"], 6)
        self.assertIn("visual_checks", final)
        self.assertIsNone(final["visual_checks"])
        self.record_final_inspection(final)
        report = tracker.verify_manifest(self.manifest)
        self.assertTrue(report["ok"], "\n".join(report["errors"]))

    def test_verify拒绝v6_final复制父级visual_checks字典(self) -> None:
        tracker = self.tracker()
        self.write_job_v2()
        records = [
            self.create_v2_direct(
                tracker,
                attempt_no=index,
                direct_index=index,
                color=color,
            )
            for index, color in enumerate(
                ((10, 20, 30), (40, 50, 60), (70, 80, 90)), start=1,
            )
        ]
        final = tracker.finalize_artifact(
            manifest_path=self.manifest,
            source_artifact_id=records[0]["artifact_id"],
            destination=self.final_dir / "定制沙发坐垫_副图_01_v01.png",
        )
        self.record_final_inspection(final)
        manifest_records = self.read_manifest()
        manifest_records[-1]["visual_checks"] = dict(records[0]["visual_checks"])
        self.manifest.write_text(
            "\n".join(json.dumps(item, ensure_ascii=False) for item in manifest_records) + "\n",
            encoding="utf-8",
        )

        report = tracker.verify_manifest(self.manifest)

        self.assertFalse(report["ok"])
        self.assertRegex(
            "\n".join(report["errors"]),
            "v6 final.*visual_checks.*null|最终图.*visual_checks.*为空",
        )

    def test_finalize拒绝当前图号的staged未终结attempt(self) -> None:
        tracker = self.tracker()
        self.require_api(tracker, "reserve_attempt", "stage_attempt")
        self.write_job_v2()
        records = [
            self.create_v2_direct(
                tracker,
                attempt_no=index,
                direct_index=index,
                color=color,
            )
            for index, color in enumerate(
                ((10, 20, 30), (40, 50, 60), (70, 80, 90)), start=1,
            )
        ]
        tracker.reserve_attempt(**self.reserve_kwargs(
            image_id="副图-01", attempt_no=4, direct_index=1,
        ))
        source = self.png(self.source_dir / "第四版待检查.png", (1024, 1024), (90, 100, 110))
        tracker.stage_attempt(
            job_path=self.job_file, image_id="副图-01", attempt_no=4, source_path=source,
        )

        destination = self.final_dir / "定制沙发坐垫_副图_01_v01.png"
        with self.assertRaisesRegex(tracker.TrackerError, "当前图号.*未终结|staged|尚未排空"):
            tracker.finalize_artifact(
                manifest_path=self.manifest,
                source_artifact_id=records[0]["artifact_id"],
                destination=destination,
            )
        self.assertFalse(destination.exists())

    def test_cli公开原子状态命令且中文帮助完整(self) -> None:
        self.tracker()
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--help"],
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0)
        for command in ("reserve", "stage", "fail"):
            self.assertIn(command, result.stdout)
            detail = subprocess.run(
                [sys.executable, str(SCRIPT_PATH), command, "--help"],
                text=True,
                encoding="utf-8",
                capture_output=True,
                check=False,
            )
            self.assertEqual(detail.returncode, 0, detail.stderr)
            self.assertIn("--job", detail.stdout)
            self.assertNotIn("show this help message", detail.stdout.lower())
        self.assertIn("--dispatch-mode", subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "reserve", "--help"],
            text=True, encoding="utf-8", capture_output=True, check=False,
        ).stdout)
        self.assertIn("--failure-type", subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "fail", "--help"],
            text=True, encoding="utf-8", capture_output=True, check=False,
        ).stdout)

    def test_reserve公共API和CLI都不接受call_started_at(self) -> None:
        tracker = self.tracker()
        self.assertNotIn("call_started_at", inspect.signature(tracker.reserve_attempt).parameters)
        help_result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "reserve", "--help"],
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertNotIn("--call-started-at", help_result.stdout)
        capture_help = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "capture", "--help"],
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )
        self.assertEqual(capture_help.returncode, 0, capture_help.stderr)
        self.assertIn("--call-started-at", capture_help.stdout)

        self.write_job_v2()
        kwargs = self.reserve_kwargs()
        before = self.job_file.read_bytes()
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "reserve",
                "--job", str(kwargs["job_path"]),
                "--image-id", kwargs["image_id"],
                "--attempt-no", str(kwargs["attempt_no"]),
                "--dispatch-mode", kwargs["dispatch_mode"],
                "--artifact-kind", kwargs["artifact_kind"],
                "--direct-index", str(kwargs["direct_index"]),
                "--prompt-id", kwargs["prompt_id"],
                "--prompt-path", str(kwargs["prompt_path"]),
                "--source-dir", str(kwargs["source_dir"]),
                "--snapshot-path", str(kwargs["snapshot_path"]),
                "--call-started-at", datetime.now(timezone.utc).isoformat(),
            ],
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertRegex(result.stderr, "参数错误|无法识别的参数")
        self.assertEqual(self.job_file.read_bytes(), before)

    def test_stage_cli把source作为中文报错的必填参数(self) -> None:
        tracker = self.tracker()
        self.write_job_v2()
        tracker.reserve_attempt(**self.reserve_kwargs())
        before = self.job_file.read_bytes()

        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "stage",
                "--job", str(self.job_file),
                "--image-id", "副图-01",
                "--attempt-no", "1",
            ],
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertRegex(result.stderr, "参数错误.*缺少必填参数.*--source")
        self.assertEqual(self.job_file.read_bytes(), before)

    def test_job_lock_blocks_contenders_and_can_be_reacquired(self) -> None:
        tracker = self.tracker()
        lock_path = self.job_file.with_name(f".{self.job_file.name}.lock")
        holder_entered = threading.Event()
        release_holder = threading.Event()
        holder_errors: list[BaseException] = []

        def hold_lock(job: dict) -> None:
            holder_entered.set()
            if not release_holder.wait(timeout=5):
                raise AssertionError("持锁线程等待释放超时")

        def run_holder() -> None:
            try:
                tracker._mutate_job_atomic(self.job_file, hold_lock)
            except BaseException as error:
                holder_errors.append(error)

        holder = threading.Thread(target=run_holder, name="temu-job-lock-holder")
        holder.start()
        self.assertTrue(holder_entered.wait(timeout=5), "持锁线程未进入临界区")
        self.assertTrue(lock_path.is_file(), "持锁期间锁文件必须存在")

        contender_entered = threading.Event()

        def unexpected_entry(job: dict) -> None:
            contender_entered.set()

        contender_results: list[str] = []
        lock_exists_after: list[bool] = []
        try:
            for _ in range(2):
                try:
                    tracker._mutate_job_atomic(self.job_file, unexpected_entry)
                except tracker.TrackerError as error:
                    contender_results.append(str(error))
                except BaseException as error:
                    contender_results.append(type(error).__name__)
                else:
                    contender_results.append("entered")
                lock_exists_after.append(lock_path.is_file())

            self.assertEqual(2, len(contender_results))
            for message in contender_results:
                self.assertRegex(message, "正在被其他主 Session 修改")
            self.assertEqual([True, True], lock_exists_after)
            self.assertFalse(contender_entered.is_set(), "竞争者不得突破持锁线程的互斥区")
        finally:
            release_holder.set()
            holder.join(timeout=5)

        self.assertFalse(holder.is_alive(), "持锁线程未正常退出")
        self.assertEqual([], holder_errors)
        self.assertTrue(lock_path.is_file(), "持久锁文件释放后应继续保留")

        reacquired = threading.Event()
        tracker._mutate_job_atomic(self.job_file, lambda job: reacquired.set())
        self.assertTrue(reacquired.is_set(), "锁所有者释放后必须允许重新获取")

    def test_job_lock_hard_exit_releases_lock_for_next_process(self) -> None:
        tracker = self.tracker()
        child_code = """
import importlib.util
import os
import sys

script_path, job_path = sys.argv[1:]
spec = importlib.util.spec_from_file_location("artifact_tracker_child", script_path)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

def hard_exit(job):
    print("LOCKED", flush=True)
    os._exit(23)

module._mutate_job_atomic(job_path, hard_exit)
"""
        result = subprocess.run(
            [sys.executable, "-c", child_code, str(SCRIPT_PATH), str(self.job_file)],
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=5,
            check=False,
        )
        self.assertEqual(result.returncode, 23, result.stderr)
        self.assertIn("LOCKED", result.stdout)

        def persist_probe(job: dict) -> None:
            job["lock_recovery_probe"] = "parent-reacquired"

        tracker._mutate_job_atomic(self.job_file, persist_probe)
        self.assertEqual(self.read_job()["lock_recovery_probe"], "parent-reacquired")

    def test_job_lock_open_failure_reports_chinese_and_fails_closed(self) -> None:
        tracker = self.tracker()
        lock_path = self.job_file.with_name(f".{self.job_file.name}.lock")
        lock_path.mkdir()
        entered = threading.Event()

        with self.assertRaisesRegex(tracker.TrackerError, "排他锁文件无法打开"):
            tracker._mutate_job_atomic(self.job_file, lambda job: entered.set())

        self.assertFalse(entered.is_set())

    def test_job_lock_native_failure_reports_chinese_and_fails_closed(self) -> None:
        tracker = self.tracker()
        entered = threading.Event()
        if sys.platform == "win32":
            native_lock = mock.patch.object(
                tracker.msvcrt,
                "locking",
                side_effect=OSError(5, "synthetic native lock failure"),
            )
        else:
            native_lock = mock.patch.object(
                tracker.fcntl,
                "flock",
                side_effect=OSError(5, "synthetic native lock failure"),
            )

        with native_lock:
            with self.assertRaisesRegex(tracker.TrackerError, "排他锁文件无法加锁"):
                tracker._mutate_job_atomic(self.job_file, lambda job: entered.set())

        self.assertFalse(entered.is_set())

    def test_v2_capture_adopts_same_hash_target_orphan(self) -> None:
        tracker = self.tracker()
        attempt, kwargs, destination = self.prepare_v2_capture(tracker)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(Path(attempt["staged_path"]).read_bytes())

        record = tracker.capture_artifact(**kwargs)

        self.assertEqual(record["target_sha256"], self.sha256(destination))
        self.assertEqual(self.read_manifest(), [record])
        terminal = self.find_attempt("副图-01", 1)
        self.assertEqual(terminal["artifact_id"], record["artifact_id"])
        self.assertEqual(terminal["status"], "accepted")

    def test_v2_capture_blocks_different_hash_target_orphan(self) -> None:
        tracker = self.tracker()
        _, kwargs, destination = self.prepare_v2_capture(tracker)
        self.png(destination, (1024, 1024), (90, 91, 92))
        original = destination.read_bytes()

        with self.assertRaisesRegex(tracker.TrackerError, "孤儿|哈希|拒绝覆盖|目标文件已存在"):
            tracker.capture_artifact(**kwargs)

        self.assertEqual(destination.read_bytes(), original)
        self.assertFalse(self.manifest.exists())
        self.assertEqual(self.find_attempt("副图-01", 1)["status"], "staged")

    def test_v2_capture_sync_commit_failure_rolls_back_new_target_and_manifest(self) -> None:
        tracker = self.tracker()
        _, kwargs, destination = self.prepare_v2_capture(tracker)
        job_before = self.job_file.read_bytes()

        with mock.patch.object(
            tracker,
            "_commit_v2_attempt_record",
            side_effect=tracker.TrackerError("模拟同步 job commit 失败"),
        ):
            with self.assertRaisesRegex(tracker.TrackerError, "模拟同步 job commit 失败"):
                tracker.capture_artifact(**kwargs)

        self.assertFalse(destination.exists())
        self.assertFalse(self.manifest.exists())
        self.assertEqual(self.job_file.read_bytes(), job_before)
        self.assertEqual(self.find_attempt("副图-01", 1)["status"], "staged")

    def test_v2_capture_terminal_retry_is_idempotent(self) -> None:
        tracker = self.tracker()
        _, kwargs, _ = self.prepare_v2_capture(tracker)
        first = tracker.capture_artifact(**kwargs)
        manifest_before = self.manifest.read_bytes()
        job_before = self.job_file.read_bytes()

        repeated = tracker.capture_artifact(**kwargs)

        self.assertEqual(repeated["artifact_id"], first["artifact_id"])
        self.assertEqual(self.manifest.read_bytes(), manifest_before)
        self.assertEqual(self.job_file.read_bytes(), job_before)

    def test_v2_capture_replay_rejects_every_stable_field_conflict(self) -> None:
        tracker = self.tracker()
        staged_attempt, kwargs, _ = self.prepare_v2_capture(tracker)
        staged_job = self.job_file.read_bytes()
        original = tracker.capture_artifact(**kwargs)
        stable_fields = set(original) - {"artifact_id", "captured_at"}
        mutations = {
            "schema_version": 5,
            "task_id": "other-task",
            "provider": "other-provider",
            "platform": "other-platform",
            "product_name": "其他产品",
            "image_id": "副图-99",
            "image_type": "主图",
            "immutable_identity_sha256": "f" * 64,
            "approval_scope_version": 99,
            "approval_scope_sha256": "e" * 64,
            "session_id": "other-session",
            "attempt_no": 99,
            "direct_index": 2,
            "artifact_kind": "revision",
            "prompt_id": "other-prompt",
            "prompt_path": str((self.prompt_dir / "other.txt").resolve()),
            "prompt_sha256": "d" * 64,
            "call_started_at": "2026-07-21T08:03:00+00:00",
            "dispatch_mode": "serial",
            "provenance_mode": "snapshot_diff",
            "provider_source_path": str((self.source_dir / "other.png").resolve()),
            "provider_source_sha256": "c" * 64,
            "staged_at": "2026-07-21T08:04:00+00:00",
            "source_path": str((self.job_temp_dir / "staged" / "other.png").resolve()),
            "source_sha256": "b" * 64,
            "target_path": str((self.direct_dir / "other.png").resolve()),
            "target_sha256": "a" * 64,
            "width": 999,
            "height": 999,
            "status": "rejected",
            "visual_checks": {**VISUAL_CHECKS_OK, "text_correct": False},
            "inspection_session_id": "other-inspector",
            "inspection_checked_at": "2026-07-21T08:05:00+00:00",
            "inspection_notes": "不同检查结论",
            "rejection_reason": "不同拒绝原因",
            "derived_from_artifact_id": "other-parent",
            "snapshot_path": str((self.prompt_dir / "other-snapshot.json").resolve()),
            "snapshot_sha256": "9" * 64,
            "supersedes_artifact_id": "other-superseded",
            "supersession_reason": "不同替换原因",
        }
        self.assertEqual(stable_fields, set(mutations))

        for field, value in mutations.items():
            with self.subTest(field=field):
                self.job_file.write_bytes(staged_job)
                changed = copy.deepcopy(original)
                changed[field] = value
                self.manifest.write_text(
                    json.dumps(changed, ensure_ascii=False, sort_keys=True) + "\n",
                    encoding="utf-8",
                )

                with self.assertRaisesRegex(
                    tracker.TrackerError,
                    "冲突|不一致|不能恢复|孤儿|目标|清单|快照.*使用",
                ):
                    tracker.capture_artifact(**kwargs)
                self.assertEqual(self.find_attempt("副图-01", 1), staged_attempt)
                self.assertEqual(self.read_manifest(), [changed])

    def test_v2_capture_rejects_inspection_before_staged_at(self) -> None:
        tracker = self.tracker()
        attempt, kwargs, destination = self.prepare_v2_capture(tracker)
        self.assertLess(
            datetime.fromisoformat(attempt["call_started_at"]),
            datetime.fromisoformat(attempt["staged_at"]),
        )
        kwargs["inspection_checked_at"] = attempt["call_started_at"]

        with self.assertRaisesRegex(tracker.TrackerError, "检查时间.*staged|检查时间.*暂存"):
            tracker.capture_artifact(**kwargs)

        self.assertFalse(destination.exists())
        self.assertFalse(self.manifest.exists())
        self.assertEqual(self.find_attempt("副图-01", 1)["status"], "staged")

    def test_verify_reports_inspection_before_staged_at(self) -> None:
        tracker = self.tracker()
        attempt, kwargs, _ = self.prepare_v2_capture(tracker)
        record = tracker.capture_artifact(**kwargs)
        bad_time = attempt["call_started_at"]
        records = self.read_manifest()
        records[0]["inspection_checked_at"] = bad_time
        self.manifest.write_text(
            json.dumps(records[0], ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        job = self.read_job()
        job["images"][0]["execution"]["attempts"][0]["inspection_checked_at"] = bad_time
        self.write_job_data(job)

        report = tracker.verify_manifest(self.manifest)

        self.assertFalse(report["ok"])
        self.assertRegex("\n".join(report["errors"]), "staged_at|暂存.*检查|检查.*暂存")
        self.assertEqual(record["staged_at"], attempt["staged_at"])

    def test_finalize_adopts_same_hash_target_orphan(self) -> None:
        tracker = self.tracker()
        directs = self.create_three_directs(tracker)
        destination = self.final_dir / "定制沙发坐垫_副图_01_v01.png"
        first = tracker.finalize_artifact(
            manifest_path=self.manifest,
            source_artifact_id=directs[0]["artifact_id"],
            destination=destination,
        )
        orphan_bytes = destination.read_bytes()
        self.manifest.write_text(
            "\n".join(json.dumps(item, ensure_ascii=False, sort_keys=True) for item in self.read_manifest()[:-1]) + "\n",
            encoding="utf-8",
        )

        adopted = tracker.finalize_artifact(
            manifest_path=self.manifest,
            source_artifact_id=directs[0]["artifact_id"],
            destination=destination,
        )

        self.assertEqual(destination.read_bytes(), orphan_bytes)
        self.assertEqual(adopted["target_sha256"], first["target_sha256"])
        self.assertEqual(len(self.read_manifest()), 4)

    def test_finalize_blocks_different_hash_target_orphan(self) -> None:
        tracker = self.tracker()
        directs = self.create_three_directs(tracker)
        destination = self.png(
            self.final_dir / "定制沙发坐垫_副图_01_v01.png",
            (1000, 1000),
            (90, 91, 92),
        )
        original = destination.read_bytes()

        with self.assertRaisesRegex(tracker.TrackerError, "孤儿|哈希|拒绝覆盖|目标已存在"):
            tracker.finalize_artifact(
                manifest_path=self.manifest,
                source_artifact_id=directs[0]["artifact_id"],
                destination=destination,
            )

        self.assertEqual(destination.read_bytes(), original)
        self.assertEqual(len(self.read_manifest()), 3)

    def test_finalize_manifest_retry_is_idempotent(self) -> None:
        tracker = self.tracker()
        directs = self.create_three_directs(tracker)
        destination = self.final_dir / "定制沙发坐垫_副图_01_v01.png"
        first = tracker.finalize_artifact(
            manifest_path=self.manifest,
            source_artifact_id=directs[0]["artifact_id"],
            destination=destination,
        )
        manifest_before = self.manifest.read_bytes()

        repeated = tracker.finalize_artifact(
            manifest_path=self.manifest,
            source_artifact_id=directs[0]["artifact_id"],
            destination=destination,
        )

        self.assertEqual(repeated["artifact_id"], first["artifact_id"])
        self.assertEqual(self.manifest.read_bytes(), manifest_before)

    def test_finalize_sync_failure_preserves_preexisting_same_hash_orphan(self) -> None:
        tracker = self.tracker()
        directs = self.create_three_directs(tracker)
        destination = self.final_dir / "定制沙发坐垫_副图_01_v01.png"
        tracker.finalize_artifact(
            manifest_path=self.manifest,
            source_artifact_id=directs[0]["artifact_id"],
            destination=destination,
        )
        orphan_bytes = destination.read_bytes()
        direct_manifest = (
            "\n".join(json.dumps(item, ensure_ascii=False, sort_keys=True) for item in self.read_manifest()[:-1]) + "\n"
        ).encode("utf-8")
        self.manifest.write_bytes(direct_manifest)

        with mock.patch.object(
            tracker,
            "_append_manifest",
            side_effect=tracker.TrackerError("模拟 final 清单同步失败"),
        ):
            with self.assertRaisesRegex(tracker.TrackerError, "模拟 final 清单同步失败"):
                tracker.finalize_artifact(
                    manifest_path=self.manifest,
                    source_artifact_id=directs[0]["artifact_id"],
                    destination=destination,
                )

        self.assertEqual(destination.read_bytes(), orphan_bytes)
        self.assertEqual(self.manifest.read_bytes(), direct_manifest)

    def test_manifest_append_uses_atomic_replace_and_preserves_previous_bytes_on_failure(self) -> None:
        tracker = self.tracker()
        self.manifest.parent.mkdir(parents=True, exist_ok=True)
        previous = b'{"existing": true}\n'
        self.manifest.write_bytes(previous)

        with mock.patch.object(tracker.os, "replace", side_effect=OSError(5, "synthetic replace failure")):
            with self.assertRaisesRegex(tracker.TrackerError, "清单.*原子|清单.*写入|replace"):
                tracker._append_manifest(self.manifest, {"next": True})

        self.assertEqual(self.manifest.read_bytes(), previous)

    def test_manifest_lock_blocks_capture_and_is_persistent(self) -> None:
        tracker = self.tracker()
        self.assertTrue(hasattr(tracker, "_manifest_lock"), "必须提供持久 manifest 原生锁")
        _, kwargs, destination = self.prepare_v2_capture(tracker)
        entered = threading.Event()
        release = threading.Event()
        errors: list[BaseException] = []

        def hold_manifest() -> None:
            try:
                with tracker._manifest_lock(self.manifest):
                    entered.set()
                    if not release.wait(timeout=5):
                        raise AssertionError("manifest 锁等待释放超时")
            except BaseException as error:
                errors.append(error)

        holder = threading.Thread(target=hold_manifest, name="temu-manifest-lock-holder")
        holder.start()
        self.assertTrue(entered.wait(timeout=5))
        try:
            with self.assertRaisesRegex(tracker.TrackerError, "清单.*其他主 Session|manifest.*修改"):
                tracker.capture_artifact(**kwargs)
            self.assertFalse(destination.exists())
            self.assertFalse(self.manifest.exists())
        finally:
            release.set()
            holder.join(timeout=5)

        self.assertFalse(holder.is_alive())
        self.assertEqual(errors, [])
        lock_path = self.manifest.with_name(f".{self.manifest.name}.lock")
        self.assertTrue(lock_path.is_file())

    def test_capture_job_lock_conflict_happens_before_target_or_manifest_write(self) -> None:
        tracker = self.tracker()
        _, kwargs, destination = self.prepare_v2_capture(tracker)
        entered = threading.Event()
        release = threading.Event()

        def hold_job(job: dict) -> None:
            entered.set()
            if not release.wait(timeout=5):
                raise AssertionError("job 锁等待释放超时")

        holder = threading.Thread(
            target=lambda: tracker._mutate_job_atomic(self.job_file, hold_job),
            name="temu-capture-job-lock-holder",
        )
        holder.start()
        self.assertTrue(entered.wait(timeout=5))
        try:
            with self.assertRaisesRegex(tracker.TrackerError, "任务 JSON.*其他主 Session"):
                tracker.capture_artifact(**kwargs)
            self.assertFalse(destination.exists())
            self.assertFalse(self.manifest.exists())
        finally:
            release.set()
            holder.join(timeout=5)

    def test_manifest_lock_blocks_finalize_before_target_write(self) -> None:
        tracker = self.tracker()
        self.assertTrue(hasattr(tracker, "_manifest_lock"), "必须提供持久 manifest 原生锁")
        directs = self.create_three_directs(tracker)
        destination = self.final_dir / "定制沙发坐垫_副图_01_v01.png"
        entered = threading.Event()
        release = threading.Event()

        def hold_manifest() -> None:
            with tracker._manifest_lock(self.manifest):
                entered.set()
                if not release.wait(timeout=5):
                    raise AssertionError("manifest 锁等待释放超时")

        holder = threading.Thread(target=hold_manifest, name="temu-finalize-manifest-lock-holder")
        holder.start()
        self.assertTrue(entered.wait(timeout=5))
        try:
            with self.assertRaisesRegex(tracker.TrackerError, "清单.*其他主 Session|manifest.*修改"):
                tracker.finalize_artifact(
                    manifest_path=self.manifest,
                    source_artifact_id=directs[0]["artifact_id"],
                    destination=destination,
                )
            self.assertFalse(destination.exists())
        finally:
            release.set()
            holder.join(timeout=5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
