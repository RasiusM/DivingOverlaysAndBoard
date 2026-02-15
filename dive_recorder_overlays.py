'''
Dive Recorder OBS Overlays/Board Script
Version 1.0.0
'''
# Converted from divingoverlaysV4.0.0.lua (Andy)
import typing

from overlay_data import dvov_act_set_event_complete, dvov_act_single_event_referee_update, dvov_act_single_event_referee_update

if typing.TYPE_CHECKING:
    import _obspython as obs  # full symbol set for IDE
else:
    import obspython as obs   # real runtime module

import socket
import threading
import os
from typing import List, Union

# local imports
from datatypes import DiveMessage, DiveListRecord
from state_controls import dvov_state_on_message, dvov_state_set_event_complete
from rankings import dvov_rank_set_divers
from overlay_script_common import dvov_script_properties, dvov_script_defaults, dvov_script_update, dvov_script_load
from obs_utils import log_info_if_debug

# ---------- Globals
portClient = 58091  # main port for DR broadcast data
tcp_port = 58291  # DiveRecorder listening TCP port

last_message_text = ""
udp_polling_enabled = True

# settings (populated via script_update)
debug = False

# internal state
activeId = 0
id_ = 0

# Update message hash to detect changes
update_message_hash = ""

# flag to indicate if rankings retrieval and update is enabled (script setting)
rankings_enabled = False
rankings_mode = False
event_complete = False

# UDP socket and polling
udp_sock: Union[socket.socket, None] = None
udp_lock = threading.Lock()

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

# ---- global variable to hold parsed structures ----
referee_message: Union[DiveMessage, None] = None

ranking_records: List[DiveListRecord] = []
rankings_event_record: DiveMessage

# need to ensure thread-safe access to rankings_records
ranking_records_lock: threading.Lock = threading.Lock()

# Pending rankings update (processed on main thread to avoid OBS crashes)
pending_rankings_update = False

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
        return []

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
    thread = threading.Thread(target=_fetch_update_file, args=(ip_address, message_file_name))
    thread.daemon = True  # thread will exit when OBS exits
    thread.start()

