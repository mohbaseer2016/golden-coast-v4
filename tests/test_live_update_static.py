from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
MAIN=(ROOT/"app/main.py").read_text(encoding="utf-8")
HTML=(ROOT/"app/templates/index.html").read_text(encoding="utf-8")
JS=(ROOT/"app/static/app.js").read_text(encoding="utf-8")

def test_render_commit_is_version_source():
    assert 'os.getenv("RENDER_GIT_COMMIT")' in MAIN
    assert '@app.get("/api/version")' in MAIN

def test_shell_and_version_are_no_cache():
    assert 'Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"' in MAIN
    assert 'path == "/"' in MAIN and 'path == "/api/version"' in MAIN

def test_static_assets_are_commit_versioned():
    assert 'app.css?v={{ app_version }}' in HTML
    assert 'app.js?v={{ app_version }}' in HTML
    assert 'window.APP_VERSION = "{{ app_version }}"' in HTML

def test_update_check_does_not_force_reload():
    assert "checkForAppUpdate" in JS
    assert "setInterval(checkForAppUpdate, 60000)" in JS
    assert "location.reload()" in JS
    assert "activeForm" in JS
    assert "تحديث الآن" in JS
