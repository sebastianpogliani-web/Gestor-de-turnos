"""
actualizar.py — obtiene eventos del Google Calendar via `claude --print`
y actualiza el array EVENTOS en monitor-visitas.html sin tocar el resto.
"""
import subprocess
import sys
import json
import re
import datetime
import webbrowser
from pathlib import Path

SCRIPT_DIR  = Path(__file__).parent
HTML_FILE   = SCRIPT_DIR / "monitor-visitas.html"
CLAUDE      = r"C:\Users\Pogliani Sebastian\AppData\Roaming\npm\claude.cmd"
LOG_FILE    = SCRIPT_DIR / "actualizar.log"
CALENDAR_ID = (
    "c_84c41fa8e326a6cb74924c914b67461489f1c5e1451a130bae3a94d09063c825"
    "@group.calendar.google.com"
)


# ── logging ───────────────────────────────────────────────────────────────────

def log(msg: str) -> None:
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ── filtrado ──────────────────────────────────────────────────────────────────

def _excluded(title: str) -> bool:
    t = title.strip().upper()
    return "NO AGENDAR" in t or "OJS" in t or t.startswith("SSC")


# ── fetch via claude --print ──────────────────────────────────────────────────

PROMPT_TEMPLATE = (
    "Usá la herramienta de Google Calendar para listar TODOS los eventos del "
    "calendario con ID '{cal_id}' entre el {start} y el {end} (inclusive). "
    "Devolvé ÚNICAMENTE un array JSON válido, sin explicaciones, sin markdown, "
    "sin texto adicional antes ni después. Cada elemento debe tener: summary, "
    "start (objeto con dateTime o date), end (objeto con dateTime o date), "
    "y opcionalmente location y description."
)


def fetch_raw() -> str:
    today = datetime.date.today()
    end   = today + datetime.timedelta(days=7)
    prompt = PROMPT_TEMPLATE.format(
        cal_id=CALENDAR_ID,
        start=today.isoformat(),
        end=end.isoformat(),
    )
    log("Invocando claude --print (stdin)...")
    try:
        result = subprocess.run(
            [CLAUDE, "--print"],
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=180,
        )
    except FileNotFoundError:
        log(f"ERROR: ejecutable no encontrado en {CLAUDE}")
        sys.exit(1)
    except subprocess.TimeoutExpired:
        log("ERROR: timeout (>3 min). Abortando.")
        sys.exit(1)

    if result.returncode != 0:
        log(f"ERROR: claude salió con código {result.returncode}")
        if result.stderr:
            log(f"stderr: {result.stderr[:400]}")
        sys.exit(1)

    return result.stdout


def extract_json_array(text: str) -> str:
    text = re.sub(r"```(?:json)?\s*", "", text)
    text = re.sub(r"```", "", text).strip()
    m = re.search(r"\[", text)
    if not m:
        return text
    # Conteo de brackets para encontrar el cierre correcto
    depth = 0
    start = m.start()
    for i in range(start, len(text)):
        if text[i] == "[":
            depth += 1
        elif text[i] == "]":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return text


# ── actualización del HTML ────────────────────────────────────────────────────

def replace_eventos(html: str, events: list) -> str:
    """
    Reemplaza el contenido de la primera asignación que coincida con:
        const|let|var EVENTOS = [...];
    usando conteo de brackets para tolerar arrays anidados.
    """
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
        log("ERROR: array EVENTOS no tiene cierre de bracket.")
        sys.exit(1)

    new_json = json.dumps(events, ensure_ascii=False, indent=2)
    return html[:bracket_start] + new_json + html[bracket_end + 1:]


def update_html(events: list) -> Path:
    if not HTML_FILE.exists():
        log(f"ERROR: no se encontró {HTML_FILE}")
        sys.exit(1)

    html = HTML_FILE.read_text(encoding="utf-8")
    new_html = replace_eventos(html, events)
    HTML_FILE.write_text(new_html, encoding="utf-8")
    log(f"EVENTOS actualizado: {len(events)} evento(s) → {HTML_FILE.name}")
    return HTML_FILE


# ── git ───────────────────────────────────────────────────────────────────────

def git_push() -> None:
    ts  = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    msg = f"Actualización automática de eventos - {ts}"
    cwd = str(HTML_FILE.parent)

    cmds = [
        (["git", "add", HTML_FILE.name],   "git add"),
        (["git", "commit", "-m", msg],      "git commit"),
        (["git", "push"],                   "git push"),
    ]

    for cmd, label in cmds:
        result = subprocess.run(
            cmd, cwd=cwd,
            capture_output=True, text=True, encoding="utf-8",
        )
        if result.returncode == 0:
            log(f"{label}: OK")
        else:
            # "nothing to commit" no es un error real
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

    raw = fetch_raw()
    log(f"Respuesta: {len(raw)} caracteres")

    clean = extract_json_array(raw)
    try:
        events = json.loads(clean)
    except json.JSONDecodeError as e:
        log(f"ERROR JSON: {e}")
        log(f"Fragmento: {raw[:500]}")
        sys.exit(1)

    if not isinstance(events, list):
        log("ERROR: la respuesta no es una lista.")
        sys.exit(1)

    log(f"{len(events)} evento(s) recibidos del calendario")
    events = [e for e in events if not _excluded(e.get("summary", ""))]
    log(f"{len(events)} evento(s) tras filtrado")

    update_html(events)
    git_push()
    webbrowser.open(HTML_FILE.as_uri())
    log("Fin de actualización\n")


if __name__ == "__main__":
    main()
