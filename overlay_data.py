import typing

if typing.TYPE_CHECKING:
    import _obspython as obs  # full symbol set for IDE
else:
    import obspython as obs   # real runtime module

from datatypes import DivePhase, DiveUpdate
from obs_utils import center_score, set_filter_path, set_source_string, set_source_file, set_source_visibility, log_info_if_debug, set_vlc_playlist, is_source_available
from enums import (DiveInfoBoardGrp, EventInfo, IndividualAwards, InstantReplaySrc, JudgeAwardsBoardGrp, MainBoardGrp, SynchroLabelsBoardGrp,
                   TVBannerGrp, SynchroAwards, SynchroLabelsGrp, DiveInfoGrp, AwardsCommonGrp)

import os

flagLoc = ""
rootDir = ""
debug = False
event_name = ""
event_ab_is_a = True  # default to Event A
overlays_enabled = True

set_source_props_retries = 0
SET_SOURCE_PROPS_RETRIES_MAX_RETRIES = 10

# constants (penalty / position lookups)
positionText = {
    "A": "Straight",
    "B": "Pike",
    "C": "Tuck",
    "D": "Free"
}

def clear_data():
    # Clear all sources to blank or default state (e.g. hide judge awards, clear flags, etc.)
    set_source_string(EventInfo.Info, " ")
    set_source_string(EventInfo.Title, " ")
    set_source_string(EventInfo.DiverNo, " ")
    set_source_string(EventInfo.RoundNo, " ")


    set_source_string(TVBannerGrp.Diver, " ")
    set_source_file(TVBannerGrp.Flag, "")
    set_source_string(TVBannerGrp.Position, " ")
    set_source_string(TVBannerGrp.Total, " ")

    set_source_file(MainBoardGrp.Flag1, "")
    set_source_file(MainBoardGrp.Flag2, "")
    set_source_string(MainBoardGrp.Diver1, " ")
    set_source_string(MainBoardGrp.Diver2, " ")

    set_source_visibility(IndividualAwards.JudgesGrp7, False)
    set_source_visibility(IndividualAwards.JudgesGrp5, False)
    set_source_visibility(IndividualAwards.JudgesGrp3, False)

    set_source_visibility(SynchroLabelsGrp.GroupName, False)

    set_source_visibility(SynchroAwards.JudgesGrp11, False)
    set_source_visibility(SynchroAwards.JudgesGrp9, False)
    set_source_visibility(SynchroAwards.JudgesGrp7, False)
    set_source_visibility(SynchroAwards.JudgesGrp5, False)

    set_source_visibility(JudgeAwardsBoardGrp.GroupName, False)
    set_source_visibility(SynchroLabelsBoardGrp.GroupName, False)

    for i in range(1, 12):
        if i <= 7:
            set_source_string(f"{SynchroAwards.JudgeExecPrefix}{i}", "  ")
            set_source_string(f"{IndividualAwards.JudgePrefix}{i}", "  ")
            set_source_string(f"{JudgeAwardsBoardGrp.JExecPrefix}{i}", "  ")

        if i <= 5:
            set_source_string(f"{SynchroAwards.JudgeSynchroPrefix}{i}", "  ")
            set_source_string(f"{JudgeAwardsBoardGrp.JSynchroPrefix}{i}", "  ")

    set_source_visibility(DiveInfoGrp.GroupName, False)
    set_source_visibility(DiveInfoBoardGrp.GroupName, False)


def set_synchro_judge_number(count_judges: int):
    # overlay synchro judge awards and labels visibility
    set_source_visibility(SynchroLabelsGrp.GroupName, (count_judges > 0))
    set_source_visibility(SynchroAwards.JudgesGrp11, (count_judges == 11))
    set_source_visibility(SynchroAwards.JudgesGrp9, (count_judges == 9))
    set_source_visibility(SynchroAwards.JudgesGrp7, (count_judges == 7))
    set_source_visibility(SynchroAwards.JudgesGrp5, (count_judges == 5))

    # setting Synchro Labels in Board visibility
    set_source_visibility(SynchroLabelsBoardGrp.GroupName, (count_judges > 0))
    set_source_visibility(JudgeAwardsBoardGrp.GroupName, (count_judges > 0))


def set_individual_judge_number(count_judges: int):
    log_info_if_debug(debug, f"Setting individual judge number: {count_judges}")
    # overlay individual judge scores visibility
    set_source_visibility(IndividualAwards.JudgesGrp7, (count_judges == 7))
    set_source_visibility(IndividualAwards.JudgesGrp5, (count_judges == 5))
    set_source_visibility(IndividualAwards.JudgesGrp3, (count_judges == 3))

    # board judge scores visibility (visibility of irrelevant score fields is managed by emptying the text)
    set_source_visibility(JudgeAwardsBoardGrp.GroupName, (count_judges > 0))


