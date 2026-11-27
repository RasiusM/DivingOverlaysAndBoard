'''
Diving Overlays/Board OBS Script for DiveRecorder and DiveCalc
'''
# Converted from divingoverlaysV4.0.0.lua (Andy)
import typing

if typing.TYPE_CHECKING:
    import _obspython as obs  # full symbol set for IDE
else:
    import obspython as obs   # real runtime module

import socket
import threading
import os
import ipaddress
from typing import Union

# local imports
from datatypes import DiveMessage, DiveListRecord, DiveUpdate, EventStartUpdate, RankingsUpdate
from diverecorder_adapter import adapt_dive, adapt_rankings
from overlay_controller import apply_dive, apply_rankings, complete_event
from overlay_script_common import dvov_script_properties, dvov_script_defaults, dvov_script_update, dvov_script_load, dvov_script_unload
from obs_utils import is_source_available, log_info_if_debug, update_event_countdown
from enums import (EventABGrp, EventInfo, IndividualAwards, JudgeAwardsBoardGrp,
                   MainBoardGrp, PostEventGrp, RankingsSrc, SynchroAwards, TVBannerGrp)
from update_mailbox import UpdateMailbox
from divecalc_adapter import parse_descriptions
from divecalc_receiver import DiveCalcReceiver
import state_controls

# ---------- Globals
portClient = 58091  # main port for DR broadcast data
tcp_port = 58291  # DiveRecorder listening TCP port

last_message_text = ""
udp_polling_enabled = True
scoring_source = "diverecorder"
selected_scoring_source = "diverecorder"
receiver = None
transport_config = None
script_loaded = False
replay_enabled = False
replay_trigger_signal = ""
REPLAY_CONDITION_NAME = "DiveCalc Request Awards received"
DEFAULT_REPLAY_PATH = "/divecalc-replay"
DEFAULT_REPLAY_COOLDOWN = 5
# OBS can load the script before its scene sources. A saved provider different
# from the default triggers a reset at startup, so defer that reset until ready.
startup_reset_pending = False
startup_reset_attempts = 0
STARTUP_RESET_MAX_ATTEMPTS = 50  # 200 ms timer intervals, approximately 10 seconds
# Mirror the text, file and status sources written by set_event_a's reset.
# Keep this list in sync with overlay_data.clear_data and rankings.clear_data.
STARTUP_RESET_SOURCES = (
    EventABGrp.AActive, EventABGrp.BActive, PostEventGrp.EventCompleted,
    EventInfo.Info, EventInfo.Title, EventInfo.DiverNo, EventInfo.RoundNo,
    TVBannerGrp.Diver, TVBannerGrp.Flag, TVBannerGrp.Rank, TVBannerGrp.Total,
    MainBoardGrp.Flag1, MainBoardGrp.Flag2, MainBoardGrp.Diver1, MainBoardGrp.Diver2,
    RankingsSrc.HeaderMeet, RankingsSrc.HeaderEvent, RankingsSrc.HeaderListType,
) + tuple(
    f"{prefix}{index}"
    for prefix, count in (
        (IndividualAwards.JudgePrefix, 7), (JudgeAwardsBoardGrp.JExecPrefix, 7),
        (SynchroAwards.JudgeSynchroPrefix, 5), (JudgeAwardsBoardGrp.JSynchroPrefix, 5),
        (RankingsSrc.RankPrefix, 10), (RankingsSrc.NamePrefix, 10),
        (RankingsSrc.TeamPrefix, 10), (RankingsSrc.ScorePrefix, 10),
    )
    for index in range(1, count + 1)
)
descriptions = {}
warned_inactive = False

# settings (populated via script_update)
debug = False

# internal state
activeId = 0
id_ = 0

# flag to indicate if rankings retrieval and update is enabled (script setting)
rankings_enabled = False

# UDP socket and polling
udp_sock: Union[socket.socket, None] = None

# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# ---------- Parsing and message processing ----------
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

# ---- parser helper: converts parts[] → DiveMessage ----
def parse_dive_message(parts):
    # ensure list has 75 so indexes 0..73 exist
    padded = parts + [""] * (75 - len(parts))

    # create the dataclass from indexes 0..73
    return DiveMessage(
        *padded[0:74]  # unpack first 74 elements (0..73)
    )

tcp_receive_timeout = 1.0  # seconds per recv

# TCP workers and HTTP handlers publish snapshots for the OBS timer to apply.
mailbox = UpdateMailbox()
transport_generation = 0

