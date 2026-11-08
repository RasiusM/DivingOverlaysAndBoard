import unittest
from dataclasses import replace
import sys
from unittest.mock import MagicMock, mock_open, patch

from datatypes import DiveListRecord, DiveMessage, DivePhase
from diverecorder_adapter import adapt_dive, adapt_rankings

sys.modules.setdefault("obspython", MagicMock())

import overlay_controller
import overlay_data
import rankings
import state_controls
import diving_overlays
from enums import AwardsCommonGrp, DiveInfoGrp, EventMode, RankingsSrc, TVBannerGrp


def make_message(**values):
    fields = {name: "" for name in DiveMessage.__dataclass_fields__}
    fields.update(
        packet_id="REFEREE", event_ab="a", long_event_name="Test event",
        meet_title="Test meet", number_of_judges="5", synchro_event="False",
        d1_full_name_team="First Diver SSC", d1_first_name="First",
        d1_family_name="Diver", d1_team_code="SSC", start_no="2",
        round="1", rounds_in_event="5", divers_in_event="3",
    )
    fields.update(values)
    return DiveMessage(**fields)


class ScriptPropertiesTests(unittest.TestCase):
    def test_script_update_tracks_selected_source_before_transport_starts(self):
        settings = {"scoring_source": "divecalc", "divecalc_path": "/divecalc",
                    "divecalc_allowed_ip": "", "rootDir": "."}
        with patch.object(diving_overlays, "script_loaded", False), \
             patch.object(diving_overlays, "selected_scoring_source", "diverecorder"), \
             patch.object(diving_overlays, "dvov_script_update"), \
             patch.object(diving_overlays, "parse_descriptions", return_value={}), \
             patch("builtins.open", mock_open(read_data="")), \
             patch.object(diving_overlays.obs, "obs_data_get_string", side_effect=lambda data, key: data[key]), \
             patch.object(diving_overlays.obs, "obs_data_get_bool", return_value=True), \
             patch.object(diving_overlays.obs, "obs_data_get_int", return_value=8765):
            diving_overlays.script_update(settings)
            self.assertEqual(diving_overlays.selected_scoring_source, "divecalc")

    def test_scoring_source_controls_visibility_without_changing_settings(self):
        props = object()
        properties = {}
        callbacks = {}
        visibility = {}

        def add_property(parent, name, *args):
            self.assertIs(parent, props)
            properties[name] = name
            return name

        def set_callback(prop, callback):
            callbacks[prop] = callback

        settings = {"scoring_source": "divecalc", "divecalc_port": 9000,
                    "divecalc_path": "/custom", "divecalc_allowed_ip": "127.0.0.1",
                    "udp_polling_enabled": False}
        original_settings = settings.copy()
        with patch.object(diving_overlays, "selected_scoring_source", "divecalc"), \
             patch.object(diving_overlays, "dvov_script_properties"), \
             patch.multiple(
                 diving_overlays.obs,
                 obs_properties_create=MagicMock(return_value=props),
                 obs_properties_add_list=MagicMock(side_effect=add_property),
                 obs_properties_add_bool=MagicMock(side_effect=add_property),
                 obs_properties_add_int=MagicMock(side_effect=add_property),
                 obs_properties_add_text=MagicMock(side_effect=add_property),
                 obs_property_set_modified_callback=MagicMock(side_effect=set_callback),
                 obs_properties_get=MagicMock(side_effect=lambda parent, name: properties[name]),
                 obs_property_set_visible=MagicMock(side_effect=lambda prop, visible: visibility.update({prop: visible})),
                 obs_data_get_string=MagicMock(side_effect=lambda data, name: data[name]),
             ):
            self.assertIs(diving_overlays.script_properties(), props)
            self.assertEqual(visibility, {
                "udp_polling_enabled": False,
                "divecalc_port": True,
                "divecalc_path": True,
                "divecalc_allowed_ip": True,
            })
            callback = callbacks["scoring_source"]
            for source in ("divecalc", "diverecorder", "", "divecalc"):
                with self.subTest(source=source):
                    settings["scoring_source"] = source
                    self.assertTrue(callback(props, properties["scoring_source"], settings))
                    self.assertEqual(visibility, {
                        "udp_polling_enabled": source in ("diverecorder", ""),
                        "divecalc_port": source == "divecalc",
                        "divecalc_path": source == "divecalc",
                        "divecalc_allowed_ip": source == "divecalc",
                    })
            self.assertEqual(settings, original_settings)