def dvov_act_set_event_complete(is_event_complete: bool):
    if is_event_complete:
        set_source_string(EventInfo.Info, f" {event_name} \n Completed")
        set_source_string(EventInfo.DiverNo, " ")
        set_source_string(EventInfo.RoundNo, "Completed")
    else:
        set_source_string(EventInfo.Info, f" {event_name} ")
        set_source_string(EventInfo.DiverNo, " ")
        set_source_string(EventInfo.RoundNo, " ")


def dvov_act_set_event_ab(event_is_a: bool, selected_event_name: str = ""):
    global event_ab_is_a, event_name
    event_ab_is_a = event_is_a
    # Completion text for the newly selected slot needs its own event name.
    event_name = selected_event_name

    # event changed, all data is invalid
    clear_data()


def dvov_act_set_display_enabled(enabled: bool):
    global overlays_enabled
    overlays_enabled = enabled


def dvov_act_render_dive(update: DiveUpdate):
    """Render normalized content; the controller owns selected-event routing."""

    global event_name

    synchro = update.synchro

    #----------------------------------------------------------
    # Event info
    #----------------------------------------------------------
    event_name = update.event.name

    diverLabel = "Divers" if synchro else "Diver"

    diverNo = f"{diverLabel} {update.start_number}/{update.event.diver_count} "
    roundNo = f"Round {update.event.round_number}/{update.event.round_count} "
    event_info = (
        f" {event_name} \n "
        f" {diverNo}"
        f" {roundNo}"
    )

    set_source_string(EventInfo.Info, event_info)
    set_source_string(EventInfo.Title, event_name)
    set_source_string(EventInfo.DiverNo, diverNo)
    set_source_string(EventInfo.RoundNo, roundNo)

    #----------------------------------------------------------
    # Flag
    #----------------------------------------------------------
    def get_flag_path(team_code):
        if not team_code or team_code.strip() == "":
            return ""

        flag_file = os.path.join(flagLoc, team_code + ".png")

        log_info_if_debug(debug, f"Flag file path: {flag_file}")

        if not os.path.isfile(flag_file):
            folder = os.path.dirname(flag_file)
            flag_file = os.path.join(folder, "Default.png")

        log_info_if_debug(debug, f"Flag file path FINAL: {flag_file}")

        return flag_file

    set_source_file(TVBannerGrp.Flag, get_flag_path(update.team1_code))
    set_source_file(MainBoardGrp.Flag1, get_flag_path(update.team1_code))
    set_source_file(MainBoardGrp.Flag2, get_flag_path(update.team2_code))

    #----------------------------------------------------------
    # Diver name
    #----------------------------------------------------------
    set_source_string(MainBoardGrp.Diver1, update.diver1_name)
    set_source_string(MainBoardGrp.Diver2, update.diver2_name)
    set_source_string(TVBannerGrp.Diver, update.banner_name)

    #----------------------------------------------------------
    # Awards?
    # Presentation phase is supplied by the scoring adapter. Historical scores
    # can exist on an upcoming-dive snapshot without selecting the awards view.
    #----------------------------------------------------------
    awards_present = update.phase == DivePhase.Awards

    set_source_string(AwardsCommonGrp.Penalty, "")

    # always hide synchro labels initially
    set_synchro_judge_number(0)
    set_individual_judge_number(0)

    if awards_present:
        # on awards, hide pre-dive info
        set_source_visibility(DiveInfoGrp.GroupName, False)
        set_source_visibility(DiveInfoBoardGrp.GroupName, False)

        # ----- Rank
        # Ensure rank is 3 characters wide for display alignment (text source is buggy with alignment)
        rank = update.rank
        rank = rank.rjust(3)
        set_source_string(TVBannerGrp.Position, rank)

        # ----- Judge lists -----
        count_j = update.judge_count

        if synchro:
            # Populate Execution Judge sources JE1..JE6, JOE1..JOE6
            judge_values = update.awards[:6]

            for i, val in enumerate(judge_values, start=1):
                set_source_string(f"{SynchroAwards.JudgeExecPrefix}{i}", val.rjust(3))
                set_source_string(f"{JudgeAwardsBoardGrp.JExecPrefix}{i}", center_score(val))

            # Populate Synchro Judge sources JS1..JS5, JOS1..JOS5
            judge_values = update.awards[6:11]

            for i, val in enumerate(judge_values, start=1):
                set_source_string(f"{SynchroAwards.JudgeSynchroPrefix}{i}", val.rjust(3))
                set_source_string(f"{JudgeAwardsBoardGrp.JSynchroPrefix}{i}", center_score(val))

        else:
            # Fill in Execution judge values for overlay and board JE1..JE7, JOE1..JOE7
            judge_values = update.awards[:7]

            for i, val in enumerate(judge_values, start=1):
                set_source_string(f"{IndividualAwards.JudgePrefix}{i}", val.rjust(3))
                set_source_string(f"{JudgeAwardsBoardGrp.JExecPrefix}{i}", center_score(val))

            # Clear JS1..JS5, JOS1..JOS5
            clear_values = ["  "] * 5
            for i, val in enumerate(clear_values, start=1):
                set_source_string(f"{SynchroAwards.JudgeSynchroPrefix}{i}", val)
                set_source_string(f"{JudgeAwardsBoardGrp.JSynchroPrefix}{i}", val)

        # Penalty text
        set_source_string(AwardsCommonGrp.Points, update.points)
        set_source_string(AwardsCommonGrp.Penalty, update.penalty_text)
        set_source_string(TVBannerGrp.Total, update.total)

        # show awards sources
        if overlays_enabled:
            set_source_visibility(AwardsCommonGrp.GroupName, True)

            if synchro:
                set_synchro_judge_number(count_j)
            else:
                set_individual_judge_number(count_j)
    else:
        #------------------------------------------------------
        # Pre dive info
        #------------------------------------------------------
        set_source_visibility(AwardsCommonGrp.GroupName, False)
        set_source_visibility(JudgeAwardsBoardGrp.GroupName, False)
        set_source_visibility(SynchroLabelsBoardGrp.GroupName, False)

        # ----- Start No
        # Ensure start number is 3 characters wide for display alignment (text source is buggy with alignment)
        start_no = update.start_number
        start_no = start_no.rjust(3)

        set_source_string(TVBannerGrp.Position, start_no)
        log_info_if_debug(debug, "Pre-dive info branch")
        position = positionText.get(update.position_code, "")

        # set Total points for the next diver
        set_source_string(TVBannerGrp.Total, update.total)

        # Fill in dive info
        set_source_string(DiveInfoGrp.Number, f"{update.dive_number}{update.position_code}")
        set_source_string(DiveInfoGrp.Difficulty, update.difficulty)
        set_source_string(DiveInfoGrp.Board, f"{update.height}m" if update.height else " ")
        set_source_string(DiveInfoGrp.Description, f"{update.description}, {position}")

        # TODO: Consider moving show/hide logics to state_controls and only keep source updates here in overlay_data
        if overlays_enabled:
            set_source_visibility(DiveInfoGrp.GroupName, True)
            set_source_visibility(DiveInfoBoardGrp.GroupName, True)


