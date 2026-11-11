from datetime import datetime
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from sqlalchemy import select, func, desc
import secrets, os
from .config import settings
from .db import Base, engine, get_db
from .models import Recording, Transcript, Analysis, Employee
from .oss import presigned_audio_url

app = FastAPI(title=settings.app_name, version='1.0.0')
security = HTTPBasic()
Base.metadata.create_all(bind=engine)
app.mount('/static', StaticFiles(directory='web'), name='static')

def auth(credentials: HTTPBasicCredentials = Depends(security)):
    user_ok = secrets.compare_digest(credentials.username, settings.admin_user)
    pass_ok = secrets.compare_digest(credentials.password, settings.admin_password)
    if not (user_ok and pass_ok):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Invalid credentials', headers={'WWW-Authenticate':'Basic'})
    return credentials.username

@app.get('/healthz')
def health(): return {'ok': True, 'service': settings.app_name}

@app.get('/', response_class=HTMLResponse)
def dashboard(_: str = Depends(auth)):
    with open('web/index.html', encoding='utf-8') as f: return f.read()


def analysis_grade(analysis: Analysis | None):
    if analysis is None:
        return None, None
    if analysis.model_name == 'rules-only' and analysis.score == 100:
        return None, 'REVIEW'
    return analysis.score, analysis.risk_level


@app.get('/api/overview')
def overview(_: str = Depends(auth), db: Session = Depends(get_db)):
    total = db.scalar(select(func.count(Recording.id))) or 0
    completed = db.scalar(select(func.count(Recording.id)).where(Recording.status=='COMPLETED')) or 0
    pending = db.scalar(select(func.count(Recording.id)).where(Recording.status.in_(['PENDING','DOWNLOADING','TRANSCRIBING','ANALYZING']))) or 0
    failed = db.scalar(select(func.count(Recording.id)).where(Recording.status=='FAILED')) or 0
    ungraded = (Analysis.model_name == 'rules-only') & (Analysis.score == 100)
    avg = db.scalar(select(func.avg(Analysis.score)).where(~ungraded))
    high = db.scalar(select(func.count(Analysis.id)).where(
        Analysis.risk_level.in_(['HIGH','REVIEW']) | (ungraded & Analysis.human_review_required)
    )) or 0
    return {'total':total,'completed':completed,'pending':pending,'failed':failed,'avg_score':round(float(avg),1) if avg is not None else None,'review_count':high}

@app.get('/api/recordings')
def recordings(limit: int=100, _: str=Depends(auth), db: Session=Depends(get_db)):
    rows = db.scalars(select(Recording).order_by(desc(Recording.created_at)).limit(min(limit,500))).all()
    out=[]
    for r in rows:
        a=db.scalar(select(Analysis).where(Analysis.recording_id==r.id).order_by(desc(Analysis.id)).limit(1))
        score, risk = analysis_grade(a)
        out.append({'id':r.id,'object_key':r.object_key,'device_id':r.device_id,'filename':r.filename,'size_bytes':r.size_bytes,
            'status':r.status,'language':r.detected_language,'score':score,'risk_level':risk,
            'created_at':r.created_at.isoformat() if r.created_at else None,'error':r.error})
    return out

@app.get('/api/recordings/{recording_id}')
def recording_detail(recording_id:int, _:str=Depends(auth), db:Session=Depends(get_db)):
    r=db.get(Recording, recording_id)
    if not r: raise HTTPException(404,'Recording not found')
    t=db.scalar(select(Transcript).where(Transcript.recording_id==r.id).order_by(desc(Transcript.id)).limit(1))
    a=db.scalar(select(Analysis).where(Analysis.recording_id==r.id).order_by(desc(Analysis.id)).limit(1))
    score, risk = analysis_grade(a)
    analysis = None
    if a:
        summary = a.summary
        result = a.result
        if score is None:
            summary = '规则初筛未命中关键词。当前未评级，请结合原始录音确认通话是否属于催收场景。'
            result = {**result, 'score': score, 'risk_level': risk, 'summary': summary}
        analysis = {'score':score,'risk_level':risk,'summary':summary,'result':result,
            'human_review_required':a.human_review_required,'review_decision':a.review_decision,'review_note':a.review_note}
    return {'recording':{'id':r.id,'object_key':r.object_key,'device_id':r.device_id,'filename':r.filename,'status':r.status,'error':r.error,'language':r.detected_language,'duration_seconds':r.duration_seconds},
        'transcript':{'language':t.language,'text':t.text,'segments':t.segments} if t else None,
        'analysis':analysis}

