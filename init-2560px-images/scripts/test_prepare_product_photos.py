import importlib.util
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image


SCRIPT = Path(__file__).with_name("prepare_product_photos.py")
OUTPUT_DIR = "2560px拍摄图"
SPEC = importlib.util.spec_from_file_location("prepare_product_photos", SCRIPT)
PREPARE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PREPARE)


class PrepareProductPhotosTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source = self.root / "source"
        self.task = self.root / "task with spaces"
        self.source.mkdir()
        self.task.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def run_script(self, source=True):
        command = [sys.executable, "-X", "utf8", str(SCRIPT), "--task-root", str(self.task.resolve())]
        if source:
            command.extend(["--source", str(self.source.resolve())])
        return subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")

    def manifest(self):
        return json.loads((self.task / OUTPUT_DIR / "_manifest.json").read_text(encoding="utf-8"))

    @staticmethod
    def jpeg(path, size=(100, 50), color="red", orientation=None):
        path.parent.mkdir(parents=True, exist_ok=True)
        exif = Image.Exif()
        if orientation:
            exif[274] = orientation
        Image.new("RGB", size, color).save(path, "JPEG", exif=exif)

    def test_copies_small_image_byte_for_byte_and_never_copies_raw(self):
        source = self.source / "angle" / "IMG_0001.JPG"
        self.jpeg(source)
        (self.source / "angle" / "IMG_0001.ARW").write_bytes(b"must not be opened")

        result = self.run_script()

        self.assertEqual(result.returncode, 0, result.stderr)
        target = self.task / OUTPUT_DIR / "angle" / source.name
        self.assertEqual(target.read_bytes(), source.read_bytes())
        self.assertFalse((self.task / OUTPUT_DIR / "angle" / "IMG_0001.ARW").exists())
        item = self.manifest()["files"][0]
        self.assertEqual(item["relative_path"], "angle/IMG_0001.JPG")
        self.assertEqual((item["source_width"], item["source_height"]), (100, 50))
        self.assertEqual((item["target_width"], item["target_height"]), (100, 50))
        self.assertEqual(item["source_sha256"], item["target_sha256"])
        self.assertEqual(item["operation"], "copied")

    def test_writes_portable_manifest_and_absolute_cli_location(self):
        source = self.source / "正面 空格" / "01.JPG"
        self.jpeg(source)
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = self.manifest()
        self.assertEqual(manifest["version"], 2)
        self.assertEqual(manifest["target_root"], ".")
        item = manifest["files"][0]
        self.assertEqual(item["target_path"], "正面 空格/01.JPG")
        self.assertEqual(item["relative_path"], item["target_path"])
        self.assertEqual(item["source_path"], str(source.resolve()))
        self.assertEqual(manifest["source_root"], str(self.source.resolve()))
        self.assertIn("manifest=" + str(self.task / OUTPUT_DIR / "_manifest.json"), result.stdout)

    def test_copied_manifest_and_cache_resolve_without_original_task_or_source(self):
        for folder, color in [("正面 空格", "red"), ("背面/细节", "blue")]:
            self.jpeg(self.source / folder / "same.jpg", color=color)
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = self.manifest()
        cache = {"version": 2, "files": [
            {"target_path": item["target_path"], "sha256": item["target_sha256"],
             "facts": "fixture product", "completeness": "完整", "viewpoint": "正面",
             "occlusion": "未见", "structure_3d": "清晰", "people": "未见"}
            for item in manifest["files"]
        ]}
        original_output = self.task / OUTPUT_DIR
        PREPARE.write_json_atomic(original_output / "_inspection_cache.json", cache)
        copied_output = self.root / "需求 B 空格" / OUTPUT_DIR
        shutil.copytree(original_output, copied_output)
        # Both moves remain inside this test's isolated temporary directory.
        for old, name in [(self.task, "old task unavailable"), (self.source, "old source unavailable")]:
            new = self.root / name
            self.assertTrue(old.resolve().is_relative_to(self.root.resolve()))
            self.assertTrue(new.resolve().is_relative_to(self.root.resolve()))
            old.rename(new)
        copied_manifest = json.loads((copied_output / "_manifest.json").read_text(encoding="utf-8"))
        copied_cache = json.loads((copied_output / "_inspection_cache.json").read_text(encoding="utf-8"))
        self.assertEqual(copied_manifest, manifest)  # Includes every original source_* value.
        self.assertEqual(copied_cache, cache)
        for item, record in zip(copied_manifest["files"], copied_cache["files"]):
            target = PREPARE.target_path(copied_output, item["target_path"])
            self.assertTrue(target.is_relative_to(copied_output.resolve()))
            self.assertEqual(record["target_path"], item["target_path"])
            self.assertEqual(PREPARE.sha256_file(target), record["sha256"])
            self.assertFalse(Path(item["source_path"]).exists())

    def test_explicit_initialization_reuses_copied_targets(self):
        self.jpeg(self.source / "front" / "same.jpg")
        self.assertEqual(self.run_script().returncode, 0)
        copied_task = self.root / "copied task"
        copied_output = copied_task / OUTPUT_DIR
        shutil.copytree(self.task / OUTPUT_DIR, copied_output)
        target = copied_output / "front" / "same.jpg"
        before = target.stat().st_mtime_ns
        with patch.object(PREPARE, "atomic_copy", side_effect=AssertionError("must reuse")), \
             patch.object(PREPARE, "resize_atomic", side_effect=AssertionError("must reuse")), \
             patch.object(PREPARE, "image_info", side_effect=AssertionError("must not decode")):
            manifest = PREPARE.prepare(copied_task, self.source)
        self.assertEqual(manifest["files"][0]["status"], "reused")
        self.assertEqual(target.stat().st_mtime_ns, before)

    def test_target_paths_reject_absolute_noncanonical_and_escaping_paths(self):
        root = self.task / OUTPUT_DIR
        root.mkdir()
        invalid = ["../outside.jpg", "nested/../../outside.jpg", "/outside.jpg",
                   "C:/outside.jpg", "C:outside.jpg", "//server/share/photo.jpg",
                   "nested\\photo.jpg", "", ".", "./photo.jpg", "nested//photo.jpg"]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(PREPARE.PreparationError):
                PREPARE.target_path(root, value)

    def test_manifest_rejects_escaping_or_inconsistent_target_records(self):
        self.jpeg(self.source / "valid.jpg")
        self.assertEqual(self.run_script().returncode, 0)
        root = self.task / OUTPUT_DIR
        manifest = self.manifest()
        for target in ["../outside.jpg", "other.jpg"]:
            with self.subTest(target=target):
                manifest["files"][0]["target_path"] = target
                PREPARE.write_json_atomic(root / "_manifest.json", manifest)
                with self.assertRaises(PREPARE.PreparationError):
                    PREPARE.read_manifest(root / "_manifest.json", self.source, root)

    def test_target_paths_reject_symlink_escape(self):
        root = self.task / OUTPUT_DIR
        root.mkdir()
        if sys.platform == "win32":
            environment = os.environ.copy()
            environment["TEST_JUNCTION_PATH"] = str(root / "escape")
            environment["TEST_JUNCTION_TARGET"] = str(self.source)
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "New-Item -ItemType Junction -Path $env:TEST_JUNCTION_PATH -Value $env:TEST_JUNCTION_TARGET -ErrorAction Stop | Out-Null"],
                env=environment, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            (root / "escape").symlink_to(self.source, target_is_directory=True)
        with self.assertRaises(PREPARE.PreparationError):
            PREPARE.target_path(root, "escape/photo.jpg")

    def test_resizes_exif_jpeg_mpo_and_png_to_correct_orientation(self):
        exif_jpeg = self.source / "rotated.JPG"
        self.jpeg(exif_jpeg, (4000, 2000), orientation=8)
        mpo = self.source / "camera.JPG"
        first = Image.new("RGB", (4000, 2000), "red")
        second = Image.new("RGB", (4000, 2000), "blue")
        first.save(mpo, format="MPO", save_all=True, append_images=[second])
        png = self.source / "tall.png"
        Image.new("RGB", (1000, 4000), "green").save(png, "PNG")

        result = self.run_script()

        self.assertEqual(result.returncode, 0, result.stderr)
        expected = {
            "rotated.JPG": ("JPEG", (1280, 2560)),
            "camera.JPG": ("JPEG", (2560, 1280)),
            "tall.png": ("PNG", (640, 2560)),
        }
        for name, (image_format, size) in expected.items():
            with self.subTest(name=name), Image.open(self.task / OUTPUT_DIR / name) as image:
                self.assertEqual(image.format, image_format)
                self.assertEqual(image.size, size)
                self.assertEqual(image.getexif().get(274, 1), 1)

    def test_preserves_relative_directories_for_duplicate_filenames(self):
        self.jpeg(self.source / "front" / "same.jpg", color="red")
        self.jpeg(self.source / "back" / "same.jpg", color="blue")

        result = self.run_script()

        self.assertEqual(result.returncode, 0, result.stderr)
        front = self.task / OUTPUT_DIR / "front" / "same.jpg"
        back = self.task / OUTPUT_DIR / "back" / "same.jpg"
        self.assertTrue(front.is_file())
        self.assertTrue(back.is_file())
        self.assertNotEqual(front.read_bytes(), back.read_bytes())
        self.assertEqual(
            [item["relative_path"] for item in self.manifest()["files"]],
            ["back/same.jpg", "front/same.jpg"],
        )

    def test_invalid_supported_image_fails_without_replacing_manifest(self):
        self.jpeg(self.source / "valid.jpg")
        first = self.run_script()
        self.assertEqual(first.returncode, 0, first.stderr)
        manifest = self.task / OUTPUT_DIR / "_manifest.json"
        previous = manifest.read_bytes()
        (self.source / "broken.jpg").write_bytes(b"not a jpeg")

        result = self.run_script()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("broken.jpg", result.stderr)
        self.assertEqual(manifest.read_bytes(), previous)

    def test_no_supported_images_fails_without_manifest(self):
        (self.source / "only.ARW").write_bytes(b"raw")

        result = self.run_script()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no supported images", result.stderr)
        self.assertFalse((self.task / OUTPUT_DIR / "_manifest.json").exists())

    def shortcut(self, link, target):
        link.parent.mkdir(parents=True, exist_ok=True)
        environment = os.environ.copy()
        environment.update(TEST_SHORTCUT=str(link), TEST_SHORTCUT_TARGET=str(target))
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:TEST_SHORTCUT);"
             "$s.TargetPath=$env:TEST_SHORTCUT_TARGET;$s.Save()"],
            env=environment, capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_auto_discovers_photo_folder_without_requiring_raw_files(self):
        for name in ["产品拍摄原图", "产品实拍图", "拍摄图"]:
            with self.subTest(name=name):
                folder = self.task / name
                self.jpeg(folder / "front.jpg")
                result = self.run_script(source=False)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.manifest()["source_root"], str(folder))
                folder.rename(self.root / name)

    def test_ambiguous_photo_folders_require_explicit_source(self):
        self.jpeg(self.task / "产品实拍图" / "a.jpg")
        self.jpeg(self.task / "拍摄图" / "b.jpg")
        result = self.run_script(source=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("multiple", result.stderr)
        self.assertIn("--source", result.stderr)
        self.assertFalse((self.task / OUTPUT_DIR).exists())

    @unittest.skipUnless(sys.platform == "win32", "Windows shortcut behavior")
    def test_photo_folder_expands_three_shortcuts_with_distinct_output_paths(self):
        folder = self.task / "产品拍摄原图"
        for name, color in [("奥利芬ARY-014", "red"), ("奥利芬bry9", "blue"),
                            ("主图产品NGLS701-013", "green")]:
            source = self.source / name / "角度" / "same.JPG"
            self.jpeg(source, color=color)
            source.with_suffix(".ARW").write_bytes(b"raw must not be decoded")
            self.shortcut(folder / (name + ".lnk"), self.source / name)
        self.jpeg(self.task / "unrelated.jpg")
        result = self.run_script(source=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = self.manifest()
        self.assertEqual(len(manifest["files"]), 3)
        self.assertEqual(manifest["source_root"], str(folder))
        for item in manifest["files"]:
            target = self.task / OUTPUT_DIR / item["target_path"]
            self.assertEqual(target.read_bytes(), Path(item["source_path"]).read_bytes())
            self.assertTrue(item["target_path"].endswith("/角度/same.JPG"))
        self.assertEqual(len({item["target_sha256"] for item in manifest["files"]}), 3)
        again = self.run_script(source=False)
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertIn("prepared=0 reused=3", again.stdout)

    @unittest.skipUnless(sys.platform == "win32", "Windows shortcut behavior")
    def test_explicit_source_mixes_photos_subfolders_and_nested_shortcuts(self):
        external = self.root / "external"
        self.jpeg(external / "remote.jpg")
        self.jpeg(self.source / "local.jpg")
        self.shortcut(self.source / "分组" / "别名.lnk", external)
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual({item["target_path"] for item in self.manifest()["files"]},
                         {"local.jpg", "分组/别名/remote.jpg"})

    @unittest.skipUnless(sys.platform == "win32", "Windows shortcut behavior")
    def test_broken_nested_shortcut_fails_before_writing_any_images(self):
        self.jpeg(self.source / "valid.jpg")
        self.shortcut(self.source / "missing.lnk", self.root / "missing")
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing.lnk", result.stderr)
        self.assertFalse((self.task / OUTPUT_DIR).exists())

    @unittest.skipUnless(sys.platform == "win32", "Windows shortcut behavior")
    def test_shortcut_cycle_fails_before_writing_any_images(self):
        self.jpeg(self.source / "valid.jpg")
        self.shortcut(self.source / "loop.lnk", self.source)
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cycle", result.stderr)
        self.assertFalse((self.task / OUTPUT_DIR).exists())

    @unittest.skipUnless(sys.platform == "win32", "Windows shortcut behavior")
    def test_shortcut_alias_collision_fails_before_overwriting(self):
        self.jpeg(self.source / "same" / "photo.jpg")
        external = self.root / "external"
        self.jpeg(external / "photo.jpg", color="blue")
        self.shortcut(self.source / "same.lnk", external)
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("collision", result.stderr)
        self.assertFalse((self.task / OUTPUT_DIR).exists())

    @unittest.skipUnless(sys.platform == "win32", "Windows shortcut behavior")
    def test_retargeted_shortcut_does_not_reuse_old_source_with_same_stat(self):
        first = self.root / "first"
        second = self.root / "second"
        self.jpeg(first / "photo.jpg", color="red")
        self.jpeg(second / "photo.jpg", color="blue")
        size = max((first / "photo.jpg").stat().st_size, (second / "photo.jpg").stat().st_size)
        for photo in [first / "photo.jpg", second / "photo.jpg"]:
            photo.write_bytes(photo.read_bytes().ljust(size, b"\0"))
            os.utime(photo, ns=(1700000000000000000, 1700000000000000000))
        link = self.source / "alias.lnk"
        self.shortcut(link, first)
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.shortcut(link, second)
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        item = self.manifest()["files"][0]
        self.assertEqual(item["source_path"], str(second / "photo.jpg"))
        self.assertEqual((self.task / OUTPUT_DIR / "alias" / "photo.jpg").read_bytes(),
                         (second / "photo.jpg").read_bytes())

    def test_reuses_unchanged_target_and_rebuilds_corruption_or_changed_source(self):
        source = self.source / "stable.jpg"
        self.jpeg(source, color="red")
        first = self.run_script()
        self.assertEqual(first.returncode, 0, first.stderr)
        target = self.task / OUTPUT_DIR / "stable.jpg"
        original_mtime = target.stat().st_mtime_ns

        second = self.run_script()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(target.stat().st_mtime_ns, original_mtime)
        self.assertEqual(self.manifest()["files"][0]["status"], "reused")

        target.write_bytes(b"corrupt")
        repaired = self.run_script()
        self.assertEqual(repaired.returncode, 0, repaired.stderr)
        self.assertEqual(target.read_bytes(), source.read_bytes())

        self.jpeg(source, color="blue")
        changed = self.run_script()
        self.assertEqual(changed.returncode, 0, changed.stderr)
        self.assertEqual(target.read_bytes(), source.read_bytes())
        self.assertEqual(self.manifest()["files"][0]["status"], "created")

    @unittest.skipUnless(sys.platform == "win32", "Windows shortcut behavior")
    def test_resolves_fixed_shortcut_and_does_not_scan_task_root(self):
        self.jpeg(self.source / "source.jpg")
        self.jpeg(self.task / "must-not-be-scanned.jpg", color="blue")
        shortcut = self.task / "产品拍摄原图.lnk"
        command = (
            "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:TEST_SHORTCUT);"
            "$s.TargetPath=$env:TEST_SHORTCUT_TARGET;$s.Save()"
        )
        environment = os.environ.copy()
        environment["TEST_SHORTCUT"] = str(shortcut)
        environment["TEST_SHORTCUT_TARGET"] = str(self.source.resolve())
        created = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        self.assertEqual(created.returncode, 0, created.stderr)

        result = self.run_script(source=False)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([item["relative_path"] for item in self.manifest()["files"]], ["source.jpg"])
        self.assertEqual(self.manifest()["source_shortcut"], str(shortcut.resolve()))

    @unittest.skipUnless(sys.platform == "win32", "Windows file lock behavior")
    def test_rejects_concurrent_run(self):
        import msvcrt

        self.jpeg(self.source / "source.jpg")
        output = self.task / OUTPUT_DIR
        output.mkdir()
        lock = (output / "_prepare.lock").open("a+b")
        lock.write(b"0")
        lock.flush()
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        try:
            result = self.run_script()
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            lock.close()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("already running", result.stderr)


if __name__ == "__main__":
    unittest.main()
