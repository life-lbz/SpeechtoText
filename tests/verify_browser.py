"""使用 Chrome 和真实本地模型验收页面，录音输入来自仓库样本。"""

import argparse
import re
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ORIGIN = "http://127.0.0.1:8000"
SAMPLES = Path(__file__).resolve().parents[1] / "samples"
CASES = (
    ("zh", "chinese.wav", "你好，欢迎使用本地语音识别系统。", 5_100),
    ("en", "english.wav", "Hello and welcome to the local speech to text system.", 4_200),
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
    return page


def is_transcription(response):
    return response.url == f"{ORIGIN}/api/transcribe" and response.request.method == "POST"


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
    print(language, body, flush=True)
    return body


def verify_upload_and_denied_permission(playwright):
    browser = playwright.chromium.launch(
        channel="chrome", args=["--use-fake-device-for-media-stream"]
    )
    try:
        page = open_page(browser, ["clipboard-read", "clipboard-write"])
        for language, filename, reference, _ in CASES:
            page.locator(f'.lang-btn[data-lang="{language}"]').click()
            page.locator("#fileInput").set_input_files(SAMPLES / filename)
            with page.expect_response(is_transcription, timeout=30_000) as response:
                page.locator("#uploadBtn").click()
            body = check_result(page, response.value, language, reference)
            page.locator("#copyBtn").click()
            assert page.evaluate("navigator.clipboard.readText()") == body["text"]
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
    for language, filename, reference, recording_ms in CASES:
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
            with page.expect_response(is_transcription, timeout=30_000) as response:
                page.wait_for_timeout(recording_ms)
                record.click()
            check_result(page, response.value, language, reference)
            if check_limit and language == "zh":
                requests = []
                page.on(
                    "response",
                    lambda item: requests.append(item) if is_transcription(item) else None,
                )
                with page.expect_response(is_transcription, timeout=100_000) as response:
                    record.click()
                    page.get_by_text("录音中", exact=True).wait_for()
                body = check_result(page, response.value, language, reference)
                assert 59.5 <= body["duration_seconds"] <= 60.5, body
                assert len(requests) == 1
                print("60 秒录音自动停止并成功提交一次", flush=True)
        finally:
            browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record-limit", action="store_true", help="额外验收 60 秒自动停止")
    args = parser.parse_args()
    with sync_playwright() as playwright:
        verify_upload_and_denied_permission(playwright)
        verify_recording(playwright, args.record_limit)
