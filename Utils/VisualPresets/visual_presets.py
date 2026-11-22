"""Save and load visual settings for the diving overlay design scenes."""

import json
import math
import os
import re
import tempfile

import obspython as obs


SCENE_NAMES = (
    "OverlaySchedule",
    "OverlayCountdown",
    "OverlayEvent",
    "OverlayRankings",
    "BoardEvent",
    "BoardRankings",
    "Schedule Design",
    "Livestream Lists Header Design",
    "Livestream Elements Design",
    "Board Lists Design",
    "Replay Scene 1",
    "Replay Scene 2",
    "Replay Scene 3",
)
SCHEME_VERSION = 1
SOURCE_PROPERTIES = {
    "color_source": ("color", "alpha"),
    "gradient_source": (
        "rotation",
        "from_color",
        "from_opacity",
        "midpoint_1",
        "to_color_1",
        "to_opacity_1",
    ),
    "image_source": ("file",),
    "text_gdiplus": ("font", "color", "opacity", "bk_color", "bk_opacity", "align", "valign"),
}
SOURCE_TYPE_OPTIONS = {
    "gradient_source": ("include_gradient", "Gradient sources"),
    "color_source": ("include_color", "Solid color sources"),
    "image_source": ("include_image", "Image sources"),
    "text_gdiplus": ("include_text", "Text sources (GDI+)"),
}

_scheme_name = ""
_selected_scheme = ""
_enabled_source_types = set(SOURCE_TYPE_OPTIONS)
_include_transitions = False


def _saved_directory():
    return os.path.join(os.path.abspath(script_path()), "Saved")


def _scheme_filename(name):
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    if not cleaned:
        raise ValueError("Enter a valid scheme name.")
    if cleaned.upper().split(".")[0] in {
        "CON", "PRN", "AUX", "NUL",
        *(f"COM{number}" for number in range(1, 10)),
        *(f"LPT{number}" for number in range(1, 10)),
    }:
        cleaned = f"_{cleaned}"
    return cleaned


def _obs_color_to_hex(value):
    red = value & 0xFF
    green = (value >> 8) & 0xFF
    blue = (value >> 16) & 0xFF
    return f"#{red:02X}{green:02X}{blue:02X}"


def _hex_to_obs_color(value):
    if not isinstance(value, str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}", value):
        raise ValueError(f"Invalid color value: {value!r}")
    red = int(value[1:3], 16)
    green = int(value[3:5], 16)
    blue = int(value[5:7], 16)
    return (blue << 16) | (green << 8) | red


def _source_properties(source, source_type):
    settings = obs.obs_source_get_settings(source)
    try:
        if source_type == "color_source":
            color = obs.obs_data_get_int(settings, "color")
            return {
                "color": _obs_color_to_hex(color),
                "alpha": (color >> 24) & 0xFF,
            }
        if source_type == "gradient_source":
            return {
                "rotation": obs.obs_data_get_double(settings, "rotation"),
                "from_color": _obs_color_to_hex(
                    obs.obs_data_get_int(settings, "from_color")
                ),
                "from_opacity": obs.obs_data_get_double(settings, "from_opacity"),
                "midpoint_1": obs.obs_data_get_double(settings, "midpoint_1"),
                "to_color_1": _obs_color_to_hex(
                    obs.obs_data_get_int(settings, "to_color_1")
                ),
                "to_opacity_1": obs.obs_data_get_double(settings, "to_opacity_1"),
            }
        if source_type == "image_source":
            return {"file": obs.obs_data_get_string(settings, "file")}
        if source_type == "text_gdiplus":
            font = obs.obs_data_get_obj(settings, "font")
            if font is None:
                raise ValueError(
                    f"Text source has no font settings: {obs.obs_source_get_name(source)}"
                )
            try:
                font_values = {
                    "face": obs.obs_data_get_string(font, "face"),
                    "style": obs.obs_data_get_string(font, "style"),
                    "size": obs.obs_data_get_int(font, "size"),
                    "flags": obs.obs_data_get_int(font, "flags"),
                }
            finally:
                obs.obs_data_release(font)
            return {
                "font": font_values,
                "color": obs.obs_data_get_int(settings, "color"),
                "opacity": obs.obs_data_get_int(settings, "opacity"),
                "bk_color": obs.obs_data_get_int(settings, "bk_color"),
                "bk_opacity": obs.obs_data_get_int(settings, "bk_opacity"),
                "align": obs.obs_data_get_string(settings, "align"),
                "valign": obs.obs_data_get_string(settings, "valign"),
            }
        raise ValueError(f"Unsupported source type: {source_type}")
    finally:
        obs.obs_data_release(settings)


