import typing

if typing.TYPE_CHECKING:
    import _obspython as obs  # full symbol set for IDE
else:
    import obspython as obs   # real runtime module

from datatypes import DiveMessage
from obs_utils import set_source_string, set_source_file, set_source_visibility
import os

flagLoc = ""
debug = False

# constants (penalty / position lookups)
positionText = {
    "A": "Straight",
    "B": "Pike",
    "C": "Tuck",
    "D": "Free"
}

penaltyText = {
    "0": " ",
    "1": "Failed Dive   ",
    "2": "Restarted (-2 points)",
    "3": "Flight or Danger (Max 2 points)",
    "4": "Arm position (Max 4½ points)"
}


def dvov_act_set_data (flagLocation: str, debug_flag: bool):
    global debug, flagLoc
    debug = debug_flag

    if debug:
        obs.script_log(obs.LOG_INFO, f"Setting flag location to: {flagLoc}")

    flagLoc = flagLocation

def dvov_act_set_synchro_judge_labels(count_judges):
    set_source_visibility("SynchroJLabels11", False)
    set_source_visibility("SynchroJLabels9", False)
    set_source_visibility("SynchroJLabels7", False)
    set_source_visibility("SynchroJLabels5", False)
    set_source_visibility("SynchroJLabelsStatic", True)

    if count_judges == "11":
        set_source_visibility("SynchroJLabels11", True)
    elif count_judges == "9":
        set_source_visibility("SynchroJLabels9", True)
    elif count_judges == "7":
        set_source_visibility("SynchroJLabels7", True)
    elif count_judges == "5":
        set_source_visibility("SynchroJLabels5", True)


# ---------- String insert helper (keeps string length) ----------
def string_insert(str1, str2, pos):
    # Lua used 0-based pos; Python slicing uses 0-based so it's similar.
    # If pos beyond len(str1) it's allowed but we will print a warning like Lua does.
    lenstr1 = len(str1)
    lenstr2 = len(str2)
    if (lenstr2 + pos) > lenstr1:
        obs.script_log(obs.LOG_WARNING, f"string_insert length overrun by: {((lenstr2 + pos) - lenstr1)}, str1: {str1}, str2: {str2}")
    return str1[:pos] + str2 + str1[pos + lenstr2:]