# ---- parser helper: converts UPDATE message → List[RankingRecord] ----
def parse_update_message(msg: str):
    """
    Parse UPDATE message beginning at the given field index (1-based).
    Converts data into Record instances with correct types.
    """

    start_field: int = 74
    rec_size: int = 6

    fields = msg.split("|")

    # Parse event record from start of message (same as for REFEREE, but only meet/event info is relevant)
    rankings_event_rec = parse_dive_message(fields)

    # Convert to zero-based index
    start_idx = start_field - 1

    if start_idx >= len(fields):
        return [], rankings_event_rec

    remaining = fields[start_idx:]
    records = []
    exception_count = 0

    for i in range(0, len(remaining), rec_size):
        chunk = remaining[i:i+rec_size]
        if len(chunk) < rec_size:
            break   # Incomplete last chunk → stop

        rank_str, points_str, unknown, diver, start_pos_str, club_code = chunk

        try:
            record = DiveListRecord(
                rank=int(rank_str) if rank_str.strip() else 0,
                points=points_str.strip(),
                unknown=unknown.strip(),
                diver=diver.strip(),
                start_position=int(start_pos_str) if start_pos_str.strip() else 0,
                club_code=club_code.strip(),
            )
            records.append(record)
            log_info_if_debug(debug, f"Parsed Record: {record}")

        except Exception:
            # If any conversion fails, skip this chunk safely
            exception_count += 1
            if exception_count <= 5:
                obs.script_log(obs.LOG_WARNING, f"Failed to parse ranking record chunk: {chunk}")
                continue
            else:
                obs.script_log(obs.LOG_WARNING, "Multiple parsing errors encountered; further errors will be suppressed.")
                break

    log_info_if_debug(debug, f"Finished parsing UPDATE message, total records: {len(records)}")

    return records, rankings_event_rec

# --- Non-blocking fetch function ---
def fetch_update_file_async(ip_address: str, message_file_name: str):
    """
    Starts a background thread to fetch the update file from DiveRecorder.
    """
    # Capture the generation before starting the worker, not when it finishes.
    thread = threading.Thread(target=_fetch_update_file, args=(ip_address, message_file_name, transport_generation))
    thread.daemon = True  # thread will exit when OBS exits
    thread.start()

# Initiate TCP connection to fetch file (most likely Update.txt)
def _fetch_update_file(ip_address: str, message_file_name: str, generation=None):
    """
    Connects to DiveRecorder TCP port, requests given remote file,
    parses the response, and publishes an immutable rankings update.

    ip_address: str - IP from UDP message
    message_file_name: str - file path received in UDP message (e.g., Update.txt)
    """

    def recv_exact(sock, n):
        buf = b''
        while len(buf) < n:
            chunk = sock.recv(n - len(buf))
            if not chunk:
                raise Exception("Connection closed early")
            buf += chunk
        return buf

    global tcp_port, tcp_receive_timeout

    if generation is None:
        generation = transport_generation

    try:
        HOST = ip_address
        PORT = tcp_port

        log_info_if_debug(debug, f"Initiating TCP connection to {ip_address}:{tcp_port} for file {message_file_name}")

        with socket.create_connection((HOST, PORT), timeout=tcp_receive_timeout) as s:
            request_text = f"XFER|{message_file_name}\n"
            s.sendall(request_text.encode('utf-8'))

            s.settimeout(tcp_receive_timeout)

            # Step 1: read the 4-byte header
            header = recv_exact(s, 4)

            # interpret length of payload (adjust endianness as needed)
            payload_len = int.from_bytes(header, 'big')  # or 'little'
            log_info_if_debug(debug, f"Payload length from header: {payload_len}")

            # Step 2: read the full payload
            chunks = []
            bytes_read = 0
            while bytes_read < payload_len:
                chunk = s.recv(min(4096, payload_len - bytes_read))
                if not chunk:
                    raise Exception("Connection closed before full message received")
                chunks.append(chunk)
                bytes_read += len(chunk)

            # flush remaining bytes until remote closes
            try:
                while True:
                    if not s.recv(1024):
                        break
            except:
                pass

            s.settimeout(None)

        data = b''.join(chunks)

        # Step 3: decode UTF-16LE text (skip BOM if needed)
        message_file_contents = data.decode('utf-16le')
        log_info_if_debug(debug, f"Message File Contents:\n{message_file_contents}")

        parsed_records, parsed_event_record = parse_update_message(message_file_contents)
        update = adapt_rankings(parsed_records, parsed_event_record)
        # Publish only data here. Source updates and pagination belong to the
        # OBS timer; an in-flight fetch must not repopulate state after unload.
        if not mailbox.publish(update, generation):
            return False
        obs.script_log(obs.LOG_INFO, "Rankings data updated, flagged for main thread processing.")

        return True

    except Exception as e:
        # A worker outliving script unload must not call into OBS.
        if generation == transport_generation:
            obs.script_log(obs.LOG_ERROR, f"Failed to fetch update file from {ip_address}:{tcp_port} - {e}")
        return False

