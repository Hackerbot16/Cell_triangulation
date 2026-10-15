import requests
import json
import folium
import webbrowser
import os
from datetime import datetime  # For timestamps
import re  # For hex pattern matching
import time  # For delay check

# --- Constants ---
UNWIRED_API_KEY = os.environ.get("UNWIRED_API_KEY", "")  # Update if needed
MCC_FALLBACK = 404  # India
MNC_FALLBACK = 40   # Airtel
TAC_FALLBACK_HEX = "B044"
SERVER_PORT = 80  # Hardcoded for auto-open URL

# --- Global History (In-Memory: List of (lat, lon, acc, addr, timestamp)) ---
HISTORY = []  # Appended on each success; server clears on restart
HISTORY_LIMIT = 10  # Keep last N points

# --- Helper Functions ---

def is_hex_field(field):
    """Check if field looks like a hex string (alphanumeric, 4-8 chars, uppercase)."""
    if not field or not re.match(r'^[0-9A-F]{4,8}$', field.strip().upper()):
        return False
    return True

def is_numeric_field(field, expected_digits=None):
    """Check if field is numeric; optional digit count."""
    if not field:
        return False
    try:
        num = int(field.strip())
        if expected_digits and len(str(num)) != expected_digits:
            return False
        return True
    except ValueError:
        return False

def hex_to_decimal(hex_str):
    """Converts a hexadecimal string (like TAC or eNB ID) to decimal."""
    hex_str = hex_str.strip().strip('"\'')
    if not hex_str:
        return 0
    try:
        return int(hex_str, 16)
    except ValueError:
        raise ValueError(f"Invalid hex string encountered: {hex_str}")

def asu_to_dbm(asu):
    """Converts LTE/GSM Arbitrary Strength Unit (ASU) to dBm (RSRP approx)."""
    return 2 * asu - 113

def create_cell_towers_list(cell_fields, rssi_main):
    """Dynamically parses cell fields: MCC, MNC, TAC_s, eNB_s + optional neighbors (eNB_n, TAC_n, RSRP_n)."""
    cell_towers = []
    i = 0
    num_fields = len(cell_fields)
    
    # Parse serving cell
    # Skip empties until MCC (3-digit numeric)
    while i < num_fields and not is_numeric_field(cell_fields[i], 3):
        i += 1
    if i < num_fields:
        mcc = int(cell_fields[i])
        i += 1
    else:
        print(f"Warning: No MCC found, using fallback {MCC_FALLBACK}")
        mcc = MCC_FALLBACK
    
    # MNC (2-digit numeric)
    while i < num_fields and not is_numeric_field(cell_fields[i], 2):
        i += 1
    if i < num_fields:
        mnc = int(cell_fields[i])
        i += 1
    else:
        print(f"Warning: No MNC found, using fallback {MNC_FALLBACK}")
        mnc = MNC_FALLBACK
    
    # TAC_s (hex)
    tac_main = 0
    while i < num_fields and not is_hex_field(cell_fields[i]):
        i += 1
    if i < num_fields:
        tac_main = hex_to_decimal(cell_fields[i])
        i += 1
    else:
        print(f"Warning: No serving TAC found, using fallback {TAC_FALLBACK_HEX}")
        tac_main = hex_to_decimal(TAC_FALLBACK_HEX)
    
    # eNB_s (hex)
    while i < num_fields and not is_hex_field(cell_fields[i]):
        i += 1
    if i < num_fields:
        enb_main = hex_to_decimal(cell_fields[i])
        i += 1
    else:
        print("Warning: No serving eNB found, using 0")
        enb_main = 0
    
    # Add serving cell
    cell_towers.append({
        "radioType": "lte",
        "mobileCountryCode": mcc,
        "mobileNetworkCode": mnc,
        "locationAreaCode": tac_main,  # TAC
        "cellId": enb_main,  # eNB ID
        "signalStrength": rssi_main,  # From ASU
        "serving": 1
    })
    
    # Parse up to 4 neighbors: eNB (hex), TAC (hex), RSRP (signed int)
    neighbors_added = 0
    while i + 2 < num_fields and neighbors_added < 4:
        # eNB_n (hex)
        while i < num_fields and not is_hex_field(cell_fields[i]):
            i += 1
        if i >= num_fields:
            break
        enb = hex_to_decimal(cell_fields[i])
        i += 1
        
        # TAC_n (hex)
        while i < num_fields and not is_hex_field(cell_fields[i]):
            i += 1
        if i >= num_fields:
            break
        tac = hex_to_decimal(cell_fields[i])
        i += 1
        
        # RSRP_n (signed int, like -63)
        while i < num_fields:
            try:
                rsrp = int(cell_fields[i])
                break
            except ValueError:
                i += 1
        else:
            rsrp = -80  # Fallback
            i += 1
        
        cell_towers.append({
            "radioType": "lte",
            "mobileCountryCode": mcc,
            "mobileNetworkCode": mnc,
            "locationAreaCode": tac,
            "cellId": enb,
            "signalStrength": rsrp,
            "serving": 0
        })
        neighbors_added += 1
        print(f"Added neighbor {neighbors_added}: eNB={enb}, TAC={tac}, RSRP={rsrp} dBm")
    
    print(f"Parsed Towers: Serving eNB={enb_main} (TAC={tac_main}, {rssi_main} dBm); {neighbors_added} neighbors")
    return cell_towers, mcc, mnc

