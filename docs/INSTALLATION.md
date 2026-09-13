# Installation Guide

## Prerequisites

- Python 3.11
- pip
- An SMTP account for OTP, verification, and reset messages

## Local Setup

```sh
cp .env.example .env
python3 -m pip install -r requirements.txt
python3 app.py --port 5000
```

Open `http://localhost:5000`. Configure `SECRET_KEY`, `MASTER_PASSWORD`, and SMTP credentials before use. Local Socket.IO and `*.e2b.app` preview hosts are permitted by the development origin policy.

## Verification

```sh
python3 -m py_compile app.py
```
