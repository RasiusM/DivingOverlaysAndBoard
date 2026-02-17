import os
import typing

if typing.TYPE_CHECKING:
    import _obspython as obs  # full symbol set for IDE
else:
    import obspython as obs   # real runtime module

from typing import List
from datatypes import DiveListRecord, DiveMessage
from enums import RankingsSrc, EventMode
from obs_utils import is_source_available, set_source_file, set_source_string, set_source_visibility, log_info_if_debug

# ------------------------------------------------------------------------------------------------------------------------------------------------------------------
# --------- Rankings handling
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------
RANKINGS_MAX_LINES = 8  # max number of lines supported in the scene

rankings_no_lines_per_page = 8
rankings_page_display_duration = 10  # seconds per page

ranking_rec_working_copy: List[DiveListRecord] = []
rankings_event_rec_working_copy: DiveMessage

mode: EventMode = EventMode.Undefined  # Initialize with default mode

debug = False
root_dir = ""
set_source_props_retries = 0
SET_SOURCE_PROPS_RETRIES_MAX_RETRIES = 10

# ---------------------------
# Internal state
# ---------------------------
_current_page = 0
_total_pages = 0
_timer_active = False

_hotkey_start_id = None
_hotkey_stop_id = None

event_ab_is_a = True  # default to event A

def dvov_rank_set_mode(eventMode: EventMode):
    global mode
    mode = eventMode

    # Reset pagination on any mode (usefull for resseting)
    stop_pagination()

    if (EventMode.StartList == mode) or (EventMode.Rankings == mode):
        start_pagination()


def dvov_rank_set_event_ab(event_is_a: bool):
    global event_ab_is_a
    event_ab_is_a = event_is_a

    # event changed, all data is invalid
    clear_data()
    stop_pagination()


def clear_data():
    log_info_if_debug(debug, "Clearing ranking data from sources...")

    set_source_string(RankingsSrc.HeaderMeet, " ")
    set_source_string(RankingsSrc.HeaderEvent, " ")

    for i in range(RANKINGS_MAX_LINES):
        set_source_visibility(f"{RankingsSrc.LinePrefix}{i+1}", False)
        set_source_visibility(f"{RankingsSrc.BoardLinePrefix}{i+1}", False)

        set_source_string(f"{RankingsSrc.RankPrefix}{i+1}", " ")
        set_source_string(f"{RankingsSrc.NamePrefix}{i+1}", " ")
        set_source_string(f"{RankingsSrc.TeamPrefix}{i+1}", " ")
        set_source_string(f"{RankingsSrc.ScorePrefix}{i+1}", " ")


def dvov_rank_set_divers(records: List[DiveListRecord], event_record: DiveMessage):
    global ranking_rec_working_copy, rankings_event_rec_working_copy

    ranking_rec_working_copy = records.copy()
    rankings_event_rec_working_copy = event_record

    log_info_if_debug(debug, "Set Divers event.")

    # Reset pagination on any data update
    stop_pagination()

    log_info_if_debug(debug, "Set Divers event: Stopped pagination.")

    if (EventMode.StartList == mode) or (EventMode.Rankings == mode):
        log_info_if_debug(debug, "Set Divers event: Starting pagination.")
        start_pagination()

    log_info_if_debug(debug, f"Set Divers event: Got ranking records for {len(ranking_rec_working_copy)} divers.")


# ---------------------------
# Pagination (show each page)
# ---------------------------
def show_page(ranking_rec: List[DiveListRecord], rankings_event_rec: DiveMessage, page_index):
    set_source_string(RankingsSrc.HeaderMeet, rankings_event_rec.meet_title)
    set_source_string(RankingsSrc.HeaderEvent, rankings_event_rec.long_event_name)

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
            set_source_visibility(f"{RankingsSrc.LinePrefix}{i + 1}", False)
            set_source_visibility(f"{RankingsSrc.BoardLinePrefix}{i + 1}", False)

    for i in range(rankings_no_lines_per_page):
        if i < rankings_no_lines_per_page:
            disp_no = i + 1
            if i < len(chunk):
                diver = chunk[i]

                # use rank or start position based on mode
                if EventMode.Rankings == mode:
                    set_source_string(f"{RankingsSrc.RankPrefix}{disp_no}", str(diver.rank) if int(diver.rank) > 0 else "G")
                else:
                    set_source_string(f"{RankingsSrc.RankPrefix}{disp_no}", str(diver.start_position))

                set_source_string(f"{RankingsSrc.NamePrefix}{disp_no}", diver.diver)
                set_source_string(f"{RankingsSrc.TeamPrefix}{disp_no}", diver.club_code)

                if EventMode.Rankings == mode:
                    set_source_string(f"{RankingsSrc.ScorePrefix}{disp_no}", diver.points)
                else:
                    set_source_string(f"{RankingsSrc.ScorePrefix}{disp_no}", " ")

                set_source_visibility(f"{RankingsSrc.LinePrefix}{disp_no}", True)
                set_source_visibility(f"{RankingsSrc.BoardLinePrefix}{disp_no}", True)


