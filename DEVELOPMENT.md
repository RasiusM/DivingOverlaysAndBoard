# How The Scripts Work

Developer notes for the OBS Python scripts. For installation and operation, see
[README.md](README.md).

## Modules

| Module | Responsibility |
| --- | --- |
| [dive_recorder_overlays.py](dive_recorder_overlays.py) | OBS entry script. UDP receive loop, TCP file fetch, DiveRecorder packet parsing, lifecycle. |
| [diverecorder_adapter.py](diverecorder_adapter.py) | Converts raw DiveRecorder records into provider-neutral updates. No OBS imports. |
| [datatypes.py](datatypes.py) | Raw DiveRecorder records (`DiveMessage`, `DiveListRecord`) and frozen display models. |
| [overlay_controller.py](overlay_controller.py) | Routes updates to the selected A/B event and applies them. Called on the OBS thread only. |
| [state_controls.py](state_controls.py) | A/B selection, per-event state, visibility, autohide, status board, F1-F10 hotkeys. |
| [overlay_data.py](overlay_data.py) | Writes dive/award content into overlay and scoreboard sources. |
| [rankings.py](rankings.py) | Start list/rankings filtering, sorting and pagination. |
| [overlay_script_common.py](overlay_script_common.py) | Settings, load and unload shared by the helper modules. |
| [obs_utils.py](obs_utils.py), [enums.py](enums.py) | Low-level OBS source helpers and scene source names. |
| [divecalc_feed_probe.py](divecalc_feed_probe.py) | Standalone research tool for DiveCalc HTTP feeds. Not used by OBS. |

Only the entry script and adapter know DiveRecorder field layouts. Everything after
the adapter consumes `DiveUpdate`, `RankingsUpdate` and `EventDetails`.

## DiveRecorder Communication

DiveRecorder broadcasts UDP messages to port 58091. Fields are separated by `|`.

| Message | Handling |
| --- | --- |
| `REFEREE` | Next dive or awards. Parsed into `DiveMessage` (74 fields), adapted to `DiveUpdate`. |
| `UPDATE` | Notification that `Update.txt` changed. Triggers a TCP fetch (when rankings are enabled). |
| `AVIDEO ... ENDOFEVENT` | Marks the event in field 1 (`a`/`b`) as completed. |
| `AWARD` | Sent per judge score. Currently ignored. |

The `Update.txt` fetch connects to TCP port 58291 on the IP from the UPDATE message,
sends `XFER|Update.txt`, and reads a 4-byte big-endian length followed by a UTF-16LE
payload. The payload starts with the same header fields as `REFEREE`; list records
of six fields (rank, points, unknown, diver, start position, club) begin at field 74.

DiveRecorder conventions translated by the adapter:

- Blank J1 means upcoming dive; any J1 value, including `0`, means awards.
- A REFEREE message reopens a completed event.
- Negative rank means guest diver; zero rank is treated as guest/unranked.
- Penalty reason codes are mapped to English text.

## Threads And Timers

OBS source changes must happen on the OBS thread. Script timers run there; the only
other threads are TCP fetch workers.

```text
UDP timer (200 ms, OBS thread)
  REFEREE  -> parse -> adapt_dive      -> apply_dive
  AVIDEO   -> complete_event(slot)
  UPDATE   -> start TCP worker thread
                 fetch -> parse -> adapt_rankings
                 -> pending_rankings_updates[slot]  (under lock)
  next tick: take pending snapshots    -> apply_rankings
```

Workers never touch OBS sources. They publish an immutable snapshot under
`ranking_records_lock`; the UDP timer takes it and applies it after releasing the lock.

| Timer | Owner | Purpose |
| --- | --- | --- |
| `udp_timer_callback` (200 ms) | entry script | Receive UDP, apply pending rankings. |
| `tv_banner_remove_callback` (setting `dinterval`) | state_controls | Autohide after an upcoming dive. Replaced on each upcoming dive; cancelled on A/B switch. |
| `_advance_page` (setting `rnk_display_duration`) | rankings | Cycle list pages. |
| `set_source_paths` (3 s, max 10 retries) | overlay_data | Set replay paths once scene sources exist. |

## Event A/B Selection

DiveRecorder can run two events (A and B); the operator displays one (F4).

- Dive updates and completion are stored for both events; only the selected one is displayed.
- Switching clears the display, cancels the hide timer, and restores the selected
  event's latest dive (shown with F7) and completion status.
- Rankings are only accepted for the selected event and are not kept per event; the
  list fills on the next UPDATE after a switch.
- F1-F3 mode is never changed automatically by incoming data.

## Duplicate Suppression

- Transport: an identical consecutive UDP message is ignored, except `UPDATE`.
- Rankings: an identical snapshot does not restart pagination. Reset on A/B switch and
  settings change.

## Lifecycle

- `script_load`: registers hotkeys, loads settings, binds the UDP socket, starts the UDP timer.
- `script_update`: reapplies settings; can enable/disable UDP polling.
- `script_unload`: stops timers, rejects late TCP worker results, closes the socket.

Python keeps helper modules imported across script reloads, so module state and
hotkey registration can persist. Restart OBS after changing helper modules.

## Adding A Scoring Source

A new source needs its own transport and adapter producing `DiveUpdate` /
`RankingsUpdate`, then calls the controller on the OBS thread. Network handlers must
hand data over like the TCP workers do rather than calling OBS directly.

Known DiveRecorder-specific behavior to revisit for another source:

- `apply_dive` clears completion on every dive (DiveCalc sends dives after an event finishes).
- Zero rank is treated as guest, which may hide pre-event start lists from other sources.
- `EventDetails.slot` is DiveRecorder's A/B; another source must choose a slot.

## Tests

The suite mocks `obspython` and runs without OBS:

```powershell
python -m unittest discover -s tests -p test_overlay_pipeline.py -v
```

It does not cover real timers, source lookups, hotkeys, or a live DiveRecorder
connection. Before a competition, test start lists, pre-dive info, awards/penalties,
rankings, guests, A/B switching and F5-F9 with both individual and synchro events,
on the stream overlay and the venue scoreboard.