# Initiate TCP connection to fetch file (most likely Update.txt)
def _fetch_update_file(ip_address: str, message_file_name: str):
    """
    Connects to DiveRecorder TCP port, requests given remote file,
    parses the response, and updates global rankings_records.

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

    global tcp_port, rankings_records, rankings_event_record, tcp_receive_timeout

    try:
        HOST = ip_address
        PORT = tcp_port

        log_info_if_debug(debug, f"Initiating TCP connection to {ip_address}:{tcp_port} for file {message_file_name}")

        with socket.create_connection((HOST, PORT)) as s:
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

        # check if contents have changed and skip parsing/events if same
        global update_message_hash

        log_info_if_debug(debug, "Calculating UPDATE message hash.")

        current_hash = hash(message_file_contents)

        if current_hash != update_message_hash:
            update_message_hash = current_hash

            log_info_if_debug(debug, "NEW UPDATE Message!")

            parsed_records, parsed_event_record = parse_update_message(message_file_contents)

            # Update shared data with minimal lock time
            global pending_rankings_update
            with ranking_records_lock:
                rankings_records = parsed_records
                rankings_event_record = parsed_event_record
                pending_rankings_update = True
            obs.script_log(obs.LOG_INFO, "Rankings data updated, flagged for main thread processing.")

        return True

    except Exception as e:
        obs.script_log(obs.LOG_ERROR, f"Failed to fetch update file from {ip_address}:{tcp_port} - {e}")
        return False

# ---------- Process incoming UDP messages ----------
def process_udp_message(k: str):
    global synchro, resultK, referee_message

    log_info_if_debug(debug, "process_udp_message()")

    if not k:
        return

    # Split message
    parts = k.split("|")
    if parts and parts[-1].endswith("\r"):
        parts[-1] = parts[-1][:-1]
    resultK = parts

    if parts:
        log_info_if_debug(debug, f"UDP message: {parts}")

    # --- parse into dataclass ---
    if (parts[0] == "REFEREE"):
        referee_message = parse_dive_message(parts)
        synchro = (referee_message.synchro_event == "True" and referee_message.event_ab == "a")

        dvov_state_on_message(referee_message)
        dvov_act_single_event_referee_update(referee_message, synchro)

        dvov_state_set_event_complete(False)


    elif parts[0] == "UPDATE" and rankings_enabled:
        referee_message = None

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
                dvov_act_set_event_complete(True)
                dvov_state_set_event_complete(True)

    elif parts[0] == "AWARD":
        # TODO: dive recorder sends AWARD(s) message after each judge score is entered. So it is possible to implement "live" display of scores after a dive
        pass



#---------- UDP polling (called on OBS timer) ----------
def udp_timer_callback():
    global id_, activeId, udp_sock, last_message_text
    global pending_rankings_update, rankings_records, rankings_event_record

    # If script reloaded, stop old timer
    if id_ < activeId:
        try:
            obs.remove_current_callback()
        except Exception:
            pass
        return

    # Process pending rankings update on main thread (thread-safe for OBS API)
    if pending_rankings_update:
        try:
            if not ranking_records_lock.acquire(False):
                return
            try:
                log_info_if_debug(debug, "Processing rankings on main thread...")
                dvov_rank_set_divers(rankings_records, rankings_event_record)
                pending_rankings_update = False
            finally:
                ranking_records_lock.release()
        except Exception as e:
            obs.script_log(obs.LOG_ERROR, f"Error processing rankings: {e}")
            pending_rankings_update = False

    # Non-blocking socket recv
    try:
        while True:
            try:
                if udp_sock is None:
                    obs.script_log(obs.LOG_ERROR, "UDP socket is not initialized.")
                    break
                data, addr = udp_sock.recvfrom(8192)
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
    return "<center><h2>Display DiveRecorder Data as a Video Overlay or Overlays</h2></center><p>Display diver and scores from DiveRecorder for single individual or synchro diving event or simultaneous individual events. The appropriate OBS Source (.json) file must be imported into OBS for this overlay to function correctly. You must be connected to the same Class C sub-net as the DR computers.</p><p>Converted from divingoverlaysV4.0.0.lua</p>"

def script_properties():
    log_info_if_debug(debug, "------------------------------ script_properties() called")

    props = obs.obs_properties_create()

    # register common properties
    dvov_script_properties(props)

    obs.obs_properties_add_bool(props, "udp_polling_enabled", "Enable UDP Polling")

    return props


def script_defaults(settings):
    log_info_if_debug(debug, "------------------------------ script_defaults() called")

    obs.obs_data_set_default_bool(settings, "udp_polling_enabled", True)

    dvov_script_defaults(settings)

def script_update(settings):
    global udp_polling_enabled, debug, activeId, rankings_enabled
    log_info_if_debug(debug, "------------------------------ script_update() called")

    dvov_script_update(settings)

    debug = obs.obs_data_get_bool(settings, "debug")
    rankings_enabled = obs.obs_data_get_bool(settings, "rankings_enabled")

    # mostly for debugging
    new_state = obs.obs_data_get_bool(settings, "udp_polling_enabled")

    # No change? Do nothing.
    if new_state == udp_polling_enabled:
        return

    udp_polling_enabled = new_state

    if udp_polling_enabled:
        init()
        obs.script_log(obs.LOG_INFO, "UDP polling ENABLED")
    else:
        try:
            obs.timer_remove(udp_timer_callback)
        except Exception:
            pass
        obs.script_log(obs.LOG_INFO, "UDP polling DISABLED")


def script_load(settings):
    global udp_polling_enabled, udp_sock, activeId, id_, rankings_enabled, debug
    log_info_if_debug(debug, "------------------------------ script_update() called")

    dvov_script_load(settings)

    log_info_if_debug(debug, "script_load()")

    debug = obs.obs_data_get_bool(settings, "debug")
    rankings_enabled = obs.obs_data_get_bool(settings, "rankings_enabled")

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

    # Start UDP polling via obs timer
    udp_polling_enabled = obs.obs_data_get_bool(settings, "udp_polling_enabled")

    if udp_polling_enabled:
        init()
        obs.script_log(obs.LOG_INFO, "UDP polling ENABLED at script load")
    else:
        obs.script_log(obs.LOG_INFO, "UDP polling DISABLED at script load")


def script_unload():
    global udp_sock

    # cleanup
    try:
        obs.remove_current_callback()
    except Exception:
        pass
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
    obs.script_log(obs.LOG_INFO, f"Listening on UDP ports. Re-start ID: {id_}")
