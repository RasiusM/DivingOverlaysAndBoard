import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch


sys.modules.setdefault("obspython", MagicMock())

MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "Utils"
    / "VisualPresets"
    / "visual_presets.py"
)
spec = importlib.util.spec_from_file_location("visual_presets", MODULE_PATH)
visual_presets = importlib.util.module_from_spec(spec)
spec.loader.exec_module(visual_presets)


class VisualPresetHelpersTests(unittest.TestCase):
    def test_transition_round_trip_preserves_item_identity_and_group_transitions(self):
        scene_name = "Replay Scene 3"
        shared = {"name": "Shared", "type": "image_source"}
        group_source = {"name": "Group", "type": "group"}

        def transition(kind, name, **settings):
            return {"id": kind, "name": name, "settings": settings}

        first = {"id": 1, "source": shared,
                 "show": transition(
                     "obs_stinger_transition", "Stinger",
                     path="C:\\Media\\organizer_a.mov", preload=True, transition_point=700,
                 ),
                 "hide": None, "show_duration": 200, "hide_duration": 0}
        second = {"id": 2, "source": shared,
                  "show": None, "hide": transition("move_transition", "Move", distance=12),
                  "show_duration": 50, "hide_duration": 600}
        group = {"id": 3, "source": group_source, "items": [second],
                 "show": None, "hide": None, "show_duration": 0, "hide_duration": 0}
        scenes = {scene_name: {"items": [first, group]}}
        releases = []

        def set_transition(item, show, value):
            item["show" if show else "hide"] = value

        def set_duration(item, show, value):
            item["show_duration" if show else "hide_duration"] = value

        with tempfile.TemporaryDirectory() as directory, \
             patch.object(visual_presets, "_saved_directory", return_value=directory), \
             patch.object(visual_presets, "SCENE_NAMES", (scene_name,)), \
             patch.object(visual_presets, "_enabled_source_types", set()), \
             patch.object(visual_presets, "_include_transitions", True), \
             patch.multiple(
                 visual_presets.obs,
                 OBS_SOURCE_TYPE_TRANSITION=9,
                 obs_get_source_by_name=MagicMock(side_effect=scenes.get),
                 obs_scene_from_source=MagicMock(side_effect=lambda scene: scene),
                 obs_scene_enum_items=MagicMock(side_effect=lambda scene: list(scene["items"])),
                 obs_sceneitem_group_enum_items=MagicMock(
                     side_effect=lambda item: list(item["items"])
                 ),
                 obs_sceneitem_is_group=MagicMock(side_effect=lambda item: "items" in item),
                 obs_sceneitem_get_source=MagicMock(side_effect=lambda item: item["source"]),
                 obs_sceneitem_get_id=MagicMock(side_effect=lambda item: item["id"]),
                 obs_source_get_name=MagicMock(side_effect=lambda source: source["name"]),
                 obs_source_get_unversioned_id=MagicMock(
                     side_effect=lambda source: source["type"]
                 ),
                 obs_sceneitem_get_transition=MagicMock(
                     side_effect=lambda item, show: item["show" if show else "hide"]
                 ),
                 obs_sceneitem_get_transition_duration=MagicMock(
                     side_effect=lambda item, show: item["show_duration" if show else "hide_duration"]
                 ),
                 obs_source_get_id=MagicMock(side_effect=lambda source: source["id"]),
                 obs_source_get_settings=MagicMock(side_effect=lambda source: source["settings"]),
                 obs_data_get_json_with_defaults=MagicMock(side_effect=json.dumps),
                 obs_get_source_defaults=MagicMock(return_value={}),
                 obs_data_create_from_json=MagicMock(side_effect=json.loads),
                 obs_source_create_private=MagicMock(
                     side_effect=lambda kind, name, settings:
                     transition(kind, name, **settings)
                 ),
                 obs_source_get_type=MagicMock(return_value=9),
                 obs_sceneitem_set_transition=MagicMock(side_effect=set_transition),
                 obs_sceneitem_set_transition_duration=MagicMock(side_effect=set_duration),
                 obs_data_release=MagicMock(),
                 obs_source_release=MagicMock(side_effect=releases.append),
                 sceneitem_list_release=MagicMock(),
             ):
            path = visual_presets._write_scheme("Transitions")
            with open(path, encoding="utf-8") as file:
                document = json.load(file)
            self.assertEqual(len(document["item_transitions"]), 3)
            self.assertEqual(document["sources"], [])
            self.assertEqual(
                document["item_transitions"][0]["show"]["transition"]["settings"]["path"],
                "C:\\Media\\organizer_a.mov",
            )

            first["show"] = transition(
                "obs_stinger_transition", "Stinger", path="C:\\Media\\organizer_b.mov"
            )
            first["hide"] = transition("fade_transition", "New")
            first["show_duration"] = 1
            second["hide"] = None
            group["show"] = transition("fade_transition", "New")
            self.assertEqual(visual_presets._apply_scheme(document), (3, []))
            self.assertEqual(first["show"], transition(
                "obs_stinger_transition", "Stinger",
                path="C:\\Media\\organizer_a.mov", preload=True, transition_point=700,
            ))
            self.assertIsNone(first["hide"])
            self.assertEqual(first["show_duration"], 200)
            self.assertEqual(second["hide"], transition("move_transition", "Move", distance=12))
            self.assertEqual(second["hide_duration"], 600)
            self.assertIsNone(group["show"])
            self.assertEqual(
                [source["name"] for source in releases if "id" in source],
                ["Stinger", "Move"],
            )

    def test_transition_missing_item_or_plugin_preserves_current_transition(self):
        scene_name = visual_presets.SCENE_NAMES[0]
        source = {"name": "Image", "type": "image_source"}
        existing = object()
        item = {"id": 1, "source": source, "show": existing}
        scene = {"items": [item]}
        entry = {
            "scene": scene_name, "path": [{"id": 1, "name": "Image", "type": "image_source"}],
            "show": {"duration": 200, "transition": {
                "id": "missing_plugin", "name": "Missing", "settings": {},
            }},
            "hide": {"duration": 0, "transition": None},
        }
        missing = dict(entry, path=[{"id": 2, "name": "Missing", "type": "image_source"}])
        changed = dict(entry, path=[{"id": 1, "name": "Old name", "type": "image_source"}])
        with patch.object(visual_presets, "_enabled_source_types", set()), \
             patch.object(visual_presets, "_include_transitions", True), \
             patch.multiple(
                 visual_presets.obs,
                 obs_get_source_by_name=MagicMock(return_value=scene),
                 obs_scene_from_source=MagicMock(return_value=scene),
                 obs_scene_enum_items=MagicMock(return_value=[item]),
                 obs_sceneitem_get_source=MagicMock(return_value=source),
                 obs_sceneitem_get_id=MagicMock(return_value=1),
                 obs_source_get_name=MagicMock(return_value="Image"),
                 obs_source_get_unversioned_id=MagicMock(return_value="image_source"),
                 obs_sceneitem_is_group=MagicMock(return_value=False),
                 obs_get_source_defaults=MagicMock(return_value=None),
                 obs_sceneitem_set_transition=MagicMock(),
                 obs_sceneitem_set_transition_duration=MagicMock(),
                 obs_source_release=MagicMock(),
                 sceneitem_list_release=MagicMock(),
             ):
            applied, warnings = visual_presets._apply_scheme({
                "sources": [], "item_transitions": [entry, missing],
            })
            self.assertEqual(applied, 1)
            self.assertEqual(len(warnings), 2)
            self.assertIn("missing_plugin", warnings[0])
            self.assertIn("Missing", warnings[1])
            visual_presets.obs.obs_sceneitem_set_transition.assert_called_once_with(item, False, None)
            self.assertIs(item["show"], existing)
            visual_presets.obs.obs_sceneitem_set_transition.reset_mock()
            applied, warnings = visual_presets._apply_scheme({
                "sources": [], "item_transitions": [changed],
            })
            self.assertEqual(applied, 0)
            self.assertIn("Scene item changed", warnings[0])
            visual_presets.obs.obs_sceneitem_set_transition.assert_not_called()

    def test_transition_option_is_opt_in_and_old_presets_do_not_clear_transitions(self):
        with patch.object(visual_presets, "_enabled_source_types", set()), \
             patch.object(visual_presets, "_include_transitions", True), \
             patch.object(visual_presets, "_apply_transitions") as apply:
            self.assertEqual(visual_presets._apply_scheme({"sources": []}), (0, []))
            apply.assert_not_called()

        settings = {}
        with patch.object(visual_presets.obs, "obs_data_set_default_string",
                          side_effect=lambda data, key, value: data.setdefault(key, value)), \
             patch.object(visual_presets.obs, "obs_data_set_default_bool",
                          side_effect=lambda data, key, value: data.setdefault(key, value)), \
             patch.object(visual_presets.obs, "obs_data_get_bool",
                          side_effect=lambda data, key: data[key]), \
             patch.object(visual_presets, "_enabled_source_types", set()), \
             patch.object(visual_presets, "_include_transitions", False):
            visual_presets.script_defaults(settings)
            self.assertFalse(settings["include_transitions"])
            settings["include_transitions"] = True
            visual_presets._update_source_types(settings)
            self.assertTrue(visual_presets._include_transitions)
            settings["include_transitions"] = False
            visual_presets._update_source_types(settings)
            self.assertFalse(visual_presets._include_transitions)

    def test_disabled_transitions_are_ignored_on_save_and_load(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(visual_presets, "_saved_directory", return_value=directory), \
             patch.object(visual_presets, "_enabled_source_types", {"color_source"}), \
             patch.object(visual_presets, "_include_transitions", False), \
             patch.object(visual_presets, "_collect_sources", return_value=[
                 {"name": "Solid", "type": "color_source",
                  "properties": {"color": "#112233", "alpha": 127}},
             ]), \
             patch.object(visual_presets, "_collect_transitions") as collect, \
             patch.object(visual_presets, "_apply_transitions") as apply, \
             patch.object(visual_presets.obs, "obs_get_source_by_name", return_value=None):
            path = visual_presets._write_scheme("No transitions")
            with open(path, encoding="utf-8") as file:
                document = json.load(file)
            self.assertNotIn("item_transitions", document)
            collect.assert_not_called()
            document["item_transitions"] = "invalid but disabled"
            visual_presets._apply_scheme(document)
            apply.assert_not_called()

    def test_invalid_transitions_are_rejected_before_source_updates(self):
        document = {
            "sources": [{"name": "Solid", "type": "color_source",
                         "properties": {"color": "#112233", "alpha": 127}}],
            "item_transitions": [{"scene": visual_presets.SCENE_NAMES[0], "path": [],
                                  "show": {}, "hide": {}}],
        }
        with patch.object(visual_presets, "_include_transitions", True), \
             patch.object(visual_presets.obs, "obs_get_source_by_name") as lookup:
            with self.assertRaises(ValueError):
                visual_presets._apply_scheme(document)
            lookup.assert_not_called()

    def test_source_type_options_default_to_enabled_and_update_with_settings(self):
        settings = {}

        def set_default(data, name, value):
            data.setdefault(name, value)

        with patch.object(visual_presets.obs, "obs_data_set_default_string",
                          side_effect=set_default), \
             patch.object(visual_presets.obs, "obs_data_set_default_bool",
                          side_effect=set_default), \
             patch.object(visual_presets.obs, "obs_data_get_string",
                          side_effect=lambda data, key: data[key]), \
             patch.object(visual_presets.obs, "obs_data_get_bool",
                          side_effect=lambda data, key: data[key]), \
             patch.object(visual_presets, "_enabled_source_types", set()):
            visual_presets.script_defaults(settings)
            visual_presets.script_update(settings)
            self.assertEqual(visual_presets._enabled_source_types,
                             set(visual_presets.SOURCE_TYPE_OPTIONS))
            settings["include_gradient"] = False
            settings["include_text"] = False
            visual_presets.script_update(settings)
            self.assertEqual(visual_presets._enabled_source_types,
                             {"color_source", "image_source"})

    def test_script_properties_expose_all_source_type_checkboxes(self):
        properties = object()
        with patch.multiple(
            visual_presets.obs,
            obs_properties_create=MagicMock(return_value=properties),
            obs_properties_add_bool=MagicMock(),
            obs_properties_add_text=MagicMock(),
            obs_properties_get=MagicMock(),
            obs_property_set_modified_callback=MagicMock(),
            obs_properties_add_button=MagicMock(),
            obs_properties_add_list=MagicMock(),
        ), patch.object(visual_presets, "_refresh_scheme_list"):
            self.assertIs(visual_presets.script_properties(), properties)
            for setting, label in visual_presets.SOURCE_TYPE_OPTIONS.values():
                visual_presets.obs.obs_properties_add_bool.assert_any_call(
                    properties, setting, label
                )
            visual_presets.obs.obs_properties_add_bool.assert_any_call(
                properties, "include_transitions", "Source show/hide transitions"
            )
            self.assertEqual(visual_presets.obs.obs_properties_add_bool.call_count, 5)

    def test_selected_types_filter_saved_and_loaded_sources(self):
        sources = {
            "Solid": {"name": "Solid", "type": "color_source",
                      "properties": {"color": "#112233", "alpha": 127}},
            "Gradient": {"name": "Gradient", "type": "gradient_source", "properties": {
                "rotation": 270, "from_color": "#112233", "from_opacity": 80,
                "midpoint_1": 50, "to_color_1": "#AABBCC", "to_opacity_1": 90,
            }},
            "Image": {"name": "Image", "type": "image_source",
                      "properties": {"file": "logo.png"}},
            "Text": {"name": "Text", "type": "text_gdiplus", "properties": {
                "font": {"face": "Arial", "style": "Regular", "size": 40, "flags": 0},
                "color": 0xFFFFFFFF, "opacity": 100, "bk_color": 0, "bk_opacity": 0,
                "align": "left", "valign": "top",
            }},
        }
        scenes = {name: {"items": []} for name in visual_presets.SCENE_NAMES}
        scenes[visual_presets.SCENE_NAMES[0]]["items"] = list(sources.values())

        def set_value(settings, key, value):
            settings[key] = value

        with tempfile.TemporaryDirectory() as directory, \
             patch.object(visual_presets, "_saved_directory", return_value=directory), \
             patch.object(visual_presets, "_enabled_source_types",
                          set(visual_presets.SOURCE_TYPE_OPTIONS)), \
             patch.multiple(
                 visual_presets.obs,
                 obs_get_source_by_name=MagicMock(
                     side_effect=lambda name: scenes.get(name) or sources.get(name)
                 ),
                 obs_scene_from_source=MagicMock(side_effect=lambda scene: scene),
                 obs_scene_enum_items=MagicMock(side_effect=lambda scene: scene["items"]),
                 obs_sceneitem_is_group=MagicMock(return_value=False),
                 obs_sceneitem_get_source=MagicMock(side_effect=lambda item: item),
                 obs_source_get_unversioned_id=MagicMock(side_effect=lambda item: item["type"]),
                 obs_source_get_name=MagicMock(side_effect=lambda item: item["name"]),
                 obs_data_create=MagicMock(side_effect=dict),
                 obs_data_set_int=MagicMock(side_effect=set_value),
                 obs_data_set_double=MagicMock(side_effect=set_value),
                 obs_data_set_string=MagicMock(side_effect=set_value),
                 obs_data_set_obj=MagicMock(side_effect=set_value),
                 obs_source_update=MagicMock(),
                 obs_data_release=MagicMock(),
                 obs_source_release=MagicMock(),
                 sceneitem_list_release=MagicMock(),
             ), patch.object(
                 visual_presets, "_source_properties",
                 side_effect=lambda source, _: source["properties"],
             ):
            for name, source in sources.items():
                with self.subTest(source=name):
                    visual_presets._enabled_source_types = {source["type"]}
                    path = visual_presets._write_scheme(name)
                    with open(path, encoding="utf-8") as file:
                        document = json.load(file)
                    self.assertEqual([entry["name"] for entry in document["sources"]], [name])

            visual_presets._enabled_source_types = set(visual_presets.SOURCE_TYPE_OPTIONS)
            full_path = visual_presets._write_scheme("Full")
            with open(full_path, encoding="utf-8") as file:
                document = json.load(file)
            for name, source in sources.items():
                with self.subTest(load=name):
                    visual_presets._enabled_source_types = {source["type"]}
                    visual_presets.obs.obs_source_update.reset_mock()
                    self.assertEqual(visual_presets._apply_scheme(document), (1, []))
                    self.assertIs(visual_presets.obs.obs_source_update.call_args.args[0], source)
                    visual_presets.obs.obs_source_update.assert_called_once()

    def test_no_selected_types_cannot_overwrite_or_load(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(visual_presets, "_saved_directory", return_value=directory), \
             patch.object(visual_presets, "_enabled_source_types", set()), \
             patch.object(visual_presets.obs, "obs_get_source_by_name") as find_source:
            path = Path(directory) / "existing.json"
            path.write_text("unchanged", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "at least one source type"):
                visual_presets._write_scheme("existing")
            self.assertEqual(path.read_text(encoding="utf-8"), "unchanged")
            with self.assertRaisesRegex(ValueError, "at least one source type"):
                visual_presets._apply_scheme({"sources": []})
            find_source.assert_not_called()

    def test_disabled_source_properties_are_not_applied_or_validated(self):
        entries = [
            {"name": "Image", "type": "image_source", "properties": {"file": 42}},
        ]
        with patch.object(visual_presets, "_enabled_source_types", {"color_source"}), \
             patch.object(visual_presets.obs, "obs_get_source_by_name") as find_source:
            self.assertEqual(visual_presets._apply_scheme({"sources": entries}), (0, []))
            find_source.assert_not_called()

    def test_saved_directory_is_inside_script_directory(self):
        with patch.object(visual_presets, "script_path",
                          return_value=str(MODULE_PATH.parent), create=True):
            self.assertEqual(
                Path(visual_presets._saved_directory()),
                MODULE_PATH.parent / "Saved",
            )

    def test_collect_sources_in_groups_and_nested_groups(self):
        solid = {"name": "Solid", "type": "color_source"}
        gradient = {"name": "Gradient", "type": "gradient_source"}
        nested = {"name": "Nested group", "type": "group", "items": [gradient]}
        group = {"name": "Group", "type": "group", "items": [solid, nested]}
        scenes = {name: {"name": name, "items": []} for name in visual_presets.SCENE_NAMES}
        scenes[visual_presets.SCENE_NAMES[0]]["items"] = [group]
        scenes[visual_presets.SCENE_NAMES[1]]["items"] = [solid]
        sources = {item["name"]: item for item in (solid, gradient)}
        lists = []

        def enum_items(container):
            items = list(container["items"])
            lists.append(items)
            return items

        with patch.multiple(
            visual_presets.obs,
            obs_get_source_by_name=MagicMock(
                side_effect=lambda name: scenes.get(name) or sources.get(name)
            ),
            obs_scene_from_source=MagicMock(side_effect=lambda scene: scene),
            obs_scene_enum_items=MagicMock(side_effect=enum_items),
            obs_sceneitem_is_group=MagicMock(side_effect=lambda item: item["type"] == "group"),
            obs_sceneitem_group_enum_items=MagicMock(side_effect=enum_items),
            obs_sceneitem_get_source=MagicMock(side_effect=lambda item: item),
            obs_source_get_unversioned_id=MagicMock(side_effect=lambda source: source["type"]),
            obs_source_get_name=MagicMock(side_effect=lambda source: source["name"]),
            sceneitem_list_release=MagicMock(),
            obs_source_release=MagicMock(),
        ), patch.object(visual_presets, "_source_properties", return_value={}):
            result = visual_presets._collect_sources()
            self.assertEqual([entry["name"] for entry in result], ["Gradient", "Solid"])
            self.assertEqual(result[0]["scenes"], [visual_presets.SCENE_NAMES[0]])
            self.assertEqual(result[1]["scenes"], sorted(visual_presets.SCENE_NAMES[:2]))
            self.assertEqual(visual_presets.obs.sceneitem_list_release.call_count, len(lists))
            for items in lists:
                visual_presets.obs.sceneitem_list_release.assert_any_call(items)

    def test_collect_sources_uses_python_scene_enumeration_and_releases_items(self):
        source = {"name": "Shared color", "type": "color_source"}
        scenes = {name: {"name": name} for name in visual_presets.SCENE_NAMES}
        scene_items = {
            name: ([source, source] if index == 0 else [source] if index == 1 else [])
            for index, name in enumerate(visual_presets.SCENE_NAMES)
        }
        returned_lists = []

        def enumerate_items(scene):
            items = list(scene_items[scene["name"]])
            returned_lists.append(items)
            return items

        with patch.object(visual_presets.obs, "obs_get_source_by_name",
                          side_effect=lambda name: scenes.get(name) or source), \
             patch.object(visual_presets.obs, "obs_scene_from_source",
                          side_effect=lambda scene: scene), \
             patch.object(visual_presets.obs, "obs_scene_enum_items",
                          side_effect=enumerate_items), \
             patch.object(visual_presets.obs, "obs_sceneitem_is_group", return_value=False), \
             patch.object(visual_presets.obs, "obs_sceneitem_get_source",
                          side_effect=lambda item: item), \
             patch.object(visual_presets.obs, "obs_source_get_unversioned_id",
                          side_effect=lambda item: item["type"]), \
             patch.object(visual_presets.obs, "obs_source_get_name",
                          side_effect=lambda item: item["name"]), \
             patch.object(visual_presets.obs, "sceneitem_list_release") as release_items, \
             patch.object(visual_presets.obs, "obs_source_release") as release_source, \
             patch.object(visual_presets, "_source_properties",
                          return_value={"color": "#112233", "alpha": 127}):
            result = visual_presets._collect_sources()

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "Shared color")
        self.assertEqual(result[0]["scenes"], sorted(visual_presets.SCENE_NAMES[:2]))
        self.assertEqual(release_items.call_count, len(visual_presets.SCENE_NAMES))
        for items in returned_lists:
            release_items.assert_any_call(items)
        self.assertEqual(release_source.call_count, len(visual_presets.SCENE_NAMES) + 1)

    def test_obs_color_conversion_preserves_rgb_order_and_alpha(self):
        obs_color = (0x7A << 24) | (0x33 << 16) | (0x22 << 8) | 0x11

        self.assertEqual(visual_presets._obs_color_to_hex(obs_color), "#112233")
        self.assertEqual(visual_presets._hex_to_obs_color("#112233"), 0x332211)
        self.assertEqual(
            visual_presets._validated_properties(
                "color_source", {"color": "#112233", "alpha": 0x7A}
            )["color"],
            obs_color,
        )

    def test_scheme_names_cannot_escape_saved_folder(self):
        self.assertEqual(visual_presets._scheme_filename("../meet:2026"), "_meet_2026")
        with self.assertRaises(ValueError):
            visual_presets._scheme_filename(" ... ")

    def test_gradient_properties_use_obs_setting_names(self):
        properties = {
            "rotation": 270,
            "from_color": "#112233",
            "from_opacity": 95,
            "midpoint_1": 42.5,
            "to_color_1": "#AABBCC",
            "to_opacity_1": 85,
        }
        with patch.object(visual_presets.obs, "obs_source_get_settings", return_value=object()), \
             patch.object(visual_presets.obs, "obs_data_get_double",
                          side_effect=lambda _, key: properties[key]), \
             patch.object(visual_presets.obs, "obs_data_get_int",
                          side_effect=lambda _, key: visual_presets._hex_to_obs_color(
                              properties[key]
                          ) if key in ("from_color", "to_color_1")
                          else properties[key]), \
             patch.object(visual_presets.obs, "obs_data_release"):
            saved = visual_presets._source_properties(object(), "gradient_source")

        self.assertEqual(saved, properties)
        applied = visual_presets._validated_properties("gradient_source", saved)
        self.assertEqual(applied["rotation"], 270.0)
        self.assertEqual(applied["midpoint_1"], 42.5)
        self.assertEqual(applied["from_color"], 0xFF332211)
        self.assertEqual(applied["to_color_1"], 0xFFCCBBAA)

    def test_collect_sources_releases_items_when_enumeration_processing_fails(self):
        scene = object()
        items = [object()]
        with patch.object(visual_presets.obs, "obs_get_source_by_name", return_value=scene), \
             patch.object(visual_presets.obs, "obs_scene_from_source", return_value=scene), \
             patch.object(visual_presets.obs, "obs_scene_enum_items", return_value=items), \
             patch.object(visual_presets.obs, "obs_sceneitem_is_group", return_value=False), \
             patch.object(visual_presets.obs, "obs_sceneitem_get_source",
                          side_effect=RuntimeError("OBS failure")), \
             patch.object(visual_presets.obs, "sceneitem_list_release") as release_items, \
             patch.object(visual_presets.obs, "obs_source_release") as release_source:
            with self.assertRaisesRegex(RuntimeError, "OBS failure"):
                visual_presets._collect_sources()
        release_items.assert_called_once_with(items)
        release_source.assert_called_once_with(scene)

    def test_save_and_load_round_trip_without_changing_other_settings(self):
        sources = {
            "Solid": {"type": "color_source",
                      "settings": {"color": 0x7A332211, "width": 500}},
            "Gradient": {"type": "gradient_source", "settings": {
                "rotation": 123.5, "from_color": 0xFF332211, "from_opacity": 80.5,
                "midpoint_1": 42.5, "to_color_1": 0xFFCCBBAA,
                "to_opacity_1": 65.5, "height": 700,
            }},
            "Image": {"type": "image_source",
                      "settings": {"file": "C:\\images\\logo.png", "unload": True}},
            "Text": {"type": "text_gdiplus", "settings": {
                "font": {"face": "DejaVu Sans", "style": "Bold", "size": 80, "flags": 3},
                "color": 0xFF332211, "opacity": 80,
                "bk_color": 0xFFCCBBAA, "bk_opacity": 30,
                "align": "center", "valign": "bottom", "text": "Current results",
            }},
        }
        scenes = {name: {"type": "scene"} for name in visual_presets.SCENE_NAMES}
        scenes[visual_presets.SCENE_NAMES[0]]["items"] = [
            {"type": "group", "items": ["Solid", "Gradient", "Image", "Text", "Text"]}
        ]
        scenes[visual_presets.SCENE_NAMES[1]]["items"] = ["Solid"]
        original = {name: source["settings"].copy() for name, source in sources.items()}

        def find_source(name):
            return sources.get(name) or scenes.get(name)

        def enum_items(scene):
            return [
                sources[item] if isinstance(item, str) else item
                for item in scene.get("items", [])
            ]

        def set_value(settings, name, value):
            settings[name] = value

        with tempfile.TemporaryDirectory() as directory, \
             patch.object(visual_presets, "_saved_directory", return_value=directory), \
             patch.multiple(
                 visual_presets.obs,
                 obs_get_source_by_name=MagicMock(side_effect=find_source),
                 obs_scene_from_source=MagicMock(side_effect=lambda scene: scene),
                 obs_scene_enum_items=MagicMock(side_effect=enum_items),
                 obs_sceneitem_is_group=MagicMock(
                     side_effect=lambda item: item["type"] == "group"
                 ),
                 obs_sceneitem_group_enum_items=MagicMock(side_effect=enum_items),
                 obs_sceneitem_get_source=MagicMock(side_effect=lambda item: item),
                 obs_source_get_id=MagicMock(
                     side_effect=lambda source: "color_source_v3"
                     if source["type"] == "color_source" else source["type"]
                 ),
                 obs_source_get_unversioned_id=MagicMock(
                     side_effect=lambda source: source["type"]
                 ),
                 obs_source_get_name=MagicMock(
                     side_effect=lambda source: next(
                         name for name, item in sources.items() if item is source
                     )
                 ),
                 obs_source_get_settings=MagicMock(
                     side_effect=lambda source: source["settings"].copy()
                 ),
                 obs_data_get_int=MagicMock(side_effect=lambda settings, key: int(settings[key])),
                 obs_data_get_double=MagicMock(
                     side_effect=lambda settings, key: float(settings[key])
                 ),
                 obs_data_get_string=MagicMock(side_effect=lambda settings, key: settings[key]),
                 obs_data_get_obj=MagicMock(side_effect=lambda settings, key: settings[key].copy()),
                 obs_data_create=MagicMock(side_effect=dict),
                 obs_data_set_int=MagicMock(side_effect=set_value),
                 obs_data_set_double=MagicMock(side_effect=set_value),
                 obs_data_set_string=MagicMock(side_effect=set_value),
                 obs_data_set_obj=MagicMock(side_effect=lambda settings, key, value:
                                            settings.update({key: value.copy()})),
                 obs_source_update=MagicMock(
                     side_effect=lambda source, values: source["settings"].update(values)
                 ),
                 obs_data_release=MagicMock(),
                 obs_source_release=MagicMock(),
                 sceneitem_list_release=MagicMock(),
             ):
            path = visual_presets._write_scheme("Meet A")
            with open(path, encoding="utf-8") as file:
                saved = json.load(file)
            self.assertEqual(len(saved["sources"]), 4)
            self.assertEqual(
                next(item for item in saved["sources"] if item["name"] == "Solid")["scenes"],
                sorted(visual_presets.SCENE_NAMES[:2]),
            )
            for source in sources.values():
                source["settings"].clear()
            sources["Solid"]["settings"]["width"] = 1000
            sources["Gradient"]["settings"]["height"] = 1400
            sources["Image"]["settings"]["unload"] = False
            sources["Text"]["settings"]["text"] = "New results"

            applied, warnings = visual_presets._apply_scheme(visual_presets._read_scheme("Meet A"))
            self.assertEqual((applied, warnings), (4, []))
            for name, untouched in (("Solid", "width"), ("Gradient", "height"),
                                    ("Image", "unload"), ("Text", "text")):
                current = sources[name]["settings"].copy()
                self.assertNotEqual(current.pop(untouched), original[name][untouched])
                expected = original[name].copy()
                expected.pop(untouched)
                self.assertEqual(current, expected)

    def test_invalid_text_properties_do_not_partially_apply_scheme(self):
        properties = {
            "font": {"face": "Arial", "style": "Regular", "size": 40, "flags": 0},
            "color": 0xFFFFFFFF, "opacity": 100, "bk_color": 0,
            "bk_opacity": 0, "align": "center", "valign": "bottom",
        }
        entries = [
            {"name": "Solid", "type": "color_source",
             "properties": {"color": "#112233", "alpha": 127}},
            {"name": "Text", "type": "text_gdiplus", "properties": properties},
        ]
        for key, bad in (("opacity", 101), ("bk_color", "white"), ("valign", "left")):
            with self.subTest(key=key):
                invalid = dict(properties, **{key: bad})
                entries[1]["properties"] = invalid
                with patch.object(visual_presets.obs, "obs_get_source_by_name") as find_source:
                    with self.assertRaises(ValueError):
                        visual_presets._apply_scheme({"sources": entries})
                    find_source.assert_not_called()

    def test_existing_preset_without_text_remains_loadable(self):
        source = {"type": "color_source", "settings": {"color": 0}}
        document = {
            "version": 1,
            "sources": [{"name": "Solid", "type": "color_source",
                         "properties": {"color": "#112233", "alpha": 127}}],
        }
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(visual_presets, "_saved_directory", return_value=directory), \
             patch.multiple(
                 visual_presets.obs,
                 obs_get_source_by_name=MagicMock(return_value=source),
                 obs_source_get_unversioned_id=MagicMock(return_value="color_source"),
                 obs_data_create=MagicMock(side_effect=dict),
                 obs_data_set_int=MagicMock(
                     side_effect=lambda data, key, value: data.update({key: value})
                 ),
                 obs_source_update=MagicMock(
                     side_effect=lambda item, values: item["settings"].update(values)
                 ),
                 obs_data_release=MagicMock(),
                 obs_source_release=MagicMock(),
             ):
            with open(Path(directory) / "old.json", "w", encoding="utf-8") as file:
                json.dump(document, file)
            self.assertEqual(
                visual_presets._apply_scheme(visual_presets._read_scheme("old")),
                (1, []),
            )
            self.assertEqual(source["settings"]["color"], 0x7F332211)

    def test_invalid_scheme_is_validated_before_updating_any_source(self):
        entries = [
            {"name": "Solid", "type": "color_source",
             "properties": {"color": "#112233", "alpha": 127}},
            {"name": "Bad", "type": "image_source", "properties": {"file": 42}},
        ]
        with patch.object(visual_presets.obs, "obs_get_source_by_name") as find_source:
            with self.assertRaisesRegex(ValueError, "Image file path"):
                visual_presets._apply_scheme({"sources": entries})
            find_source.assert_not_called()

    def test_save_does_not_change_loaded_selection_behind_dropdown(self):
        with patch.object(visual_presets, "_scheme_name", "New"), \
             patch.object(visual_presets, "_selected_scheme", "Old"), \
             patch.object(visual_presets, "_write_scheme", return_value="New.json"), \
             patch.object(visual_presets, "_refresh_scheme_list"), \
             patch.object(visual_presets.obs, "script_log"):
            visual_presets._save_clicked(object(), object())
            self.assertEqual(visual_presets._selected_scheme, "Old")


if __name__ == "__main__":
    unittest.main()
