import requests
import folium
import webbrowser 
import time
import os
import base64
import json
import io # Used for reading string content like a file

# --- CONFIGURATION ---

# !!! IMPORTANT: Replace this with your actual Unwired Labs API key !!!
UNWIRED_API_KEY = os.environ.get("UNWIRED_API_KEY", "") 

# --- GITHUB CONFIG ---
GITHUB_USERNAME = "Hackerbot16" 
REPOSITORY_NAME = "Cell_triangulation" 
# --- TARGET FILE NAME ---
# The single file that will contain the continuously appended packets (CSV lines)
TARGET_FILE_NAME = "packets.txt"
PACKET_FILE_PATH = TARGET_FILE_NAME 
# Note: PACKET_FOLDER_PATH is implicitly "" (root) because TARGET_FILE_NAME is in the root.

# GitHub PAT provided by the user (CAUTION: hardcoding PATs is insecure)
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

# Local file to track the number of lines/packets processed in the TARGET_FILE_NAME
STATE_FILE = 'last_processed_line_count.json'

# Polling interval in seconds (how often the script checks GitHub)
POLLING_INTERVAL = 10 

# --- HELPER FUNCTIONS (No change to core logic) ---
def hex_to_decimal(hex_str):
    """Converts a hexadecimal string (like LAC or Cell ID) to decimal."""
    hex_str = hex_str.strip().strip('"\'')
    try:
        return int(hex_str, 16)
    except ValueError:
        raise ValueError(f"Invalid hex string encountered: {hex_str}")

def asu_to_dbm(asu):
    """Converts GSM Arbitrary Strength Unit (ASU) to dBm."""
    return 2 * asu - 113

# ... (create_cell_towers_list, query_unwiredlabs, generate_map, process_packet remain unchanged)

def create_cell_towers_list(values):
    """
    Parses the 17-value input into a list of cell tower objects for the API.
    """
    if len(values) != 17:
        raise ValueError("Error: Exactly 17 values (indices 27 to 43) are required for main NMR data.")
    
    # --- Serving Cell Data ---
    asu_main = int(values[0])
    rssi_main = asu_to_dbm(asu_main)
    mcc = int(values[1]) 
    mnc = int(values[2]) 
    lac_main = hex_to_decimal(values[3])
    cell_main = hex_to_decimal(values[4])

    cell_towers = []
    cell_towers.append({
        "radioType": "gsm", "mobileCountryCode": mcc, "mobileNetworkCode": mnc,
        "locationAreaCode": lac_main, "cellId": cell_main, 
        "signalStrength": rssi_main, "serving": 1
    })

    # 2. Neighboring Cells (4 neighbors)
    for i in range(4):
        idx = 5 + i * 3
        cell = hex_to_decimal(values[idx])
        lac = hex_to_decimal(values[idx + 1])
        rssi = int(values[idx + 2]) 
        
        if rssi > 0 and rssi < 32:
             print(f"Warning: Neighbor RSSI ({rssi}) looks like ASU. Converting to dBm.")
             rssi = asu_to_dbm(rssi)

        cell_towers.append({
            "radioType": "gsm", "mobileCountryCode": mcc, "mobileNetworkCode": mnc,
            "locationAreaCode": lac, "cellId": cell, 
            "signalStrength": rssi, "serving": 0
        })
    return cell_towers, mcc, mnc

def query_unwiredlabs(cell_towers, mcc, mnc):
    """Queries the Unwired Labs API using the global key."""
    if UNWIRED_API_KEY == "":
        pass 
    
    url = "https://us1.unwiredlabs.com/v2/process.php"
    
    cells = [
        {"lac": tower["locationAreaCode"], "cid": tower["cellId"], "signal": tower["signalStrength"]} 
        for tower in cell_towers
    ]
        
    payload = {
        "token": UNWIRED_API_KEY,
        "radio": "gsm", "mcc": mcc, "mnc": mnc, "cells": cells
    }
    
    try:
        response = requests.post(url, json=payload, timeout=15)
        response.raise_for_status() 
        data = response.json()
        
        if data.get("status") == "ok":
            pos = [data["lat"], data["lon"]]
            accuracy = data.get("accuracy", 300) 
            return pos, accuracy, "Unwired_Labs"
        else:
            print(f"API Error: {data.get('message', 'No location found')}. Status: {data.get('status')}")
            return None, None, "Unwired_Labs"
    except requests.exceptions.RequestException as e:
        print(f"Request failed (Network/API Error): {e}")
        return None, None, "Unwired_Labs"

