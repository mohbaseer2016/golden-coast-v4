from pathlib import Path
import re
ROOT=Path(__file__).resolve().parents[1]
MAIN=(ROOT/"app/main.py").read_text(encoding="utf-8")
JS=(ROOT/"app/static/app.js").read_text(encoding="utf-8")

def test_update_user_updates_same_row():
    b=re.search(r'@app\.post\("/api/users/\{username\}"\).*?(?=\n@app\.)',MAIN,re.S).group(0)
    assert "user.username = new_username" in b
    assert "db.add(User(" not in b

def test_default_users_seed_only_on_empty_database():
    startup=re.search(r'@app\.on_event\("startup"\).*?(?=\n@app\.)',MAIN,re.S).group(0)
    assert "has_any_user" in startup
    assert "if not has_any_user:" in startup
    assert 'upsert_user(db, "hr1"' in startup
    assert 'upsert_user(db, "dr1"' in startup

def test_edit_form_uses_update_endpoint():
    assert 'id="editUserForm"' in JS
    assert "url = '/api/users/' + encodeURIComponent(form.dataset.username)" in JS
