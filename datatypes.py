from dataclasses import dataclass

# ---- Class to store REFEREE message contents ----
@dataclass
class DiveMessage:
    packet_id: str                 #  1
    event_ab: str                  #  2
    sending_computer_id: str       #  3
    event_mode: str                #  4
    event_status: str              #  5
    round: str                     #  6
    attempt: str                   #  7
    start_no: str                  #  8
    d1_full_name_team: str         #  9
    d1_family_name: str            # 10
    d2_full_name_team: str         # 11
    d2_family_name: str            # 12
    dive_no: str                   # 13
    pos_code: str                  # 14
    dd: str                        # 15
    board: str                     # 16
    j1: str                        # 17
    j2: str                        # 18
    j3: str                        # 19
    j4: str                        # 20
    j5: str                        # 21
    j6: str                        # 22
    j7: str                        # 23
    j8: str                        # 24
    j9: str                        # 25
    j10: str                       # 26
    j11: str                       # 27
    judge_total: str               # 28
    points: str                    # 29
    total: str                     # 30
    scoreboard_display_mode: str   # 31
    rank: str                      # 32
    prediction: str                # 33
    likely_rank: str               # 34
    background_color: str          # 35
    atext_color: str               # 36
    btext_color: str               # 37
    caption_color: str             # 38
    message1: str                  # 39
    message2: str                  # 40
    message3: str                  # 41
    message4: str                  # 42
    message5: str                  # 43
    message6: str                  # 44
    message7: str                  # 45
    message8: str                  # 46
    synchro_event: str             # 47
    show_running_total: str        # 48
    show_prediction: str           # 49
    number_of_judges: str          # 50
    penalty_code: str              # 51
    station_no: str                # 52
    number_of_stations: str        # 53
    d1_first_name: str             # 54
    d1_team_name: str              # 55
    d1_team_code: str              # 56
    d2_first_name: str             # 57
    d2_team_name: str              # 58
    d2_team_code: str              # 59
    long_event_name: str           # 60
    dive_description: str          # 61
    meet_title: str                # 62
    rounds_in_event: str           # 63
    divers_in_event: str           # 64
    short_dive_description: str    # 65
    conversion_factor: str         # 66
    short_event_name: str          # 67
    team_a2: str                   # 68
    team_code_a2: str              # 69
    team_b2: str                   # 70
    team_code_b2: str              # 71
    seconds_per_dive: str          # 72
    dvov_not_rank_flag: str          # 73
    team_event: str                # 74

@dataclass
class DiveListRecord:
    rank: int
    points: str
    unknown: str
    diver: str
    start_position: int
    club_code: str

