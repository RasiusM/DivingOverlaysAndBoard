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

from obs_utils import set_source_string, set_color_source_alpha, set_source_visibility, log_info_if_debug
from enums import (
    EventMode,
    DiveInfoGrp,
    JudgeAwardsGrp,
    SynchroJLabels,
    TVBannerGrp,
    MainBoardGrp,
    DiveInfoBoardGrp,
    JudgeAwardsBoardGrp,
    PreEventGrp,
    InProgrGrp,
    PostEventGrp,
    EventABGrp,
    EventInfoGrp,
    DisableOvrlGrp,
    AutoHideGrp,
    TopOvrlPosGrp,
    TopOverlayGrp,
)

from overlay_data import dvov_act_single_event_referee_update, dvov_act_set_event_ab, dvov_act_set_display_enabled
from rankings import dvov_rank_set_event_ab

from datatypes import DiveMessage

debug = False

referee_message: Union[DiveMessage, None] = None

synchro = False

top_overlay_pos_left: bool = True
event_ab_is_a: bool = True
overlays_enabled: bool = True
event_complete: bool = False
file_contents_changed: bool = True
hide_disable: bool = False
display_duration: int = 5000  # milliseconds
script_settings = None

def dvov_state_set_event_complete(is_event_complete: bool):
    global event_complete
    event_complete = is_event_complete
    set_color_source_alpha(PostEventGrp.EventCompleted, 255 if event_complete else 0)


# responsible for updating visibility/overlay removal logic
def dvov_state_on_message(msg: DiveMessage):
    global referee_message, synchro, event_complete

    referee_message = msg

    # If not "our" event, ignore message (e.g. if Event A message received but currently displaying Event B)
    if ((referee_message.event_ab == "a" and not event_ab_is_a)
        or
        (referee_message.event_ab == "b" and event_ab_is_a)):
        return

    # Judges count
    set_judges_count(int(msg.number_of_judges) if msg.number_of_judges.isdigit() else 0)

    # Set hide timer only if pre-dive message was received
    # TODO: should not depend on j1 being set. Find a better way.
    if referee_message.j1.strip() == "":
        obs.timer_add(lambda: tv_banner_remove_callback(), display_duration)

    synchro = (referee_message.synchro_event == "True")

    # Show warning if Synchro Event is true but it's B event (not sure if this is supported in diving software - original script did not handle this case)
    # TODO: test synchro B event
    if synchro and referee_message.event_ab == "b":
        obs.script_log(obs.LOG_WARNING, "Received message with Synchro Event = True but it's B event. Is this supported?")

    # Event type (Synchro / Individual)
    set_synchro_event(synchro)

    display_top_overlay(top_overlay_pos_left)
    display_tv_banner()


def set_synchro_event(synchro: bool):
    if synchro:
        set_source_string(EventInfoGrp.EventType, "Synchro Event")
        set_color_source_alpha(EventInfoGrp.Synchro, 255)
        set_color_source_alpha(EventInfoGrp.Individual, 0)
    else:
        set_source_string(EventInfoGrp.EventType, "Individual Event")
        set_color_source_alpha(EventInfoGrp.Individual, 255)
        set_color_source_alpha(EventInfoGrp.Synchro, 0)


def set_judges_count(number_of_judges: int):
    set_source_string(EventInfoGrp.NoOfJudges, f"No Judges: {number_of_judges}")


def display_top_overlay(left: bool):
    if left:
        set_color_source_alpha(TopOvrlPosGrp.Left, 255)
        set_color_source_alpha(TopOvrlPosGrp.Right, 0)
        if overlays_enabled:
            set_source_visibility(TopOverlayGrp.Left, True)
            set_source_visibility(TopOverlayGrp.Right, False)

    else:
        set_color_source_alpha(TopOvrlPosGrp.Left, 0)
        set_color_source_alpha(TopOvrlPosGrp.Right, 255)

        if overlays_enabled:
            set_source_visibility(TopOverlayGrp.Left, False)
            set_source_visibility(TopOverlayGrp.Right, True)


