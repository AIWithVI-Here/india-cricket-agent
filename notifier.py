#!/usr/bin/env python3
"""India cricket reminder agent. Runs every ~10 min (GitHub Actions) and pushes
phone notifications via ntfy: 1-day / 1-hour reminders, toss, match start,
and schedule changes. Standard library only."""
import json, os, sys, argparse, urllib.request, urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent
IST = timezone(timedelta(hours=5, minutes=30))
TOPIC = os.environ.get("NTFY_TOPIC", "").strip()
SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
API_KEY = os.environ.get("CRICAPI_KEY", "").strip()
API = "https://api.cricapi.com/v1"
DRY = False
VERBOSE = False


def log(*a):
    if VERBOSE or DRY:
        print(*a)


def load(name, default):
    p = ROOT / name
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def save(name, data):
    (ROOT / name).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def parse_dt(s):
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    d = datetime.fromisoformat(s)
    return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d.astimezone(timezone.utc)


def fmt_ist(d):
    return d.astimezone(IST).strftime("%a %d %b, %I:%M %p IST")


def http_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "india-cricket-agent"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def notify(title, body, tags="cricket_game", priority="default"):
    if DRY or not TOPIC:
        print(f"[DRY] {title} | {body}")
        return True
    req = urllib.request.Request(
        f"{SERVER}/{TOPIC}", data=body.encode("utf-8"), method="POST",
        headers={"Title": title, "Tags": tags, "Priority": priority})
    try:
        urllib.request.urlopen(req, timeout=20).read()
        return True
    except Exception as e:
        print("ntfy error:", e, file=sys.stderr)
        return False