# ---------- Process incoming UDP messages ----------
def process_udp_message(k: str):
    log_info_if_debug(debug, "process_udp_message()")

    if not k:
        return

    # Split message
    parts = k.split("|")
    if parts and parts[-1].endswith("\r"):
        parts[-1] = parts[-1][:-1]
    if parts:
        log_info_if_debug(debug, f"UDP message: {parts}")

    # --- parse into dataclass ---
    if (parts[0] == "REFEREE"):
        # Only the parser/adapter sees wire fields; downstream code gets an
        # explicit phase, formatted names, and provider-independent event data.
        apply_dive(adapt_dive(parse_dive_message(parts)))


    elif parts[0] == "UPDATE" and rankings_enabled:
        if rankings_enabled:
            # Example: UPDATE|a|DIVING_CONTUPER|1|192.168.1.1|C:\ProgramData\MDT\DiveRecorder\Xfer\Update.txt|^
            if len(parts) >= 6:
                ip_addr = parts[4]

                dive_recorder_message_filename = os.path.basename(parts[5])  # just the filename, e.g.
                if dive_recorder_message_filename == "Update.txt":
                    fetch_update_file_async(ip_addr, dive_recorder_message_filename)
                else:
                    obs.script_log(obs.LOG_WARNING, f"Received unrecognized remote file reference: {dive_recorder_message_filename}")

    elif parts[0] == "AVIDEO":
        # AVIDEO|a|EMEA300365|1|ENDOFEVENT|^
        if len(parts) >= 5:
            if parts[4] == "ENDOFEVENT":
                log_info_if_debug(debug, "AVIDEO ENDOFEVENT received, marking event complete.")
                complete_event(parts[1])

    elif parts[0] == "AWARD":
        # TODO: dive recorder sends AWARD(s) message after each judge score is entered. So it is possible to implement "live" display of scores after a dive
        pass



#---------- UDP polling (called on OBS timer) ----------
def udp_timer_callback():
    global id_, activeId, udp_sock, last_message_text, startup_reset_pending, startup_reset_attempts, warned_inactive

    # If script reloaded, stop old timer
    if id_ < activeId:
        try:
            obs.remove_current_callback()
        except Exception:
            pass
        return

    # Do not drain incoming updates until the reset has run: otherwise it could
    # erase fresh data. Once reset, source lookups are skipped on later ticks.
    if startup_reset_pending:
        startup_reset_attempts += 1
        ready = all(is_source_available(name) for name in STARTUP_RESET_SOURCES)
        if not ready and startup_reset_attempts < STARTUP_RESET_MAX_ATTEMPTS:
            return
        # Stop waiting even for a missing source; the normal reset logs it.
        startup_reset_pending = False
        state_controls.set_event_a(state_controls.event_ab_is_a)

    # Take ownership of pending snapshots atomically. Do not hold the worker
    # lock while invoking OBS helpers or restarting list pagination.
    updates, dropped = mailbox.drain()
    if dropped:
        obs.script_log(obs.LOG_WARNING, f"Dropped {dropped} incoming updates because the mailbox was full.")

    for update in updates:
        try:
            if scoring_source == "divecalc" and not state_controls.event_ab_is_a and not warned_inactive:
                obs.script_log(obs.LOG_WARNING, "DiveCalc data is assigned to event A; event B is selected.")
                warned_inactive = True
            if state_controls.event_ab_is_a:
                warned_inactive = False
            log_info_if_debug(debug, "Processing incoming update on main thread...")
            if isinstance(update, DiveUpdate):
                apply_dive(update)
            elif isinstance(update, RankingsUpdate):
                if rankings_enabled:
                    apply_rankings(update)
                else:
                    apply_rankings(update, show_rankings=False)
            elif isinstance(update, EventStartUpdate):
                # Browser updates belong on the OBS thread, including Present Event.
                update_event_countdown(update.start_time, debug_enabled=debug)
        except Exception as e:
            obs.script_log(obs.LOG_ERROR, f"Error processing incoming update: {e}")

    if scoring_source != "diverecorder" or not udp_polling_enabled:
        return

    # Non-blocking socket recv
    try:
        while True:
            try:
                if udp_sock is None:
                    obs.script_log(obs.LOG_ERROR, "UDP socket is not initialized.")
                    break
                data, addr = udp_sock.recvfrom(8192)
                # Log the received UDP packet for debugging purposes (had a situation where OBS would not react to DiveRecorder actions at all)
                # obs.script_log(
                #     obs.LOG_INFO,
                #     f"UDP received: sender={addr}, bytes={len(data)}, "
                #     f"local={udp_sock.getsockname()}, preview={data[:100]!r}"
                # )
            except BlockingIOError:
                break

            if data:
                text = data.decode(errors='replace')

                # compare to last message to avoid duplicate processing
                # process only if different from last or an UPDATE message (UPDATE is always the same, so we force process)
                if last_message_text != text or text.startswith("UPDATE|"):
                    last_message_text = text

                    log_info_if_debug(debug, f"UDP Message Text: {text}")

                    process_udp_message(text)

    except Exception as e:
        obs.script_log(obs.LOG_ERROR, f"UDP polling error: {e}")


