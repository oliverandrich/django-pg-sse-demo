"""Who may read which server-sent event topic, and who is in the chat.

django-pg-sse runs the streams.

PG_SSE["CAN_SUBSCRIBE"] and PG_SSE["PRESENCE_IDENTITY"] in settings.py point here.
"""

import asyncio
import contextvars
import logging
import weakref
from typing import Any

from asgiref.sync import sync_to_async
from django.db import connections
from django.http import HttpRequest
from django.template.loader import render_to_string
from django_pg_sse import broadcast
from django_pg_sse.permissions import can_subscribe as default_can_subscribe
from django_pg_sse.presence import Presence, present

logger = logging.getLogger(__name__)

# Seconds a change waits, so the joins and leaves of that second share one broadcast.
ONLINE_DELAY = 1.0
# The event loops whose broadcast has not read the list yet.
_pending: weakref.WeakSet[asyncio.AbstractEventLoop] = weakref.WeakSet()
# asyncio keeps only weak references to tasks.
_tasks: set[asyncio.Task[None]] = set()


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
    """Schedules the chat's new online list for every open chat page.

    apps.py connects it to presence_changed.
    Each join would otherwise send a list of every visitor to every stream.
    """
    from demo.views import TOPIC

    if topic != TOPIC:
        return
    loop = asyncio.get_running_loop()
    if loop in _pending:
        return
    # An empty context: the change may come from a stream or a sweep, and its request context
    # would give sync_to_async that request's thread. Without one, it uses the shared sync thread.
    task = loop.create_task(_send_online(topic), context=contextvars.Context())
    _pending.add(loop)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def _send_online(topic: str) -> None:
    try:
        await asyncio.sleep(ONLINE_DELAY)
    finally:
        # Removed before the read: a change during the read schedules the next broadcast.
        _pending.discard(asyncio.get_running_loop())
    try:
        await sync_to_async(_broadcast_online)(topic)
    except Exception:
        logger.exception("Sending the online list failed.")


def _broadcast_online(topic: str) -> None:
    from demo.models import Visitor

    try:
        online = Visitor.of(present(topic))
        html = render_to_string("chat.html#online", {"online": online, "oob": True})
        # latest: a replay sends only the newest list, not every list the tab missed.
        broadcast(topic, html, latest="online")
    finally:
        # The shared sync thread would hold its connections until the worker stops.
        connections.close_all()
