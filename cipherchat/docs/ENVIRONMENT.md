# Environment Variables

| Variable | Required | Description |
| --- | --- | --- |
| `SECRET_KEY` | Yes | High-entropy Flask signing secret |
| `ADMIN_EMAIL` | Yes | Bootstrap administrator email |
| `MASTER_PASSWORD` | Yes | Bootstrap credential; replace with a password hash during persistence migration |
| `SMTP_EMAIL` | Yes | SMTP sender account |
| `SMTP_PASSWORD` | Yes | SMTP application password |
| `BASE_URL` | Yes | Public canonical application URL |
| `SOCKET_CORS_ORIGINS` | Production | Comma-separated allowed browser origins |
| `SESSION_COOKIE_SECURE` | Production | Set to `true` behind HTTPS |
| `FLASK_DEBUG` | No | Set to `1` only for local debugging |

Never commit `.env` or reuse secrets across environments.
