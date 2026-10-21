#!/usr/bin/env python3
"""Generate or edit a raster image by calling the local OpenAI Codex CLI.

This is the executable half of the ``codex-imagegen`` agent skill.  It runs
``codex exec`` in a throw-away working directory, asks Codex to use its built-in
``image_gen`` tool exactly once, locates the generated file from the Codex
thread id, and copies it atomically to ``--out``.

It intentionally refuses to run inside a Codex session so Codex cannot recurse
into itself: Codex must call its own built-in tool directly.

Requires Python 3.8+ and a logged-in Codex CLI.  Pillow is optional and is only
needed for ``--fit`` or for converting to a different output format.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shlex
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SCRIPT_VERSION = "1.0.0"

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_SELF_CALL = 3
EXIT_CODEX_NOT_FOUND = 4
EXIT_CODEX_FAILED = 5
EXIT_TIMEOUT = 6
EXIT_NO_IMAGE = 7
EXIT_OUT_EXISTS = 8
EXIT_MULTIPLE_IMAGES = 9
EXIT_INVALID_IMAGE = 10
EXIT_POSTPROCESS = 11
EXIT_INVALID_INPUT = 12

EXIT_NAMES = {
    EXIT_OK: "ok",
    EXIT_USAGE: "usage",
    EXIT_SELF_CALL: "self_call_refused",
    EXIT_CODEX_NOT_FOUND: "codex_not_found",
    EXIT_CODEX_FAILED: "codex_failed",
    EXIT_TIMEOUT: "timeout",
    EXIT_NO_IMAGE: "no_image",
    EXIT_OUT_EXISTS: "out_exists",
    EXIT_MULTIPLE_IMAGES: "multiple_images",
    EXIT_INVALID_IMAGE: "invalid_image",
    EXIT_POSTPROCESS: "postprocess_failed",
    EXIT_INVALID_INPUT: "invalid_input",
}

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
SUFFIX_FORMAT = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".webp": "WEBP"}
CODEX_MARKERS = ("CODEX_THREAD_ID", "CODEX_SESSION_ID", "CODEX_TOOL_CALL_ID")

ARGS = None  # set in main(), used by fail()


# --------------------------------------------------------------------------- #
# Output helpers
# --------------------------------------------------------------------------- #


def _reconfigure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def emit(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def fail(code: int, message: str, hint: str = None, extra: dict = None) -> "None":
    """Report an error in the selected format and exit."""
    if ARGS is not None and getattr(ARGS, "json", False):
        payload = {
            "ok": False,
            "v": 1,
            "code": EXIT_NAMES.get(code, "error"),
            "exit_code": code,
            "error": message,
        }
        if hint:
            payload["hint"] = hint
        if extra:
            payload.update(extra)
        emit(payload)
    else:
        print("error: {}".format(message), file=sys.stderr)
        if hint:
            print("hint: {}".format(hint), file=sys.stderr)
        if extra:
            for key in ("log_dir", "stderr_tail"):
                if extra.get(key):
                    print("{}: {}".format(key, extra[key]), file=sys.stderr)
    sys.exit(code)


def inside_codex() -> dict:
    return {name: os.environ[name] for name in CODEX_MARKERS if os.environ.get(name)}


# --------------------------------------------------------------------------- #
# Small utilities
# --------------------------------------------------------------------------- #


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_size(value: str) -> tuple:
    match = re.fullmatch(r"\s*(\d{2,5})\s*[xX]\s*(\d{2,5})\s*", value or "")
    if not match:
        raise ValueError("expected WIDTHxHEIGHT, for example 1536x1024")
    width, height = int(match.group(1)), int(match.group(2))
    if width < 64 or height < 64:
        raise ValueError("width and height must be at least 64 pixels")
    if width > 8192 or height > 8192:
        raise ValueError("width and height must not exceed 8192 pixels")
    return width, height


def image_dimensions(path: Path):
    """Best-effort PNG/JPEG/WebP dimension reader (stdlib only)."""
    try:
        with open(path, "rb") as handle:
            head = handle.read(32)
            if head.startswith(b"\x89PNG\r\n\x1a\n"):
                handle.seek(16)
                width, height = struct.unpack(">II", handle.read(8))
                return int(width), int(height)

            if head.startswith(b"\xff\xd8"):
                handle.seek(2)
                while True:
                    byte = handle.read(1)
                    while byte and byte != b"\xff":
                        byte = handle.read(1)
                    while byte == b"\xff":
                        byte = handle.read(1)
                    if not byte:
                        return None, None
                    marker = byte[0]
                    if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
                        continue
                    length_bytes = handle.read(2)
                    if len(length_bytes) != 2:
                        return None, None
                    length = int.from_bytes(length_bytes, "big")
                    if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                                  0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                        handle.read(1)
                        height = int.from_bytes(handle.read(2), "big")
                        width = int.from_bytes(handle.read(2), "big")
                        return width, height
                    handle.seek(max(length - 2, 0), 1)

            if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
                chunk = head[12:16]
                if chunk == b"VP8X":
                    width = 1 + int.from_bytes(head[24:27], "little")
                    height = 1 + int.from_bytes(head[27:30], "little")
                    return width, height
                if chunk == b"VP8 ":
                    handle.seek(26)
                    width = int.from_bytes(handle.read(2), "little") & 0x3FFF
                    height = int.from_bytes(handle.read(2), "little") & 0x3FFF
                    return width, height
                if chunk == b"VP8L":
                    handle.seek(21)
                    bits = int.from_bytes(handle.read(4), "little")
                    width = (bits & 0x3FFF) + 1
                    height = ((bits >> 14) & 0x3FFF) + 1
                    return width, height
    except Exception:
        pass
    return None, None


def file_magic(path: Path) -> str:
    try:
        with open(path, "rb") as handle:
            head = handle.read(12)
    except OSError:
        return ""
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head.startswith(b"\xff\xd8"):
        return "jpeg"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    return ""


def list_generated_images(gen_dir: Path) -> list:
    if not gen_dir.is_dir():
        return []
    result = []
    for path in gen_dir.iterdir():
        try:
            if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES and path.stat().st_size > 0:
                result.append(path)
        except OSError:
            continue
    return sorted(result)


def tail(text: str, lines: int = 12, chars: int = 4000) -> str:
    if not text:
        return ""
    picked = "\n".join(text.strip().splitlines()[-lines:])
    return picked[-chars:]


def resolve_codex(requested: str) -> str:
    candidate = shutil.which(requested)
    if candidate:
        return candidate
    expanded = Path(requested).expanduser()
    if expanded.is_file():
        return str(expanded)
    if requested != "codex":
        return ""
    fallbacks = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "OpenAI" / "Codex" / "bin" / "codex.exe",
        Path.home() / ".local" / "bin" / "codex",
        Path("/usr/local/bin/codex"),
        Path("/opt/homebrew/bin/codex"),
    ]
    for path in fallbacks:
        try:
            if path.is_file():
                return str(path)
        except OSError:
            continue
    return ""


def kill_tree(proc: subprocess.Popen) -> None:
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# Prompt / command construction
# --------------------------------------------------------------------------- #


BACKEND_RULES = """\
You are being used only as an image generation backend by an external agent.

