"""One-shot Seedream 5.0 Pro image generation with crash-safe request records."""

import argparse
import base64
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import threading
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from PIL import Image


API_URL = "https://ark.cn-beijing.volces.com/api/v3/images/generations"
MODEL = "doubao-seedream-5-0-pro-260628"
RETRYABLE_ERRORS = {
    (429, "RateLimitExceeded.EndpointRPMExceeded"), (429, "RateLimitExceeded.EndpointTPMExceeded"),
    (429, "ModelAccountRpmRateLimitExceeded"), (429, "ModelAccountTpmRateLimitExceeded"),
    (429, "APIAccountRpmRateLimitExceeded"), (429, "ModelAccountIpmRateLimitExceeded"),
    (429, "ServerOverloaded"), (429, "RequestBurstTooFast"), (429, "AccountRateLimitExceeded"),
    (500, "InternalServiceError"),
}


class ValidationError(ValueError):
    pass


class RunError(RuntimeError):
    pass


class UnresolvedResult(RunError):
    def __init__(self, status, code):
        super().__init__("unresolved generation response")
        self.status, self.code = status, code


class ExplicitFailure(RunError):
    def __init__(self, status, error):
        super().__init__(error.get("message") or "generation failed")
        self.status, self.code = status, error.get("code")


def now():
    return datetime.now(timezone.utc).isoformat()


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def absolute(path, name):
    path = Path(path)
    if not path.is_absolute():
        raise ValidationError(name + " must be an absolute path")
    return path


def machine_api_key():
    if sys.platform != "win32":
        return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment") as key:
            return winreg.QueryValueEx(key, "ARK_API_KEY")[0]
    except OSError:
        return None


def api_key(environ, machine_key):
    key = environ.get("ARK_API_KEY") or machine_key()
    if not key:
        raise ValidationError("ARK_API_KEY is not configured")
    return key


def input_info(role, path):
    if not role:
        raise ValidationError("input role is required")
    path = absolute(path, "input")
    if not path.is_file():
        raise ValidationError("input does not exist")
    size = path.stat().st_size
    if size > 30 * 1024 * 1024:
        raise ValidationError("input exceeds 30 MB")
    raw = path.read_bytes()
    try:
        with Image.open(Path(path)) as image:
            image.verify()
        with Image.open(Path(path)) as image:
            fmt, width, height = image.format, image.width, image.height
    except (OSError, ValueError) as exc:
        raise ValidationError("input is not a valid JPEG or PNG") from exc
    if fmt not in ("JPEG", "PNG", "MPO") or (fmt == "MPO" and path.suffix.lower() not in (".jpg", ".jpeg")):
        raise ValidationError("input must be JPEG or PNG")
    if width <= 14 or height <= 14 or not 1 / 16 <= width / height <= 16 or width * height > 36_000_000:
        raise ValidationError("input dimensions are outside API limits")
    mime = "image/jpeg" if fmt in ("JPEG", "MPO") else "image/png"
    return {
        "role": role, "path": str(path), "mime": mime, "width": width, "height": height,
        "bytes": size, "sha256": sha256(raw), "data_uri": "data:" + mime + ";base64," + base64.b64encode(raw).decode("ascii"),
    }


def record_path(output):
    return output.parent / "_records" / (output.stem + ".call.json")


def write_record(path, record):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
    with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as file:
        file.write(data)
        temp = Path(file.name)
    os.replace(temp, path)


def read_record(path):
    return json.loads(path.read_text(encoding="utf-8"))


_locks, _locks_guard = {}, threading.Lock()
_generation_slots = threading.BoundedSemaphore(8)