def display_tv_banner():
    if overlays_enabled:
        set_source_visibility(TVBannerGrp.GroupName, True)
        set_source_visibility(MainBoardGrp.GroupName, True)

# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# ---------- Banner ----------
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
tv_banner_removed = False

def remove_tv_banner():
    log_info_if_debug(debug, "start remove_tv_banner()")

    # remove stream overlays, do not touch board info
    for name in [TopOverlayGrp.Left, TopOverlayGrp.Right, TVBannerGrp.GroupName, JudgeAwardsGrp.GroupName, DiveInfoGrp.GroupName]:
        set_source_visibility(name, False)

    # cancel any pending remove_TVbanner timer callback if exists:
    try:
        obs.remove_current_callback()
    except Exception:
        pass


def tv_banner_remove_callback():
    global tv_banner_removed
    log_info_if_debug(debug, "start tv_banner_remove_callback()")

    if hide_disable and not event_complete:
        tv_banner_removed = True
        try:
            obs.remove_current_callback()
        except Exception:
            pass

        log_info_if_debug(debug, "hide_disable set - skipping tv_banner_remove_callback unless event_complete true")

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

    log_info_if_debug(debug, "Removing overlays and board info.")

    # disable all sources (overlays and board)
    for name in [TopOverlayGrp.Left, TopOverlayGrp.Right,
                 TVBannerGrp.GroupName, JudgeAwardsGrp.GroupName, DiveInfoGrp.GroupName,
                 MainBoardGrp.GroupName, JudgeAwardsBoardGrp.GroupName, DiveInfoBoardGrp.GroupName,
                 SynchroJLabels.Judges11, SynchroJLabels.Judges9, SynchroJLabels.Judges7, SynchroJLabels.Judges5, SynchroJLabels.JudgesBoard]:
        set_source_visibility(name, False)


def display_overlays(pressed):
    if not pressed:
        return

    display_top_overlay(top_overlay_pos_left)


# same as display_overlays plus redisplay tvBanner
def redisplay_overlays(pressed):
    if not pressed:
        return
    # re-display top overlay
    display_overlays(True)

    if referee_message is None:
        log_info_if_debug(debug, "No parsed message available for redisplay.")
        return

    # information is available, re-display tv banner
    display_tv_banner()
    dvov_act_single_event_referee_update(referee_message, synchro)


def set_display_enabled(is_enabled):
    set_color_source_alpha(DisableOvrlGrp.Disabled, 0 if is_enabled else 255)
    if is_enabled:
        set_source_string(DisableOvrlGrp.Status, "Overlays Visible")
    else:
        set_source_string(DisableOvrlGrp.Status, "Overlays NOT Visible")
        remove_overlays(True)


def toggle_display_disable(pressed):
    global overlays_enabled
    if not pressed:
        return
    overlays_enabled = not overlays_enabled

    obs.obs_data_set_bool(script_settings, "overlays_enabled", overlays_enabled)
    set_display_enabled(overlays_enabled)
    dvov_act_set_display_enabled(overlays_enabled)


def set_event_a(is_a: bool):
    set_color_source_alpha(EventABGrp.AActive, 255 if is_a else 0)
    set_color_source_alpha(EventABGrp.BActive, 0 if is_a else 255)

    dvov_act_set_event_ab(is_a)
    dvov_rank_set_event_ab(is_a)

    remove_overlays(True)


def toggle_event_a_or_b(pressed):
    global event_ab_is_a
    if not pressed:
        return
    event_ab_is_a = not event_ab_is_a

    set_event_a(event_ab_is_a)


def set_autohide_enabled(isEnabled):
    if isEnabled:
        set_color_source_alpha(AutoHideGrp.Disabled, 0)
        set_source_string(AutoHideGrp.Status, "Auto-Hide Enabled")
    else:
        set_color_source_alpha(AutoHideGrp.Disabled, 255)
        set_source_string(AutoHideGrp.Status, "Auto-Hide Disabled")


