from dataclasses import dataclass
from zlib import crc32

from django.db import models
from django_pg_sse.presence import Presence


@dataclass(frozen=True)
class Visitor:
    """A chat visitor as the page shows them: a name with initials and an avatar hue."""

    name: str

    @classmethod
    def of(cls, readers: list[Presence]) -> list[Visitor]:
        """The visitors behind the readers that present() returns."""
        return [cls(reader.meta["name"]) for reader in readers]

    @property
    def initials(self) -> str:
        return "".join(part[0] for part in self.name.split()[:2]).upper()

    @property
    def hue(self) -> int:
        """A stable avatar hue per name."""
        return crc32(self.name.encode()) % 360


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
        return Visitor(self.name).initials

    @property
    def hue(self) -> int:
        return Visitor(self.name).hue