@contextmanager
def task_lock(output):
    path = record_path(output).with_suffix(".lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with _locks_guard:
        lock = _locks.setdefault(str(path), threading.Lock())
    if not lock.acquire(blocking=False):
        raise RunError("output task is already running")
    file = path.open("a+b")
    try:
        file.seek(0); file.write(b"0"); file.flush(); file.seek(0)
        try:
            if sys.platform == "win32":
                import msvcrt
                msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RunError("output task is already running") from exc
        try:
            yield
        finally:
            file.seek(0)
            if sys.platform == "win32": msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
            else: fcntl.flock(file.fileno(), fcntl.LOCK_UN)
    finally:
        file.close(); lock.release()


def fingerprint(prompt_sha, inputs, size):
    public_inputs = [{key: item[key] for key in ("mime", "sha256")} for item in inputs]
    return sha256(json.dumps({"prompt_sha256": prompt_sha, "inputs": public_inputs, "size": size},
                              sort_keys=True, separators=(",", ":")).encode("utf-8"))


def safe_inputs(inputs):
    return [{key: item[key] for key in ("role", "path", "mime", "width", "height", "bytes", "sha256")} for item in inputs]


def post_payload(prompt, inputs, size):
    payload = {
        "model": MODEL, "prompt": prompt, "size": size, "output_format": "png", "response_format": "url",
        "watermark": False, "optimize_prompt_options": {"mode": "standard"},
    }
    if inputs:
        images = [item["data_uri"] for item in inputs]
        payload["image"] = images[0] if len(images) == 1 else images
    return payload


def structured_error(data):
    try:
        if isinstance(data, bytes): data = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict): return None
    if isinstance(data.get("error"), dict): return data["error"]
    items = data.get("data")
    if isinstance(items, list) and len(items) == 1 and isinstance(items[0], dict) and isinstance(items[0].get("error"), dict):
        return items[0]["error"]
    return None


def request_url(payload, key, http_open):
    request = Request(API_URL, data=json.dumps(payload).encode("utf-8"), method="POST",
                      headers={"Content-Type": "application/json", "Authorization": "Bearer " + key})
    response = http_open(request, timeout=300)
    try:
        status = getattr(response, "status", 200)
        body = response.read()
    finally:
        response.close()
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UnresolvedResult(status, "invalid_json_response") from exc
    error = structured_error(data)
    if error:
        raise ExplicitFailure(status, error)
    if not 200 <= status < 300 or not isinstance(data, dict) or not isinstance(data.get("data"), list) or len(data["data"]) != 1:
        raise UnresolvedResult(status, "invalid_response_shape")
    item = data["data"][0]
    if not isinstance(item, dict):
        raise UnresolvedResult(status, "invalid_response_shape")
    if not isinstance(item.get("url"), str) or not item["url"]:
        raise UnresolvedResult(status, "missing_response_url")
    return item["url"], status


def matching_pending_output(output, pending, size):
    if not isinstance(pending, dict) or not output.is_file():
        return None
    raw = output.read_bytes()
    expected = (1024, 1024) if size == "1K" else (2048, 2048)
    if (pending.get("bytes") != len(raw) or pending.get("sha256") != sha256(raw)
            or (pending.get("width"), pending.get("height")) != expected):
        return None
    try:
        with Image.open(io.BytesIO(raw)) as image:
            image.load()
            if image.format != "PNG" or image.size != expected:
                return None
    except (OSError, ValueError):
        return None
    return raw


def complete_download(record, path, raw, audit, size):
    completed_at = now()
    audit.update(download_completed_at=audit.get("download_completed_at") or completed_at, status="completed")
    record.update(state="completed", completed_at=completed_at,
                  download_completed_at=audit["download_completed_at"], download_elapsed_ms=audit.get("elapsed_ms"),
                  output_width=1024 if size == "1K" else 2048, output_height=1024 if size == "1K" else 2048,
                  output_bytes=len(raw), output_sha256=sha256(raw), error_code=None)
    write_record(path, record)