class AdapterTests(unittest.TestCase):
    def test_upcoming_dive(self):
        update = adapt_dive(make_message(dive_no="103", pos_code="C", dd="1.6"))
        self.assertEqual(update.phase, DivePhase.Upcoming)
        self.assertEqual(update.banner_name, "First Diver SSC")
        self.assertEqual(update.event.slot, "a")
        self.assertEqual(update.event.round_number, "1")
        self.assertEqual(update.judge_count, 5)
        self.assertEqual(update.dive_number, "103")

    def test_awards_and_penalty(self):
        update = adapt_dive(make_message(j1="0", j2="5.5", penalty_code="2", total="42.00"))
        self.assertEqual(update.phase, DivePhase.Awards)
        self.assertEqual(update.awards[:2], ("0", "5.5"))
        self.assertEqual(len(update.awards), 11)
        self.assertEqual(update.penalty_text, "Restarted (-2 points)")
        self.assertEqual(update.total, "42.00")

    def test_synchro_names_and_event_b(self):
        update = adapt_dive(make_message(
            synchro_event="True", event_ab="b", d2_first_name="Second",
            d2_family_name="Diver", d2_team_code="LTU",
        ))
        self.assertTrue(update.synchro)
        self.assertEqual(update.banner_name, "First Diver + Second Diver SSC/LTU")
        self.assertEqual(update.diver2_name, "Second Diver - LTU")

    def test_guest_semantics_and_immutable_rankings(self):
        records = [
            DiveListRecord(1, "42", "", "First", 2, "SSC"),
            DiveListRecord(-2, "40", "", "Guest", 1, "LTU"),
            DiveListRecord(0, "", "", "Unranked", 3, "SSC"),
        ]
        update = adapt_rankings(records, make_message())
        records.clear()
        self.assertEqual([entry.rank for entry in update.entries], [1, 2, 0])
        self.assertEqual([entry.is_guest for entry in update.entries], [False, True, True])
        self.assertEqual(update.event.name, "Test event")


