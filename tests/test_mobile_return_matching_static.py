from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
JS=(ROOT/"app/static/app.js").read_text(encoding="utf-8")

def test_return_match_is_serialized_before_submit():
    assert "function serializeReturnChecks(form)" in JS
    assert "if(id==='returnForm')" in JS
    assert "if(!serializeReturnChecks(form)) return;" in JS
    assert "issue_results_json" in JS
    assert "match: matched" in JS

def test_unmatched_requires_actual_quantity():
    assert "if(!matched && !actual)" in JS
