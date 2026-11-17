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
# 确认当前 Python 为 3.12
python --version
python -m pip install -r requirements.txt
```

## 启动

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

浏览器打开 <http://127.0.0.1:8000> 即可使用。

- 首次启动会自动从 Hugging Face 下载 `faster-whisper base`。访问 `http://127.0.0.1:8000/health`，收到 `{"status":"ok"}` 即表示模型已可用。
- 模型默认缓存在 `~/.cache/huggingface/hub`。首次下载成功后，可以停止服务，在同一个 PowerShell 中执行以下命令，从现有缓存重新启动。

```powershell
$env:HF_HUB_OFFLINE = "1"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

缓存缺失时，清除当前 PowerShell 的离线设置 `Remove-Item Env:HF_HUB_OFFLINE`，恢复网络并重启服务。

## 使用方式

1. **麦克风录音**：选择语言 → 点击圆形麦克风按钮开始录音（最长 60 秒，可手动停止）→ 停止后自动识别。
2. **上传音频**：选择或拖拽 WAV / MP3 / WEBM / OGG / M4A / FLAC 文件（≤ 10MB）→ 点击「上传并识别」。
3. 结果区展示识别文本、语言、音频时长与服务端耗时，可一键复制。

## API

| Method | Endpoint | 说明 |
|---|---|---|
| GET | `/health` | 模型已就绪时返回 `{"status":"ok"}`，懒加载模式下未加载时为 `standby`，加载失败时为 `unhealthy` |
| GET | `/` | Web 前端页面 |
| POST | `/api/transcribe` | 音频识别（multipart/form-data） |
| GET | `/docs` | 自动生成的接口文档 |

请求示例：

```powershell
curl.exe -X POST http://127.0.0.1:8000/api/transcribe `
  -F "file=@samples/chinese.wav" -F "language=zh"
curl.exe -X POST http://127.0.0.1:8000/api/transcribe `
  -F "file=@samples/english.wav" -F "language=en"
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

错误码：`400` 格式不支持、文件为空或损坏、音频过长，`413` 文件超过 10 MB，`422` 语言参数非法，`500` 推理异常，`503` 模型不可用。后端允许 0.5 秒录音收尾偏差。处理耗时涵盖音频校验、解码和推理，排除首次加载模型的时间。

## 测试

```powershell
python -m pytest -q
```

常规 pytest 测试使用 Mock 模型，同时执行实际 WAV 和 WebM 解码。真实模型可以用上述两条上传命令验证，预期文本见 [samples/reference.txt](samples/reference.txt)。

如需重复验收浏览器流程，先按默认配置启动真实模型服务并准备本机 Chrome，再在另一个终端运行以下可选脚本。它会用仓库音频模拟麦克风，并测试上传、录音、剪贴板和拒绝权限。带上 `--record-limit` 会额外录满 60 秒。

```powershell
python -m pip install playwright
python -X utf8 -m tests.verify_browser --record-limit
```

人工验收清单和实测结果见 [测试报告](docs/test-report.md)。

## 配置

均通过环境变量覆盖，默认值见 [app/config.py](app/config.py)：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `ASR_MODEL_SIZE` | `base` | 模型规格：tiny / base / small |
| `ASR_DEVICE` | `cpu` | 推理设备 |
| `ASR_COMPUTE_TYPE` | `int8` | 量化精度 |
| `ASR_PRELOAD` | `1` | `1` 在启动时加载，`0` 在首次有效识别请求时加载，加载失败后可重新提交请求 |

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
├── docs/                    # 考核需求、设计、测试结果和开发记录
├── requirements.txt
└── pytest.ini
```

## 说明

- 上传的音频写入系统临时目录，识别结束立即删除；服务启动时会清理超过 5 分钟的残留临时文件。
- 不保存识别历史、不做用户体系，纯本地单机运行。
- 浏览器录音使用 MediaRecorder（Chrome / Edge 输出 webm），后端统一解码，前端无需转码。
