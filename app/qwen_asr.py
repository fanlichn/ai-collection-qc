from collections import Counter

from faster_whisper.audio import decode_audio
from faster_whisper.vad import VadOptions, get_speech_timestamps

from .config import COMPARISON_MODEL

SAMPLE_RATE = 16000
LANGUAGE_CODES = {
    'Arabic': 'ar', 'Cantonese': 'yue', 'Chinese': 'zh', 'Czech': 'cs', 'Danish': 'da',
    'Dutch': 'nl', 'English': 'en', 'Filipino': 'fil', 'Finnish': 'fi', 'French': 'fr',
    'German': 'de', 'Greek': 'el', 'Hindi': 'hi', 'Hungarian': 'hu', 'Indonesian': 'id',
    'Italian': 'it', 'Japanese': 'ja', 'Korean': 'ko', 'Macedonian': 'mk', 'Malay': 'ms',
    'Persian': 'fa', 'Polish': 'pl', 'Portuguese': 'pt', 'Romanian': 'ro', 'Russian': 'ru',
    'Spanish': 'es', 'Swedish': 'sv', 'Thai': 'th', 'Turkish': 'tr', 'Vietnamese': 'vi',
}
_model = None


def transcribe(path: str) -> dict:
    global _model
    audio = decode_audio(path, sampling_rate=SAMPLE_RATE)
    speech = get_speech_timestamps(audio, VadOptions(max_speech_duration_s=25))
    rows = []
    language_samples = Counter()
    if speech:
        if _model is None:
            import torch
            from qwen_asr import Qwen3ASRModel

            _model = Qwen3ASRModel.from_pretrained(
                COMPARISON_MODEL, dtype=torch.float16, device_map='cuda:0',
                attn_implementation='sdpa', max_inference_batch_size=1, max_new_tokens=512,
            )
        for segment in speech:
            start, end = segment['start'], segment['end']
            result = _model.transcribe(audio=(audio[start:end], SAMPLE_RATE), language=None)[0]
            if result.text.strip():
                code = LANGUAGE_CODES.get(result.language)
                if code:
                    language_samples[code] += end - start
                rows.append({'start': round(start / SAMPLE_RATE, 2), 'end': round(end / SAMPLE_RATE, 2),
                             'text': result.text.strip(), 'speaker': 'UNKNOWN'})
    language = language_samples.most_common(1)[0][0] if language_samples else 'und'
    return {'language': language, 'duration': len(audio) / SAMPLE_RATE,
            'text': '\n'.join(row['text'] for row in rows), 'segments': rows}
