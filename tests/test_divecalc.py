import http.client
import json
import socket
import unittest

from datatypes import DivePhase
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
        for penalty, maximum, expected in [("2", "10", "Restarted (-2 points)"), ("0", "0", "Failed Dive"), ("0", "4", "Max 4 points"), ("1", "10", "Penalty (-1 points)")]:
            dive.update(penalty=penalty, maxAward=maximum, result="87.75")
            update = adapt_payload(payload)[0]
            self.assertEqual((update.penalty_text, update.points), (expected, "87.75"))
        payload["action"] = "results"
        payload["event"]["results"][0].update(rank=None, result="DNS")
        self.assertEqual((adapt_payload(payload)[0].entries[0].rank, adapt_payload(payload)[0].entries[0].points), (0, "DNS"))

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

    def test_provisional_synchro_slots(self):
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
        self.assertEqual(warnings, ["Unsupported DiveCalc team event"])

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