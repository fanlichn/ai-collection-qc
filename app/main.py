from datetime import date, timedelta
from calendar import monthrange
from fastapi import FastAPI, Depends, Form, HTTPException, Query, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from sqlalchemy import select, func, desc, or_
from .login import credentials_match, login_page, session_user, start_session, verify_origin
from .config import COMPARISON_MODEL, settings
from .db import Base, engine, get_db
from .models import Recording, Transcript, Analysis, Employee, TranscriptComparison
from .oss import presigned_audio_url
from .recording_audio import resolve_audio_key
from .call_volume import employee_bindings, issue_labels, latest_analyses, recording_day, summarize_calls
from .call_outcome import WAIT_MARKER, is_wait_recording

app = FastAPI(title=settings.app_name, version='1.0.0')
security = HTTPBasic(auto_error=False)
Base.metadata.create_all(bind=engine)
app.mount('/static', StaticFiles(directory='web'), name='static')

def auth(request: Request, credentials: HTTPBasicCredentials | None = Depends(security)):
    unsafe = request.method not in ('GET', 'HEAD', 'OPTIONS')
    if credentials and credentials_match(credentials.username, credentials.password):
        if unsafe and 'origin' in request.headers:
            verify_origin(request)
        return credentials.username
    user = session_user(request)
    if user is None:
        raise HTTPException(401, 'Not authenticated', headers={'WWW-Authenticate': 'Basic'})
    if unsafe:
        verify_origin(request)
    return user

@app.get('/healthz')
def health(): return {'ok': True, 'service': settings.app_name}

@app.get('/', response_class=HTMLResponse)
def dashboard(request: Request, credentials: HTTPBasicCredentials | None = Depends(security)):
    if session_user(request) is None and not (credentials and credentials_match(
            credentials.username, credentials.password)):
        return login_page()
    with open('web/index.html', encoding='utf-8') as f:
        return HTMLResponse(f.read(), headers={'Cache-Control': 'no-store'})


@app.post('/login')
def login(request: Request, username: str = Form(max_length=256), password: str = Form(max_length=1024)):
    verify_origin(request)
    if not credentials_match(username, password):
        return login_page(invalid=True)
    response = RedirectResponse('/', status_code=303, headers={'Cache-Control': 'no-store'})
    start_session(request, response)
    return response


def analysis_grade(analysis: Analysis | None):
    if analysis is None:
        return None, None
    if analysis.model_name == 'rules-only' and analysis.score == 100:
        return None, 'REVIEW'
    return analysis.score, analysis.risk_level


@app.get('/api/overview')
def overview(_: str = Depends(auth), db: Session = Depends(get_db)):
    eligible = ~func.lower(Recording.filename).contains(WAIT_MARKER)
    total = db.scalar(select(func.count(Recording.id))) or 0
    completed = db.scalar(select(func.count(Recording.id)).where(Recording.status=='COMPLETED', eligible)) or 0
    pending = db.scalar(select(func.count(Recording.id)).where(Recording.status.in_(['PENDING','DOWNLOADING','TRANSCRIBING','ANALYZING']))) or 0
    failed = db.scalar(select(func.count(Recording.id)).where(Recording.status=='FAILED')) or 0
    ungraded = (Analysis.model_name == 'rules-only') & (Analysis.score == 100)
    avg = db.scalar(select(func.avg(Analysis.score)).join(Recording, Recording.id == Analysis.recording_id)
                    .where(eligible, ~ungraded))
    high = db.scalar(select(func.count(Analysis.id)).join(Recording, Recording.id == Analysis.recording_id).where(
        eligible,
        Analysis.risk_level.in_(['HIGH','REVIEW']) | (ungraded & Analysis.human_review_required)
    )) or 0
    return {'total':total,'completed':completed,'pending':pending,'failed':failed,'avg_score':round(float(avg),1) if avg is not None else None,'review_count':high}

