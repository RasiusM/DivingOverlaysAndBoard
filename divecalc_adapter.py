"""Translate DiveCalc JSON snapshots into provider-neutral overlay updates."""

import math
import re
from dataclasses import replace
from datetime import datetime, timezone

from datatypes import DivePhase, DiveUpdate, EventDetails, EventStartUpdate, EventType, RankingEntry, RankingsUpdate, RankingStatus
from diverecorder_adapter import PENALTY_TEXT


def parse_descriptions(text, warn=lambda message: None):
    """Read dive-code descriptions, skipping comments and warning on bad lines."""
    descriptions = {}
    for line_number, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        code, separator, description = line.partition(",")
        if not separator or not code.strip().isdigit() or not description.strip():
            warn(f"Invalid dive description on line {line_number}")
            continue
        descriptions[code.strip()] = description.strip()
    return descriptions


def adapt_event_start(payload, warn=lambda message: None):
    """Read DiveCalc's Unix-millisecond start independently of the action."""
    event = payload.get("event")
    if not isinstance(event, dict) or event.get("startTime") is None:
        return None
    value = event["startTime"]
    try:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("startTime must be a number")
        return EventStartUpdate(datetime.fromtimestamp(value / 1000, timezone.utc))
    except (ValueError, OverflowError, OSError):
        warn("Invalid DiveCalc event startTime")
        return None


def _text(value):
    return "" if value is None else str(value)


def _integer(value):
    # rank format is undocumented; a non-numeric value must not reject the whole list.
    match = re.search(r"\d+", _text(value))
    return int(match.group()) if match else 0


def _ranking_status(entry):
    result = _text(entry.get("result")).strip().upper()
    for status in (RankingStatus.DNS, RankingStatus.DNF, RankingStatus.DQ):
        if result == status.value:
            return status
    return RankingStatus.Unranked if _integer(entry.get("rank")) == 0 else None


def _is_guest(entry, status):
    # Outside-competition captures omit rank and pending but retain numeric scores.
    if status != RankingStatus.Unranked or "pending" in entry or entry.get("rank") not in (None, "", 0, "0"):
        return False
    try:
        score = float(entry.get("result"))
    except (TypeError, ValueError):
        return False
    return math.isfinite(score) and score >= 0


def _ranking_entry(entry, event_type):
    status = _ranking_status(entry)
    return RankingEntry(
        rank=0 if status is not None else _integer(entry.get("rank")),
        points=status.value if status not in (None, RankingStatus.Unranked) else _text(entry.get("result")),
        diver=_display_name(entry, event_type), start_position=_integer(entry.get("position")),
        club_code=_ranking_club_code(entry, event_type), is_guest=_is_guest(entry, status),
        status=status,
    )


def _display_name(entry, event_type):
    # DiveCalc supplies formatted short names, not separate given/family names.
    if event_type in ("SYNCRO", "TEAM"):
        short_name = _text(entry.get("shortName"))
        if short_name.strip():
            return short_name
    return _text(entry.get("name"))


def _ranking_club_code(entry, event_type):
    # Pair/team entries can represent divers from different clubs; the entry's
    # nationality is not a substitute for the individual participant codes.
    if event_type == "TEAM" or (event_type == "SYNCRO" and not _text(entry.get("team")).strip()):
        codes = [_text(participant.get("team")).strip() for participant in (entry.get("participants") or [])]
        codes = [code for code in codes if code]
        if codes:
            return "/".join(codes)
    return _text(entry.get("team") or (entry.get("nationality") if event_type == "TEAM" else ""))


def _penalty(dive, suffix, warn):
    """Translate feed penalty fields to existing overlay text without rescoring."""
    try:
        penalty = dive.get("penalty" + suffix)
        maximum = dive.get("maxAward" + suffix)
        # Empty values mean no penalty and no limit; a real 0 maxAward is a failed dive.
        penalty = 0.0 if penalty in (None, "") else float(penalty)
        maximum = 10.0 if maximum in (None, "") else float(maximum)
        if not math.isfinite(penalty) or not math.isfinite(maximum):
            raise ValueError("non-finite penalty")
    except (TypeError, ValueError):
        warn("Invalid DiveCalc penalty or maxAward")
        return " "
    # Reuse the existing labels for known penalties; retain other values as text.
    if maximum == 0:
        return PENALTY_TEXT["1"]
    if penalty == 2:
        return PENALTY_TEXT["2"]
    if maximum == 2:
        return PENALTY_TEXT["3"]
    if maximum == 4.5:
        return PENALTY_TEXT["4"]
    if penalty > 0:
        return f"Penalty (-{penalty:g} points)"
    if maximum < 10:
        return f"Max {maximum:g} points"
    return " "


