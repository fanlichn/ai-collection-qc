from pathlib import Path
from faster_whisper import WhisperModel
from .config import settings

_model = None

def get_model():
    global _model
    if _model is None:
        device = settings.whisper_device
        compute = settings.whisper_compute_type
        try:
            _model = WhisperModel(settings.whisper_model, device=device, compute_type=compute)
        except Exception:
            # CPU fallback keeps the service usable if CUDA/cuDNN is not correctly installed.
            _model = WhisperModel(settings.whisper_model, device='cpu', compute_type='int8')
    return _model

def transcribe(path: str):
    model = get_model()
    kwargs = {
        'beam_size': settings.whisper_beam_size,
        'vad_filter': True,
        'condition_on_previous_text': False,
    }
    if settings.whisper_language:
        kwargs['language'] = settings.whisper_language
    segments, info = model.transcribe(path, **kwargs)
    rows = []
    full = []
    for seg in segments:
        text = (seg.text or '').strip()
        if not text:
            continue
        rows.append({'start': round(seg.start, 2), 'end': round(seg.end, 2), 'text': text, 'speaker': 'UNKNOWN'})
        full.append(text)
    return {'language': info.language, 'language_probability': float(info.language_probability or 0),
            'duration': float(info.duration or 0), 'text': '\n'.join(full), 'segments': rows}