def download(record, path, output, http_open, size):
    if output.exists():
        raw = matching_pending_output(output, record.get("pending_output"), size)
        if raw is None:
            raise RunError("existing output does not match pending download")
        complete_download(record, path, raw, record["downloads"][-1], size)
        return output
    if record["download_attempt_count"] >= 2:
        raise RunError("download attempt limit reached")
    record["download_attempt_count"] += 1
    started = time.monotonic()
    record.setdefault("downloads", []).append({"started_at": now(), "http_status": None, "error_code": None})
    audit = record["downloads"][-1]
    write_record(path, record)
    temp = None
    try:
        response = http_open(record["temporary_url"], timeout=120)
        try:
            body = response.read()
            status = getattr(response, "status", 200)
        finally:
            response.close()
        audit["http_status"] = status
        if not 200 <= status < 300:
            raise OSError("image download HTTP " + str(status))
        with Image.open(io.BytesIO(body)) as image:
            image.load()
            if image.format != "PNG" or image.size != ((1024, 1024) if size == "1K" else (2048, 2048)):
                raise ValidationError("downloaded image is not the requested PNG size")
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("wb", dir=output.parent, suffix=".png", delete=False) as file:
            file.write(body)
            temp = Path(file.name)
        audit.update(download_completed_at=now(), elapsed_ms=round((time.monotonic() - started) * 1000),
                     status="validated")
        record.update(pending_output={"bytes": len(body), "sha256": sha256(body),
                                      "width": image.width, "height": image.height})
        write_record(path, record)
        os.link(temp, output)
    except HTTPError as exc:
        audit["http_status"] = exc.code
        audit.update(download_completed_at=now(), elapsed_ms=round((time.monotonic() - started) * 1000), error_code=type(exc).__name__)
        record.update(state="download_pending", download_elapsed_ms=audit["elapsed_ms"], error_code=audit["error_code"])
        write_record(path, record)
        raise RunError("image download is pending recovery") from exc
    except Exception as exc:
        audit.update(download_completed_at=now(), elapsed_ms=round((time.monotonic() - started) * 1000), error_code=type(exc).__name__)
        record.update(state="download_pending", download_elapsed_ms=audit["elapsed_ms"], error_code=audit["error_code"])
        write_record(path, record)
        raise RunError("image download is pending recovery") from exc
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)
    complete_download(record, path, body, audit, size)
    return output


