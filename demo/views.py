from uuid import uuid4

from django.http import HttpRequest, HttpResponse, HttpResponseForbidden
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.views.decorators.http import require_POST
from django_pg_sse import broadcast

from demo.forms import JoinForm, MessageForm
from demo.models import Message

TOPIC = "public:chat"
HISTORY = 50


def join(request: HttpRequest) -> HttpResponse:
    data = request.POST if request.method == "POST" else None
    form = JoinForm(data, initial={"name": request.session.get("chat_name")})
    if form.is_valid():
        request.session["chat_name"] = form.cleaned_data["name"]
        request.session.setdefault("chat_sender", uuid4().hex)
        return redirect("chat")
    return render(request, "join.html", {"form": form}, status=400 if form.is_bound else 200)


def chat(request: HttpRequest) -> HttpResponse:
    if "chat_name" not in request.session:
        return redirect("join")
    # The newest messages, shown oldest first.
    history = reversed(Message.objects.order_by("-pk")[:HISTORY])
    return render(request, "chat.html", {"history": history, "form": MessageForm(), "topic": TOPIC})


@require_POST
def send(request: HttpRequest) -> HttpResponse:
    if "chat_name" not in request.session:
        return HttpResponseForbidden()
    form = MessageForm(request.POST)
    if not form.is_valid():
        return render(request, "chat.html#form", {"form": form}, status=400)
    message = form.save(commit=False)
    message.name = request.session["chat_name"]
    message.sender = request.session["chat_sender"]
    message.save()
    broadcast(TOPIC, render_to_string("chat.html#broadcast", {"message": message}))
    return render(request, "chat.html#form", {"form": MessageForm()})
