# Competition pacing

A standalone desktop app for monitoring the schedule of one DiveCalc event.
It does not require OBS, the overlay scripts, or any packages from `pip`.
You can copy `competition_pacing.py` to another computer with Python 3.10 or
newer and Tkinter installed.

## Set up DiveCalc

1. From the repository folder, start the app:

   ```powershell
   python .\Utils\CompetitionPacing\competition_pacing.py
   ```

2. In DiveCalc, add a **Result Feed** device for **JSON over HTTP**. If the app
   and DiveCalc are on the same computer, enter
   `http://127.0.0.1:8766/divecalc`. Add a separate device if you already send
   results to OBS; leave the OBS device as it is.
3. Assign **Display Awards** to **Accept Awards** and **Present Dive** to
   **Next Diver**. Use **Present Event** before the first dive so the schedule
   appears and you can set the actual start.

If you're running the app on another computer, start it with
`--bind <app-computer-IPv4>` and substitute that address for `127.0.0.1` in
the DiveCalc device URL. Allow inbound TCP port `8766` on that computer,
restricted to the DiveCalc computer. The receiver has no authentication; don't
expose it to the internet. If DiveCalc stops sending after you restart the app,
disconnect and reconnect the Result Feed device.

## Read the display

- **Present Event** loads the schedule without starting the dive timer. Use
  **Set Start Time** before the first **Next Diver** if you want to record the
  actual event start instead of showing the scheduled start.
- The main timer counts up from **Next Diver**. It turns green for the last
  five seconds of **Required** as a cue to press **Next Diver** when ready.
  It turns red if the dive exceeds **Required** or the event misses its deadline.
  The scheduled end is still shown, without a countdown.
- **Time per dive** stacks three rows with their times aligned in one column.
  **Required** is calculated at **Next Diver**: time left until the scheduled
  end divided by the remaining dives, including the one just started. It stays
  fixed during that dive and shows **Missed deadline** once time runs out.
  **Last dive** measures the time from one **Next Diver** to the next,
  including any wait after scoring. For the final dive, **Accept Awards**
  stops the timer and records the last duration.
- The finish estimate uses the **Average** of the dive times the app has
  measured. It appears once the app has timed a dive and carries across rounds.
  Before the deadline, the estimate is **green** when it's between 5 minutes
  early and 2 minutes late (inclusive), **blue** when earlier, and **red** when
  later. Once the deadline passes it stays **red**, but the estimate keeps
  updating until the event finishes. Without a scheduled end, the app still
  estimates the finish without a target color.
- To change the tolerance, add `--early-minutes 5 --late-minutes 2` to the launch
  command and replace the numbers. Add `--port <port>` if you need a different
  listening port, and use that port in the DiveCalc URL too.

The app is for **single events**, not event groups that alternate rounds across
multiple events. DiveCalc's documented Result Feed has no group ID or member list;
a grouped-session capture is needed to check for undocumented fields. The app
shows the schedule but withholds an estimate when DiveCalc doesn't report enough
progress, an entry withdraws or is disqualified, or an entry has multiple dives
per round.
