import json
from pathlib import Path

import pandas as pd
import streamlit as st

LOG_FILE = Path(__file__).with_name("machine_events.jsonl")
PRESENCE_FILE = Path(__file__).with_name("machine_presence.json")

IDLE_STATES = {"break", "setting", "manpower", "noload", "powercut", "mould"}
SKIP_STATES = {"reconnection", "heartbeat"}
SHOT_STATES = {"production"} | IDLE_STATES
OFFLINE_AFTER_SEC = 45

st.set_page_config(
    page_title="Machine Live Monitor",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@400;500;600;700&display=swap');

    html, body, [data-testid="stAppViewContainer"], .stApp, .stMarkdown, p, span, div, label, table, th, td {
        font-family: 'Montserrat', sans-serif !important;
    }

    html, body, [data-testid="stAppViewContainer"] {
        overflow: hidden !important;
        height: 100vh !important;
    }
    .stApp {
        background: linear-gradient(165deg, #0d1b2a 0%, #1b263b 50%, #1a3a4a 100%);
        color: #edf2f7;
    }
    [data-testid="stHeader"] { background: transparent; }
    .block-container {
        padding: 0.55rem 1.1rem 0.35rem 1.1rem !important;
        max-width: 100% !important;
    }
    #MainMenu, footer, [data-testid="stToolbar"] { visibility: hidden; }

    .live-wrap {
        display: flex;
        align-items: center;
        gap: 8px;
        background: rgba(229,57,53,0.14);
        border: 1px solid rgba(229,57,53,0.4);
        border-radius: 999px;
        padding: 5px 12px;
        height: fit-content;
    }
    .live-dot {
        width: 10px;
        height: 10px;
        border-radius: 50%;
        background: #e53935;
        border: 1.5px solid #ff8a80;
        animation: live-blink 1.15s ease-in-out infinite;
    }
    .live-label {
        font-size: 0.72rem;
        font-weight: 700;
        color: #ff8a80;
        letter-spacing: 0.1em;
    }
    @keyframes live-blink {
        0%, 100% { opacity: 1; transform: scale(1); }
        50% { opacity: 0.3; transform: scale(0.85); }
    }

    .header-row {
        display: grid;
        grid-template-columns: 1.2fr 1.3fr;
        gap: 0.75rem;
        margin-bottom: 0.65rem;
    }
    .header-card {
        border-radius: 16px;
        padding: 0.9rem 1.15rem;
        box-shadow: 0 10px 28px rgba(0,0,0,0.22);
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 1rem;
    }
    .header-left {
        background: linear-gradient(135deg, #1b4965 0%, #2a6f97 100%);
        color: #f8fbff;
    }
    .header-right {
        background: rgba(13, 27, 42, 0.65);
        border: 1px solid rgba(148, 183, 214, 0.28);
        color: #edf2f7;
    }
    .hdr-title {
        font-weight: 700;
        font-size: 1.2rem;
        letter-spacing: -0.01em;
    }
    .hdr-line {
        font-size: 0.8rem;
        font-weight: 500;
        opacity: 0.92;
        margin-top: 0.22rem;
    }
    .hdr-mono {
        font-size: 1.02rem;
        font-weight: 600;
        margin-top: 0.35rem;
        letter-spacing: 0.01em;
    }
    .stat-pair {
        display: flex;
        gap: 0.55rem;
        width: 100%;
    }
    .stat-box {
        flex: 1;
        border-radius: 12px;
        padding: 0.65rem 0.55rem;
        text-align: center;
    }
    .stat-run { background: #d9f2e3; color: #146c43; }
    .stat-idle { background: #fde2e4; color: #a4133c; }
    .stat-disc { background: #fff3cd; color: #856404; }
    .stat-label {
        font-size: 0.62rem;
        font-weight: 600;
        letter-spacing: 0.03em;
        text-transform: uppercase;
    }
    .stat-value {
        font-size: 1.45rem;
        font-weight: 700;
        margin-top: 0.2rem;
    }

    .section-title {
        font-size: 0.78rem;
        font-weight: 700;
        color: #9dbbd4;
        margin: 0.1rem 0 0.4rem 0;
        text-transform: uppercase;
        letter-spacing: 0.08em;
    }

    [data-testid="stDataFrame"] {
        border-radius: 14px !important;
        overflow: hidden !important;
        border: 1px solid rgba(157, 187, 212, 0.3) !important;
        background: rgba(255,255,255,0.97) !important;
        box-shadow: 0 8px 22px rgba(0,0,0,0.16);
    }
    [data-testid="stDataFrame"] * {
        font-family: 'Montserrat', sans-serif !important;
    }
    [data-testid="stVerticalBlock"] > div { gap: 0.35rem !important; }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data(ttl=1)
def load_events(mtime: float):
    empty = pd.DataFrame(columns=["time", "machine_no", "state", "shot"])
    if not LOG_FILE.exists():
        return empty

    rows = []
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    if not rows:
        return empty

    df = pd.DataFrame(rows)
    for col in ["time", "machine_no", "state", "shot"]:
        if col not in df.columns:
            df[col] = None

    df = df[["time", "machine_no", "state", "shot"]].copy()
    df["time"] = pd.to_datetime(df["time"], errors="coerce")
    df["shot"] = pd.to_numeric(df["shot"], errors="coerce").fillna(0).astype(int)
    df["machine_no"] = df["machine_no"].astype(str)
    df["state"] = df["state"].astype(str).str.lower()
    df = df.dropna(subset=["time"]).sort_values("time")
    return df


def load_presence():
    if not PRESENCE_FILE.exists():
        return {}
    try:
        return json.loads(PRESENCE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def current_shift_window(now=None):
    now = pd.Timestamp.now() if now is None else pd.Timestamp(now)
    day = now.normalize()
    eight_am = day + pd.Timedelta(hours=8)
    eight_pm = day + pd.Timedelta(hours=20)

    if eight_am <= now < eight_pm:
        return "Shift I", eight_am, eight_pm
    if now >= eight_pm:
        return "Shift II", eight_pm, eight_am + pd.Timedelta(days=1)
    return "Shift II", eight_pm - pd.Timedelta(days=1), eight_am


def filter_current_shift(df: pd.DataFrame):
    name, start, end = current_shift_window()
    if df.empty:
        return name, start, end, df
    masked = df[(df["time"] >= start) & (df["time"] < end)].copy()
    return name, start, end, masked


def compute_shot_deltas(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["time", "machine_no", "shot", "prev_shot", "cycle_sec"])

    work = df[df["state"].isin(SHOT_STATES)].copy()
    parts = []
    for _, g in work.groupby("machine_no", sort=False):
        g = g.sort_values("time").copy()
        g["prev_shot"] = g["shot"].shift(1)
        g["cycle_sec"] = (g["time"] - g["time"].shift(1)).dt.total_seconds()
        inc = g[(g["prev_shot"].notna()) & (g["shot"] > g["prev_shot"])].copy()
        if not inc.empty:
            parts.append(inc)

    if not parts:
        return pd.DataFrame(columns=["time", "machine_no", "shot", "prev_shot", "cycle_sec"])
    return pd.concat(parts, ignore_index=True)


def shots_produced_this_shift(df_all: pd.DataFrame, machine: str, shift_start: pd.Timestamp) -> int:
    m = df_all[
        (df_all["machine_no"] == machine) & (df_all["state"].isin(SHOT_STATES))
    ].sort_values("time")
    if m.empty:
        return 0

    before = m[m["time"] < shift_start]
    during = m[m["time"] >= shift_start]
    if during.empty:
        return 0

    latest = int(during.iloc[-1]["shot"])
    if before.empty:
        first = int(during.iloc[0]["shot"])
        return max(0, latest - first)

    baseline = int(before.iloc[-1]["shot"])
    if latest >= baseline:
        return latest - baseline
    return latest


def format_elapsed(seconds: float) -> str:
    if seconds is None or seconds < 0:
        return "—"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def spell_start(g: pd.DataFrame, match_state: str):
    t = g.iloc[-1]["time"]
    for i in range(len(g) - 1, -1, -1):
        if g.iloc[i]["state"] == match_state:
            t = g.iloc[i]["time"]
        else:
            break
    return t


def build_machine_table(
    df_shift: pd.DataFrame,
    df_all: pd.DataFrame,
    deltas: pd.DataFrame,
    shift_start: pd.Timestamp,
    presence: dict,
) -> pd.DataFrame:
    empty_cols = [
        "Machine No", "Status", "Shots", "Idle", "From", "Elapsed",
        "Cycle Time (Fastest)", "Quantity/Hour", "Efficiency",
        "Last Updated", "Reconnections",
    ]
    if df_shift.empty and not presence:
        return pd.DataFrame(columns=empty_cols)

    now = pd.Timestamp.now()
    shift_elapsed_sec = max((now - shift_start).total_seconds(), 1.0)
    shift_hours = shift_elapsed_sec / 3600.0

    machines = sorted(set(df_shift["machine_no"].unique().tolist()) | set(presence.keys()))

    fastest_by_machine = {}
    if not deltas.empty:
        valid = deltas[(deltas["cycle_sec"] > 0) & (deltas["cycle_sec"] <= 1800)]
        if not valid.empty:
            fastest_by_machine = valid.groupby("machine_no")["cycle_sec"].min().to_dict()

    rows = []
    for machine in machines:
        g = df_shift[df_shift["machine_no"] == machine].sort_values("time")
        if g.empty and machine not in presence:
            continue

        pres = presence.get(machine, {})
        last_seen = None
        if pres.get("last_seen"):
            last_seen = pd.to_datetime(pres["last_seen"], errors="coerce")

        if not g.empty:
            last = g.iloc[-1]
            state = str(last["state"]).lower()
            last_updated = last["time"]
        else:
            state = str(pres.get("state", "disconnected")).lower()
            last_updated = last_seen if pd.notna(last_seen) else now

        online = True
        if last_seen is not None and pd.notna(last_seen):
            age = (now - last_seen).total_seconds()
            if age > OFFLINE_AFTER_SEC or not pres.get("online", True):
                online = False
        elif state == "disconnected":
            online = False

        is_idle = state in IDLE_STATES
        is_running = state == "production"
        is_reconnected = state == "reconnection"
        is_disconnected = (not online) or state == "disconnected"

        if is_disconnected:
            status = "Disconnected"
        elif is_reconnected:
            status = "Reconnected"
        elif is_running:
            status = "Running"
        elif is_idle:
            status = "Idle"
        elif state == "heartbeat" and not g.empty:
            useful = g[~g["state"].isin(SKIP_STATES | {"disconnected"})]
            if not useful.empty:
                us = str(useful.iloc[-1]["state"]).lower()
                if us == "production":
                    status = "Running"
                elif us in IDLE_STATES:
                    status = "Idle"
                elif us == "reconnection":
                    status = "Reconnected"
                else:
                    status = us.title()
            else:
                status = "Running"
        else:
            status = state.title()

        idle_name = state if (is_idle and not is_disconnected) else "—"
        from_time = "—"
        elapsed = "—"

        if status == "Idle" and not g.empty:
            start_t = spell_start(g, state)
            from_time = start_t.strftime("%H:%M:%S")
            elapsed = format_elapsed((now - start_t).total_seconds())
        elif status == "Disconnected":
            if not g.empty and (g["state"] == "disconnected").any():
                start_t = spell_start(g, "disconnected")
            elif last_seen is not None and pd.notna(last_seen):
                start_t = last_seen
            elif not g.empty:
                start_t = g.iloc[-1]["time"]
            else:
                start_t = now
            from_time = pd.Timestamp(start_t).strftime("%H:%M:%S")
            elapsed = format_elapsed((now - pd.Timestamp(start_t)).total_seconds())

        shots = shots_produced_this_shift(df_all, machine, shift_start)
        fastest = fastest_by_machine.get(machine)
        qty_hour = shots / shift_hours if shift_hours > 0 else None

        efficiency = None
        if fastest and fastest > 0:
            theoretical = shift_elapsed_sec / fastest
            if theoretical > 0:
                efficiency = min(100.0, (shots / theoretical) * 100.0)

        reconnects = int((g["state"] == "reconnection").sum()) if not g.empty else 0

        if last_seen is not None and pd.notna(last_seen):
            if pd.Timestamp(last_updated) < last_seen:
                last_updated = last_seen

        rows.append(
            {
                "Machine No": machine,
                "Status": status,
                "Shots": shots,
                "Idle": idle_name,
                "From": from_time,
                "Elapsed": elapsed,
                "Cycle Time (Fastest)": f"{fastest:.1f}s" if fastest else "—",
                "Quantity/Hour": f"{qty_hour:.1f}" if qty_hour is not None else "—",
                "Efficiency": f"{efficiency:.1f}%" if efficiency is not None else "—",
                "Last Updated": pd.Timestamp(last_updated).strftime("%Y-%m-%d %H:%M:%S"),
                "Reconnections": reconnects,
            }
        )

    return pd.DataFrame(rows)


def style_machine_table(df: pd.DataFrame):
    if df.empty:
        return df

    def status_color(col):
        if col.name != "Status":
            return [""] * len(col)
        out = []
        for v in col:
            if v == "Running":
                out.append(
                    "background-color: #d9f2e3; color: #146c43; font-weight: 700; "
                    "border-radius: 8px; text-align: center;"
                )
            elif v == "Idle":
                out.append(
                    "background-color: #fde2e4; color: #a4133c; font-weight: 700; "
                    "border-radius: 8px; text-align: center;"
                )
            elif v == "Disconnected":
                out.append(
                    "background-color: #fff3cd; color: #856404; font-weight: 700; "
                    "border-radius: 8px; text-align: center;"
                )
            elif v == "Reconnected":
                out.append(
                    "background-color: #cfe2ff; color: #084298; font-weight: 700; "
                    "border-radius: 8px; text-align: center;"
                )
            else:
                out.append("")
        return out

    def zebra(_):
        styles = []
        for i in range(len(df)):
            bg = "#ffffff" if i % 2 == 0 else "#f3f7fb"
            styles.append([f"background-color: {bg};"] * len(df.columns))
        return pd.DataFrame(styles, index=df.index, columns=df.columns)

    return (
        df.style
        .apply(zebra, axis=None)
        .apply(status_color, axis=0)
        .set_properties(**{
            "font-family": "Montserrat, sans-serif",
            "font-size": "0.78rem",
            "font-weight": "500",
            "padding": "9px 10px",
            "border": "none",
            "color": "#1b263b",
        })
        .set_table_styles([
            {
                "selector": "th",
                "props": [
                    ("background-color", "#1b4965"),
                    ("color", "#f8fbff"),
                    ("font-family", "Montserrat, sans-serif"),
                    ("font-weight", "600"),
                    ("font-size", "0.72rem"),
                    ("padding", "10px 10px"),
                    ("border", "none"),
                ],
            },
            {
                "selector": "td",
                "props": [("border-bottom", "1px solid rgba(27,73,101,0.08)")],
            },
        ])
    )


def hourly_shot_trend(deltas: pd.DataFrame) -> pd.DataFrame:
    if deltas.empty:
        return pd.DataFrame(columns=["hour", "shots"])

    d = deltas.copy()
    d["shots_added"] = d["shot"] - d["prev_shot"]
    d["hour"] = d["time"].dt.floor("h")
    out = d.groupby("hour", as_index=False)["shots_added"].sum()
    out = out.rename(columns={"shots_added": "shots"})
    out["hour"] = out["hour"].dt.strftime("%H:00")
    return out


# Same live refresh pattern that worked before — full app rerun every 2s
try:
    from streamlit_autorefresh import st_autorefresh
    st_autorefresh(interval=2000, key="log_refresh")
except Exception:
    st.error("Install live refresh: pip install streamlit-autorefresh")

mtime = LOG_FILE.stat().st_mtime if LOG_FILE.exists() else 0.0
df_all = load_events(mtime)
presence = load_presence()
shift_name, shift_start, shift_end, df = filter_current_shift(df_all)
now = pd.Timestamp.now()

deltas = compute_shot_deltas(df)
table = build_machine_table(df, df_all, deltas, shift_start, presence)

machines_running = int((table["Status"] == "Running").sum()) if not table.empty else 0
machines_idle = int((table["Status"] == "Idle").sum()) if not table.empty else 0
machines_disc = int((table["Status"] == "Disconnected").sum()) if not table.empty else 0

st.markdown(
    f"""
    <div class="header-row">
      <div class="header-card header-left">
        <div>
          <div class="hdr-title">Machine Live Monitor</div>
          <div class="hdr-mono">{now.strftime('%d %b %Y · %H:%M:%S')}</div>
          <div class="hdr-line">{shift_name} · {shift_start.strftime('%d %b %H:%M')} – {shift_end.strftime('%d %b %H:%M')}</div>
        </div>
        <div class="live-wrap"><div class="live-dot"></div><div class="live-label">LIVE</div></div>
      </div>
      <div class="header-card header-right">
        <div class="stat-pair">
          <div class="stat-box stat-run">
            <div class="stat-label">Running</div>
            <div class="stat-value">{machines_running}</div>
          </div>
          <div class="stat-box stat-idle">
            <div class="stat-label">Idle</div>
            <div class="stat-value">{machines_idle}</div>
          </div>
          <div class="stat-box stat-disc">
            <div class="stat-label">Disconnected</div>
            <div class="stat-value">{machines_disc}</div>
          </div>
        </div>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

if table.empty:
    st.warning(f"No events yet for {shift_name}. Waiting for machines...")
    st.stop()

st.markdown('<div class="section-title">Machines</div>', unsafe_allow_html=True)
st.dataframe(
    style_machine_table(table),
    use_container_width=True,
    hide_index=True,
    height=240,
)

st.markdown('<div class="section-title">Shot Trend · 1 Hour Buckets</div>', unsafe_allow_html=True)
hourly = hourly_shot_trend(deltas)
if hourly.empty:
    st.caption("No shot trend yet.")
else:
    chart = hourly.set_index("hour")
    st.line_chart(chart, y="shots", height=190, color="#4cc9f0")
