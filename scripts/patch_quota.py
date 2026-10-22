from pathlib import Path

path = Path("app/services/youtube.py")
text = path.read_text(encoding="utf-8")

old_block = """def youtube_credentials() -> Credentials:
    \"\"\"Load and refresh the private OAuth token for both API and resumable HTTP requests.\"\"\"
    settings = get_settings()"""

new_block = """def youtube_credentials() -> Credentials:
    \"\"\"Load and refresh the private OAuth token for both API and resumable HTTP requests.\"\"\"
    try:
        from app.services.quota_rotator import get_next_available_credentials
        creds, _ = get_next_available_credentials()
        return creds
    except Exception as rot_err:
        log.warning("Quota rotator fallback: %s", rot_err)
    settings = get_settings()"""

if old_block in text:
    text = text.replace(old_block, new_block, 1)

old_start = """    status = int(getattr(response, "status_code", 0) or 0)
    if status != 200:
        raise RuntimeError(f"YouTube rejected resumable session initialization (HTTP {status})")"""

new_start = """    status = int(getattr(response, "status_code", 0) or 0)
    if status != 200:
        err_detail = getattr(response, "text", "")[:250]
        if status == 429:
            try:
                from app.services.quota_rotator import get_next_available_credentials, mark_project_exhausted
                _, current_tok = get_next_available_credentials()
                mark_project_exhausted(current_tok, err_detail)
            except Exception:
                pass
        raise RuntimeError(f"YouTube rejected resumable session initialization (HTTP {status}): {err_detail}")"""

if old_start in text:
    text = text.replace(old_start, new_start, 1)

path.write_text(text, encoding="utf-8")
print("youtube.py successfully patched with quota rotator integration!")