def dvov_act_single_event_referee_update(msg: DiveMessage, synchro: bool):
    if debug:
        obs.script_log(obs.LOG_INFO, f"start single_update(), Message Type: {msg.packet_id}")

    if msg.packet_id != "REFEREE":
        return

    #----------------------------------------------------------
    # Event info
    #----------------------------------------------------------
    event_info = (
        f" {msg.long_event_name} \n"
        f" Diver {msg.start_no}/{msg.divers_in_event} "
        f" Round {msg.round}/{msg.rounds_in_event} "
    )

    set_source_string("EventData", event_info)

    #----------------------------------------------------------
    # Flag
    #----------------------------------------------------------
    def get_flag_path(team_code):
        flag_file = os.path.join(flagLoc, team_code + ".png")

        print(f"Flag file path: {flag_file}")

        if not os.path.isfile(flag_file):
            folder = os.path.dirname(flag_file)
            flag_file = os.path.join(folder, "Default.png")

        print(f"Flag file path FINAL: {flag_file}")

        return flag_file

    set_source_file("Flag", get_flag_path(msg.d1_team_code))
    set_source_file("Flag1", get_flag_path(msg.d1_team_code))
    set_source_file("Flag2", get_flag_path(msg.d2_team_code))

    #----------------------------------------------------------
    # Diver name
    #----------------------------------------------------------
    if synchro:
        displayName = (
            f"{msg.d1_first_name} {msg.d1_family_name} + "
            f"{msg.d2_first_name} {msg.d2_family_name} "
            f"{msg.d1_team_code}/{msg.d2_team_code}"
        )
        set_source_string("Diver1", f"{msg.d1_first_name} {msg.d1_family_name} - {msg.d1_team_code}")
        set_source_string("Diver2", f"{msg.d2_first_name} {msg.d2_family_name} - {msg.d2_team_code}")
    else:
        displayName = msg.d1_full_name_team

    set_source_string("Diver", displayName)

    #----------------------------------------------------------
    # Awards?
    # Awards exist if J1 is not blank
    #----------------------------------------------------------
    awards_present = (msg.j1.strip() != "")

    print(f"J1 contents: [{msg.j1}]")

    set_source_string("Penalty", "")

    if awards_present:

        # ----- Rank 
        # Ensure rank is 3 characters wide for display alignment (text source is buggy with alignment)
        rank = msg.rank
        rank = rank.rjust(3)
        set_source_string("Position_Rank", rank)

        # ----- Judge lists -----
        count_j = msg.number_of_judges

        print("I'm here - awards branch!")

        # always hide synchro labels initially
        dvov_act_set_synchro_judge_labels(0)

        if synchro:
            dvov_act_set_synchro_judge_labels(count_j)

            # Populate fixed Execution Judge sources JE1..JE6
            judge_values = [
                    msg.j1, msg.j2, msg.j3, msg.j4, msg.j5, msg.j6
                ]
            
            for i, val in enumerate(judge_values, start=1):
                set_source_string(f"JE{i}", val)

            # Populate Synchro Judge sources JS1..JS5 based on count_j
            judge_values = [
                    msg.j7, msg.j8, msg.j9, msg.j10, msg.j11
                ]
            
            for i, val in enumerate(judge_values, start=1):
                set_source_string(f"JS{i}", val)

            # populate variable judge_values for J1..J11 based on count_j
            if count_j == "11":
                judge_values = [
                    msg.j1, msg.j2, msg.j3, msg.j4, msg.j5, msg.j6,
                    msg.j7, msg.j8, msg.j9, msg.j10, msg.j11
                ]
            elif count_j == "9":
                judge_values = [
                    msg.j1, msg.j2, msg.j3, msg.j4, 
                    msg.j7, msg.j8, msg.j9, msg.j10, msg.j11
                ]
            elif count_j == "7":
                judge_values = [
                    msg.j1, msg.j2, msg.j3, msg.j4, 
                    msg.j7, msg.j8, msg.j9
                ]
            elif count_j == "5":
                judge_values = [
                    msg.j1, msg.j2,  
                    msg.j7, msg.j8, msg.j9
                ]
            else:
                obs.script_log(obs.LOG_WARNING, f"Invalid number of synchro judges: {count_j}")
        else:
            judge_values = [
                    msg.j1, msg.j2, msg.j3, msg.j4, msg.j5, msg.j6, msg.j7
                ]
            
            for i, val in enumerate(judge_values, start=1):
                set_source_string(f"JE{i}", val)

            # Clear JS1..JS5
            clear_values = [" "] * 5
            for i, val in enumerate(clear_values, start=1):
                set_source_string(f"JS{i}", val)

            # mapping of judge values for variable J1..J11
            judge_values = [
                msg.j1, msg.j2, msg.j3, msg.j4, msg.j5, msg.j6,
                msg.j7, msg.j8, msg.j9, msg.j10, msg.j11
            ]

        # Populate J1..J11
        for i, val in enumerate(judge_values, start=1):
            set_source_string(f"J{i}", val if i <= int(count_j) else " ")

        # Penalty text
        penalty = penaltyText.get(msg.penalty_code, " ")

        set_source_string("Points", msg.points)
        set_source_string("Penalty", penalty)
        set_source_string("Total", msg.total)

        set_source_visibility("JudgeAwards", True)
        set_source_visibility("DiveInfo", False)

        # event complete?
        if msg.start_no == msg.divers_in_event and msg.round == msg.rounds_in_event:
            event_complete = True
            set_source_visibility("Event_Complete", True)
        else:
            set_source_visibility("Event_Complete", False)

    else:
        #------------------------------------------------------
        # Pre dive info
        #------------------------------------------------------
        # ----- Start No 
        # Ensure start number is 3 characters wide for display alignment (text source is buggy with alignment)
        start_no = msg.start_no
        start_no = start_no.rjust(3)

        print(f"Start No after rjust: [{start_no}]")

        set_source_string("Position_Rank", start_no)

        print("Pre-dive info branch")
        position = positionText.get(msg.pos_code, "")

        set_source_string("Dive_Number", f"{msg.dive_no}{msg.pos_code}")
        set_source_string("Dive_Difficulty", msg.dd)
        set_source_string("Dive_Board", f"{msg.board}m" if msg.board else " ")
        set_source_string("Dive_Description", f"{msg.dive_description}, {position}")

        set_source_visibility("JudgeAwards", False)
        set_source_visibility("DiveInfo", True)

    #----------------------------------------------------------
    # TV Banner
    #----------------------------------------------------------
    set_source_visibility("TVBanner", True)