def _collect_sources():
    sources = {}

    def collect_items(items, scene_name):
        if items is None:
            return
        try:
            for item in items:
                if obs.obs_sceneitem_is_group(item):
                    collect_items(obs.obs_sceneitem_group_enum_items(item), scene_name)
                    continue
                source = obs.obs_sceneitem_get_source(item)
                if source is None:
                    continue
                source_type = obs.obs_source_get_unversioned_id(source)
                if source_type not in _enabled_source_types:
                    continue
                source_name = obs.obs_source_get_name(source)
                entry = sources.setdefault(
                    source_name,
                    {"name": source_name, "type": source_type, "scenes": set()},
                )
                if entry["type"] != source_type:
                    obs.script_log(
                        obs.LOG_WARNING,
                        f"Visual presets: source type changed while scanning {source_name}",
                    )
                    continue
                entry["scenes"].add(scene_name)
        finally:
            obs.sceneitem_list_release(items)

    for scene_name in SCENE_NAMES:
        scene_source = obs.obs_get_source_by_name(scene_name)
        if scene_source is None:
            obs.script_log(obs.LOG_WARNING, f"Visual presets: scene not found: {scene_name}")
            continue
        try:
            scene = obs.obs_scene_from_source(scene_source)
            if scene is None:
                obs.script_log(obs.LOG_WARNING, f"Visual presets: not a scene: {scene_name}")
                continue
            collect_items(obs.obs_scene_enum_items(scene), scene_name)
        finally:
            obs.obs_source_release(scene_source)

    result = []
    for source_name in sorted(sources):
        entry = sources[source_name]
        source = obs.obs_get_source_by_name(source_name)
        if source is None:
            obs.script_log(
                obs.LOG_WARNING,
                f"Visual presets: source disappeared while scanning: {source_name}",
            )
            continue
        try:
            result.append({
                "name": source_name,
                "type": entry["type"],
                "scenes": sorted(entry["scenes"]),
                "properties": _source_properties(source, entry["type"]),
            })
        finally:
            obs.obs_source_release(source)
    return result


def _visit_scene_items(scene_name, visitor):
    scene_source = obs.obs_get_source_by_name(scene_name)
    if scene_source is None:
        return False
    try:
        scene = obs.obs_scene_from_source(scene_source)
        if scene is None:
            return False

        def visit_items(items, parents):
            if items is None:
                return
            try:
                for item in items:
                    source = obs.obs_sceneitem_get_source(item)
                    if source is None:
                        continue
                    part = {
                        "id": obs.obs_sceneitem_get_id(item),
                        "name": obs.obs_source_get_name(source),
                        "type": obs.obs_source_get_unversioned_id(source),
                    }
                    path = parents + [part]
                    visitor(item, path)
                    if obs.obs_sceneitem_is_group(item):
                        visit_items(obs.obs_sceneitem_group_enum_items(item), path)
            finally:
                obs.sceneitem_list_release(items)

        visit_items(obs.obs_scene_enum_items(scene), [])
        return True
    finally:
        obs.obs_source_release(scene_source)


def _transition_settings(item, show):
    transition = obs.obs_sceneitem_get_transition(item, show)
    result = {"duration": obs.obs_sceneitem_get_transition_duration(item, show)}
    if transition is None:
        result["transition"] = None
        return result
    settings = obs.obs_source_get_settings(transition)
    try:
        result["transition"] = {
            "id": obs.obs_source_get_id(transition),
            "name": obs.obs_source_get_name(transition),
            "settings": json.loads(obs.obs_data_get_json_with_defaults(settings)),
        }
    finally:
        obs.obs_data_release(settings)
    return result


def _collect_transitions():
    entries = []
    for scene_name in SCENE_NAMES:
        def collect(item, path):
            entries.append({
                "scene": scene_name,
                "path": path,
                "show": _transition_settings(item, True),
                "hide": _transition_settings(item, False),
            })

        if not _visit_scene_items(scene_name, collect):
            obs.script_log(obs.LOG_WARNING, f"Visual presets: scene not found: {scene_name}")
    return entries


