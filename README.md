# 本地语音识别 Web 应用

基于 **faster-whisper + FastAPI + 原生 HTML/CSS/JS** 的离线语音转文字服务。麦克风录音或上传音频文件，支持中文 / 英文识别，模型在本地 CPU 上运行，音频不出本机。

## 环境要求

| 项目 | 要求 |
|---|---|
| 操作系统 | Windows 11 / 10 x64（其他平台同样可用） |
| Python | 3.11 / 3.12 |
| 内存 | ≥ 4GB（base 模型常驻约 500MB） |
| 网络 | 仅首次启动下载模型权重（约 150MB） |

## 安装

```powershell
# 1. 创建并激活虚拟环境（可选，但推荐）
conda create -n speech_to_text python=3.12 -y
conda activate speech_to_text

# 2. 安装依赖
python -m pip install -r requirements.txt
```

## 启动

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

浏览器打开 <http://127.0.0.1:8000> 即可使用。

- 首次启动会自动从 HuggingFace 下载 `faster-whisper base` 模型（约 150MB），加载完成后 `/health` 返回 `ok`。
- 模型缓存位于 `~/.cache/huggingface/hub`，之后启动无需联网，可完全断网运行。
- 国内网络如下载受阻，可先设置镜像：

```powershell
$env:HF_ENDPOINT = "https://hf-mirror.com"
```

## 使用方式

1. **麦克风录音**：选择语言 → 点击圆形麦克风按钮开始录音（最长 60 秒，可手动停止）→ 停止后自动识别。
2. **上传音频**：选择或拖拽 WAV / MP3 / WEBM / OGG / M4A / FLAC 文件（≤ 10MB）→ 点击「上传并识别」。
3. 结果区展示识别文本、语言、音频时长与服务端耗时，可一键复制。

## API

| Method | Endpoint | 说明 |
|---|---|---|
| GET | `/health` | 健康检查：`{"status": "ok", "model_ready": true}` |
| GET | `/` | Web 前端页面 |
| POST | `/api/transcribe` | 音频识别（multipart/form-data） |
| GET | `/docs` | 自动生成的接口文档 |

请求示例：

```powershell
curl.exe -X POST http://127.0.0.1:8000/api/transcribe `
  -F "file=@samples/chinese.wav" -F "language=zh"
```

响应：

```json
{
  "text": "你好，欢迎使用本地语音识别系统。",
  "language": "zh",
  "duration_seconds": 4.2,
  "processing_seconds": 1.6
}
```

错误码：`400` 格式不支持 / 文件为空或损坏 / 时长超 60 秒，`413` 文件超过 10MB，`422` 语言参数非法，`500` 推理异常，`503` 模型未就绪。

## 测试

```powershell
python -m pytest -q
```

测试默认使用 Mock 模型（不加载权重、不联网），覆盖校验器、解码器、推理重试与 API 全链路；真实模型效果可用 `samples/` 下的中英文音频手动验证。

## 配置

均通过环境变量覆盖，默认值见 [app/config.py](app/config.py)：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `ASR_MODEL_SIZE` | `base` | 模型规格：tiny / base / small |
| `ASR_DEVICE` | `cpu` | 推理设备 |
| `ASR_COMPUTE_TYPE` | `int8` | 量化精度 |
| `ASR_PRELOAD` | `1` | 启动时预加载模型，`0` 为懒加载 |

## 目录结构

```text
SpeechtoText/
├── app/
│   ├── main.py              # FastAPI 应用工厂、生命周期、请求体限制中间件
│   ├── config.py            # 全部可调参数
│   ├── schemas.py           # 请求/响应模型
│   ├── api/routes.py        # /health、/、/api/transcribe
│   └── services/
│       ├── validator.py     # 文件格式/大小校验
│       ├── tempfiles.py     # 临时文件写入与清理
│       ├── decoder.py       # wave + av 解码为 16kHz 单声道
│       ├── audio_utils.py   # 时长计算
│       └── transcriber.py   # faster-whisper 推理（懒加载 + 重试）
├── static/                  # 原生前端（HTML/CSS/JS）
├── tests/                   # pytest 用例（Mock 模型）
├── samples/                 # 中英文样例音频与参考文本
├── requirements.txt
└── pytest.ini
```

## 说明

- 上传的音频写入系统临时目录，识别结束立即删除；服务启动时会清理超过 5 分钟的残留临时文件。
- 不保存识别历史、不做用户体系，纯本地单机运行。
- 浏览器录音使用 MediaRecorder（Chrome / Edge 输出 webm），后端统一解码，前端无需转码。