def generate_map(pos, accuracy, api_name, packet_id):
    """Generates and updates a single, persistent HTML Folium map."""
    
    filename = 'latest_nmr_map.html' 
    
    # Create or replace the map centered on the new location
    m = folium.Map(location=pos, zoom_start=14, tiles='OpenStreetMap')
    
    # packet_id here will be the line number
    folium.Marker(
        pos, 
        popup=f"**Packet Line {packet_id}**<br>{api_name} Est: ({pos[0]:.6f}, {pos[1]:.6f})", 
        icon=folium.Icon(color='red', icon='star')
    ).add_to(m)
    
    folium.Circle(
        pos, 
        radius=accuracy, 
        popup=f"Estimated Radius: {accuracy}m", 
        color='blue', 
        fill=False
    ).add_to(m)
    
    m.save(filename)
    print(f"Interactive map updated as '{filename}'.")
    
    if not hasattr(generate_map, 'opened_browser'):
        try:
            webbrowser.open(filename, new=2) 
            generate_map.opened_browser = True
            print("Automatically opened map in browser. Refresh the tab for updates.")
        except Exception:
            pass 

def process_packet(csv_input, packet_filename):
    """
    Main logic: extracts NMR data, queries API, and generates map.
    Returns True on success, False on failure.
    """
    # ... (function body remains unchanged)
    print(f"\n--- Geolocator: Processing packet {packet_filename} ---")
    try:
        val = [v.strip() for v in csv_input.split(',')]
        
        if len(val) < 44:
            raise ValueError(f"Packet too short. Expected at least 44 elements, got {len(val)}.")
            
        # Extract the 17 values corresponding to indices 27 through 43
        values = list(val[27:44]) 
        
        cell_towers, mcc, mnc = create_cell_towers_list(values)
        
        # 1. Unwired Labs Query
        pos_u, acc_u, api_u = query_unwiredlabs(cell_towers, mcc, mnc)
        
        if pos_u:
            # Success: Coordinates obtained, generate map
            generate_map(pos_u, acc_u, api_u, packet_filename)
            return True 
        else:
            print("Processing finished without coordinates.")
            return False

    except ValueError as e:
        print(f"Processing Error (Data Format): {e}")
        return False
    except Exception as e:
        print(f"An UNHANDLED ERROR occurred during packet processing: {e}")
        return False
    
# --- NEW STATE MANAGEMENT FUNCTIONS ---

def get_last_processed_line_count():
    """Reads the last known line count from the state file."""
    if not os.path.exists(STATE_FILE):
        return 0
    try:
        with open(STATE_FILE, 'r') as f:
            state = json.load(f)
            return state.get('line_count', 0)
    except Exception:
        return 0

def save_last_processed_line_count(count):
    """Saves the current line count to the state file."""
    with open(STATE_FILE, 'w') as f:
        json.dump({'line_count': count}, f)

# --- UPDATED GITHUB POLLING LOGIC ---

def poll_github_for_packets():
    """
    Checks the single target file on GitHub, processes new lines, and updates state.
    """
    if not GITHUB_TOKEN:
        print("ERROR: GITHUB_TOKEN not set. Cannot poll repository.")
        return
        
    last_processed_count = get_last_processed_line_count()
    
    # Construct the GitHub API URL for the single file's raw content
    raw_url = f"https://raw.githubusercontent.com/{GITHUB_USERNAME}/{REPOSITORY_NAME}/main/{PACKET_FILE_PATH}"
    
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
    }

    try:
        print(f"\nChecking GitHub file '{TARGET_FILE_NAME}'...")
        
        # Fetch the entire raw content of the file
        file_response = requests.get(raw_url, headers=headers, timeout=30)
        file_response.raise_for_status()
        
        # Content is the entire text file (all packets)
        all_packets_text = file_response.text
        
        # Use io.StringIO to treat the string content as a file object
        file_stream = io.StringIO(all_packets_text)
        
        new_packets_count = 0
        current_line_count = 0
        
        for line_number, line in enumerate(file_stream, 1):
            current_line_count = line_number
            csv_packet = line.strip()
            
            # Process only lines that are NEW (line_number > last_processed_count)
            if line_number > last_processed_count and csv_packet:
                
                print(f"--- Found New Packet (Line {line_number}) ---")
                
                # Process the packet and update the map
                if process_packet(csv_packet, line_number):
                    print(f"Successfully processed and mapped: Line {line_number}")
                else:
                    print(f"Failed to geolocate: Line {line_number}")
                
                new_packets_count += 1
        
        if new_packets_count == 0:
            print("No new packets found in the file.")
            return

        # Update the state file with the total number of lines processed
        save_last_processed_line_count(current_line_count)
        print(f"Processed {new_packets_count} new packet(s). Total lines processed: {current_line_count}")

    except requests.exceptions.RequestException as e:
        print(f"GitHub/Network Request Failed: {e}")
    except Exception as e:
        print(f"An unexpected error occurred during file processing: {e}")

# --- MAIN LOOP ---

if __name__ == '__main__':
    print("--- Starting GitHub Single-File Polling Geolocator ---")
    print(f"Monitoring file: {GITHUB_USERNAME}/{REPOSITORY_NAME}/{PACKET_FILE_PATH}")
    print(f"Polling interval: {POLLING_INTERVAL} seconds")
    
    while True:
        poll_github_for_packets()
        
        # Wait before checking again
        print(f"\n--- Waiting for {POLLING_INTERVAL} seconds... ---")
        time.sleep(POLLING_INTERVAL)