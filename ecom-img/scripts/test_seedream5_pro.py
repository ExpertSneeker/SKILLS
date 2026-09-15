import base64
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
import subprocess
import sys
from urllib.error import HTTPError, URLError

from PIL import Image


MODULE = Path(__file__).with_name("seedream5_pro.py")


def load_module():
    spec = importlib.util.spec_from_file_location("seedream5_pro", MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def png(size=(1024, 1024), color="white"):
    stream = io.BytesIO()
    Image.new("RGB", size, color).save(stream, "PNG")
    return stream.getvalue()


def wait_until(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while not predicate():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(0.01, remaining))
    return True


class Response:
    def __init__(self, body, status=200):
        self.body, self.status = body, status

    def read(self):
        return self.body

    def close(self):
        pass


class HTTP:
    def __init__(self, posts=(), gets=(), before_post=None):
        self.posts = list(posts)
        self.gets = list(gets)
        self.before_post = before_post
        self.post_requests = []
        self.get_urls = []
        self.auth = []
        self.boundaries = []

    def __call__(self, request, timeout=None):
        if hasattr(request, "data"):
            self.post_requests.append(json.loads(request.data.decode("utf-8")))
            self.auth.append(request.get_header("Authorization"))
            self.boundaries.append((request.full_url, request.get_method(), request.get_header("Content-type"), timeout))
            if self.before_post:
                self.before_post()
            result = self.posts.pop(0)
        else:
            self.get_urls.append(request)
            result = self.gets.pop(0)
        if isinstance(result, BaseException):
            raise result
        return Response(result)


def generation(url="https://temporary.example/image", size=None):
    item = {"url": url}
    if size is not None:
        item["size"] = size
    return json.dumps({"data": [item]}).encode()


def explicit_error(code, message="bad", error_code="RateLimitExceeded.EndpointRPMExceeded"):
    return HTTPError(
        "https://ark.cn-beijing.volces.com/api/v3/images/generations",
        code,
        message,
        {},
        io.BytesIO(json.dumps({"error": {"code": error_code, "message": message}}).encode()),
    )


class Seedream5ProTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.prompt = self.root / "prompt.txt"
        self.prompt.write_text("clean product photo", encoding="utf-8")
        self.output = self.root / "result.png"
        self.m = load_module()

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, http, **kwargs):
        return self.m.run(
            self.prompt, self.output, http_open=http, environ={"ARK_API_KEY": "test-secret"}, **kwargs
        )

    def test_documented_nonsquare_sizes_match_response_and_record(self):
        for tier, dimensions in (("1K", (1152, 864)), ("2K", (2368, 1776))):
            with self.subTest(tier=tier):
                output = self.root / (tier + ".png")
                reported = "%dx%d" % dimensions
                http = HTTP([generation(size=reported)], [png(dimensions)])
                self.m.run(self.prompt, output, size=tier, http_open=http,
                           environ={"ARK_API_KEY": "test-secret"})
                record = json.loads(self.m.record_path(output).read_text())
                self.assertEqual(record["response_size"], reported)
                self.assertEqual((record["output_width"], record["output_height"]), dimensions)
                self.assertEqual(record["output_sha256"], self.m.sha256(output.read_bytes()))
                self.assertEqual(record["attempt_count"], 1)

    def test_response_size_mismatch_is_not_accepted_or_reposted(self):
        with self.assertRaises(self.m.RunError):
            self.call(HTTP([generation(size="1152x864")], [png()]))
        self.assertFalse(self.output.exists())
        recovery = HTTP([], [png((1152, 864))])
        self.call(recovery)
        self.assertEqual(recovery.post_requests, [])
        self.assertEqual(len(recovery.get_urls), 1)

    def test_nonsquare_without_size_metadata_keeps_conservative_fallback(self):
        with self.assertRaises(self.m.RunError):
            self.call(HTTP([generation()], [png((1152, 864))]))
        self.assertFalse(self.output.exists())
        record = json.loads(self.m.record_path(self.output).read_text())
        self.assertEqual(record["state"], "download_pending")
        self.assertEqual(record["attempt_count"], 1)

    def test_invalid_response_size_is_unresolved_and_not_reposted(self):
        for index, value in enumerate(("0x864", "-1x864", "1152X864", "1.5K", 123, "1152x864junk")):
            with self.subTest(value=value):
                output = self.root / ("bad-%d.png" % index)
                http = HTTP([generation(size=value)], [png()])
                with self.assertRaises(self.m.RunError):
                    self.m.run(self.prompt, output, http_open=http, environ={"ARK_API_KEY": "key"})
                record = json.loads(self.m.record_path(output).read_text())
                self.assertEqual(record["state"], "unresolved")
                self.assertEqual(record["error_code"], "invalid_response_size")
                again = HTTP()
                with self.assertRaises(self.m.RunError):
                    self.m.run(self.prompt, output, http_open=again, environ={"ARK_API_KEY": "key"})
                self.assertEqual(again.post_requests + again.get_urls, [])

    def test_nonsquare_download_recovery_keeps_response_contract(self):
        with self.assertRaises(self.m.RunError):
            self.call(HTTP([generation(size="1152x864")], [URLError("offline")]))
        again = HTTP([], [png((1152, 864))])
        self.call(again)
        record = json.loads(self.m.record_path(self.output).read_text())
        self.assertEqual(again.post_requests, [])
        self.assertEqual(record["download_attempt_count"], 2)
        self.assertEqual(record["response_size"], "1152x864")
        self.assertEqual((record["output_width"], record["output_height"]), (1152, 864))

    def test_nonsquare_published_output_recovers_after_record_write_crash(self):
        write = self.m.write_record
        def crash(path, record):
            if record.get("state") == "completed":
                raise OSError("simulated final write failure")
            write(path, record)
        self.m.write_record = crash
        try:
            with self.assertRaises(OSError):
                self.call(HTTP([generation(size="1152x864")], [png((1152, 864))]))
        finally:
            self.m.write_record = write
        self.assertTrue(self.output.exists())
        no_network = HTTP()
        self.call(no_network)
        self.assertEqual(no_network.post_requests + no_network.get_urls, [])
        record = json.loads(self.m.record_path(self.output).read_text())
        self.assertEqual(record["state"], "completed")
        self.assertEqual((record["output_width"], record["output_height"]), (1152, 864))

    def test_reported_size_does_not_accept_non_png_image(self):
        stream = io.BytesIO()
        Image.new("RGB", (1152, 864)).save(stream, "JPEG")
        with self.assertRaises(self.m.RunError):
            self.call(HTTP([generation(size="1152x864")], [stream.getvalue()]))
        self.assertFalse(self.output.exists())

    def test_payload_without_inputs_defaults_to_1k_and_writes_png(self):
        http = HTTP([generation()], [png()])
        self.call(http)
        self.assertEqual(http.post_requests[0]["size"], "1K")
        self.assertNotIn("image", http.post_requests[0])
        with Image.open(self.output) as image:
            self.assertEqual(image.size, (1024, 1024))

    def test_one_input_uses_string_data_uri_and_record_redacts_secret(self):
        source = self.root / "source.jpg"
        Image.new("RGB", (30, 31), "red").save(source, "JPEG")
        http = HTTP([generation()], [png()])
        self.call(http, inputs=[("main", source)])
        body = http.post_requests[0]
        self.assertIsInstance(body["image"], str)
        self.assertTrue(body["image"].startswith("data:image/jpeg;base64,"))
        record = (self.root / "_records" / "result.call.json").read_text(encoding="utf-8")
        self.assertNotIn("test-secret", record)
        self.assertNotIn(base64.b64encode(source.read_bytes()).decode(), record)

    def test_jpg_mpo_input_is_sent_as_jpeg(self):
        source = self.root / "camera.jpg"
        first = Image.new("RGB", (30, 31), "red")
        second = Image.new("RGB", (30, 31), "blue")
        first.save(source, format="MPO", save_all=True, append_images=[second])
        http = HTTP([generation()], [png()])

        try:
            self.call(http, inputs=[("main", source)])
        except self.m.ValidationError as exc:
            self.fail(str(exc))

        self.assertTrue(http.post_requests[0]["image"].startswith("data:image/jpeg;base64,"))

    def test_many_inputs_preserve_order_and_explicit_2k(self):
        paths = []
        for name, color in [("front", "red"), ("back", "blue")]:
            path = self.root / (name + ".png")
            Image.new("RGB", (30, 31), color).save(path, "PNG")
            paths.append((name, path))
        http = HTTP([generation()], [png((2048, 2048))])
        self.call(http, inputs=paths, size="2K")
        self.assertEqual(http.post_requests[0]["size"], "2K")
        self.assertIsInstance(http.post_requests[0]["image"], list)
        self.assertEqual([item.split(",", 1)[0] for item in http.post_requests[0]["image"]],
                         ["data:image/png;base64", "data:image/png;base64"])
        with Image.open(self.output) as image:
            self.assertEqual(image.size, (2048, 2048))

    def test_payload_always_has_fixed_generation_parameters(self):
        http = HTTP([generation()], [png()])
        self.call(http)
        body = http.post_requests[0]
        self.assertEqual(body["model"], "doubao-seedream-5-0-pro-260628")
        self.assertEqual(body["output_format"], "png")
        self.assertEqual(body["response_format"], "url")
        self.assertFalse(body["watermark"])
        self.assertEqual(body["optimize_prompt_options"], {"mode": "standard"})
        self.assertNotIn("sequential_image_generation", body)
        self.assertNotIn("stream", body)
        self.assertNotIn("tools", body)

    def test_machine_key_fallback_is_used_when_environment_lacks_key(self):
        http = HTTP([generation()], [png()])
        self.m.run(self.prompt, self.output, http_open=http, environ={}, machine_key=lambda: "machine-only")
        self.assertEqual(http.auth, ["Bearer machine-only"])

    def test_missing_key_does_not_create_an_unrecoverable_calling_record(self):
        with self.assertRaises(self.m.ValidationError):
            self.m.run(self.prompt, self.output, http_open=HTTP(), environ={}, machine_key=lambda: None)
        self.assertFalse((self.root / "_records" / "result.call.json").exists())

    def test_rejects_invalid_input_count_type_and_dimensions_before_network(self):
        bad = self.root / "tiny.png"
        Image.new("RGB", (14, 30), "white").save(bad, "PNG")
        text = self.root / "bad.gif"
        text.write_bytes(b"not an image")
        for inputs in [[("x", bad)], [("x", text)], [(str(i), bad) for i in range(11)]]:
            with self.subTest(inputs=len(inputs)), self.assertRaises(self.m.ValidationError):
                self.call(HTTP(), inputs=inputs)

    def test_record_is_created_in_calling_state_before_post(self):
        seen = []
        def before_post():
            record = json.loads((self.root / "_records" / "result.call.json").read_text(encoding="utf-8"))
            seen.append(record["state"])
        self.call(HTTP([generation()], [png()], before_post))
        self.assertEqual(seen, ["calling"])

    def test_429_and_500_retry_once_then_succeed(self):
        for code, error_code in ((429, "RateLimitExceeded.EndpointRPMExceeded"), (500, "InternalServiceError")):
            with self.subTest(code=code):
                output = self.root / (str(code) + ".png")
                http = HTTP([explicit_error(code, error_code=error_code), generation()], [png()])
                self.m.run(self.prompt, output, http_open=http, environ={"ARK_API_KEY": "key"})
                record = json.loads((self.root / "_records" / (str(code) + ".call.json")).read_text())
                self.assertEqual(len(http.post_requests), 2)
                self.assertEqual(record["attempt_count"], 2)
                self.assertEqual(record["state"], "completed")

    def test_nonretryable_429_posts_once(self):
        http = HTTP([explicit_error(429, error_code="QuotaExceeded")])
        with self.assertRaises(self.m.RunError): self.call(http)
        self.assertEqual(len(http.post_requests), 1)

    def test_explicit_failure_allows_one_changed_request_manual_retry(self):
        http = HTTP([explicit_error(400)])
        with self.assertRaises(self.m.RunError):
            self.call(http)
        self.prompt.write_text("corrected prompt", encoding="utf-8")
        retry = HTTP([generation()], [png()])
        self.call(retry)
        record = json.loads((self.root / "_records" / "result.call.json").read_text())
        self.assertEqual(record["attempt_count"], 2)
        self.assertTrue(self.output.exists())

    def test_unknown_post_result_is_unresolved_and_never_reposted(self):
        with self.assertRaises(self.m.RunError):
            self.call(HTTP([URLError("offline")]))
        with self.assertRaises(self.m.RunError):
            self.call(HTTP([generation()], [png()]))
        record = json.loads((self.root / "_records" / "result.call.json").read_text())
        self.assertEqual(record["state"], "unresolved")
        self.assertEqual(record["attempt_count"], 1)

    def test_download_pending_recovers_with_get_only(self):
        with self.assertRaises(self.m.RunError):
            self.call(HTTP([generation()], [URLError("download failed")]))
        resume = HTTP([], [png()])
        self.call(resume)
        record = json.loads((self.root / "_records" / "result.call.json").read_text())
        self.assertEqual(resume.post_requests, [])
        self.assertEqual(record["download_attempt_count"], 2)
        self.assertTrue(self.output.exists())

    def test_destination_created_during_download_is_not_overwritten(self):
        external = png(color="black")
        downloaded = png()

        class RacingHTTP(HTTP):
            def __call__(inner, request, timeout=None):
                if hasattr(request, "data"):
                    return super().__call__(request, timeout)
                self.output.write_bytes(external)
                inner.get_urls.append(request)
                return Response(downloaded)

        with self.assertRaises(self.m.RunError):
            self.call(RacingHTTP([generation()]))
        self.assertEqual(self.output.read_bytes(), external)
        record = json.loads((self.root / "_records" / "result.call.json").read_text())
        self.assertEqual(record["state"], "download_pending")
        self.assertEqual(record["pending_output"]["bytes"], len(downloaded))
        self.assertEqual(record["pending_output"]["sha256"], self.m.sha256(downloaded))
        self.assertEqual((record["pending_output"]["width"], record["pending_output"]["height"]), (1024, 1024))
        no_network = HTTP()
        with self.assertRaises(self.m.RunError):
            self.call(no_network)
        self.assertEqual(no_network.post_requests + no_network.get_urls, [])
        self.assertEqual(self.output.read_bytes(), external)

    def test_published_output_recovers_without_network_after_final_record_write_crash(self):
        real_write_record = self.m.write_record
        crashed = False

        def crash_before_completed_record(path, record):
            nonlocal crashed
            if record.get("state") == "completed" and self.output.exists() and not crashed:
                crashed = True
                raise OSError("simulated record write crash")
            real_write_record(path, record)

        self.m.write_record = crash_before_completed_record
        try:
            with self.assertRaises(OSError):
                self.call(HTTP([generation()], [png()]))
        finally:
            self.m.write_record = real_write_record
        persisted = json.loads((self.root / "_records" / "result.call.json").read_text())
        self.assertEqual(persisted["state"], "download_pending")
        self.assertEqual(persisted["pending_output"]["sha256"], self.m.sha256(self.output.read_bytes()))

        no_network = HTTP()
        self.call(no_network)
        self.assertEqual(no_network.post_requests + no_network.get_urls, [])
        completed = json.loads((self.root / "_records" / "result.call.json").read_text())
        self.assertEqual(completed["state"], "completed")

    def test_completed_matching_output_is_idempotent_without_network(self):
        self.call(HTTP([generation()], [png()]))
        http = HTTP()
        self.call(http)
        self.assertEqual(http.post_requests + http.get_urls, [])

    def test_concurrent_runs_allow_one_post(self):
        entered, release = threading.Event(), threading.Event()
        outcomes, errors = [], []

        def before_post():
            entered.set()
            if not release.wait(5):
                raise TimeoutError("test did not release POST")

        http = HTTP([generation()], [png()], before_post=before_post)

        def worker():
            try:
                self.call(http)
                outcomes.append("ok")
            except self.m.RunError:
                outcomes.append("blocked")
            except BaseException as exc:
                errors.append(exc)

        first = threading.Thread(target=worker)
        second = threading.Thread(target=worker)
        first.start()
        self.assertTrue(entered.wait(5))
        second.start()
        second.join(5)
        self.assertFalse(second.is_alive())
        release.set()
        first.join(5)
        self.assertFalse(first.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(len(http.post_requests), 1)
        self.assertEqual(sorted(outcomes), ["blocked", "ok"])

    def test_changed_failed_request_is_still_serialized_to_one_repair_post(self):
        with self.assertRaises(self.m.RunError):
            self.call(HTTP([explicit_error(400)]))
        self.prompt.write_text("repaired", encoding="utf-8")
        entered, release = threading.Event(), threading.Event()
        outcomes, errors = [], []

        def before_post():
            entered.set()
            if not release.wait(5):
                raise TimeoutError("test did not release POST")

        http = HTTP([generation()], [png()], before_post=before_post)

        def worker():
            try:
                self.call(http)
                outcomes.append("ok")
            except self.m.RunError:
                outcomes.append("blocked")
            except BaseException as exc:
                errors.append(exc)

        first = threading.Thread(target=worker)
        second = threading.Thread(target=worker)
        first.start()
        self.assertTrue(entered.wait(5))
        second.start()
        second.join(5)
        self.assertFalse(second.is_alive())
        release.set()
        first.join(5)
        self.assertFalse(first.is_alive())
        self.assertEqual(errors, [])
        record = json.loads((self.root / "_records" / "result.call.json").read_text())
        self.assertEqual(len(http.post_requests), 1)
        self.assertEqual(sorted(outcomes), ["blocked", "ok"])
        self.assertEqual(record["attempt_count"], 2)

    def test_download_limit_stays_pending_and_never_reposts_after_prompt_change(self):
        with self.assertRaises(self.m.RunError):
            self.call(HTTP([generation()], [URLError("one")]))
        with self.assertRaises(self.m.RunError):
            self.call(HTTP([], [URLError("two")]))
        self.prompt.write_text("new prompt", encoding="utf-8")
        no_network = HTTP([generation()], [png()])
        with self.assertRaises(self.m.RunError):
            self.call(no_network)
        record = json.loads((self.root / "_records" / "result.call.json").read_text())
        self.assertEqual(record["state"], "download_pending")
        self.assertEqual(record["download_attempt_count"], 2)
        self.assertEqual(no_network.post_requests + no_network.get_urls, [])

    def test_completed_request_change_and_preexisting_output_are_refused(self):
        self.call(HTTP([generation()], [png()]))
        self.prompt.write_text("different", encoding="utf-8")
        with self.assertRaises(self.m.RunError):
            self.call(HTTP())
        fresh = self.root / "fresh.png"
        fresh.write_bytes(png())
        with self.assertRaises(self.m.RunError):
            self.m.run(self.prompt, fresh, http_open=HTTP(), environ={"ARK_API_KEY": "key"})
        self.assertEqual(fresh.read_bytes(), png())

    def test_record_audits_attempts_downloads_and_http_boundary(self):
        http = HTTP([generation()], [png()])
        self.call(http)
        record = json.loads((self.root / "_records" / "result.call.json").read_text())
        self.assertEqual(http.boundaries, [("https://ark.cn-beijing.volces.com/api/v3/images/generations", "POST", "application/json", 300)])
        self.assertEqual(record["output_path"], str(self.output))
        self.assertEqual(record["output_format"], "png")
        self.assertIn("submitted_at", record["attempts"][0])
        self.assertIn("generation_completed_at", record["attempts"][0])
        self.assertIn("download_completed_at", record["downloads"][0])
        self.assertIsNotNone(record["completed_at"])

    def test_structured_error_in_regular_response_is_failed_not_unresolved(self):
        body = json.dumps({"data": [{"error": {"code": "bad", "message": "no"}}]}).encode()
        with self.assertRaises(self.m.RunError):
            self.call(HTTP([body], []))
        record = json.loads((self.root / "_records" / "result.call.json").read_text())
        self.assertEqual(record["state"], "failed")
        self.assertTrue(record["retry_eligible"])

    def test_independent_outputs_run_in_parallel_but_cap_posts_at_eight(self):
        active = peak = 0
        gate, eight_entered = threading.Event(), threading.Event()
        guard = threading.Lock()

        class ParallelHTTP(HTTP):
            def __call__(self, request, timeout=None):
                nonlocal active, peak
                if hasattr(request, "data"):
                    with guard:
                        active += 1
                        peak = max(peak, active)
                        if active == 8:
                            eight_entered.set()
                    if not gate.wait(5):
                        raise TimeoutError("test did not release POSTs")
                    with guard:
                        active -= 1
                    return Response(generation())
                return Response(png())

        http = ParallelHTTP()
        outcomes, errors = [], []

        def worker(index):
            try:
                output = self.root / ("parallel-%d.png" % index)
                self.m.run(self.prompt, output, http_open=http, environ={"ARK_API_KEY": "key"})
                outcomes.append(output.exists())
            except BaseException as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for thread in threads:
            thread.start()
        self.assertTrue(eight_entered.wait(5))
        ninth = threading.Thread(target=worker, args=(8,))
        ninth.start()
        threads.append(ninth)
        self.assertTrue(wait_until(lambda: (self.root / "_records" / "parallel-8.call.json").exists()))
        self.assertEqual(peak, 8)
        gate.set()
        for thread in threads:
            thread.join(5)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(errors, [])
        self.assertEqual(outcomes, [True] * 9)

    def test_unexpected_submitted_record_write_failure_does_not_leak_generation_slot(self):
        real_write_record = self.m.write_record
        writes = 0

        def fail_submitted_record(path, record):
            nonlocal writes
            writes += 1
            if writes == 2:
                raise OSError("simulated record write failure")
            real_write_record(path, record)

        self.m.write_record = fail_submitted_record
        try:
            with self.assertRaises(OSError):
                self.call(HTTP([generation()], [png()]))
        finally:
            self.m.write_record = real_write_record

        acquired = 0
        try:
            for _ in range(8):
                if self.m._generation_slots.acquire(blocking=False):
                    acquired += 1
        finally:
            for _ in range(acquired):
                self.m._generation_slots.release()
        self.assertEqual(acquired, 8)

    def test_unknown_post_audit_keeps_known_status_and_elapsed(self):
        with self.assertRaises(self.m.RunError):
            self.call(HTTP([HTTPError("x", 503, "bad", {}, io.BytesIO(b"not-json"))]))
        record = json.loads((self.root / "_records" / "result.call.json").read_text())
        audit = record["attempts"][-1]
        self.assertEqual(record["state"], "unresolved")
        self.assertEqual(audit["http_status"], 503)
        self.assertIsNotNone(audit["elapsed_ms"])

    def test_200_invalid_json_is_typed_unresolved_with_complete_audit(self):
        http = HTTP([b"{not-json"])
        with self.assertRaises(self.m.RunError) as caught:
            self.call(http)
        self.assertIsInstance(caught.exception.__cause__, self.m.UnresolvedResult)
        self.assertEqual(caught.exception.__cause__.status, 200)
        record = json.loads((self.root / "_records" / "result.call.json").read_text())
        audit = record["attempts"][-1]
        self.assertEqual(record["state"], "unresolved")
        self.assertEqual(record["attempt_count"], 1)
        self.assertIsNotNone(audit["generation_completed_at"])
        self.assertIsNotNone(audit["elapsed_ms"])
        self.assertEqual(audit["http_status"], 200)
        self.assertEqual(audit["error_code"], "invalid_json_response")
        self.assertEqual(len(http.post_requests), 1)

    def test_200_invalid_data_shape_is_typed_unresolved_with_complete_audit(self):
        http = HTTP([json.dumps({"data": []}).encode()])
        with self.assertRaises(self.m.RunError) as caught:
            self.call(http)
        self.assertIsInstance(caught.exception.__cause__, self.m.UnresolvedResult)
        self.assertEqual(caught.exception.__cause__.status, 200)
        record = json.loads((self.root / "_records" / "result.call.json").read_text())
        audit = record["attempts"][-1]
        self.assertEqual(record["state"], "unresolved")
        self.assertEqual(record["attempt_count"], 1)
        self.assertIsNotNone(audit["generation_completed_at"])
        self.assertIsNotNone(audit["elapsed_ms"])
        self.assertEqual(audit["http_status"], 200)
        self.assertEqual(audit["error_code"], "invalid_response_shape")
        self.assertEqual(len(http.post_requests), 1)

    def test_200_missing_url_is_typed_unresolved_with_stable_error_code(self):
        http = HTTP([json.dumps({"data": [{}]}).encode()])
        with self.assertRaises(self.m.RunError) as caught:
            self.call(http)
        self.assertIsInstance(caught.exception.__cause__, self.m.UnresolvedResult)
        self.assertEqual(caught.exception.__cause__.status, 200)
        record = json.loads((self.root / "_records" / "result.call.json").read_text())
        audit = record["attempts"][-1]
        self.assertEqual(record["state"], "unresolved")
        self.assertEqual(audit["http_status"], 200)
        self.assertEqual(audit["error_code"], "missing_response_url")
        self.assertIsNotNone(audit["generation_completed_at"])

    def test_download_failure_audit_keeps_http_status(self):
        with self.assertRaises(self.m.RunError):
            self.call(HTTP([generation()], [b"ignored"]))
        record = json.loads((self.root / "_records" / "result.call.json").read_text())
        audit = record["downloads"][-1]
        self.assertEqual(audit["http_status"], 200)
        self.assertIsNotNone(audit["download_completed_at"])
        self.assertIsNotNone(audit["elapsed_ms"])

    def test_download_http_error_audit_keeps_status(self):
        failure = HTTPError("https://temporary.example/image", 503, "bad", {}, io.BytesIO(b"x"))
        with self.assertRaises(self.m.RunError): self.call(HTTP([generation()], [failure]))
        record = json.loads((self.root / "_records" / "result.call.json").read_text())
        self.assertEqual(record["downloads"][-1]["http_status"], 503)

    def test_download_ordinary_http_failure_audit_keeps_status(self):
        class StatusHTTP(HTTP):
            def __call__(self, request, timeout=None):
                if hasattr(request, "data"): return Response(generation())
                return Response(b"busy", 503)
        with self.assertRaises(self.m.RunError): self.call(StatusHTTP())
        record = json.loads((self.root / "_records" / "result.call.json").read_text())
        self.assertEqual(record["downloads"][-1]["http_status"], 503)

    def test_environment_key_overrides_machine_key(self):
        http = HTTP([generation()], [png()])
        self.m.run(self.prompt, self.output, http_open=http, environ={"ARK_API_KEY": "env"},
                   machine_key=lambda: (_ for _ in ()).throw(AssertionError("machine read")))
        self.assertEqual(http.auth, ["Bearer env"])

    def test_ten_inputs_are_accepted_in_order(self):
        inputs = []
        for index in range(10):
            path = self.root / ("%d.png" % index)
            Image.new("RGB", (20, 20), (index, 0, 0)).save(path, "PNG")
            inputs.append((str(index), path))
        http = HTTP([generation()], [png()])
        self.call(http, inputs=inputs)
        self.assertEqual(len(http.post_requests[0]["image"]), 10)
        expected = ["data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii") for _, path in inputs]
        self.assertEqual(http.post_requests[0]["image"], expected)

    def test_oversized_inputs_are_rejected_before_post(self):
        large = self.root / "large.bin"
        large.write_bytes(b"x" * (30 * 1024 * 1024 + 1))
        pixels = self.root / "pixels.png"
        Image.new("1", (6001, 6000)).save(pixels, "PNG")
        for source in (large, pixels):
            http = HTTP()
            with self.subTest(source=source.name), self.assertRaises(self.m.ValidationError):
                self.call(http, inputs=[("x", source)])
            self.assertEqual(http.post_requests, [])

    def test_ninth_queued_post_has_no_submitted_timestamp(self):
        gate, eight_entered = threading.Event(), threading.Event()
        guard, active = threading.Lock(), [0]

        class BlockingHTTP(HTTP):
            def __call__(self, request, timeout=None):
                if hasattr(request, "data"):
                    with guard:
                        active[0] += 1
                        if active[0] == 8:
                            eight_entered.set()
                    if not gate.wait(5):
                        raise TimeoutError("test did not release POSTs")
                    with guard:
                        active[0] -= 1
                    return Response(generation())
                return Response(png())

        http = BlockingHTTP()
        errors = []

        def worker(index):
            try:
                self.m.run(self.prompt, self.root / ("slot-%d.png" % index), http_open=http,
                           environ={"ARK_API_KEY": "k"})
            except BaseException as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for thread in threads:
            thread.start()
        self.assertTrue(eight_entered.wait(5))
        ninth = threading.Thread(target=worker, args=(8,))
        ninth.start()
        threads.append(ninth)
        ninth_record = self.root / "_records" / "slot-8.call.json"
        self.assertTrue(wait_until(ninth_record.exists))
        record = json.loads(ninth_record.read_text())
        self.assertIsNone(record["submitted_at"])
        gate.set()
        for thread in threads:
            thread.join(5)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(errors, [])
        record = json.loads(ninth_record.read_text())
        self.assertIsNotNone(record["submitted_at"])

    def test_os_task_lock_rejects_other_process(self):
        ready = self.root / "ready.txt"
        release = self.root / "release.txt"
        code = "import importlib.util,pathlib,time; s=importlib.util.spec_from_file_location('m',%r); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); o=pathlib.Path(%r); r=pathlib.Path(%r); done=pathlib.Path(%r)\nwith m.task_lock(o):\n r.write_text('ready'); deadline=time.monotonic()+10\n while not done.exists() and time.monotonic()<deadline: time.sleep(.01)" % (str(MODULE), str(self.output), str(ready), str(release))
        process = subprocess.Popen([sys.executable, "-c", code])
        try:
            self.assertTrue(wait_until(ready.exists, timeout=5))
            with self.assertRaises(self.m.RunError):
                with self.m.task_lock(self.output): pass
        finally:
            release.write_text("release")
            process.wait(5)


if __name__ == "__main__":
    unittest.main()
