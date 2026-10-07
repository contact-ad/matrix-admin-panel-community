# Matrix Admin Panel Community

A lightweight self-hosted administration panel for **Matrix Synapse** deployments.

Matrix Admin Panel provides a simple web interface for common Synapse administration tasks while keeping Synapse as the source of truth.

## Features

- Manage multiple Synapse instances
- List Matrix users
- Create local Matrix users
- Reset user passwords
- Invalidate existing sessions after password reset
- Reversible account deactivation
- Account reactivation with a new password
- Account erasure using `erase=true`
- Preserve existing room history when erasing an account
- Client portal accounts scoped to a specific Matrix instance
- Mandatory TOTP MFA
- Recovery codes
- Audit log
- Docker container status
- Dark responsive interface

## Important security warning

This application mounts:

```text
/var/run/docker.sock
```

Access to the Docker socket is effectively equivalent to **root-level access on the Docker host**.

For production:

- Always use HTTPS
- Enable MFA
- Use strong passwords
- Restrict network access when possible
- Keep Docker and Linux updated
- Protect backups and configuration files

Please read `SECURITY.md` before deploying this application in production.

This project has **not undergone an independent security audit**.

## Requirements

- Linux
- Docker Engine
- Docker Compose v2+
- Existing Matrix Synapse container
- Synapse and the panel connected to the same Docker network
- `register_new_matrix_user` available inside the Synapse container
- HTTPS reverse proxy for production

## Quick start

```bash
git clone https://github.com/contact-ad/matrix-admin-panel-community.git
cd matrix-admin-panel-community
chmod +x install.sh
./install.sh
```

The installer creates:

```text
.env
config/instances.json
data/
```

The panel listens by default on:

```text
127.0.0.1:8090
```

Use a reverse proxy such as Caddy, Nginx, Traefik or HAProxy.

## Caddy example

```caddy
admin.example.com {
    reverse_proxy 127.0.0.1:8090
}
```

## Nginx example

```nginx
server {
    listen 443 ssl;
    server_name admin.example.com;

    location / {
        proxy_pass http://127.0.0.1:8090;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

## Instance configuration

Instances are configured in:

```text
config/instances.json
```

Example:

```json
[
  {
    "slug": "main",
    "name": "My Matrix",
    "chat_domain": "chat.example.com",
    "rtc_domain": "rtc.example.com",
    "synapse_container": "matrix-synapse",
    "postgres_container": "matrix-postgres",
    "primary": true
  }
]
```

Fields:

- `slug`: unique internal identifier
- `name`: display name
- `chat_domain`: Matrix homeserver domain
- `rtc_domain`: optional MatrixRTC domain
- `synapse_container`: Synapse Docker container name
- `postgres_container`: optional PostgreSQL container name
- `primary`: marks the main instance

Multiple Synapse instances can be configured in the same file.

## Synapse service account

For each configured Matrix instance, the panel can create a dedicated local Synapse administrator account.

Its access token is stored in:

```text
data/tokens/
```

These tokens are sensitive and must never be committed to Git.

## Account lifecycle

### Create user

Administrators can create local Matrix users with:

- Matrix username
- Display name
- Password
- Administrator role

### Reset password

The panel can reset a user's password and invalidate existing sessions.

### Deactivate account

Deactivation uses:

```text
erase=false
```

The account becomes unavailable but can later be reactivated.

### Reactivate account

A deactivated account can be reactivated with a new password.

The panel sets:

```text
deactivated=false
```

### Erase account

Account erasure uses:

```text
erase=true
```

This action is treated as irreversible from the administration panel.

The panel deliberately **does not delete or redact old room messages or files already shared in rooms**.

This preserves the history of rooms that may still be actively used by other members.

## Portal authentication

The installer creates the initial portal administrator.

Passwords are stored as secure password hashes.

Plaintext passwords are not stored.

## MFA

TOTP MFA is supported and required for privileged portal accounts.

Compatible applications include:

- Microsoft Authenticator
- Google Authenticator
- Bitwarden
- 1Password
- Other standard TOTP applications

Recovery codes are generated during MFA setup.

## Client portal accounts

Portal accounts can be restricted to a specific Matrix instance.

This is useful for service providers managing multiple independent Matrix environments.

## Audit log

The portal keeps an audit log for administrative operations such as:

- Login
- Failed login
- Matrix user creation
- Password reset
- Account deactivation
- Account reactivation
- Account erasure
- MFA configuration
- Portal account creation

## Docker status

The dashboard can display the status of configured Docker containers such as:

```text
Synapse
PostgreSQL
```

Possible states include:

```text
running
healthy
stopped
absent
```

## Backups

At minimum, back up:

```text
data/portal.db
data/tokens/
.env
config/instances.json
```

Protect these files as secrets.

The provided upgrade script creates a local backup before rebuilding the container:

```bash
./upgrade.sh
```

Backups are stored under:

```text
backups/
```

## Updating

If installed using Git:

```bash
cd matrix-admin-panel-community
git pull
./upgrade.sh
```

Review release notes before updating a production environment.

## Environment configuration

The project includes:

```text
.env.example
```

Example:

```env
APP_SECRET=CHANGE_ME_WITH_A_LONG_RANDOM_VALUE
BOOTSTRAP_ADMIN_USER=admin
BOOTSTRAP_ADMIN_HASH=CHANGE_ME_WITH_INSTALL_SCRIPT

