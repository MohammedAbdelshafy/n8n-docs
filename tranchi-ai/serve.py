"""
TRANCHI AI — always-on entrypoint for free hosts (Railway / Render / Fly.io).

Runs TWO things in one process so a single free service does everything:
  1. The FastAPI webhook server (inbound SMS + opt-in funnel) on $PORT.
  2. A background scheduler thread that fires the full daily pipeline
     (`python main.py all`) once per day at RUN_HOUR_UTC.

The daily run is launched as a subprocess so a scraper crash can never take
down the web server. Env vars:
  PORT          — web port (host sets this; default 8000)
  RUN_HOUR_UTC  — hour (0-23 UTC) to run the daily pipeline (default 13 = 8am CT)
  DISABLE_CRON  — set to "1" to run web-only (no daily pipeline)
"""

import os
import sys
import time
import subprocess
import threading
from datetime import datetime, timezone, timedelta

RUN_HOUR_UTC = int(os.getenv("RUN_HOUR_UTC", "13"))
HERE = os.path.dirname(os.path.abspath(__file__))


def _seconds_until_next_run() -> float:
    now = datetime.now(timezone.utc)
    nxt = now.replace(hour=RUN_HOUR_UTC, minute=0, second=0, microsecond=0)
    if nxt <= now:
        nxt += timedelta(days=1)
    return (nxt - now).total_seconds()


def _run_daily_pipeline():
    print(f"[scheduler] firing daily pipeline at {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}",
          flush=True)
    try:
        subprocess.run([sys.executable, "main.py", "all"], cwd=HERE, check=False)
    except Exception as e:  # never let the scheduler thread die
        print(f"[scheduler] pipeline error: {e}", flush=True)


def _scheduler_loop():
    while True:
        wait = _seconds_until_next_run()
        print(f"[scheduler] next daily run in {wait/3600:.1f}h "
              f"(RUN_HOUR_UTC={RUN_HOUR_UTC})", flush=True)
        time.sleep(wait)
        _run_daily_pipeline()
        time.sleep(60)  # avoid double-firing within the same minute


def main():
    if os.getenv("DISABLE_CRON") != "1":
        threading.Thread(target=_scheduler_loop, daemon=True).start()
    else:
        print("[scheduler] DISABLE_CRON=1 — web-only mode", flush=True)

    # Start Discord bot in background thread if token is set
    if os.getenv("DISCORD_BOT_TOKEN"):
        from src.notifications.discord_bot import run_bot
        threading.Thread(target=run_bot, daemon=True).start()
        print("[discord] bot thread started", flush=True)

    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    print(f"[web] serving webhook + funnel on 0.0.0.0:{port}", flush=True)
    uvicorn.run("src.webhook.server:app", host="0.0.0.0", port=port, reload=False)


if __name__ == "__main__":
    main()