def set_source_paths():
    global set_source_props_retries

    do_source_exists_check = True

    # set any source paths that depend on root directory here

    # logic here looks too complicated because we need to deal with the fact that on script load,
    # sources might not be available yet, so we have a timer to keep retrying until sources are available,
    # but we also want to avoid infinite loop in case sources are really missing,
    # so we stop retrying after several attempts and log warnings if sources don't exist.
    set_source_props_retries += 1

    if set_source_props_retries > SET_SOURCE_PROPS_RETRIES_MAX_RETRIES:
        do_source_exists_check = False
        obs.timer_remove(set_source_paths) # stop retrying, but still attempt to set source paths one last time (which will log warnings if sources don't exist)

    # Recording and replay video path for Branch Output and Dir Watcher filters
    # Branch Output filter, when enabled, records video currently being played in the source
    # Dir Watcher filter watches the folder and updates the source with the latest video file (used for instant replay)
    recording_video_path = os.path.join(rootDir, "Replay")
    if not is_source_available(InstantReplaySrc.RecScene):
        return
    set_filter_path(InstantReplaySrc.RecScene, InstantReplaySrc.RecSceneFilter, InstantReplaySrc.RecSceneFilterPathSetting, recording_video_path)

    if not is_source_available(InstantReplaySrc.ReplayMediaSrc) and do_source_exists_check:
        return
    set_filter_path(InstantReplaySrc.ReplayMediaSrc, InstantReplaySrc.ReplayMediaSrcFilter, InstantReplaySrc.ReplayMediaSrcFilterPathSetting, recording_video_path)

    # Set playlist for "Play Repeats" source
    play_repeats_playlist_path = os.path.join(rootDir, "Replay")

    if not is_source_available(InstantReplaySrc.PlayRepeatsSrc) and do_source_exists_check:
        return
    set_vlc_playlist(InstantReplaySrc.PlayRepeatsSrc, play_repeats_playlist_path)

    # if we're here, it means we succeeded in setting source paths or we failed (and reported) because sources don't exist and we want to stop retrying
    obs.timer_remove(set_source_paths)


# load state values from persisted script settings
def dvov_act_script_update(settings):
    global flagLoc, rootDir, debug

    debug = obs.obs_data_get_bool(settings, "debug")
    rootDir = obs.obs_data_get_string(settings, "rootDir")
    flagLoc = os.path.join(rootDir, "Media\\Flags")

    # need to do this by timer, because on script load, sources aren't available yet
    obs.timer_add(set_source_paths, 3000)


def dvov_act_script_load(settings):
    dvov_act_script_update(settings)

