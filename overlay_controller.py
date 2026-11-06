"""Apply provider-neutral updates on the OBS timer thread."""

from datatypes import DiveUpdate, RankingsUpdate
from overlay_data import dvov_act_render_dive, dvov_act_set_event_complete
from rankings import dvov_rank_set_divers
from state_controls import (
    dvov_state_is_selected_event, dvov_state_on_dive,
    dvov_state_set_event_complete, dvov_state_store_completion,
    dvov_state_store_dive,
)


def apply_dive(update: DiveUpdate):
    """Apply a selected dive on the OBS thread, never in a network worker."""

    # Every slot is retained for A/B switching; only the selected one is displayed.
    dvov_state_store_dive(update)
    # DiveRecorder convention: a REFEREE update means the event is live again.
    dvov_state_store_completion(update.event.slot, False)
    if not dvov_state_is_selected_event(update.event.slot):
        return
    # Visibility/autohide and source content consume the same presentation phase.
    dvov_state_on_dive(update)
    dvov_act_render_dive(update)
    # Preserve DiveRecorder behavior: a REFEREE update resumes the live display.
    # Event completion is delivered separately through complete_event().
    dvov_state_set_event_complete(False)


def apply_rankings(update: RankingsUpdate):
    """Route lists without changing the operator's F1/F2/F3 display mode."""

    if dvov_state_is_selected_event(update.event.slot):
        dvov_rank_set_divers(update)


def complete_event(slot: str):
    """Update completion text/status without selecting a results scene or mode."""

    dvov_state_store_completion(slot, True)
    if dvov_state_is_selected_event(slot):
        dvov_act_set_event_complete(True)
        dvov_state_set_event_complete(True)