import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .call_outcome import is_wait_recording
from .models import Analysis, Employee, Recording

REPORT_TIMEZONE = timezone(timedelta(hours=8), 'Asia/Shanghai')
FILENAME_TIME = re.compile(r'(?:^|[_-])(\d{14})\.[^.]+$')
DATE_PART = re.compile(r'\d{4}-\d{2}-\d{2}')


def recording_day(filename, object_key, last_modified, created_at):
    match = FILENAME_TIME.search(filename)
    if match:
        try:
            return datetime.strptime(match[1], '%Y%m%d%H%M%S').date()
        except ValueError:
            pass
    parts = object_key.rsplit('/', 2)
    folder = parts[-2] if len(parts) == 3 else ''
    if DATE_PART.fullmatch(folder):
        try:
            return date.fromisoformat(folder)
        except ValueError:
            pass
    timestamp = last_modified or created_at
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(REPORT_TIMEZONE).date()


def employee_bindings(db: Session):
    employees = db.scalars(select(Employee).where(Employee.active.is_(True))
                           .order_by(Employee.employee_code, Employee.id)).all()
    owners = defaultdict(list)
    for employee in employees:
        if employee.device_id:
            owners[employee.device_id].append(employee.id)
    return employees, owners


def latest_analyses():
    return select(Analysis.recording_id, func.max(Analysis.id).label('analysis_id')).group_by(
        Analysis.recording_id).subquery()


def issue_labels(analysis):
    result = analysis.result if analysis and isinstance(analysis.result, dict) else {}
    violations = result.get('violations')
    if not isinstance(violations, list):
        return set()
    return {v['title'].strip() for v in violations if isinstance(v, dict)
            and isinstance(v.get('title'), str) and v['title'].strip()}


def summarize_calls(db: Session, start: date, end: date, *, include_issues: bool = False):
    employees, owners = employee_bindings(db)
    days = [(start + timedelta(days=offset)).isoformat() for offset in range((end - start).days)]
    counts = defaultdict(Counter)
    issues = defaultdict(Counter)
    query = select(Recording.filename, Recording.object_key, Recording.device_id,
                   Recording.last_modified, Recording.created_at)
    if include_issues:
        latest = latest_analyses()
        query = query.add_columns(Analysis).outerjoin(latest, latest.c.recording_id == Recording.id).outerjoin(
            Analysis, Analysis.id == latest.c.analysis_id)
    for filename, key, device, modified, created, *analysis_row in db.execute(
            query.execution_options(yield_per=1000)):
        day = recording_day(filename, key, modified, created)
        if not start <= day < end:
            continue
        candidates = owners.get(device, ())
        employee_id = candidates[0] if len(candidates) == 1 else None
        counts[employee_id][day.isoformat()] += 1
        if analysis_row and not is_wait_recording(filename):
            analysis = analysis_row[0]
            for label in issue_labels(analysis):
                if analysis.review_decision == 'REJECTED':
                    continue
                state = 'confirmed' if analysis.review_decision == 'CONFIRMED' else 'pending'
                issues[label][state] += 1

    rows = [{'id': e.id, 'name': e.name, 'code': e.employee_code,
             'counts': [counts[e.id][day] for day in days], 'total': sum(counts[e.id].values())}
            for e in employees]
    if counts[None]:
        rows.append({'id': None, 'name': '未归属', 'code': '',
                     'counts': [counts[None][day] for day in days], 'total': sum(counts[None].values())})
    return {'days': days, 'rows': rows, 'total': sum(row['total'] for row in rows),
            'issues': [{'label': label, 'pending': count['pending'], 'confirmed': count['confirmed']}
                       for label, count in sorted(issues.items(), key=lambda entry: (-sum(entry[1].values()), entry[0]))]}
