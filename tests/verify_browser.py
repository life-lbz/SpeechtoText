"""使用 Chrome 和真实本地模型验收页面，录音输入来自仓库样本。"""

import argparse
import json
import os
import re
import time
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ORIGIN = f"http://127.0.0.1:{int(os.getenv('ASR_TEST_PORT', '8000'))}"
SAMPLES = Path(__file__).resolve().parents[1] / "samples"
OBSERVATIONS = []
INFERENCE_TIMEOUT_MS = 180000

CASES = (
    ("zh", "chinese.wav", "你好，欢迎使用本地语音识别系统。请开始录音，或上传音频。"),
    ("en", "english.wav", "Hello and welcome to the local speech to text system. Please record your voice or upload an audio file."),
)


def open_page(browser, permissions=None):
    context = browser.new_context(permissions=permissions)
    context.route(
        "**/*",
        lambda route: route.continue_()
        if route.request.url.startswith(f"{ORIGIN}/")
        else route.abort(),
    )
    page = context.new_page()
    page.goto(ORIGIN)
    expect(page.locator(".bar-status")).to_have_attribute("title", "服务就绪", timeout=20000)
    expect(page.get_by_role("heading", name="麦克风录音", exact=True)).to_be_visible()
    return page


def is_transcription(response):
    return response.url == f"{ORIGIN}/api/transcribe" and response.request.method == "POST"


def is_preview_request(request):
    return request.url == f"{ORIGIN}/api/transcribe" and b'filename="preview.wav"' in (
        request.post_data_buffer or b""
    )


def is_final_transcription(response):
    return is_transcription(response) and not is_preview_request(response.request)


def check_result(page, response, language, reference):
    assert response.status == 200, response.text()
    body = response.json()
    assert body["language"] == language
    assert body["duration_seconds"] > 0
    assert body["processing_seconds"] >= 0
    normalized_reference = re.sub(r"[^\w]", "", reference.casefold())
    normalized_result = re.sub(r"[^\w]", "", body["text"].casefold())
    assert normalized_reference in normalized_result, body
    expect(page.locator("#resultText")).to_have_text(body["text"])
    expect(page.locator("#resultText")).to_be_visible()
    expect(page.get_by_role("heading", name="识别结果", exact=True)).to_be_visible()
    print(language, body, flush=True)
    OBSERVATIONS.append(dict(body))
    return body


def verify_upload_and_denied_permission(playwright):
    browser = playwright.chromium.launch(
        channel="chrome", args=["--use-fake-device-for-media-stream"]
    )
    try:
        page = open_page(browser, ["clipboard-read", "clipboard-write"])
        for language, filename, reference in CASES:
            page.locator(f'.lang-btn[data-lang="{language}"]').click()
            page.locator("#fileInput").set_input_files(SAMPLES / filename)
            with page.expect_response(is_transcription, timeout=INFERENCE_TIMEOUT_MS) as response:
                page.locator("#uploadBtn").click()
            body = check_result(page, response.value, language, reference)
            page.locator("#copyBtn").click()
            assert page.evaluate("navigator.clipboard.readText()") == body["text"]
        page.locator("#fileInput").set_input_files(
            {"name": "invalid.txt", "mimeType": "text/plain", "buffer": b"invalid"}
        )
        expect(page.locator("#uploadBtn")).to_be_disabled()
        expect(page.locator("#fileRow")).to_be_hidden()
        page.locator("#recordBtn").click()
        expect(page.locator("#progressText")).to_have_text("麦克风权限被拒绝，请在浏览器地址栏重新授权")
        print("麦克风权限拒绝提示正常", flush=True)
    finally:
        browser.close()


def verify_recording_error(page):
    page.evaluate("""() => {
        const start = MediaRecorder.prototype.start;
        MediaRecorder.prototype.start = function (...args) {
            window.currentRecorder = this;
            start.apply(this, args);
        };
        const media = navigator.mediaDevices;
        const getUserMedia = media.getUserMedia.bind(media);
        media.getUserMedia = async constraints => {
            await new Promise(resolve => { window.grantMicrophone = resolve; });
            media.getUserMedia = getUserMedia;
            return getUserMedia(constraints);
        };
    }""")
    record = page.locator("#recordBtn")
    record.click()
    expect(page.locator("#statusText")).to_have_text("等待麦克风授权")
    expect(record).to_be_disabled()
    expect(page.locator("#uploadBtn")).to_be_disabled()
    page.evaluate("window.grantMicrophone()")
    expect(page.locator("#statusText")).to_have_text("录音中")
    page.evaluate("""window.currentRecorder.dispatchEvent(new Event('error'))""")
    expect(page.locator("#progressText")).to_have_text("录音中断，请检查麦克风后重试")
    assert page.evaluate("window.currentRecorder.stream.getTracks().every(t => t.readyState === 'ended')")
    expect(record).to_be_enabled()
    expect(page.locator("#uploadBtn")).to_be_enabled()
    print("等待授权锁定输入，录音中断后释放麦克风并允许重试", flush=True)


