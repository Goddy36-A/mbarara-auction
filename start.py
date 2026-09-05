#!/usr/bin/env python
"""
Mbarara Auction Platform — Local Startup
Run: python start.py
Does everything automatically. No manual config needed.
"""
import os, sys, subprocess, time, webbrowser
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE  = BASE_DIR / ".env"
SETTINGS  = "config.settings.development"
ADMIN     = {"username": "admin", "password": "Admin@12345", "email": "admin@mbarara-auction.ug"}

# Set env var at module level — must be before any Django import
os.environ["DJANGO_SETTINGS_MODULE"] = SETTINGS

GREEN  = "\033[92m"; RED = "\033[91m"; YELLOW = "\033[93m"
RESET  = "\033[0m";  BOLD = "\033[1m"

def ok(msg):   print(f"{GREEN}✅ {msg}{RESET}")
def err(msg):  print(f"{RED}❌ {msg}{RESET}")
def info(msg): print(f"{YELLOW}➜  {msg}{RESET}")
def hdr(msg):  print(f"\n{BOLD}{msg}{RESET}")

def banner():
    print(f"""
{BOLD}╔══════════════════════════════════════════╗
║       Mbarara Auction Platform           ║
║       Local Development Setup           ║
╚══════════════════════════════════════════╝{RESET}
""")

def fix_env():
    """Create or patch .env for local SQLite development."""
    if ENV_FILE.exists():
        lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
        patched, has_settings = [], False
        for line in lines:
            s = line.strip()
            if s.startswith("DATABASE_URL=postgresql") or s.startswith("DATABASE_URL=postgres"):
                patched.append("# " + line + "  # disabled for local SQLite")
                ok("Disabled PostgreSQL DATABASE_URL → using SQLite")
            elif s.startswith("REDIS_URL=") or s.startswith("CELERY_BROKER"):
                patched.append("# " + line + "  # disabled locally — Celery runs in eager mode")
            elif "DJANGO_SETTINGS_MODULE" in s and not s.startswith("#"):
                patched.append("DJANGO_SETTINGS_MODULE=" + SETTINGS)
                has_settings = True
            else:
                patched.append(line)
        if not has_settings:
            patched.append("DJANGO_SETTINGS_MODULE=" + SETTINGS)
        # Add Celery eager mode so tasks work without Redis
        content = "\n".join(patched)
        if "CELERY_TASK_ALWAYS_EAGER" not in content:
            patched.append("CELERY_TASK_ALWAYS_EAGER=True")
        ENV_FILE.write_text("\n".join(patched), encoding="utf-8")
    else:
        ENV_FILE.write_text(
            f"DJANGO_SETTINGS_MODULE={SETTINGS}\n"
            "SECRET_KEY=django-insecure-mbarara-auction-local-dev\n"
            "DEBUG=True\n"
            "ALLOWED_HOSTS=localhost,127.0.0.1\n"
            "CELERY_TASK_ALWAYS_EAGER=True\n",
            encoding="utf-8"
        )
        ok(".env created for local development")

def run(cmd, capture=False):
    env = {**os.environ, "DJANGO_SETTINGS_MODULE": SETTINGS}
    return subprocess.run(
        [sys.executable, "manage.py"] + cmd,
        cwd=BASE_DIR, env=env,
        capture_output=capture, text=capture
    )

def migrate():
    info("Running database migrations...")
    run(["makemigrations"])
    result = run(["migrate"])
    if result.returncode != 0:
        err("Migration failed. Check errors above.")
        sys.exit(1)
    ok("Migrations complete")

