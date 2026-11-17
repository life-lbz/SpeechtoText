"""FunASR Paraformer 中文 CPU 推理。"""

from pathlib import Path

import numpy as np


class ParaformerModel:
    """按语音段运行 ONNX 模型，输入为 16 kHz 单声道波形。"""

    def __init__(self, model_path: str):
        from funasr_onnx import Paraformer

        if not (Path(model_path) / "model_quant.onnx").is_file():
            raise FileNotFoundError(f"找不到 Paraformer 量化权重：{model_path}")
        self._recognizer = Paraformer(
            model_path, batch_size=1, device_id="-1", quantize=True, intra_op_num_threads=4,
        )

    def transcribe(self, audio: np.ndarray) -> str:
        from faster_whisper.vad import VadOptions, get_speech_timestamps

        texts = []
        for part in get_speech_timestamps(audio, VadOptions(max_speech_duration_s=25)):
            predictions = self._recognizer(audio[part["start"]:part["end"]])
            if predictions:
                text = predictions[0]["preds"]
                texts.append(text if isinstance(text, str) else text[0])
        return " ".join(texts)
