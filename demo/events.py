"""Who may read which server-sent event topic, and who is in the chat.

django-pg-sse runs the streams.

PG_SSE["CAN_SUBSCRIBE"] and PG_SSE["PRESENCE_IDENTITY"] in settings.py point here.
"""

from typing import Any

from django.http import HttpRequest
from django.template.loader import render_to_string
from django_pg_sse import abroadcast
from django_pg_sse.permissions import can_subscribe as default_can_subscribe
from django_pg_sse.presence import Presence, apresent


def can_subscribe(request: HttpRequest, topic: str) -> bool:
    """Decides whether the requesting user may receive the events of `topic`.

    The default opens `public:` topics to everyone and `user:<pk>` to that user.
    Every other kind stays closed. Add a case for each kind of topic the project adds.
    It runs when a stream opens; call close_streams() after taking access away.
    """
    # kind, _, key = topic.partition(":")
    # if kind == "room":
    #     return Membership.objects.filter(room=key, user=request.user.pk).exists()
    return default_can_subscribe(request, topic)


def chat_identity(request: HttpRequest) -> tuple[str, dict[str, Any]] | None:
    """Names a chat stream's visitor by the random sender id that views.join() stores.

    Every reader of the chat sees the identity, so it is the sender id, never the session key.
    """
    if not {"chat_name", "chat_sender"} <= request.session.keys():
        return None
    return f"visitor:{request.session['chat_sender']}", {"name": request.session["chat_name"]}


async def show_who_is_here(
    sender: Any, topic: str, joined: tuple[Presence, ...], left: tuple[Presence, ...], **kwargs: Any
) -> None:
    """Sends the chat's new online list to every open chat page.

    apps.py connects it to presence_changed.
    """
    from demo.models import Visitor
    from demo.views import TOPIC

    if topic != TOPIC:
        return
    online = Visitor.of(await apresent(topic))
    html = render_to_string("chat.html#online", {"online": online, "oob": True})
    # latest: a replay sends only the newest list, not every list the tab missed.
    await abroadcast(topic, html, latest="online")
