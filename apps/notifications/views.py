from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from .models import Notification
from .services import mark_all_read, mark_read


class InboxView(LoginRequiredMixin, View):
    def get(self, request):
        notifications = Notification.objects.filter(recipient=request.user)
        return render(request, "notifications/inbox.html", {"notifications": notifications})


class MarkReadView(LoginRequiredMixin, View):
    def post(self, request, pk):
        # Scoped to the requesting user so this 404s rather than raising on
        # someone else's notification — mark_read()'s ownership check below
        # is then a defence-in-depth backstop, not the primary guard.
        notification = get_object_or_404(Notification, pk=pk, recipient=request.user)
        mark_read(notification, user=request.user)
        return redirect(request.POST.get("next") or "notifications:inbox")


class MarkAllReadView(LoginRequiredMixin, View):
    def post(self, request):
        mark_all_read(request.user)
        return redirect(request.POST.get("next") or "notifications:inbox")
