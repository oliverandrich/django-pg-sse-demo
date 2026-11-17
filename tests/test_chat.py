from unittest import mock

from asgiref.sync import async_to_sync
from django.contrib.sessions.backends.db import SessionStore
from django.test import RequestFactory
from django.utils import timezone
from django.utils.module_loading import import_string
from django_pg_sse import conf
from django_pg_sse.models import StreamEvent
from django_pg_sse.presence import Presence
from django_pg_sse.presence.models import PresenceEntry
from model_bakery import baker
from test_plus.test import TestCase

from demo import events
from demo.models import Message
from demo.views import TOPIC


class ChatTestCase(TestCase):
    def join(self, name="Ada"):
        return self.post("join", data={"name": name})


class JoinTest(ChatTestCase):
    def test_the_chat_asks_for_a_name_first(self):
        response = self.get("chat")
        self.assertRedirects(response, self.reverse("join"))

    def test_joining_stores_the_name_and_opens_the_chat(self):
        response = self.join("Ada")
        self.assertRedirects(response, self.reverse("chat"))
        self.assertEqual(self.client.session["chat_name"], "Ada")
        self.get_check_200("chat")
        self.assertResponseContains("Ada", html=False)

    def test_a_blank_name_is_rejected(self):
        self.join("   ")
        self.response_400()
        self.assertNotIn("chat_name", self.client.session)

    def test_a_new_name_keeps_the_sender(self):
        self.join("Ada")
        sender = self.client.session["chat_sender"]
        self.join("Grace")
        self.assertEqual(self.client.session["chat_name"], "Grace")
        self.assertEqual(self.client.session["chat_sender"], sender)


class ChatPageTest(ChatTestCase):
    def test_the_page_shows_earlier_messages_and_opens_the_stream(self):
        baker.make(Message, name="Grace", text="Hello there")
        self.join()
        self.get_check_200("chat")
        self.assertResponseContains("Hello there", html=False)
        self.assertResponseContains("/events/?topic=public:chat", html=False)


class SendTest(ChatTestCase):
    def test_sending_needs_a_name(self):
        self.post("send", data={"text": "Hi"})
        self.response_403()
        self.assertFalse(Message.objects.exists())

    def test_a_message_is_stored_and_broadcast(self):
        self.join("Ada")
        with self.captureOnCommitCallbacks(execute=True):
            self.post("send", data={"text": "Hi <b>all</b>"})
        self.response_200()
        message = Message.objects.get()
        self.assertEqual((message.name, message.text), ("Ada", "Hi <b>all</b>"))
        self.assertEqual(message.sender, self.client.session["chat_sender"])
        event = StreamEvent.objects.get(topic="public:chat")
        self.assertIn(f'id="message-{message.pk}"', event.data)
        self.assertIn(
            f'beforeend target:"#messages:not(:has(> #message-{message.pk}))"', event.data
        )
        self.assertIn("Hi &lt;b&gt;all&lt;/b&gt;", event.data)

    def test_an_empty_message_is_rejected(self):
        self.join()
        self.post("send", data={"text": "  "})
        self.response_400()
        self.assertFalse(Message.objects.exists())

    def test_a_message_over_500_characters_is_rejected(self):
        self.join()
        self.post("send", data={"text": "x" * 501})
        self.response_400()
        self.assertFalse(Message.objects.exists())


class PresenceTest(ChatTestCase):
    def test_a_visitor_with_a_name_is_present_under_their_sender_id(self):
        request = RequestFactory().get("/events/")
        request.session = SessionStore()
        request.session.update({"chat_name": "Ada", "chat_sender": "abc123"})
        self.assertEqual(events.chat_identity(request), ("visitor:abc123", {"name": "Ada"}))

    def test_a_session_without_a_sender_id_is_not_present(self):
        request = RequestFactory().get("/events/")
        request.session = SessionStore()
        request.session["chat_name"] = "Ada"
        self.assertIsNone(events.chat_identity(request))

    def test_a_visitor_without_a_name_is_not_present(self):
        request = RequestFactory().get("/events/")
        request.session = SessionStore()
        self.assertIsNone(events.chat_identity(request))

    def test_the_chat_topic_tracks_presence_by_that_identity(self):
        self.assertIn(TOPIC, conf.get("PRESENCE_TOPICS"))
        self.assertIs(import_string(conf.get("PRESENCE_IDENTITY")), events.chat_identity)

    def test_the_page_lists_who_is_already_here(self):
        baker.make(
            PresenceEntry,
            topic=TOPIC,
            identity="visitor:x",
            meta={"name": "Grace"},
            last_seen=timezone.now(),
        )
        self.join("Ada")
        self.get_check_200("chat")
        self.assertResponseContains('id="online"', html=False)
        self.assertResponseContains("Grace", html=False)

    def test_a_change_broadcasts_the_new_list(self):
        here = [Presence("visitor:a", {"name": "Ada"}), Presence("visitor:b", {"name": "Grace"})]
        with (
            mock.patch.object(events, "apresent", mock.AsyncMock(return_value=here)),
            mock.patch.object(events, "abroadcast", mock.AsyncMock()) as abroadcast,
        ):
            async_to_sync(events.show_who_is_here)(
                sender=Presence, topic=TOPIC, joined=(here[1],), left=()
            )
        ((topic, html), _) = abroadcast.call_args
        self.assertEqual(topic, TOPIC)
        self.assertIn('id="online"', html)
        self.assertIn('hx-swap-oob="true"', html)
        self.assertIn("Grace", html)
        self.assertIn("2 online", html)

    def test_other_topics_are_left_alone(self):
        with mock.patch.object(events, "abroadcast", mock.AsyncMock()) as abroadcast:
            async_to_sync(events.show_who_is_here)(
                sender=Presence, topic="public:other", joined=(), left=()
            )
        abroadcast.assert_not_called()
