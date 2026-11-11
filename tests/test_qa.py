from app.qa import rules_analysis

def test_safe_text_no_violation():
    r=rules_analysis('Good morning. I am calling about your payment. Can you pay next Friday?')
    assert r['score']==100
    assert not r['violations']

def test_threat_flagged_for_review():
    r=rules_analysis("If you don't pay, we will come to your house.")
    assert r['risk_level']=='HIGH'
    assert r['violations'][0]['code']=='THREAT'
