'''
Module for managing state of overlays and reflecting state in Status dock
'''
import typing

from rankings import dvov_rank_set_mode

if typing.TYPE_CHECKING:
    import _obspython as obs  # full symbol set for IDE
else:
    import obspython as obs   # real runtime module

from typing import Union

from obs_utils import EventMode, set_source_string, set_color_source_alpha, set_source_visibility
from overlay_data import dvov_act_set_synchro_judge_labels, dvov_act_single_event_referee_update
from datatypes import DiveMessage

debug = False

referee_message: Union[DiveMessage, None] = None

synchro = False

single_event_pos_left: bool = True
sim_event_a_pos_left: bool = True
overlays_enabled: bool = True
event_complete: bool = False
file_contents_changed: bool = True
hide_disable: bool = False
display_duration: int = 5000  # milliseconds
script_settings = None

def dvov_state_set_event_complete(is_event_complete: bool):
    global event_complete
    event_complete = is_event_complete
    set_source_visibility("Event_Complete", event_complete)

# responsible for updating visibility/overlay removal logic
def dvov_state_on_message(msg: DiveMessage):
    global referee_message, synchro, event_complete

    referee_message = msg

    # Judges count
    set_judges_count(int(msg.number_of_judges) if msg.number_of_judges.isdigit() else 0)

    # Set hide timer only if pre-dive message was received
    # TODO: should not depend on j1 being set. Find a better way.
    if referee_message.j1.strip() == "":
        obs.timer_add(lambda: tv_banner_remove_callback(), display_duration)

    # Cannot have synchro if this is Event B
    synchro = (referee_message.synchro_event == "True" and referee_message.event_ab == "a")

    # Event type (Synchro / Individual)
    set_synchro_event(synchro)

    display_event_overlay(single_event_pos_left)
    display_tv_banner()


def set_synchro_event(synchro: bool):
    if synchro:
        set_source_string("Event_Type", "Synchro Event")
        set_color_source_alpha("F9_Function_Background_True", 255)
        set_color_source_alpha("F9_Function_Background_False", 0)
    else:
        set_source_string("Event_Type", "Individual Event")
        set_color_source_alpha("F9_Function_Background_False", 255)
        set_color_source_alpha("F9_Function_Background_True", 0)


def set_judges_count(number_of_judges: int):
    set_source_string("No_of_Judges", f"No Judges: {number_of_judges}")


def display_event_overlay(left: bool):
    if left:
        set_color_source_alpha("OverlayPositionLeft", 255)
        set_color_source_alpha("OverlayPositionRight", 0)
        if overlays_enabled:
            set_source_visibility("Event 1", True)
            set_source_visibility("Event 2", False)

    else:
        set_color_source_alpha("OverlayPositionLeft", 0)
        set_color_source_alpha("OverlayPositionRight", 255)

        if overlays_enabled:
            set_source_visibility("Event 1", False)
            set_source_visibility("Event 2", True)

def display_tv_banner():
    if overlays_enabled:
        set_source_visibility("TVBanner", True)
        set_source_visibility("MainBoard", True)

# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# ---------- Banner ----------
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
tv_banner_removed = False

def remove_tv_banner():
    if debug:
        obs.script_log(obs.LOG_INFO, "start remove_tv_banner()")

    # remove stream overlays, do not touch board info
    for name in ["Event A", "Event B", "Event 1", "Event 2", "TVBanner", "JudgeAwards", "DiveInfo"]:
        set_source_visibility(name, False)

    # cancel any pending remove_TVbanner timer callback if exists:
    try:
        obs.remove_current_callback()
    except Exception:
        pass

def tv_banner_remove_callback():
    global tv_banner_removed
    if debug:
        obs.script_log(obs.LOG_INFO, "start tv_banner_remove_callback()")

    if hide_disable and not event_complete:
        tv_banner_removed = True
        try:
            obs.remove_current_callback()
        except Exception:
            pass

        if debug:
            obs.script_log(obs.LOG_INFO, "hide_disable set - skipping tv_banner_remove_callback unless event_complete true")

        return

    remove_tv_banner()
    try:
        obs.remove_current_callback()
    except Exception:
        pass
    tv_banner_removed = True

# ---------- Hotkey/callback functions ----------
def do_nothing(pressed):
    if not pressed:
        return
    obs.script_log(obs.LOG_INFO, "Do Nothing!")

def remove_overlays(pressed):
    if not pressed:
        return

    if debug:
        obs.script_log(obs.LOG_INFO, "Removing overlays and board info.")

    # disable all sources (overlays and board)
    for name in ["Event A", "Event B", "Event 1", "Event 2", "TVBanner", "MainBoard", "JudgeAwards", "DiveInfo", "JudgeAwardsBoard", "DiveInfoBoard",
                 "SynchroJLabels11", "SynchroJLabels9", "SynchroJLabels7", "SynchroJLabels5", "SynchroJLabelsBoard"]:
        set_source_visibility(name, False)

