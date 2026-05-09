from enum import Enum, StrEnum

# Enums for source names and group names to avoid hardcoding strings throughout the codebase

# Top Overlay and Board event info
class EventInfo(StrEnum):
    Info = "EventData"
    Title = "EventTitle"
    DiverNo = "EventDiverNo"
    RoundNo = "EventRoundNo"

# TV Banner Scene (Bottom overlay). Some sources are shared with the board scene.
class TVBannerGrp(StrEnum):
    GroupName = "TVBanner"
    Flag = "Flag"
    Total = "Total"
    Position = "Position_Rank"
    Diver = "Diver"

class SynchroLabelsGrp(StrEnum):
    GroupName = "SynchroLabels"

class SynchroAwards(StrEnum):
    JudgesGrp11 = "SynchroAwards11"
    JudgesGrp9 = "SynchroAwards9"
    JudgesGrp7 = "SynchroAwards7"
    JudgesGrp5 = "SynchroAwards5"
    JudgeExecPrefix = "JOE"
    JudgeSynchroPrefix = "JOS"

class IndividualAwards(StrEnum):
    JudgesGrp7 = "IndividualAwards7"
    JudgesGrp5 = "IndividualAwards5"
    JudgesGrp3 = "IndividualAwards3"
    JudgePrefix = "JOE"

class DiveInfoGrp(StrEnum):
    GroupName = "DiveInfo"
    Number = "Dive_Number"
    Difficulty = "Dive_Difficulty"
    Board = "Dive_Board"
    Description = "Dive_Description"

class AwardsCommonGrp(StrEnum):
    GroupName = "AwardsCommon"
    Points = "Points"
    Penalty = "Penalty"

# Main Board Scene (scene includes shared sources, source names defined in TVBanner scene enums).
class MainBoardGrp(StrEnum):
    GroupName = "MainBoard"
    Flag1 = "Flag1"
    Flag2 = "Flag2"
    Diver1 = "Diver1"
    Diver2 = "Diver2"

# most of sources in this group are shared
class DiveInfoBoardGrp(StrEnum):
    GroupName = "DiveInfoBoard"

# most of sources in this group are shared, judge award sources are hardcoded
class JudgeAwardsBoardGrp(StrEnum):
    GroupName = "JudgeAwardsBoard"
    JExecPrefix = "JE"
    JSynchroPrefix = "JS"

class SynchroLabelsBoardGrp(StrEnum):
    GroupName = "SynchroLabelsBoard"


# Rankings sources
class RankingsSrc(StrEnum):
    LinePrefix = "ListLine "
    BoardLinePrefix = "BoardListLine "
    NamePrefix = "Rnk_Name "
    RankPrefix = "Rnk_Rank "
    TeamPrefix = "Rnk_Team "
    ScorePrefix = "Rnk_Score "
    HeaderMeet = "Rnk_MeetTitle"
    HeaderEvent = "Rnk_EventTitle"
    HeaderListType = "Rnk_ListType"
    ScoreBackground = "Rnk_ScoreBackground"
    # not exactly rankings sources - used in rankings and pre-event scenes
    HeaderArt = "HeaderArt"
    HeaderArtFile = "header_art.png"
    HeaderLogo = "HeaderLogo"
    HeaderLogoFile = "header_logo.png"
    ScheduleText = "ScheduleText"
    ScheduleTextFile = "schedule.txt"

# Instant Replay
class InstantReplaySrc(StrEnum):
    Curtain = "Curtain" # source used as curtain to move-in/move-out effect for replay video
    CurtainFile = "curtain.png"
    CurtainLogo = "CurtainLogo"
    CurtainLogoFile = "curtain_logo.png"
    # Replay video source and filter settings
    RecScene = "Video Source for Replay"
    RecSceneFilter = "BO: Replay Video Source"
    RecSceneFilterPathSetting = "path"
    ReplayMediaSrc = "PlayLatestRecording"
    ReplayMediaSrcFilter = "Set Latest from dir"
    ReplayMediaSrcFilterPathSetting = "dir"
    # Not exactly Instant Replay - source below is used for "Highlights" video
    PlayRepeatsSrc = "Play Repeats"


# Status control sources
class PreEventGrp(StrEnum):
    GroupName = "PreEvent"
    Active = "PreEvent_Background_Active"

class InProgrGrp(StrEnum):
    GroupName = "InProgr"
    Active = "InProgr_Background_Active"
class PostEventGrp(StrEnum):
    GroupName = "PostEvent"
    Active = "PostEvent_Background_Active"
    EventCompleted = "PostEvent_Event_Completed"

class EventABGrp(StrEnum):
    AActive = "EventAB_Background_A_Active"
    BActive = "EventAB_Background_B_Active"

class EventInfoGrp(StrEnum):
    EventType = "Event_Type"
    NoOfJudges = "No_Of_Judges"
    Individual = "EventInfo_Background_Individual"
    Synchro = "EventInfo_Background_Synchro"

class DisableOvrlGrp(StrEnum):
    Status = "DisableOvrl_Status"
    Disabled = "DisableOvrl_Background_Disabled"

class AutoHideGrp(StrEnum):
    Status = "AutoHide_Status"
    Disabled = "AutoHide_Background_Disabled"
class TopOvrlPosGrp(StrEnum):
    Left = "TopOvrlPos_Left"
    Right = "TopOvrlPos_Right"

class TopOverlayGrp(StrEnum):
    Left = "TopLeft"
    Right = "TopRight"

# Other enums
class EventMode(Enum):
    StartList = 1
    Event = 2
    Rankings = 3
    Undefined = 4
