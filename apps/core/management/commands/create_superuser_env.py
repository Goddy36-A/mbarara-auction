import os
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create a superuser from env vars (idempotent)"

    def handle(self, *args, **options):
        User = get_user_model()

        email    = os.environ.get("DJANGO_SUPERUSER_EMAIL", "").strip()
        password = os.environ.get("DJANGO_SUPERUSER_PASSWORD", "").strip()
        username = os.environ.get("DJANGO_SUPERUSER_USERNAME", "admin").strip()

        if not email or not password:
            self.stdout.write(self.style.WARNING(
                "DJANGO_SUPERUSER_EMAIL or DJANGO_SUPERUSER_PASSWORD not set — skipping."
            ))
            return

        user, created = User.objects.get_or_create(
            username=username,
            defaults={"email": email, "role": User.Role.ADMIN},
        )

        # Always force these flags — fixes cases where user existed
        # but was created without staff/superuser rights
        user.email       = email
        user.is_staff    = True
        user.is_superuser = True
        user.role        = User.Role.ADMIN
        user.set_password(password)
        user.save()

        action = "Created" if created else "Updated"
        self.stdout.write(self.style.SUCCESS(
            f"{action} superuser: username='{username}' email='{email}' "
            f"is_staff=True is_superuser=True role=ADMIN"
        ))
