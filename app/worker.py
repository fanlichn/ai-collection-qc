import os, time, logging
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
from sqlalchemy import select, update
from .config import COMPARISON_MODEL, settings
from .call_outcome import is_wait_recording
from .db import SessionLocal, engine, Base
from .models import Recording, Transcript, Analysis, TranscriptComparison
from .oss import iter_audio_objects, download_object
from .qwen_asr import transcribe
from .recording_audio import resolve_audio_key
from .qa import analyze

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('qc-worker')


def discover():
    db = SessionLocal(); added = 0
    try:
        for obj in iter_audio_objects():
            rec = db.scalar(select(Recording).where(Recording.object_key == obj['key']))
            if rec:
                continue
            parts = obj['key'].split('/')
            device_id = parts[0] if len(parts) >= 3 else 'unknown'
            rec = Recording(object_key=obj['key'], etag=obj['etag'], device_id=device_id,
                filename=parts[-1], size_bytes=obj['size'], last_modified=obj['last_modified'], status='PENDING')
            db.add(rec); added += 1
        db.commit()
    except Exception:
        db.rollback(); raise
    finally: db.close()
    if added: log.info('Discovered %s new recordings', added)

def process_one():
    db = SessionLocal()
    try:
        rec = db.scalar(select(Recording).where(Recording.status == 'PENDING').order_by(Recording.id).limit(1))
        if not rec: return False
        if is_wait_recording(rec.filename):
            rec.status = 'COMPLETED'
            rec.error = None
            db.commit()
            log.info('Skipped QC for waiting recording id=%s', rec.id)
            return True
        if rec.size_bytes > settings.max_audio_mb * 1024 * 1024:
            rec.status='FAILED'; rec.error=f'File exceeds MAX_AUDIO_MB={settings.max_audio_mb}'; db.commit(); return True
        rec.status='DOWNLOADING'; rec.error=None; db.commit()
        os.makedirs(settings.audio_tmp_dir, exist_ok=True)
        local_path = os.path.join(settings.audio_tmp_dir, f'{rec.id}_{os.path.basename(rec.filename)}')
        try:
            download_object(rec.object_key, local_path)
            rec.status='TRANSCRIBING'; db.commit()
            result = transcribe(local_path)
            rec.duration_seconds=result['duration']; rec.detected_language=result['language']
            db.add(Transcript(recording_id=rec.id, language=result['language'], text=result['text'], segments=result['segments']))
            rec.status='ANALYZING'; db.commit()
            qa, model_name = analyze(result['text'], result['language'])
            score = int(max(0, min(100, qa.get('score', 0))))
            db.add(Analysis(recording_id=rec.id, score=score, risk_level=qa.get('risk_level','REVIEW'),
                summary=qa.get('summary',''), result=qa, model_name=model_name,
                human_review_required=bool(qa.get('human_review_required', True) or qa.get('violations'))))
            rec.status='COMPLETED'; db.commit()
            log.info('Completed recording id=%s asr=%s lang=%s score=%s',
                     rec.id, COMPARISON_MODEL, result['language'], score)
        except Exception as exc:
            db.rollback()
            rec = db.get(Recording, rec.id)
            if rec:
                rec.status='FAILED'; rec.error=str(exc)[:4000]; db.commit()
            log.exception('Processing failed for recording id=%s', rec.id)
        finally:
            try: os.remove(local_path)
            except Exception: pass
        return True
    finally: db.close()

def process_comparison():
    expired = datetime.utcnow() - timedelta(hours=1)
    claim = uuid4().hex
    with SessionLocal.begin() as db:
        job = db.scalar(select(TranscriptComparison).where(
            (TranscriptComparison.status == 'PENDING')
            | ((TranscriptComparison.status == 'RUNNING') & (TranscriptComparison.updated_at < expired))
        ).order_by(TranscriptComparison.updated_at, TranscriptComparison.recording_id)
            .limit(1).with_for_update(skip_locked=True))
        if job is None:
            return False
        recording_id = job.recording_id
        job.status = 'RUNNING'
        job.claim = claim

    try:
        with SessionLocal() as db:
            recording = db.get(Recording, recording_id)
            if (recording is None or is_wait_recording(recording.filename)
                    or recording.size_bytes > settings.max_audio_mb * 1024 * 1024):
                raise ValueError('Recording is not eligible for comparison')
            key = resolve_audio_key(db, recording)
        with TemporaryDirectory() as directory:
            path = str(Path(directory) / 'recording')
            download_object(key, path)
            result = transcribe(path)
        status = 'COMPLETED'
    except Exception as exc:
        log.warning('Comparison failed for recording id=%s: %s', recording_id, type(exc).__name__)
        status, result = 'FAILED', None

    with SessionLocal.begin() as db:
        db.execute(update(TranscriptComparison).where(
            TranscriptComparison.recording_id == recording_id, TranscriptComparison.claim == claim
        ).values(status=status, result=result, claim=None))
    return True


def main():
    Base.metadata.create_all(bind=engine)
    last_scan = 0
    while True:
        try:
            if time.time() - last_scan >= settings.oss_scan_interval:
                discover(); last_scan = time.time()
            did = process_one()
            compared = process_comparison()
            if not did and not compared: time.sleep(settings.worker_poll_seconds)
        except Exception:
            log.exception('Worker loop error'); time.sleep(15)

if __name__ == '__main__': main()
