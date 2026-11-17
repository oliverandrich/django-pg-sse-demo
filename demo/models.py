from zlib import crc32

from django.db import models


class Message(models.Model):
    """One chat message, written by a visitor who picked a name."""

    name = models.CharField(max_length=30)
    # A random id per session. chat.html compares it to align the visitor's own messages.
    sender = models.CharField(max_length=32)
    text = models.CharField(max_length=500)
    created = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.name}: {self.text[:50]}"

    @property
    def initials(self) -> str:
        return "".join(part[0] for part in self.name.split()[:2]).upper()

    @property
    def hue(self) -> int:
        """A stable avatar hue per name."""
        return crc32(self.name.encode()) % 360