# ---------- OBS script lifecycle ----------
def script_description():
    return "<center><h2>Diving Overlays v2.0.0 (beta.1)</h2></center><p>Display competition data from DiveRecorder or DiveCalc using the Diving Streaming and Board scene collection.</p>"


def set_scoring_source_visibility(props, source, enable_replay):
    """Show the selected source's settings without changing their saved values."""
    obs.obs_property_set_visible(obs.obs_properties_get(props, "udp_polling_enabled"), source == "diverecorder")
    for name in ("divecalc_port", "divecalc_path", "divecalc_allowed_ip", "divecalc_replay_enabled"):
        obs.obs_property_set_visible(obs.obs_properties_get(props, name), source == "divecalc")
    for name in ("divecalc_replay_path", "divecalc_replay_cooldown"):
        obs.obs_property_set_visible(obs.obs_properties_get(props, name), source == "divecalc" and enable_replay)


def scoring_source_modified(props, property, settings):
    """Refresh property visibility when OBS changes the scoring source."""
    source = obs.obs_data_get_string(settings, "scoring_source") or "diverecorder"
    set_scoring_source_visibility(props, source, obs.obs_data_get_bool(settings, "divecalc_replay_enabled"))
    # Tell OBS to rebuild the property UI with the updated visibility.
    return True


def script_properties():
    log_info_if_debug(debug, "------------------------------ script_properties() called")

    props = obs.obs_properties_create()

    # register common properties
    dvov_script_properties(props)

    source = obs.obs_properties_add_list(props, "scoring_source", "Scoring source", obs.OBS_COMBO_TYPE_LIST, obs.OBS_COMBO_FORMAT_STRING)
    obs.obs_property_list_add_string(source, "DiveRecorder", "diverecorder")
    obs.obs_property_list_add_string(source, "DiveCalc", "divecalc")
    obs.obs_properties_add_bool(props, "udp_polling_enabled", "Enable DiveRecorder UDP Polling")
    obs.obs_properties_add_int(props, "divecalc_port", "DiveCalc HTTP port", 1024, 65535, 1)
    obs.obs_properties_add_text(props, "divecalc_path", "DiveCalc HTTP path", obs.OBS_TEXT_DEFAULT)
    obs.obs_properties_add_text(props, "divecalc_allowed_ip", "Allowed DiveCalc IPv4 address (optional)", obs.OBS_TEXT_DEFAULT)
    replay = obs.obs_properties_add_bool(props, "divecalc_replay_enabled", "Enable replay control from DiveCalc")
    obs.obs_properties_add_text(props, "divecalc_replay_path", "DiveCalc replay HTTP path", obs.OBS_TEXT_DEFAULT)
    obs.obs_properties_add_int(props, "divecalc_replay_cooldown", "Replay request cooldown (seconds)", 1, 60, 1)
    obs.obs_property_set_modified_callback(source, scoring_source_modified)
    obs.obs_property_set_modified_callback(replay, scoring_source_modified)
    # OBS can recreate the property list without applying modification callbacks.
    set_scoring_source_visibility(props, selected_scoring_source, replay_enabled)

    return props