def _dive_people(event_type, diver, dive):
    """Select active participants and format their display names."""
    participants = diver.get("participants") or []
    if not isinstance(participants, list):
        raise ValueError("participants must be an array")
    if event_type == "TEAM":
        # The team roster can be larger than the divers in the current dive.
        participants = dive.get("participants") or []
        if not isinstance(participants, list) or not participants:
            raise ValueError("team dive participants missing")

    synchro = event_type == "SYNCRO"
    first = participants[0] if participants else diver
    second = participants[1] if len(participants) > 1 else {}
    first_name = _display_name(first, event_type) or _display_name(diver, event_type)
    second_name = _display_name(second, event_type)
    team1 = _text(first.get("team") or diver.get("team"))
    team2 = _text(second.get("team"))
    if synchro and not second_name:
        raise ValueError("synchro participants missing")
    if event_type == "TEAM":
        banner = " + ".join(_display_name(participant, event_type) for participant in participants)
        if not all(_display_name(participant, event_type) for participant in participants):
            raise ValueError("team dive participant name missing")
        team2 = ""
    else:
        banner = f"{first_name} + {second_name} {team1}/{team2}" if synchro else f"{first_name} {team1}".strip()
    return banner, first_name, second_name, team1, team2, len(participants)


def _panel_and_awards(event_type, event, dive, action, participant_count, warn):
    """Select the dive's panel and validate its awards, or reject its layout."""
    judges = []
    # Events can have multiple panels; use the one assigned to this dive.
    for panel in event.get("judges", {}).get("panels", []):
        if panel.get("panel") == dive.get("panel"):
            judges = panel.get("judges", [])
            break
    if event_type == "TEAM":
        # Team dives use ordinary award slots, not the synchro layout.
        if participant_count > 2 or (judges and (len(judges) not in (3, 5, 7) or any(judge.get("type") for judge in judges))):
            warn("Unsupported DiveCalc team judge layout")
            return None

    awards = []
    if action == "awards":
        awards = dive.get("actualAwards", [])
        if not isinstance(awards, list) or len(awards) > 11:
            raise ValueError("invalid actualAwards")
        if event_type == "TEAM" and len(awards) not in (3, 5, 7):
            warn("Unsupported DiveCalc team judge layout")
            return None
    return judges, awards


