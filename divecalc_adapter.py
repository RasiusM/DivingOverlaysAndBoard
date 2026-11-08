"""Translate DiveCalc JSON snapshots into provider-neutral overlay updates."""

import math
import re

from datatypes import DivePhase, DiveUpdate, EventDetails, RankingEntry, RankingsUpdate
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


def _text(value):
    return "" if value is None else str(value)


def _integer(value):
    # Start lists may have no rank or start position yet.
    return int(value) if value not in (None, "") else 0


def _penalty(dive, suffix, warn):
    """Translate feed penalty fields to existing overlay text without rescoring."""
    try:
        penalty = float(dive.get("penalty" + suffix, 0) or 0)
        maximum = float(dive.get("maxAward" + suffix, 10) or 0)
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
    first_name = _text(first.get("name") or diver.get("name"))
    second_name = _text(second.get("name"))
    team1 = _text(first.get("team") or diver.get("team"))
    team2 = _text(second.get("team"))
    if synchro and not second_name:
        raise ValueError("synchro participants missing")
    if event_type == "TEAM":
        banner = " + ".join(_text(participant.get("name")) for participant in participants)
        if not all(participant.get("name") for participant in participants):
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
            warn("Unsupported DiveCalc team event")
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
                # Synchro penalties can differ for A and B; show distinct texts once.
                penalties = [_penalty(dive, suffix, warn) for suffix in (("A", "B") if synchro else ("",))]
                penalty = "; ".join(dict.fromkeys(value for value in penalties if value.strip())) or " "
            else:
                # Upcoming snapshots may contain old awards; do not display them.
                judge_count = len(judges)
                penalty = " "
            # Stage 4: build the dive update from the normalized values.
            # The displayed dive position can differ from the event's current round.
            dive_details = EventDetails(**{**vars(details), "round_number": _text(dive["position"])})
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
                total=_text(dive.get("total")) if action == "awards" else _text(diver.get("result")),
                rank=_text(diver.get("rank")),
            ))
        if results is not None:
            # Stage 5: append standings after the dive update, when present.
            # A snapshot may carry standings alongside the dive, including an empty list.
            entries = tuple(RankingEntry(
                rank=_integer(row.get("rank")), points=_text(row.get("result")),
                diver=_text(row.get("name")), start_position=_integer(row.get("position")),
                club_code=_text(row.get("team") or (row.get("nationality") if event_type == "TEAM" else "")), is_guest=False,
            ) for row in results)
            updates.append(RankingsUpdate(event=details, entries=entries))
        return updates
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        # Reject the entire snapshot so partial updates cannot reach the display.
        warn("Invalid DiveCalc snapshot")
        return []