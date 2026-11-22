"""Standalone DiveCalc competition pacing monitor."""

import argparse
import json
import math
import time
from dataclasses import dataclass
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from queue import Empty, Full, Queue
from threading import Thread


FEED_PATH = "/divecalc"
MAX_BODY = 2 * 1024 * 1024


# Feed parsing: convert DiveCalc's JSON into a snapshot the timing code can use.
def integer(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def feed_time(value: object) -> float | None:
    # DiveCalc timestamps are milliseconds since the Unix epoch; Python uses seconds.
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    try:
        seconds = value / 1000
        if seconds <= 0:
            return None
        datetime.fromtimestamp(seconds)
    except (ValueError, OverflowError, OSError):
        return None
    return seconds


@dataclass(frozen=True)
class Snapshot:
    # Include the competition in the key: an event ID alone can be reused at another meet.
    key: tuple[str, float | None, int]
    name: str
    start: float | None
    end: float | None
    finished: bool
    progress: tuple[int, int] | None  # (completed dives, total dives), as reported by the feed
    progress_note: str
    total_dives: int | None
    dive_number: int | None
    is_next: bool
    is_awards: bool

    @classmethod
    def parse(cls, payload: object) -> "Snapshot":
        if not isinstance(payload, dict) or not isinstance(payload.get("event"), dict):
            raise ValueError("Expected a DiveCalc message with a current event")
        event = payload["event"]
        event_id = integer(event.get("pk"))
        name, finished = event.get("name"), event.get("finished")
        if event_id is None or not isinstance(name, str) or not isinstance(finished, bool):
            raise ValueError("Missing or invalid DiveCalc event identity or status")

        # These two "position" fields mean different things: dive-list round and start order.
        diver = payload.get("diver")
        dive = diver.get("dive") if isinstance(diver, dict) else None
        dive_round = integer(dive.get("position")) if isinstance(dive, dict) else None
        diver_position = integer(diver.get("position")) if isinstance(diver, dict) else None

        action = payload.get("action")
        completed, total, note = read_progress(event, finished, action, dive_round, diver_position)
        progress = (completed, total) if completed is not None and total is not None else None

        # Number dives across the whole event, not within a round. Results may arrive
        # in ranking order, so sort by start position and leave out no-shows.
        dive_number = None
        if total is not None and dive_round is not None and diver_position is not None:
            positions = [integer(row.get("position")) for row in event["results"] if row.get("result") != "DNS"]
            if None not in positions and len(set(positions)) == len(positions) and diver_position in positions:
                order = sorted(position for position in positions if position is not None)
                number = (dive_round - 1) * len(order) + order.index(diver_position) + 1
                if 1 <= number <= total:
                    dive_number = number

        key = (str(payload.get("competition", "")), feed_time(payload.get("startDate")), event_id)
        return cls(key, name, feed_time(event.get("startTime")), feed_time(event.get("endTime")),
                   finished, progress, note, total, dive_number, action == "dive", action == "awards")


def read_progress(
    event: dict, finished: bool, action: object, dive_round: int | None, diver_position: int | None
) -> tuple[int | None, int | None, str]:
    if integer(event.get("divesPerRound", 1)) != 1:
        return None, None, "Pacing needs one dive per start-list entry per round."

    results = event.get("results")
    rounds, current_round = integer(event.get("rounds")), integer(event.get("round"))
    if (rounds is None or rounds < 1 or not isinstance(results, list)
            or not all(isinstance(row, dict) for row in results)):
        return None, None, "Waiting for DiveCalc round and start-list information."

    # DNS entries never dive; the snapshot cannot place a mid-event withdrawal in a round.
    active = [row for row in results if row.get("result") != "DNS"]
    if any(row.get("result") in ("DNF", "DQ") for row in active):
        return None, None, "Pacing unavailable after a withdrawal or disqualification."

    total = rounds * len(active)
    if not total:
        return None, None, "Waiting for start-list entries."
    if finished:
        return total, total, ""
    if (current_round is None or not 1 <= current_round <= rounds
            or any(not isinstance(row.get("pending"), bool) for row in active)):
        return None, total, "Waiting for DiveCalc to report dive progress."

    # Normally each pending flag says whether that competitor still has to dive
    # in event.round. Earlier rounds are already complete.
    pending = sum(row["pending"] for row in active)
    if pending == 0 and current_round > 1:
        # At rollover, event.round can already name the new round while the flags
        # still say "all done" from the old one. This can persist through the
        # first Present Dive of the new round. Count only the earlier rounds.
        if action == "awards" and dive_round == current_round - 1:
            return (current_round - 1) * len(active), total, ""
        if action == "dive" and dive_round == current_round and diver_position is not None:
            positions = [position for row in active if (position := integer(row.get("position"))) is not None]
            if len(positions) == len(active) and diver_position == min(positions):
                return (current_round - 1) * len(active), total, ""

    return current_round * len(active) - pending, total, ""


# Timing model: feed progress can change at Accept Awards, but the live timer
# follows Next Diver. The final Accept Awards ends the last timing interval.
@dataclass
class Pacing:
    event: Snapshot | None = None
    manual_start: float | None = None
    finished_at: float | None = None

    current_dive: int = 0
    current_since: float | None = None
    dive_budget: float | None = None

    last_dive_duration: float | None = None
    timed_dives: int = 0
    timed_seconds: float = 0

    def update(self, event: Snapshot, received_at: float) -> None:
        previous = self.event
        if previous is None or event.key != previous.key:
            # Timing samples and the manual start belong to one event only.
            self.manual_start = self.finished_at = None
            self.current_dive = self.timed_dives = 0
            self.timed_seconds = 0
            self.current_since = self.last_dive_duration = self.dive_budget = None
            previous = None

        # Browsing the same event after it finishes must not restart the timer.
        if previous is not None and previous.finished:
            return
        self.event = event
        if self.finished_at is not None:
            return

        number, total = event.dive_number, event.total_dives
        # The last awards can confirm completion before the finished flag arrives.
        final_awards = (event.is_awards and total is not None and number == total
                        and (event.finished or event.progress == (total, total)))
        if event.finished or final_awards:
            if final_awards and self.current_dive == number:
                self.record_dive(received_at)
            if previous is not None:
                self.finished_at = received_at
            self.current_since = None
            return

        if event.is_next and number is not None and total is not None and number > self.current_dive:
            # Next Diver and a manual Present Dive use the same feed action.
            # Check progress when available; without it, allow only the next number.
            if event.progress is not None and event.progress[0] != number - 1:
                return
            if event.progress is None and number != self.current_dive + 1:
                return

            if number == self.current_dive + 1:
                self.record_dive(received_at)
            else:
                # If we joined late or missed a transition, don't time several dives as one.
                self.last_dive_duration = None

            self.current_dive, self.current_since = number, received_at
            # Freeze Required at Next Diver, including the dive just started.
            # Accept Awards must not change this dive's budget or warning threshold.
            self.dive_budget = ((event.end - received_at) / (total - number + 1)
                                if event.end is not None and event.end > received_at else None)

    def record_dive(self, received_at: float) -> None:
        start = self.current_since
        if start is not None and received_at > start:
            self.last_dive_duration = received_at - start
            self.timed_seconds += self.last_dive_duration
            self.timed_dives += 1

    @property
    def start(self) -> float | None:
        # The event start label is separate from dwell times measured between feed actions.
        if self.manual_start is not None:
            return self.manual_start
        return self.event.start if self.event else None

    def required_pace(self, now: float) -> float | None:
        if self.event is None or self.event.finished or self.finished_at is not None:
            return None
        if self.event.end is None or now >= self.event.end:
            return None
        return self.dive_budget

    def current_elapsed(self, now: float) -> float | None:
        return max(0, now - self.current_since) if self.current_since is not None else None

    @property
    def can_set_start(self) -> bool:
        return (self.event is not None and not self.event.finished and self.manual_start is None
                and self.finished_at is None and self.current_dive == 0
                and (self.event.progress is None or self.event.progress[0] == 0))

    def set_start(self, now: float) -> None:
        if self.can_set_start:
            self.manual_start = now

    def forecast(self, now: float) -> tuple[float | None, float | None]:
        pace = self.timed_seconds / self.timed_dives if self.timed_dives else None
        if self.event is None or self.event.finished or self.current_since is None or pace is None:
            return pace, None
        total = self.event.total_dives
        if total is None or self.current_dive > total:
            return pace, None

        # Estimate the end of the current dive first, then add a full average
        # for each later dive. An overlong dive can't finish in the past.
        finish = max(now, self.current_since + pace) + (total - self.current_dive) * pace
        return pace, finish


def dive_timer_color(elapsed: float | None, required: float | None, *, overdue: bool) -> str:
    if elapsed is None:
        return ""
    if overdue or (required is not None and elapsed > required):
        return "#a62020"
    if required is not None and elapsed >= required - 5:
        return "#226b35"
    return ""


def target_status(finish: float | None, end: float, early: float, late: float, *, now: float) -> tuple[str, str]:
    # Tolerance applies to the forecast, not to an actual missed deadline.
    if now >= end:
        return "Over schedule", "#a62020"
    if finish is None:
        return "", ""
    if finish < end - early * 60:
        return "Running early", "#145a8d"
    if finish > end + late * 60:
        return "Running late", "#a62020"
    return "On target", "#226b35"


def clock(value: float | None) -> str:
    if value is None:
        return "--"
    try:
        current = datetime.fromtimestamp(value)
    except (ValueError, OverflowError, OSError):
        return "Outside clock range"
    pattern = "%H:%M:%S" if current.date() == datetime.now().date() else "%d %b %H:%M:%S"
    return current.strftime(pattern)


def duration(seconds: float) -> str:
    minutes, seconds_left = divmod(math.ceil(abs(seconds)), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02}:{minutes:02}:{seconds_left:02}"


# HTTP runs in a worker; only Tk's main thread updates the timing model and UI.
class FeedServer(HTTPServer):
    def __init__(self, address: tuple[str, int]) -> None:
        self.inbox: Queue[tuple[Snapshot, float]] = Queue(maxsize=256)
        super().__init__(address, FeedHandler)


class FeedHandler(BaseHTTPRequestHandler):
    def setup(self) -> None:
        self.request.settimeout(2)
        super().setup()

    def do_POST(self) -> None:
        if self.path != FEED_PATH:
            self.send_error(404, "Use /divecalc")
            return

        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self.send_error(411, "Content-Length required")
            return
        if not 0 < length <= MAX_BODY:
            self.send_error(413, "Invalid feed body size")
            return

        try:
            body = self.rfile.read(length)
            if len(body) != length:
                self.send_error(400, "Incomplete feed body")
                return
            # DiveCalc can send raw JSON with a form content type.
            snapshot = Snapshot.parse(json.loads(body))
        except TimeoutError:
            self.send_error(408, "Timed out reading feed body")
            return
        except (ValueError, RecursionError):
            self.send_error(400, "Invalid DiveCalc snapshot")
            return

        server = self.server
        assert isinstance(server, FeedServer)
        try:
            # Timestamp on receipt, not at the next window refresh.
            server.inbox.put_nowait((snapshot, time.time()))
        except Full:
            self.send_error(503, "Pacing monitor is busy")
            return

        self.send_response_only(200)
        self.send_header("Content-Length", "0")
        self.end_headers()


def run_window(server: FeedServer, early: float, late: float) -> None:
    import tkinter as tk
    from tkinter import ttk

    state = Pacing()
    root = tk.Tk()
    root.title("Competition pacing")
    root.columnconfigure(0, weight=1)
    panel = ttk.Frame(root, padding=18)
    panel.grid(sticky="nsew")
    panel.columnconfigure(0, weight=1)

    event_title = ttk.Label(panel, text="Waiting for DiveCalc", font=("Segoe UI", 15, "bold"), wraplength=480)
    event_title.grid(sticky="w")

    timer_caption = ttk.Label(panel, text="Current dive")
    timer_caption.grid(sticky="w", pady=(8, 0))
    dive_timer = ttk.Label(panel, text="--:--:--", font=("Segoe UI", 26, "bold"))
    dive_timer.grid(sticky="w")
    schedule = ttk.Label(panel)
    schedule.grid(sticky="w")

    eta = ttk.Label(panel, text="Estimated finish: --", font=("Segoe UI", 18, "bold"))
    eta.grid(sticky="w", pady=(12, 0))
    detail = ttk.Label(panel, wraplength=480)
    detail.grid(sticky="w")

    dive_times = ttk.Frame(panel)
    dive_times.grid(sticky="w", pady=(8, 0))
    ttk.Label(dive_times, text="Time per dive").grid(row=0, columnspan=2, sticky="w")
    time_font = ("Segoe UI", 12)
    time_values = []
    for row, name in enumerate(("Required", "Average", "Last dive"), start=1):
        ttk.Label(dive_times, text=name, font=time_font).grid(row=row, column=0, sticky="w", padx=(0, 16))
        value_label = ttk.Label(dive_times, text="--", font=time_font)
        value_label.grid(row=row, column=1, sticky="e")
        time_values.append(value_label)

    start_label = ttk.Label(panel)
    start_label.grid(sticky="w", pady=(12, 0))
    button = ttk.Button(panel, text="Set Start Time", command=lambda: state.set_start(time.time()))
    button.grid(sticky="w", pady=(4, 12))

    host, port = server.server_address[:2]
    ttk.Label(panel, text=f"Listening on {host}:{port}{FEED_PATH} | Target: -{early:g} / +{late:g} min").grid(sticky="w")

    def refresh() -> None:
        # Apply queued actions in order. Bound this batch so a busy feed can't
        # keep the GUI from repainting and handling clicks.
        for _ in range(server.inbox.maxsize):
            try:
                snapshot, received_at = server.inbox.get_nowait()
            except Empty:
                break
            state.update(snapshot, received_at)

        now = time.time()
        event = state.event
        button.state(["!disabled"] if state.can_set_start else ["disabled"])
        if event:
            event_title.configure(text=event.name)
            schedule.configure(text=f"Scheduled end: {clock(event.end)}" if event.end is not None
                               else "Scheduled end not provided by DiveCalc.")

            # The live elapsed time and deadline status can change without a new message.
            done = event.finished or state.finished_at is not None
            elapsed, required = state.current_elapsed(now), state.required_pace(now)
            overdue = not done and event.end is not None and now >= event.end
            timer_caption.configure(text=f"Current dive {state.current_dive} / {event.total_dives}"
                                    if elapsed is not None and event.total_dives is not None else "Current dive")
            timer_text = duration(math.floor(elapsed)) if elapsed is not None else "--:--:--"
            dive_timer.configure(text="Event finished" if done else timer_text,
                                 foreground=dive_timer_color(elapsed, required, overdue=overdue))

            start_source = "manual" if state.manual_start is not None else "DiveCalc schedule"
            start_label.configure(text=f"Start: {clock(state.start)} ({start_source})" if state.start is not None
                                  else "Event start not provided by DiveCalc.")

            pace, finish = state.forecast(now)
            note, color = event.progress_note, ""
            if done:
                summary = f"Finish observed: {clock(state.finished_at)}" if state.finished_at is not None else "Already finished"
                note = ""
            elif finish is None:
                summary = "Estimated finish: --"
                if event.progress and event.progress[0] == event.progress[1]:
                    note = "Waiting for DiveCalc to confirm the finish."
                elif not note:
                    note = ("Waiting for a second Next Diver to measure pace." if elapsed is not None
                            else "Waiting for Next Diver.")
            else:
                summary = f"Estimated finish: {clock(finish)}"

            if not done and event.end is not None:
                status, color = target_status(finish, event.end, early, late, now=now)
                if status:
                    note = f"{status} | {note}" if note else status
            if event.progress and not done:
                completed, total = event.progress
                progress = f"{completed} / {total} dives"
                note = f"{progress} | {note}" if note else progress

            for label, value in zip(time_values, (required, pace, state.last_dive_duration)):
                label.configure(text=duration(value) if value is not None else "--")
            if overdue:
                time_values[0].configure(text="Missed deadline")

            eta.configure(text=summary, foreground=color)
            detail.configure(text=note, foreground=color)

        root.after(250, refresh)

    refresh()
    root.mainloop()


# Command-line options and application lifecycle.
def nonnegative_minutes(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError("enter a non-negative number of minutes") from None
    if not math.isfinite(value) or value < 0:
        raise argparse.ArgumentTypeError("enter a non-negative number of minutes")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind", default="127.0.0.1", help="local address to listen on (default: %(default)s)")
    parser.add_argument("--port", type=int, default=8766, help="HTTP port (default: %(default)s)")
    parser.add_argument("--early-minutes", type=nonnegative_minutes, default=5, help="early tolerance (default: %(default)s)")
    parser.add_argument("--late-minutes", type=nonnegative_minutes, default=2, help="late tolerance (default: %(default)s)")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")

    try:
        server = FeedServer((args.bind, args.port))
    except OSError as exc:
        parser.exit(1, f"Could not listen on {args.bind}:{args.port}: {exc}\n")

    with server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            run_window(server, args.early_minutes, args.late_minutes)
        finally:
            server.shutdown()
            thread.join()


if __name__ == "__main__":
    main()