def verify_recording(playwright, check_limit):
    for language, filename, reference in CASES:
        browser = playwright.chromium.launch(
            channel="chrome",
            args=[
                "--use-fake-device-for-media-stream",
                f"--use-file-for-fake-audio-capture={SAMPLES / filename}",
            ],
        )
        try:
            page = open_page(browser, ["microphone"])
            page.locator(f'.lang-btn[data-lang="{language}"]').click()
            page.locator("#fileInput").set_input_files(SAMPLES / filename)
            if language == "zh":
                verify_recording_error(page)
            record = page.locator("#recordBtn")
            record.click()
            expect(page.locator("#statusText")).to_have_text("录音中")
            assert page.locator("#uploadBtn").is_disabled()
            result = page.locator("#resultPreview")
            expect(result).to_be_visible(timeout=20_000)
            expect(result).not_to_have_text("正在等待第一个音频片段…", timeout=20000)
            first_preview = result.inner_text()
            page.wait_for_function(
                "(previous) => document.querySelector('#resultPreview').textContent.length > previous.length",
                arg=first_preview,
                timeout=15_000,
            )
            expect(page.get_by_role("heading", name="识别结果", exact=True)).to_be_visible()
            expect(page.locator("#recordTip")).to_have_text("正在实时识别，再次点击生成最终结果")
            expect(page.locator("#statusText")).to_have_text("录音中")
            print(f"{language} 停止前至少两次实时更新，首段为 {first_preview}", flush=True)
            with page.expect_response(is_final_transcription, timeout=INFERENCE_TIMEOUT_MS) as response:
                record.click()
            check_result(page, response.value, language, reference)
            if language == "zh":
                verify_preview_failure(page, language, reference)
            if check_limit and language == "en":
                verify_limit_on_page(page, language, reference)
        finally:
            browser.close()


def verify_limit_on_page(page, language, reference):
    finals = []
    page.on("response", lambda response: finals.append(response) if is_final_transcription(response) else None)
    started = time.monotonic()
    # 采集等待和推理等待分别计时，CPU慢不能放宽60秒录音上限。
    with page.expect_response(is_final_transcription, timeout=70000 + INFERENCE_TIMEOUT_MS) as response:
        page.locator("#recordBtn").click()
        expect(page.locator("#statusText")).to_have_text("录音中")
        page.get_by_text("录音已达 60 秒上限，已自动停止", exact=True).wait_for(timeout=70000)
        stopped_after = time.monotonic() - started
        assert 59.8 <= stopped_after <= 65, stopped_after
    body = check_result(page, response.value, language, reference)
    assert 59 <= body["duration_seconds"] <= 60.5, body
    assert len(finals) == 1
    OBSERVATIONS[-1].update(case="record_limit", stopped_after_seconds=round(stopped_after, 2), final_requests=len(finals))
    print(f"{stopped_after:.2f} 秒自动停止，一次终稿，CPU处理 {body['processing_seconds']} 秒", flush=True)


def verify_limit_only(playwright):
    browser = playwright.chromium.launch(channel="chrome", args=[
        "--use-fake-device-for-media-stream",
        f"--use-file-for-fake-audio-capture={SAMPLES / 'english.wav'}",
    ])
    try:
        page = open_page(browser, ["microphone"])
        page.locator('.lang-btn[data-lang="en"]').click()
        verify_limit_on_page(page, "en", CASES[1][2])
    finally:
        browser.close()


def verify_preview_failure(page, language, reference):
    def fail_preview(route):
        if is_preview_request(route.request):
            route.fulfill(status=503, json={"detail": "测试：实时转写失败"})
        else:
            route.fallback()

    url = f"{ORIGIN}/api/transcribe"
    page.route(url, fail_preview)
    try:
        record = page.locator("#recordBtn")
        record.click()
        page.get_by_text("实时转写暂时不可用，停止后仍会尝试识别整段录音", exact=True).wait_for()
        # 首个4秒分片后继续采集，确保8秒样本完整进入终稿。
        page.wait_for_timeout(5_000)
        with page.expect_response(is_final_transcription, timeout=INFERENCE_TIMEOUT_MS) as response:
            record.click()
        check_result(page, response.value, language, reference)
        print("实时片段失败后仍可生成完整结果", flush=True)
    finally:
        page.unroute(url, fail_preview)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record-limit", action="store_true", help="额外验收60秒自动停止")
    parser.add_argument("--only-record-limit", action="store_true", help="仅复验60秒自动停止")
    parser.add_argument("--inference-timeout", type=int, default=180, help="CPU推理等待上限（秒），不改变录音上限")
    parser.add_argument("--output", type=Path, help="写入结构化验证结果 JSON")
    args = parser.parse_args()
    if args.inference_timeout <= 0:
        parser.error("inference-timeout必须大于0")
    INFERENCE_TIMEOUT_MS = args.inference_timeout * 1000
    with sync_playwright() as playwright:
        if args.only_record_limit:
            verify_limit_only(playwright)
        else:
            verify_upload_and_denied_permission(playwright)
            verify_recording(playwright, args.record_limit)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({"status": "passed", "backend": "real-local-model", "cases": OBSERVATIONS}, ensure_ascii=False, indent=2), encoding="utf-8")
