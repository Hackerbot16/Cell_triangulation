import os
from flask import Flask, request, jsonify
import requests
import folium
import webbrowser 

app = Flask(__name__)
# The IoT device uses port 80 (standard HTTP port)
port = 80

# !!! IMPORTANT: Replace this placeholder with your actual Unwired Labs API key !!!
# This key is used globally by the query_unwiredlabs function.
UNWIRED_API_KEY = os.environ.get("UNWIRED_API_KEY", "") 

# --- HELPER FUNCTIONS ---

def hex_to_decimal(hex_str):
    """Converts a hexadecimal string (like LAC or Cell ID) to decimal."""
    hex_str = hex_str.strip().strip('"\'')
    try:
        return int(hex_str, 16)
    except ValueError:
        # Raises an error if conversion fails
        raise ValueError(f"Invalid hex string encountered: {hex_str}")

def asu_to_dbm(asu):
    """Converts GSM Arbitrary Strength Unit (ASU) to dBm."""
    return 2 * asu - 113

def create_cell_towers_list(values):
    """
    Parses the 17-value input into a list of cell tower objects for the API.
    Handles ASU to dBm conversion for the serving cell, and uses raw dBm for neighbors.
    """
    if len(values) != 17:
        raise ValueError("Error: Exactly 17 values (indices 27 to 43) are required for main NMR data.")
    
    # --- Serving Cell Data ---
    asu_main = int(values[0])
    rssi_main = asu_to_dbm(asu_main) # ASU to dBm conversion for main cell
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

    # 2. Neighboring Cells (4 neighbors)
    for i in range(4):
        # Indices in the 'values' list: [5, 6, 7], [8, 9, 10], [11, 12, 13], [14, 15, 16]
        idx = 5 + i * 3
        cell = hex_to_decimal(values[idx])
        lac = hex_to_decimal(values[idx + 1])
        # RSSI is provided directly in dBm (e.g., -64)
        rssi = int(values[idx + 2]) 
        
        # Fallback check: If the RSSI value looks like an ASU, convert it.
        if rssi > 0 and rssi < 32:
             print(f"Warning: Neighbor RSSI ({rssi}) looks like ASU. Converting to dBm.")
             rssi = asu_to_dbm(rssi)

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
    """Queries the Unwired Labs API using the global key."""
    
    # Check if the API key is the placeholder
    if UNWIRED_API_KEY == "pk.YOUR_ACTUAL_UNWIRED_LABS_API_KEY":
        print("\n--- Skipping Unwired Labs Query: API Key not set ---")
        return None, None, "Unwired_Labs_Placeholder"
    
    url = "https://us1.unwiredlabs.com/v2/process.php"
    
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
        response.raise_for_status() # Raises HTTPError for 4xx/5xx status
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
    Returns True on success, False on failure.
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
        
        # 1. Unwired Labs Query
        pos_u, acc_u, api_u = query_unwiredlabs(cell_towers, mcc, mnc)
        
        if pos_u:
            # Success: Coordinates obtained, generate map
            generate_map(pos_u, acc_u, api_u)
            return True 
        else:
            # Failure: API skipped or failed to return coords
            print("\nProcessing finished without coordinates. Returning failure.")
            return False

    except ValueError as e:
        print(f"\nProcessing Error (Data Format): {e}")
        return False
    except Exception as e:
        print(f"\nAn UNHANDLED ERROR occurred during packet processing: {e}")
        return False


# --- FLASK SERVER ROUTE ---

@app.route('/data', methods=['POST'])
def receive_data():
    """
    Handles incoming HTTP POST requests from the IoT device at /data.
    """
    if not request.is_json:
        return jsonify({"message": "Missing or invalid JSON in request"}), 400

    try:
        data_packet_json = request.get_json()
        csv_packet = data_packet_json.get('packet_data') 
        
        if not csv_packet or not isinstance(csv_packet, str):
            return jsonify({"message": "Invalid payload format. Expected {'packet_data': '...'}"}), 400

        print(f"\n--- Server: Received raw packet ---")
        print(f"Packet Snippet: {csv_packet[:60]}...") 
        print("---------------------------------")
        
        # Use the integrated process_packet function
        success = process_packet(csv_packet)

        if success is True:
            # 200 OK
            return jsonify({"message": "Data received, processed, and map generated!"}), 200
        else:
            # 400 Bad Request/Logical Failure
            print("Server: Returning 400 status. Check geolocator logs for details.")
            return jsonify({"message": "Data processed, but failed to geolocate. (Check API Key/Logs)"}), 400 

    except Exception as e:
        # 500 Internal Server Error
        print(f"An unexpected error occurred during server processing: {e}")
        return jsonify({"message": f"Internal server error: {e}"}), 500

if __name__ == '__main__':
    print(f"Starting Flask server on http://0.0.0.0:{port}...")
    app.run(host='0.0.0.0', port=port, debug=True)