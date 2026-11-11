import json, re
from openai import OpenAI
from .config import settings

# Starter rules are deliberately conservative. Replace/extend them with approved local policy.
RULES = [
 {'code':'THREAT','title':'威胁或恐吓表达','severity':'HIGH','deduction':35,'patterns':[
  r'we will come to your house', r'we will arrest you', r'you will be jailed', r'පොලිසියට', r'ගෙදරට එනවා', r'உன்னை கைது', r'घर.*आएंगे']},
 {'code':'INSULT','title':'辱骂或侮辱性表达','severity':'HIGH','deduction':30,'patterns':[
  r'idiot', r'stupid', r'ගොනා', r'முட்டாள்', r'傻逼', r'废物']},
 {'code':'THIRD_PARTY','title':'疑似向第三方披露债务','severity':'HIGH','deduction':30,'patterns':[
  r'tell your employer', r'tell your family.*loan', r'ඔබේ පවුලට.*ණය', r'உங்கள் குடும்பத்திடம்.*கடன்']},
 {'code':'NO_INTRO','title':'未识别到身份/机构介绍','severity':'MEDIUM','deduction':8,'patterns':[]},
]

def rules_analysis(transcript: str):
    low = transcript.lower()
    violations = []
    for rule in RULES:
        matched = []
        for pattern in rule['patterns']:
            m = re.search(pattern, low, re.I)
            if m: matched.append(m.group(0))
        if matched:
            violations.append({'code':rule['code'],'title':rule['title'],'severity':rule['severity'],
                'deduction':rule['deduction'],'evidence':matched[:3], 'confidence':'LOW',
                'note':'关键词命中仅用于筛查，必须结合原始录音和完整上下文人工复核。'})
    score = max(0, 100 - sum(v['deduction'] for v in violations))
    return {'score':score,'risk_level':'HIGH' if any(v['severity']=='HIGH' for v in violations) else ('REVIEW' if violations else 'LOW'),
            'summary':'规则初筛完成；当前规则不是法律结论，也不应单独用于员工处罚。',
            'violations':violations,'dimensions':[], 'recommendations':['复核原始录音及上下文','使用经法务/合规批准的当地催收规则']}

def analyze(transcript: str, language: str):
    if not settings.openai_api_key or not settings.openai_base_url or not settings.openai_model:
        result = rules_analysis(transcript)
        result['analysis_mode'] = 'rules-only'
        return result, 'rules-only'
    client = OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)
    system = '''You are a cautious financial collections call quality reviewer. Analyze the transcript in its original language. Do not invent facts. Do not treat keyword matches as proof. Quote exact evidence with timestamps if present. Separate confirmed facts from uncertain interpretations. Never infer emotion or intent as fact. Return ONLY valid JSON with keys: score (0-100), risk_level (LOW/MEDIUM/HIGH/REVIEW), summary, violations (array of {code,title,severity,confidence,evidence,reason,timestamp_start,timestamp_end}), dimensions (array of {name,score,max_score,reason}), recommendations (array), human_review_required (boolean). A potential legal/policy breach must be REVIEW, not a final legal determination.'''
    user = f'Language: {language}\nTranscript:\n{transcript[:50000]}'
    response = client.chat.completions.create(model=settings.openai_model, temperature=0.1,
        response_format={'type':'json_object'}, messages=[{'role':'system','content':system},{'role':'user','content':user}])
    data = json.loads(response.choices[0].message.content)
    data.setdefault('violations', []); data.setdefault('dimensions', []); data.setdefault('recommendations', [])
    data['analysis_mode'] = 'llm+rules'
    # Deterministic screening runs alongside LLM; union violations by code/evidence.
    deterministic = rules_analysis(transcript)
    known = {(v.get('code'), str(v.get('evidence'))) for v in data['violations']}
    for v in deterministic['violations']:
        if (v['code'], str(v['evidence'])) not in known:
            data['violations'].append(v)
    if any(v.get('severity') == 'HIGH' for v in data['violations']):
        data['risk_level'] = 'REVIEW'
        data['human_review_required'] = True
    return data, settings.openai_model