- Use your built-in image_gen tool exactly once to produce the requested image.
- Do not use the image_gen CLI fallback, scripts/image_gen.py, OPENAI_API_KEY, shell commands, web search, subagents, or any other tool to create or modify the image.
- Ignore any skill that suggests calling an external Codex CLI; you are the Codex instance that must generate the image yourself.
- You may use view_image to inspect attached reference images.
- Do not move, copy, rename, delete, or post-process the generated file.
- After the tool returns, reply with the absolute path of the generated image only.
"""


def build_prompt(request: str, images: list, size: tuple) -> str:
    blocks = [BACKEND_RULES.strip(), "", "User request:", request.strip()]
    if images:
        blocks += ["", "Attached images (in order):"]
        for index, path in enumerate(images, 1):
            blocks.append("{}. {}".format(index, path))
        blocks.append(
            "The user request defines each image's role. Preserve every stated invariant."
        )
    if size:
        width, height = size
        divisor = math.gcd(width, height) or 1
        blocks += [
            "",
            "Target aspect ratio: {}:{} ({}x{}). Compose and frame the image for this "
            "ratio; do not add letterboxing, padding, or borders.".format(
                width // divisor, height // divisor, width, height
            ),
        ]
    return "\n".join(blocks).strip() + "\n"


def build_command(codex: str, workdir: Path, prompt: str, images: list, model: str,
                  isolated: bool) -> list:
    command = [
        codex,
        "exec",
        "--json",
        "--skip-git-repo-check",
        "--sandbox",
        "read-only",
        "--color",
        "never",
        "-C",
        str(workdir),
    ]
    if model:
        command += ["--model", model]
    if isolated:
        command += ["--ignore-user-config"]
    # The prompt must come before --image: --image is variadic in codex-cli
    # 0.163 and would otherwise swallow the prompt as another image path.
    command.append(prompt if not prompt.startswith("-") else "\n" + prompt)
    for image in images:
        command += ["--image", str(image)]
    return command


def format_command(command: list) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline(command)
    return shlex.join(command)


# --------------------------------------------------------------------------- #
# Codex execution
# --------------------------------------------------------------------------- #


def run_codex(command: list, workdir: Path, timeout: int):
    env = os.environ.copy()
    for marker in CODEX_MARKERS:
        env.pop(marker, None)

    kwargs = dict(
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(workdir),
        env=env,
    )
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True

    started = time.monotonic()
    proc = subprocess.Popen(command, **kwargs)
    timed_out = False
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        kill_tree(proc)
        try:
            stdout, stderr = proc.communicate(timeout=10)
        except Exception:
            stdout, stderr = "", ""
    duration_ms = int((time.monotonic() - started) * 1000)
    return proc.returncode, stdout or "", stderr or "", duration_ms, timed_out


def parse_events(stdout: str):
    events = []
    thread_id = None
    for raw in stdout.splitlines():
        line = raw.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except Exception:
            continue
        events.append(event)
        if event.get("type") == "thread.started" and event.get("thread_id"):
            thread_id = event["thread_id"]
    return events, thread_id


def event_failure(events: list):
    for event in events:
        event_type = event.get("type")
        if event_type in ("turn.failed", "error"):
            return event.get("error") or event.get("message") or json.dumps(event, ensure_ascii=False)
    return None


def agent_messages(events: list):
    messages = []
    for event in events:
        if event.get("type") == "item.completed":
            item = event.get("item") or {}
            if item.get("type") == "agent_message" and item.get("text"):
                messages.append(item["text"])
    return messages


# --------------------------------------------------------------------------- #
# Image handling
# --------------------------------------------------------------------------- #


def load_pillow():
    try:
        from PIL import Image, ImageOps

        return Image, ImageOps
    except Exception:
        return None, None


def write_image(source: Path, out_path: Path, size: tuple, fit: str) -> None:
    """Copy/convert source to out_path atomically, optionally fitting to size."""
    target_size = size if (fit and fit != "none") else None
    source_suffix = source.suffix.lower()
    out_suffix = out_path.suffix.lower()
    if out_suffix not in SUFFIX_FORMAT:
        raise ValueError("unsupported output extension {!r}; use .png, .jpg, .jpeg, or .webp".format(out_path.suffix))

    same_format = SUFFIX_FORMAT.get(source_suffix) == SUFFIX_FORMAT.get(out_suffix)
    if same_format and (not target_size or image_dimensions(source) == target_size):
        temporary = out_path.with_name(".{}.{}.tmp{}".format(out_path.stem, os.getpid(), out_suffix))
        try:
            shutil.copy2(str(source), str(temporary))
            os.replace(str(temporary), str(out_path))
        finally:
            if temporary.exists():
                temporary.unlink()
        return

    Image, ImageOps = load_pillow()
    if Image is None:
        raise RuntimeError(
            "Pillow is required for --fit or format conversion; install it with: "
            "python -m pip install pillow"
        )

    output_format = SUFFIX_FORMAT[out_suffix]
    with Image.open(str(source)) as opened:
        image = ImageOps.exif_transpose(opened)
        if image.mode not in ("RGB", "RGBA"):
            image = image.convert("RGBA")
        if target_size:
            width, height = target_size
            if fit == "cover":
                image = ImageOps.fit(image, (width, height), method=Image.LANCZOS)
            elif fit == "contain":
                contained = ImageOps.contain(image, (width, height), method=Image.LANCZOS)
                if contained.mode != "RGBA":
                    contained = contained.convert("RGBA")
                background = (0, 0, 0, 0) if output_format in ("PNG", "WEBP") else (255, 255, 255, 255)
                canvas = Image.new("RGBA", (width, height), background)
                canvas.alpha_composite(
                    contained, ((width - contained.width) // 2, (height - contained.height) // 2)
                )
                image = canvas
        if output_format == "JPEG" and image.mode != "RGB":
            image = image.convert("RGB")
        temporary = out_path.with_name(".{}.{}.tmp{}".format(out_path.stem, os.getpid(), out_suffix))
        try:
            save_kwargs = {"format": output_format}
            if output_format == "JPEG":
                save_kwargs.update(quality=95, optimize=True)
            elif output_format == "WEBP":
                save_kwargs.update(quality=95, method=6)
            else:
                save_kwargs.update(optimize=True)
            image.save(str(temporary), **save_kwargs)
            os.replace(str(temporary), str(out_path))
        finally:
            if temporary.exists():
                temporary.unlink()


def check_image(path: Path, label: str) -> tuple:
    magic = file_magic(path)
    if not magic:
        raise ValueError("{} is not a PNG, JPEG, or WebP image".format(label))
    width, height = image_dimensions(path)
    if not width or not height:
        raise ValueError("could not read dimensions of {}".format(label))
    return width, height


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #


def command_check() -> int:
    codex = resolve_codex(ARGS.codex)
    if not codex:
        emit(
            {
                "ok": False,
                "v": 1,
                "code": "codex_not_found",
                "exit_code": EXIT_CODEX_NOT_FOUND,
                "error": "Codex CLI was not found",
                "hint": "Install Codex CLI and run `codex login`, or pass --codex with its absolute path.",
            }
        )
        return EXIT_CODEX_NOT_FOUND
    version = ""
    login = ""
    ok = False
    try:
        version_proc = subprocess.run(
            [codex, "--version"], capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=30,
        )
        version = (version_proc.stdout or version_proc.stderr).strip()
        login_proc = subprocess.run(
            [codex, "login", "status"], capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=30,
        )
        login = (login_proc.stdout or login_proc.stderr).strip()
        ok = login_proc.returncode == 0 and "logged in" in login.lower()
    except Exception as exc:
        login = str(exc)

    image_generation = None
    try:
        features_proc = subprocess.run(
            [codex, "features", "list"], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30,
        )
        if features_proc.returncode == 0:
            match = re.search(
                r"^image_generation\s+\S+\s+(true|false)\s*$",
                features_proc.stdout or "",
                re.MULTILINE,
            )
            if match:
                image_generation = match.group(1) == "true"
    except Exception:
        pass

    if image_generation is False:
        ok = False

    payload = {
        "ok": ok,
        "v": 1,
        "codex": codex,
        "version": version,
        "login": login,
        "image_generation": image_generation,
        "exit_code": EXIT_OK if ok else EXIT_CODEX_NOT_FOUND,
    }
    if not ok and image_generation is False:
        payload["code"] = "image_generation_disabled"
        payload["error"] = "Codex is installed but image generation is disabled"
        payload["hint"] = "run `codex features enable image_generation`, then retry --check"
    elif not ok:
        payload["code"] = "codex_not_logged_in"
        payload["error"] = "Codex is installed but not logged in"
    emit(payload)
    return EXIT_OK if ok else EXIT_CODEX_NOT_FOUND


def command_generate() -> int:
    started = time.monotonic()

    # 1. Inputs -------------------------------------------------------------
    if ARGS.prompt_file:
        if ARGS.prompt:
            return fail(EXIT_USAGE, "use either --prompt or --prompt-file, not both")
        try:
            request = Path(ARGS.prompt_file).expanduser().read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as exc:
            return fail(EXIT_INVALID_INPUT, "could not read --prompt-file: {}".format(exc))
    else:
        request = ARGS.prompt or ""
    request = request.strip()
    if not request:
        return fail(EXIT_INVALID_INPUT, "--prompt or --prompt-file is required")

    if not ARGS.out:
        return fail(EXIT_USAGE, "--out is required")

    try:
        size = parse_size(ARGS.size) if ARGS.size else None
    except ValueError as exc:
        return fail(EXIT_INVALID_INPUT, "invalid --size: {}".format(exc))
    if ARGS.fit != "none" and not size:
        return fail(EXIT_INVALID_INPUT, "--fit requires --size")

    images = []
    for raw in ARGS.image or []:
        path = Path(raw).expanduser()
        if not path.is_file():
            return fail(EXIT_INVALID_INPUT, "reference image not found: {}".format(path))
        images.append(path.resolve())

    # Refuse before doing anything else when called from inside Codex.  Codex
    # must use its own built-in image_gen tool; this bridge is for other agents.
    markers = inside_codex()
    if markers and not ARGS.dry_run:
        return fail(
            EXIT_SELF_CALL,
            "refusing to call Codex from inside a Codex session ({})".format(
                ", ".join("{}={}".format(k, v) for k, v in markers.items())
            ),
            hint="Codex must use its built-in image_gen tool directly. This skill is only for non-Codex harnesses.",
        )

    out_path = Path(ARGS.out).expanduser()
    try:
        out_path = out_path.resolve()
    except OSError:
        pass
    if out_path.suffix.lower() not in SUFFIX_FORMAT:
        return fail(EXIT_INVALID_INPUT, "unsupported --out extension; use .png, .jpg, .jpeg, or .webp")
    if out_path.exists() and not ARGS.force and not ARGS.dry_run:
        return fail(
            EXIT_OUT_EXISTS,
            "output already exists: {}".format(out_path),
            hint="choose a new filename, or pass --force to replace it",
        )

    # 2. Codex --------------------------------------------------------------
    codex = resolve_codex(ARGS.codex)
    if not codex:
        return fail(
            EXIT_CODEX_NOT_FOUND,
            "Codex CLI was not found",
            hint="Install Codex CLI and run `codex login`, or pass --codex with its absolute path.",
        )

    # 3. Build and run ------------------------------------------------------
    prompt = build_prompt(request, images, size)
    workdir = Path(ARGS.cwd).expanduser().resolve() if ARGS.cwd else None
    temp_workdir = None
    if workdir is None:
        temp_workdir = Path(tempfile.mkdtemp(prefix="codex-image-cwd-"))
        workdir = temp_workdir
    else:
        workdir.mkdir(parents=True, exist_ok=True)

    command = build_command(codex, workdir, prompt, images, ARGS.model, ARGS.isolated)

    if ARGS.dry_run:
        payload = {
            "ok": True,
            "v": 1,
            "dry_run": True,
            "codex": codex,
            "cwd": str(workdir),
            "command": format_command(command),
            "argv": command,
            "prompt": prompt,
            "images": [str(path) for path in images],
            "out": str(out_path),
        }
        if ARGS.json:
            emit(payload)
        else:
            print("command: {}".format(payload["command"]))
            print("cwd: {}".format(payload["cwd"]))
            print("out: {}".format(payload["out"]))
            print("--- prompt ---")
            print(prompt)
        if temp_workdir:
            shutil.rmtree(str(temp_workdir), ignore_errors=True)
        return EXIT_OK

    log_dir = Path(tempfile.mkdtemp(prefix="codex-image-log-"))
    stdout_path = log_dir / "codex-exec.jsonl"
    stderr_path = log_dir / "codex-exec.stderr.txt"
    prompt_path = log_dir / "prompt.txt"
    prompt_path.write_text(prompt, encoding="utf-8")
    saved_log_dir = None

    def log_location() -> str:
        return str(saved_log_dir) if saved_log_dir is not None else str(log_dir)

    def write_logs(stdout_text: str, stderr_text: str) -> None:
        stdout_path.write_text(stdout_text or "", encoding="utf-8")
        stderr_path.write_text(stderr_text or "", encoding="utf-8")

    def keep_or_clean(save: bool) -> None:
        nonlocal saved_log_dir
        if ARGS.save_log:
            destination = Path(ARGS.save_log).expanduser().resolve()
            destination.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(stdout_path), str(destination / "codex-exec.jsonl"))
            shutil.copy2(str(stderr_path), str(destination / "codex-exec.stderr.txt"))
            shutil.copy2(str(prompt_path), str(destination / "prompt.txt"))
            saved_log_dir = destination
            shutil.rmtree(str(log_dir), ignore_errors=True)
        elif not save:
            shutil.rmtree(str(log_dir), ignore_errors=True)

    returncode, stdout, stderr, duration_ms, timed_out = run_codex(
        command, workdir, max(10, int(ARGS.timeout))
    )
    write_logs(stdout, stderr)
    if temp_workdir:
        shutil.rmtree(str(temp_workdir), ignore_errors=True)

    if timed_out:
        keep_or_clean(True)
        return fail(
            EXIT_TIMEOUT,
            "Codex did not finish within {} seconds".format(ARGS.timeout),
            hint="retry with a larger --timeout (for example 600); do not start duplicate parallel calls",
            extra={"log_dir": log_location()},
        )
    if returncode != 0:
        keep_or_clean(True)
        combined = (stderr + "\n" + stdout).lower()
        hint = None
        if "login" in combined or "auth" in combined or "unauthorized" in combined:
            hint = "run `codex login` and confirm with `codex login status`"
        return fail(
            EXIT_CODEX_FAILED,
            "codex exec failed with exit code {}".format(returncode),
            hint=hint,
            extra={"log_dir": log_location(), "stderr_tail": tail(stderr)},
        )

    events, thread_id = parse_events(stdout)
    failure = event_failure(events)
    if failure:
        keep_or_clean(True)
        return fail(
            EXIT_CODEX_FAILED,
            "Codex reported a failed turn: {}".format(failure),
            extra={"log_dir": log_location(), "stderr_tail": tail(stderr)},
        )
    if not thread_id:
        keep_or_clean(True)
        return fail(
            EXIT_CODEX_FAILED,
            "could not find thread_id in codex exec output",
            extra={"log_dir": log_location(), "stderr_tail": tail(stderr)},
        )

    codex_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser()
    generated_dir = codex_home / "generated_images" / thread_id
    deadline = time.monotonic() + 8
    candidates = []
    while time.monotonic() < deadline:
        candidates = list_generated_images(generated_dir)
        if candidates:
            break
        time.sleep(0.15)

    if not candidates:
        keep_or_clean(True)
        return fail(
            EXIT_NO_IMAGE,
            "Codex finished but produced no image in {}".format(generated_dir),
            hint="confirm image generation is enabled and the Codex account has image quota; retry once",
            extra={"log_dir": log_location(), "thread_id": thread_id},
        )
    if len(candidates) > 1:
        keep_or_clean(True)
        return fail(
            EXIT_MULTIPLE_IMAGES,
            "Codex produced {} images in one call; refusing to guess".format(len(candidates)),
            hint="inspect the thread directory and rerun with a single-asset prompt",
            extra={
                "log_dir": log_location(),
                "thread_id": thread_id,
                "images": [str(path) for path in candidates],
            },
        )

    source = candidates[0]
    try:
        source_width, source_height = check_image(source, "generated image")
    except ValueError as exc:
        keep_or_clean(True)
        return fail(EXIT_INVALID_IMAGE, str(exc), extra={"log_dir": str(log_dir)})

    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        write_image(source, out_path, size, ARGS.fit)
    except Exception as exc:
        keep_or_clean(True)
        return fail(
            EXIT_POSTPROCESS,
            "could not write output: {}".format(exc),
            hint="for --fit or format conversion install Pillow: python -m pip install pillow",
            extra={"log_dir": log_location()},
        )

    try:
        out_width, out_height = check_image(out_path, "output image")
    except ValueError as exc:
        keep_or_clean(True)
        return fail(EXIT_INVALID_IMAGE, str(exc), extra={"log_dir": str(log_dir)})

    if size and ARGS.fit != "none" and (out_width, out_height) != size:
        keep_or_clean(True)
        return fail(
            EXIT_POSTPROCESS,
            "post-processing produced {}x{}, expected {}x{}".format(
                out_width, out_height, size[0], size[1]
            ),
            extra={"log_dir": log_location()},
        )

    output_sha = sha256_file(out_path)
    source_sha = sha256_file(source)
    total_ms = int((time.monotonic() - started) * 1000)

    keep_or_clean(False)

    payload = {
        "ok": True,
        "v": 1,
        "out": str(out_path),
        "source": str(source),
        "thread_id": thread_id,
        "width": out_width,
        "height": out_height,
        "source_width": source_width,
        "source_height": source_height,
        "requested_size": "{}x{}".format(size[0], size[1]) if size else None,
        "size_match": (out_width, out_height) == size if size else None,
        "fit": ARGS.fit,
        "bytes": out_path.stat().st_size,
        "sha256": output_sha,
        "source_sha256": source_sha,
        "duration_ms": total_ms,
        "codex_duration_ms": duration_ms,
        "codex": codex,
        "model": ARGS.model,
        "codex_exit": returncode,
        "log_dir": log_location() if ARGS.save_log else None,
    }

    if ARGS.json:
        emit(payload)
    else:
        print("generated: {}".format(out_path))
        print("  size: {}x{}  bytes: {}  time: {:.1f}s".format(
            out_width, out_height, payload["bytes"], total_ms / 1000.0))
        if size and ARGS.fit == "none":
            print("  requested: {}x{} (native size kept; use --fit cover for exact pixels)".format(
                size[0], size[1]))
        print("  source: {}".format(source))
        print("  thread: {}".format(thread_id))
        print("  sha256: {}".format(output_sha))
    return EXIT_OK


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="codex_image.py",
        description=(
            "Generate or edit a raster image through the local Codex CLI. "
            "Codex must not run this script; it is for non-Codex harnesses."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  codex_image.py --prompt \"a ceramic mug on stone\" --out hero.png\n"
            "  codex_image.py --prompt \"make the background navy\" --image in.png --out out.png\n"
            "  codex_image.py --prompt \"wide alpine lake\" --out hero.png --size 1536x1024 --fit cover --json\n"
            "  codex_image.py --check\n"
        ),
    )
    parser.add_argument("--prompt", help="image request (or use --prompt-file)")
    parser.add_argument("--prompt-file", help="UTF-8 file containing the image request")
    parser.add_argument("--out", help="output image path (.png, .jpg, .jpeg, .webp)")
    parser.add_argument("-i", "--image", action="append", default=[], metavar="FILE",
                        help="reference or edit input image; repeatable; order matters")
    parser.add_argument("--size", metavar="WxH",
                        help="target size/aspect ratio, e.g. 1536x1024")
    parser.add_argument("--fit", choices=["none", "cover", "contain"], default="none",
                        help="exact-size post-processing (requires Pillow); default: none")
    parser.add_argument("--model", help="Codex agent model override (passed to codex exec -m)")
    parser.add_argument("--timeout", type=int, default=300,
                        help="seconds to wait for codex exec (default: 300)")
    parser.add_argument("--cwd", help="working directory for codex exec (default: temporary dir)")
    parser.add_argument("--codex", default="codex",
                        help="Codex CLI executable or absolute path (default: codex on PATH)")
    parser.add_argument("--isolated", action="store_true",
                        help="pass --ignore-user-config to codex exec (less overhead, but ignores the user's Codex model/provider config)")
    parser.add_argument("--json", action="store_true", help="print one JSON object to stdout")
    parser.add_argument("--force", action="store_true", help="overwrite an existing --out file")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the exact codex command and prompt without running it")
    parser.add_argument("--check", action="store_true",
                        help="check that Codex is installed and logged in, then exit")
    parser.add_argument("--save-log", metavar="DIR",
                        help="write codex-exec.jsonl, stderr, and prompt.txt to this directory")
    parser.add_argument("--debug", action="store_true", help="show a traceback on unexpected errors")
    parser.add_argument("--version", action="version", version="codex_image.py {}".format(SCRIPT_VERSION))
    return parser


def main(argv: list) -> int:
    global ARGS
    _reconfigure_stdio()
    parser = build_parser()
    ARGS = parser.parse_args(argv)

    if ARGS.check:
        return command_check()

    try:
        return command_generate()
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    except Exception as exc:
        if ARGS.debug:
            raise
        return fail(EXIT_POSTPROCESS, "unexpected failure: {}".format(exc))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
