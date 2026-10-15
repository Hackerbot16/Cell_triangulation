import os
import requests
import json
import folium
import webbrowser 

# --- Constants ---
# IMPORTANT: Replace this placeholder key with your actual Unwired Labs API Key.
UNWIRED_API_KEY = os.environ.get("UNWIRED_API_KEY", "") 

# --- Helper Functions ---

def hex_to_decimal(hex_str):
    """Converts a hexadecimal string (like LAC or Cell ID) to decimal."""
    hex_str = hex_str.strip().strip('"\'')
    try:
        if not hex_str or hex_str.lower() == '0':
            return 0
        return int(hex_str, 16)
    except ValueError:
        return 0 # Return 0 for invalid hex strings, allowing processing to continue

def asu_to_dbm(asu):
    """Converts GSM Arbitrary Strength Unit (ASU) to dBm."""
    try:
        asu = int(asu)
        if asu >= 0 and asu <= 31: # Valid GSM ASU range
            return 2 * asu - 113
        elif asu == 99: # Not detectable
            return 0  
        return 0
    except ValueError:
        return 0 

def create_cell_towers_list(values):
    """
    Parses the 17-value input slice (indices 27 to 43 from the raw packet) 
    into a list of cell tower objects for the API, handling incomplete entries.
    """
    if len(values) != 17:
        raise ValueError("Error: Exactly 17 values (indices 27 to 43) are required for main NMR data.")
    
    # Serving Cell Data (Indices 0-4 of the 'values' list)
    try:
        asu_main = values[0]
        rssi_main = asu_to_dbm(asu_main) 
        mcc = int(values[1]) 
        mnc = int(values[2]) 
        lac_main = hex_to_decimal(values[3])
        cell_main = hex_to_decimal(values[4])
    except Exception as e:
        raise ValueError(f"Failed to parse main cell data: {e}")

    cell_towers = []
    # 1. Serving Cell - Only add if CID/LAC are valid
    if cell_main > 0 and lac_main > 0:
        cell_towers.append({
            "radioType": "gsm",
            "mobileCountryCode": mcc,
            "mobileNetworkCode": mnc,
            "locationAreaCode": lac_main,
            "cellId": cell_main,
            "signalStrength": rssi_main,
            "serving": 1
        })

    # 2. Neighboring Cells (4 potential neighbors)
    # Structure: [CellID_hex, LAC_hex, RSSI]
    for i in range(4):
        idx = 5 + i * 3
        
        # Check if the remaining fields are sufficient for one neighbor (3 fields)
        if idx + 2 >= len(values):
             break 
        
        # Extract potential neighbor data
        cell_hex = values[idx].strip()
        lac_hex = values[idx + 1].strip()
        rssi_str = values[idx + 2].strip()

        # If any of the required fields are empty, skip this neighbor (e.g., ,,,, at the end of the packet)
        if not cell_hex or not lac_hex or not rssi_str:
            continue

        try:
            cell = hex_to_decimal(cell_hex)
            lac = hex_to_decimal(lac_hex)
            rssi = int(rssi_str) # Assuming RSSI is directly an integer dBm value here
        except ValueError:
            print(f"Skipping incomplete or corrupt neighbor cell data (parsing error at index {idx}).")
            continue

        # Only add neighbors if the Cell ID and LAC are valid non-zero values
        if cell > 0 and lac > 0: 
             cell_towers.append({
                 "radioType": "gsm",
                 "mobileCountryCode": mcc,
                 "mobileNetworkCode": mnc,
                 "locationAreaCode": lac,
                 "cellId": cell,
                 "signalStrength": rssi,
                 "serving": 0
             })
    
    # Ensure we have at least one valid cell to query
    if not cell_towers:
        raise ValueError("No valid cell towers (serving or neighbor) could be parsed from the packet for geolocation.")
        
    return cell_towers, mcc, mnc

