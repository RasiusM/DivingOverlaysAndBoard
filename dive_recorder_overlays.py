'''
Dive Recorder OBS Overlays Script
'''
# Converted from divingoverlaysV4.0.0.lua (Andy)


#TODO: Test with multiple synchro judge numbers
#TODO: Simultaneous events implementation
#TODO: Support for reveal in rankings overlays


import typing

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
from overlay_data import dvov_act_set_data
from state_controls import dvov_state_settings, dvov_state_on_message, dvov_status_register_hotkeys_force, dvov_state_script_update

from rankings import rankings_set_divers, rankings_set_debug
from rankings import on_rankings_hotkey_stop, rankings_add_properties, rankings_register_hotkeys, rankings_update_settings

# ---------- Globals
portClient = 58091  # main port for DR broadcast data
tcp_port = 58291  # DiveRecorder listening TCP port

last_message_text = ""
udp_polling_enabled = True

# settings (populated via script_update)
flagLoc = ""
dinterval = 5000
debug = False

# internal state
activeId = 0
id_ = 0

# flag to indicate if rankings retrieval and update is enabled (script setting)
rankings_enabled = False

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

# ---- global variable to hold parsed structure ----
referee_message: Union[DiveMessage, None] = None
ranking_records: List[DiveListRecord] = []
rankings_event_record: DiveMessage

