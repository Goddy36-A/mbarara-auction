from django.urls import path

from . import views

app_name = "notifications"

urlpatterns = [
    path("", views.InboxView.as_view(), name="inbox"),
    path("<int:pk>/read/", views.MarkReadView.as_view(), name="mark_read"),
    path("mark-all-read/", views.MarkAllReadView.as_view(), name="mark_all_read"),
]
