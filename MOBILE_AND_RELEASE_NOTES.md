# CipherChat Backend – Mobile API & release notes

## Mobile JSON API (Android)

Auth base: `/api/v1/auth`

- register, login, otp/send, otp/verify, dynamic-verify, me, logout
- forgot-password, reset-password, verify-email
- oauth/google|github/start + exchange
- passcode set / verify / disable / status

Chat:

- `GET /api/v1/rooms/<id>/messages`
- `GET /api/v1/rooms`

Register blueprints in `create_app` (already applied in this package):

```python
from cipherchat.api.auth_routes import api_auth_bp
from cipherchat.api.chat_routes import api_chat_bp
app.register_blueprint(api_auth_bp)
app.register_blueprint(api_chat_bp)
```

## Environment

See `docs/ENVIRONMENT.md` and `.env.example` if present.

Required for full features:

- `SECRET_KEY`, `SMTP_*`, optional `GOOGLE_*`, `GITHUB_*`, `DATABASE_URL`

## Run

```bash
python3 -m pip install -r requirements.txt
cp .env.example .env   # if available
python3 -m cipherchat.run   # or project entrypoint (app.py / run.py)
```
