import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from PIL import Image


SCRIPT = Path(__file__).with_name("prepare_product_photos.py")
OUTPUT_DIR = "2560px拍摄图"


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
        command = [sys.executable, str(SCRIPT), "--task-root", str(self.task.resolve())]
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
