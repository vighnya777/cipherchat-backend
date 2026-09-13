# Folder Structure

```text
CipherChat
├── app.py                          # Entry point – registers routes & Socket.IO
├── cipherchat/
│   ├── __init__.py                 # Application factory (create_app)
│   ├── config.py                   # Environment-driven settings
│   ├── auth/
│   │   ├── routes.py               # Blueprint (migration in progress)
│   │   ├── services.py             # OTP, dynamic password, auth helpers
│   │   └── validators.py           # Email / username validation
│   ├── chat/
│   │   ├── routes.py
│   │   ├── events.py               # Socket.IO handlers (migration target)
│   │   └── services.py
│   ├── admin/
│   │   ├── routes.py
│   │   └── services.py
│   ├── media/
│   │   ├── routes.py
│   │   └── storage.py
│   ├── services/
│   │   ├── security.py             # Hashing, headers, sanitization, tokens
│   │   ├── email.py
│   │   ├── rate_limit.py
│   │   └── storage.py              # In-memory store (swap for Redis/DB later)
│   ├── models/
│   └── utils/
├── templates/                      # Jinja authentication, chat, admin
├── static/
│   ├── css/cipherchat.css          # Design system
│   └── js/cipherchat.js
├── uploads/                        # Runtime media (gitignored)
├── docs/
├── tests/
├── requirements.txt
├── .env.example
└── README.md
```

Routes currently remain in `app.py` for zero-downtime migration. Blueprints are registered and ready to receive handlers as they are extracted.
