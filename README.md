# Matrix Admin Panel Community

A lightweight self-hosted administration portal for **Matrix Synapse** deployments.

The project provides a web interface for common account operations while keeping Synapse as the source of truth.

## Features

- Multiple configured Synapse instances
- Matrix user listing
- Create local Matrix users
- Reset passwords and invalidate existing sessions
- Reversible account deactivation
- Account reactivation with a new password
- `erase=true` account erasure while preserving room history
- Portal accounts scoped to one configured client instance
- Mandatory TOTP MFA for portal administrators and client accounts
- Recovery codes
- Audit log
- Docker container status
- Dark responsive interface

## Important security warning

This application mounts:

```text
/var/run/docker.sock
```

Access to the Docker socket is effectively **host-level/root-equivalent control**.

Do not expose this panel casually to the public Internet. Use TLS, strong authentication, MFA, network restrictions where possible, backups, and normal host hardening. Read [SECURITY.md](SECURITY.md) before production deployment.

This project has **not** undergone an independent security audit.

## Requirements

- Linux host
- Docker Engine
- Docker Compose v2+
- An existing Synapse container
- Synapse and the panel attached to the same Docker network
- `register_new_matrix_user` available inside the Synapse container
- HTTPS reverse proxy for production use

The portal creates a dedicated local Synapse administrator account on first use for each configured instance and stores its access token under `data/tokens/`.

## Quick start

```bash
git clone YOUR_REPOSITORY_URL
cd matrix-admin-panel
chmod +x install.sh
./install.sh
```

The installer creates:

- `.env`
- `config/instances.json`
- `data/`

Then it builds the Docker container.

The service binds by default to:

```text
127.0.0.1:8090
```

Put Caddy, Nginx, Traefik, HAProxy, or another TLS reverse proxy in front of it.

### Caddy example

```caddy
admin.example.com {
    reverse_proxy 127.0.0.1:8090
}
```

### Nginx example

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

Instances are configured in `config/instances.json`.

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

You can add additional Synapse containers to the same JSON file. Every `slug` must be unique.

`postgres_container` is optional and is only used for the status card. User management uses Synapse's Admin API rather than direct PostgreSQL queries.

## Account lifecycle

### Deactivate

Uses Synapse deactivation with:

```text
erase=false
```

The account can later be reactivated with a new password.

### Reactivate

The portal sets:

```text
deactivated=false
```

and requires a new local password.

### Erase account

Uses:

```text
erase=true
```

The action is treated as irreversible from the portal.

The portal deliberately **does not redact old room messages or delete files already shared in rooms**, because those rooms may still be actively used by other members.

## Portal MFA

The initial superadmin must configure TOTP MFA.

Supported authenticator applications include standard TOTP-compatible applications such as Microsoft Authenticator, Google Authenticator, 1Password and Bitwarden.

Recovery codes are shown once when MFA is enabled.

## Backups

At minimum, back up:

```text
data/portal.db
data/tokens/
.env
config/instances.json
```

Protect these files as secrets.

`upgrade.sh` creates a local backup of the portal database and service tokens before rebuilding the container.

## Updating

For a Git checkout:

```bash
git pull
./upgrade.sh
```

Review release notes before upgrading.

## Current limitations

- Designed for Docker-hosted Synapse instances reachable on a shared Docker network.
- Local-password accounts are the primary supported user-management model.
- The panel does not provision complete Matrix/Synapse stacks.
- No LDAP/SSO identity lifecycle management is included.
- UI language is currently French.
- Docker socket access is a deliberate architectural trade-off and should be treated as privileged access.

## License

This repository is intended to be published under **GNU AGPL-3.0-or-later**.

See [LICENSE](LICENSE).

## Disclaimer

This is an independent community project. It is not an official Matrix.org Foundation, Element, or Synapse product.