def _validate_transitions(entries):
    if not isinstance(entries, list):
        raise ValueError("Invalid scene-item transition list.")
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("scene") not in SCENE_NAMES:
            raise ValueError("Invalid scene in transition entry.")
        path = entry.get("path")
        if not isinstance(path, list) or not path:
            raise ValueError("Invalid scene-item transition path.")
        ids = []
        for part in path:
            if (not isinstance(part, dict)
                    or isinstance(part.get("id"), bool) or not isinstance(part.get("id"), int)
                    or not isinstance(part.get("name"), str)
                    or not isinstance(part.get("type"), str)):
                raise ValueError("Invalid scene-item transition path.")
            ids.append(part["id"])
        key = (entry["scene"], tuple(ids))
        if key in seen:
            raise ValueError("Duplicate scene-item transition entry.")
        seen.add(key)
        for direction in ("show", "hide"):
            value = entry.get(direction)
            if not isinstance(value, dict):
                raise ValueError(f"Invalid {direction} transition.")
            duration = value.get("duration")
            if (isinstance(duration, bool) or not isinstance(duration, int)
                    or not 0 <= duration <= 0xFFFFFFFF):
                raise ValueError(f"Invalid {direction} transition duration.")
            if "transition" not in value:
                raise ValueError(f"Missing {direction} transition.")
            transition = value["transition"]
            if transition is not None and (
                not isinstance(transition, dict)
                or not isinstance(transition.get("id"), str) or not transition["id"]
                or not isinstance(transition.get("name"), str)
                or not isinstance(transition.get("settings"), dict)
            ):
                raise ValueError(f"Invalid {direction} transition settings.")


def _apply_transitions(entries):
    pending = {
        (entry["scene"], tuple(part["id"] for part in entry["path"])): entry
        for entry in entries
    }
    warnings = []
    applied = 0

    def apply_item(scene_name, item, path):
        nonlocal applied
        key = (scene_name, tuple(part["id"] for part in path))
        entry = pending.get(key)
        if entry is None:
            return
        if entry["path"] != path:
            warnings.append(f"Scene item changed: {scene_name} / {path[-1]['name']}")
            del pending[key]
            return
        del pending[key]
        changed = False
        for direction, show in (("show", True), ("hide", False)):
            value = entry[direction]
            definition = value["transition"]
            transition = None
            if definition is not None:
                defaults = obs.obs_get_source_defaults(definition["id"])
                if defaults is None:
                    warnings.append(f"Transition type not available: {definition['id']}")
                    continue
                obs.obs_data_release(defaults)
                settings = obs.obs_data_create_from_json(json.dumps(definition["settings"]))
                if settings is None:
                    warnings.append(f"Could not read transition settings: {definition['name']}")
                    continue
                try:
                    transition = obs.obs_source_create_private(
                        definition["id"], definition["name"], settings
                    )
                finally:
                    obs.obs_data_release(settings)
                if transition is None:
                    warnings.append(f"Could not create transition: {definition['name']}")
                    continue
                if obs.obs_source_get_type(transition) != obs.OBS_SOURCE_TYPE_TRANSITION:
                    warnings.append(f"Not a transition type: {definition['id']}")
                    obs.obs_source_release(transition)
                    continue
            try:
                obs.obs_sceneitem_set_transition(item, show, transition)
                obs.obs_sceneitem_set_transition_duration(item, show, value["duration"])
                changed = True
            finally:
                if transition is not None:
                    obs.obs_source_release(transition)
        if changed:
            applied += 1

    for scene_name in {entry["scene"] for entry in entries}:
        _visit_scene_items(
            scene_name, lambda item, path: apply_item(scene_name, item, path)
        )
    for entry in pending.values():
        warnings.append(f"Scene item not found: {entry['scene']} / {entry['path'][-1]['name']}")
    return applied, warnings


