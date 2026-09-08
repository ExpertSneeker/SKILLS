"""Prepare traceable 2560px images without exposing originals."""

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tempfile

from PIL import Image, ImageOps


MAX_LONG_EDGE = 2560
OUTPUT_DIR_NAME = "2560px拍摄图"
MANIFEST_NAME = "_manifest.json"
LOCK_NAME = "_prepare.lock"
SHORTCUT_NAME = "产品拍摄原图.lnk"
SOURCE_DIR_NAME = "产品拍摄原图"
SOURCE_DIR_ALIASES = {"产品实拍图", "实拍图", "拍摄图", "产品拍摄图"}
FORMATS = {".jpg": {"JPEG", "MPO"}, ".jpeg": {"JPEG", "MPO"}, ".png": {"PNG"}}


class PreparationError(RuntimeError):
    pass


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def directory(path, name):
    path = Path(path)
    if not path.is_absolute():
        raise PreparationError(name + " must be an absolute path")
    path = path.resolve()
    if not path.is_dir():
        raise PreparationError(name + " does not exist")
    return path


def resolve_shortcut(path):
    if sys.platform != "win32":
        raise PreparationError("--source is required outside Windows")
    if not path.is_file():
        raise PreparationError(str(path) + " does not exist; pass --source")
    command = (
        "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8;"
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:INIT_2560PX_IMAGE_SHORTCUT);"
        "[Console]::Write($s.TargetPath)"
    )
    environment = os.environ.copy()
    environment["INIT_2560PX_IMAGE_SHORTCUT"] = str(path)
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    target = result.stdout.strip()
    if result.returncode or not target:
        raise PreparationError("cannot resolve " + str(path))
    return directory(target, "shortcut target for " + str(path))


def discover_source(task_root, source):
    if source is not None:
        return directory(source, "source"), None
    shortcut = task_root / SHORTCUT_NAME
    if shortcut.is_file():
        return resolve_shortcut(shortcut), shortcut
    folder = task_root / SOURCE_DIR_NAME
    if folder.is_dir():
        return folder.resolve(), None
    alternatives = sorted(
        (path for path in task_root.iterdir()
         if path.name in SOURCE_DIR_ALIASES and path.is_dir()),
        key=lambda path: path.name,
    )
    if len(alternatives) == 1:
        return alternatives[0].resolve(), None
    if alternatives:
        raise PreparationError("multiple photo directories found; pass --source: "
                               + ", ".join(str(path) for path in alternatives))
    raise PreparationError("no original photo directory or " + SHORTCUT_NAME
                           + " found; pass --source")


def collect_images(source_root, task_root, target_root):
    """Expand directory shortcuts into stable, alias-prefixed output paths."""
    candidates = []
    destinations = {}
    target_root = target_root.resolve()

    def walk(folder, relative, ancestors):
        folder = folder.resolve()
        if (folder == task_root or folder.is_relative_to(target_root)
                or target_root.is_relative_to(folder)):
            raise PreparationError("source overlaps the task/output directory: " + str(folder))
        if folder in ancestors:
            raise PreparationError("source directory shortcut cycle: " + str(folder))
        ancestors = ancestors | {folder}
        for path in sorted(folder.iterdir(), key=lambda item: (item.name.casefold(), item.name)):
            if path.is_dir():
                walk(path, relative / path.name, ancestors)
            elif path.suffix.lower() == ".lnk":
                walk(resolve_shortcut(path), relative / path.stem, ancestors)
            elif path.suffix.lower() in FORMATS and path.is_file():
                output = (relative / path.name).as_posix()
                target_path(target_root, output)
                key = output.casefold()
                if key in destinations:
                    raise PreparationError("output path collision: " + output + " from "
                                           + str(destinations[key]) + " and " + str(path))
                destinations[key] = path
                candidates.append((path.resolve(), output))

    walk(source_root, PurePosixPath(), set())
    return sorted(candidates, key=lambda item: (item[1].casefold(), item[1]))


@contextmanager
def task_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    file = path.open("a+b")
    if path.stat().st_size == 0:
        file.seek(0)
        file.write(b"0")
        file.flush()
    file.seek(0)
    try:
        try:
            if sys.platform == "win32":
                import msvcrt
                msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise PreparationError("image preparation is already running") from exc
        try:
            yield
        finally:
            file.seek(0)
            if sys.platform == "win32":
                msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(file.fileno(), fcntl.LOCK_UN)
    finally:
        file.close()


def read_manifest(path, source_root, target_root):
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if (
        manifest.get("version") != 2
        or manifest.get("max_long_edge") != MAX_LONG_EDGE
        or manifest.get("source_root") != str(source_root)
        or manifest.get("target_root") != "."
    ):
        return {}
    entries = {}
    for item in manifest.get("files", []):
        relative = item.get("target_path")
        target_path(target_root, relative)
        if item.get("relative_path") != relative:
            raise PreparationError("manifest target_path must match relative_path")
        entries[relative] = item
    return entries


def write_json_atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as file:
            json.dump(value, file, ensure_ascii=False, sort_keys=True, indent=2)
            file.write("\n")
            temp = Path(file.name)
        os.replace(temp, path)
    finally:
        if temp and temp.exists():
            temp.unlink()


