from django.contrib import admin

from .models import RadiosondeProfile


@admin.register(RadiosondeProfile)
class RadiosondeProfileAdmin(admin.ModelAdmin):
    list_display = ("id", "date", "time", "observed_at", "bucket", "object_key")
    list_filter = ("date",)
    search_fields = ("object_key",)
    ordering = ("-date", "time")
