# Publication checklist

Before switching the repository to Public:

- [ ] Search the repository history for old secrets, customer names, private domains and public/private IPs.
- [ ] Prefer a fresh public repository instead of changing an internal production repository from Private to Public.
- [ ] Confirm `.env`, `data/`, `config/instances.json` and backups are not committed.
- [ ] Replace the security contact guidance in `SECURITY.md`.
- [ ] Confirm the chosen license is AGPL-3.0-or-later, or replace it with the license you actually want.
- [ ] Enable GitHub Private Vulnerability Reporting if desired.
- [ ] Add repository topics such as `matrix`, `synapse`, `self-hosted`, `flask`, `docker`.
- [ ] Create a `v1.0.0` release.