class ControllerTests(unittest.TestCase):
    def setUp(self):
        state_controls.event_ab_is_a = True
        state_controls.current_dive = None
        state_controls.event_complete = False
        state_controls.latest_dives.clear()
        state_controls.completed_slots.clear()
        state_controls.event_names.clear()

    def test_overlay_visibility_defaults_to_enabled(self):
        settings = object()
        with patch.object(state_controls.obs, "obs_data_set_default_int"), \
             patch.object(state_controls.obs, "obs_data_set_default_bool") as set_default:
            state_controls.dvov_state_script_defaults(settings)
            set_default.assert_called_once_with(settings, "overlays_enabled", True)

    def test_overlay_visibility_setting_is_shared_with_renderer(self):
        for enabled in (False, True):
            with self.subTest(enabled=enabled), \
                 patch.object(state_controls.obs, "obs_data_get_bool", side_effect=lambda settings, key: enabled if key == "overlays_enabled" else False), \
                 patch.object(state_controls.obs, "obs_data_get_int", return_value=5000), \
                 patch.object(state_controls, "overlays_enabled", True), \
                 patch.object(overlay_data, "overlays_enabled", True):
                state_controls.dvov_state_script_update(object())
                self.assertEqual(state_controls.overlays_enabled, enabled)
                self.assertEqual(overlay_data.overlays_enabled, enabled)

    def test_awards_visibility_follows_shared_setting(self):
        update = adapt_dive(make_message(j1="5"))
        for enabled in (False, True):
            with self.subTest(enabled=enabled), \
                 patch.object(state_controls, "overlays_enabled", enabled), \
                 patch.object(overlay_data, "overlays_enabled", enabled), \
                 patch.object(state_controls, "set_source_visibility") as state_visibility, \
                 patch.object(overlay_data, "set_source_visibility") as render_visibility, \
                 patch.object(state_controls, "set_source_string"), \
                 patch.object(state_controls, "set_color_source_alpha"), \
                 patch.object(overlay_data, "set_source_string"), \
                 patch.object(overlay_data, "set_source_file"):
                overlay_controller.apply_dive(update)
                self.assertEqual(
                    any(call.args == (TVBannerGrp.GroupName, True) for call in state_visibility.call_args_list),
                    enabled,
                )
                self.assertEqual(
                    any(call.args == (AwardsCommonGrp.GroupName, True) for call in render_visibility.call_args_list),
                    enabled,
                )

    def switch_event(self, is_a):
        with patch.object(state_controls, "dvov_act_set_event_ab") as set_ab, \
             patch.object(state_controls, "dvov_rank_set_event_ab"), \
             patch.object(state_controls, "remove_overlays"), \
             patch.object(state_controls, "set_color_source_alpha"), \
             patch.object(state_controls, "dvov_act_set_event_complete") as complete_text:
            state_controls.set_event_a(is_a)
        return set_ab, complete_text

    def test_selected_dive_is_applied_in_order(self):
        update = adapt_dive(make_message())
        with patch.multiple(overlay_controller, dvov_state_on_dive=MagicMock(),
                            dvov_act_render_dive=MagicMock(), dvov_state_set_event_complete=MagicMock()):
            overlay_controller.apply_dive(update)
            overlay_controller.dvov_state_on_dive.assert_called_once_with(update)
            overlay_controller.dvov_act_render_dive.assert_called_once_with(update)
            overlay_controller.dvov_state_set_event_complete.assert_not_called()

    def test_finished_dive_and_rankings_preserve_completion(self):
        dive = adapt_dive(make_message())
        finished_dive = replace(dive, event=replace(dive.event, finished=True))
        ranking = adapt_rankings([], make_message())
        ranking = replace(ranking, event=replace(ranking.event, finished=True))
        with patch.object(overlay_controller, "dvov_state_on_dive"), \
             patch.object(overlay_controller, "dvov_act_render_dive"), \
             patch.object(overlay_controller, "dvov_act_set_event_complete") as text, \
             patch.object(overlay_controller, "dvov_state_set_event_complete") as status, \
             patch.object(overlay_controller, "dvov_rank_set_divers"):
            overlay_controller.apply_rankings(ranking)
            overlay_controller.apply_dive(finished_dive)
            self.assertIn("a", state_controls.completed_slots)
            status.assert_called_once_with(True)
            self.assertEqual(text.call_count, 2)

    def test_other_event_cannot_change_display_or_completion(self):
        with patch.object(overlay_controller, "dvov_act_render_dive") as render, \
             patch.object(overlay_controller, "dvov_state_set_event_complete") as complete, \
             patch.object(overlay_controller, "dvov_rank_set_divers") as rank_update:
            overlay_controller.apply_dive(adapt_dive(make_message(event_ab="b")))
            overlay_controller.complete_event("b")
            overlay_controller.apply_rankings(adapt_rankings([], make_message(event_ab="b")))
            render.assert_not_called()
            complete.assert_not_called()
            rank_update.assert_not_called()

    def test_explicit_phase_controls_rendering(self):
        update = replace(adapt_dive(make_message(j1="5", rank="1")), phase=DivePhase.Upcoming)
        with patch.object(overlay_data, "set_source_string") as text, \
             patch.object(overlay_data, "set_source_file"), \
             patch.object(overlay_data, "set_source_visibility") as visibility:
            overlay_data.dvov_act_render_dive(update)
            visibility.assert_any_call(DiveInfoGrp.GroupName, True)
            visibility.assert_any_call(AwardsCommonGrp.GroupName, False)
            text.assert_any_call(TVBannerGrp.Position, "  2")

    def test_blank_description_displays_only_position(self):
        update = adapt_dive(make_message(pos_code="B", dive_description=""))
        with patch.object(overlay_data, "set_source_string") as text, \
             patch.object(overlay_data, "set_source_file"), \
             patch.object(overlay_data, "set_source_visibility"):
            overlay_data.dvov_act_render_dive(update)
            text.assert_any_call(DiveInfoGrp.Description, "Pike")

    def test_other_event_does_not_replace_redisplay_cache(self):
        selected = adapt_dive(make_message())
        state_controls.current_dive = selected
        state_controls.dvov_state_on_dive(adapt_dive(make_message(event_ab="b")))
        self.assertIs(state_controls.current_dive, selected)

    def test_event_switch_clears_redisplay_cache(self):
        state_controls.current_dive = adapt_dive(make_message())
        self.switch_event(False)
        self.assertIsNone(state_controls.current_dive)
        self.assertFalse(state_controls.event_ab_is_a)

    def test_event_switch_restores_each_slot_cache(self):
        dive_a = adapt_dive(make_message(start_no="1"))
        dive_b = adapt_dive(make_message(event_ab="b", start_no="2"))
        with patch.object(overlay_controller, "dvov_state_on_dive"), \
             patch.object(overlay_controller, "dvov_act_render_dive") as render:
            overlay_controller.apply_dive(dive_a)
            overlay_controller.apply_dive(dive_b)
            render.assert_called_once_with(dive_a)
        self.switch_event(False)
        self.assertIs(state_controls.current_dive, dive_b)
        self.switch_event(True)
        self.assertIs(state_controls.current_dive, dive_a)

    def test_completion_is_kept_per_slot(self):
        with patch.object(overlay_controller, "dvov_state_on_dive"), \
             patch.object(overlay_controller, "dvov_act_render_dive"), \
             patch.object(overlay_controller, "dvov_act_set_event_complete") as selected_text:
            overlay_controller.apply_dive(adapt_dive(make_message(event_ab="b", long_event_name="Event B")))
            overlay_controller.complete_event("b")
            selected_text.assert_not_called()
        self.assertFalse(state_controls.event_complete)

        set_ab, complete_text = self.switch_event(False)
        set_ab.assert_called_once_with(False, "Event B")
        complete_text.assert_called_once_with(True)
        self.assertTrue(state_controls.event_complete)

        _, complete_text = self.switch_event(True)
        complete_text.assert_not_called()
        self.assertFalse(state_controls.event_complete)

        # DiveRecorder reopens an event on REFEREE, even while it is inactive.
        with patch.object(overlay_controller, "dvov_act_render_dive"):
            overlay_controller.apply_dive(adapt_dive(make_message(event_ab="b")))
        self.switch_event(False)
        self.assertFalse(state_controls.event_complete)

    def test_completion_and_next_dive(self):
        with patch.object(overlay_controller, "dvov_act_set_event_complete") as complete_text, \
             patch.object(overlay_controller, "dvov_state_on_dive"), \
             patch.object(overlay_controller, "dvov_act_render_dive"):
            overlay_controller.complete_event("a")
            complete_text.assert_called_once_with(True)
            self.assertTrue(state_controls.event_complete)
            overlay_controller.apply_dive(adapt_dive(make_message()))
            self.assertFalse(state_controls.event_complete)

    def test_completion_from_rankings_without_rankings_display(self):
        update = adapt_rankings([], make_message(long_event_name="Final"))
        update = replace(update, event=replace(update.event, finished=True))
        with patch.object(overlay_controller, "dvov_act_set_event_complete") as text, \
             patch.object(overlay_controller, "dvov_state_set_event_complete") as status, \
             patch.object(overlay_controller, "dvov_rank_set_divers") as rank_update:
            overlay_controller.apply_rankings(update, show_rankings=False)
            text.assert_called_once_with(True, "Final")
            status.assert_called_once_with(True)
            rank_update.assert_not_called()

    def test_inactive_rankings_completion_restores_event_name(self):
        update = adapt_rankings([], make_message(event_ab="b", long_event_name="Final B"))
        update = replace(update, event=replace(update.event, finished=True))
        overlay_controller.apply_rankings(update)
        set_ab, text = self.switch_event(False)
        set_ab.assert_called_once_with(False, "Final B")
        text.assert_called_once_with(True)

    def test_redisplay_uses_normalized_cache(self):
        update = adapt_dive(make_message(j1="5"))
        state_controls.current_dive = update
        with patch.object(state_controls, "display_overlays"), \
             patch.object(state_controls, "display_tv_banner"), \
             patch.object(state_controls, "dvov_act_render_dive") as render:
            state_controls.redisplay_overlays(True)
            render.assert_called_once_with(update)

    def test_redisplay_restores_completion_text(self):
        state_controls.current_dive = adapt_dive(make_message())
        state_controls.event_complete = True
        with patch.object(state_controls, "display_overlays"), \
             patch.object(state_controls, "display_tv_banner"), \
             patch.object(state_controls, "dvov_act_render_dive"), \
             patch.object(state_controls, "dvov_act_set_event_complete") as text:
            state_controls.redisplay_overlays(True)
            text.assert_called_once_with(True)


