# Visual Presets utility

Add `visual_presets.py` as a separate script in **OBS > Tools > Scripts**. It is\
independent of `diving_overlays.py` and operates on the active scene collection.\

Enter a name and choose **Save current appearance** to create or replace a JSON\
preset in this `Saved` folder. Choose a preset under **Saved visual presets** and\
select **Load selected preset** to apply it immediately. Saving does not\
automatically change the selected preset. Use **Refresh saved presets** to discover JSON files added to the folder outside OBS.\

Use the gradient, solid color, image, and text checkboxes to select which source types are included.\
The **Source show/hide transitions** checkbox is independent and off by default.\

## Saved properties

- Solid color sources
  - Color
  - Alpha channel
- Gradient sources
  - Rotation
  - From/to colors and opacities
  - Midpoint
- Image sources
  - Image file path
- Text (GDI+) sources
  - Font
  - Text/background colors and opacities
  - Horizontal/vertical alignment
- Source show/hide transitions
  - Transition type
  - Duration
  - Transition-specific settings, including stinger video paths

Sources inside groups are included. Transitions cover items of all types,\
including groups and nested group items. Scene transitions, text content, and\
other source settings are never saved or changed.\

## Saving and loading

Saving writes only the selected types, and replacing an existing preset removes its unselected types.\

Loading applies only types that are both selected and present in the preset;\
other sources are unchanged. Select at least one source type or transitions\
before saving or loading. Older presets without transitions leave them unchanged.\

Transitions are associated with individual scene items, not just source names.\
If an item is removed, recreated, renamed, or moved between groups, it may no\
longer match its preset and is skipped with a warning in the OBS log. Missing\
transition plugins are also reported and the affected transition is left unchanged.\

## Included scenes

The utility scans the following scenes:\

- Schedule Design
- Livestream Lists Header Design
- Livestream Elements Design
- Board Lists Design
- OverlaySchedule
- OverlayCountdown
- OverlayEvent
- OverlayRankings
- BoardEvent
- BoardRankings
- Replay Scene 1
- Replay Scene 2
- Replay Scene 3

After changing the script's scene list, restart OBS if removing and adding the\
script still uses the old list. Save each preset\
again to capture newly included scenes; existing presets cannot restore settings\
that were never captured.\

Sources shared between scenes are saved once, keyed by their OBS source name;\
renaming a source may require\
resaving the preset. Errors and missing sources are reported in the OBS log.\
