from django.contrib import admin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("created_at", "recipient", "event", "channel", "title", "is_read")
    list_filter = ("event", "channel")
    search_fields = ("recipient__username", "title", "message")
    readonly_fields = ("recipient", "event", "channel", "title", "message", "related_object_type", "related_object_id", "link", "created_at")

    def has_add_permission(self, request):
        return False  # notifications are only ever created via apps.notifications.services.notify

    def is_read(self, obj):
        return obj.is_read
    is_read.boolean = True
