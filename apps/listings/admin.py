from django.contrib import admin
from .models import AuctionImage


@admin.register(AuctionImage)
class AuctionImageAdmin(admin.ModelAdmin):
    list_display = ("auction", "sort_order")
    list_filter = ("auction__status",)
