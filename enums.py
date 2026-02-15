from enum import Enum

# Enums for source names and group names to avoid hardcoding strings throughout the codebase

# Top Overlay and Board event info
class EventInfo(str, Enum):
    Info = "EventData"
    Title = "EventTitle"
    DiverNo = "EventDiverNo"
    RoundNo = "EventRoundNo"

# TV Banner Scene (Bottom overlay). Some sources are shared with the board scene.
class TVBannerGrp(str, Enum):
    GroupName = "TVBanner"
    Flag = "Flag"
    Total = "Total"
    Position = "Position_Rank"
    Diver = "Diver"

class SynchroJLabels(str, Enum):
    Judges11 = "SynchroJLabels11"
    Judges9 = "SynchroJLabels9"
    Judges7 = "SynchroJLabels7"
    Judges5 = "SynchroJLabels5"
    JudgesBoard = "SynchroJLabelsBoard"
    JPrefix = "J"
    JBSynchroPrefix = "JS"
    JBExecPrefix = "JE"


class DiveInfoGrp(str, Enum):
    GroupName = "DiveInfo"
    Number = "Dive_Number"
    Difficulty = "Dive_Difficulty"
    Board = "Dive_Board"
    Description = "Dive_Description"

class JudgeAwardsGrp(str, Enum):
    GroupName = "JudgeAwards"
    Points = "Points"
    Penalty = "Penalty"

# Main Board Scene (scene includes shared sources, source names defined in TVBanner scene enums).
class MainBoardGrp(str, Enum):
    GroupName = "MainBoard"
    Flag1 = "Flag1"
    Flag2 = "Flag2"
    Diver1 = "Diver1"
    Diver2 = "Diver2"

# most of sources in this group are shared
class DiveInfoBoardGrp(str, Enum):
    GroupName = "DiveInfoBoard"

# most of sources in this group are shared, judge award sources are hardcoded
class JudgeAwardsBoardGrp(str, Enum):
    GroupName = "JudgeAwardsBoard"

# Rankings sources
class RankingsSrc(str, Enum):
    LinePrefix = "ListLine "
    BoardLinePrefix = "BoardListLine "
    NamePrefix = "Rnk_Name "
    RankPrefix = "Rnk_Rank "
    TeamPrefix = "Rnk_Team "
    ScorePrefix = "Rnk_Score "
    HeaderMeet = "Rnk_MeetTitle"
    HeaderEvent = "Rnk_EventTitle"
    # not exactly rankings sources - used in rankings and pre-event scenes
    HeaderArt = "HeaderArt"
    HeaderArtFile = "header_art.png"
    HeaderLogo = "HeaderLogo"
    HeaderLogoFile = "header_logo.png"
    ScheduleText = "ScheduleText"
    ScheduleTextFile = "schedule.txt"

# Instant Replay
class InstantReplaySrc(str, Enum):
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
class PreEventGrp(str, Enum):
    GroupName = "PreEvent"
    Active = "PreEvent_Background_Active"

class InProgrGrp(str, Enum):
    GroupName = "InProgr"
    Active = "InProgr_Background_Active"
class PostEventGrp(str, Enum):
    GroupName = "PostEvent"
    Active = "PostEvent_Background_Active"
    EventCompleted = "PostEvent_Event_Completed"

class EventABGrp(str, Enum):
    AActive = "EventAB_Background_A_Active"
    BActive = "EventAB_Background_B_Active"

class EventInfoGrp(str, Enum):
    EventType = "EventInfo"
    NoOfJudges = "No_Of_Judges"
    Individual = "EventInfo_Background_Individual"
    Synchro = "EventInfo_Background_Synchro"

class DisableOvrlGrp(str, Enum):
    Status = "DisableOvrl_Status"
    Disabled = "DisableOvrl_Background_Disabled"

class AutoHideGrp(str, Enum):
    Status = "AutoHide_Status"
    Disabled = "AutoHide_Background_Disabled"
class TopOvrlPosGrp(str, Enum):
    Left = "TopOvrlPos_Left"
    Right = "TopOvrlPos_Right"

class TopOverlayGrp(str, Enum):
    Left = "TopLeft"
    Right = "TopRight"

# Other enums
class EventMode(Enum):
    StartList = 1
    Event = 2
    Rankings = 3
    Undefined = 4