def query_unwiredlabs(cell_towers, mcc, mnc):
    """Queries the Unwired Labs API."""
    if UNWIRED_API_KEY == "": 
        print("\n--- Skipping Unwired Labs Query: PLEASE UPDATE API KEY ---")
        return None, None, "Unwired_Labs_Placeholder"
    
    url = "https://us1.unwiredlabs.com/v2/process.php"
    
    # The API needs lac, cid, and signal
    cells = [
        {"lac": tower["locationAreaCode"], "cid": tower["cellId"], "signal": tower["signalStrength"]} 
        for tower in cell_towers if tower["cellId"] > 0 and tower["locationAreaCode"] > 0
    ]
        
    payload = {
        "token": UNWIRED_API_KEY,
        "radio": "gsm",
        "mcc": mcc,
        "mnc": mnc,
        "cells": cells
    }
    
    print("\n--- Querying Unwired Labs API ---")
    try:
        response = requests.post(url, json=payload, timeout=15)
        response.raise_for_status() 
        data = response.json()
        
        if data.get("status") == "ok":
            pos = [data["lat"], data["lon"]]
            accuracy = data.get("accuracy", 300) 
            print(f"API Result: ({pos[0]:.6f}, {pos[1]:.6f}), Accuracy: {accuracy}m")
            return pos, accuracy, "Unwired_Labs"
        else:
            print(f"API Error: {data.get('message', 'No location found')}. Status: {data.get('status')}")
            return None, None, "Unwired_Labs"
    except requests.exceptions.RequestException as e:
        print(f"Request failed (Network/Timeout Error): {e}")
        return None, None, "Unwired_Labs"
    except Exception as e:
        print(f"An unexpected error occurred during API query: {e}")
        return None, None, "Unwired_Labs"

def generate_map(pos, accuracy, api_name):
    """Generates an HTML Folium map and opens it automatically."""
    
    m = folium.Map(location=pos, zoom_start=14, tiles='OpenStreetMap')
    
    folium.Marker(pos, 
        popup=f"{api_name} Estimated: ({pos[0]:.6f}, {pos[1]:.6f})<br>Accuracy: {accuracy}m", 
        icon=folium.Icon(color='red', icon='star')
    ).add_to(m)
    
    folium.Circle(pos, radius=accuracy, popup="Estimated Radius", color='blue', fill=False).add_to(m)
    
    filename = f'{api_name.lower()}_nmr_map.html'
    m.save(filename)
    print(f"\nInteractive map saved as '{filename}'.")
    
    try:
        webbrowser.open(filename)
        print(f"Automatically opening '{filename}' in the default browser.")
    except Exception as e:
        print(f"Could not automatically open web browser. Please open '{filename}' manually.")


# --- Main Processing Function ---

def process_packet(csv_input):
    """
    Takes the raw CSV string, extracts the NMR data, 
    queries the API, and generates the map.
    Returns True on success, False on failure.
    """
    print("--- Geolocator: Starting packet processing ---")
    try:
        # Split the CSV string
        val = [v.strip() for v in csv_input.split(',')]
        
        # Check if the packet has enough fields.
        if len(val) < 44:
            raise ValueError(f"Packet too short for NMR data. Expected at least 44 elements, got {len(val)}.")
            
        # Extract the 17 values corresponding to indices 27 through 43 (Python slice 27:44)
        values = list(val[27:44]) 
        
        cell_towers, mcc, mnc = create_cell_towers_list(values)
        
        print(f"Input: MCC={mcc}, MNC={mnc}. Analyzing {len(cell_towers)} cell(s).")
        
        # 1. Unwired Labs Query
        pos_u, acc_u, api_u = query_unwiredlabs(cell_towers, mcc, mnc)
        
        if pos_u:
            generate_map(pos_u, acc_u, api_u)
            return True # Success
        else:
            print("\nGeolocation attempt failed to return coordinates.")
            return False # Failure

    except ValueError as e:
        print(f"\nProcessing Error (Data Format): {e}")
        return False
    except Exception as e:
        print(f"\nAn unexpected error occurred: {e}")
        return False