def toggle_disable_of_autohide(pressed):
    global hide_disable
    if not pressed:
        return

    hide_disable = not hide_disable

    if debug:
        obs.script_log(obs.LOG_INFO, f"toggle_disable_of_autohide(): hide_disable={hide_disable}")

    obs.obs_data_set_bool(script_settings, "hide_disable", hide_disable)

    set_autohide_enabled(not hide_disable)

def toggle_top_overlay_position(pressed):
    global top_overlay_pos_left
    if not pressed:
        return

    top_overlay_pos_left = not top_overlay_pos_left

    obs.obs_data_set_bool(script_settings, "single_event_pos_left", top_overlay_pos_left)
    display_top_overlay(top_overlay_pos_left)

    if debug:
        obs.script_log(obs.LOG_INFO, "Toggle single event position.")


def set_event_mode (eventMode: EventMode):
    set_color_source_alpha(PreEventGrp.Active, 0)
    set_color_source_alpha(InProgrGrp.Active, 0)
    set_color_source_alpha(PostEventGrp.Active, 0)

    if eventMode == EventMode.StartList:
        set_color_source_alpha(PreEventGrp.Active, 255)
    elif eventMode == EventMode.Event:
        set_color_source_alpha(InProgrGrp.Active, 255)
    elif eventMode == EventMode.Rankings:
        set_color_source_alpha(PostEventGrp.Active, 255)

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

    # JSON fragment. Use OBS key tokens here.
    json_s = (
        '{'
        '"htk_1":  [ { "key": "OBS_KEY_F1" } ],'
        '"htk_2":  [ { "key": "OBS_KEY_F2" } ],'
        '"htk_3":  [ { "key": "OBS_KEY_F3" } ],'
        '"htk_4":  [ { "key": "OBS_KEY_F4" } ],'
        '"htk_5":  [ { "key": "OBS_KEY_F5" } ],'
        '"htk_6":  [ { "key": "OBS_KEY_F6" } ],'
        '"htk_7":  [ { "key": "OBS_KEY_F7" } ],'
        '"htk_8":  [ { "key": "OBS_KEY_F8" } ],'
        '"htk_9":  [ { "key": "OBS_KEY_F9" } ],'
        '"htk_10": [ { "key": "OBS_KEY_F10" } ]'
        #'"htk_12": [ { "key": "OBS_KEY_F12" } ]'
        '}'
    )

    # Define mapping: id -> (description, callback)
    HK = {
            "htk_1":  ("Set Waiting for Event mode",                set_waiting_for_event_mode),
            "htk_2":  ("Set Event mode",                            set_event_in_progress_mode),
            "htk_3":  ("Set Rankings mode",                         set_event_rankings_mode),
            "htk_4":  ("Toggle to Display Event A or Event B",       toggle_event_a_or_b),
            "htk_5":  ("Temporary Remove DR2TVOverlays",            remove_overlays),
            "htk_6":  ("Temporary Display All DR2TVOverlays",       display_overlays),
            "htk_7":  ("Re-display Overlays",                       redisplay_overlays),
            "htk_8":  ("Permanently Remove All Overlays",           toggle_display_disable),
            "htk_9":  ("Disable Auto-hide of Overlays",             toggle_disable_of_autohide),
            "htk_10": ("Toggle Event Overlay Position",             toggle_top_overlay_position),
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
    global top_overlay_pos_left, overlays_enabled, hide_disable, debug, display_duration

    debug = obs.obs_data_get_bool(settings, "debug")
    display_duration = obs.obs_data_get_int(settings, "dinterval")

    top_overlay_pos_left = obs.obs_data_get_bool(settings, "single_event_pos_left")
    overlays_enabled = obs.obs_data_get_bool(settings, "overlays_enabled")
    hide_disable = obs.obs_data_get_bool(settings, "hide_disable")


def dvov_state_script_load(settings):
    global script_settings, hide_disable
    if settings is not None:
        script_settings = settings

    # load persisted states
    dvov_state_script_update(settings)
    if debug:
        obs.script_log(obs.LOG_INFO, f"dvov_state_script_load(): single_event_pos_left={top_overlay_pos_left}, overlays_enabled={overlays_enabled}, hide_disable={hide_disable}")



