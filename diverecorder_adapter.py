"""Translate DiveRecorder protocol records into overlay updates."""

from typing import Sequence

from datatypes import (
    DiveListRecord, DiveMessage, DivePhase, DiveUpdate, EventDetails,
    RankingEntry, RankingsUpdate,
)


# These are DiveRecorder reason codes, not deduction amounts. Resolve them here
# so the renderer does not need to understand a scoring program's protocol.
PENALTY_TEXT = {
    "0": " ",
    "1": "Failed Dive",
    "2": "Restarted (-2 points)",
    "3": "Flight or Danger (Max 2 points)",
    "4": "Arm position (Max 4\u00bd points)",
}


def event_details(message: DiveMessage) -> EventDetails:
    """Extract the event context used by both REFEREE and UPDATE records."""

    return EventDetails(
        slot=message.event_ab,
        meet_title=message.meet_title,
        name=message.long_event_name,
        round_number=message.round,
        round_count=message.rounds_in_event,
        diver_count=message.divers_in_event,
    )


def adapt_dive(message: DiveMessage) -> DiveUpdate:
    """Preserve DiveRecorder's display values without recomputing scores."""

    synchro = message.synchro_event == "True"
    # Keep the existing banner and board name formats, including team codes.
    if synchro:
        first_name = f"{message.d1_first_name} {message.d1_family_name}"
        second_name = f"{message.d2_first_name} {message.d2_family_name}"
        banner_name = (
            f"{first_name} + {second_name} "
            f"{message.d1_team_code}/{message.d2_team_code}"
        )
        diver1_name = f"{first_name} - {message.d1_team_code}"
        diver2_name = f"{second_name} - {message.d2_team_code}"
    else:
        banner_name = message.d1_full_name_team
        diver1_name = banner_name
        diver2_name = " "

    # DiveRecorder distinguishes pre-dive information from accepted awards by
    # leaving J1 blank. Translate that convention once, not in each OBS layer.
    return DiveUpdate(
        event=event_details(message),
        phase=DivePhase.Awards if message.j1.strip() else DivePhase.Upcoming,
        synchro=synchro,
        start_number=message.start_no,
        banner_name=banner_name,
        diver1_name=diver1_name,
        diver2_name=diver2_name,
        team1_code=message.d1_team_code,
        team2_code=message.d2_team_code,
        dive_number=message.dive_no,
        position_code=message.pos_code,
        difficulty=message.dd,
        height=message.board,
        description=message.dive_description,
        awards=tuple(getattr(message, f"j{number}") for number in range(1, 12)),
        judge_count=int(message.number_of_judges) if message.number_of_judges.isdigit() else 0,
        penalty_text=PENALTY_TEXT.get(message.penalty_code, " "),
        points=message.points,
        total=message.total,
        rank=message.rank,
    )


def adapt_rankings(records: Sequence[DiveListRecord], message: DiveMessage) -> RankingsUpdate:
    """Translate signed guest ranks and detach the list from mutable parsing data."""

    # Negative ranks retain their placement but identify guests; zero follows
    # the existing unranked/guest filtering policy. Other providers need not use
    # signed ranks because the shared model carries guest status explicitly.
    return RankingsUpdate(
        event=event_details(message),
        entries=tuple(
            RankingEntry(
                rank=abs(record.rank),
                points=record.points,
                diver=record.diver,
                start_position=record.start_position,
                club_code=record.club_code,
                is_guest=record.rank <= 0,
            )
            for record in records
        ),
    )