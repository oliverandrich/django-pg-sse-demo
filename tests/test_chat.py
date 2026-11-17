from django_pg_sse.models import StreamEvent
from model_bakery import baker
from test_plus.test import TestCase

from demo.models import Message


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
