from .services import unread_count


def notifications(request):
    """Adds `unread_notification_count` to every template context so the
    navbar badge (templates/base.html) doesn't need every view to remember
    to pass it in explicitly."""
    user = getattr(request, "user", None)
    return {"unread_notification_count": unread_count(user) if user else 0}
