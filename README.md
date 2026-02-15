# Diving Overlays And Scoreboard

[OBS studio](https://obsproject.com/) Python script/scenes to present springboard/platform diving competition information in overlays for live streaming and on scoreboard in venue.  
Python port and heavy refactoring from [Andy's DR2TVOverlay](https://github.com/andy5211d/DR2TVOverlay)  
Designed more for "single man orchestra" operations :) - automated as much as possible.   
Supported diving software: [DiveRecorder 7.0.7.6](https://diverecorder.co.uk)

**Functionality**:

- Supported event types:
    - Individual
    - Synchro

- Event modes:
    - Waiting for event displays
        - Countdown to next event (managed by Countdown Timer in OBS)
        - Event schedule (from text file)
        - Start list (UDP/TCP communication with DiveRecorder)
        - Dive replays ("Highlights") from recorded Instant Replay clips (in development)
    - Event in progress
        - Next Diver/Dive information (UDP from DiveRecorder)
        - Dive scores/penalties/totals (UDP from DiveRecorder)
        - Instant dive replay (OBS hotkeys)
    - Event results
        - Rankings (UDP/TCP communication with DiveRecorder)
        - Reveal/Show All modes (managed from DiveRecorder)
        - Dive replays from recorded Instant Replay clips (in development)

- Streaming:
    - Multiple camera support. Camera switches performed by hotkeys, not scene switching in OBS
    - Instant Replay (slow motion)
    - Instant Replay source can be set to specific camera in multiple camera setup or to active camera.
      
- Video Scoreboard
    - Data from DiveRecorder is displayed simultanously in overlays for video live streaming and scenes, that can be used on video scoreboards
      
- Simultaneous events
    - can choose one of events (A or B) - can switch anytime, but not recommended (i.e. switch to correct one before event)
    - streaming info of both events is not supported

- Status/Common hotkeys board

- Language - English only (dive position/penalty text hardcoded, dive description is provided by DiveRecorder)

## Installation

### Required OBS Plugins:

- Countdown Timers (for event countdown)
- Gradient Source (for graphics elements)
- Move Transition (for instant replay transitions)
- Source Dock (for status board)
- advanced-scene-switcher (for scene scripting)
- dir-watch-media (for instant replay support)
- osi-branch-output (for instant replay support)

### Python

Python 3.10 (latest supported by OBS). Set the path in OBS script settings.

### Script/scene installation

Download ZIP, unzip into local folder, import Scene Collection and Profile, point OBS to script dive_recorder_overlays.py

*More detailed instructions to come...*

### Camera setup

Most likely you will need to add and use your specific camera source(s).
1. Add source to scene *Active Video Source* - this scene is used as video source for streaming.
2. Set source to not visible
3. Add this source to Video Source for Replay, set it to not visible.
4. Open Advenced Scene Switcher, add this camera to *Active camera switches/Hide all camera sources* macro (similar to already existing actions)
5. Duplicate one of *When switched to ...* macros and modify it for your camera source.
6. Setup hotkey to Show this camera source (do not set Hide unless you want to go to black scree/preset background). I usually set **Ctrl-Num 1..3** to manage cameras.
7. Repeat for all your cameras.

You can use some recording as fake camera to test whole setup - just point *Active Video Source/Fake Camera* to your file.  

### Instant replay setup

Scene/source, that is set to visible in *Video Source for Replay* will be used for recording clips for instant replays.  
To use specific camera, set that camera source to visible.  
To use camera, currently active in streaming, set *Active Video Source* subscene to visible.  

This is convenient if you would like to stream dive in real time from various cameras, but always show dive repeat from single camera.  
**Notes:**
- Replay clips are placed in Replay folder.  This folder is not cleaned-up - take care of it! Next time you start OBS after cleanup, you might get error about missing replay file. Ignore it.
- Why not use "Native" OBS studio Replay buffer? Unreliable.
- There's some lag between hotkey press and recording. Get some practice!
- Replay clips are limited to 10s - recording will stop automatically. Some divers take their time on the board. Might want to setup hotkey to cut recording short without showing replay and start recording again (TODO).

### Media

Replace files with your art in Media/Art folder. If picture sizes are different from current ones, sources might need adjusting in corresponding scenes.

## Operation

### Scenes

- use *LiveStream Composite* for streaming.
- use *ProjectorScreen Composite* for HD Video scoreboard (1920x1080): Right click on scene->Open Scene Projector->Select scoreboard display.

### Main Hotkeys

**Scene controls:**  
**F1** - switch to Waiting for Event scene  
**F2** - switch to Event in Progress scene  
**F3** - switch to Event Completed scene  

**Event controls:**  
**F4** - toggle between A and B events  

**Overlay controlls:**  
**F5** - hide overlays temporary, clear scoreboard screen until next update from DiveRecorder  
**F6** - redisplay top overlay, no effect in scoreboard  
**F7** - redisplay all overlays, redisplay scoreboard  
**F8** - disable overlays, clear scoreboard until re-enabled  
**F9** - turn off autohide, overlays shown permanently, no effect on scoreboard.  
**F10** - toggle position of top overlay  

**Num 0** - start recording for instant replay  
**Ctrl-Num 0** - stop recording and show instant replay  

**Num +** - show/hide instant replay  
**Num -** - show repeats (repeats are played until switched to different camera)  

**Overlay toggles in Waiting for Event mode**  
**Ctrl-Q** - countdown display  
**Ctrl-W** - start list (valid only when recording is setup in DiveRecorder)  
**Ctrl-E** - schedule (set the text in Data/schedule.txt)  

**Ctrl-R** - toggle rankings overlay in Event Complete mode  


### Notes

Meet title/event title will not be populated unless DiveRecorder is in Recording or Results Display mode.

*More detailed instructions to come...*
