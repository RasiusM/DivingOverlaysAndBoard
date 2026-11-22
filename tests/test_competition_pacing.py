import http.client
import json
import unittest
from threading import Thread

from Utils.CompetitionPacing.competition_pacing import FeedServer, Pacing, Snapshot, dive_timer_color, target_status


START = 1_800_000_000


def feed(pending=(True, True), current_round=1, **event_fields):
    event = {
        "pk": 42, "name": "3m final", "round": current_round, "rounds": 2,
        "divesPerRound": 1, "finished": False, "startTime": START * 1000,
        "endTime": (START + 240) * 1000,
        "results": [{"pk": index, "position": index, "pending": value} for index, value in enumerate(pending, 1)],
    }
    return {"action": "awards", "competition": "Test Open", "event": event | event_fields}


def live(action, position, dive_round, pending, current_round=None, **event_fields):
    payload = feed(pending, current_round or dive_round, **event_fields)
    return payload | {"action": action, "diver": {"position": position, "dive": {"position": dive_round}}}


class CompetitionPacingTests(unittest.TestCase):
    def test_schedule_and_present_event_do_not_start_the_dive_timer(self):
        state = Pacing()
        snapshot = Snapshot.parse(feed() | {"action": "event"})
        state.update(snapshot, START)
        self.assertEqual((state.start, snapshot.end), (START, START + 240))
        state.set_start(START + 10)
        self.assertIsNone(state.current_elapsed(START + 20))
        state.update(Snapshot.parse(live("dive", 1, 1, (True, True))), START + 30)
        self.assertEqual(state.start, START + 10)
        self.assertEqual(state.current_elapsed(START + 35), 5)
        state.update(Snapshot.parse(feed(pk=43)), START + 245)
        self.assertIsNone(state.manual_start)
        self.assertIsNone(state.current_elapsed(START + 245))
        self.assertEqual(state.forecast(START + 245), (None, None))

    def test_required_pace_changes_only_on_next_diver_until_deadline(self):
        state = Pacing()
        state.update(Snapshot.parse(feed() | {"action": "event"}), START)
        self.assertIsNone(state.required_pace(START))
        state.update(Snapshot.parse(live("dive", 1, 1, (True, True))), START)
        self.assertEqual(state.required_pace(START), 60)
        self.assertEqual(state.required_pace(START + 70), 60)
        state.update(Snapshot.parse(live("awards", 1, 1, (False, True))), START + 90)
        self.assertEqual(state.required_pace(START + 90), 60)
        state.update(Snapshot.parse(live("dive", 2, 1, (False, True))), START + 90)
        self.assertEqual(state.required_pace(START + 90), 50)
        state.update(Snapshot.parse(live("dive", 2, 1, (False, True))), START + 110)
        self.assertEqual(state.required_pace(START + 110), 50)
        self.assertIsNone(state.required_pace(START + 240))

    def test_next_diver_times_each_cycle_and_final_awards_end_the_last(self):
        state = Pacing()
        for elapsed, payload, last, timer in (
            (10, live("dive", 1, 1, (True, True)), None, 0),
            (40, live("awards", 1, 1, (False, True)), None, 30),
            (60, live("dive", 2, 1, (False, True)), 50, 0),
            (65, live("dive", 2, 1, (False, True)), 50, 5),
            (70, live("dive", 1, 1, (False, True)), 50, 10),
            (95, live("awards", 2, 1, (False, False), current_round=2), 50, 35),
            (110, live("dive", 1, 2, (False, False)), 50, 0),
            (150, live("awards", 1, 2, (False, True)), 50, 40),
            (170, live("dive", 2, 2, (False, True)), 60, 0),
            (205, live("awards", 2, 2, (False, False), finished=True), 35, None),
            (220, live("awards", 2, 2, (False, False), finished=True), 35, None),
        ):
            with self.subTest(elapsed=elapsed):
                state.update(Snapshot.parse(payload), START + elapsed)
                self.assertEqual(state.last_dive_duration, last)
                self.assertEqual(state.current_elapsed(START + elapsed), timer)
        self.assertEqual(state.finished_at, START + 205)
        self.assertEqual(state.forecast(START + 230), (48.75, None))

    def test_joining_late_and_missing_next_diver_does_not_inflate_average(self):
        state = Pacing()
        state.update(Snapshot.parse(live("dive", 2, 1, (False, True))), START + 50)
        self.assertEqual(state.current_elapsed(START + 55), 5)
        state.update(Snapshot.parse(live("dive", 2, 2, (False, True))), START + 150)
        self.assertIsNone(state.last_dive_duration)
        self.assertEqual(state.forecast(START + 150), (None, None))

    def test_forecast_continues_after_deadline_or_when_end_is_missing(self):
        state = Pacing()
        state.update(Snapshot.parse(live("dive", 1, 1, (True, True))), START + 150)
        state.update(Snapshot.parse(live("dive", 2, 1, (False, True))), START + 170)
        self.assertEqual(state.forecast(START + 241), (20, START + 281))
        self.assertEqual(target_status(START + 281, START + 240, 5, 2, now=START + 241)[0], "Over schedule")
        state.update(Snapshot.parse(feed((False, True), endTime=None)), START + 242)
        self.assertEqual(state.forecast(START + 242), (20, START + 282))
        self.assertIsNone(state.required_pace(START + 242))

    def test_round_rollover_keeps_pace_when_pending_flags_lag(self):
        state = Pacing()
        for elapsed, action, round_number, dive_round, position, flags, expected in (
            (60, "awards", 1, 1, 2, (False, False, True), 2),
            (90, "awards", 2, 1, 3, (False, False, False), 3),
            (110, "dive", 2, 2, 1, (False, False, False), 3),
            (120, "awards", 2, 2, 1, (False, True, True), 4),
        ):
            with self.subTest(action=action, round=round_number, elapsed=elapsed):
                payload = feed(flags, round_number)
                payload.update(action=action, diver={"position": position, "dive": {"position": dive_round}})
                for row in payload["event"]["results"]:
                    row["position"] = row["pk"]
                payload["event"]["results"].reverse()  # Standings need not be in start order.
                snapshot = Snapshot.parse(payload)
                state.update(snapshot, START + elapsed)
                self.assertEqual(snapshot.progress, (expected, 6))
        self.assertEqual(state.current_elapsed(START + 120), 10)

    def test_no_invented_progress_for_unsupported_or_incomplete_rounds(self):
        for event_fields in (
            {"divesPerRound": 2},
            {"results": [{"pk": 1}]},
            {"results": [{"pk": 1, "pending": False, "result": "DNF"}]},
        ):
            with self.subTest(event_fields=event_fields):
                self.assertIsNone(Snapshot.parse(feed(**event_fields)).progress)
        self.assertEqual(Snapshot.parse(feed(results=[
            {"pk": 1, "pending": False}, {"pk": 2, "result": "DNS"},
        ])).progress, (1, 2))

    def test_dive_timer_green_window_and_overdue_priority(self):
        for elapsed, required, overdue, color in (
            (24.9, 30, False, ""),
            (25, 30, False, "#226b35"),
            (30, 30, False, "#226b35"),
            (30.1, 30, False, "#a62020"),
            (0, 4, False, "#226b35"),
            (25, 30, True, "#a62020"),
            (25, None, False, ""),
            (None, 30, False, ""),
        ):
            with self.subTest(elapsed=elapsed, required=required, overdue=overdue):
                self.assertEqual(dive_timer_color(elapsed, required, overdue=overdue), color)

    def test_schedule_tolerance_is_inclusive_and_configurable(self):
        for delta, expected in ((-301, "Running early"), (-300, "On target"),
                                (120, "On target"), (121, "Running late")):
            with self.subTest(delta=delta):
                self.assertEqual(target_status(START + delta, START, 5, 2, now=START - 600)[0], expected)
        self.assertEqual(target_status(START + 180, START, 5, 3, now=START - 1)[0], "On target")
        self.assertEqual(target_status(START + 1, START, 5, 3, now=START), ("Over schedule", "#a62020"))

    def test_divecalc_http_post_delivers_snapshot_without_requiring_json_content_type(self):
        with FeedServer(("127.0.0.1", 0)) as server:
            worker = Thread(target=server.serve_forever)
            worker.start()
            connection = http.client.HTTPConnection(*server.server_address, timeout=3)
            try:
                body = json.dumps(feed((False, True))).encode("utf-8")
                connection.request("POST", "/divecalc", body, {"Content-Type": "application/x-www-form-urlencoded"})
                response = connection.getresponse()
                self.assertEqual((response.status, response.read()), (200, b""))
                snapshot, received = server.inbox.get(timeout=3)
                self.assertEqual(snapshot.progress, (1, 4))
                self.assertGreater(received, 0)
                connection.request("POST", "/divecalc", b"{bad json")
                response = connection.getresponse()
                self.assertEqual(response.status, 400)
                response.read()
                self.assertTrue(server.inbox.empty())
            finally:
                connection.close()
                server.shutdown()
                worker.join()
