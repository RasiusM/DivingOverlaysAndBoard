'''File for common overlay settings (i.e. not specific to diving software)'''
import typing
import os

if typing.TYPE_CHECKING:
    import _obspython as obs  # full symbol set for IDE
else:
    import obspython as obs   # real runtime module

from state_controls import dvov_state_script_properties, dvov_state_script_defaults, dvov_state_script_update, dvov_state_script_load, dvov_status_register_hotkeys_force
from overlay_data import dvov_act_script_update, dvov_act_script_load, dvov_act_script_properties, dvov_act_script_defaults
from rankings import dvov_rank_add_properties, dvov_rank_script_defaults, dvov_rank_script_update, dvov_rank_script_load, dvov_rank_register_hotkeys, on_rankings_hotkey_stop

# ---------- OBS script lifecycle ----------
def dvov_script_properties(props):
    dvov_act_script_properties(props)
    dvov_state_script_properties(props)

    obs.obs_properties_add_bool(props, "rankings_enabled", "Rankings Enabled")

    dvov_rank_add_properties(props)

    obs.obs_properties_add_bool(props, "debug", "Show debug data in Log file")

    return props


def dvov_script_defaults(settings):
    dvov_act_script_defaults(settings)
    dvov_rank_script_defaults(settings)
    dvov_state_script_defaults(settings)

    obs.obs_data_set_default_bool(settings, "debug", False)
    obs.obs_data_set_default_bool(settings, "rankings_enabled", True)


def dvov_script_update(settings):
    dvov_rank_script_update(settings)
    dvov_state_script_update(settings)
    dvov_act_script_update(settings)


def dvov_script_load(settings):
    dvov_status_register_hotkeys_force()
    dvov_rank_register_hotkeys(settings)

    dvov_rank_script_load(settings)
    dvov_state_script_load(settings)
    dvov_act_script_load(settings)

def dvov_script_unload():
    on_rankings_hotkey_stop(True)

