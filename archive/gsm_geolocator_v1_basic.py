import os
# geolocator.py
import requests
import json
import folium
import webbrowser 

# --- Constants ---
# NOTE: Using a placeholder key here. Ensure your key is valid.
UNWIRED_API_KEY = os.environ.get("UNWIRED_API_KEY", "") 

# --- Helper Functions ---

def hex_to_decimal(hex_str):
    """Converts a hexadecimal string (like LAC or Cell ID) to decimal."""
    hex_str = hex_str.strip().strip('"\'')
    try:
        return int(hex_str, 16)
    except ValueError:
        # Raise an informative error if parsing fails
        raise ValueError(f"Invalid hex string encountered: {hex_str}")

def asu_to_dbm(asu):
    """Converts GSM Arbitrary Strength Unit (ASU) to dBm."""
    return 2 * asu - 113

def create_cell_towers_list(values):
    """Parses the 17-value input into a list of cell tower objects for the API."""
    if len(values) != 17:
        raise ValueError("Error: Exactly 17 values (indices 27 to 43) are required for main NMR data.")
    
    # Serving Cell Data (Indices 0-4 of the 'values' list, corresponding to 27-31 in the raw packet)
    asu_main = int(values[0])
    rssi_main = asu_to_dbm(asu_main) 
    mcc = int(values[1]) 
    mnc = int(values[2]) 
    lac_main = hex_to_decimal(values[3])
    cell_main = hex_to_decimal(values[4])

    cell_towers = []
    # 1. Serving Cell
    cell_towers.append({
        "radioType": "gsm",
        "mobileCountryCode": mcc,
        "mobileNetworkCode": mnc,
        "locationAreaCode": lac_main,
        "cellId": cell_main,
        "signalStrength": rssi_main,
        "serving": 1
    })

    # 2. Neighboring Cells (4 neighbors, 3 values each: Cell ID, LAC, RSSI)
    for i in range(4):
        # Indices in the 'values' list: [5, 6, 7], [8, 9, 10], [11, 12, 13], [14, 15, 16]
        idx = 5 + i * 3
        cell = hex_to_decimal(values[idx])
        lac = hex_to_decimal(values[idx + 1])
        rssi = int(values[idx + 2])
        
        cell_towers.append({
            "radioType": "gsm",
            "mobileCountryCode": mcc,
            "mobileNetworkCode": mnc,
            "locationAreaCode": lac,
            "cellId": cell,
            "signalStrength": rssi,
            "serving": 0
        })
    return cell_towers, mcc, mnc

def query_unwiredlabs(cell_towers, mcc, mnc):
    """Queries the Unwired Labs API."""
    if UNWIRED_API_KEY == "UNWIRED_API_KEY": # Check if the key is still the placeholder
        print("\n--- Skipping Unwired Labs Query: Please update the UNWIRED_API_KEY ---")
        return None, None, "Unwired_Labs_Placeholder"
    
    url = "https://us1.unwiredlabs.com/v2/process.php"
    
    # Format the cell tower list for the Unwired Labs API payload
    cells = [
        {"lac": tower["locationAreaCode"], "cid": tower["cellId"], "signal": tower["signalStrength"]} 
        for tower in cell_towers
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
        response.raise_for_status() # Raises an HTTPError if the status is 4xx or 5xx
        data = response.json()
        
        if data.get("status") == "ok":
            pos = [data["lat"], data["lon"]]
            accuracy = data.get("accuracy", 300) # Default accuracy if API doesn't provide one
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
    
    # Estimated Marker
    folium.Marker(pos, 
        popup=f"{api_name} Estimated: ({pos[0]:.6f}, {pos[1]:.6f})<br>Accuracy: {accuracy}m", 
        icon=folium.Icon(color='red', icon='star')
    ).add_to(m)
    
    # Accuracy Circle
    folium.Circle(pos, radius=accuracy, popup="Estimated Radius", color='blue', fill=False).add_to(m)
    
    filename = f'{api_name.lower()}_nmr_map.html'
    m.save(filename)
    print(f"\nInteractive map saved as '{filename}'.")
    
    # Automatically open the map file
    try:
        webbrowser.open(filename)
        print(f"Automatically opening '{filename}' in the default browser.")
    except Exception as e:
        print(f"Could not automatically open web browser: {e}")


# --- Main Processing Function ---

def process_packet(csv_input):
    """
    Takes the raw CSV string, extracts the NMR data, 
    queries the API, and generates the map.
    Returns True on success, False on failure.
    """
    print("--- Geolocator: Starting packet processing ---")
    try:
        # Input CSV string for main device's NMR (main + 4 neighbors)
        val = [v.strip() for v in csv_input.split(',')]
        
        # Check if the packet has at least 44 elements (indices 0 to 43)
        if len(val) < 44:
            raise ValueError(f"Packet too short. Expected at least 44 elements, got {len(val)}.")
            
        # Extract the 17 values corresponding to indices 27 through 43 (Python slice 27:44)
        values = list(val[27:44]) 
        
        cell_towers, mcc, mnc = create_cell_towers_list(values)
        
        # Print summary of input data
        print(f"Input: MCC={mcc}, MNC={mnc}")
        print(f"Serving Cell RSSI: {asu_to_dbm(int(values[0]))} dBm (ASU {values[0]})")
        
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