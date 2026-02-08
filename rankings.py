import typing

if typing.TYPE_CHECKING:
    import _obspython as obs  # full symbol set for IDE
else:
    import obspython as obs   # real runtime module

from typing import List
from datatypes import DiveListRecord, DiveMessage
from obs_utils import set_source_string, set_sceneitem_visible, get_scene, set_source_visibility, EventMode

#TODO: support for multiple events (not simultaneous)

# ------------------------------------------------------------------------------------------------------------------------------------------------------------------
# --------- Rankings handling
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------
RANKINGS_MAX_LINES = 8  # max number of lines supported in the scene

rankings_scene_name = ""
rankings_no_lines_per_page = 8
rankings_page_display_duration = 10  # seconds per page


# Source naming conventions
RNK_LINE_PREFIX = "ListLine "
RNK_BRD_LINE_PREFIX = "BoardListLine "
RNK_NAME_PREFIX = "Rnk_Name "
RNK_RANK_PREFIX = "Rnk_Rank "
RNK_TEAM_PREFIX = "Rnk_Team "
RNK_SCORE_PREFIX = "Rnk_Score "

RNK_HEADER_MEET = "Rnk_MeetTitle"
RNK_HEADER_EVENT = "Rnk_EventTitle"

ranking_rec_working_copy: List[DiveListRecord] = []
rankings_event_rec_working_copy: DiveMessage

mode: EventMode = EventMode.Undefined  # Initialize with default mode

debug = False

# ---------------------------
# Internal state
# ---------------------------
_current_page = 0
_total_pages = 0
_timer_active = False

_hotkey_start_id = None
_hotkey_stop_id = None

def dvov_rank_set_mode(eventMode: EventMode):
    global mode
    mode = eventMode

    # Reset pagination on any mode (usefull for resseting)
    stop_pagination()

    if (EventMode.StartList == mode) or (EventMode.Rankings == mode):
        start_pagination()


def dvov_rank_set_divers(records: List[DiveListRecord], event_record: DiveMessage):
    global ranking_rec_working_copy, rankings_event_rec_working_copy

    ranking_rec_working_copy = records.copy()
    rankings_event_rec_working_copy = event_record

    obs.script_log(obs.LOG_INFO, f"Set Divers event.")

    # Reset pagination on any data update
    stop_pagination()

    obs.script_log(obs.LOG_INFO, f"Set Divers event: Stopped pagination.")

    if (EventMode.StartList == mode) or (EventMode.Rankings == mode):
        obs.script_log(obs.LOG_INFO, f"Set Divers event: Starting pagination.")
        start_pagination()

    if debug:
        obs.script_log(obs.LOG_INFO, f"Set Divers event: Got ranking records for {len(ranking_rec_working_copy)} divers.")


# ---------------------------
# Pagination (show each page)
# ---------------------------
def show_page(ranking_rec: List[DiveListRecord], rankings_event_rec: DiveMessage, page_index):
    set_source_string(RNK_HEADER_MEET, rankings_event_rec.meet_title)
    set_source_string(RNK_HEADER_EVENT, rankings_event_rec.long_event_name)

    # Sort according to mode
    if EventMode.Rankings == mode:
        ranking_rec_working_copy.sort(key=lambda r: r.rank)  # sort by rank
    else:
        ranking_rec_working_copy.sort(key=lambda r: r.start_position)  # sort by position number for startlist

    start = page_index * rankings_no_lines_per_page
    chunk = ranking_rec[start:start + rankings_no_lines_per_page]

    # only hide lines if more than 1 page (it looks annoying on single page, flickering)
    if _total_pages > 1:
        for i in range(RANKINGS_MAX_LINES):
            set_source_visibility(f"{RNK_LINE_PREFIX}{i + 1}", False)
            set_source_visibility(f"{RNK_BRD_LINE_PREFIX}{i + 1}", False)

    for i in range(rankings_no_lines_per_page):
        if i < rankings_no_lines_per_page:
            disp_no = i + 1
            if i < len(chunk):
                diver = chunk[i]

                # use rank or start position based on mode
                if EventMode.Rankings == mode:
                    set_source_string(f"{RNK_RANK_PREFIX}{disp_no}", str(diver.rank) if int(diver.rank) > 0 else "G")
                else:
                    set_source_string(f"{RNK_RANK_PREFIX}{disp_no}", str(diver.start_position))

                set_source_string(f"{RNK_NAME_PREFIX}{disp_no}", diver.diver)
                set_source_string(f"{RNK_TEAM_PREFIX}{disp_no}", diver.club_code)

                if EventMode.Rankings == mode:
                    set_source_string(f"{RNK_SCORE_PREFIX}{disp_no}", diver.points)
                else:
                    set_source_string(f"{RNK_SCORE_PREFIX}{disp_no}", " ")

                set_source_visibility(f"{RNK_LINE_PREFIX}{disp_no}", True)
                set_source_visibility(f"{RNK_BRD_LINE_PREFIX}{disp_no}", True)