def adapt_payload(payload, descriptions=None, warn=lambda message: None):
    """Convert one feed snapshot to a dive update followed by optional rankings.

    Dive and awards actions can produce both updates; startlist and results actions
    produce rankings only. Unsupported or invalid snapshots produce no updates.
    """
    descriptions = descriptions or {}
    try:
        # Stage 1: validate the snapshot and build shared event details.
        if not isinstance(payload, dict):
            raise ValueError("snapshot must be an object")
        action = payload.get("action")
        if action not in ("dive", "awards", "startlist", "results"):
            return []
        event = payload["event"]
        event_type = event["type"]
        # Multiple dives per round have not been mapped to the overlay model.
        if int(event.get("divesPerRound", 1)) > 1:
            warn("Unsupported DiveCalc dives per round")
            return []
        if event_type not in ("NORMAL", "SYNCRO", "TEAM"):
            raise ValueError("unknown event type")
        finished = event.get("finished")
        if not isinstance(finished, bool):
            raise ValueError("event.finished must be boolean")
        results = event.get("results")
        if results is not None and not isinstance(results, list):
            raise ValueError("event.results must be an array")
        # DiveCalc occupies event slot A; completion comes from the feed, not scores.
        details = EventDetails(
            slot="a", meet_title=_text(payload.get("competition")),
            name=_text(event["name"]), round_number=_text(event.get("round")),
            round_count=_text(event.get("rounds")),
            diver_count=_text(len(results)) if results is not None else "",
            finished=finished,
            event_type={"NORMAL": EventType.Individual, "SYNCRO": EventType.Synchro, "TEAM": EventType.Team}[event_type],
        )
        updates = []
        if action in ("dive", "awards"):
            # Stage 2: resolve the dive, active participants and judge panel.
            diver = payload["diver"]
            dive = diver["dive"]
            match = re.fullmatch(r"(\d+)([A-Da-d])", _text(dive["dive"]))
            if not match:
                raise ValueError("invalid dive code")
            synchro = event_type == "SYNCRO"
            banner, first_name, second_name, team1, team2, participant_count = _dive_people(event_type, diver, dive)
            panel_and_awards = _panel_and_awards(event_type, event, dive, action, participant_count, warn)
            if panel_and_awards is None:
                return []
            judges, awards = panel_and_awards

            # Stage 3: map awards and penalties, or prepare the upcoming dive.
            if action == "awards":
                awards = [_text(value) for value in awards]
                judge_count = len(awards)
                if synchro:
                    # The overlay expects six execution slots followed by five
                    # synchronization slots, regardless of feed panel order.
                    if len(judges) == len(awards) and all(judge.get("type") in ("A", "B", "SYNCRO") for judge in judges):
                        paired = list(zip(judges, awards))
                        execution = [value for judge, value in sorted(paired, key=lambda pair: (pair[0].get("type", ""), pair[0].get("position", 0))) if judge["type"] in ("A", "B")]
                        synchronization = [value for judge, value in sorted(paired, key=lambda pair: pair[0].get("position", 0)) if judge["type"] == "SYNCRO"]
                        awards = (execution + [""] * 6)[:6] + (synchronization + [""] * 5)[:5]
                    else:
                        warn("Unknown DiveCalc synchro judge layout; using award order")
                # Retain the reason labels but identify whose penalty is applied.
                penalties = [_penalty(dive, suffix, warn) for suffix in (("A", "B") if synchro else ("",))]
                if synchro:
                    if penalties[0] == penalties[1]:
                        penalty = f"A/B: {penalties[0]}" if penalties[0].strip() else " "
                    else:
                        penalty = "; ".join(
                            f"{suffix}: {value}" for suffix, value in zip(("A", "B"), penalties) if value.strip()
                        )
                else:
                    penalty = penalties[0]
            else:
                # Upcoming snapshots may contain old awards; do not display them.
                judge_count = len(judges)
                penalty = " "
            # Stage 4: build the dive update from the normalized values.
            # The displayed dive position can differ from the event's current round.
            dive_details = replace(details, round_number=_text(dive["position"]))
            status = _ranking_status(diver)
            total = _text(dive.get("total")) if action == "awards" else _text(diver.get("result"))
            rank = _text(diver.get("rank"))
            if status not in (None, RankingStatus.Unranked):
                total = status.value
                rank = ""
            elif status == RankingStatus.Unranked:
                rank = "G" if _is_guest(diver, status) else ""
            updates.append(DiveUpdate(
                event=dive_details, phase=DivePhase.Awards if action == "awards" else DivePhase.Upcoming,
                synchro=synchro, start_number=_text(diver.get("position")), banner_name=banner,
                diver1_name=f"{first_name} - {team1}" if synchro else banner,
                diver2_name=f"{second_name} - {team2}" if synchro else " ",
                team1_code=team1, team2_code=team2, dive_number=match.group(1),
                position_code=match.group(2).upper(), difficulty=_text(dive.get("dd")),
                height=_text(dive.get("height")), description=descriptions.get(match.group(1), ""),
                awards=tuple((awards + [""] * 11)[:11]), judge_count=judge_count,
                penalty_text=penalty, points=_text(dive.get("result")) if action == "awards" else "",
                total=total, rank=rank,
            ))
        if results is not None:
            # Stage 5: append standings after the dive update, when present.
            # A snapshot may carry standings alongside the dive, including an empty list.
            entries = tuple(_ranking_entry(row, event_type) for row in results)
            updates.append(RankingsUpdate(event=details, entries=entries))
        return updates
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        # Reject the entire snapshot so partial updates cannot reach the display.
        warn("Invalid DiveCalc snapshot")
        return []