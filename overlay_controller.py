"""Apply provider-neutral updates on the OBS timer thread."""

from datatypes import DiveUpdate, EventType, RankingsUpdate
from overlay_data import dvov_act_render_dive, dvov_act_set_event_complete
from rankings import dvov_rank_set_divers
from state_controls import (
    completed_slots, event_names,
    dvov_state_is_selected_event, dvov_state_on_dive,
    dvov_state_set_event_complete, dvov_state_store_completion,
    dvov_state_store_dive, dvov_state_store_event, set_event_type,
)


def apply_dive(update: DiveUpdate):
    """Apply a selected dive on the OBS thread, never in a network worker."""

    # Every slot is retained for A/B switching; only the selected one is displayed.
    dvov_state_store_dive(update)
    was_complete = update.event.slot in completed_slots
    if update.event.finished is not None:
        dvov_state_store_completion(update.event.slot, update.event.finished)
    if not dvov_state_is_selected_event(update.event.slot):
        return
    # Visibility/autohide and source content consume the same presentation phase.
    dvov_state_on_dive(update)
    dvov_act_render_dive(update)
    is_complete = update.event.slot in completed_slots
    if is_complete:
        dvov_act_set_event_complete(True)
    if is_complete != was_complete:
        dvov_state_set_event_complete(is_complete)


def apply_rankings(update: RankingsUpdate, show_rankings=True):
    """Route lists without changing the operator's F1/F2/F3 display mode."""

    previous_name = event_names.get(update.event.slot)
    dvov_state_store_event(update.event.slot, update.event.name)
    was_complete = update.event.slot in completed_slots
    if update.event.finished is not None:
        dvov_state_store_completion(update.event.slot, update.event.finished)
    if dvov_state_is_selected_event(update.event.slot):
        if update.event.event_type is not None:
            set_event_type(update.event.event_type == EventType.Synchro,
                           update.event.event_type == EventType.Team)
        if show_rankings:
            dvov_rank_set_divers(update)
        is_complete = update.event.slot in completed_slots
        if is_complete != was_complete:
            dvov_act_set_event_complete(is_complete, update.event.name)
            dvov_state_set_event_complete(is_complete)
        elif is_complete and previous_name != update.event.name:
            dvov_act_set_event_complete(True, update.event.name)


def complete_event(slot: str):
    """Update completion text/status without selecting a results scene or mode."""

    dvov_state_store_completion(slot, True)
    if dvov_state_is_selected_event(slot):
        dvov_act_set_event_complete(True)
        dvov_state_set_event_complete(True)