def create_admin():
    info("Setting up admin account...")
    env = {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": SETTINGS,
        "DJANGO_SUPERUSER_USERNAME": ADMIN["username"],
        "DJANGO_SUPERUSER_PASSWORD": ADMIN["password"],
        "DJANGO_SUPERUSER_EMAIL":    ADMIN["email"],
    }
    r = subprocess.run(
        [sys.executable, "manage.py", "createsuperuser", "--no-input"],
        cwd=BASE_DIR, env=env, capture_output=True, text=True
    )
    if r.returncode == 0:
        ok(f"Admin created  →  {ADMIN['username']} / {ADMIN['password']}")
    elif "already exists" in (r.stderr + r.stdout):
        ok(f"Admin exists  →  {ADMIN['username']} / {ADMIN['password']}")
    else:
        print(f"{YELLOW}⚠️  {r.stderr.strip() or r.stdout.strip()}{RESET}")

    # Always reset admin password and role
    try:
        import django; django.setup()
        from django.contrib.auth import get_user_model
        User = get_user_model()
        u = User.objects.get(username=ADMIN["username"])
        u.set_password(ADMIN["password"])
        u.role = "ADMIN"
        u.is_staff = True
        u.is_superuser = True
        u.is_verified = True
        u.save()
        ok("Admin password confirmed and role set")
    except Exception as e:
        print(f"{YELLOW}⚠️  Admin reset: {e}{RESET}")