# need to ensure thread-safe access to rankings_records
ranking_records_lock: threading.Lock = threading.Lock()

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
            if debug:
                obs.script_log(obs.LOG_INFO, f"Parsed Record: {record}")

        except Exception:
            # If any conversion fails, skip this chunk safely
            exception_count += 1
            if exception_count <= 5:
                obs.script_log(obs.LOG_WARNING, f"Failed to parse ranking record chunk: {chunk}")
                continue
            else:
                obs.script_log(obs.LOG_WARNING, "Multiple parsing errors encountered; further errors will be suppressed.")
                break

    if debug:
        obs.script_log(obs.LOG_INFO, f"Finished parsing UPDATE message, total records: {len(records)}")

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
    Connects to DiveRecorder TCP port, requests the given remote file, 
    and saves it to local disk.
    
    ip_address: str - IP from UDP message
    message_file_name: str - file path received in UDP message (e.g., Update.txt)
    """

    with ranking_records_lock:
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

            if debug:
                obs.script_log(obs.LOG_INFO, f"Initiating TCP connection to {ip_address}:{tcp_port} for file {message_file_name}")

            with socket.create_connection((HOST, PORT)) as s:
                request_text = f"XFER|{message_file_name}\n"
                s.sendall(request_text.encode('utf-8'))

                s.settimeout(tcp_receive_timeout)

                # Step 1: read the 4-byte header
                header = recv_exact(s, 4)

                # interpret length of payload (adjust endianness as needed)
                payload_len = int.from_bytes(header, 'big')  # or 'little'
                print(f"Payload length: {payload_len}")

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
            if debug:    
                obs.script_log(obs.LOG_INFO, f"Message File Contents:\n{message_file_contents}")

            rankings_records, rankings_event_record = parse_update_message(message_file_contents)

            rankings_set_divers(rankings_records, rankings_event_record)

            return True

        except Exception as e:
            obs.script_log(obs.LOG_ERROR, f"Failed to fetch update file from {ip_address}:{tcp_port} - {e}")
            return False
    
# ---------- Process incoming UDP messages ----------
def process_udp_message(k: str):
    global synchro, eventB, overlays_enabled
    global resultK, file_contents_changed
    global referee_message, simultaneous_events, debug, rankings_enabled

    if debug:
        obs.script_log(obs.LOG_INFO, "process_udp_message()")

    if not k:
        return

    # Split message
    parts = k.split("|")
    if parts and parts[-1].endswith("\r"):
        parts[-1] = parts[-1][:-1]
    resultK = parts

    # --- parse into dataclass ---
    if (parts[0] == "REFEREE"):
        referee_message = parse_dive_message(parts)

        dvov_state_on_message(referee_message)
    
        if debug:
            obs.script_log(obs.LOG_INFO,
                        f'UDP message: "{parts[0] if parts else ""}" '
                        f'received, fields: {len(parts)}')

        # ---- 
        # if simultaneous_events:
        #     if len(resultK) > 0 and referee_message == "REFEREE":
        #         synchro = referee_message.synchro_event == "True"
        #         eventB = referee_message.event_ab == "b"
        #         if overlays_enabled:
        #             simultaneous_update(resultK)
        # else:
        #     # How this happens??????? Event B selected in DR, but not actually simultaneous?
        #     if eventB:
        #         if len(resultK) > 1 and referee_message.packet_id == "REFEREE" and referee_message.event_ab == "b":
        #             synchro = False
        #             if overlays_enabled:
        #                 single_update(referee_message)
        #     else:
        #         if len(resultK) > 1 and referee_message.packet_id == "REFEREE" and referee_message.event_ab == "a":
        #             synchro = referee_message.synchro_event == "True"
        #             if overlays_enabled:
        #                 single_update(referee_message)
    elif parts[0] == "UPDATE" and rankings_enabled:
        referee_message = None
        if debug:
            obs.script_log(obs.LOG_INFO, f"UPDATE packet received: {parts}")

        if rankings_enabled:
            # Example: UPDATE|a|DIVING_CONTUPER|1|192.168.1.1|C:\ProgramData\MDT\DiveRecorder\Xfer\Update.txt|^
            if len(parts) >= 6:
                ip_addr = parts[4]
                    
                dive_recorder_message_filename = os.path.basename(parts[5])  # just the filename, e.g.
                if dive_recorder_message_filename == "Update.txt":
                    fetch_update_file_async(ip_addr, dive_recorder_message_filename)
                else:
                    obs.script_log(obs.LOG_WARNING, f"Received unrecognized remote file reference: {dive_recorder_message_filename}")


#---------- UDP polling (called on OBS timer) ----------
def udp_timer_callback():
    global id_, activeId, udp_sock, last_message_text

    # If script reloaded, stop old timer
    if id_ < activeId:
        try:
            obs.remove_current_callback()
        except Exception:
            pass
        return

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

                    if debug:
                        obs.script_log(obs.LOG_INFO, f"UDP Message Text: {text}")

                    process_udp_message(text)
                #else:
                    #file_contents_changed = False
    except Exception as e:
        obs.script_log(obs.LOG_ERROR, f"UDP polling error: {e}")

# ---------- simultaneous_update ----------
def simultaneous_update(v):
    global tv_banner_removed, event_complete, sim_event_a_pos_left, dinterval

    # if debug:
    #     obs.script_log(obs.LOG_INFO, f"start simultaneous_update(), Message Header: {v[0] if len(v)>0 else ''}")

    # if event_complete and tv_banner_removed and not file_contents_changed:
    #     return

    # dvov_act_sim_event_referee_update (v,  (not eventB and sim_event_a_pos_left), synchro, debug)

    # # schedule hide timer for simultaneous too
    # obs.timer_add(lambda: tv_banner_remove_callback(), dinterval)


# ---------- OBS script lifecycle ----------
def script_description():
    return "<center><h2>Display DiveRecorder Data as a Video Overlay or Overlays</h2></center><p>Display diver and scores from DiveRecorder for single individual or synchro diving event or simultaneous individual events. The appropriate OBS Source (.json) file must be imported into OBS for this overlay to function correctly. You must be connected to the same Class C sub-net as the DR computers.</p><p>Converted from divingoverlaysV4.0.0.lua</p>"

def script_properties():
    props = obs.obs_properties_create()

    obs.obs_properties_add_path(props, "flagLoc", "Path to flags folder", obs.OBS_PATH_DIRECTORY, "", None)
    obs.obs_properties_add_int(props, "dinterval", "TVOverlay display period (ms)", 4000, 15000, 2000)
    obs.obs_properties_add_bool(props, "debug", "Show debug data in Log file")
    obs.obs_properties_add_bool(props, "udp_polling_enabled", "Enable UDP Polling")
    obs.obs_properties_add_bool(props, "rankings_enabled", "Rankings Enabled")

    rankings_add_properties(props)

    return props


def script_defaults(settings):
    obs.obs_data_set_default_string(settings, "flagLoc", "C:/Users/<your UserID>/Documents/OBS/flags")
    obs.obs_data_set_default_int(settings, "dinterval", 5000)
    obs.obs_data_set_default_bool(settings, "debug", False)
    obs.obs_data_set_default_bool(settings, "rankings_enabled", False) 
    

def script_update(settings):
    global udp_polling_enabled, flagLoc, dinterval, debug, activeId, rankings_enabled

    flagLoc = obs.obs_data_get_string(settings, "flagLoc")
    dinterval = obs.obs_data_get_int(settings, "dinterval")
    debug = obs.obs_data_get_bool(settings, "debug")
    rankings_enabled = obs.obs_data_get_bool(settings, "rankings_enabled")

    # load persisted state values from settings
    dvov_state_script_update()

    # obs.script_log(obs.LOG_INFO, "OBS defaults updated by script_update()")
    # obs.script_log(obs.LOG_INFO, f"simultaneous_events: {simultaneous_events}")
    # obs.script_log(obs.LOG_INFO, f"Synchro selected: {synchro}")
    # obs.script_log(obs.LOG_INFO, f"B Event selected: {eventB}")
    # obs.script_log(obs.LOG_INFO, f"Event Complete: {event_complete}")
    # obs.script_log(obs.LOG_INFO, f"Enable Updates: {overlays_enabled}")
    # obs.script_log(obs.LOG_INFO, f"File Contents Changed: {file_contents_changed}")
    # obs.script_log(obs.LOG_INFO, f"TVBanner removed: {tv_banner_removed}")
    # obs.script_log(obs.LOG_INFO, f"Rankings Enabled: {rankings_enabled}")

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
    
    rankings_update_settings(settings)

script_settings = None

def script_load(settings):
    global udp_polling_enabled, udp_sock, activeId, id_

    global script_settings
    script_settings = settings

    dvov_status_register_hotkeys_force()
    rankings_register_hotkeys(settings)

    rankings_set_debug(debug)
    dvov_state_settings(dinterval, settings, debug)

    dvov_act_set_data(flagLoc, debug)

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

    # Really needed here?
    #remove_tv_banner()


def script_unload():
    global udp_sock
    
    on_rankings_hotkey_stop(True)

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
    if debug:
        obs.script_log(obs.LOG_INFO, "init()")
    activeId += 1
    id_ = activeId
    obs.timer_add(udp_timer_callback, 200)
    obs.script_log(obs.LOG_INFO, f"Listening on UDP ports. Re-start ID: {id_}")
    # Really needed here?
    #remove_tv_banner()