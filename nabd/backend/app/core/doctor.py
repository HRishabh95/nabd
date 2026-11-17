"""Environment checks shared by `nabd doctor` and GET /api/system/doctor."""

import shutil
import subprocess
import sys

from .config import get_settings
from .db import conn


def checks() -> list[dict]:
    s = get_settings()
    out = []

    def add(name, ok, detail, fix=None, warn=False):
        level = "ok" if ok else ("warn" if warn else "fail")
        out.append({"name": name, "ok": bool(ok) or warn, "level": level, "detail": detail, "fix": fix})

    add("Python", sys.version_info >= (3, 12), sys.version.split()[0], "Use Python 3.12+ (uv sync)")
    try:
        conn().execute("SELECT 1")
        add("Database", True, str(s.db_path))
    except Exception as exc:  # pragma: no cover
        add("Database", False, str(exc))

    add("LLM provider", s.llm_provider in {"codex", "azure_openai", "local"}, s.llm_provider)
    if s.llm_provider == "codex":
        path = shutil.which(s.codex_bin)
        if not path:
            add("Codex CLI", False, "not found on PATH", "npm i -g @openai/codex")
        else:
            try:
                v = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=10).stdout.strip()
                add("Codex CLI", True, v)
                st = subprocess.run([path, "login", "status"], capture_output=True, text=True, timeout=15)
                status = (st.stdout or st.stderr).strip().splitlines()
                add("Codex sign-in", st.returncode == 0 and "Logged in" in " ".join(status),
                    status[0] if status else "unknown", "codex login")
            except Exception as exc:
                add("Codex CLI", False, str(exc))
        add("Data residency", False,
            "Codex sends prompts to OpenAI; demo with open data only",
            "Use azure_openai (UAE North) or local for any CBUAE data", warn=True)
    add("FRED API key", bool(s.fred_api_key), "set" if s.fred_api_key else "not set (optional: the public CSV is used)",
        "Free key at fred.stlouisfed.org; set NABD_FRED_API_KEY in nabd/.env", warn=True)
    add("SEC EDGAR", bool(s.sec_user_agent), "contact set" if s.sec_user_agent else "off: needs a contact header",
        'Set NABD_SEC_USER_AGENT="Org name contact@org" in nabd/.env', warn=True)
    return out
