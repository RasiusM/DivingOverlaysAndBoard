import typing

if typing.TYPE_CHECKING:
    import _obspython as obs  # full symbol set for IDE
else:
    import obspython as obs   # real runtime module

from typing import List
from datatypes import DiveListRecord, DiveMessage
from obs_utils import set_source_string, set_sceneitem_visible, get_scene

#TODO: support for multiple events (not simultaneous)

# ------------------------------------------------------------------------------------------------------------------------------------------------------------------
# --------- Rankings handling
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------
rankings_scene_name = ""
rankings_no_lines_per_page = 8
rankings_page_display_duration = 10  # seconds per page

# Source naming conventions
RNK_GRADIENT_PREFIX = "Rnk_Gradient "
RNK_NAME_PREFIX = "Rnk_Name "
RNK_RANK_PREFIX = "Rnk_Rank "
RNK_TEAM_PREFIX = "Rnk_Team "
RNK_SCORE_PREFIX = "Rnk_Score "

RNK_HEADER_MEET = "Rnk_MeetTitle"
RNK_HEADER_EVENT = "Rnk_EventTitle"

RNK_GROUP_PREFIXES = [RNK_GRADIENT_PREFIX, RNK_NAME_PREFIX, RNK_RANK_PREFIX, RNK_TEAM_PREFIX, RNK_SCORE_PREFIX]

ranking_rec_working_copy: List[DiveListRecord] = []
rankings_event_rec_working_copy: DiveMessage

debug = False

# ---------------------------
# Internal state
# ---------------------------
_current_page = 0
_total_pages = 0
_timer_active = False

_hotkey_start_id = None
_hotkey_stop_id = None

def rankings_set_debug(on: bool):
    global debug
    debug = on

def rankings_set_divers(records: List[DiveListRecord], event_record: DiveMessage):
    global ranking_rec_working_copy, rankings_event_rec_working_copy

    ranking_rec_working_copy = records.copy()
    rankings_event_rec_working_copy = event_record

    # Determine if startlist or rankings based on all ranks being 1
    is_startlist = all(rec.rank == "1" for rec in ranking_rec_working_copy) or len(ranking_rec_working_copy) == 0

    # Sort appropriately
    if is_startlist:
        ranking_rec_working_copy.sort(key=lambda r: r.start_position)  # sort by position number for startlist
    else:
        ranking_rec_working_copy.sort(key=lambda r: int(r.rank))  # sort by rank for rankings

# ---------------------------
# Pagination (show each page)
# ---------------------------
def show_page(ranking_rec: List[DiveListRecord], rankings_event_rec: DiveMessage, page_index):
    #TODO: set header values!
    scene, src = get_scene(rankings_scene_name)
    if scene is None:
        obs.script_log(obs.LOG_ERROR, f"Scene not found: {rankings_scene_name}")
        return

    start = page_index * rankings_no_lines_per_page
    chunk = ranking_rec[start:start + rankings_no_lines_per_page]

    for i in range(rankings_no_lines_per_page):
        disp_no = i + 1
        if i < len(chunk):
            diver = chunk[i]

            set_source_string(f"{RNK_RANK_PREFIX}{disp_no}", diver.rank)
            set_source_string(f"{RNK_NAME_PREFIX}{disp_no}", diver.diver)
            set_source_string(f"{RNK_TEAM_PREFIX}{disp_no}", diver.club_code)
            set_source_string(f"{RNK_SCORE_PREFIX}{disp_no}", diver.points)

            for prefix in RNK_GROUP_PREFIXES:
                set_sceneitem_visible(scene, f"{prefix}{disp_no}", True)
        else:
            for prefix in RNK_GROUP_PREFIXES:
                set_sceneitem_visible(scene, f"{prefix}{disp_no}", False)

    # SAFE release: only release the source
    obs.obs_source_release(src)


# ---------------------------
# Pagination control
# ---------------------------
def start_pagination():
    global ranking_rec_working_copy, rankings_event_rec_working_copy, _current_page, _total_pages, _timer_active

    # TODO: hide all lines so that no old data is shown if no records are present
    if ranking_rec_working_copy == []:
        if debug:
            obs.script_log(obs.LOG_INFO, "No startlist/ranking records")
        return

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

    # If wrapping back to page 0 → reload XML
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

        #TODO: check if listst are not empty
        start_pagination()

def on_rankings_hotkey_stop(pressed):
    if pressed:
        if debug:
            obs.script_log(obs.LOG_INFO, "Rankings stop hotkey pressed.")

        stop_pagination()

def rankings_add_properties(props):
    obs.obs_properties_add_text(props, "rnk_scene_name", "Rankings: Scene name", obs.OBS_TEXT_DEFAULT)
    obs.obs_properties_add_int(props, "rnk_num_per_page", "Rankings: Divers per page", 1, 50, 1)
    obs.obs_properties_add_int(props, "rnk_display_duration", "Rankings: Seconds per page", 1, 3600, 1)

# script_update actions
def rankings_update_settings(settings):
    # Rankings settings
    global rankings_scene_name, rankings_no_lines_per_page, rankings_page_display_duration

    rankings_scene_name = obs.obs_data_get_string(settings, "rnk_scene_name")
    rankings_no_lines_per_page = obs.obs_data_get_int(settings, "rnk_num_per_page")
    rankings_page_display_duration = obs.obs_data_get_int(settings, "rnk_display_duration")


# script_load actions
def rankings_register_hotkeys(settings):
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