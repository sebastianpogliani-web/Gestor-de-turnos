import sys
import json
import datetime
import webbrowser
from pathlib import Path
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("America/Argentina/Buenos_Aires")
SCRIPT_DIR = Path(__file__).parent

DIAS_ES = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
MESES_ES = [
    "", "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]

# Capacidad por turno (9hs=mañana, 12hs=mediodia, 15hs=tarde) indexada por weekday
DISP = {
    0: {"mañana": 9, "mediodia": 9, "tarde": 4},
    1: {"mañana": 8, "mediodia": 9, "tarde": 5},
    2: {"mañana": 5, "mediodia": 6, "tarde": 3},
    3: {"mañana": 8, "mediodia": 9, "tarde": 5},
    4: {"mañana": 8, "mediodia": 9, "tarde": 6},
    5: {"mañana": 3, "mediodia": 3, "tarde": 3},
    6: {"mañana": 0, "mediodia": 0, "tarde": 0},
}


# ── input ────────────────────────────────────────────────────────────────────

def read_json_input() -> list:
    print("=" * 60)
    print("  Monitor de Visitas Médicas")
    print("=" * 60)
    print()
    print("Copiá y pegá los datos del calendario aquí:")
    print("(cuando termines, presioná Enter, luego Ctrl+Z y Enter)")
    print()

    lines = []
    try:
        for line in sys.stdin:
            lines.append(line)
    except EOFError:
        pass

    raw = "".join(lines).strip()
    if not raw:
        print("\n⚠  No se ingresaron datos. Saliendo.")
        sys.exit(0)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"\n❌  JSON inválido: {e}")
        sys.exit(1)

    if not isinstance(data, list):
        print("\n❌  El JSON debe ser una lista de eventos.")
        sys.exit(1)

    return data


# ── filtering & parsing ───────────────────────────────────────────────────────

def _excluded(title: str) -> bool:
    t = title.upper()
    return "NO AGENDAR" in t or "OJS" in t or t.startswith("SSC")


def get_shift(hour: int) -> str:
    if hour < 12:
        return "mañana"
    elif hour < 14:
        return "mediodia"
    else:
        return "tarde"


def parse_events(events: list) -> dict:
    days: dict = {}
    skipped = 0

    for event in events:
        title = event.get("summary", "")
        if _excluded(title):
            skipped += 1
            continue

        start = event.get("start", {})
        end = event.get("end", {})

        if "dateTime" in start:
            dt = datetime.datetime.fromisoformat(start["dateTime"]).astimezone(LOCAL_TZ)
            dt_end = datetime.datetime.fromisoformat(end["dateTime"]).astimezone(LOCAL_TZ)
            shift = get_shift(dt.hour)
            date_key = dt.date()
            time_str = dt.strftime("%H:%M")
            duration_min = int((dt_end - dt).total_seconds() / 60)
            if duration_min < 60:
                duration_str = f"{duration_min} min"
            else:
                duration_str = f"{duration_min // 60}h {duration_min % 60:02d}min"
        elif "date" in start:
            date_key = datetime.date.fromisoformat(start["date"])
            shift = "mañana"
            time_str = "Todo el día"
            duration_str = ""
        else:
            skipped += 1
            continue

        if date_key not in days:
            days[date_key] = {"mañana": [], "mediodia": [], "tarde": []}

        days[date_key][shift].append({
            "title": title or "Sin título",
            "time": time_str,
            "duration": duration_str,
            "location": event.get("location", ""),
            "description": (event.get("description") or "").strip(),
        })

    if skipped:
        print(f"    {skipped} evento(s) excluido(s) por filtro.")

    return dict(sorted(days.items()))


# ── html generation ───────────────────────────────────────────────────────────

def format_date_header(d: datetime.date) -> str:
    return f"{DIAS_ES[d.weekday()]} {d.day} de {MESES_ES[d.month]}"


def event_card(ev: dict) -> str:
    location_html = f'<div class="ev-loc">📍 {ev["location"]}</div>' if ev["location"] else ""
    desc_html = f'<div class="ev-desc">{ev["description"]}</div>' if ev["description"] else ""
    duration_html = f'<span class="ev-dur">{ev["duration"]}</span>' if ev["duration"] else ""
    return f"""
        <div class="event-card">
          <div class="ev-header">
            <span class="ev-time">{ev["time"]}</span>
            {duration_html}
          </div>
          <div class="ev-title">{ev["title"]}</div>
          {location_html}
          {desc_html}
        </div>"""


