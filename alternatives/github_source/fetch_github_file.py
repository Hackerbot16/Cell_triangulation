from flask import Flask, request, jsonify, render_template_string
import requests
import folium
import webbrowser 
import re 
import os 

app = Flask(__name__)
port = 80

# !!! IMPORTANT: Replace this placeholder with your actual Unwired Labs API key !!!
# This key is used globally by the query_unwiredlabs function.
UNWIRED_API_KEY = os.environ.get("UNWIRED_API_KEY", "") 

# --- CONFIGURATION FOR GITHUB DATA SOURCE ---
# This is the RAW content URL derived from your provided link.
GITHUB_RAW_URL = "https://raw.githubusercontent.com/Hackerbot16/Cell_triangulation/main/packet.txt" 
# Assuming the GitHub file contains the raw CSV packet string (e.g., $PVT,KRI1,...checksum*')

# --- HELPER FUNCTIONS (No Change) ---

def hex_to_decimal(hex_str):
    """Converts a hexadecimal string (like LAC or Cell ID) to decimal."""
    hex_str = hex_str.strip().strip('"\'')
    try:
        if re.match(r'^[0-9a-fA-F]+$', hex_str) and len(hex_str) > 3:
             return int(hex_str, 16)
        return int(hex_str)
    except ValueError as e:
        raise ValueError(f"Invalid string for hex/dec conversion: {hex_str}. Error: {e}")

def asu_to_dbm(asu):
    """Converts GSM Arbitrary Strength Unit (ASU) to dBm."""
    return 2 * asu - 113

def create_cell_towers_list(values):
    """Parses the 17-value input into a list of cell tower objects for the API."""
    if len(values) != 17:
        raise ValueError("Error: Exactly 17 values are required for main NMR data.")
    
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
    if UNWIRED_API_KEY == "pk.YOUR_ACTUAL_UNWIRED_LABS_API_KEY":
        print("\n--- Skipping Unwired Labs Query: API Key not set ---")
        return None, None, "Unwired_Labs_Placeholder"
    
    url = "https://us1.unwiredlabs.com/v2/process.php"
    cells = [{"lac": tower["locationAreaCode"], "cid": tower["cellId"], "signal": tower["signalStrength"]} for tower in cell_towers]
        
    payload = {"token": UNWIRED_API_KEY, "radio": "gsm", "mcc": mcc, "mnc": mnc, "cells": cells}
    
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
        print(f"Request failed (Network/API Error): {e}")
        return None, None, "Unwired_Labs"

def generate_map(pos, accuracy, api_name):
    """Generates an HTML Folium map and opens it automatically."""
    m = folium.Map(location=pos, zoom_start=14, tiles='OpenStreetMap')
    folium.Marker(pos, popup=f"{api_name} Est: ({pos[0]:.6f}, {pos[1]:.6f})", icon=folium.Icon(color='red', icon='star')).add_to(m)
    folium.Circle(pos, radius=accuracy, popup="Estimated Radius", color='blue', fill=False).add_to(m)
    
    filename = f'{api_name.lower()}_nmr_map.html'
    m.save(filename)
    print(f"Interactive map saved as '{filename}'.")
    
    try:
        webbrowser.open(filename)
        print(f"Automatically opening '{filename}' in the default browser.")
    except Exception as e:
        print(f"Could not automatically open web browser: {e}")

def process_packet(csv_input):
    """
    Main logic: extracts NMR data, queries API, and generates map.
    Assumes the input is the CLEANED CSV string (no start/end chars, no checksum).
    """
    print("--- Geolocator: Starting packet processing ---")
    try:
        val = [v.strip() for v in csv_input.split(',')]
        
        if len(val) < 44:
            raise ValueError(f"Packet too short. Expected at least 44 elements, got {len(val)}.")
            
        # Extract the 17 values corresponding to indices 27 through 43 (Python slice 27:44)
        values = list(val[27:44]) 
        
        cell_towers, mcc, mnc = create_cell_towers_list(values)
        
        print(f"Input: MCC={mcc}, MNC={mnc}")
        print(f"Serving Cell RSSI: {asu_to_dbm(int(values[0]))} dBm (ASU {values[0]})")
        
        pos_u, acc_u, api_u = query_unwiredlabs(cell_towers, mcc, mnc)
        
        if pos_u:
            generate_map(pos_u, acc_u, api_u)
            return True 
        else:
            print("\nProcessing finished without coordinates. Returning failure.")
            return False

    except ValueError as e:
        print(f"\nProcessing Error (Data Format): {e}")
        return False
    except Exception as e:
        print(f"\nAn UNHANDLED ERROR occurred during packet processing: {e}")
        return False


# --- FLASK SERVER ROUTE: FETCHER LOGIC ---

@app.route('/fetch_data', methods=['GET'])
def fetch_and_process_data():
    """
    Triggers fetching the packet from the specified GitHub URL,
    cleans the packet, processes it, and generates the map.
    """
    print(f"\n--- Server: Attempting to fetch packet from GitHub ---")
    
    try:
        # 1. Fetch data from GitHub
        response = requests.get(GITHUB_RAW_URL, timeout=10)
        response.raise_for_status() # Raise exception for bad status codes (4xx or 5xx)
        raw_packet = response.text.strip()

        if not raw_packet:
             return jsonify({"message": "Fetched data is empty."}), 400

        print(f"Packet Snippet (Raw): {raw_packet[:60]}...") 

        # 2. Clean the packet (Strip start/end characters and checksum)
        # Assumes format is <Start_Char>CSV_DATA,CHECKSUM<End_Char>
        if len(raw_packet) < 2:
            return jsonify({"message": "Fetched packet is too short for cleaning."}), 400

        # Remove the first and last character (Start/End Char)
        stripped_packet = raw_packet[1:-1]
        
        # Find the last comma to split the CSV data from the Checksum
        last_comma_index = stripped_packet.rfind(',')
        if last_comma_index == -1:
            csv_data = stripped_packet # No checksum, use all data
        else:
            csv_data = stripped_packet[:last_comma_index] # Data is before the last comma

        # 3. Process the cleaned CSV data
        success = process_packet(csv_data)

        if success is True:
            map_filename = 'unwired_labs_nmr_map.html'
            if os.path.exists(map_filename):
                 # Provide a status message and instructions
                 return render_template_string(
                     f"<h2>Processing Complete!</h2><p>Data fetched and geolocated successfully.</p>"
                     f"<p>Map file **'{map_filename}'** generated and automatically opened (check your browser/log).</p>"
                     f'<p>If the link doesn\'t work, open the file manually from the server directory.</p>'), 200
            else:
                 return jsonify({"message": "Data processed, but map file was not found/generated correctly."}), 500
        else:
            return jsonify({"message": "Data processed, but failed to geolocate. (Check API Key/Logs)"}), 400 

    except requests.exceptions.RequestException as e:
        return jsonify({"message": f"Failed to fetch packet from GitHub. Check URL and network connectivity. Error: {e}"}), 500
    except Exception as e:
        print(f"An unexpected error occurred during server processing: {e}")
        return jsonify({"message": f"Internal server error: {e}"}), 500

if __name__ == '__main__':
    print(f"Starting Flask server on http://0.0.0.0:{port}...")
    print(f"GitHub Raw URL set to: {GITHUB_RAW_URL}")
    print(f"Trigger processing by visiting: http://127.0.0.1:{port}/fetch_data (or use your local IP)")
    app.run(host='0.0.0.0', port=port, debug=True)