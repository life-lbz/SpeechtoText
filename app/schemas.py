"""请求与响应数据模型。"""

from pydantic import BaseModel


class TranscriptionResponse(BaseModel):
    text: str
    language: str
    duration_seconds: float
    processing_seconds: float


class HealthResponse(BaseModel):
    status: str
    device: str | None = None
    model: str | None = None
    gpu_status: str | None = None
    gpu_error: str | None = None
