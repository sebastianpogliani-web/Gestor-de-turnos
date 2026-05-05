"""
actualizar.py — obtiene eventos de Google Calendar API, inyecta en index.html y hace git push.
Primera corrida: abre el browser para autorizar (guarda token.json).
Corridas siguientes: completamente automático.
"""
import os
import subprocess
import sys
import json
import re
import datetime
import webbrowser
from pathlib import Path
from zoneinfo import ZoneInfo

IN_CI = os.getenv("CI") == "true"

try:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
except ImportError:
    subprocess.run([sys.executable, "-m", "pip", "install",
                    "google-api-python-client", "google-auth-httplib2",
                    "google-auth-oauthlib", "tzdata"], check=True)
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

SCRIPT_DIR  = Path(__file__).parent
HTML_FILE   = SCRIPT_DIR / "index.html"
LOG_FILE    = SCRIPT_DIR / "actualizar.log"
CREDS_FILE  = SCRIPT_DIR / "credentials.json"
TOKEN_FILE  = SCRIPT_DIR / "token.json"

CALENDAR_ID = (
    "c_84c41fa8e326a6cb74924c914b67461489f1c5e1451a130bae3a94d09063c825"
    "@group.calendar.google.com"
)
LOCAL_TZ    = ZoneInfo("America/Argentina/Buenos_Aires")
SCOPES      = ["https://www.googleapis.com/auth/calendar.readonly"]
MESES       = ["ene","feb","mar","abr","may","jun","jul","ago","sep","oct","nov","dic"]
EXCLUIR     = ["no agendar", "ojs", "c1091009 jsk", "visita de monitoreo"]


# ── logging ───────────────────────────────────────────────────────────────────

def log(msg: str) -> None:
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ── filtrado ──────────────────────────────────────────────────────────────────

def _excluded(title: str) -> bool:
    t = title.strip().casefold()
    return any(k in t for k in EXCLUIR) or t.startswith("ssc")


# ── autenticación OAuth2 ──────────────────────────────────────────────────────

def get_credentials() -> Credentials:
    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            log("Renovando token de acceso...")
            creds.refresh(Request())
        else:
            if not CREDS_FILE.exists():
                log(f"ERROR: no se encontró {CREDS_FILE}")
                log("Descargá las credenciales OAuth2 desde Google Cloud Console")
                log("y guardá el archivo como credentials.json en esta carpeta.")
                sys.exit(1)
            log("Abriendo browser para autorización (solo esta vez)...")
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_FILE), SCOPES)
            creds = flow.run_local_server(port=0)

        TOKEN_FILE.write_text(creds.to_json())
        log("token.json guardado.")

    return creds


# ── fetch de eventos ──────────────────────────────────────────────────────────

def fetch_events() -> list:
    creds   = get_credentials()
    service = build("calendar", "v3", credentials=creds)

    now = datetime.datetime.now(tz=datetime.timezone.utc)
    end = now + datetime.timedelta(days=7)

    log("Consultando Google Calendar API...")
    result = (
        service.events()
        .list(
            calendarId=CALENDAR_ID,
            timeMin=now.isoformat(),
            timeMax=end.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )
    raw = result.get("items", [])
    log(f"{len(raw)} evento(s) recibidos del calendario")

    events = []
    for ev in raw:
        s   = ev.get("summary", "").strip()
        start = ev.get("start", {})
        end_  = ev.get("end", {})
        ini = start.get("dateTime") or start.get("date", "")
        fin = end_.get("dateTime")  or end_.get("date", "")
        if s and ini and not _excluded(s):
            events.append({"s": s, "ini": ini, "fin": fin})

    log(f"{len(events)} evento(s) tras filtrado")
    return events


# ── actualización del HTML ────────────────────────────────────────────────────

def replace_eventos(html: str, events: list) -> str:
    m = re.search(r'((?:const|let|var)\s+EVENTOS\s*=\s*)(\[)', html)
    if not m:
        log("ERROR: no se encontró 'EVENTOS = [' en el HTML.")
        sys.exit(1)

    bracket_start = m.start(2)
    depth = 0
    bracket_end = bracket_start
    for i in range(bracket_start, len(html)):
        if html[i] == "[":
            depth += 1
        elif html[i] == "]":
            depth -= 1
            if depth == 0:
                bracket_end = i
                break
    else:
        log("ERROR: array EVENTOS sin cierre de bracket.")
        sys.exit(1)

    new_json = json.dumps(events, ensure_ascii=False, separators=(",", ":"))
    return html[:bracket_start] + new_json + html[bracket_end + 1:]


def replace_timestamp(html: str, now: datetime.datetime) -> str:
    stamp = f"Actualizado: {now.day:02d} {MESES[now.month-1]} · {now.strftime('%H:%M')} hs"
    new_html, n = re.subn(
        r'(Próximos 7 días · ).*?(</div>)',
        rf'\g<1>{stamp}\2',
        html,
        count=1,
        flags=re.DOTALL,
    )
    if n == 0:
        log("AVISO: no se encontró el patrón de timestamp en el HTML.")
    else:
        log(f"Timestamp actualizado: {stamp}")
    return new_html


def update_html(events: list) -> None:
    if not HTML_FILE.exists():
        log(f"ERROR: no se encontró {HTML_FILE}")
        sys.exit(1)
    now  = datetime.datetime.now(tz=LOCAL_TZ)
    html = HTML_FILE.read_text(encoding="utf-8")
    html = replace_eventos(html, events)
    html = replace_timestamp(html, now)
    HTML_FILE.write_text(html, encoding="utf-8")
    log(f"index.html actualizado con {len(events)} evento(s)")


# ── git ───────────────────────────────────────────────────────────────────────

def git_push() -> None:
    ts  = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    msg = f"Actualización automática de eventos - {ts}"
    cwd = str(HTML_FILE.parent)

    for cmd, label in [
        (["git", "add", HTML_FILE.name], "git add"),
        (["git", "commit", "-m", msg],   "git commit"),
        (["git", "push"],                "git push"),
    ]:
        result = subprocess.run(
            cmd, cwd=cwd,
            capture_output=True, text=True, encoding="utf-8",
        )
        if result.returncode == 0:
            log(f"{label}: OK")
        else:
            stderr = result.stderr.strip() or result.stdout.strip()
            if "nothing to commit" in stderr.lower():
                log(f"{label}: sin cambios, nada que commitear")
                break
            log(f"ERROR en {label}: {stderr[:300]}")
            sys.exit(1)


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    log("=" * 50)
    log("Inicio de actualización")

    events = fetch_events()
    update_html(events)
    if IN_CI:
        log("Modo CI: git push y browser delegados al workflow.")
    else:
        git_push()
        webbrowser.open(HTML_FILE.as_uri())
    log("Fin de actualización\n")


if __name__ == "__main__":
    main()
