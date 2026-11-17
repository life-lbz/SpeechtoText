# 本地语音识别 Web 应用

基于 **FunASR、faster-whisper 和 FastAPI** 的离线语音转文字服务。支持麦克风录音和上传音频的中英文识别。CPU 启动，CUDA 验证通过后切换到 GPU，音频留在本机。

## 环境要求

| 项目 | 要求 |
|---|---|
| 操作系统 | Windows 11 / 10 x64（其他平台同样可用） |
| Python | 3.11 / 3.12 |
| 内存 | 目标为 4 GB 起。上传音频解码后的占用随音频时长增加，整机 4 GB 尚待实机验收。 |
| 模型 | 根目录 `models/` 中的三个运行模型约 2.0 GB。 |
| 网络 | 安装依赖和补齐缺失的权重时需要网络。依赖和本地模型准备好后可离线运行。 |

## 安装

```powershell
# 确认当前 Python 为 3.12
python --version
python -m pip install -r requirements-funasr.txt
```

仅部署 Whisper 时可使用 `requirements.txt`。

## 启动

```powershell
$env:HF_HUB_OFFLINE = "1"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

浏览器打开 <http://127.0.0.1:8000> 即可使用。直接打开 `static/index.html` 会进入界面预览，录音和上传识别需要从本地服务地址进入。

- 将 [模型目录](models/README.md) 随项目放好，服务会优先从中加载。未找到本地 Whisper 权重时，会尝试 Hugging Face 缓存。需要在线补齐时，清除本终端的 `HF_HUB_OFFLINE` 后重启。
- 访问 `http://127.0.0.1:8000/health` 查看就绪状态和实际模型。若端口已占用，可修改启动命令的 `--port` 并打开对应地址。

## 使用方式

1. **麦克风实时转写**：选择语言并点击圆形麦克风按钮。录音期间每采集约 4 秒音频，就发送一段给本地模型，文字陆续显示在「识别结果」区。再次点击或达到 60 秒后，系统用完整录音生成最终稿。
2. **上传音频**：选择或拖拽 WAV / MP3 / WEBM / OGG / M4A / FLAC 文件（≤ 10 MB，时长不限），点击「上传并识别」。
3. 结果区展示识别文本、语言、音频时长与服务端耗时，可一键复制。

中文结果会在本机统一转换为简体。使用 Whisper 时，中文上传和录音最终稿使用更宽的解码搜索，实时片段使用低延迟解码。最终稿可能需要更长的处理时间。

## API

| Method | Endpoint | 说明 |
|---|---|---|
| GET | `/health` | 就绪时 `status` 为 `ok`，懒加载等待首次请求时为 `standby`，加载失败时为 `unhealthy` |
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

普通上传只检查文件大小和格式。网页录音终稿附带 `recording=true`，实时分段请求附带 `preview=true` 并使用低延迟解码。这两种请求都应用网页录音的时长上限。

错误码：`400` 格式不支持、文件为空或损坏、网页录音超时，`413` 文件超过 10 MB，`422` 请求参数非法，`500` 推理异常，`503` 模型不可用。后端允许 0.5 秒录音收尾偏差。处理耗时涵盖音频校验、解码和推理，排除首次加载模型的时间。

## 测试

```powershell
python -m pytest -q
```

常规 pytest 测试使用 Mock 模型，同时执行实际 WAV 和 WebM 解码。真实模型可以用上述两条上传命令验证，预期文本见 [samples/reference.txt](samples/reference.txt)。

如需重复验收浏览器流程，先按默认配置启动真实模型服务并准备本机 Chrome，再在另一个终端运行以下可选脚本。它会用仓库音频模拟麦克风，检查停止前至少两次更新文字、停止后生成最终稿、实时片段失败时的恢复，以及上传、剪贴板和拒绝权限。带上 `--record-limit` 会额外录满 60 秒。使用其他本地端口时，将 `ASR_TEST_PORT` 设为对应端口。