def script_defaults(settings):
    log_info_if_debug(debug, "------------------------------ script_defaults() called")

    obs.obs_data_set_default_bool(settings, "udp_polling_enabled", True)
    obs.obs_data_set_default_string(settings, "scoring_source", "diverecorder")
    obs.obs_data_set_default_int(settings, "divecalc_port", 8765)
    obs.obs_data_set_default_string(settings, "divecalc_path", "/divecalc")
    obs.obs_data_set_default_string(settings, "divecalc_allowed_ip", "")
    obs.obs_data_set_default_bool(settings, "divecalc_replay_enabled", False)
    obs.obs_data_set_default_string(settings, "divecalc_replay_path", DEFAULT_REPLAY_PATH)
    obs.obs_data_set_default_int(settings, "divecalc_replay_cooldown", DEFAULT_REPLAY_COOLDOWN)

    dvov_script_defaults(settings)

def script_update(settings):
    global udp_polling_enabled, debug, rankings_enabled, descriptions, selected_scoring_source
    global replay_enabled
    log_info_if_debug(debug, "------------------------------ script_update() called")

    dvov_script_update(settings)

    debug = obs.obs_data_get_bool(settings, "debug")
    rankings_enabled = obs.obs_data_get_bool(settings, "rankings_enabled")

    udp_polling_enabled = obs.obs_data_get_bool(settings, "udp_polling_enabled")
    source = obs.obs_data_get_string(settings, "scoring_source") or "diverecorder"
    selected_scoring_source = source
    replay_enabled = obs.obs_data_get_bool(settings, "divecalc_replay_enabled")
    path = obs.obs_data_get_string(settings, "divecalc_path") or "/divecalc"
    port = obs.obs_data_get_int(settings, "divecalc_port")
    allowed_ip = obs.obs_data_get_string(settings, "divecalc_allowed_ip").strip()

    # Load dive descriptions if the scoring source is divecalc
    if source == "divecalc":
        try:
            filename = os.path.join(obs.obs_data_get_string(settings, "rootDir"), "Data", "dive_descriptions.csv")
            with open(filename, encoding="utf-8-sig") as file:
                descriptions = parse_descriptions(file.read(), lambda message: obs.script_log(obs.LOG_WARNING, message))
        except (OSError, UnicodeError) as error:
            descriptions = {}
            obs.script_log(obs.LOG_WARNING, f"Could not load dive descriptions: {error}")

    config = (source, port, path, allowed_ip) if source == "divecalc" else (source, 0, "", "")

    if script_loaded:
        if config != transport_config or (source == "divecalc" and receiver is None):
            _restart_transport(config)
        elif receiver:
            receiver.server.descriptions = descriptions
            receiver.server.debug = debug
        if receiver:
            if replay_enabled:
                try:
                    receiver.configure_replay(
                        obs.obs_data_get_string(settings, "divecalc_replay_path").strip(),
                        obs.obs_data_get_int(settings, "divecalc_replay_cooldown"),
                    )
                except ValueError as error:
                    receiver.configure_replay(None)
                    obs.script_log(obs.LOG_ERROR, f"DiveCalc replay control disabled: {error}")
            else:
                receiver.configure_replay(None)


def _check_replay_condition(data):
    current_receiver = receiver
    pending = current_receiver is not None and current_receiver.take_replay_request()
    reply = obs.calldata_create()
    try:
        obs.calldata_set_int(reply, "completion_id", obs.calldata_int(data, "completion_id"))
        obs.calldata_set_bool(reply, "result", pending)
        obs.signal_handler_signal(
            obs.obs_get_signal_handler(), obs.calldata_string(data, "completion_signal_name"), reply
        )
    finally:
        obs.calldata_destroy(reply)


def _register_replay_condition():
    global replay_trigger_signal
    data = obs.calldata_create()
    try:
        obs.calldata_set_string(data, "name", REPLAY_CONDITION_NAME)
        obs.calldata_set_ptr(data, "default_settings", None)
        if (obs.proc_handler_call(obs.obs_get_proc_handler(), "advss_register_script_condition", data)
                and obs.calldata_bool(data, "success")):
            replay_trigger_signal = obs.calldata_string(data, "trigger_signal_name")
            obs.signal_handler_connect(obs.obs_get_signal_handler(), replay_trigger_signal, _check_replay_condition)
    finally:
        obs.calldata_destroy(data)


def _retry_replay_condition_registration():
    obs.timer_remove(_retry_replay_condition_registration)
    _register_replay_condition()
    if not replay_trigger_signal:
        obs.script_log(obs.LOG_WARNING, "Could not register the DiveCalc replay condition. Check Advanced Scene Switcher scripting support.")