def atomic_copy(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(dir=target.parent, suffix=target.suffix)
    os.close(handle)
    temp = Path(name)
    try:
        shutil.copy2(source, temp)
        os.replace(temp, target)
    finally:
        if temp.exists():
            temp.unlink()


def image_info(path):
    try:
        with Image.open(path) as image:
            image_format = image.format
            if image_format not in FORMATS[path.suffix.lower()]:
                raise PreparationError(str(path) + ": format does not match its extension")
            oriented = ImageOps.exif_transpose(image)
            oriented.load()
            return image_format, oriented.size
    except PreparationError:
        raise
    except (OSError, ValueError, SyntaxError) as exc:
        raise PreparationError(str(path) + ": cannot decode supported image") from exc


def resize_atomic(source, target, image_format, target_size):
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(dir=target.parent, suffix=target.suffix)
    os.close(handle)
    temp = Path(name)
    try:
        with Image.open(source) as image:
            oriented = ImageOps.exif_transpose(image)
            oriented.load()
            resized = oriented.resize(target_size, Image.Resampling.LANCZOS)
            exif = oriented.getexif()
            save = {"icc_profile": image.info.get("icc_profile")}
            if exif:
                save["exif"] = exif.tobytes()
            save = {key: value for key, value in save.items() if value is not None}
            if image_format in ("JPEG", "MPO"):
                if resized.mode not in ("RGB", "L", "CMYK"):
                    resized = resized.convert("RGB")
                resized.save(temp, "JPEG", quality=95, optimize=True, **save)
            else:
                resized.save(temp, "PNG", **save)
        os.replace(temp, target)
    finally:
        if temp.exists():
            temp.unlink()


def target_path(root, relative_path):
    if not isinstance(relative_path, str) or not relative_path:
        raise PreparationError("target_path must be a nonempty relative POSIX path")
    relative = PurePosixPath(relative_path)
    if (relative.is_absolute() or "\\" in relative_path or ":" in relative_path
            or ".." in relative.parts or relative_path == "."
            or relative.as_posix() != relative_path):
        raise PreparationError("target_path must be a canonical relative POSIX path")
    root = Path(root).resolve()
    target = root.joinpath(*relative.parts).resolve()
    if not target.is_relative_to(root):
        raise PreparationError("target_path escapes the 2560px image directory")
    return target


def valid_target(item, target):
    return target.is_file() and sha256_file(target) == item.get("target_sha256")


def prepared_entry(source, target, relative, stat, source_sha, source_size, target_size,
                   operation, status):
    return {
        "relative_path": relative,
        "source_path": str(source),
        "target_path": relative,
        "source_width": source_size[0],
        "source_height": source_size[1],
        "target_width": target_size[0],
        "target_height": target_size[1],
        "source_bytes": stat.st_size,
        "source_mtime_ns": stat.st_mtime_ns,
        "target_bytes": target.stat().st_size,
        "source_sha256": source_sha,
        "target_sha256": sha256_file(target),
        "operation": operation,
        "status": status,
    }


def prepare(task_root, source=None):
    task_root = directory(task_root, "task root")
    source_root, shortcut = discover_source(task_root, source)
    target_root = task_root / OUTPUT_DIR_NAME
    candidates = collect_images(source_root, task_root, target_root)
    if not candidates:
        raise PreparationError("no supported images found")

    target_root.mkdir(parents=True, exist_ok=True)
    manifest_path = target_root / MANIFEST_NAME
    with task_lock(target_root / LOCK_NAME):
        previous = read_manifest(manifest_path, source_root, target_root)
        files = []
        for source_path, relative in candidates:
            target = target_path(target_root, relative)
            stat = source_path.stat()
            old = previous.get(relative)
            if old and old.get("source_path") != str(source_path):
                old = None
            unchanged = old and old.get("source_bytes") == stat.st_size and old.get("source_mtime_ns") == stat.st_mtime_ns
            if unchanged and valid_target(old, target):
                entry = dict(old)
                entry["status"] = "reused"
                files.append(entry)
                continue

            image_format, source_size = image_info(source_path)
            source_sha = sha256_file(source_path)
            if old and old.get("source_sha256") == source_sha and valid_target(old, target):
                entry = dict(old)
                entry.update(source_bytes=stat.st_size, source_mtime_ns=stat.st_mtime_ns, status="reused")
                files.append(entry)
                continue

            if max(source_size) <= MAX_LONG_EDGE:
                atomic_copy(source_path, target)
                target_size = source_size
                operation = "copied"
            else:
                scale = MAX_LONG_EDGE / max(source_size)
                target_size = tuple(max(1, round(value * scale)) for value in source_size)
                resize_atomic(source_path, target, image_format, target_size)
                operation = "resized"
            files.append(prepared_entry(
                source_path, target, relative, stat, source_sha, source_size, target_size,
                operation, "created",
            ))

        manifest = {
            "version": 2,
            "max_long_edge": MAX_LONG_EDGE,
            "source_shortcut": str(shortcut) if shortcut else None,
            "source_root": str(source_root),
            "target_root": ".",
            "files": files,
        }
        write_json_atomic(manifest_path, manifest)
        return manifest


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-root", required=True, type=Path)
    parser.add_argument("--source", type=Path)
    args = parser.parse_args(argv)
    try:
        manifest = prepare(args.task_root, args.source)
    except (PreparationError, OSError) as exc:
        parser.error(str(exc))
    created = sum(item["status"] == "created" for item in manifest["files"])
    reused = len(manifest["files"]) - created
    manifest_path = args.task_root.resolve() / OUTPUT_DIR_NAME / MANIFEST_NAME
    print(f"prepared={created} reused={reused} manifest={manifest_path}")
    return 0


if __name__ == "__main__":
    main()
