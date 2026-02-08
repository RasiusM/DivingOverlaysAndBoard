import obspython as obs
import os
import time

# -------------------------
# Script settings
# -------------------------
folder_path = ""
media_source_name = ""
check_interval = 2000  # milliseconds
_timer_active = False

# -------------------------
# Logging helper
# -------------------------
def log(msg):
    obs.script_log(obs.LOG_INFO, "[LatestFile] " + str(msg))


# -------------------------
# Find newest video in folder
# -------------------------
def get_latest_video(folder):
    if not os.path.isdir(folder):
        log("Folder does not exist: " + folder)
        return None

    latest_file = None
    latest_time = 0

    for name in os.listdir(folder):
        path = os.path.join(folder, name)
        if os.path.isfile(path) and name.lower().endswith(
            (".mp4", ".mov", ".avi", ".mkv", ".webm")
        ):
            mtime = os.path.getmtime(path)
            if mtime > latest_time:
                latest_time = mtime
                latest_file = path

    return latest_file


# -------------------------
# Update Media Source
# -------------------------
def update_media_source():
    global folder_path, media_source_name

    if not media_source_name:
        log("Media source name missing.")
        return

    latest = get_latest_video(folder_path)

    src = obs.obs_get_source_by_name(media_source_name)
    if not src:
        log("Source not found: " + media_source_name)
        return

    settings = obs.obs_source_get_settings(src)

    if latest:
        obs.obs_data_set_string(settings, "local_file", latest)
        #log(f"Updated '{media_source_name}' → {latest}")
    else:
        obs.obs_data_set_string(settings, "local_file", "")
        #log(f"No video found in folder, clearing source '{media_source_name}'")

    obs.obs_source_update(src, settings)

    obs.obs_data_release(settings)
    obs.obs_source_release(src)


# -------------------------
# Timer callback
# -------------------------
def timer_callback():
    update_media_source()


# -------------------------
# Hotkey
# -------------------------
_hotkey_start_id = None
_hotkey_stop_id = None


# def hotkey_pressed(pressed):
#     if pressed:
#         update_media_source()


# ---------------------------
# Hotkeys
# ---------------------------
def on_hotkey_start(pressed):
    if pressed:
        # Start timer once
        global _timer_active
        if not _timer_active:
            obs.timer_add(timer_callback, check_interval)
            _timer_active = True

        log("Started updating latest file.")


def on_hotkey_stop(pressed):
    if pressed:
        # Stop timer
        global _timer_active
        if _timer_active:
            obs.timer_remove(timer_callback)
            _timer_active = False

        log("Stopped updating latest file.")


# -------------------------
# OBS Script API
# -------------------------
def script_description():
    return "Monitors a folder and always loads the latest video into a Media Source."


def script_properties():
    props = obs.obs_properties_create()

    obs.obs_properties_add_path(
        props,
        "folder_path",
        "Folder to watch",
        obs.OBS_PATH_DIRECTORY,
        None,
        None,
    )

    obs.obs_properties_add_text(
        props,
        "media_source_name",
        "Media Source name",
        obs.OBS_TEXT_DEFAULT,
    )

    obs.obs_properties_add_int(
        props,
        "interval",
        "Check interval (ms)",
        200,
        10000,
        100,
    )

    return props


def script_update(settings):
    global folder_path, media_source_name, check_interval, _timer_active

    folder_path = obs.obs_data_get_string(settings, "folder_path")
    media_source_name = obs.obs_data_get_string(settings, "media_source_name")
    check_interval = obs.obs_data_get_int(settings, "interval")

    # Never auto-restart the timer unless it's supposed to run
    obs.timer_remove(timer_callback)

    if _timer_active and folder_path and media_source_name:
        obs.timer_add(timer_callback, check_interval)


def script_load(settings):
    global _hotkey_start_id, _hotkey_stop_id

    # Register start hotkey
    _hotkey_start_id = obs.obs_hotkey_register_frontend(
        "latest_file.start", "Start Updating Latest File Cycle", on_hotkey_start)
    arr = obs.obs_data_get_array(settings, "latest_file.start")
    obs.obs_hotkey_load(_hotkey_start_id, arr)
    obs.obs_data_array_release(arr)

    # Register stop hotkey
    _hotkey_stop_id = obs.obs_hotkey_register_frontend(
        "latest_file.stop", "Stop Updating Latest File Cycle", on_hotkey_stop)
    arr = obs.obs_data_get_array(settings, "latest_file.stop")
    obs.obs_hotkey_load(_hotkey_stop_id, arr)
    obs.obs_data_array_release(arr)

    log("Script loaded. Set hotkeys in OBS Settings → Hotkeys.")

def script_save(settings):
    arr = obs.obs_hotkey_save(_hotkey_start_id)
    obs.obs_data_set_array(settings, "latest_file.start", arr)
    obs.obs_data_array_release(arr)

    arr = obs.obs_hotkey_save(_hotkey_stop_id)
    obs.obs_data_set_array(settings, "latest_file.stop", arr)
    obs.obs_data_array_release(arr)


def script_unload():
    obs.timer_remove(timer_callback)
    log("Script unloaded.")