class TransportTests(unittest.TestCase):
    def setUp(self):
        diving_overlays.mailbox = diving_overlays.UpdateMailbox()
        diving_overlays.transport_generation = 0
        diving_overlays.rankings_enabled = True
        diving_overlays.startup_reset_pending = False
        diving_overlays.startup_reset_attempts = 0

    def test_referee_packet_is_normalized_before_dispatch(self):
        message = make_message(j1="5", points="21.00")
        packet = "|".join(vars(message).values())
        with patch.object(diving_overlays, "apply_dive") as apply_update:
            diving_overlays.process_udp_message(packet)
            update = apply_update.call_args.args[0]
            self.assertEqual(update.phase, DivePhase.Awards)
            self.assertEqual(update.points, "21.00")

    def test_completion_carries_event_slot(self):
        with patch.object(diving_overlays, "complete_event") as complete:
            diving_overlays.process_udp_message("AVIDEO|b|computer|1|ENDOFEVENT|^")
            complete.assert_called_once_with("b")

    def test_empty_update_has_consistent_result(self):
        records, event = diving_overlays.parse_update_message("UPDATE|a")
        self.assertEqual(records, [])
        self.assertEqual(event.event_ab, "a")

    def fetch_rankings(self, generation=0):
        fields = list(vars(make_message()).values())[:73]
        text = "|".join(fields + ["1", "42.00", "", "First Diver", "2", "SSC"])
        payload = text.encode("utf-16le")
        connection = MagicMock()
        connection.recv.side_effect = [len(payload).to_bytes(4, "big"), payload, b""]
        with patch.object(diving_overlays.socket, "create_connection") as connect:
            connect.return_value.__enter__.return_value = connection
            return diving_overlays._fetch_update_file("127.0.0.1", "Update.txt", generation)

    def test_tcp_fetch_defers_obs_update_until_timer(self):
        with patch.object(diving_overlays, "apply_rankings") as apply_update:
            self.assertTrue(self.fetch_rankings())
            apply_update.assert_not_called()
            udp_socket = MagicMock()
            udp_socket.recvfrom.side_effect = BlockingIOError
            with patch.object(diving_overlays, "udp_sock", udp_socket):
                diving_overlays.udp_timer_callback()
            apply_update.assert_called_once()
            self.assertEqual(diving_overlays.mailbox.drain(), ([], 0))

    def test_unloaded_worker_cannot_publish(self):
        diving_overlays.transport_generation = diving_overlays.mailbox.new_token()
        self.assertFalse(self.fetch_rankings(generation=0))
        self.assertEqual(diving_overlays.mailbox.drain(), ([], 0))
        self.assertTrue(self.fetch_rankings(generation=1))
        self.assertEqual(diving_overlays.mailbox.drain()[0][0].event.slot, "a")

    def test_unload_stops_transport_and_common_timers(self):
        udp_socket = MagicMock()
        diving_overlays.startup_reset_pending = True
        with patch.object(diving_overlays, "udp_sock", udp_socket), \
             patch.object(diving_overlays, "dvov_script_unload") as common_unload:
            diving_overlays.script_unload()
            udp_socket.close.assert_called_once()
            common_unload.assert_called_once()
            self.assertEqual(diving_overlays.transport_generation, 1)
            self.assertFalse(diving_overlays.startup_reset_pending)

    def test_switch_sources_clears_state_and_stops_receiver(self):
        state_controls.latest_dives["a"] = adapt_dive(make_message())
        state_controls.completed_slots.add("a")
        state_controls.event_names["a"] = "Old event"
        fake_receiver = MagicMock()
        fake_socket = MagicMock()
        with patch.object(diving_overlays, "scoring_source", "diverecorder"), \
               patch.object(diving_overlays, "transport_config", ("diverecorder", 0, "", "")), \
             patch.object(diving_overlays, "udp_sock", fake_socket), \
             patch.object(diving_overlays, "receiver", None), \
             patch.object(diving_overlays, "DiveCalcReceiver", return_value=fake_receiver), \
             patch.object(state_controls, "set_event_a") as clear_display:
            diving_overlays._restart_transport(("divecalc", 8765, "/divecalc", ""))
            fake_socket.close.assert_called_once()
            clear_display.assert_called_once()
            self.assertEqual(state_controls.latest_dives, {})
            self.assertEqual(state_controls.completed_slots, set())
            self.assertEqual(state_controls.event_names, {})
            with patch.object(diving_overlays.socket, "socket", return_value=MagicMock()):
                diving_overlays._restart_transport(("diverecorder", 0, "", ""))
            fake_receiver.stop.assert_called_once()

    def test_startup_reset_waits_for_sources_before_processing_updates(self):
        update = adapt_dive(make_message())
        fake_receiver = MagicMock()
        operations = []
        with patch.object(diving_overlays, "scoring_source", "diverecorder"), \
             patch.object(diving_overlays, "transport_config", None), \
             patch.object(diving_overlays, "receiver", None), \
             patch.object(diving_overlays, "udp_sock", None), \
             patch.object(diving_overlays, "DiveCalcReceiver", return_value=fake_receiver), \
             patch.object(diving_overlays, "is_source_available", return_value=False) as available, \
             patch.object(state_controls, "set_event_a") as clear_display, \
             patch.object(diving_overlays, "apply_dive") as apply_update:
            clear_display.side_effect = lambda selected: operations.append("reset")
            apply_update.side_effect = lambda item: operations.append("update")
            diving_overlays._restart_transport(("divecalc", 8765, "/divecalc", ""))
            self.assertTrue(diving_overlays.mailbox.publish(update, diving_overlays.transport_generation))
            clear_display.assert_not_called()
            diving_overlays.udp_timer_callback()
            clear_display.assert_not_called()
            apply_update.assert_not_called()
            available.side_effect = lambda name: name != "Rnk_Score 10"
            diving_overlays.udp_timer_callback()
            clear_display.assert_not_called()
            apply_update.assert_not_called()
            available.side_effect = None
            available.return_value = True
            diving_overlays.udp_timer_callback()
            clear_display.assert_called_once()
            apply_update.assert_called_once_with(update)
            self.assertEqual(operations, ["reset", "update"])
            self.assertFalse(diving_overlays.startup_reset_pending)

    def test_startup_reset_eventually_reports_missing_sources(self):
        diving_overlays.startup_reset_pending = True
        diving_overlays.startup_reset_attempts = diving_overlays.STARTUP_RESET_MAX_ATTEMPTS - 1
        with patch.object(diving_overlays, "scoring_source", "divecalc"), \
             patch.object(diving_overlays, "is_source_available", return_value=False), \
             patch.object(state_controls, "set_event_a") as clear_display:
            diving_overlays.udp_timer_callback()
            clear_display.assert_called_once()
            self.assertFalse(diving_overlays.startup_reset_pending)

    def test_load_starts_only_selected_divecalc_transport(self):
        settings = object()
        values = {"scoring_source": "divecalc", "divecalc_path": "/divecalc",
                  "divecalc_allowed_ip": "", "rootDir": "."}
        fake_receiver = MagicMock()
        with patch.object(diving_overlays, "script_loaded", False), \
             patch.object(diving_overlays, "transport_config", None), \
             patch.object(diving_overlays, "scoring_source", "diverecorder"), \
             patch.object(diving_overlays, "receiver", None), \
             patch.object(diving_overlays, "udp_sock", None), \
             patch.object(diving_overlays, "dvov_script_load"), \
             patch.object(diving_overlays, "dvov_script_update"), \
             patch.object(state_controls, "set_event_a"), \
             patch.object(diving_overlays, "DiveCalcReceiver", return_value=fake_receiver) as create_receiver, \
             patch.object(diving_overlays.socket, "socket") as create_udp, \
             patch.object(diving_overlays.obs, "obs_data_get_string", side_effect=lambda data, key: values[key]), \
             patch.object(diving_overlays.obs, "obs_data_get_bool", return_value=True), \
             patch.object(diving_overlays.obs, "obs_data_get_int", return_value=8765):
            diving_overlays.script_load(settings)
            create_receiver.assert_called_once()
            create_udp.assert_not_called()
            diving_overlays.script_unload()
            fake_receiver.stop.assert_called_once()