# Not used
def dvov_act_sim_event_referee_update(v, event_position_left: bool, synchro: bool, debug: bool):
    if synchro:
        obs.script_log(obs.LOG_INFO, "ERROR - Can't display Synchro event in simultaneous mode")

    # clear appropriate EventData to blank
    if event_position_left:
        set_source_string("EventData_A", " ")
    else:
        set_source_string("EventData_B", " ")

    def L(i):
        if i-1 < len(v) and i-1 >= 0:
            return v[i-1]
        return ""

    set_source_visibility("Event A", True)
    #set_source_visibility("EventData_A", True)
    set_source_visibility("Event B", True)
    #set_source_visibility("EventData_B", True)

    if L(32) == "":
        v[31] = " "
        if debug:
            obs.script_log(obs.LOG_INFO, "Nil detected in Rank field (first round?)")

    # prepare lines
    lineOne = " " * 40
    lineTwo = " " * 40
    lineThree = " " * 40

    if L(17) != " " and L(17) != "":
        # awards branch
        display1a = " " + L(60) + "  "
        display1b = " Dvr " + L(8) + "/" + L(64) + " "
        display1c = " Rnd " + L(6) + "/" + L(63) + " "
        lineOne = string_insert(lineOne, display1a, 0)
        lineOne = string_insert(lineOne, display1c, 33)

        # penalty
        penalty = penaltyText.get(L(51), " ")
        # awards string (concatenate judges)
        awards = "  ".join([L(i) for i in range(17,24)])
        display3a = L(29)
        lineThree = string_insert(lineThree, awards, 0)
        lineThree = string_insert(lineThree, display3a, 34)
    else:
        display1a = " " + L(60) + "  "
        display1b = " Dvr " + L(8) + "/" + L(64) + " "
        display1c = " Rnd " + L(6) + "/" + L(63) + " "
        lineOne = string_insert(lineOne, display1a, 0)
        lineOne = string_insert(lineOne, display1b, 33)
        pos_code = L(14)
        position = positionText.get(pos_code, "")
        board = " "
        if L(16) in ["1", "3", "5", "7.5", "10"]:
            board = " " + L(16) + "m"
        dive_info = f"{L(13)}{L(14)} (DD: {L(15)}) "
        display3a = f"{dive_info}{L(61)}{position}{board}"
        lineThree = string_insert(lineThree, display3a, 0)

    display2a = L(32) + " "
    display2b = L(9)
    display2c = " " + L(30)

    lineTwo = string_insert(lineTwo, display2a, 0)
    lineTwo = string_insert(lineTwo, display2b, 4)
    lineTwo = string_insert(lineTwo, display2c, 34)

    displayText = lineOne + "\n" + lineTwo + "\n" + lineThree

    # Fill in source on appropriate EventData side
    set_source_string("EventData_A" if event_position_left else "EventData_B", displayText)