# CipherChat

**Secure. Private. Intelligent.**

CipherChat is a production-oriented secure messaging platform built with **Python Flask** and **Socket.IO**. It provides email-verified accounts, multi-step OTP authentication, group and direct messaging, media uploads, invite links, and a full administrator workspace.

## Architecture (current)

```
CipherChat
├── app.py                    # Application entry (routes + Socket.IO handlers)
├── cipherchat/
│   ├── config.py             # Central configuration
│   ├── auth/                 # Auth domain (services, validators, future routes)
│   ├── chat/                 # Chat domain
│   ├── admin/                # Admin domain
│   ├── media/                # Uploads
│   ├── services/
│   │   ├── security.py       # Argon2/bcrypt, headers, sanitization, tokens
│   │   ├── email.py          # SMTP delivery
│   │   ├── rate_limit.py     # OTP / login rate limiting
│   │   └── storage.py        # In-memory store (interface ready for Redis/Postgres)
│   └── models/, utils/
├── templates/                # Jinja2 views
├── static/                   # Design system CSS + JS
├── docs/                     # Architecture, install, deploy
└── tests/
```

The application is being modularized incrementally. All existing features remain fully functional while logic is extracted into the `cipherchat` package.

## Security highlights

- Argon2 password hashing (bcrypt fallback)
- Multi-step login (credentials → OTP → dynamic password)
- Rate limiting on OTP and sensitive endpoints
- CSP, X-Frame-Options, HSTS-ready headers
- Input sanitization and file-type checks
- Session hardening (HttpOnly, SameSite)

## Quick start

```bash
cp .env.example .env
# Edit .env – set SECRET_KEY, MASTER_PASSWORD, SMTP_*, ADMIN_EMAIL

python3 -m pip install -r requirements.txt
python3 app.py --port 5000
```

Open http://localhost:5000

See `docs/INSTALLATION.md`, `docs/ARCHITECTURE.md`, and `docs/ENVIRONMENT.md` for details.

## Design system

Dark-first glassmorphism UI:

| Token        | Value     |
|--------------|-----------|
| Background   | `#09090B` |
| Surface      | `#111827` |
| Primary      | `#6366F1` |
| Secondary    | `#8B5CF6` |
| Accent       | `#06B6D4` |
| Radius       | `18px`    |
| Spacing      | 8px grid  |
| Font         | Manrope / DM Mono |

## Roadmap (incremental)

1. Extract remaining routes into blueprints under `cipherchat/`
2. Replace in-memory store with PostgreSQL + Redis
3. Add comprehensive test suite
4. Optional separate React client behind the same Socket.IO / REST contracts
