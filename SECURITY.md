# Security

## Docker socket

Matrix Admin Panel uses the Docker socket to:

- inspect Synapse/PostgreSQL container state;
- execute `register_new_matrix_user` inside Synapse.

Mounting `/var/run/docker.sock` gives the application extremely powerful access to the Docker host and should be considered root-equivalent.

Recommended controls:

- expose the portal only through HTTPS;
- require MFA;
- restrict source networks/VPN where practical;
- keep the host and Docker Engine patched;
- do not run unrelated untrusted containers on the same host;
- back up `data/portal.db` and `data/tokens/`;
- protect `.env` and the `config/` directory;
- monitor portal audit logs and reverse-proxy logs.

## Stored secrets

The following must remain private:

- `.env`
- `data/portal.db`
- `data/tokens/`
- backup copies of the above

Never commit them to Git.

## Reverse proxy

The application trusts one reverse-proxy hop through Werkzeug `ProxyFix`.

Do not expose the Gunicorn port directly to untrusted networks while also accepting spoofable forwarded headers.

## Session cookies

Production configuration uses secure cookies. Keep:

```text
SESSION_COOKIE_SECURE=true
```

when using HTTPS.

## Security reports

Do not publish exploitable security issues in a public issue before the maintainer has had a reasonable opportunity to review them.

Before publishing the repository, replace this paragraph with your preferred private security contact or enable GitHub Private Vulnerability Reporting.