def clear_data():
    obs.script_log(obs.LOG_INFO, "clear_data: start.")

    set_source_string(RNK_HEADER_MEET, " ")
    set_source_string(RNK_HEADER_EVENT, " ")

    for i in range(RANKINGS_MAX_LINES):
        set_source_visibility(f"{RNK_LINE_PREFIX}{i+1}", False)
        set_source_visibility(f"{RNK_BRD_LINE_PREFIX}{i+1}", False)

        set_source_string(f"{RNK_RANK_PREFIX}{i+1}", " ")
        set_source_string(f"{RNK_NAME_PREFIX}{i+1}", " ")
        set_source_string(f"{RNK_TEAM_PREFIX}{i+1}", " ")
        set_source_string(f"{RNK_SCORE_PREFIX}{i+1}", " ")

    obs.script_log(obs.LOG_INFO, "clear_data: end.")


# ---------------------------
# Pagination control
# ---------------------------
def start_pagination():
    global ranking_rec_working_copy, rankings_event_rec_working_copy, _current_page, _total_pages, _timer_active

    clear_data()

    if ranking_rec_working_copy == []:
        if debug:
            obs.script_log(obs.LOG_INFO, "No startlist/ranking records")
        return

    if debug:
        obs.script_log(obs.LOG_INFO, "Starting pagination...")

    _current_page = 0
    _total_pages = (len(ranking_rec_working_copy) + rankings_no_lines_per_page - 1) // rankings_no_lines_per_page

    if debug:
        obs.script_log(obs.LOG_INFO, f"Starting continuous cycling: {_total_pages} pages")

    show_page(ranking_rec_working_copy, rankings_event_rec_working_copy, _current_page)

    # Start timer once
    if not _timer_active:
        obs.timer_add(_advance_page, int(rankings_page_display_duration * 1000))
        _timer_active = True


def _advance_page():
    global _current_page, _total_pages, ranking_rec_working_copy, rankings_event_rec_working_copy

    if ranking_rec_working_copy == [] or _total_pages == 0:
        return

    # Next page index
    next_page = (_current_page + 1) % _total_pages

    # If wrapping back to page 0 → reload data
    if next_page == 0:
        if debug:
            obs.script_log(obs.LOG_INFO, "Reloading ranking list for next cycle...")

        if ranking_rec_working_copy != []:
            _total_pages = (len(ranking_rec_working_copy) + rankings_no_lines_per_page - 1) // rankings_no_lines_per_page
        else:
            if debug:
                obs.script_log(obs.LOG_INFO, "No divers loaded after reload.")

    _current_page = next_page
    if debug:
        obs.script_log(obs.LOG_INFO, f"Advancing to page {_current_page + 1} of {_total_pages}")

    show_page(ranking_rec_working_copy, rankings_event_rec_working_copy, _current_page)


def stop_pagination():
    global _timer_active
    if _timer_active:
        obs.timer_remove(_advance_page)
        _timer_active = False
    if debug:
        obs.script_log(obs.LOG_INFO, "Stopped pagination.")

# ---------------------------
# Ranking Hotkeys callbacks
# ---------------------------
def on_rankings_hotkey_start(pressed):
    if pressed:
        if debug:
            obs.script_log(obs.LOG_INFO, "Rankings start hotkey pressed.")

        start_pagination()

def on_rankings_hotkey_stop(pressed):
    if pressed:
        if debug:
            obs.script_log(obs.LOG_INFO, "Rankings stop hotkey pressed.")

        stop_pagination()

def dvov_rank_add_properties(props):
    obs.obs_properties_add_text(props, "rnk_scene_name", "Rankings: Scene name", obs.OBS_TEXT_DEFAULT)
    obs.obs_properties_add_int(props, "rnk_num_per_page", "Rankings: Divers per page", 1, RANKINGS_MAX_LINES, 1)
    obs.obs_properties_add_int(props, "rnk_display_duration", "Rankings: Seconds per page", 1, 20, 1)


def dvov_rank_script_defaults(settings):
    obs.obs_data_set_default_string(settings, "rnk_scene_name", "OverlayRankings")
    obs.obs_data_set_default_int(settings, "rnk_num_per_page", 8)
    obs.obs_data_set_default_int(settings, "rnk_display_duration", 10)


# script_update actions
def dvov_rank_script_update(settings):
    # Rankings settings
    global debug, rankings_scene_name, rankings_no_lines_per_page, rankings_page_display_duration

    debug = obs.obs_data_get_bool(settings, "debug")
    rankings_scene_name = obs.obs_data_get_string(settings, "rnk_scene_name")
    rankings_no_lines_per_page = obs.obs_data_get_int(settings, "rnk_num_per_page")
    rankings_page_display_duration = obs.obs_data_get_int(settings, "rnk_display_duration")


def dvov_rank_script_load(settings):
    dvov_rank_script_update(settings)


# script_load actions
def dvov_rank_register_hotkeys(settings):
    # Rankings hotkeys
    global _hotkey_start_id, _hotkey_stop_id

    # Register start hotkey
    _hotkey_start_id = obs.obs_hotkey_register_frontend(
        "rankings.start", "Start Rankings Cycle", on_rankings_hotkey_start)
    arr = obs.obs_data_get_array(settings, "rankings.start")
    obs.obs_hotkey_load(_hotkey_start_id, arr)
    obs.obs_data_array_release(arr)

    # Register stop hotkey
    _hotkey_stop_id = obs.obs_hotkey_register_frontend(
        "rankings.stop", "Stop Rankings Cycle", on_rankings_hotkey_stop)
    arr = obs.obs_data_get_array(settings, "rankings.stop")
    obs.obs_hotkey_load(_hotkey_stop_id, arr)
    obs.obs_data_array_release(arr)