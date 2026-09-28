from django.contrib import admin

from .models import RadiosondeProfile, RadiosondeReport


@admin.register(RadiosondeProfile)
class RadiosondeProfileAdmin(admin.ModelAdmin):
    list_display = ("id", "date", "time", "observed_at", "bucket", "object_key")
    list_filter = ("date",)
    search_fields = ("object_key",)
    ordering = ("-date", "time")


@admin.register(RadiosondeReport)
class RadiosondeReportAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "start_date",
        "end_date",
        "time",
        "status",
        "profile_count",
        "processed_count",
        "failed_count",
        "created_at",
    )
    list_filter = ("status", "start_date", "end_date")
    search_fields = ("filename", "fingerprint", "object_key")
    ordering = ("-created_at",)
