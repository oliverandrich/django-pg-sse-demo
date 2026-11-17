from django.contrib import admin

from demo.models import Message


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ["created", "name", "text"]
    search_fields = ["name", "text"]
    ordering = ["-pk"]
