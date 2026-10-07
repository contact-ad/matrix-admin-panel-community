# Contributing

Contributions are welcome.

Please:

1. open an issue for significant behavior changes;
2. avoid committing secrets, private domains, IP addresses or customer data;
3. keep security-sensitive changes small and reviewable;
4. test account creation, password reset, deactivate/reactivate, MFA and audit logging;
5. run the Python syntax check before submitting a pull request:

```bash
python3 -m py_compile app.py matrix_ops.py cli.py
```

For security issues, follow `SECURITY.md`.