def _unregister_replay_condition():
    global replay_trigger_signal
    if not replay_trigger_signal:
        return
    obs.signal_handler_disconnect(obs.obs_get_signal_handler(), replay_trigger_signal, _check_replay_condition)
    replay_trigger_signal = ""
    data = obs.calldata_create()
    try:
        obs.calldata_set_string(data, "name", REPLAY_CONDITION_NAME)
        if not (obs.proc_handler_call(obs.obs_get_proc_handler(), "advss_deregister_script_condition", data)
                and obs.calldata_bool(data, "success")):
            obs.script_log(obs.LOG_WARNING, "Could not deregister the DiveCalc replay condition.")
    finally:
        obs.calldata_destroy(data)


def script_load(settings):
    global script_loaded
    log_info_if_debug(debug, "------------------------------ script_load() called")

    dvov_script_load(settings)

    _register_replay_condition()
    if not replay_trigger_signal:
        obs.timer_add(_retry_replay_condition_registration, 1000)
    script_loaded = True
    script_update(settings)
    init()


def _restart_transport(config):
    global udp_sock, receiver, transport_generation, transport_config, scoring_source, last_message_text, warned_inactive
    global startup_reset_pending, startup_reset_attempts
    old_source = scoring_source
    initial_start = transport_config is None
    if receiver:
        receiver.stop()
        receiver = None
    transport_generation = mailbox.new_token()
    if udp_sock:
        udp_sock.close()
        udp_sock = None
    scoring_source, port, path, allowed_ip = config
    transport_config = config
    last_message_text = ""
    warned_inactive = False
    if old_source != scoring_source:
        # Clear cached state immediately; only the OBS source reset must wait.
        state_controls.latest_dives.clear()
        state_controls.completed_slots.clear()
        state_controls.event_names.clear()
        # Subsequent provider switches reset immediately unless startup is still
        # waiting for sources. The timer performs any deferred reset once.
        if initial_start or startup_reset_pending:
            startup_reset_pending = True
            startup_reset_attempts = 0
        else:
            state_controls.set_event_a(state_controls.event_ab_is_a)
    if scoring_source == "divecalc":
        try:
            if not 1024 <= port <= 65535:
                raise ValueError("port must be between 1024 and 65535")
            if allowed_ip:
                ipaddress.IPv4Address(allowed_ip)
            receiver = DiveCalcReceiver(mailbox, transport_generation, port, path, allowed_ip, descriptions,
                                        warn=lambda message: obs.script_log(obs.LOG_WARNING, message),
                                        log=lambda message: obs.script_log(obs.LOG_INFO, message), debug=debug)
            obs.script_log(obs.LOG_INFO, f"DiveCalc HTTP receiver listening on port {port}")
        except (OSError, ValueError) as error:
            obs.script_log(obs.LOG_ERROR, f"Could not start DiveCalc receiver on port {port}: {error}")
        return
    if scoring_source != "diverecorder":
        obs.script_log(obs.LOG_ERROR, "Unknown scoring source; no transport started.")
        return

    # create and bind UDP socket (non-blocking)
    try:
        udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        udp_sock.setblocking(False)
        # bind to all interfaces on portClient
        udp_sock.bind(("", portClient))
        obs.script_log(obs.LOG_INFO, f"Listening on UDP {portClient}")
    except Exception as e:
        obs.script_log(obs.LOG_ERROR, f"Failed to bind UDP socket: {e}")
        udp_sock = None

def script_unload():
    global udp_sock, transport_generation, receiver, script_loaded, transport_config, startup_reset_pending

    # Stop consumers and invalidate publishers before clearing shared state.
    # Common cleanup also removes timers registered by the helper modules.
    obs.timer_remove(udp_timer_callback)
    obs.timer_remove(_retry_replay_condition_registration)
    script_loaded = False
    transport_config = None
    startup_reset_pending = False
    if receiver:
        receiver.stop()
        receiver = None
    _unregister_replay_condition()
    transport_generation = mailbox.new_token()
    dvov_script_unload()
    if udp_sock:
        try:
            udp_sock.close()
        except Exception:
            pass
        udp_sock = None

def init():
    # increase activeId and start timer loop
    global activeId, id_
    log_info_if_debug(debug, "init()")

    activeId += 1
    id_ = activeId
    obs.timer_add(udp_timer_callback, 200)
    obs.script_log(obs.LOG_INFO, f"Incoming update timer started. Re-start ID: {id_}")
