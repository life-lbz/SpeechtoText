"""使用 Chrome 和真实本地模型验收页面，录音输入来自仓库样本。"""

import argparse
import os
import re
import time
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ORIGIN = f"http://127.0.0.1:{int(os.getenv('ASR_TEST_PORT', '8000'))}"
SAMPLES = Path(__file__).resolve().parents[1] / "samples"
CASES = (
    ("zh", "chinese.wav", "你好，欢迎使用本地语音识别系统。"),
    ("en", "english.wav", "Hello and welcome to the local speech to text system."),
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
    page.get_by_text("服务就绪", exact=True).wait_for()
    expect(page.get_by_role("heading", name="实时语音识别", exact=True)).to_be_visible()
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
            with page.expect_response(is_transcription, timeout=30_000) as response:
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
        page.get_by_text("麦克风权限被拒绝，请在浏览器地址栏重新授权", exact=True).wait_for()
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
    page.get_by_text("等待麦克风授权", exact=True).wait_for()
    expect(record).to_be_disabled()
    expect(page.locator("#uploadBtn")).to_be_disabled()
    page.evaluate("window.grantMicrophone()")
    page.get_by_text("录音中", exact=True).wait_for()
    page.evaluate("""window.currentRecorder.dispatchEvent(new Event('error'))""")
    page.get_by_text("录音中断，请检查麦克风后重试", exact=True).wait_for()
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
            page.get_by_text("录音中", exact=True).wait_for()
            assert page.locator("#uploadBtn").is_disabled()
            result = page.locator("#resultText")
            expect(result).to_be_visible(timeout=20_000)
            first_preview = result.inner_text()
            page.wait_for_function(
                "(previous) => document.querySelector('#resultText').textContent.length > previous.length",
                arg=first_preview,
                timeout=15_000,
            )
            expect(page.get_by_role("heading", name="识别结果", exact=True)).to_be_visible()
            expect(page.locator("#recordTip")).to_have_text("正在实时识别，再次点击生成最终结果")
            expect(page.locator("#statusText")).to_have_text("录音中")
            print(f"{language} 停止前至少两次实时更新，首段为 {first_preview}", flush=True)
            with page.expect_response(is_final_transcription, timeout=30_000) as response:
                record.click()
            check_result(page, response.value, language, reference)
            if language == "zh":
                verify_preview_failure(page, language, reference)
            if check_limit and language == "en":
                requests = []
                page.on(
                    "response",
                    lambda item: requests.append(item) if is_final_transcription(item) else None,
                )
                with page.expect_response(is_final_transcription, timeout=100_000) as response:
                    started = time.monotonic()
                    record.click()
                    page.get_by_text("录音中", exact=True).wait_for()
                    page.get_by_text("录音已达 60 秒上限，已自动停止", exact=True).wait_for(
                        timeout=70_000
                    )
                    elapsed = time.monotonic() - started
                body = check_result(page, response.value, language, reference)
                assert 59.8 <= elapsed <= 65, elapsed
                # 模拟设备编码出的实际样本时长可能略短于浏览器录音时钟。
                assert 59 <= body["duration_seconds"] <= 60.5, body
                assert len(requests) == 1
                print(f"{elapsed:.2f} 秒后自动停止并成功提交一次完整录音", flush=True)
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
        # 样本接近 5 秒，给完整录音留出足够的采集时间。
        page.wait_for_timeout(1_200)
        with page.expect_response(is_final_transcription, timeout=30_000) as response:
            record.click()
        check_result(page, response.value, language, reference)
        print("实时片段失败后仍可生成完整结果", flush=True)
    finally:
        page.unroute(url, fail_preview)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record-limit", action="store_true", help="额外验收 60 秒自动停止")
    args = parser.parse_args()
    with sync_playwright() as playwright:
        verify_upload_and_denied_permission(playwright)
        verify_recording(playwright, args.record_limit)