def display_overlays(pressed):
    if not pressed:
        return

    # if simultaneous_events:
    #     # enable the commonly used overlay groups:
    #     return
    #     for name in ["Event A", "Event B"]:
    #         set_source_visibility(name, True)
    # else:
        # enable the commonly used overlay groups:

    display_event_overlay(single_event_pos_left)

# same as display_overlays plus redisplay tvBanner
def redisplay_overlays(pressed):
    if not pressed:
        return
    # re-display top overlay
    display_overlays(True)

    if referee_message is None:
        if debug:
            obs.script_log(obs.LOG_INFO, "No parsed message available for redisplay.")
        return

    # information is available, re-display tv banner
    display_tv_banner()
    dvov_act_single_event_referee_update(referee_message, synchro)


def set_display_enabled(is_enabled):
    set_color_source_alpha("F4_Function_Background_True", 255 if is_enabled else 0)
    set_color_source_alpha("F4_Function_Background_False",  0 if is_enabled else 255)
    if is_enabled:
        set_source_string("Overlays_Visible", "Overlays Visible")
    else:
        set_source_string("Overlays_Visible", "Overlays NOT Visible")
        remove_overlays(True)


def toggle_display_disable(pressed):
    global overlays_enabled
    if not pressed:
        return
    overlays_enabled = not overlays_enabled

    obs.obs_data_set_bool(script_settings, "overlays_enabled", overlays_enabled)
    set_display_enabled(overlays_enabled)


def toggle_event_a_or_b(pressed):
    global sim_event_a_pos_left
    if not pressed:
        return
    sim_event_a_pos_left = not sim_event_a_pos_left

    #TODO: Implement toggling of Event A/B overlays
    #TODO: Implement toggling of Event A/B overlays status


def set_autohide_enabled(isEnabled):
    if isEnabled:
        set_color_source_alpha("F5_Function_Background_True", 255)
        set_color_source_alpha("F5_Function_Background_False", 0)
        set_source_string("AutoHide", "Auto-Hide Enabled")
    else:
        set_color_source_alpha("F5_Function_Background_True", 0)
        set_color_source_alpha("F5_Function_Background_False", 255)
        set_source_string("AutoHide", "Auto-Hide Disabled")


def toggle_disable_of_autohide(pressed):
    global hide_disable
    if not pressed:
        return

    hide_disable = not hide_disable

    if debug:
        obs.script_log(obs.LOG_INFO, f"toggle_disable_of_autohide(): hide_disable={hide_disable}")

    obs.obs_data_set_bool(script_settings, "hide_disable", hide_disable)

    set_autohide_enabled(not hide_disable)

def toggle_event_position(pressed):
    global sim_event_a_pos_left, single_event_pos_left, simultaneous_events
    if not pressed:
        return

    # if simultaneous_events:
    #     obs.script_log(obs.LOG_INFO, "Simultaneous mode not implemented.")
    #     sim_event_a_pos_left = not sim_event_a_pos_left
    # else:

    single_event_pos_left = not single_event_pos_left

    obs.obs_data_set_bool(script_settings, "single_event_pos_left", single_event_pos_left)
    display_event_overlay(single_event_pos_left)

    if debug:
        obs.script_log(obs.LOG_INFO, "Toggle single event position.")

# def toggle_simultaneous_events(pressed):
#     global simultaneous_events
#     if not pressed:
#         return
#     simultaneous_events = not simultaneous_events
#     if simultaneous_events:
#         return
#         # enable event groups for simultaneous
#         set_source_visibility("Event A", True)
#         # set_source_visibility("EventData_A", True)
#         set_source_visibility("Event B", True)
#         # set_source_visibility("EventData_B", True)

#         set_color_source_alpha("Position1", 255)
#         set_color_source_alpha("Position2", 255)

#         toggle_event_position(True)
#         display_overlays(True)
#     else:
#         # disable event groups for simultaneous
#         set_source_visibility("Event A", False)
#         set_source_visibility("Event B", False)

#         dvov_status_set_event_overlay_position(single_event_pos_left)

def set_event_mode (eventMode: EventMode):
    set_color_source_alpha("F7_Function_Background_Active", 0)
    set_color_source_alpha("F8_Function_Background_Active", 0)
    set_color_source_alpha("F9_Function_Background_Active", 0)

    if eventMode == EventMode.StartList:
        set_color_source_alpha("F7_Function_Background_Active", 255)
    elif eventMode == EventMode.Event:
        set_color_source_alpha("F8_Function_Background_Active", 255)
    elif eventMode == EventMode.Rankings:
        set_color_source_alpha("F9_Function_Background_Active", 255)

    if debug:
        obs.script_log(obs.LOG_INFO, f"Setting Event Mode to {eventMode}.")


def set_waiting_for_event_mode(pressed):
    if not pressed:
        return

    dvov_rank_set_mode(EventMode.StartList)
    set_event_mode(EventMode.StartList)

