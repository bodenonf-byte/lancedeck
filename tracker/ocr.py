"""Text off a frame.  RapidOCR on ONNX Runtime; DirectML (the GPU) when available — on an
RTX 4090 a 1080p frame reads in under 400 ms and the lance-panel corner in ~60 ms, against
3 s and 1 s on the CPU.  Returns lines with their boxes so the matcher can group tokens
into rows, pair columns by order, and sample a text's colour for friend/enemy.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
from PIL import Image

logging.getLogger("OrtInferSession").setLevel(logging.WARNING)


@dataclass
class Line:
    text: str
    conf: float
    x0: int
    y0: int
    x1: int
    y1: int

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2

    @property
    def h(self) -> int:
        return self.y1 - self.y0


class Reader:
    def __init__(self, use_dml: bool = True, det_limit: int = 1920, threads: int = 0):
        from rapidocr_onnxruntime import RapidOCR
        self.backend = "cpu"
        kw = dict(det_limit_side_len=det_limit, det_limit_type="max")
        if threads and not use_dml:
            kw.update(intra_op_num_threads=int(threads), inter_op_num_threads=1)
        if use_dml:
            try:
                import onnxruntime as ort
                if "DmlExecutionProvider" in ort.get_available_providers():
                    self.engine = RapidOCR(det_use_dml=True, rec_use_dml=True, cls_use_dml=True, **kw)
                    self.backend = "dml"
                    return
            except Exception:
                pass
        self.engine = RapidOCR(**kw)

    def read(self, img: Image.Image, scale: float = 1.0) -> list[Line]:
        if scale != 1.0:
            img = img.resize((int(img.width * scale), int(img.height * scale)), Image.BILINEAR)
        arr = np.asarray(img.convert("RGB"))
        result, _ = self.engine(arr, use_cls=False)      # the HUD is never rotated; the angle classifier is a third of the time
        out: list[Line] = []
        if not result:
            return out
        for box, text, conf in result:
            xs = [p[0] for p in box]; ys = [p[1] for p in box]
            out.append(Line(text, float(conf), int(min(xs) / scale), int(min(ys) / scale),
                            int(max(xs) / scale), int(max(ys) / scale)))
        out.sort(key=lambda l: (l.cy, l.x0))
        return out
