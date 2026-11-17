# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx>=0.28"]
# ///
"""Load test for the chat: many SSE clients, one sender, delivery latency per message.

Each client joins with a name, so presence runs as in a browser, then opens the stream of
public:chat. Once all clients are connected, a sender posts messages at a fixed rate. Every
message carries its send time, and every client measures how long it took to arrive.

    uv run loadtest/sse_load.py --clients 500 --rate 10 --duration 30

Run it against a server without DEBUG, on the same database as the chat.
"""

import argparse
import asyncio
import re
import statistics
import time
import uuid
from dataclasses import dataclass, field

import httpx

TOPIC = "public:chat"
MARKER = re.compile(r"LOADMSG (\d+) (\d+\.\d+) (\w+)")


@dataclass
class Stats:
    connected: int = 0
    failed: int = 0
    connect_seconds: list[float] = field(default_factory=list)
    errors: dict[str, int] = field(default_factory=dict)
    deliveries: int = 0
    latencies: list[float] = field(default_factory=list)
    send_seconds: list[float] = field(default_factory=list)
    sent: int = 0
    send_failed: int = 0

    def error(self, kind: str) -> None:
        self.errors[kind] = self.errors.get(kind, 0) + 1


async def join(client: httpx.AsyncClient, base: str, name: str) -> None:
    """The join form: a session with a name, and the CSRF cookie for later posts."""
    await client.get(f"{base}/join/")
    token = client.cookies.get("csrftoken", "")
    response = await client.post(
        f"{base}/join/", data={"name": name}, headers={"X-CSRFToken": token}
    )
    if response.status_code != 302:
        raise RuntimeError(f"join answered {response.status_code}")


async def listen(
    index: int, args: argparse.Namespace, run: str, stats: Stats, stop: asyncio.Event
) -> None:
    async with httpx.AsyncClient(timeout=httpx.Timeout(30, read=None)) as client:
        started = time.perf_counter()
        try:
            if not args.anonymous:
                await join(client, args.base, f"load {index}")
            headers = {"Accept": "text/event-stream"}
            async with client.stream(
                "GET", f"{args.base}/events/", params={"topic": TOPIC}, headers=headers
            ) as response:
                if response.status_code != 200:
                    stats.failed += 1
                    stats.error(f"HTTP {response.status_code}")
                    return
                lines = response.aiter_lines()
                async for line in lines:
                    if line.startswith(": connected"):
                        stats.connected += 1
                        stats.connect_seconds.append(time.perf_counter() - started)
                        break
                reading = asyncio.ensure_future(_read(lines, run, stats))
                await stop.wait()
                reading.cancel()
        except (httpx.HTTPError, RuntimeError) as error:
            stats.failed += 1
            stats.error(type(error).__name__)


async def _read(lines, run: str, stats: Stats) -> None:  # noqa: ANN001
    async for line in lines:
        if line.startswith("data:") and (match := MARKER.search(line)) and match[3] == run:
            stats.deliveries += 1
            stats.latencies.append(time.time() - float(match[2]))


async def send(args: argparse.Namespace, run: str, stats: Stats) -> None:
    async with httpx.AsyncClient(timeout=30) as client:
        await join(client, args.base, "load sender")
        token = client.cookies.get("csrftoken", "")
        interval = 1 / args.rate
        deadline = time.perf_counter() + args.duration
        sequence = 0
        while time.perf_counter() < deadline:
            tick = time.perf_counter()
            text = f"LOADMSG {sequence} {time.time():.6f} {run}"
            try:
                response = await client.post(
                    f"{args.base}/messages/", data={"text": text}, headers={"X-CSRFToken": token}
                )
                if response.status_code == 200:
                    stats.sent += 1
                else:
                    stats.send_failed += 1
            except httpx.HTTPError:
                stats.send_failed += 1
            stats.send_seconds.append(time.perf_counter() - tick)
            sequence += 1
            await asyncio.sleep(max(0, interval - (time.perf_counter() - tick)))


def percentiles(values: list[float]) -> str:
    if not values:
        return "-"
    ordered = sorted(values)

    def at(share: float) -> float:
        return ordered[min(len(ordered) - 1, int(share * len(ordered)))] * 1000

    shares = ", ".join(f"p{round(share * 100)} {at(share):.0f} ms" for share in (0.5, 0.95, 0.99))
    return f"{shares}, max {ordered[-1] * 1000:.0f} ms"


async def main(args: argparse.Namespace) -> None:
    run = uuid.uuid4().hex[:8]
    stats = Stats()
    stop = asyncio.Event()
    kind = "anonymous" if args.anonymous else "named"
    print(f"run {run}: {args.clients} clients at {args.ramp}/s, {kind}")

    started = time.perf_counter()
    listeners = []
    for index in range(args.clients):
        listeners.append(asyncio.create_task(listen(index, args, run, stats, stop)))
        await asyncio.sleep(1 / args.ramp)
    # Every client has either connected or failed.
    while (
        stats.connected + stats.failed < args.clients
        and time.perf_counter() - started < args.connect_timeout
    ):
        await asyncio.sleep(0.2)
    ramp_seconds = time.perf_counter() - started
    print(f"connected {stats.connected}, failed {stats.failed} after {ramp_seconds:.1f} s")

    if stats.connected:
        await asyncio.sleep(args.settle)
        await send(args, run, stats)
        await asyncio.sleep(args.settle)
    stop.set()
    await asyncio.gather(*listeners, return_exceptions=True)

    expected = stats.sent * stats.connected
    print()
    print(
        f"connections   ok {stats.connected}, failed {stats.failed}, errors {stats.errors or '-'}"
    )
    print(f"connect time  {percentiles(stats.connect_seconds)}")
    print(f"messages      sent {stats.sent} at {args.rate}/s, failed {stats.send_failed}")
    print(f"send request  {percentiles(stats.send_seconds)}")
    loss = 1 - stats.deliveries / expected if expected else 0
    print(f"deliveries    {stats.deliveries} of {expected} ({loss:.2%} lost)")
    print(f"latency       {percentiles(stats.latencies)}")
    if stats.latencies:
        print(f"latency mean  {statistics.mean(stats.latencies) * 1000:.0f} ms")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default="http://127.0.0.1:8000", help="the chat's URL")
    parser.add_argument("--clients", type=int, default=100)
    parser.add_argument("--ramp", type=float, default=50, help="new connections per second")
    parser.add_argument("--rate", type=float, default=5, help="messages per second")
    parser.add_argument("--duration", type=float, default=20, help="seconds of sending")
    parser.add_argument("--settle", type=float, default=3, help="seconds before and after sending")
    parser.add_argument("--connect-timeout", type=float, default=120)
    parser.add_argument(
        "--anonymous", action="store_true", help="skip the join, so presence tracks nobody"
    )
    asyncio.run(main(parser.parse_args()))
