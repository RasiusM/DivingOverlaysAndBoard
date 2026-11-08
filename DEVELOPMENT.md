# How The Scripts Work

Developer notes for the OBS Python scripts. For installation and operation, see
[README.md](README.md).

## Modules

| Module | Responsibility |
| --- | --- |
| [diving_overlays.py](diving_overlays.py) | OBS entry script, source selection, DiveRecorder transport and lifecycle. |
| [diverecorder_adapter.py](diverecorder_adapter.py) | Converts raw DiveRecorder records into provider-neutral updates. No OBS imports. |
| [divecalc_adapter.py](divecalc_adapter.py) | Converts DiveCalc JSON snapshots and parses the description table. No OBS imports. |
| [divecalc_receiver.py](divecalc_receiver.py) | Bounded HTTP receiver and worker lifecycle. |
| [update_mailbox.py](update_mailbox.py) | Ordered, bounded, generation-guarded worker-to-OBS handoff. |
| [datatypes.py](datatypes.py) | Raw DiveRecorder records (`DiveMessage`, `DiveListRecord`) and frozen display models. |
| [overlay_controller.py](overlay_controller.py) | Routes updates to the selected A/B event and applies them. Called on the OBS thread only. |
| [state_controls.py](state_controls.py) | A/B selection, per-event state, visibility, autohide, status board, F1-F10 hotkeys. |
| [overlay_data.py](overlay_data.py) | Writes dive/award content into overlay and scoreboard sources. |
| [rankings.py](rankings.py) | Start list/rankings filtering, sorting and pagination. |
| [overlay_script_common.py](overlay_script_common.py) | Settings, load and unload shared by the helper modules. |
| [obs_utils.py](obs_utils.py), [enums.py](enums.py) | Low-level OBS source helpers and scene source names. |

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

OBS source changes must happen on the OBS thread. Script timers run there; TCP
fetch workers and DiveCalc HTTP handlers publish immutable snapshots instead.

```text
UDP timer (200 ms, OBS thread)
  REFEREE  -> parse -> adapt_dive      -> apply_dive
  AVIDEO   -> complete_event(slot)
  UPDATE   -> start TCP worker thread
                 fetch -> parse -> adapt_rankings
                 -> ordered mailbox
DiveCalc HTTP handler -> validate JSON -> adapt -> ordered mailbox
  next tick: drain mailbox -> apply_dive / apply_rankings
```

The mailbox holds up to 200 updates, drops the oldest on overflow and reports the
count on the next timer tick. It does not coalesce dive updates. A generation token
rejects late publishers after a transport stops; each HTTP snapshot is published as
one batch. Concurrent HTTP requests are serialized when they are adapted and
published; request completion order, not connection acceptance order, is used.

| Timer | Owner | Purpose |
| --- | --- | --- |
| `udp_timer_callback` (200 ms) | entry script | Drain updates and, when selected and enabled, receive DiveRecorder UDP. |
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
- DiveCalc always uses A. Rankings snapshots also carry completion and event names,
  even when rankings display is disabled or B is selected.

## Duplicate Suppression

- Transport: an identical consecutive UDP message is ignored, except `UPDATE`.
- Rankings: an identical snapshot does not restart pagination. Reset on A/B switch and
  settings change.

## Lifecycle

- `script_load`: registers hotkeys, starts only the selected source and the inbound timer.
- `script_update`: reloads settings and descriptions; restarts the transport when source or DiveCalc network settings change. Source changes clear cached dives, completion, rankings and display sources.
- `script_unload`: invalidates publishers, stops timers and the receiver, and closes sockets.

When startup changes the initial provider, the display reset waits for the OBS
sources it clears, for up to 10 seconds. Incoming updates remain queued until the
reset runs; genuinely missing sources are then reported by the normal reset.

Python keeps helper modules imported across script reloads, so module state and
hotkey registration can persist. Restart OBS after changing helper modules.

## DiveCalc Communication

The selected source exposes HTTP POST on all interfaces with the configured path,
port and optional IPv4 allowlist. It accepts UTF-8 JSON regardless of content type,
with a 2 MiB body limit and five-second socket timeout. The listener does not use
`SO_REUSEADDR`. Bodies and personal data are not logged. HTTP is unauthenticated;
the firewall and optional source-IP restriction are essential deployment controls.

The adapter treats `dive` and `awards` as display phases, uses the displayed dive's
position for its round, and takes scores and totals directly from the feed. Rankings
are emitted from snapshots with results, with no DiveRecorder guest convention.
`event.finished` explicitly controls completion; DiveRecorder REFEREE sets it false,
and its ENDOFEVENT message sets completion separately. The editable descriptions
are loaded from `Data/dive_descriptions.csv` under the configured root.

For captured `TEAM` events with one dive per round, the adapter uses the active
`diver.dive.participants` for the banner and team standings from `event.results`.
The captured team feed had five untyped judges for one- and two-person dives. The
adapter uses the individual award slots; this layout is not yet verified in OBS.
Typed team judges, unsupported judge
counts and multiple dives per round are rejected. Shared display models are
unchanged, so team events retain the individual-event status and diver label.

Synchro judge layout, penalties, pre-event values, DNS/DNF/DQ and two-machine LAN
behavior need live capture and verification. The receiver
uses the standard threaded HTTP server, so simultaneous slow clients consume worker
threads until their read timeout; deploy on a trusted/restricted network.

## Tests

The suite mocks `obspython` and runs without OBS:

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
```

Loopback tests cover the receiver but not real OBS timers, source lookups, hotkeys,
live DiveRecorder/DiveCalc connections or LAN deployment. Before a competition,
verify the manual matrix in the integration brief, including overlay and scoreboard.