def report_range(period: str, value: date):
    start = value.replace(day=1) if period == 'month' else value
    try:
        end = start + timedelta(days=monthrange(start.year, start.month)[1] if period == 'month' else 1)
    except OverflowError as exc:
        raise HTTPException(422, 'Date is outside the supported report range') from exc
    return start, end


@app.get('/api/call-volume')
def call_volume(period: str = Query(pattern=r'^(day|month)$'), value: date = Query(),
                include_issues: bool = False, _: str = Depends(auth), db: Session = Depends(get_db)):
    return summarize_calls(db, *report_range(period, value), include_issues=include_issues)


@app.get('/api/recordings')
def recordings(limit: int = Query(100, ge=1), q: str = Query('', max_length=200),
               period: str = Query('day', pattern=r'^(day|month)$'), value: date | None = None,
               employee: int | None = Query(None, ge=0), issue: str = Query('', max_length=500),
               page: int | None = Query(None, ge=1, le=2147483647),
               _: str = Depends(auth), db: Session = Depends(get_db)):
    query = select(Recording)
    keyword = q.strip()
    if keyword:
        comparison_text = select(TranscriptComparison.result['text'].as_string()).where(
            TranscriptComparison.recording_id == Recording.id,
            TranscriptComparison.status == 'COMPLETED',
        ).scalar_subquery()
        original_text = select(Transcript.text).where(
            Transcript.recording_id == Recording.id,
        ).order_by(Transcript.id.desc()).limit(1).scalar_subquery()
        query = query.where(or_(
            Recording.filename.contains(keyword, autoescape=True),
            Recording.device_id.contains(keyword, autoescape=True),
            func.coalesce(comparison_text, original_text).contains(keyword, autoescape=True),
        ))
    filtered_in_python = value is not None or bool(issue) or employee is not None
    limit = min(limit, 500) if page is None else 20
    offset = 0 if page is None else (page - 1) * limit
    total = 0
    if page is not None and not filtered_in_python:
        total = db.scalar(select(func.count()).select_from(query.subquery()))
    latest = latest_analyses()
    query = query.add_columns(Analysis).outerjoin(latest, latest.c.recording_id == Recording.id).outerjoin(
        Analysis, Analysis.id == latest.c.analysis_id).order_by(Recording.created_at.desc(), Recording.id.desc())
    if value is not None:
        start, end = report_range(period, value)
    owners = employee_bindings(db)[1] if employee is not None else {}
    if not filtered_in_python:
        query = query.offset(offset).limit(limit)
    out=[]
    for r, a in db.execute(query.execution_options(yield_per=1000)):
        if value is not None and not start <= recording_day(
                r.filename, r.object_key, r.last_modified, r.created_at) < end:
            continue
        if employee is not None:
            candidates = owners.get(r.device_id, ())
            owner = candidates[0] if len(candidates) == 1 else 0
            if owner != employee:
                continue
        unanswered = is_wait_recording(r.filename)
        if issue and (unanswered or issue not in issue_labels(a) or a.review_decision == 'REJECTED'):
            continue
        if page is not None and filtered_in_python:
            total += 1
            if total <= offset or len(out) == limit:
                continue
        score, risk = (None, None) if unanswered else analysis_grade(a)
        out.append({'id':r.id,'object_key':r.object_key,'device_id':r.device_id,'filename':r.filename,'size_bytes':r.size_bytes,
            'status':r.status,'language':r.detected_language,'score':score,'risk_level':risk,
            'unanswered': unanswered,
            'created_at':r.created_at.isoformat() if r.created_at else None,'error':r.error})
        if len(out) == limit and page is None:
            break
    if page is None:
        return out
    return {'rows': out, 'page': page, 'total': total, 'pages': max(1, (total + limit - 1) // limit)}

@app.get('/api/recordings/{recording_id}')
def recording_detail(recording_id:int, _:str=Depends(auth), db:Session=Depends(get_db)):
    r=db.get(Recording, recording_id)
    if not r: raise HTTPException(404,'Recording not found')
    t=db.scalar(select(Transcript).where(Transcript.recording_id==r.id).order_by(desc(Transcript.id)).limit(1))
    a=db.scalar(select(Analysis).where(Analysis.recording_id==r.id).order_by(desc(Analysis.id)).limit(1))
    unanswered = is_wait_recording(r.filename)
    score, risk = analysis_grade(a)
    analysis = None
    if a and not unanswered:
        summary = a.summary
        result = a.result
        if score is None:
            summary = '规则初筛未命中关键词。当前未评级，请结合原始录音确认通话是否属于催收场景。'
            result = {**result, 'score': score, 'risk_level': risk, 'summary': summary}
        analysis = {'score':score,'risk_level':risk,'summary':summary,'result':result,
            'human_review_required':a.human_review_required,'review_decision':a.review_decision,'review_note':a.review_note}
    return {'recording':{'id':r.id,'object_key':r.object_key,'device_id':r.device_id,'filename':r.filename,'status':r.status,'error':r.error,'language':r.detected_language,'duration_seconds':r.duration_seconds,'unanswered':unanswered},
        'transcript':{'language':t.language,'text':t.text,'segments':t.segments} if t else None,
        'analysis':analysis}

@app.get('/api/recordings/{recording_id}/audio')
def recording_audio(recording_id:int, _:str=Depends(auth), db:Session=Depends(get_db)):
    r=db.get(Recording, recording_id)
    if not r: raise HTTPException(404,'Recording not found')
    try:
        return {'url': presigned_audio_url(resolve_audio_key(db, r), 300)}
    except Exception as exc:
        raise HTTPException(502, 'Recording audio unavailable') from exc


@app.get('/api/recordings/{recording_id}/comparison')
def get_comparison(recording_id: int, _: str = Depends(auth), db: Session = Depends(get_db)):
    if db.get(Recording, recording_id) is None:
        raise HTTPException(404, 'Recording not found')
    job = db.get(TranscriptComparison, recording_id)
    return {'model': COMPARISON_MODEL, 'status': job.status if job else 'NOT_STARTED',
            'result': job.result if job else None}


@app.post('/api/recordings/{recording_id}/comparison', status_code=202)
def start_comparison(recording_id: int, _: str = Depends(auth), db: Session = Depends(get_db)):
    recording = db.get(Recording, recording_id, with_for_update=True)
    if recording is None:
        raise HTTPException(404, 'Recording not found')
    if (recording.status != 'COMPLETED' or is_wait_recording(recording.filename)
            or recording.size_bytes > settings.max_audio_mb * 1024 * 1024):
        raise HTTPException(409, 'Recording is not eligible for comparison')
    job = db.get(TranscriptComparison, recording_id)
    if job is None:
        job = TranscriptComparison(recording_id=recording_id, status='PENDING')
        db.add(job)
    elif job.status == 'FAILED':
        job.status = 'PENDING'
    db.commit()
    return {'status': job.status}

@app.post('/api/recordings/{recording_id}/retry')
def retry_recording(recording_id:int, _:str=Depends(auth), db:Session=Depends(get_db)):
    r=db.get(Recording, recording_id)
    if not r: raise HTTPException(404,'Recording not found')
    if r.status != 'FAILED': raise HTTPException(409,'Only FAILED recordings can be retried')
    r.status='PENDING'; r.error=None; db.commit(); return {'ok':True}

@app.post('/api/recordings/{recording_id}/review')
def review(recording_id:int, payload:dict, user:str=Depends(auth), db:Session=Depends(get_db)):
    recording = db.get(Recording, recording_id)
    if recording and is_wait_recording(recording.filename):
        raise HTTPException(409, 'Waiting recordings are excluded from quality review')
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
        score, risk = (None, None) if is_wait_recording(r.filename) else analysis_grade(a)
        w.writerow([r.id,r.object_key,r.device_id,r.filename,r.status,r.detected_language,score,risk,r.created_at])
    return StreamingResponse(iter([buf.getvalue()]),media_type='text/csv',headers={'Content-Disposition':'attachment; filename=qc-recordings.csv'})