class RankingsTests(unittest.TestCase):
    def setUp(self):
        rankings.last_update = None

    def test_guest_filter_uses_explicit_status(self):
        update = adapt_rankings([
            DiveListRecord(1, "42", "", "First", 2, "SSC"),
            DiveListRecord(-2, "40", "", "Guest", 1, "LTU"),
        ], make_message())
        with patch.object(rankings, "show_guests", False), \
             patch.object(rankings, "clear_data"), patch.object(rankings, "reset_pagination"):
            rankings.dvov_rank_set_divers(update)
            self.assertEqual([entry.diver for entry in rankings.ranking_rec_working_copy], ["First"])

    def test_guest_rank_and_color_are_preserved(self):
        entry = adapt_rankings([DiveListRecord(-2, "40", "", "Guest", 1, "LTU")], make_message()).entries[0]
        with patch.object(rankings, "mode", EventMode.Rankings), \
             patch.object(rankings, "show_guests", True), \
             patch.object(rankings, "get_source_string", return_value=""), \
             patch.object(rankings, "set_source_string") as text, \
             patch.object(rankings, "set_source_visibility"), \
             patch.object(rankings, "set_color_source_color") as color:
            rankings.show_rank_line(entry, 1)
            text.assert_any_call(f"{RankingsSrc.RankPrefix}1", "2")
            color.assert_any_call(f"{RankingsSrc.RankPrefix}1", 0x9a9a9a)

    def test_duplicate_snapshot_does_not_restart_pagination(self):
        update = adapt_rankings([DiveListRecord(1, "42", "", "First", 1, "SSC")], make_message())
        with patch.object(rankings, "clear_data"), patch.object(rankings, "reset_pagination") as reset:
            rankings.dvov_rank_set_divers(update)
            rankings.dvov_rank_set_divers(update)
            reset.assert_called_once()
            rankings.dvov_rank_set_event_ab(True)
            reset.reset_mock()
            rankings.dvov_rank_set_divers(update)
            reset.assert_called_once()

    def test_startlist_and_rankings_order_are_preserved(self):
        update = adapt_rankings([
            DiveListRecord(2, "40", "", "Second ranked", 1, "SSC"),
            DiveListRecord(1, "42", "", "First ranked", 2, "LTU"),
        ], make_message())
        with patch.object(rankings, "clear_data"), patch.object(rankings, "reset_pagination"), \
             patch.object(rankings, "set_source_string"), patch.object(rankings, "set_color_source_alpha"):
            rankings.dvov_rank_set_divers(update)
            with patch.object(rankings, "mode", EventMode.StartList):
                rankings.sort_list()
                self.assertEqual(rankings.ranking_rec_working_copy[0].start_position, 1)
            with patch.object(rankings, "mode", EventMode.Rankings):
                rankings.sort_list()
                self.assertEqual(rankings.ranking_rec_working_copy[0].rank, 1)


if __name__ == "__main__":
    unittest.main()