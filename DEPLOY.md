# Deployment & resume notes

## Where things stand

- Core logic is complete and reusable: `lastfm.py`, `sentiment.py`, `stats.py`, `users.py`.
- GitHub Actions scheduler is now the primary deploy path (no always-on host needed).
- Weekly post target is Friday 10:00 Europe/Stockholm via `.github/workflows/weekly-lastfm.yml`.
- Action posts through Discord webhook (`DISCORD_WEBHOOK_URL`) instead of bot token login.
- User registry is loaded from a GitHub secret (`USERS_JSON`) into `data/users.json` at runtime.

## GitHub Actions deployment checklist

1. **Push repo to GitHub** (private repo is fine).
2. **Create a Discord webhook** in your target channel:
   - Discord → Server Settings → Integrations → Webhooks → New Webhook.
   - Copy webhook URL.
3. **Add GitHub repository secrets** (Settings → Secrets and variables → Actions):
   - `LASTFM_API_KEY`
   - `DISCORD_WEBHOOK_URL`
   - `USERS_JSON` (the full JSON content of `data/users.json`)
4. **Commit and push** the workflow and script:
   - `.github/workflows/weekly-lastfm.yml`
   - `scripts/weekly_post.py`
5. **Manual test in Actions UI**:
   - Go to Actions → "Weekly Last.fm Awards" → Run workflow.
   - Keep defaults (`force_run=true`, `dry_run=false`) to post immediately.
   - Optional safe test: set `dry_run=true` to print output in logs only.
6. **Verify schedule**:
   - Workflow has two Friday cron triggers (`08:00` and `09:00` UTC) for DST.
   - Script time-gates to exactly Friday 10:00 Europe/Stockholm, so only one run posts.

## Notes on users and secrets

- `USERS_JSON` should contain a JSON object of Discord ID to Last.fm username.
- Example secret value:
  ```json
  {
    "123456789012345678": "alice_lastfm",
    "987654321098765432": "bob_lastfm"
  }
  ```
- Keep `data/users.json` out of git (`data/` is already ignored in `.gitignore`).

## Useful local commands

```
# dev setup
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# compute awards locally against current users.json
python scripts/dry_run.py
python scripts/dry_run.py --verbose   # per-user tag/score breakdown

# test Actions posting script locally (requires env vars)
FORCE_RUN=true DRY_RUN=true python scripts/weekly_post.py
```

## Known tradeoffs / future tweaks

- **No slash-command registration in Actions mode**: with webhook-only posting, `/register` and related commands are not active unless `bot.py` is hosted.
- **Trailing 7 days**, not calendar week: `lastfm.py::week_window` returns `(now - 7d, now)`.
- **Cache is ephemeral in Actions**: `data/lastfm_tags.json` is rebuilt each run unless you add Actions cache/artifact steps.
- **Users with few scrobbles can win mood awards** on small evidence; add a minimum threshold in `stats.py::_dim_leader` if needed.
- **Tag map coverage**: extend `sentiment.py::TAG_MAP` if specific genres dominate your group.

## Files

- `scripts/weekly_post.py` — Actions entrypoint; computes awards and posts webhook.
- `.github/workflows/weekly-lastfm.yml` — weekly cron + manual run trigger.
- `lastfm.py` — Last.fm API client.
- `sentiment.py` — tag-to-mood scoring + cache.
- `stats.py` — awards computation + message formatting.
- `users.py` — reads registry from `data/users.json`.
- `scripts/dry_run.py` — local awards preview.
