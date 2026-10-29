# India Cricket Agent

Runs by itself every ~10 minutes on GitHub Actions (free) and pushes alerts to your phone via ntfy:
1 day before, 1 hour before, toss update, match start, and schedule changes (new fixtures / time changes).
Men's and women's teams. Works with your phone locked and the app closed.

## Setup (about 10 minutes)
1. **Phone:** install the free **ntfy** app. Subscribe to a topic with a long random name,
   e.g. `india-cricket-k8x2q9m4v7` (anyone who knows the name can read it, so keep it private).
2. **GitHub:** create a new **public** repo and upload every file in this folder
   (including the `.github` folder). Public repos get free Actions minutes.
3. Repo **Settings > Secrets and variables > Actions > New secret**:
   - `NTFY_TOPIC` = your topic name
   - `CRICAPI_KEY` = free key from cricapi.com (optional, see below)
4. **Actions** tab > enable workflows > run **cricket-reminders** once manually.
5. Test push from your computer: `NTFY_TOPIC=your-topic python notifier.py --test`

## Choose what you get: `config.json`
- `teams`: `men` / `women` on or off
- `reminders`: `day_before`, `hour_before`
- `updates`: `toss`, `match_start`, `schedule_changes`
- `muted_matches`: list of match ids (e.g. `["m3"]`) to skip

## Automatic fixtures
- Without `CRICAPI_KEY`: uses `fixtures.json` (current NZ series and women's SA tour). It will not learn new series.
- With `CRICAPI_KEY`: refreshes India men's and women's fixtures every 6 hours, picks up new series
  and time changes (and notifies you), and reads the toss result when available. The free tier allows 100 calls a day, which is enough.

## Not verified
I couldn't reach the internet while building this, so the live CricAPI calls are **untested**.
Check once with `CRICAPI_KEY=... python notifier.py --refresh --verbose --dry-run`.
If it returns nothing, the API's field names may differ; edit `refresh_api` in `notifier.py`.
The reminder, toss-time and start logic was tested with simulated times (`--dry-run --now 2026-11-01T06:35:00Z`).

## Good to know
- GitHub can delay scheduled runs by several minutes; reminders have a grace window for this.
- GitHub pauses schedules after 60 days of repo inactivity; re-enable in the Actions tab if that happens.
- Women's South Africa start times are estimates until announced; the API (or editing `fixtures.json`) fixes that.