# ---------------------------
# Pagination control
# ---------------------------
def start_pagination():
    global ranking_rec_working_copy, rankings_event_rec_working_copy, _current_page, _total_pages, _timer_active

    clear_data()

    if ranking_rec_working_copy == []:
        log_info_if_debug(debug, "No startlist/ranking records")
        return

    log_info_if_debug(debug, "Starting pagination...")

    _current_page = 0
    _total_pages = (len(ranking_rec_working_copy) + rankings_no_lines_per_page - 1) // rankings_no_lines_per_page

    log_info_if_debug(debug, f"Starting continuous cycling: {_total_pages} pages")

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
        log_info_if_debug(debug, "Reloading ranking list for next cycle...")

        if ranking_rec_working_copy != []:
            _total_pages = (len(ranking_rec_working_copy) + rankings_no_lines_per_page - 1) // rankings_no_lines_per_page
        else:
            log_info_if_debug(debug, "No divers loaded after reload.")

    _current_page = next_page
    log_info_if_debug(debug, f"Advancing to page {_current_page + 1} of {_total_pages}")

    show_page(ranking_rec_working_copy, rankings_event_rec_working_copy, _current_page)


def stop_pagination():
    global _timer_active
    if _timer_active:
        obs.timer_remove(_advance_page)
        _timer_active = False
    log_info_if_debug(debug, "Stopped pagination.")

# ---------------------------
# Ranking Hotkeys callbacks
# ---------------------------
def on_rankings_hotkey_start(pressed):
    if pressed:
        log_info_if_debug(debug, "Rankings start hotkey pressed.")

        start_pagination()

def on_rankings_hotkey_stop(pressed):
    if pressed:
        log_info_if_debug(debug, "Rankings stop hotkey pressed.")

        stop_pagination()


# -------
# script lifecycle functions
# ------
def set_source_paths():
    global set_source_props_retries

    do_source_exists_check=True

    # set any source paths that depend on root directory here

    # logic here looks too complicated because we need to deal with the fact that on script load,
    # sources might not be available yet, so we have a timer to keep retrying until sources are available,
    # but we also want to avoid infinite loop in case sources are really missing,
    # so we stop retrying after several attempts and log warnings if sources don't exist.
    set_source_props_retries += 1

    if set_source_props_retries > SET_SOURCE_PROPS_RETRIES_MAX_RETRIES:
        do_source_exists_check = False
        obs.timer_remove(set_source_paths) # stop retrying, but still attempt to set source paths one last time (which will log warnings if sources don't exist)

    pic_file = os.path.join(root_dir, f"Media\\Art\\{RankingsSrc.HeaderArtFile}")
    if not os.path.isfile(pic_file):
        obs.script_log(obs.LOG_WARNING, f"{RankingsSrc.HeaderArtFile} file does not exist: {pic_file}")

    if not is_source_available(RankingsSrc.HeaderArt) and do_source_exists_check:
        return
    set_source_file(RankingsSrc.HeaderArt, pic_file)

    pic_file = os.path.join(root_dir, f"Media\\Art\\{RankingsSrc.HeaderLogoFile}")
    if not os.path.isfile(pic_file):
        obs.script_log(obs.LOG_WARNING, f"{RankingsSrc.HeaderLogoFile} file does not exist: {pic_file}")

    if not is_source_available(RankingsSrc.HeaderLogo) and do_source_exists_check:
        return
    set_source_file(RankingsSrc.HeaderLogo, pic_file)

    # Set Schedule text to file content
    schedule_file = os.path.join(root_dir, f"data\\{RankingsSrc.ScheduleTextFile}")
    if not os.path.isfile(schedule_file):
        obs.script_log(obs.LOG_WARNING, f"{RankingsSrc.ScheduleTextFile} file does not exist: {schedule_file}")

    if not is_source_available(RankingsSrc.ScheduleText) and do_source_exists_check:
        return
    set_source_file(RankingsSrc.ScheduleText, schedule_file)

    # if we're here, it means we succeeded in setting source paths or we failed (and reported) because sources don't exist and we want to stop retrying
    obs.timer_remove(set_source_paths)


def dvov_rank_add_properties(props):
    obs.obs_properties_add_int(props, "rnk_num_per_page", "Rankings: Divers per page", 1, RANKINGS_MAX_LINES, 1)
    obs.obs_properties_add_int(props, "rnk_display_duration", "Rankings: Seconds per page", 1, 20, 1)


def dvov_rank_script_defaults(settings):
    obs.obs_data_set_default_int(settings, "rnk_num_per_page", 8)
    obs.obs_data_set_default_int(settings, "rnk_display_duration", 10)


def dvov_rank_script_update(settings):
    # Rankings settings
    global debug, rankings_no_lines_per_page, rankings_page_display_duration, root_dir

    debug = obs.obs_data_get_bool(settings, "debug")
    rankings_no_lines_per_page = obs.obs_data_get_int(settings, "rnk_num_per_page")
    rankings_page_display_duration = obs.obs_data_get_int(settings, "rnk_display_duration")

    # Set Header picture source files
    root_dir = obs.obs_data_get_string(settings, "rootDir")

    # need to do this by timer, because on script load, sources aren't available yet
    obs.timer_add(set_source_paths, 3000)


def dvov_rank_script_load(settings):
    dvov_rank_script_update(settings)


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