def _run_unlocked(prompt_file, output, inputs=(), size="1K", http_open=urlopen, environ=os.environ, machine_key=machine_api_key):
    prompt_file, output = absolute(prompt_file, "prompt-file"), absolute(output, "output")
    if output.suffix.lower() != ".png":
        raise ValidationError("output must be a .png path")
    if size not in ("1K", "2K"):
        raise ValidationError("size must be 1K or 2K")
    if not prompt_file.is_file():
        raise ValidationError("prompt-file does not exist")
    prompt_raw = prompt_file.read_bytes()
    try:
        prompt = prompt_raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValidationError("prompt-file must be UTF-8") from exc
    if not 0 <= len(inputs) <= 10:
        raise ValidationError("provide between 0 and 10 inputs")
    details = [input_info(role, source) for role, source in inputs]
    prompt_sha = sha256(prompt_raw)
    request_fingerprint = fingerprint(prompt_sha, details, size)
    path = record_path(output)

    created = False
    key = None
    try:
        record = read_record(path)
    except FileNotFoundError:
        if output.exists():
            raise RunError("output already exists without a request record")
        key = api_key(environ, machine_key)
        record = {
            "state": "calling", "attempt_count": 0, "download_attempt_count": 0,
            "request_fingerprint": request_fingerprint, "prompt_path": str(prompt_file), "prompt_sha256": prompt_sha,
            "inputs": safe_inputs(details), "size": size, "output_path": str(output), "output_format": "png",
            "submitted_at": None, "generation_completed_at": None, "download_completed_at": None, "completed_at": None,
            "attempts": [], "downloads": [],
        }
        write_record(path, record)
        created = True

    state = record.get("state")
    if state == "completed":
        if record.get("request_fingerprint") == request_fingerprint and output.is_file() and sha256(output.read_bytes()) == record.get("output_sha256"):
            return output
        raise RunError("completed record does not match output")
    if state == "calling" and not created:
        raise RunError("previous generation result is unresolved")
    if state == "unresolved" and record["attempt_count"]:
        raise RunError("previous generation result is unresolved")
    if state == "download_pending":
        return download(record, path, output, http_open, record["size"])
    if state == "failed":
        if not record.get("retry_eligible") or record["attempt_count"] != 1 or record.get("request_fingerprint") == request_fingerprint:
            raise RunError("failed generation requires a changed request")
        key = api_key(environ, machine_key)
        record.update(state="calling", request_fingerprint=request_fingerprint, prompt_path=str(prompt_file),
                      prompt_sha256=prompt_sha, inputs=safe_inputs(details), size=size, error_code=None)
        write_record(path, record)
    elif state != "calling":
        raise RunError("invalid request record")

    payload = post_payload(prompt, details, size)
    while record["attempt_count"] < 2:
        with _generation_slots:
            record["attempt_count"] += 1
            record["state"] = "calling"
            started = time.monotonic()
            audit = {"submitted_at": now(), "generation_completed_at": None, "elapsed_ms": None,
                     "http_status": None, "error_code": None}
            record.setdefault("attempts", []).append(audit)
            record["submitted_at"] = audit["submitted_at"]
            write_record(path, record)
            try:
                url, status = request_url(payload, key, http_open)
            except HTTPError as exc:
                error = structured_error(exc.read())
                record.update(generation_elapsed_ms=round((time.monotonic() - started) * 1000),
                              post_http_status=exc.code, error_code=(error or {}).get("code"))
                if error:
                    audit.update(generation_completed_at=now(), elapsed_ms=record["generation_elapsed_ms"],
                                 http_status=exc.code, error_code=error.get("code"))
                    record["generation_completed_at"] = audit["generation_completed_at"]
                if error and (exc.code, error.get("code")) in RETRYABLE_ERRORS and record["attempt_count"] < 2:
                    write_record(path, record)
                    continue
                if error:
                    record.update(state="failed", retry_eligible=record["attempt_count"] == 1,
                                  generation_completed_at=audit["generation_completed_at"])
                    write_record(path, record)
                    raise RunError("generation request failed") from exc
                audit.update(elapsed_ms=record["generation_elapsed_ms"], http_status=exc.code,
                             error_code="invalid_error_response")
                record.update(state="unresolved", retry_eligible=False)
                write_record(path, record)
                raise RunError("generation result is unresolved") from exc
            except ExplicitFailure as exc:
                audit.update(generation_completed_at=now(),
                             elapsed_ms=round((time.monotonic() - started) * 1000),
                             http_status=exc.status, error_code=exc.code)
                record.update(generation_completed_at=audit["generation_completed_at"],
                              generation_elapsed_ms=audit["elapsed_ms"], post_http_status=exc.status,
                              error_code=exc.code)
                if (exc.status, exc.code) in RETRYABLE_ERRORS and record["attempt_count"] < 2:
                    write_record(path, record)
                    continue
                record.update(state="failed", retry_eligible=record["attempt_count"] == 1)
                write_record(path, record)
                raise RunError("generation request failed") from exc
            except UnresolvedResult as exc:
                audit.update(generation_completed_at=now(),
                             elapsed_ms=round((time.monotonic() - started) * 1000),
                             http_status=exc.status, error_code=exc.code)
                record.update(state="unresolved", retry_eligible=False,
                              generation_completed_at=audit["generation_completed_at"],
                              generation_elapsed_ms=audit["elapsed_ms"], post_http_status=exc.status,
                              error_code=exc.code)
                write_record(path, record)
                raise RunError("generation result is unresolved") from exc
            except (URLError, TimeoutError, OSError, RunError) as exc:
                audit.update(elapsed_ms=round((time.monotonic() - started) * 1000),
                             error_code=type(exc).__name__)
                record.update(state="unresolved", retry_eligible=False,
                              generation_elapsed_ms=audit["elapsed_ms"], error_code=type(exc).__name__)
                write_record(path, record)
                raise RunError("generation result is unresolved") from exc
            record.update(state="download_pending", temporary_url=url, post_http_status=status,
                          generation_completed_at=now(),
                          generation_elapsed_ms=round((time.monotonic() - started) * 1000),
                          error_code=None)
            audit.update(generation_completed_at=record["generation_completed_at"],
                         elapsed_ms=record["generation_elapsed_ms"], http_status=status, status="completed")
            write_record(path, record)
        return download(record, path, output, http_open, size)
    raise RunError("generation retry limit reached")


def run(prompt_file, output, inputs=(), size="1K", http_open=urlopen, environ=os.environ, machine_key=machine_api_key):
    output = absolute(output, "output")
    with task_lock(output):
        return _run_unlocked(prompt_file, output, inputs, size, http_open, environ, machine_key)


def parse_input(value):
    role, separator, source = value.partition("=")
    if not separator:
        raise argparse.ArgumentTypeError("input must be role=absolute-path")
    return role, Path(source)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt-file", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--input", action="append", type=parse_input, default=[])
    parser.add_argument("--size", choices=("1K", "2K"), default="1K")
    args = parser.parse_args(argv)
    try:
        run(args.prompt_file, args.output, args.input, args.size)
    except (ValidationError, RunError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    main()
