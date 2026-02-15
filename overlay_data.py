import typing

if typing.TYPE_CHECKING:
    import _obspython as obs  # full symbol set for IDE
else:
    import obspython as obs   # real runtime module

from datatypes import DiveMessage
from obs_utils import set_filter_path, set_source_string, set_source_file, set_source_visibility, log_info_if_debug, set_vlc_playlist
from enums import DiveInfoBoardGrp, EventInfo, InstantReplaySrc, JudgeAwardsBoardGrp, MainBoardGrp, TVBannerGrp, SynchroJLabels, DiveInfoGrp, JudgeAwardsGrp
import os

flagLoc = ""
rootDir = ""
debug = False
event_name = ""
event_ab_is_a = True  # default to Event A
overlays_enabled = True

# constants (penalty / position lookups)
positionText = {
    "A": "Straight",
    "B": "Pike",
    "C": "Tuck",
    "D": "Free"
}

penaltyText = {
    "0": " ",
    "1": "Failed Dive",
    "2": "Restarted\n(-2 points)",
    "3": "Flight or Danger\n(Max 2 points)",
    "4": "Arm position\n(Max 4½ points)"
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

    set_source_visibility(JudgeAwardsGrp.GroupName, False)
    set_source_visibility(JudgeAwardsBoardGrp.GroupName, False)
    set_source_visibility(SynchroJLabels.JudgesBoard, False)

    for i in range(1, 12):
        set_source_string(f"{SynchroJLabels.JPrefix}{i}", "  ")

        if i <= 7:
            set_source_string(f"{SynchroJLabels.JBExecPrefix}{i}", "  ")

        if i <= 5:
            set_source_string(f"{SynchroJLabels.JBSynchroPrefix}{i}", "  ")

    set_source_visibility(DiveInfoGrp.GroupName, False)
    set_source_visibility(DiveInfoBoardGrp.GroupName, False)


def set_synchro_judge_labels(count_judges):
    # overlay synchro judge labels visibility
    set_source_visibility(SynchroJLabels.Judges11, (count_judges == "11") and overlays_enabled)
    set_source_visibility(SynchroJLabels.Judges9, (count_judges == "9") and overlays_enabled)
    set_source_visibility(SynchroJLabels.Judges7, (count_judges == "7") and overlays_enabled)
    set_source_visibility(SynchroJLabels.Judges5, (count_judges == "5") and overlays_enabled)


def dvov_act_set_event_complete(is_event_complete: bool):
    if is_event_complete:
        set_source_string(EventInfo.Info, f" {event_name} \n Completed")
        set_source_string(EventInfo.DiverNo, " ")
        set_source_string(EventInfo.RoundNo, "Completed")
    else:
        set_source_string(EventInfo.Info, f" {event_name} ")
        set_source_string(EventInfo.DiverNo, " ")
        set_source_string(EventInfo.RoundNo, " ")


def dvov_act_set_event_ab(event_is_a: bool):
    global event_ab_is_a
    event_ab_is_a = event_is_a

    # event changed, all data is invalid
    clear_data()


def dvov_act_set_display_enabled(enabled: bool):
    global overlays_enabled
    overlays_enabled = enabled


def dvov_act_single_event_referee_update(msg: DiveMessage, synchro: bool):
    global event_name

    log_info_if_debug(debug, f"start single_update(), Message Type: {msg.packet_id}")

    if msg.packet_id != "REFEREE":
        return

    # Not "our" event, ignore message (e.g. if Event A message received but currently displaying Event B)
    if (event_ab_is_a and msg.event_ab != "a") or (not event_ab_is_a and msg.event_ab != "b"):
        return

    #----------------------------------------------------------
    # Event info
    #----------------------------------------------------------
    event_name = msg.long_event_name

    diverNo = f"Diver {msg.start_no}/{msg.divers_in_event} "
    roundNo = f"Round {msg.round}/{msg.rounds_in_event} "
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

    set_source_file(TVBannerGrp.Flag, get_flag_path(msg.d1_team_code))
    set_source_file(MainBoardGrp.Flag1, get_flag_path(msg.d1_team_code))
    set_source_file(MainBoardGrp.Flag2, get_flag_path(msg.d2_team_code))

    #----------------------------------------------------------
    # Diver name
    #----------------------------------------------------------
    if synchro:
        displayName = (
            f"{msg.d1_first_name} {msg.d1_family_name} + "
            f"{msg.d2_first_name} {msg.d2_family_name} "
            f"{msg.d1_team_code}/{msg.d2_team_code}"
        )
        set_source_string(MainBoardGrp.Diver1, f"{msg.d1_first_name} {msg.d1_family_name} - {msg.d1_team_code}")
        set_source_string(MainBoardGrp.Diver2, f"{msg.d2_first_name} {msg.d2_family_name} - {msg.d2_team_code}")
    else:
        displayName = msg.d1_full_name_team
        set_source_string(MainBoardGrp.Diver1, displayName)
        set_source_string(MainBoardGrp.Diver2, " ")

    set_source_string(TVBannerGrp.Diver, displayName)

    #----------------------------------------------------------
    # Awards?
    # Awards exist if J1 is not blank
    #----------------------------------------------------------
    awards_present = (msg.j1.strip() != "")

    log_info_if_debug(debug, f"J1 contents: [{msg.j1}]")

    set_source_string(JudgeAwardsGrp.Penalty, "")

    # always hide synchro labels initially
    set_synchro_judge_labels(0)
    set_source_visibility(SynchroJLabels.JudgesBoard, False)

    if awards_present:

        # on awards, hide pre-dive info
        set_source_visibility(DiveInfoGrp.GroupName, False)
        set_source_visibility(DiveInfoBoardGrp.GroupName, False)

        # ----- Rank
        # Ensure rank is 3 characters wide for display alignment (text source is buggy with alignment)
        rank = msg.rank
        rank = rank.rjust(3)
        set_source_string(TVBannerGrp.Position, rank)

        # ----- Judge lists -----
        count_j = msg.number_of_judges

        if synchro:
            set_synchro_judge_labels(count_j)

            if overlays_enabled:
                set_source_visibility(SynchroJLabels.JudgesBoard, True)

            # Fill in board judge values JE1..JE6 and JS1..JS5
            # Populate Execution Judge sources JE1..JE6
            judge_values = [
                    msg.j1, msg.j2, msg.j3, msg.j4, msg.j5, msg.j6
                ]

            for i, val in enumerate(judge_values, start=1):
                set_source_string(f"{SynchroJLabels.JBExecPrefix}{i}", val)

            # Populate Synchro Judge sources JS1..JS5
            judge_values = [
                    msg.j7, msg.j8, msg.j9, msg.j10, msg.j11
                ]

            for i, val in enumerate(judge_values, start=1):
                set_source_string(f"{SynchroJLabels.JBSynchroPrefix}{i}", val)

            # Fill in overlay judge values
            # populate variable judge_values for J1..J11 based on count_j
            if count_j == "11":
                judge_values = [
                    msg.j1, msg.j2, msg.j3, msg.j4, msg.j5, msg.j6,
                    msg.j7, msg.j8, msg.j9, msg.j10, msg.j11
                ]
            elif count_j == "9":
                judge_values = [
                    msg.j1, msg.j2, msg.j3, msg.j4,
                    msg.j7, msg.j8, msg.j9, msg.j10, msg.j11,
                    "  ", "  "
                ]
            elif count_j == "7":
                judge_values = [
                    msg.j1, msg.j2, msg.j3, msg.j4,
                    msg.j7, msg.j8, msg.j9,
                    "  ", "  ", "  ", "  "
                ]
            elif count_j == "5":
                judge_values = [
                    msg.j1, msg.j2,
                    msg.j7, msg.j8, msg.j9,
                    "  ", "  ", "  ", "  ", "  "
                ]
            else:
                obs.script_log(obs.LOG_WARNING, f"Invalid number of synchro judges: {count_j}")

            for i, val in enumerate(judge_values, start=1):
                set_source_string(f"{SynchroJLabels.JPrefix}{i}", val.rjust(2) if i <= int(count_j) else "  ")

        else:
            # Fill in board judge values JE1..JE7 and clear JS1..JS5
            judge_values = [
                    msg.j1, msg.j2, msg.j3, msg.j4, msg.j5, msg.j6, msg.j7
                ]

            for i, val in enumerate(judge_values, start=1):
                set_source_string(f"{SynchroJLabels.JBExecPrefix}{i}", val.rjust(2))
            # Clear JS1..JS5
            clear_values = ["  "] * 5
            for i, val in enumerate(clear_values, start=1):
                set_source_string(f"{SynchroJLabels.JBSynchroPrefix}{i}", val)
            # Fill in overlay judge values
            # mapping of judge values for variable J1..J11
            judge_values = [
                msg.j1, msg.j2, msg.j3, msg.j4, msg.j5, msg.j6,
                msg.j7, msg.j8, msg.j9, msg.j10, msg.j11
            ]

            for i, val in enumerate(judge_values, start=1):
                set_source_string(f"{SynchroJLabels.JPrefix}{i}", val.rjust(2) if i <= int(count_j) else "  ")

        # Penalty text
        penalty = penaltyText.get(msg.penalty_code, " ")

        set_source_string(JudgeAwardsGrp.Points, msg.points)
        set_source_string(JudgeAwardsGrp.Penalty, penalty)
        set_source_string(TVBannerGrp.Total, msg.total)

        # show awards sources
        if overlays_enabled:
            set_source_visibility(JudgeAwardsGrp.GroupName, True)
            set_source_visibility(JudgeAwardsBoardGrp.GroupName, True)

    else:
        #------------------------------------------------------
        # Pre dive info
        #------------------------------------------------------
        set_source_visibility(JudgeAwardsGrp.GroupName, False)
        set_source_visibility(JudgeAwardsBoardGrp.GroupName, False)
        set_source_visibility(SynchroJLabels.JudgesBoard, False)

        # ----- Start No
        # Ensure start number is 3 characters wide for display alignment (text source is buggy with alignment)
        start_no = msg.start_no
        start_no = start_no.rjust(3)

        set_source_string(TVBannerGrp.Position, start_no)
        log_info_if_debug(debug, "Pre-dive info branch")
        position = positionText.get(msg.pos_code, "")

        # set Total points for the next diver
        set_source_string(TVBannerGrp.Total, msg.total)

        # Fill in dive info
        set_source_string(DiveInfoGrp.Number, f"{msg.dive_no}{msg.pos_code}")
        set_source_string(DiveInfoGrp.Difficulty, msg.dd)
        set_source_string(DiveInfoGrp.Board, f"{msg.board}m" if msg.board else " ")
        set_source_string(DiveInfoGrp.Description, f"{msg.dive_description}, {position}")

        # TODO: Consider moving show/hide logics to state_controls and only keep source updates here in overlay_data
        if overlays_enabled:
            set_source_visibility(DiveInfoGrp.GroupName, True)
            set_source_visibility(DiveInfoBoardGrp.GroupName, True)

def set_source_paths(root_dir):
    # set any source paths that depend on root directory here

    # Curtain and curtain logo for instant replay scene
    curtain_file = os.path.join(root_dir, f"Media\\Art\\{InstantReplaySrc.CurtainFile}")

    if not os.path.isfile(curtain_file):
        obs.script_log(obs.LOG_WARNING, f"Curtain file not found: {curtain_file}")
        curtain_file = ""

    set_source_file(InstantReplaySrc.Curtain, curtain_file)

    curtain_logo_file = os.path.join(root_dir, f"Media\\Art\\{InstantReplaySrc.CurtainLogoFile}")
    if not os.path.isfile(curtain_logo_file):
        obs.script_log(obs.LOG_WARNING, f"Curtain logo file not found: {curtain_logo_file}")
        curtain_logo_file = ""

    set_source_file(InstantReplaySrc.CurtainLogo, curtain_logo_file)

    # Recording and replay video path for Branch Output and Dir Watcher filters
    # Branch Output filter, when enabled, records video currently being played in the source
    # Dir Watcher filter watches the folder and updates the source with the latest video file (used for instant replay)
    recording_video_path = os.path.join(root_dir, "Replay")
    try:
        set_filter_path(InstantReplaySrc.RecScene, InstantReplaySrc.RecSceneFilter, InstantReplaySrc.RecSceneFilterPathSetting, recording_video_path)
        set_filter_path(InstantReplaySrc.ReplayMediaSrc, InstantReplaySrc.ReplayMediaSrcFilter, InstantReplaySrc.ReplayMediaSrcFilterPathSetting, recording_video_path)
    except Exception as e:
        obs.script_log(obs.LOG_WARNING, f"Error setting filter paths: {e}")

    # Set playlist for "Play Repeats" source
    play_repeats_playlist_path = os.path.join(root_dir, "Replay")
    set_vlc_playlist(InstantReplaySrc.PlayRepeatsSrc, play_repeats_playlist_path)


# load state values from persisted script settings
def dvov_act_script_update(settings):
    global flagLoc, rootDir, debug

    debug = obs.obs_data_get_bool(settings, "debug")
    rootDir = obs.obs_data_get_string(settings, "rootDir")
    flagLoc = os.path.join(rootDir, "Media\\Flags")

    set_source_paths(rootDir)


def dvov_act_script_load(settings):
    dvov_act_script_update(settings)

