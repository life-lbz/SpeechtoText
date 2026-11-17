# 本地模型

本目录包含应用运行所需的三套权重，合计约 2.0 GB，随项目一同交付。服务按下列默认目录名自动加载。Git 跟踪模型说明和 SHA-256 清单，二进制权重单独交付。

## 运行模型

| 目录 | 用途 | 来源 |
|---|---|---|
| `funasr-paraformer` | CPU 中文，ONNX INT8 | [FunASR Paraformer](https://modelscope.cn/models/iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-onnx) |
| `faster-whisper-base` | CPU 英文，或 FunASR 不可用时的 CPU 转写 | [Systran faster-whisper-base](https://huggingface.co/Systran/faster-whisper-base) |
| `faster-whisper-large-v3-turbo` | NVIDIA CUDA 中文和英文 | [CTranslate2 Turbo 权重](https://modelscope.cn/models/mobiuslabsgmbh/faster-whisper-large-v3-turbo) |

## 对比测试留存

以下模型保留来源和测试记录。所列耗时均来自同一段 2 分钟面试音频，术语命中数按 11 个抽查术语的完整拼写统计。

| 模型 | 测试记录 | 来源 |
|---|---|---|
| Whisper `small` | GPU 加术语提示，命中 11/11，4.04 秒 | [Systran faster-whisper-small](https://modelscope.cn/models/Systran/faster-whisper-small) |
| Whisper `medium` | GPU 加术语提示，命中 11/11，7.66 秒 | [Systran faster-whisper-medium](https://modelscope.cn/models/Systran/faster-whisper-medium) |
| FunASR Contextual Paraformer | CPU 加术语提示，命中 4/11，4.51 秒 | [Contextual Paraformer](https://modelscope.cn/models/iic/speech_paraformer-large-contextual_asr_nat-zh-cn-16k-common-vocab8404-onnx) |
| SenseVoice INT8 | CPU 默认识别，命中 2/11，2.96 秒 | [sherpa-onnx 官方模型发布包](https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2025-09-09.tar.bz2) |

## 文件校验

在项目根目录可用 PowerShell 校验全部权重和配置文件。

```powershell
Get-Content models/SHA256SUMS.txt | ForEach-Object {
    $expected, $relativePath = $_ -split '  ', 2
    $path = Join-Path 'models' $relativePath
    if ((Get-FileHash -LiteralPath $path -Algorithm SHA256 -ErrorAction Stop).Hash -ne $expected) {
        throw "SHA-256 mismatch: $path"
    }
}
```
