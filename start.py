#!/usr/bin/env python
"""
One-click startup script for Mbarara Auction System.
Automatically sets up venv, installs dependencies, runs migrations, and starts the server.

Usage:
    python start.py          # Full setup + run server
    python start.py --reset  # Wipe database and start fresh
    python start.py --help   # Show options
"""

import os
import sys
import subprocess
import platform
import shutil
import secrets
from pathlib import Path

# Color output for better UX
class Color:
    GREEN = '\033[92m'
    BLUE = '\033[94m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    RESET = '\033[0m'

def print_step(msg):
    print(f"{Color.BLUE}→ {msg}{Color.RESET}")

def print_success(msg):
    print(f"{Color.GREEN}✓ {msg}{Color.RESET}")

def print_warning(msg):
    print(f"{Color.YELLOW}⚠ {msg}{Color.RESET}")

def print_error(msg):
    print(f"{Color.RED}✗ {msg}{Color.RESET}")
    sys.exit(1)

def run_command(cmd, check=True, shell=False):
    """Run a shell command and return success status."""
    try:
        result = subprocess.run(
            cmd,
            shell=shell,
            check=check,
            cwd=os.getcwd(),
            env=os.environ.copy()
        )
        return result.returncode == 0
    except subprocess.CalledProcessError as e:
        print_error(f"Command failed: {' '.join(cmd) if isinstance(cmd, list) else cmd}")
        return False
    except FileNotFoundError:
        return False

def get_python_executable():
    """Get the Python executable path."""
    if sys.platform == "win32":
        return sys.executable
    return sys.executable

def get_venv_activate():
    """Get the path to venv activate script."""
    venv_path = Path(".venv")
    if sys.platform == "win32":
        return venv_path / "Scripts" / "activate.bat"
    return venv_path / "bin" / "activate"

def create_venv():
    """Create virtual environment if it doesn't exist."""
    venv_path = Path(".venv")
    if venv_path.exists():
        print_success("Virtual environment already exists")
        return True

    print_step("Creating virtual environment...")
    if not run_command([sys.executable, "-m", "venv", ".venv"]):
        print_error("Failed to create virtual environment")
    print_success("Virtual environment created")
    return True

def get_pip_executable():
    """Get pip executable for the venv."""
    venv_path = Path(".venv")
    if sys.platform == "win32":
        return venv_path / "Scripts" / "pip.exe"
    return venv_path / "bin" / "pip"

def install_dependencies():
    """Install project dependencies."""
    print_step("Installing dependencies...")
    pip_exe = get_pip_executable()
    
    # Upgrade pip
    run_command([str(pip_exe), "install", "--upgrade", "pip", "setuptools", "wheel"], check=False)
    
    # Install requirements
    if not run_command([str(pip_exe), "install", "-r", "requirements.txt"]):
        print_error("Failed to install dependencies")
    print_success("Dependencies installed")
    return True

def create_env_file():
    """Create .env file from .env.example if it doesn't exist."""
    env_file = Path(".env")
    env_example = Path(".env.example")
    
    if env_file.exists():
        print_success(".env file already exists")
        return True
    
    if not env_example.exists():
        print_warning(".env.example not found, creating minimal .env")
        secret_key = secrets.token_urlsafe(50)
        env_content = f"""DJANGO_SETTINGS_MODULE=config.settings.development
SECRET_KEY={secret_key}
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1
DATABASE_URL=sqlite:///db.sqlite3
CSRF_TRUSTED_ORIGINS=http://localhost:8000
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
CELERY_TASK_ALWAYS_EAGER=True
SQL_DEBUG_LEVEL=WARNING
"""
    else:
        print_step("Creating .env from .env.example...")
        env_content = env_example.read_text()
        secret_key = secrets.token_urlsafe(50)
        env_content = env_content.replace("change-me-to-a-long-random-string", secret_key)
        env_content = env_content.replace(
            "DATABASE_URL=postgres://auction_user:auction_pass@localhost:5432/mbarara_auction",
            "DATABASE_URL=sqlite:///db.sqlite3"
        )
        env_content += f"\nCELERY_TASK_ALWAYS_EAGER=True\nSQL_DEBUG_LEVEL=WARNING\n"
    
    env_file.write_text(env_content)
    print_success(".env file created")
    return True

def run_migrations():
    """Run Django migrations."""
    print_step("Running database migrations...")
    python_exe = get_python_executable()
    
    if not run_command([python_exe, "manage.py", "migrate"]):
        print_error("Failed to run migrations")
    print_success("Migrations completed")
    return True

def create_superuser():
    """Create superuser if it doesn't exist."""
    print_step("Checking for superuser...")
    python_exe = get_python_executable()
    
    # Check if any superuser exists
    check_cmd = f"""python manage.py shell -c "from django.contrib.auth import get_user_model; User = get_user_model(); exit(0 if User.objects.filter(is_superuser=True).exists() else 1)"""
    
    if run_command([python_exe, "manage.py", "shell", "-c", 
                    "from django.contrib.auth import get_user_model; User = get_user_model(); import sys; sys.exit(0 if User.objects.filter(is_superuser=True).exists() else 1)"],
                   check=False):
        print_success("Superuser already exists")
        return True
    
    print_step("No superuser found. Creating one...")
    print(f"{Color.YELLOW}Enter superuser credentials:{Color.RESET}")
    
    username = input("Username [admin]: ").strip() or "admin"
    email = input("Email [admin@localhost]: ").strip() or "admin@localhost"
    password = input("Password: ").strip()
    
    if not password:
        print_error("Password cannot be empty")
    
    create_cmd = f"""from django.contrib.auth import get_user_model; User = get_user_model(); User.objects.filter(username='{username}').delete(); User.objects.create_superuser('{username}', '{email}', '{password}')"""
    
    if not run_command([python_exe, "manage.py", "shell", "-c", create_cmd], check=False):
        print_warning("Could not auto-create superuser. You can create one manually after startup.")
        return False
    
    print_success(f"Superuser '{username}' created")
    return True

def reset_database():
    """Reset database and start fresh."""
    print_step("Resetting database...")
    db_file = Path("db.sqlite3")
    
    if db_file.exists():
        db_file.unlink()
        print_success("Database deleted")
    
    run_migrations()
    create_superuser()
    print_success("Database reset complete")

def run_server():
    """Start Django development server."""
    print_step("Starting development server...")
    print(f"{Color.GREEN}")
    print("="*60)
    print("Mbarara Auction System is running!")
    print("="*60)
    print(f"Visit: {Color.BLUE}http://localhost:8000{Color.GREEN}")
    print(f"Admin: {Color.BLUE}http://localhost:8000/admin{Color.GREEN}")
    print("Press CTRL+C to stop")
    print(f"{Color.RESET}")
    
    python_exe = get_python_executable()
    try:
        subprocess.run([python_exe, "manage.py", "runserver"], check=False)
    except KeyboardInterrupt:
        print(f"\n{Color.YELLOW}Server stopped.{Color.RESET}")
        sys.exit(0)

def main():
    """Main setup and startup flow."""
    print(f"{Color.BLUE}")
    print("="*60)
    print("Mbarara Auction System - Auto Setup")
    print("="*60)
    print(f"{Color.RESET}")
    
    # Handle command-line arguments
    reset_mode = "--reset" in sys.argv
    help_mode = "--help" in sys.argv or "-h" in sys.argv
    
    if help_mode:
        print(f"""{Color.BLUE}Usage:{Color.RESET}
    python start.py              # Full setup + run server
    python start.py --reset      # Wipe database and start fresh
    python start.py --help       # Show this message

{Color.BLUE}What it does:{Color.RESET}
    1. Creates virtual environment (if needed)
    2. Installs dependencies
    3. Creates .env file (if needed)
    4. Runs database migrations
    5. Creates superuser (if needed)
    6. Starts development server

{Color.BLUE}After startup:{Color.RESET}
    • Visit http://localhost:8000
    • Log in with your superuser account at http://localhost:8000/admin
    • Press CTRL+C to stop the server
        """)
        return
    
    # Check Python version
    if sys.version_info < (3, 8):
        print_error(f"Python 3.8+ required. You have {sys.version}")
    
    # Setup steps
    try:
        if not create_venv():
            return
        if not install_dependencies():
            return
        if not create_env_file():
            return
        
        if reset_mode:
            reset_database()
        else:
            if not run_migrations():
                return
            create_superuser()
        
        run_server()
    except KeyboardInterrupt:
        print(f"\n{Color.YELLOW}Setup cancelled.{Color.RESET}")
        sys.exit(1)
    except Exception as e:
        print_error(f"Unexpected error: {e}")

if __name__ == "__main__":
    main()
