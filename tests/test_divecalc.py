import http.client
import json
import socket
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from datatypes import DivePhase, EventType, RankingStatus
from divecalc_adapter import adapt_payload, parse_descriptions
from divecalc_receiver import DiveCalcReceiver, MAX_BODY
from update_mailbox import UpdateMailbox


def snapshot(action="awards"):
    return {
        "action": action, "competition": "Test Meet",
        "event": {"pk": 1, "type": "NORMAL", "name": "Final", "round": 2,
                  "rounds": 5, "divesPerRound": 1, "finished": False,
                  "judges": {"panels": [{"panel": "A", "judges": [{"position": index} for index in range(5)]}]},
                  "results": [{"position": 1, "rank": 1, "name": "\u0104sta", "team": "SSC", "result": "21.00"}]},
        "diver": {"position": 1, "rank": 1, "result": "21.00", "name": "\u0104sta", "team": "SSC",
                  "participants": [{"name": "\u0104sta", "team": "SSC"}],
                  "dive": {"position": 1, "dive": "101A", "height": "1", "dd": "1.4", "panel": "A",
                           "actualAwards": ["5.0", "5.5", "4.5", "4.0", "6.0"],
                           "penalty": "0", "maxAward": "10", "result": "21.00", "total": "21.00"}},
    }


