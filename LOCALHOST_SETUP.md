# Mbarara Auction — Efficient Localhost Setup (SQLite)

This guide configures your development environment to run **entirely offline using SQLite** — no PostgreSQL installation needed.

---

## Quick Start (3 minutes, SQLite only)

### Prerequisites

- **Python 3.12+** ([download](https://www.python.org/downloads/))
- **Git**

> **On Linux:** `sudo apt install python3.12 python3.12-venv git`  
> **On macOS:** `brew install python@3.12 git`  
> **On Windows:** Use [Windows Terminal](https://apps.microsoft.com/store/detail/windows-terminal/9N0DX20HK701)

### Step 1: Clone & Create Virtual Environment

```bash
git clone https://github.com/Goddy36-A/mbarara-auction.git
cd mbarara-auction

# Create isolated Python environment
python3.12 -m venv .venv

# Activate (choose your OS)
# Linux / macOS:
source .venv/bin/activate
# Windows (PowerShell):
.venv\Scripts\Activate.ps1
# Windows (Command Prompt):
.venv\Scripts\activate.bat
```

### Step 2: Install Dependencies

```bash
# Upgrade pip
pip install --upgrade pip setuptools wheel

# Install project dependencies
pip install -r requirements.txt
```

### Step 3: Environment Configuration

```bash
cp .env.example .env
```

Edit `.env` to use SQLite instead of PostgreSQL:

```dotenv
DJANGO_SETTINGS_MODULE=config.settings.development

SECRET_KEY=your-secret-key-here-at-least-50-random-characters
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

# SQLite database (no external server needed, stored as a file)
DATABASE_URL=sqlite:///db.sqlite3

CSRF_TRUSTED_ORIGINS=http://localhost:8000

# Email: console backend prints to terminal
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
EMAIL_HOST_USER=
EMAIL_HOST_PASSWORD=

# Disable Redis (optional tasks run synchronously)
CELERY_TASK_ALWAYS_EAGER=True
```

### Step 4: Create Tables

```bash
python manage.py migrate
```

Output: `Running migrations... OK`

### Step 5: Create Superuser

```bash
python manage.py createsuperuser
```

Follow the prompts:

```
Username: admin
Email address: admin@localhost
Password: (enter a password)
Password (again): (confirm)
Superuser created successfully.
```

### Step 6: Run the Server

```bash
python manage.py runserver
```

Expected output:
```
Starting development server at http://127.0.0.1:8000/
Quit the server with CONTROL-C.
```

Visit **http://localhost:8000** and log in with your superuser credentials.

---

## Performance Optimizations for SQLite Localhost

### 1. **Enable In-Memory Cache**

Add to `.env`:

```dotenv
CACHE_BACKEND=locmem
```

Or add to `config/settings/development.py`:

```python
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'mbarara-cache',
    }
}
```

**Benefit:** Cache queries in RAM; 10–100× faster than disk.

### 2. **Run Async Tasks Synchronously**

Add to `config/settings/development.py`:

```python
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
```

**Benefit:** No Redis or Celery worker needed; tasks execute instantly in your Django process.

### 3. **Disable SQL Logging by Default**

Keep this in `.env`:

```dotenv
SQL_DEBUG_LEVEL=WARNING
```

Enable only when debugging:

```bash
SQL_DEBUG_LEVEL=DEBUG python manage.py runserver
```

### 4. **SQLite WAL Mode (Write-Ahead Logging)**

SQLite by default uses disk I/O that can be slow. Enable WAL mode for better concurrency:

Add to `config/settings/development.py`:

```python
if 'sqlite' in DATABASES['default']['ENGINE']:
    DATABASES['default']['OPTIONS'] = {
        'timeout': 20,
        'isolation_level': None,  # autocommit mode
    }
```

Then initialize WAL:

```bash
python -c "
import sqlite3
conn = sqlite3.connect('db.sqlite3')
conn.execute('PRAGMA journal_mode=WAL')
conn.close()
print('WAL mode enabled on db.sqlite3')
"
```

---

## Running Tests

```bash
# Run all tests
python manage.py test

# Run a specific app's tests
python manage.py test apps.bidding

# Run with keep-db (reuse test database, much faster)
python manage.py test --keepdb --verbosity=2

# Run one test class
python manage.py test apps.bidding.tests.BidPlacementTests
```

---

## Important: SQLite Limitations

SQLite works great for **local development** but has these limitations:

| Feature | SQLite | PostgreSQL |
|---------|--------|-----------|
| **Concurrent writes** | Queues them (slower) | Handles them efficiently |
| **Row-level locking** | Not available | ✅ Used by bidding engine |
| **Transactions** | Supports them | ✅ Full ACID compliance |
| **Development** | ✅ Fast & simple | Full-featured |
| **Production** | ❌ Not recommended | ✅ Designed for it |

**For testing bid concurrency accurately**, you'll want PostgreSQL. But for **browsing, creating auctions, and general UI testing**, SQLite is perfect.

---

## Switching Back to PostgreSQL

When ready to use PostgreSQL:

```bash
# 1. Install PostgreSQL (see step-by-step above)
# 2. Update .env:
DATABASE_URL=postgres://auction_user:auction_pass@localhost:5432/mbarara_auction

# 3. Migrate (creates tables in PostgreSQL)
python manage.py migrate

# 4. Create superuser (optional, if needed)
python manage.py createsuperuser
```

Your `db.sqlite3` file remains untouched.

---

## Troubleshooting

### "database is locked"

SQLite locks when multiple processes access it simultaneously. **Fix:**

```bash
# Only run one Django process at a time
# Close any other runserver instances
# Stop Celery workers if running
```

### Database file `db.sqlite3` keeps growing

SQLite doesn't auto-vacuum. Clean it up:

```bash
python manage.py shell
>>> from django.core.management import call_command
>>> call_command('shell')
>>> import sqlite3
>>> conn = sqlite3.connect('db.sqlite3')
>>> conn.execute('VACUUM')
>>> conn.close()
```

### "ModuleNotFoundError: No module named 'django'"

Activate your venv:

```bash
# Linux / macOS:
source .venv/bin/activate

# Windows:
.venv\Scripts\activate.bat
```

### Port 8000 already in use

```bash
# Use a different port:
python manage.py runserver 8001

# Or kill the process (Linux/macOS):
lsof -ti:8000 | xargs kill -9
```

### Reset database (start fresh)

```bash
rm db.sqlite3
python manage.py migrate
python manage.py createsuperuser
```

---

## Development Workflow Checklist

- ✅ Venv activated: `which python` shows `.venv/bin/python`
- ✅ Dependencies installed: `pip list | grep -i django` shows Django 5.0.6
- ✅ `.env` configured with `DATABASE_URL=sqlite:///db.sqlite3`
- ✅ Migrations run: `python manage.py migrate` (no errors)
- ✅ Superuser created: `python manage.py createsuperuser`
- ✅ Server starts: `python manage.py runserver` → visits http://localhost:8000

---

## When You Need PostgreSQL

Switch to PostgreSQL when:

- **Testing bid concurrency** — SQLite can't test row locking
- **Preparing for production** — PostgreSQL is production-ready
- **Multiple team members** — Need a real database server
- **Large datasets** — SQLite gets slow with 1M+ rows

Until then, **SQLite is all you need** for rapid iteration.

---

## Next Steps

1. **Create test data:** Use Django Admin (http://localhost:8000/admin)
2. **Explore the code:** See `apps/core/views.py` for the dashboard
3. **Run tests:** `python manage.py test --keepdb`
4. **Review README:** See project structure in main README.md

Happy hacking! 🚀
