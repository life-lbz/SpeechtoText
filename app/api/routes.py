"""语音识别相关 API 路由。"""

import logging
import time
import uuid

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse

from app.config import INDEX_FILE, settings
from app.schemas import HealthResponse, TranscriptionResponse
from app.services.audio_utils import audio_duration
from app.services.decoder import AudioDecodeError, AudioTooLongError, decode_audio
from app.services.tempfiles import temporary_audio_file
from app.services.transcriber import ModelNotReadyError, TranscriptionError
from app.services.validator import AudioValidationError, validate_upload

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/", include_in_schema=False)
def index():
    if not INDEX_FILE.exists():
        raise HTTPException(status_code=404, detail="前端页面缺失，请检查 static/index.html")
    return FileResponse(INDEX_FILE)


@router.get("/health", response_model=HealthResponse, tags=["system"])
def health(request: Request):
    transcriber = request.app.state.transcriber
    if transcriber.ready:
        return HealthResponse(status="ok")
    if request.app.state.model_error:
        return HealthResponse(status="unhealthy")
    return HealthResponse(status="initializing" if settings.preload_model else "standby")


@router.post(
    "/api/transcribe",
    response_model=TranscriptionResponse,
    tags=["asr"],
    summary="上传音频并返回识别文本",
)
async def transcribe(
    request: Request,
    file: UploadFile = File(..., description="音频文件，支持 wav/mp3/webm/ogg/m4a/flac"),
    language: str = Form(..., description="识别语言：zh 或 en"),
):
    started = time.perf_counter()
    trace_id = uuid.uuid4().hex[:8]
    language = (language or "").strip().lower()

    if language not in settings.allowed_languages:
        raise HTTPException(status_code=422, detail="Language must be 'zh' or 'en'")

    # 多读 1 字节用于识别超限，避免把超大文件读入内存
    content = await file.read(settings.max_file_size + 1)
    logger.info(
        "[trace_id=%s] request_received language=%s size=%s file=%s",
        trace_id,
        language,
        len(content),
        file.filename,
    )

    try:
        suffix = validate_upload(file.filename, len(content))
    except AudioValidationError as exc:
        logger.warning("[trace_id=%s] 校验失败: %s", trace_id, exc.message)
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    transcriber = request.app.state.transcriber
    if settings.preload_model and not transcriber.ready:
        raise HTTPException(status_code=503, detail="语音识别模型不可用，请检查服务日志。")

    model_load_seconds = 0.0
    try:
        with temporary_audio_file(content, suffix) as audio_path:
            audio = await run_in_threadpool(
                decode_audio,
                audio_path,
                max_seconds=settings.max_duration_seconds + settings.recording_tolerance_seconds,
            )
            duration = audio_duration(audio, settings.target_sample_rate)
        if not transcriber.ready:
            load_started = time.perf_counter()
            try:
                await run_in_threadpool(transcriber.load)
            except Exception as exc:
                request.app.state.model_error = str(exc)
                logger.exception("[trace_id=%s] 模型加载失败", trace_id)
                raise HTTPException(
                    status_code=503, detail="语音识别模型加载失败，请检查模型缓存后重试。"
                ) from exc
            model_load_seconds = time.perf_counter() - load_started
            request.app.state.model_error = None
        text = await run_in_threadpool(transcriber.transcribe, audio, language)
    except AudioTooLongError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"音频超过 {settings.max_duration_seconds:g} 秒上限，请分段识别。",
        ) from exc
    except AudioDecodeError as exc:
        logger.warning("[trace_id=%s] 解码失败: %s", trace_id, exc)
        raise HTTPException(status_code=400, detail="音频文件为空或已损坏，请重新上传。") from exc
    except ModelNotReadyError as exc:
        raise HTTPException(status_code=503, detail="语音识别模型不可用，请检查服务日志。") from exc
    except TranscriptionError as exc:
        logger.error("[trace_id=%s] 推理失败: %s", trace_id, exc)
        raise HTTPException(status_code=500, detail="识别失败，请重试。") from exc

    processing = round(time.perf_counter() - started - model_load_seconds, 2)
    text = text.strip()
    logger.info(
        "[trace_id=%s] 识别完成 duration=%.2fs processing=%.2fs text_len=%s",
        trace_id,
        duration,
        processing,
        len(text),
    )
    return TranscriptionResponse(
        text=text,
        language=language,
        duration_seconds=round(duration, 2),
        processing_seconds=processing,
    )