def _write_scheme(name):
    scheme_name = _scheme_filename(name)
    if not _enabled_source_types and not _include_transitions:
        raise ValueError("Select at least one source type or transitions.")
    os.makedirs(_saved_directory(), exist_ok=True)
    document = {
        "version": SCHEME_VERSION,
        "name": name.strip(),
        "sources": _collect_sources() if _enabled_source_types else [],
    }
    if _include_transitions:
        document["item_transitions"] = _collect_transitions()
    if not document["sources"] and not document.get("item_transitions"):
        raise ValueError("No selected sources or scene items were found in the configured scenes.")

    destination = os.path.join(_saved_directory(), f"{scheme_name}.json")
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="\n",
            dir=_saved_directory(),
            prefix=f".{scheme_name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = temporary.name
            json.dump(document, temporary, ensure_ascii=False, indent=2)
            temporary.write("\n")
        os.replace(temporary_path, destination)
    finally:
        if temporary_path and os.path.exists(temporary_path):
            os.remove(temporary_path)
    return destination


def _read_scheme(scheme_stem):
    safe_stem = _scheme_filename(scheme_stem)
    if safe_stem != scheme_stem:
        raise ValueError("Select a valid saved scheme.")
    path = os.path.join(_saved_directory(), f"{safe_stem}.json")
    with open(path, "r", encoding="utf-8") as scheme_file:
        document = json.load(scheme_file)
    if not isinstance(document, dict) or document.get("version") != SCHEME_VERSION:
        raise ValueError(f"Unsupported or invalid visual preset: {scheme_stem}")
    if not isinstance(document.get("sources"), list):
        raise ValueError(f"Invalid source list in visual preset: {scheme_stem}")
    return document


def _validated_properties(source_type, properties):
    if not isinstance(properties, dict):
        raise ValueError("Invalid source properties in visual preset.")
    if source_type == "color_source":
        color = _hex_to_obs_color(properties["color"])
        alpha = properties["alpha"]
        if isinstance(alpha, bool) or not isinstance(alpha, int) or not 0 <= alpha <= 255:
            raise ValueError("Color alpha must be an integer from 0 to 255.")
        return {"color": (alpha << 24) | color}
    if source_type == "gradient_source":
        rotation = properties["rotation"]
        from_opacity = properties["from_opacity"]
        to_opacity = properties["to_opacity_1"]
        midpoint = properties["midpoint_1"]
        if (isinstance(rotation, bool) or not isinstance(rotation, (int, float))
                or not math.isfinite(rotation)):
            raise ValueError("Gradient rotation must be a finite number.")
        if (isinstance(midpoint, bool) or not isinstance(midpoint, (int, float))
                or not math.isfinite(midpoint) or not 0 <= midpoint <= 100):
            raise ValueError("Gradient midpoint must be a number from 0 to 100.")
        for opacity in (from_opacity, to_opacity):
            if (isinstance(opacity, bool) or not isinstance(opacity, (int, float))
                    or not math.isfinite(opacity) or not 0 <= opacity <= 100):
                raise ValueError("Gradient opacity must be a number from 0 to 100.")
        return {
            "rotation": float(rotation),
            "from_color": 0xFF000000 | _hex_to_obs_color(properties["from_color"]),
            "from_opacity": float(from_opacity),
            "midpoint_1": float(midpoint),
            "to_color_1": 0xFF000000 | _hex_to_obs_color(properties["to_color_1"]),
            "to_opacity_1": float(to_opacity),
        }
    if source_type == "image_source":
        file_path = properties["file"]
        if not isinstance(file_path, str):
            raise ValueError("Image file path must be a string.")
        return {"file": file_path}
    if source_type == "text_gdiplus":
        font = properties["font"]
        if not isinstance(font, dict):
            raise ValueError("Text font must be an object.")
        for key in ("face", "style"):
            if not isinstance(font[key], str):
                raise ValueError(f"Text font {key} must be a string.")
        for key in ("size", "flags"):
            value = font[key]
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"Text font {key} must be a non-negative integer.")
        for key in ("color", "bk_color"):
            value = properties[key]
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 0xFFFFFFFF:
                raise ValueError(f"Text {key} must be a 32-bit color.")
        for key in ("opacity", "bk_opacity"):
            value = properties[key]
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
                raise ValueError(f"Text {key} must be an integer from 0 to 100.")
        for key, allowed in (("align", ("left", "center", "right")),
                             ("valign", ("top", "center", "bottom"))):
            if properties[key] not in allowed:
                raise ValueError(f"Invalid text {key}: {properties[key]!r}")
        return {
            "font": {key: font[key] for key in ("face", "style", "size", "flags")},
            **{key: properties[key] for key in
               ("color", "opacity", "bk_color", "bk_opacity", "align", "valign")},
        }
    raise ValueError(f"Unsupported source type in visual preset: {source_type}")