def shift_column(label: str, icon: str, color: str, events: list, shift_key: str,
                 capacity: int) -> str:
    count = len(events)
    cards = "".join(event_card(e) for e in events) if events else '<div class="empty">Sin visitas</div>'

    if capacity > 0:
        pct = min(count / capacity, 1.0)
        if pct >= 1.0:
            bar_color = "#ef4444"
        elif pct >= 0.75:
            bar_color = "#f59e0b"
        else:
            bar_color = "#22c55e"
        bar_html = f"""
        <div class="cap-bar-wrap" title="{count} de {capacity} turnos">
          <div class="cap-bar" style="width:{pct*100:.0f}%;background:{bar_color}"></div>
        </div>
        <div class="cap-label">{count} / {capacity}</div>"""
    else:
        bar_html = ""

    return f"""
      <div class="shift-col shift-{shift_key}">
        <div class="shift-header" style="background:{color}">
          <span class="shift-icon">{icon}</span>
          <span class="shift-label">{label}</span>
          <span class="badge">{count}</span>
        </div>
        {bar_html}
        <div class="shift-body">
          {cards}
        </div>
      </div>"""


def generate_html(days: dict) -> Path:
    today = datetime.date.today()
    total_events = sum(len(shifts[s]) for shifts in days.values() for s in shifts)

    if days:
        dates = list(days.keys())
        d0, d1 = dates[0], dates[-1]
        date_range = (
            f"{d0.day} de {MESES_ES[d0.month]}"
            if d0.month == d1.month
            else f"{d0.day} de {MESES_ES[d0.month]} — {d1.day} de {MESES_ES[d1.month]}"
        )
    else:
        date_range = "sin datos"

    days_html = ""
    for date_key, shifts in days.items():
        total_day = sum(len(shifts[s]) for s in shifts)
        is_today = date_key == today
        disp = DISP.get(date_key.weekday(), {"mañana": 0, "mediodia": 0, "tarde": 0})
        today_badge = '<span class="today-badge">HOY</span>' if is_today else ""

        col_m = shift_column("Mañana",   "🌅", "#d97706", shifts["mañana"],  "manana",  disp["mañana"])
        col_d = shift_column("Mediodía", "☀️", "#059669", shifts["mediodia"], "mediodia", disp["mediodia"])
        col_t = shift_column("Tarde",    "🌆", "#4f46e5", shifts["tarde"],   "tarde",   disp["tarde"])

        days_html += f"""
      <div class="day-block {'today' if is_today else ''}">
        <div class="day-header">
          <div class="day-title">
            {today_badge}
            <span class="day-name">{format_date_header(date_key)}</span>
          </div>
          <span class="day-total">{total_day} visita{"s" if total_day != 1 else ""}</span>
        </div>
        <div class="shifts-grid">
          {col_m}
          {col_d}
          {col_t}
        </div>
      </div>"""

    if not days:
        days_html = '<div class="no-events">No hay visitas en los datos ingresados.</div>'

    generated_at = datetime.datetime.now(LOCAL_TZ).strftime("%d/%m/%Y %H:%M")

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Monitor de Visitas Médicas</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: #0f172a;
      color: #e2e8f0;
      min-height: 100vh;
      padding: 24px 16px;
    }}

    .page-header {{
      max-width: 1200px;
      margin: 0 auto 32px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 12px;
    }}
    .logo-area {{ display: flex; align-items: center; gap: 14px; }}
    .logo-icon {{
      width: 52px; height: 52px; border-radius: 14px;
      background: linear-gradient(135deg, #6366f1, #8b5cf6);
      display: flex; align-items: center; justify-content: center;
      font-size: 26px;
    }}
    h1 {{ font-size: 1.55rem; font-weight: 700; color: #f8fafc; }}
    .subtitle {{ font-size: 0.85rem; color: #94a3b8; margin-top: 2px; }}
    .stats-bar {{ display: flex; gap: 12px; flex-wrap: wrap; }}
    .stat-pill {{
      background: #1e293b; border: 1px solid #334155;
      border-radius: 999px; padding: 6px 16px;
      font-size: 0.82rem; color: #94a3b8;
    }}
    .stat-pill strong {{ color: #f8fafc; }}

    .container {{ max-width: 1200px; margin: 0 auto; }}

    .day-block {{
      background: #1e293b;
      border: 1px solid #334155;
      border-radius: 16px;
      margin-bottom: 20px;
      overflow: hidden;
    }}
    .day-block.today {{
      border-color: #6366f1;
      box-shadow: 0 0 0 1px #6366f1, 0 8px 32px rgba(99,102,241,.18);
    }}
    .day-header {{
      display: flex; align-items: center; justify-content: space-between;
      padding: 14px 20px;
      background: #0f172a;
      border-bottom: 1px solid #334155;
    }}
    .day-title {{ display: flex; align-items: center; gap: 10px; }}
    .today-badge {{
      background: #6366f1; color: #fff;
      font-size: 0.7rem; font-weight: 700;
      padding: 2px 8px; border-radius: 999px; letter-spacing: .05em;
    }}
    .day-name {{ font-size: 1rem; font-weight: 600; color: #f1f5f9; text-transform: capitalize; }}
    .day-total {{ font-size: 0.8rem; color: #64748b; }}

    .shifts-grid {{
      display: grid;
      grid-template-columns: repeat(3, 1fr);
    }}
    .shift-col {{ border-right: 1px solid #334155; }}
    .shift-col:last-child {{ border-right: none; }}

    .shift-header {{
      display: flex; align-items: center; gap: 8px;
      padding: 10px 16px;
      font-size: 0.82rem; font-weight: 600; color: #fff;
    }}
    .shift-icon {{ font-size: 1rem; }}
    .shift-label {{ flex: 1; }}
    .badge {{
      background: rgba(255,255,255,.22);
      border-radius: 999px; padding: 1px 8px;
      font-size: 0.75rem; font-weight: 700;
    }}

    .cap-bar-wrap {{
      height: 4px; background: #0f172a; margin: 0 16px;
    }}
    .cap-bar {{ height: 4px; border-radius: 2px; transition: width .4s; }}
    .cap-label {{
      font-size: 0.68rem; color: #64748b;
      text-align: right; padding: 2px 16px 6px;
    }}

    .shift-body {{ padding: 10px 12px 12px; min-height: 72px; }}

    .event-card {{
      background: #0f172a;
      border: 1px solid #1e293b;
      border-radius: 10px;
      padding: 9px 12px;
      margin-bottom: 7px;
    }}
    .event-card:last-child {{ margin-bottom: 0; }}
    .ev-header {{ display: flex; align-items: center; gap: 8px; margin-bottom: 3px; }}
    .ev-time {{ font-size: 0.76rem; font-weight: 700; color: #94a3b8; }}
    .ev-dur {{
      font-size: 0.68rem; color: #64748b;
      background: #1e293b; border-radius: 4px; padding: 1px 6px;
    }}
    .ev-title {{ font-size: 0.86rem; font-weight: 600; color: #e2e8f0; }}
    .ev-loc {{ font-size: 0.73rem; color: #64748b; margin-top: 4px; }}
    .ev-desc {{
      font-size: 0.73rem; color: #94a3b8;
      margin-top: 5px; line-height: 1.4;
      border-top: 1px solid #1e293b; padding-top: 5px;
      white-space: pre-wrap;
    }}

    .empty {{ text-align: center; color: #475569; font-size: 0.78rem; padding: 22px 0; }}
    .no-events {{
      text-align: center; color: #64748b;
      font-size: 1rem; padding: 60px;
      background: #1e293b; border-radius: 16px;
    }}
    .page-footer {{
      max-width: 1200px; margin: 24px auto 0;
      text-align: right; font-size: 0.73rem; color: #475569;
    }}

    @media (max-width: 700px) {{
      .shifts-grid {{ grid-template-columns: 1fr; }}
      .shift-col {{ border-right: none; border-bottom: 1px solid #334155; }}
      .shift-col:last-child {{ border-bottom: none; }}
    }}
  </style>
</head>
<body>
  <header class="page-header">
    <div class="logo-area">
      <div class="logo-icon">🏥</div>
      <div>
        <h1>Monitor de Visitas Médicas</h1>
        <div class="subtitle">{date_range}</div>
      </div>
    </div>
    <div class="stats-bar">
      <div class="stat-pill"><strong>{len(days)}</strong> días</div>
      <div class="stat-pill"><strong>{total_events}</strong> visitas totales</div>
    </div>
  </header>

  <div class="container">
    {days_html}
  </div>

  <footer class="page-footer">Generado el {generated_at} · i-Trials</footer>
</body>
</html>"""

    output = SCRIPT_DIR / "monitor.html"
    output.write_text(html, encoding="utf-8")
    return output


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    events = read_json_input()
    print(f"\n    {len(events)} evento(s) recibido(s).")

    days = parse_events(events)
    print(f"    {sum(len(s[k]) for s in days.values() for k in s)} visita(s) procesada(s) en {len(days)} día(s).")

    print("\n🎨  Generando dashboard HTML...")
    html_path = generate_html(days)
    print(f"    Guardado en: {html_path}")

    print("🌐  Abriendo en el navegador...")
    webbrowser.open(html_path.as_uri())
    print("✅  Listo.")


if __name__ == "__main__":
    main()