def set_event_in_progress_mode(pressed):
    if not pressed:
        return

    dvov_rank_set_mode(EventMode.Event)
    set_event_mode(EventMode.Event)

def set_event_rankings_mode(pressed):
    if not pressed:
        return

    dvov_rank_set_mode(EventMode.Rankings)
    set_event_mode(EventMode.Rankings)


hotkey_handles = {}
_registered = False

def dvov_status_register_hotkeys_force():
    """
    Register hotkeys and force default F1..F12 bindings using a JSON blob,
    similar to your working Lua code.
    """
    global hotkey_handles, _registered
    if _registered:
        obs.script_log(obs.LOG_INFO, "Hotkeys already registered (skipping).")
        return

    # JSON fragment similar to your Lua snippet. Use OBS key tokens here.
    json_s = (
        '{'
        '"htk_1":  [ { "key": "OBS_KEY_F1" } ],'
        '"htk_2":  [ { "key": "OBS_KEY_F2" } ],'
        '"htk_3":  [ { "key": "OBS_KEY_F3" } ],'
        '"htk_4":  [ { "key": "OBS_KEY_F4" } ],'
        '"htk_5":  [ { "key": "OBS_KEY_F5" } ],'
        '"htk_6":  [ { "key": "OBS_KEY_F6" } ],'
        '"htk_7":  [ { "key": "OBS_KEY_F7" } ],' # Will become F1
        '"htk_8":  [ { "key": "OBS_KEY_F8" } ],'
        '"htk_9":  [ { "key": "OBS_KEY_F9" } ],'
        '"htk_10": [ { "key": "OBS_KEY_F10" } ]'
        #'"htk_12": [ { "key": "OBS_KEY_F12" } ]'
        '}'
    )

    # Define mapping: id -> (description, callback)
    HK = {
        "htk_1":  ("Temporary Remove DR2TVOverlays",            remove_overlays),
        "htk_2":  ("Temporary Display All DR2TVOverlays",       display_overlays),
        "htk_3":  ("Re-display Overlays",                       redisplay_overlays),
        "htk_4":  ("Permanently Remove All Overlays",           toggle_display_disable),
        "htk_5":  ("Disable Auto-hide of Overlays",             toggle_disable_of_autohide),
        #"htk_6":  ("Toggle to Display Event A or Event B",       toggle_event_a_or_b),
        "htk_6":  ("Not used",                                  do_nothing),
        "htk_7":  ("Set Waiting for Event mode",                set_waiting_for_event_mode),
        "htk_8":  ("Set Event mode",                            set_event_in_progress_mode),
        "htk_9":  ("Set Rankings mode",                         set_event_rankings_mode),
        "htk_10": ("Toggle Event Overlay Position",             toggle_event_position),
        #"htk_12": ("Toggle to/from Simultaneous Event Overlays", toggle_simultaneous_events),
    }

    # Create an obs_data_t from JSON
    data = obs.obs_data_create_from_json(json_s)
    if data is None:
        obs.script_log(obs.LOG_ERROR, "Failed to create obs_data from JSON hotkey defaults.")
        return

    # Register hotkeys & load arrays from JSON
    for key_id, (desc, callback) in HK.items():
        try:
            handle = obs.obs_hotkey_register_frontend(key_id, desc, callback)
            hotkey_handles[key_id] = handle

            arr = obs.obs_data_get_array(data, key_id)
            # Load default key array into the handle (this sets F1..F12)
            obs.obs_hotkey_load(handle, arr)
            obs.obs_data_array_release(arr)
        except Exception as e:
            obs.script_log(obs.LOG_ERROR, f"Error registering hotkey {key_id}: {e}")

    obs.obs_data_release(data)
    _registered = True
    obs.script_log(obs.LOG_INFO, "Hotkeys registered and defaults loaded (forced).")

def dvov_state_script_properties(props):
    obs.obs_properties_add_int(props, "dinterval", "TVOverlay display period (ms)", 4000, 15000, 1000)


def dvov_state_script_defaults(settings):
    obs.obs_data_set_default_int(settings, "dinterval", 5000)


# load state values from persisted script settings
def dvov_state_script_update(settings):
    global single_event_pos_left, overlays_enabled, hide_disable, debug, display_duration

    debug = obs.obs_data_get_bool(settings, "debug")
    display_duration = obs.obs_data_get_int(settings, "dinterval")

    single_event_pos_left = obs.obs_data_get_bool(settings, "single_event_pos_left")
    overlays_enabled = obs.obs_data_get_bool(settings, "overlays_enabled")
    hide_disable = obs.obs_data_get_bool(settings, "hide_disable")


def dvov_state_script_load(settings):
    global script_settings, hide_disable
    if settings is not None:
        script_settings = settings

    # load persisted states
    dvov_state_script_update(settings)
    if debug:
        obs.script_log(obs.LOG_INFO, f"dvov_state_script_load(): single_event_pos_left={single_event_pos_left}, overlays_enabled={overlays_enabled}, hide_disable={hide_disable}")