def query_unwiredlabs(cell_towers, mcc, mnc):
    """Queries the Unwired Labs API for LTE cell triangulation."""
    if UNWIRED_API_KEY == "UNWIRED_API_KEY":
        print("\n--- Skipping Unwired Labs Query: Update UNWIRED_API_KEY with a valid token ---")
        return None, None, None
    
    url = "https://us1.unwiredlabs.com/v2/process.php"
    
    # Format cells for API (lac=TAC, cid=eNB, signal=dBm)
    cells = [
        {"lac": tower["locationAreaCode"], "cid": tower["cellId"], "signal": tower["signalStrength"]} 
        for tower in cell_towers if tower["cellId"] > 0  # Skip invalid
    ]
    
    if not cells:
        print("No valid cells to query.")
        return None, None, None
        
    payload = {
        "token": UNWIRED_API_KEY,
        "radio": "lte",
        "mcc": mcc,
        "mnc": mnc,
        "cells": cells,
        "address": 1
    }
    
    print("\n--- Querying Unwired Labs API (LTE) ---")
    print(f"Payload summary: {len(cells)} towers (MCC={mcc}, MNC={mnc})")
    try:
        response = requests.post(url, json=payload, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        if data.get("status") == "ok":
            pos = [data["lat"], data["lon"]]
            accuracy = data.get("accuracy", 500)  # Higher default for fewer towers
            address = data.get("address", "Unknown")
            print(f"API Success: ({pos[0]:.6f}, {pos[1]:.6f}), Accuracy: {accuracy}m, Address: {address}")
            return pos, accuracy, address
        else:
            print(f"API Error: {data.get('message', 'No location found')}. Status: {data.get('status')}")
            return None, None, None
    except requests.exceptions.RequestException as e:
        print(f"Request failed (Network/Timeout): {e}")
        return None, None, None
    except Exception as e:
        print(f"Unexpected API error: {e}")
        return None, None, None

def generate_live_map(history=HISTORY, output_dir="maps"):
    """Generates/updates a single live Folium map with history trail; auto-opens on every update using HTTP URL."""
    os.makedirs(output_dir, exist_ok=True)
    
    if not history:
        print("No history to map.")
        return
    
    # Center on latest point
    latest = history[-1]
    pos_latest = [latest[0], latest[1]]  # lat, lon
    m = folium.Map(location=pos_latest, zoom_start=15, tiles='OpenStreetMap')
    
    # Add historical markers (faded for older) + line trail
    colors = ['gray', 'lightblue', 'blue', 'darkblue']  # Cycle for recency
    points = []
    for i, (lat, lon, acc, addr, ts) in enumerate(history):
        color = colors[min(i % len(colors), len(colors)-1)]
        opacity = 0.4 + 0.6 * (i / max(len(history)-1, 1))  # Fade older less aggressively
        points.append([lat, lon])
        
        folium.Marker(
            [lat, lon],
            popup=f"#{len(history)-i} ({ts})<br>Lat/Lon: ({lat:.6f}, {lon:.6f})<br>Acc: {acc}m<br>{addr}",
            icon=folium.Icon(color=color, icon='info-sign')
        ).add_to(m)
        
        # Accuracy circle
        folium.Circle([lat, lon], radius=acc, color=color, fill=True, fillOpacity=0.1, popup=f"±{acc}m").add_to(m)
    
    # Trail line (connect points)
    if len(points) > 1:
        folium.PolyLine(points, color='red', weight=2.5, opacity=0.8, popup="Movement Trail").add_to(m)
    
    # Highlight latest
    folium.Marker(
        pos_latest,
        popup=f"LATEST ({latest[4]})<br>Lat/Lon: ({pos_latest[0]:.6f}, {pos_latest[1]:.6f})<br>Acc: {latest[2]}m<br>{latest[3]}",
        icon=folium.Icon(color='red', icon='star'),
        tooltip="Live Position"
    ).add_to(m)
    
    filename = f"{output_dir}/live_map.html"
    m.save(filename)
    
    # Embed auto-refresh JS (poll /status every 30s, reload if new)
    try:
        with open(filename, 'r') as f:
            html = f.read()
        js_refresh = '''
        <script>
        function checkUpdate() {
            fetch('/status').then(r => r.json()).then(data => {
                if (data.updated_at && new Date(data.updated_at) > new Date(localStorage.getItem('last_update') || 0)) {
                    localStorage.setItem('last_update', data.updated_at);
                    location.reload();
                }
            }).catch(() => {});  // Silent fail
        }
        setInterval(checkUpdate, 30000);  // 30s poll
        checkUpdate();  // Initial
        </script>
        '''
        html = html.replace('</body>', js_refresh + '</body>')
        with open(filename, 'w') as f:
            f.write(html)
    except Exception as e:
        print(f"Warning: Could not embed JS in map: {e}")
    
    print(f"🗺️  Live map updated: {filename} (History: {len(history)} points)")
    
    # Auto-open HTTP URL on EVERY update (will open new tab if closed; browsers may block popups—keep tab open if possible)
    try:
        map_url = f'http://127.0.0.1:{SERVER_PORT}/live_map.html'
        opened = webbrowser.open(map_url, new=2)  # new=2: force new tab
        if opened:
            print(f"🖥️  Auto-opened live map in new tab: {map_url}")
        else:
            print(f"⚠️  webbrowser.open returned False (browser issue?); Manually visit {map_url}")
    except Exception as e:
        print(f"Could not open browser: {e}. Manually visit http://127.0.0.1:{SERVER_PORT}/live_map.html")

# --- Main Processing Function ---
def process_packet(csv_input):
    """
    Processes the raw NMEA/CSV packet: Dynamically extracts LTE cell data after 'IND airtel' and '0', queries API, returns (lat, lon, acc, addr, ts).
    """
    print("--- Geolocator: Processing LTE Packet ---")
    try:
        val = [v.strip() for v in csv_input.split(',') if v.strip() or True]  # Keep empties as ''
        if len(val) < 20:  # Minimal check
            raise ValueError(f"Packet too short: {len(val)} fields.")
        
        print(f"Total fields: {len(val)}")  # Debug
        
        # Find operator index ('IND airtel')
        try:
            op_index = val.index('IND airtel')
        except ValueError:
            raise ValueError("No operator field 'IND airtel' found.")
        
        print(f"Operator at index {op_index}")
        
        # ASU at op_index + 3 (field 25 in full)
        asu_str = val[op_index + 3] if op_index + 3 < len(val) else '0'
        try:
            asu = int(float(asu_str))
            rssi_main = asu_to_dbm(asu)
        except ValueError:
            print(f"Warning: Invalid ASU '{asu_str}', using -70 dBm")
            rssi_main = -70
        
        print(f"📡 Serving ASU={asu} (~{rssi_main} dBm)")
        
        # Cell fields start after '0' (op_index + 5)
        zero_index = op_index + 5
        if zero_index < len(val) and val[zero_index] != '0':
            print("Warning: Expected '0' at index {}, found '{}'".format(zero_index, val[zero_index]))
        cell_fields = val[zero_index + 1 :]  # From field 28+
        print(f"Cell fields ({len(cell_fields)}): {cell_fields[:10]}{'...' if len(cell_fields)>10 else ''}")  # Debug first 10
        
        cell_towers, mcc, mnc = create_cell_towers_list(cell_fields, rssi_main)
        
        print(f"📡 Parsed: MCC={mcc} (India), MNC={mnc} (Airtel)")
        print(f"📡 Towers: {len(cell_towers)} (1 serving + {len(cell_towers)-1} neighbors)")
        
        # Query API
        pos, acc, addr = query_unwiredlabs(cell_towers, mcc, mnc)
        
        if pos:
            timestamp = datetime.now().strftime("%H:%M:%S")
            new_entry = (pos[0], pos[1], acc, addr, timestamp)
            HISTORY.append(new_entry)
            if len(HISTORY) > HISTORY_LIMIT:
                HISTORY.pop(0)  # Trim old
            print(f"✅ Added to history: {pos[0]:.6f}°N, {pos[1]:.6f}°E ±{acc}m ({timestamp})")
            return new_entry
        else:
            print("❌ Triangulation failed (check API key/network).")
            return None

    except ValueError as e:
        print(f"❌ Parse Error: {e}")
        return None
    except Exception as e:
        print(f"❌ Unexpected Error: {e}")
        return None