PANEL_BRAND=Matrix Admin Panel
PANEL_TITLE=Matrix Admin
MFA_ISSUER=Matrix Admin Panel
SESSION_COOKIE_SECURE=true
PANEL_PORT=8090

MATRIX_NETWORK=matrix_default
INSTANCE_CONFIG=/config/instances.json

SERVICE_ADMIN_DISPLAY_NAME=Matrix Admin Service
```

Never commit your real `.env` file.

## Files that must remain private

Never publish:

```text
.env
data/
backups/
config/instances.json
*.db
*.sqlite
*.sqlite3
```

The repository includes a `.gitignore` file to help prevent accidental publication.

## Project structure

```text
matrix-admin-panel-community/
├── app.py
├── matrix_ops.py
├── cli.py
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── install.sh
├── upgrade.sh
├── VERSION
├── README.md
├── SECURITY.md
├── CONTRIBUTING.md
├── CHANGELOG.md
├── PUBLICATION_CHECKLIST.md
├── LICENSE
├── .env.example
├── .gitignore
├── config/
│   └── instances.example.json
├── static/
│   ├── app.js
│   └── style.css
└── templates/
    ├── audit.html
    ├── base.html
    ├── client.html
    ├── dashboard.html
    ├── login.html
    ├── mfa_setup.html
    ├── mfa_verify.html
    └── portal_users.html
```

## Current limitations

- Designed primarily for Docker-hosted Synapse installations
- Local Matrix password accounts are the primary supported account type
- LDAP lifecycle management is not included
- SSO lifecycle management is not included
- The panel does not install a complete Matrix server
- The panel does not configure MatrixRTC or LiveKit
- The current interface language is primarily French
- Docker socket access gives the portal privileged access to the host

## Security architecture

The current version uses Docker access to execute:

```text
register_new_matrix_user
```

inside the Synapse container and to inspect container status.

This makes deployment easy but gives the administration panel highly privileged access.

Future versions may replace direct Docker socket access with a restricted helper service.

## Contributing

Contributions are welcome.

Please read:

```text
CONTRIBUTING.md
```

before submitting a pull request.

## Security issues

Please read:

```text
SECURITY.md
```

Do not publicly disclose exploitable vulnerabilities before the maintainer has had time to investigate them.

## License

Matrix Admin Panel Community is released under:

```text
GNU AGPL-3.0-or-later
```

See `LICENSE` for details.

## Disclaimer

Matrix Admin Panel Community is an independent community project.

It is **not** an official product of:

- Matrix.org Foundation
- Element
- Synapse

Matrix and related trademarks belong to their respective owners.

## Version

Current Community release:

```text
v1.0.0
```