class DiveCalcAdapterTests(unittest.TestCase):
    def test_event_type_is_preserved_in_dive_and_list_updates(self):
        for feed_type, expected in (("NORMAL", EventType.Individual),
                                    ("SYNCRO", EventType.Synchro),
                                    ("TEAM", EventType.Team)):
            with self.subTest(feed_type=feed_type):
                payload = snapshot("startlist")
                payload["event"]["type"] = feed_type
                self.assertEqual(adapt_payload(payload)[0].event.event_type, expected)
        payload = snapshot()
        payload["event"]["type"] = "TEAM"
        payload["diver"]["dive"]["participants"] = [{"name": "First", "team": "AAA"}]
        dive, ranking = adapt_payload(payload)
        self.assertEqual((dive.event.event_type, ranking.event.event_type), (EventType.Team, EventType.Team))

    def test_awards_and_rankings(self):
        dive, ranking = adapt_payload(snapshot(), {"101": "Forward Dive"})
        self.assertEqual((dive.phase, dive.event.round_number, dive.description), (DivePhase.Awards, "1", "Forward Dive"))
        self.assertEqual(dive.awards[:5], ("5.0", "5.5", "4.5", "4.0", "6.0"))
        self.assertEqual((dive.points, dive.total, dive.judge_count), ("21.00", "21.00", 5))
        self.assertEqual((ranking.entries[0].diver, ranking.entries[0].is_guest), ("\u0104sta", False))

    def test_finished_upcoming_ignores_historical_awards(self):
        payload = snapshot("dive")
        payload["event"]["finished"] = True
        dive, ranking = adapt_payload(payload)
        self.assertTrue(dive.event.finished)
        self.assertTrue(ranking.event.finished)
        self.assertEqual(dive.phase, DivePhase.Upcoming)
        self.assertEqual(dive.awards, ("",) * 11)
        self.assertEqual(dive.judge_count, 5)

    def test_penalties_correction_and_results(self):
        payload = snapshot()
        dive = payload["diver"]["dive"]
        for penalty, maximum, expected in [("2", "10", "Restarted (-2 points)"), ("0", "0", "Failed Dive"), (0, 0, "Failed Dive"), (None, None, " "), ("", "", " "), ("0", "4", "Max 4 points"), ("1", "10", "Penalty (-1 points)")]:
            dive.update(penalty=penalty, maxAward=maximum, result="87.75")
            update = adapt_payload(payload)[0]
            self.assertEqual((update.penalty_text, update.points), (expected, "87.75"))
        payload["action"] = "results"
        payload["event"]["results"][0].update(rank=None, result="DNS")
        self.assertEqual((adapt_payload(payload)[0].entries[0].rank, adapt_payload(payload)[0].entries[0].points), (0, "DNS"))
        for status in ("DNS", "DNF", "DQ"):
            payload["event"]["results"][0].update(rank="", result=status)
            entry = adapt_payload(payload)[0].entries[0]
            self.assertEqual((entry.rank, entry.points), (0, status))
            self.assertEqual(entry.status, RankingStatus(status))
            self.assertFalse(entry.is_guest)

    def test_outside_competition_classification_does_not_include_pending_or_unknown_results(self):
        cases = [
            ({}, "37.80", True),
            ({"rank": 0}, "0.00", True),
            ({"rank": "0"}, "37.80", True),
            ({"pending": True}, "37.80", False),
            ({"pending": False}, "37.80", False),
            ({"pending": None}, "37.80", False),
            ({"rank": 1}, "37.80", False),
            ({"rank": "unknown"}, "37.80", False),
            ({}, "", False),
            ({}, None, False),
            ({}, "DNF", False),
            ({}, "DQ", False),
        ]
        for action in ("awards", "startlist", "results"):
            for fields, result, expected in cases:
                with self.subTest(action=action, fields=fields, result=result):
                    payload = snapshot(action)
                    row = payload["event"]["results"][0]
                    row.pop("rank")
                    row.update(fields, result=result)
                    entry = adapt_payload(payload)[-1].entries[0]
                    self.assertEqual(entry.is_guest, expected)
                    if expected:
                        self.assertEqual(entry.status, RankingStatus.Unranked)

    def test_status_banner_keeps_dive_points_and_original_awards(self):
        for action in ("awards", "dive"):
            for status in ("DNF", "DQ"):
                with self.subTest(action=action, status=status):
                    payload = snapshot(action)
                    payload["diver"].update(rank=0, result=status)
                    payload["diver"]["dive"].update(result="26.40", total="118.80",
                                                   effectiveAwards=["0.0"] * 5)
                    payload["event"]["results"][0].update(rank=None, result=status)
                    dive, ranking = adapt_payload(payload)
                    self.assertEqual((dive.total, dive.rank), (status, ""))
                    self.assertEqual(dive.event.finished, False)
                    self.assertEqual((ranking.entries[0].status, ranking.entries[0].is_guest),
                                     (RankingStatus(status), False))
                    self.assertEqual(dive.points, "26.40" if action == "awards" else "")
                    self.assertEqual(dive.awards[:5], tuple(payload["diver"]["dive"]["actualAwards"])
                                     if action == "awards" else ("",) * 5)

    def test_synchro_penalties_identify_affected_divers(self):
        payload = snapshot()
        payload["event"]["type"] = "SYNCRO"
        payload["diver"]["participants"].append({"name": "Second", "team": "BBB"})
        types = ["A", "A", "B", "B"] + ["SYNCRO"] * 5
        payload["event"]["judges"]["panels"][0]["judges"] = [
            {"type": judge_type, "position": index} for index, judge_type in enumerate(types)
        ]
        dive = payload["diver"]["dive"]
        dive.update(actualAwards=["7.0"] * 9, effectiveAwards=["4.5"] * 4 + ["7.0"] * 5)
        cases = [
            ("2.0", "0.0", "10", "10", "A: Restarted (-2 points)"),
            ("0.0", "2.0", "10", "10", "B: Restarted (-2 points)"),
            ("0.0", "0.0", "4.5", "4.5", "A/B: Arm position (Max 4\u00bd points)"),
            ("2.0", "0.0", "10", "4.5", "A: Restarted (-2 points); B: Arm position (Max 4\u00bd points)"),
            ("0.0", "0.0", "0.0", "10", "A: Failed Dive"),
            ("0.0", "0.0", "10", "10", " "),
        ]
        for penalty_a, penalty_b, maximum_a, maximum_b, expected in cases:
            with self.subTest(expected=expected):
                dive.update(penaltyA=penalty_a, penaltyB=penalty_b,
                            maxAwardA=maximum_a, maxAwardB=maximum_b)
                warnings = []
                update = adapt_payload(payload, warn=warnings.append)[0]
                self.assertEqual(update.penalty_text, expected)
                self.assertEqual(update.awards, ("7.0",) * 4 + ("",) * 2 + ("7.0",) * 5)
                self.assertEqual(warnings, [])

    def test_failed_dive_preserves_original_marks_and_supplied_zero_score(self):
        payload = snapshot()
        payload["diver"]["dive"].update(maxAward="0.0", result="0.00", total="29.40",
                                       effectiveAwards=["0.0"] * 5)
        dive = adapt_payload(payload)[0]
        self.assertEqual((dive.penalty_text, dive.points, dive.total), ("Failed Dive", "0.00", "29.40"))
        self.assertEqual(dive.awards[:5], tuple(payload["diver"]["dive"]["actualAwards"]))

    def test_synchro_ranking_club_falls_back_to_participants(self):
        payload = snapshot("results")
        payload["event"]["type"] = "SYNCRO"
        row = payload["event"]["results"][0]
        row.update(nationality="LTU", participants=[{"team": "AAA"}, {"team": "BBB"}])
        for team, expected in ((None, "AAA/BBB"), ("", "AAA/BBB"), ("PAIR", "PAIR")):
            with self.subTest(team=team):
                row["team"] = team
                self.assertEqual(adapt_payload(payload)[0].entries[0].club_code, expected)

    def test_presentation_actions_do_not_produce_dive_or_ranking_updates(self):
        for action in ("event", "judges"):
            with self.subTest(action=action):
                warnings = []
                self.assertEqual(adapt_payload(snapshot(action), warn=warnings.append), [])
                self.assertEqual(warnings, [])

    def test_invalid_and_multiple_dives_per_round_are_ignored(self):
        warnings = []
        payload = snapshot()
        payload["event"]["type"] = "TEAM"
        payload["event"]["divesPerRound"] = 2
        self.assertEqual(adapt_payload(payload, warn=warnings.append), [])
        payload = snapshot()
        del payload["diver"]["dive"]["dive"]
        self.assertEqual(adapt_payload(payload, warn=warnings.append), [])
        self.assertEqual(len(warnings), 2)

    def test_team_dive_uses_current_participants_and_team_rankings(self):
        payload = snapshot()
        payload["event"].update(type="TEAM", round=2)
        payload["event"]["results"][0].update(name="Test Team", team=None, nationality="LTU")
        payload["diver"].update(name="Test Team", team=None, nationality="LTU")
        payload["diver"]["participants"] = [{"name": "First", "team": "AAA"}, {"name": "Second", "team": "BBB"}]
        payload["diver"]["dive"]["participants"] = [{"name": "Second", "team": "BBB"}]
        dive, ranking = adapt_payload(payload)
        self.assertEqual((dive.banner_name, dive.diver1_name, dive.team1_code), ("Second", "Second", "BBB"))
        self.assertEqual((dive.event.round_number, dive.total), ("1", "21.00"))
        self.assertEqual((ranking.entries[0].diver, ranking.entries[0].club_code), ("Test Team", "LTU"))

    def test_team_list_uses_participant_clubs(self):
        for action in ("startlist", "results"):
            for clubs, expected in ((["AAA", "BBB"], "AAA/BBB"),
                                    (["AAA", "AAA"], "AAA/AAA"),
                                    (["AAA", ""], "AAA"),
                                    (["AAA", "BBB", "CCC", "DDD"], "AAA/BBB/CCC/DDD"),
                                    (["", ""], "LTU")):
                with self.subTest(action=action, clubs=clubs):
                    payload = snapshot(action)
                    payload["event"]["type"] = "TEAM"
                    row = payload["event"]["results"][0]
                    row.update(team=None, nationality="LTU",
                               participants=[{"team": club} for club in clubs])
                    self.assertEqual(adapt_payload(payload)[0].entries[0].club_code, expected)

    def test_team_list_prefers_participant_clubs_then_entry_team(self):
        payload = snapshot("results")
        payload["event"]["type"] = "TEAM"
        row = payload["event"]["results"][0]
        row.update(team="TEAM", nationality="LTU", participants=[{"team": "AAA"}, {"team": "BBB"}])
        self.assertEqual(adapt_payload(payload)[0].entries[0].club_code, "AAA/BBB")
        row["participants"] = []
        self.assertEqual(adapt_payload(payload)[0].entries[0].club_code, "TEAM")

    def test_team_pair_preserves_ordinary_award_slots(self):
        payload = snapshot()
        payload["event"].update(type="TEAM", finished=True)
        payload["diver"]["dive"]["participants"] = [{"name": "First", "team": "AAA"}, {"name": "Second", "team": "BBB"}]
        warnings = []
        dive, ranking = adapt_payload(payload, warn=warnings.append)
        self.assertEqual(dive.banner_name, "First + Second")
        self.assertFalse(dive.synchro)
        self.assertEqual(dive.awards[:5], ("5.0", "5.5", "4.5", "4.0", "6.0"))
        self.assertTrue(dive.event.finished)
        self.assertTrue(ranking.event.finished)
        self.assertEqual(warnings, [])

    def test_short_names_for_team_and_synchro(self):
        for event_type in ("TEAM", "SYNCRO"):
            with self.subTest(event_type=event_type):
                payload = snapshot()
                payload["event"]["type"] = event_type
                payload["event"]["results"][0].update(name="Full pair", shortName="A. First/B. Second")
                participants = [{"name": "Alice First", "shortName": "A. First", "team": "AAA"},
                                {"name": "Bob Second", "shortName": "B. Second", "team": "BBB"}]
                payload["diver"]["participants"] = participants
                payload["diver"]["dive"]["participants"] = participants
                dive, ranking = adapt_payload(payload)
                self.assertIn("A. First + B. Second", dive.banner_name)
                self.assertEqual(dive.banner_name, "A. First + B. Second AAA/BBB" if event_type == "SYNCRO" else "A. First + B. Second")
                self.assertEqual((dive.team1_code, dive.team2_code), ("AAA", "BBB" if event_type == "SYNCRO" else ""))
                self.assertEqual(ranking.entries[0].diver, "A. First/B. Second")
                del participants[1]["shortName"]
                payload["event"]["results"][0]["shortName"] = "  "
                dive, ranking = adapt_payload(payload)
                self.assertIn("A. First + Bob Second", dive.banner_name)
                self.assertEqual(ranking.entries[0].diver, "Full pair")

    def test_individual_keeps_full_name(self):
        payload = snapshot()
        payload["diver"]["participants"][0]["shortName"] = "A."
        payload["event"]["results"][0]["shortName"] = "A."
        dive, ranking = adapt_payload(payload)
        self.assertIn("\u0104sta", dive.banner_name)
        self.assertEqual(ranking.entries[0].diver, "\u0104sta")

    def test_team_upcoming_correction_and_startlist(self):
        payload = snapshot("dive")
        payload["event"].update(type="TEAM", round=3)
        payload["event"]["results"][0].update(name="Test Team", team=None, nationality="LTU", rank=None, result="")
        payload["diver"].update(name="Test Team", team=None, result="42.00")
        payload["diver"]["dive"].update(position=2, participants=[{"name": "Second", "team": "BBB"}])
        dive, ranking = adapt_payload(payload)
        self.assertEqual((dive.phase, dive.banner_name, dive.total, dive.event.round_number),
                         (DivePhase.Upcoming, "Second", "42.00", "2"))
        self.assertEqual(dive.awards, ("",) * 11)
        self.assertEqual((ranking.entries[0].rank, ranking.entries[0].diver), (0, "Test Team"))
        payload["action"] = "awards"
        payload["diver"]["dive"].update(result="33.25", total="75.25")
        dive, _ = adapt_payload(payload)
        self.assertEqual((dive.points, dive.total), ("33.25", "75.25"))
        payload["action"] = "startlist"
        del payload["diver"]
        self.assertEqual(adapt_payload(payload)[0].entries[0].club_code, "LTU")

    def test_team_dive_requires_active_participants(self):
        payload = snapshot()
        payload["event"]["type"] = "TEAM"
        warnings = []
        self.assertEqual(adapt_payload(payload, warn=warnings.append), [])
        self.assertEqual(warnings, ["Invalid DiveCalc snapshot"])

    def test_team_with_typed_or_unsupported_judges_is_ignored(self):
        for judges in ([{"type": "SYNCRO"}] * 5, [{}] * 9):
            payload = snapshot()
            payload["event"]["type"] = "TEAM"
            payload["diver"]["dive"]["participants"] = [{"name": "First", "team": "AAA"}, {"name": "Second", "team": "BBB"}]
            payload["event"]["judges"]["panels"][0]["judges"] = judges
            warnings = []
            self.assertEqual(adapt_payload(payload, warn=warnings.append), [])
            self.assertEqual(warnings, ["Unsupported DiveCalc team judge layout"])

    def test_team_supported_panel_sizes(self):
        for count in (3, 5, 7):
            with self.subTest(count=count):
                payload = snapshot()
                payload["event"]["type"] = "TEAM"
                payload["diver"]["dive"]["participants"] = [{"name": "First"}, {"name": "Second"}]
                payload["event"]["judges"]["panels"][0]["judges"] = [{} for _ in range(count)]
                payload["diver"]["dive"]["actualAwards"] = [str(index) for index in range(count)]
                warnings = []
                dive, _ = adapt_payload(payload, warn=warnings.append)
                self.assertEqual((dive.judge_count, dive.awards[:count]), (count, tuple(str(index) for index in range(count))))
                self.assertEqual(warnings, [])

    def test_team_unsupported_awards_and_participant_count(self):
        for participants, awards in (([{"name": "First"}], ["5.0"] * 4),
                                     ([{"name": "First"}, {"name": "Second"}, {"name": "Third"}], ["5.0"] * 5)):
            with self.subTest(participants=participants, awards=awards):
                payload = snapshot()
                payload["event"]["type"] = "TEAM"
                payload["diver"]["dive"].update(participants=participants, actualAwards=awards)
                warnings = []
                self.assertEqual(adapt_payload(payload, warn=warnings.append), [])
                self.assertEqual(warnings, ["Unsupported DiveCalc team judge layout"])

    def test_description_parser(self):
        warnings = []
        result = parse_descriptions("# comment\n101,Forward, dive\ninvalid\n203,\u0104\n", warnings.append)
        self.assertEqual(result, {"101": "Forward, dive", "203": "\u0104"})
        self.assertEqual(len(warnings), 1)

    def test_synchro_slots(self):
        for execution_count, synchro_count in ((4, 5), (6, 5)):
            payload = snapshot()
            payload["event"]["type"] = "SYNCRO"
            payload["diver"]["participants"].append({"name": "Second", "team": "KPM"})
            judges = ([{"type": "A", "position": index} for index in range(execution_count // 2)] +
                      [{"type": "B", "position": index} for index in range(execution_count // 2)] +
                      [{"type": "SYNCRO", "position": index} for index in range(synchro_count)])
            payload["event"]["judges"]["panels"][0]["judges"] = judges
            payload["diver"]["dive"]["actualAwards"] = [str(index) for index in range(len(judges))]
            update = adapt_payload(payload)[0]
            self.assertEqual(update.judge_count, execution_count + synchro_count)
            self.assertEqual(update.awards[:execution_count], tuple(str(index) for index in range(execution_count)))
            self.assertEqual(update.awards[6:], tuple(str(index) for index in range(execution_count, len(judges))))

    def test_missing_synchro_types_warns_and_falls_back(self):
        payload = snapshot()
        payload["event"]["type"] = "SYNCRO"
        payload["diver"]["participants"].append({"name": "Second", "team": "KPM"})
        warnings = []
        update = adapt_payload(payload, warn=warnings.append)[0]
        self.assertEqual(update.awards[:5], tuple(payload["diver"]["dive"]["actualAwards"]))
        self.assertTrue(warnings)


class MailboxTests(unittest.TestCase):
    def test_order_overflow_and_invalidation(self):
        mailbox = UpdateMailbox(2)
        for value in (1, 2, 3):
            self.assertTrue(mailbox.publish(value, 0))
        self.assertEqual(mailbox.drain(), ([2, 3], 1))
        token = mailbox.new_token()
        self.assertFalse(mailbox.publish(4, 0))
        self.assertTrue(mailbox.publish(5, token))
        self.assertEqual(mailbox.drain(), ([5], 0))


class ReceiverTests(unittest.TestCase):
    def setUp(self):
        self.mailbox = UpdateMailbox()
        self.receiver = DiveCalcReceiver(self.mailbox, 0, port=0)

    def tearDown(self):
        if self.receiver:
            self.receiver.stop()

    def request(self, method="POST", path="/divecalc", body=b"{}", headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.receiver.port, timeout=2)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def test_valid_json_and_order(self):
        for action in ("awards", "dive"):
            body = json.dumps(snapshot(action)).encode("utf-8")
            self.assertEqual(self.request(body=body, headers={"Content-Type": "application/x-www-form-urlencoded"}), (200, b""))
        updates, dropped = self.mailbox.drain()
        self.assertEqual(dropped, 0)
        self.assertEqual([updates[0].phase, updates[2].phase], [DivePhase.Awards, DivePhase.Upcoming])

    def test_replay_route_is_opt_in_and_does_not_publish_overlays(self):
        path = "/divecalc-replay"
        payload = snapshot("judges")
        payload["event"]["startTime"] = 1795634400000
        body = json.dumps(payload).encode()
        self.assertEqual(self.request(path=path, body=body)[0], 404)
        with self.assertRaises(ValueError):
            self.receiver.configure_replay("/divecalc", 5)
        self.receiver.configure_replay(path, 5)
        self.assertEqual(self.request(path=path, body=b'{"action":"awards"}')[0], 400)
        self.assertEqual(self.request(body=body)[0], 200)
        self.assertFalse(self.receiver.take_replay_request())
        self.assertEqual(len(self.mailbox.drain()[0]), 1)
        self.assertEqual(self.request(path=path, body=body)[0], 200)
        self.assertTrue(self.receiver.take_replay_request())
        self.assertFalse(self.receiver.take_replay_request())
        self.assertEqual(self.mailbox.drain(), ([], 0))
        self.receiver.server.allowed_ip = "192.0.2.1"
        self.assertEqual(self.request(path=path, body=body)[0], 403)

    def test_replay_cooldown_drops_repeats_without_extending_window(self):
        path = "/divecalc-replay"
        self.receiver.configure_replay(path, 5)
        with patch("divecalc_receiver.monotonic", return_value=100) as clock:
            body = b'{"action":"judges"}'
            for now, expected in ((100, True), (104.9, False), (105, True)):
                clock.return_value = now
                self.assertEqual(self.request(path=path, body=body)[0], 200)
                self.assertIs(self.receiver.take_replay_request(), expected)

            clock.return_value = 110
            self.assertEqual(self.request(path=path, body=body)[0], 200)
            clock.return_value = 112
            self.assertFalse(self.receiver.take_replay_request())

            clock.return_value = 115
            self.assertEqual(self.request(path=path, body=body)[0], 200)
            self.receiver.configure_replay(None)
            self.assertFalse(self.receiver.take_replay_request())
            self.assertEqual(self.request(path=path, body=body)[0], 404)

    def test_event_start_is_published_from_any_action_independently_of_overlay_support(self):
        expected = datetime(2026, 11, 16, 20, 20, tzinfo=timezone.utc)
        for action in ("event", "judges", "dive", "awards", "startlist", "results", "other"):
            with self.subTest(action=action):
                payload = {"action": action, "event": {"startTime": expected.timestamp() * 1000}}
                self.assertEqual(self.request(body=json.dumps(payload).encode()), (200, b""))
                updates, dropped = self.mailbox.drain()
                self.assertEqual(dropped, 0)
                self.assertEqual(len(updates), 1)
                self.assertEqual(updates[0].start_time, expected)

    def test_invalid_start_time_warns_without_losing_overlay_updates(self):
        warnings = []
        self.receiver.server.warn = warnings.append
        for value in ("invalid", True, float("inf"), 10 ** 30):
            with self.subTest(value=value):
                payload = snapshot()
                payload["event"]["startTime"] = value
                self.assertEqual(self.request(body=json.dumps(payload).encode()), (200, b""))
                self.assertEqual(len(self.mailbox.drain()[0]), 2)
        self.assertEqual(warnings.count("Invalid DiveCalc event startTime"), 4)

    def test_ignored_presentation_actions_are_diagnosed_only_in_debug_mode(self):
        logs = []
        warnings = []
        receiver = self.receiver
        assert receiver is not None
        with patch.object(receiver.server, "log", logs.append), patch.object(receiver.server, "warn", warnings.append):
            for debug in (False, True):
                with patch.object(receiver.server, "debug", debug):
                    logs.clear()
                    for action in ("judges", "event"):
                        self.assertEqual(self.request(body=json.dumps(snapshot(action)).encode()), (200, b""))
                    self.assertEqual(self.mailbox.drain(), ([], 0))
                    self.assertEqual(warnings, [])
                    if debug:
                        self.assertEqual(len(logs), 2)
                        self.assertIn("action=judges", logs[0])
                        self.assertIn("action=event", logs[1])
                        self.assertTrue(all("ignored: presentation not supported" in message for message in logs))
                    else:
                        self.assertEqual(logs, [])

    def test_validation(self):
        self.assertEqual(self.request("GET")[0], 405)
        self.assertEqual(self.request("TRACE")[0], 405)
        self.assertEqual(self.request(path="/other")[0], 404)
        self.assertEqual(self.request(body=b"not json")[0], 400)
        self.assertEqual(self.request(body=b"[]")[0], 400)
        self.assertEqual(self.request(body=b"", headers={"Content-Length": str(MAX_BODY + 1)})[0], 413)
        self.receiver.server.allowed_ip = "192.0.2.1"
        self.assertEqual(self.request()[0], 403)

    def test_chunked_and_shutdown(self):
        body = json.dumps(snapshot("results")).encode()
        chunked = f"{len(body):X}\r\n".encode() + body + b"\r\n0\r\n\r\n"
        self.assertEqual(self.request(body=chunked, headers={"Transfer-Encoding": "chunked"})[0], 200)
        self.assertEqual(len(self.mailbox.drain()[0]), 1)
        port = self.receiver.port
        self.receiver.stop()
        self.receiver = None
        self.assertFalse(self.mailbox.publish("late", 0))
        with socket.socket() as sock:
            sock.bind(("0.0.0.0", port))

    def test_invalid_chunked_and_team_warning_deduplication(self):
        self.assertEqual(self.request(body=b"ZZ\r\n", headers={"Transfer-Encoding": "chunked"})[0], 400)
        warnings = []
        self.receiver.server.warn = warnings.append
        payload = snapshot()
        payload["event"]["type"] = "TEAM"
        payload["event"]["divesPerRound"] = 2
        for _ in range(2):
            self.assertEqual(self.request(body=json.dumps(payload).encode())[0], 200)
        self.assertEqual(warnings, ["Unsupported DiveCalc dives per round"])

    def test_team_layout_warning_is_once_per_event(self):
        warnings = []
        self.receiver.server.warn = warnings.append
        payload = snapshot()
        payload["event"]["type"] = "TEAM"
        payload["diver"]["dive"]["participants"] = [{"name": "First"}, {"name": "Second"}]
        payload["event"]["judges"]["panels"][0]["judges"][0]["type"] = "SYNCRO"
        for _ in range(2):
            self.assertEqual(self.request(body=json.dumps(payload).encode())[0], 200)
        self.assertEqual(warnings, ["Unsupported DiveCalc team judge layout"])