def seed_demo_data():
    """Seed realistic Mbarara auction demo data."""
    hdr("Seeding demo data...")

    import datetime
    from django.contrib.auth import get_user_model
    from django.utils import timezone
    from apps.accounts.models import SellerProfile, BidderProfile
    from apps.auctions.models  import AuctionCategory, Auction

    User  = get_user_model()
    now   = timezone.now()

    # ── Auction Categories ───────────────────────────────────────────
    categories_data = [
        ("Land & Plots",             "land-plots"),
        ("Residential Property",     "residential-property"),
        ("Commercial Property",      "commercial-property"),
        ("Motor Vehicles",           "motor-vehicles"),
        ("Agricultural Equipment",   "agricultural-equipment"),
        ("Livestock",                "livestock"),
        ("Electronics & Appliances", "electronics-appliances"),
        ("Business Assets",          "business-assets"),
    ]
    cats = {}
    for name, slug in categories_data:
        c, _ = AuctionCategory.objects.get_or_create(name=name, defaults={"slug": slug})
        cats[slug] = c
    ok(f"Categories ready ({len(cats)})")

    # ── Demo Users ───────────────────────────────────────────────────
    users_data = [
        # (username, first, last, email, role, phone, password)
        ("officer1",  "Grace",    "Tumuhairwe", "g.tumuhairwe@auction.ug", "OFFICER", "0772100001", "Pass@2025"),
        ("seller1",   "Robert",   "Mugisha",    "r.mugisha@auction.ug",    "SELLER",  "0772100002", "Pass@2025"),
        ("seller2",   "Patricia", "Nakato",     "p.nakato@auction.ug",     "SELLER",  "0772100003", "Pass@2025"),
        ("bidder1",   "David",    "Ssemakula",  "d.ssemakula@auction.ug",  "BIDDER",  "0772100004", "Pass@2025"),
        ("bidder2",   "Florence", "Auma",       "f.auma@auction.ug",       "BIDDER",  "0772100005", "Pass@2025"),
        ("bidder3",   "Joseph",   "Okello",     "j.okello@auction.ug",     "BIDDER",  "0772100006", "Pass@2025"),
    ]
    created_users = {}
    for (uname, fn, ln, email, role, phone, pwd) in users_data:
        u, u_new = User.objects.get_or_create(
            username=uname,
            defaults={"email": email, "first_name": fn, "last_name": ln,
                      "role": role, "phone_number": phone, "is_verified": True}
        )
        if u_new:
            u.set_password(pwd); u.save()
        created_users[uname] = u

        # Create profiles
        if role == "SELLER":
            SellerProfile.objects.get_or_create(user=u, defaults={"phone": phone})
        elif role == "BIDDER":
            BidderProfile.objects.get_or_create(
                user=u,
                defaults={"phone": phone, "location": "Mbarara",
                          "verification_status": "VERIFIED", "account_status": "ACTIVE"}
            )
    ok(f"Demo users ready ({len(users_data)})")

    # ── Demo Auctions ────────────────────────────────────────────────
    auctions_data = [
        {
            "title":          "5-Acre Maize Farm — Rwampara",
            "category":       "land-plots",
            "seller":         "seller1",
            "starting_price": 45_000_000,
            "location":       "Rwampara, Mbarara",
            "start_offset":   -2,   # started 2 hours ago
            "end_offset":     22,   # ends in 22 hours
            "status":         "LIVE",
        },
        {
            "title":          "Toyota Land Cruiser V8 — 2018",
            "category":       "motor-vehicles",
            "seller":         "seller1",
            "starting_price": 120_000_000,
            "location":       "Mbarara Municipality",
            "start_offset":   -1,
            "end_offset":     47,
            "status":         "LIVE",
        },
        {
            "title":          "Commercial Plot — Mbarara City Centre",
            "category":       "commercial-property",
            "seller":         "seller2",
            "starting_price": 200_000_000,
            "location":       "Mbarara City",
            "start_offset":   24,
            "end_offset":     72,
            "status":         "APPROVED",
        },
        {
            "title":          "10 Friesian Dairy Cows",
            "category":       "livestock",
            "seller":         "seller2",
            "starting_price": 15_000_000,
            "location":       "Kiruhura District",
            "start_offset":   -5,
            "end_offset":     3,
            "status":         "LIVE",
        },
        {
            "title":          "Residential House — 4 Bedrooms, Ruti",
            "category":       "residential-property",
            "seller":         "seller1",
            "starting_price": 180_000_000,
            "location":       "Ruti, Mbarara",
            "start_offset":   48,
            "end_offset":     120,
            "status":         "SUBMITTED",
        },
    ]
    auction_count = 0
    for a in auctions_data:
        try:
            seller_user = created_users[a["seller"]]
            seller_profile = SellerProfile.objects.get(user=seller_user)
            _, created = Auction.objects.get_or_create(
                title=a["title"],
                defaults={
                    "seller":         seller_profile,
                    "category":       cats[a["category"]],
                    "location":       a["location"],
                    "starting_price": a["starting_price"],
                    "start_time":     now + datetime.timedelta(hours=a["start_offset"]),
                    "end_time":       now + datetime.timedelta(hours=a["end_offset"]),
                    "status":         a["status"],
                }
            )
            if created: auction_count += 1
        except Exception as e:
            print(f"{YELLOW}⚠️  Auction '{a['title']}': {e}{RESET}")

    ok(f"Demo auctions ready ({auction_count} new)")

    hdr("Demo data ready.")
    print(f"""
  {BOLD}Presentation accounts:{RESET}
  ┌─────────────┬──────────────┬──────────────────────┐
  │ Username    │ Password     │ Role                 │
  ├─────────────┼──────────────┼──────────────────────┤
  │ admin       │ Admin@12345  │ Administrator        │
  │ officer1    │ Pass@2025    │ Auction Officer      │
  │ seller1     │ Pass@2025    │ Seller               │
  │ seller2     │ Pass@2025    │ Seller               │
  │ bidder1     │ Pass@2025    │ Bidder               │
  │ bidder2     │ Pass@2025    │ Bidder               │
  └─────────────┴──────────────┴──────────────────────┘
""")

def start_server():
    url = "http://127.0.0.1:8000"
    print(f"""
{BOLD}🚀 Server starting...{RESET}
   App:   {url}
   Admin: {url}/admin
   Stop   →  Ctrl+C

   Note: Celery runs in eager mode locally (no Redis needed).
         Auction lifecycle tasks execute synchronously.
""")
    time.sleep(1)
    webbrowser.open(url)
    run(["runserver"])

if __name__ == "__main__":
    banner()
    fix_env()
    migrate()
    create_admin()
    seed_demo_data()
    start_server()