# ---------- fixtures ----------
def refresh_api(cfg, state, now, force=False):
    """Pull India fixtures from CricAPI. Returns list of change messages."""
    if not API_KEY:
        return []
    last = state.get("last_refresh")
    gap = timedelta(hours=cfg.get("refresh_hours", 6))
    if not force and last and now - parse_dt(last) < gap:
        return []
    found, offset = {}, 0
    for _ in range(cfg.get("max_pages", 4)):
        try:
            res = http_json(f"{API}/matches?apikey={urllib.parse.quote(API_KEY)}&offset={offset}")
        except Exception as e:
            print("fixture refresh failed:", e, file=sys.stderr)
            return []
        if res.get("status") != "success":
            print("API said:", res.get("status"), res.get("reason", ""), file=sys.stderr)
            return []
        rows = res.get("data") or []
        for m in rows:
            teams = [t.strip() for t in (m.get("teams") or [])]
            if "India" not in teams and "India Women" not in teams:
                continue
            dt = m.get("dateTimeGMT") or m.get("date")
            if not dt:
                continue
            start = parse_dt(dt)
            if start < now - timedelta(days=1):
                continue
            found["api-" + m["id"]] = {
                "id": "api-" + m["id"], "api_id": m["id"],
                "y": "w" if "India Women" in teams else "m",
                "name": m.get("name", "India match"), "venue": m.get("venue", ""),
                "start": start.strftime("%Y-%m-%dT%H:%M:%SZ")}
        if len(rows) < 25:
            break
        offset += 25
    old = {f["id"]: f for f in load("fixtures_api.json", [])}
    changes = []
    if old:  # first run: don't announce everything as "new"
        for fid, f in found.items():
            if fid not in old:
                changes.append(f"New fixture: {f['name']} - {fmt_ist(parse_dt(f['start']))}")
            elif old[fid]["start"] != f["start"]:
                changes.append(f"Time changed: {f['name']} - now {fmt_ist(parse_dt(f['start']))}")
    save("fixtures_api.json", sorted(found.values(), key=lambda f: f["start"]))
    state["last_refresh"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    log(f"refreshed: {len(found)} India fixtures from API")
    return changes


def all_fixtures():
    manual = load("fixtures.json", [])
    api = load("fixtures_api.json", [])
    out = list(api)
    for m in manual:  # drop manual entry if API has the same match
        ms = parse_dt(m["start"])
        if not any(a["y"] == m["y"] and abs(parse_dt(a["start"]) - ms) < timedelta(hours=6) for a in api):
            out.append(m)
    return sorted(out, key=lambda f: f["start"])


# ---------- alerts ----------
def toss_text(f):
    if not (API_KEY and f.get("api_id")):
        return None
    try:
        d = http_json(f"{API}/match_info?apikey={urllib.parse.quote(API_KEY)}&id={f['api_id']}").get("data") or {}
    except Exception as e:
        log("toss lookup failed:", e)
        return None
    w, c = d.get("tossWinner"), d.get("tossChoice")
    return f"{w} won the toss and chose to {c}." if w and c else None


def run_alerts(cfg, state, now):
    sent = state.setdefault("sent", {})
    rem, upd = cfg.get("reminders", {}), cfg.get("updates", {})
    teams = cfg.get("teams", {})
    for f in all_fixtures():
        if not teams.get("men" if f["y"] == "m" else "women", True):
            continue
        if f["id"] in cfg.get("muted_matches", []):
            continue
        start = parse_dt(f["start"])
        tbc = " (start time TBC)" if f.get("tbc") else ""
        info = f"{f['name']}\n{fmt_ist(start)}{tbc}" + (f"\n{f['venue']}" if f.get("venue") else "")

        def once(kind, title, body, prio="default", tag="cricket_game"):
            key = f"{f['id']}:{kind}"
            if key in sent:
                return
            if notify(title, body, tag, prio):
                sent[key] = now.strftime("%Y-%m-%dT%H:%M:%SZ")

        # reminders: fire once inside a grace window (cron can run late)
        for kind, on, lead, grace, title in (
            ("d1", rem.get("day_before", True), timedelta(days=1), timedelta(hours=3), "Tomorrow: India match"),
            ("h1", rem.get("hour_before", True), timedelta(hours=1), timedelta(minutes=45), "India match in 1 hour")):
            if on and start - lead <= now <= start - lead + grace:
                once(kind, title, info)
        if upd.get("toss", True) and start - timedelta(minutes=45) <= now <= start + timedelta(minutes=20):
            key = f"{f['id']}:toss"
            if key not in sent:
                t = toss_text(f)
                if t:
                    once("toss", "Toss update", f"{t}\n{f['name']}", "high", "coin")
                elif not f.get("api_id") and now >= start - timedelta(minutes=30):
                    once("toss", "Toss time", f"Toss is due about now.\n{info}", "default", "coin")
        if upd.get("match_start", True) and start <= now <= start + timedelta(minutes=30):
            once("start", "Play is about to begin", info, "high", "cricket_game")
    # prune old state (>60 days)
    cutoff = now - timedelta(days=60)
    state["sent"] = {k: v for k, v in sent.items() if parse_dt(v) > cutoff}


def main():
    global DRY, VERBOSE
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print instead of sending")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--test", action="store_true", help="send a test notification and exit")
    ap.add_argument("--refresh", action="store_true", help="force a fixture refresh")
    ap.add_argument("--now", help="pretend it is this UTC time (ISO), for testing")
    a = ap.parse_args()
    DRY, VERBOSE = a.dry_run, a.verbose
    if a.test:
        sys.exit(0 if notify("Test from India Cricket Agent", "If you can read this, push works.") else 1)
    now = parse_dt(a.now) if a.now else datetime.now(timezone.utc)
    cfg, state = load("config.json", {}), load("state.json", {"sent": {}})
    changes = refresh_api(cfg, state, now, force=a.refresh)
    if cfg.get("updates", {}).get("schedule_changes", True):
        for c in changes:
            notify("Schedule update", c, "calendar", "high")
    run_alerts(cfg, state, now)
    if not DRY:
        save("state.json", state)


if __name__ == "__main__":
    main()