def _apply_scheme(document):
    if not _enabled_source_types and not _include_transitions:
        raise ValueError("Select at least one source type or transitions.")
    applied = 0
    warnings = []
    entries = []
    for entry in document["sources"]:
        if not isinstance(entry, dict):
            raise ValueError("Invalid source entry in visual preset.")
        source_name = entry.get("name")
        source_type = entry.get("type")
        if (not isinstance(source_name, str) or not isinstance(source_type, str)
                or source_type not in SOURCE_PROPERTIES):
            raise ValueError("Invalid source identity in visual preset.")
        if source_type not in _enabled_source_types:
            continue
        values = _validated_properties(source_type, entry.get("properties"))
        entries.append((source_name, source_type, values))

    transitions = document.get("item_transitions", []) if _include_transitions else []
    _validate_transitions(transitions)

    for source_name, source_type, values in entries:
        source = obs.obs_get_source_by_name(source_name)
        if source is None:
            warnings.append(f"Source not found: {source_name}")
            continue
        try:
            if obs.obs_source_get_unversioned_id(source) != source_type:
                warnings.append(f"Source type changed: {source_name}")
                continue
            settings = obs.obs_data_create()
            try:
                if source_type == "color_source":
                    obs.obs_data_set_int(settings, "color", values["color"])
                elif source_type == "gradient_source":
                    obs.obs_data_set_double(settings, "rotation", values["rotation"])
                    obs.obs_data_set_int(settings, "from_color", values["from_color"])
                    obs.obs_data_set_double(
                        settings, "from_opacity", values["from_opacity"]
                    )
                    obs.obs_data_set_double(settings, "midpoint_1", values["midpoint_1"])
                    obs.obs_data_set_int(settings, "to_color_1", values["to_color_1"])
                    obs.obs_data_set_double(
                        settings, "to_opacity_1", values["to_opacity_1"]
                    )
                elif source_type == "image_source":
                    obs.obs_data_set_string(settings, "file", values["file"])
                else:
                    font = obs.obs_data_create()
                    try:
                        for key in ("face", "style"):
                            obs.obs_data_set_string(font, key, values["font"][key])
                        for key in ("size", "flags"):
                            obs.obs_data_set_int(font, key, values["font"][key])
                        obs.obs_data_set_obj(settings, "font", font)
                    finally:
                        obs.obs_data_release(font)
                    for key in ("color", "opacity", "bk_color", "bk_opacity"):
                        obs.obs_data_set_int(settings, key, values[key])
                    for key in ("align", "valign"):
                        obs.obs_data_set_string(settings, key, values[key])
                obs.obs_source_update(source, settings)
            finally:
                obs.obs_data_release(settings)
            applied += 1
        finally:
            obs.obs_source_release(source)
    if transitions:
        item_count, item_warnings = _apply_transitions(transitions)
        applied += item_count
        warnings.extend(item_warnings)
    return applied, warnings


def _list_scheme_stems():
    os.makedirs(_saved_directory(), exist_ok=True)
    return sorted(
        os.path.splitext(filename)[0]
        for filename in os.listdir(_saved_directory())
        if filename.lower().endswith(".json")
        and os.path.isfile(os.path.join(_saved_directory(), filename))
    )


def _refresh_scheme_list(props):
    property_list = obs.obs_properties_get(props, "selected_scheme")
    if property_list is None:
        return
    obs.obs_property_list_clear(property_list)
    stems = _list_scheme_stems()
    obs.obs_property_list_add_string(property_list, "Select a preset", "")
    for stem in stems:
        obs.obs_property_list_add_string(property_list, stem, stem)


def _on_name_changed(_, __, settings):
    global _scheme_name
    _scheme_name = obs.obs_data_get_string(settings, "scheme_name")
    return True


def _on_scheme_changed(_, __, settings):
    global _selected_scheme
    _selected_scheme = obs.obs_data_get_string(settings, "selected_scheme")
    return True


def _save_clicked(props, _):
    try:
        destination = _write_scheme(_scheme_name)
    except (OSError, ValueError, KeyError) as error:
        obs.script_log(obs.LOG_ERROR, f"Visual presets: could not save preset: {error}")
        return True
    saved_scheme = os.path.splitext(os.path.basename(destination))[0]
    obs.script_log(obs.LOG_INFO, f"Visual presets: saved '{saved_scheme}'.")
    try:
        _refresh_scheme_list(props)
    except OSError as error:
        obs.script_log(obs.LOG_ERROR, f"Visual presets: could not refresh preset list: {error}")
    return True


