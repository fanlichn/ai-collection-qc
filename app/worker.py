import os, time, logging
from datetime import datetime
from sqlalchemy import select
from .config import settings
from .db import SessionLocal, engine, Base
from .models import Recording, Transcript, Analysis
from .oss import iter_audio_objects, download_object
from .asr import transcribe
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
            log.info('Completed recording id=%s lang=%s score=%s', rec.id, result['language'], score)
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

def main():
    Base.metadata.create_all(bind=engine)
    last_scan = 0
    while True:
        try:
            if time.time() - last_scan >= settings.oss_scan_interval:
                discover(); last_scan = time.time()
            did = process_one()
            if not did: time.sleep(settings.worker_poll_seconds)
        except Exception:
            log.exception('Worker loop error'); time.sleep(15)

if __name__ == '__main__': main()
