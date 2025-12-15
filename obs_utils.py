import typing

if typing.TYPE_CHECKING:
    import _obspython as obs  # full symbol set for IDE
else:
    import obspython as obs   # real runtime module

def get_scene(scene_name):
    src = obs.obs_get_source_by_name(scene_name)
    if not src:
        return None, None  # scene, source

    scene = obs.obs_scene_from_source(src)
    # DO NOT release scene — OBS owns it
    return scene, src  # return the source so we can release only that


def find_scene_item(scene, source_name):
    if scene is None:
        return None
    return obs.obs_scene_find_source(scene, source_name)


def set_sceneitem_visible(scene, source_name, visible):
    if scene is None:
        return False
    
    item = find_scene_item(scene, source_name)
    if item:
        obs.obs_sceneitem_set_visible(item, visible)
        return True
    return False

def get_all_scene_names():
    scene_names = []

    # Get all scenes in OBS
    scenes = obs.obs_frontend_get_scenes()
    if not scenes:
        return scene_names

    for scene_source in scenes:
        name = obs.obs_source_get_name(scene_source)
        scene_names.append(name)
        obs.obs_source_release(scene_source)  # release reference

    return scene_names

def set_source_visibility(name, visible):
    scene_items_to_set = []

    # Check if this is a group action
    # global group_actions
    # if name in group_actions:
    #     obs.script_log(obs.LOG_INFO, f"Performing group action for '{name}' with visibility {visible}")
    #     group_actions[name](visible)
    #     return

    # Step 1: Collect scene items to set
    for scene_name in get_all_scene_names():
        scene, scene_src = get_scene(scene_name)
        if not scene:
            continue

        item = find_scene_item(scene, name)
        if item:
            scene_items_to_set.append((scene_name, item))

        obs.obs_source_release(scene_src)

    for scene_name, item in scene_items_to_set:
        obs.obs_sceneitem_set_visible(item, visible)

# ---------- Helpers for OBS source updates ----------
def set_source_string(source_name, text):
    src = obs.obs_get_source_by_name(source_name)
    if src is not None:
        settings = obs.obs_data_create()
        obs.obs_data_set_string(settings, "text", text)
        obs.obs_source_update(src, settings)
        obs.obs_data_release(settings)
        obs.obs_source_release(src)
    else:
        obs.script_log(obs.LOG_WARNING, f"Source not found: {source_name}")

def set_source_file(source_name, file_path):
    src = obs.obs_get_source_by_name(source_name)
    if src is not None:
        settings = obs.obs_data_create()
        obs.obs_data_set_string(settings, "file", file_path)
        obs.obs_source_update(src, settings)
        obs.obs_data_release(settings)
        obs.obs_source_release(src)
    else:
        obs.script_log(obs.LOG_WARNING, f"Source not found (file): {source_name}")

def set_color_source_alpha(source_name, alpha):
    """
    Sets only the alpha channel of a color source's ABGR color.
    Alpha: 0–255
    This is used as hack to hide/show sources inside source groups. 
    Python OBS API does not work in setting source visibility directly inside groups.
    """
    source = obs.obs_get_source_by_name(source_name)
    if source is None:
        obs.script_log(obs.LOG_WARNING, f"Source not found: {source_name}")
        return

    settings = obs.obs_source_get_settings(source)

    # Read current ABGR (0xAABBGGRR)
    current_abgr = obs.obs_data_get_int(settings, "color")

    # Clamp alpha
    if alpha < 0: alpha = 0
    if alpha > 255: alpha = 255

    # Mask out OLD alpha (upper 8 bits)
    rgb = current_abgr & 0x00FFFFFF  # keep BB GG RR

    # Insert NEW alpha (alpha << 24)
    new_abgr = (alpha << 24) | rgb

    # Write back
    obs.obs_data_set_int(settings, "color", new_abgr)
    obs.obs_source_update(source, settings)

    obs.obs_data_release(settings)
    obs.obs_source_release(source)

def rgb_to_bgr(rgb):
    r = (rgb >> 16) & 0xFF
    g = (rgb >> 8) & 0xFF
    b = rgb & 0xFF
    return (b << 16) | (g << 8) | r

def set_color_source_color(source_name, rgb):
    # rgb must be 0xRRGGBB
    # Convert RGB to BGR
    bgr = rgb_to_bgr(rgb)

    # Force full alpha channel
    argb = 0xFF000000 | (bgr & 0x00FFFFFF)

    source = obs.obs_get_source_by_name(source_name)
    if source is not None:
        settings = obs.obs_data_create()
        obs.obs_data_set_int(settings, "color", argb)
        obs.obs_source_update(source, settings)
        obs.obs_data_release(settings)
        obs.obs_source_release(source)