def _load_clicked(_, __):
    if not _selected_scheme:
        obs.script_log(obs.LOG_WARNING, "Visual presets: select a saved preset to load.")
        return True
    try:
        document = _read_scheme(_selected_scheme)
        applied, warnings = _apply_scheme(document)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        obs.script_log(obs.LOG_ERROR, f"Visual presets: could not load preset: {error}")
        return True
    for warning in warnings:
        obs.script_log(obs.LOG_WARNING, f"Visual presets: {warning}")
    if applied:
        obs.script_log(
            obs.LOG_INFO,
            f"Visual presets: loaded '{_selected_scheme}' ({applied} sources or scene items updated).",
        )
    else:
        obs.script_log(
            obs.LOG_WARNING,
            f"Visual presets: no selected sources were updated from '{_selected_scheme}'.",
        )
    return True


def _refresh_clicked(props, _):
    try:
        _refresh_scheme_list(props)
    except OSError as error:
        obs.script_log(obs.LOG_ERROR, f"Visual presets: could not list presets: {error}")
    return True


def script_description():
    return (
        "Visual Presets: save and load colors, images and text styling for the predefined Diving Overlays "
        "design scenes. Load this script separately from diving_overlays.py."
    )


def script_defaults(settings):
    obs.obs_data_set_default_string(settings, "scheme_name", "")
    obs.obs_data_set_default_string(settings, "selected_scheme", "")
    for setting, _ in SOURCE_TYPE_OPTIONS.values():
        obs.obs_data_set_default_bool(settings, setting, True)
    obs.obs_data_set_default_bool(settings, "include_transitions", False)


def _update_source_types(settings):
    global _enabled_source_types, _include_transitions
    _enabled_source_types = {
        source_type for source_type, (setting, _) in SOURCE_TYPE_OPTIONS.items()
        if obs.obs_data_get_bool(settings, setting)
    }
    _include_transitions = obs.obs_data_get_bool(settings, "include_transitions")


def script_load(settings):
    global _scheme_name, _selected_scheme
    _scheme_name = obs.obs_data_get_string(settings, "scheme_name")
    _selected_scheme = obs.obs_data_get_string(settings, "selected_scheme")
    _update_source_types(settings)
    try:
        os.makedirs(_saved_directory(), exist_ok=True)
    except OSError as error:
        obs.script_log(obs.LOG_ERROR, f"Visual presets: could not create Saved folder: {error}")


def script_update(settings):
    global _scheme_name, _selected_scheme
    _scheme_name = obs.obs_data_get_string(settings, "scheme_name")
    _selected_scheme = obs.obs_data_get_string(settings, "selected_scheme")
    _update_source_types(settings)


def script_properties():
    properties = obs.obs_properties_create()
    for setting, label in SOURCE_TYPE_OPTIONS.values():
        obs.obs_properties_add_bool(properties, setting, label)
    obs.obs_properties_add_bool(properties, "include_transitions", "Source show/hide transitions")
    obs.obs_properties_add_text(
        properties, "scheme_name", "New preset name", obs.OBS_TEXT_DEFAULT
    )
    name_property = obs.obs_properties_get(properties, "scheme_name")
    obs.obs_property_set_modified_callback(name_property, _on_name_changed)
    obs.obs_properties_add_button(properties, "save_scheme", "Save current appearance", _save_clicked)

    schemes = obs.obs_properties_add_list(
        properties,
        "selected_scheme",
        "Saved visual presets",
        obs.OBS_COMBO_TYPE_LIST,
        obs.OBS_COMBO_FORMAT_STRING,
    )
    try:
        _refresh_scheme_list(properties)
    except OSError as error:
        obs.script_log(obs.LOG_ERROR, f"Visual presets: could not list presets: {error}")
    obs.obs_property_set_modified_callback(schemes, _on_scheme_changed)
    obs.obs_properties_add_button(
        properties, "load_scheme", "Load selected preset", _load_clicked
    )
    obs.obs_properties_add_button(
        properties, "refresh_schemes", "Refresh saved presets", _refresh_clicked
    )
    return properties