@app.get('/api/recordings/{recording_id}/audio')
def recording_audio(recording_id:int, _:str=Depends(auth), db:Session=Depends(get_db)):
    r=db.get(Recording, recording_id)
    if not r: raise HTTPException(404,'Recording not found')
    try: return {'url':presigned_audio_url(r.object_key, 300)}
    except Exception as exc: raise HTTPException(502, f'OSS audio URL error: {exc}')

@app.post('/api/recordings/{recording_id}/retry')
def retry_recording(recording_id:int, _:str=Depends(auth), db:Session=Depends(get_db)):
    r=db.get(Recording, recording_id)
    if not r: raise HTTPException(404,'Recording not found')
    if r.status != 'FAILED': raise HTTPException(409,'Only FAILED recordings can be retried')
    r.status='PENDING'; r.error=None; db.commit(); return {'ok':True}

@app.post('/api/recordings/{recording_id}/review')
def review(recording_id:int, payload:dict, user:str=Depends(auth), db:Session=Depends(get_db)):
    a=db.scalar(select(Analysis).where(Analysis.recording_id==recording_id).order_by(desc(Analysis.id)).limit(1))
    if not a: raise HTTPException(404,'Analysis not found')
    decision=payload.get('decision')
    if decision not in ['CONFIRMED','REJECTED','NEEDS_MORE_INFO']: raise HTTPException(400,'Invalid decision')
    a.reviewed_by=user; a.review_decision=decision; a.review_note=str(payload.get('note',''))[:4000]; a.human_review_required=False
    db.commit(); return {'ok':True}

@app.get('/api/employees')
def employees(_:str=Depends(auth), db:Session=Depends(get_db)):
    return [{'id':e.id,'employee_code':e.employee_code,'name':e.name,'team':e.team,'device_id':e.device_id,'active':e.active} for e in db.scalars(select(Employee).order_by(Employee.id)).all()]

@app.post('/api/employees')
def create_employee(payload:dict, _:str=Depends(auth), db:Session=Depends(get_db)):
    code=str(payload.get('employee_code','')).strip(); name=str(payload.get('name','')).strip()
    if not code or not name: raise HTTPException(400,'employee_code and name required')
    if db.scalar(select(Employee).where(Employee.employee_code==code)): raise HTTPException(409,'employee_code exists')
    e=Employee(employee_code=code,name=name,team=str(payload.get('team','')),device_id=payload.get('device_id'))
    db.add(e); db.commit(); return {'id':e.id}

@app.get('/api/export.csv')
def export_csv(_:str=Depends(auth), db:Session=Depends(get_db)):
    import csv, io
    from fastapi.responses import StreamingResponse
    buf=io.StringIO(); w=csv.writer(buf); w.writerow(['id','object_key','device_id','filename','status','language','score','risk_level','created_at'])
    for r in db.scalars(select(Recording).order_by(desc(Recording.created_at))).all():
        a=db.scalar(select(Analysis).where(Analysis.recording_id==r.id).order_by(desc(Analysis.id)).limit(1))
        score, risk = analysis_grade(a)
        w.writerow([r.id,r.object_key,r.device_id,r.filename,r.status,r.detected_language,score,risk,r.created_at])
    return StreamingResponse(iter([buf.getvalue()]),media_type='text/csv',headers={'Content-Disposition':'attachment; filename=qc-recordings.csv'})
