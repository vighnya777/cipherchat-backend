# Database

## Production (PostgreSQL required)

```bash
# Create role and database
sudo -u postgres createuser -P cipherchat
sudo -u postgres createdb -O cipherchat cipherchat

# .env
DATABASE_URL=postgresql+psycopg2://cipherchat:YOUR_PASSWORD@localhost:5432/cipherchat

# Install deps and migrate
pip install -r requirements.txt
alembic upgrade head

python3 app.py --port 5000
```

## Development / Testing

SQLite is allowed **only** for local development and automated tests:

```bash
export DATABASE_URL=sqlite:///./cipherchat_dev.db
# or
export USE_SQLALCHEMY=1   # uses sqlite:///cipherchat_dev.db

alembic upgrade head
```

## Migration commands

```bash
alembic revision --autogenerate -m "description"
alembic upgrade head
alembic downgrade -1
alembic current
```

## Architecture

```
Routes / Socket.IO
      ↓
Services
      ↓
Storage facade (cipherchat.services.storage.store)
      ↓
StoreBackend interface
      ├── MemoryRepository   (default when no DATABASE_URL)
      └── PostgresRepository (SQLAlchemy → PostgreSQL or SQLite)
```

Ephemeral data (active socket sessions, rate-limit windows) remains in-process.