```powershell
python -m pip install playwright
python -X utf8 -m tests.verify_browser --record-limit
```

人工验收清单和实测结果见 [测试报告](docs/test-report.md)。

## 配置

均通过环境变量覆盖，默认值见 [app/config.py](app/config.py)：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `ASR_MODEL_SIZE` | `base` | 自动模式的 CPU 模型，或固定设备模式的模型。 |
| `ASR_CPU_PARAFORMER_PATH` | `models/funasr-paraformer`（权重存在时） | CPU 中文使用 FunASR，纯英文和 FunASR 故障时使用 Whisper。可设为空来关闭 FunASR。 |
| `ASR_GPU_MODEL_SIZE` | `large-v3-turbo` | 自动模式的 CUDA 模型。 |
| `ASR_GPU_MODEL_PATH` | 空 | 可为自动模式指定 CUDA 模型目录。留空时按模型名优先在 `models/` 查找。 |
| `ASR_DEVICE` | `auto` | CPU 先就绪，后台验证 CUDA 后切换。可设为 `cpu` 固定使用 CPU，或设为 `cuda` 固定使用 CUDA。 |
| `ASR_COMPUTE_TYPE` | `int8` | 固定设备模式的计算精度。`auto` 模式在 CPU 上用 `int8`，在 CUDA 上用 `int8_float16`。 |
| `ASR_PRELOAD` | `1` | `1` 在启动时加载，`0` 在首次有效识别请求时加载，加载失败后可重新提交请求 |

`auto` 模式的 `/health` 会返回实际推理设备 `device`、模型 `model` 和 `gpu_status`。CUDA 验证失败时继续使用 CPU，并返回 `gpu_error`。CUDA 推理过程中发生设备或显存错误时，当前请求切回 CPU 重试。失败后至少间隔 60 秒才由后续识别请求触发下一次探测。

自动模式先加载 CPU 模型，再在检测到 CUDA 后加载 GPU 模型。离线部署可以将预下载的 CTranslate2 模型目录传给 `ASR_GPU_MODEL_PATH`。如果该目录中的模型与默认型号不同，也设置 `ASR_GPU_MODEL_SIZE`，使健康接口显示对应型号。

启用 CPU 中文 FunASR 时，在启动服务的 Python 环境安装 `funasr-onnx`，并将包含 `model_quant.onnx`、`tokens.json`、`am.mvn` 和 `config.yaml` 的 Paraformer 模型目录设为 `ASR_CPU_PARAFORMER_PATH`。等 CUDA 就绪后，两种语言都使用 CUDA 模型。无 GPU 设备在不同语言间切换时按需加载对应 CPU 模型。

Windows 上启用加速时，确认启动服务的 Python 进程能找到与 CTranslate2 版本匹配的 CUDA 运行库。若 `gpu_error` 提示缺少 `cublas64_12.dll`，将兼容的 cuBLAS DLL 所在目录加入启动终端的 `PATH`，然后重启服务。

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
│       ├── decoder.py       # wave + av 解码为 16kHz 单声道
│       ├── paraformer.py    # FunASR 中文 CPU 推理
│       ├── audio_utils.py   # 时长计算
│       └── transcriber.py   # 模型路由、懒加载和回退
├── models/                  # 本地权重、来源说明和校验清单
├── static/                  # 原生前端（HTML/CSS/JS）
├── tests/                   # pytest 用例（Mock 模型）
├── samples/                 # 中英文样例音频与参考文本
├── docs/                    # 考核需求、设计、测试结果和开发记录
├── requirements.txt
├── requirements-funasr.txt
└── pytest.ini
```

## 说明

- 解码直接读取上传流，推理在内存中执行。multipart 框架可能使用临时文件缓冲较大的上传，请求结束时关闭缓冲文件。
- 不保存识别历史、不做用户体系，纯本地单机运行。
- 浏览器录音使用 MediaRecorder（Chrome / Edge 输出 webm），后端统一解码，前端无需转码。
