# .pi/ — workspace-persisted Pi agent data

This directory holds the Pi coding agent's persistent data so it survives
devcontainer rebuilds (the home directory does not). It is managed by
`devscripts/setup_pi_persistence.sh`, which the `.devcontainer/post-install.sh`
hook re-runs automatically on every container build.

- `agent/sessions/` — conversation transcripts
- `agent/extensions/` — Pi extensions (e.g. web-tools.ts: web_search + web_fetch)
- `agent/settings.json`, `agent/auth.json` — configuration + API credentials
  (auth.json holds SECRETS: this folder is git-ignored — never commit it)
- `agent/local-backup-*/` may exist under ~/.pi after a migration, not here.

The whole `.pi/` folder is git-ignored except this README. If Pi's launcher
starts acting oddly, re-run the setup script or inspect it with
`bash devscripts/setup_pi_persistence.sh --check`.
