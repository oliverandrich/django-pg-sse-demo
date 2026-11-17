# django-pg-sse demo

A small chat that shows [django-pg-sse](https://github.com/oliverandrich/django-pg-sse) in a Django project.
Visitors pick a name and chat; there is no login.
Messages reach every open browser over PostgreSQL LISTEN/NOTIFY and server-sent events.
No Redis and no WebSocket server are involved.
The header shows who is online, through the presence app of django-pg-sse.

![The chat page with messages from two visitors and both of them online in the header.](docs/screenshot.png)

The project was generated from [django-project-starter](https://github.com/oliverandrich/django-project-starter).
It uses htmx 4 with its hx-sse extension, and Tailwind CSS with daisyUI.

## Run it

You need [mise](https://mise.jdx.dev/) and a running PostgreSQL server.

```sh
mise trust
mise run bootstrap   # .env, dependencies, database, CSS
mise run migrate
mise run debugserver
```

Open <http://127.0.0.1:8000/> in two browsers, or in a normal and a private window.
`mise run runserver` speaks WSGI and cannot stream, so use `debugserver`.

## Where to look

| File | What it shows |
|---|---|
| `demo/views.py` | `send()` stores a message and calls `broadcast("public:chat", html)`. |
| `demo/templates/chat.html` | The partial `broadcast` wraps a message in `hx-swap-oob="beforeend"` for `#messages`. |
| `demo/templates/chat.html` | `hx-sse:connect` opens one stream for the topic `public:chat`. |
| `demo/templates/chat.html` | A short script aligns the visitor's own messages, since every visitor receives the same HTML. |
| `demo/settings.py` | `PG_SSE` points `CAN_SUBSCRIBE` and `PRESENCE_IDENTITY` at `demo/events.py` and tracks `public:chat`. |
| `demo/events.py` | `chat_identity()` names a visitor by the random sender id; `show_who_is_here()` broadcasts the online list. |
| `demo/events.py` | The list goes out with `latest="online"`, so a replay sends only the newest one. |
| `demo/templates/chat.html` | The partial `online` renders that list, with `hx-swap-oob="true"` in the broadcast. |
| `demo/urls.py` | The stream view lives at `/events/`. |

`broadcast()` sends after the transaction commits.
The default `can_subscribe()` opens `public:` topics to everyone, so anonymous visitors may read the chat.
A reconnecting browser replays the messages it missed from the table `django_pg_sse_streamevent`.
The page itself renders the last 50 messages.

## Load test

`loadtest/sse_load.py` opens many streams and measures how long each message takes to reach all of them.
Each client joins with a name, so presence runs as in a browser; `--anonymous` skips the join.
It is a standalone uv script, so the demo needs no extra dependency.

Run the server without `DEBUG`, as `debugserver` adds a browser-reload stream per tab:

```sh
ulimit -n 65536
uv run python manage.py collectstatic --no-input
DEBUG=false SECRET_KEY=local ALLOWED_HOSTS=127.0.0.1 GRANIAN_PORT=8002 uv run python manage.py serve
```

In a second shell:

```sh
ulimit -n 65536
uv run loadtest/sse_load.py --base http://127.0.0.1:8002 --clients 1000 --rate 10 --duration 20
```

granian handles at most `GRANIAN_BACKPRESSURE` requests per worker at once, and every open stream is one.
granian's own default is its backlog of 1024 divided by the workers.
`manage.py serve` sets 8192 instead; without it, the 2000-client runs below failed past 1024 streams.

First results, one worker, client and server on one MacBook, PostgreSQL local:

| Clients | Join | Messages | Connected after | Lost | Latency p50 / p99 | Worker RSS |
|---|---|---|---|---|---|---|
| 100 | named | 10/s | 1.2 s | 0 | 13 / 22 ms | 97 MB |
| 500 | named | 10/s | 7.8 s | 0 | 21 / 42 ms | 184 MB |
| 1000 | named | 10/s | 24.9 s | 0 | 30 / 84 ms | 360 MB |
| 1000 | anonymous | 10/s | 10.5 s | 0 | 31 / 75 ms | 347 MB |
| 1000 | named | 50/s | 24.7 s | 0 | 25 / 43 ms | 383 MB |
| 2000 | named | 10/s | 90.0 s | 0 | 47 / 142 ms | 834 MB |
| 2000 | anonymous | 10/s | 21.2 s | 0 | 46 / 155 ms | 804 MB |

The ramp asked for 100 new clients per second.
In these runs, every join sent the whole online list to every open stream.

`demo/events.py` now sends at most one online list per second and worker, and the list has a fixed size:

| Clients | Join | Messages | Connected after | Lost | Latency p50 / p99 | Worker RSS |
|---|---|---|---|---|---|---|
| 1000 | named | 10/s | 10.5 s | 0 | 28 / 45 ms | 222 MB |
| 2000 | named | 10/s | 21.2 s | 0 | 46 / 103 ms | 364 MB |

Both connect as fast as the ramp, like anonymous clients.

## Known limits

A message sent between rendering the page and opening the stream does not reach that page.
The first connect has no `Last-Event-ID` to replay from.

## License

MIT, see [LICENSE](LICENSE).
