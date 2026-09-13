"""Apple Vision OCR（macOS 系统框架）：pyobjc 依赖隔离，未安装时优雅降级。"""

from __future__ import annotations

_LANGS_DEFAULT = ["zh-Hans", "en-US"]


def available() -> bool:
    try:
        import Vision  # noqa: F401
    except ImportError:
        return False
    return True


def recognize_png(png: bytes, langs: list[str] | None = None) -> str:
    """识别 PNG 位图中的文字（Apple Vision，本机推理）。失败返回空串。"""
    import Vision

    handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(png, None)
    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    request.setRecognitionLanguages_(langs or list(_LANGS_DEFAULT))
    ok, _err = handler.performRequests_error_([request], None)
    if not ok:
        return ""
    lines: list[str] = []
    for observation in request.results() or []:
        candidates = observation.topCandidates_(1)
        if candidates:
            lines.append(candidates[0].string())
    return "\n".join(lines)
