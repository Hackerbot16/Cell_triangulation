from flask import Flask, request, jsonify, send_file
import os
import sys

# Import the processing function from the core logic file
from geolocator import process_packet 

app = Flask(__name__)
# Port 80 is used as specified in the technical requirements
port = 80
MAP_FILE_PATH = 'latest_location_map.html'

@app.route('/', methods=['POST'])
def receive_data():
    """
    Handles incoming raw string POST requests from the IoT modem.
    Reads the raw request body (request.data), decodes it, and passes it 
    to the geolocator for processing and map update.
    """
    try:
        # Read the raw request body (bytes)
        raw_data = request.data

        if not raw_data:
            print("Error: Empty request body received.")
            return jsonify({"message": "Empty request body received"}), 400

        # Decode the raw bytes into the CSV packet string, robustly handling errors
        # as suggested in the specification (Section 3.2)
        csv_packet = raw_data.decode('utf-8', errors='ignore').strip()

        print(f"\n--- Server: Received raw packet ---")
        # Print the first part of the CSV string for verification
        print(f"Packet Snippet: {csv_packet[:60]}...") 
        print("---------------------------------")

        # Process the packet, which also generates/updates the map file
        success = process_packet(csv_packet, MAP_FILE_PATH)

        if success:
            return jsonify({"message": "Data received, processed, and map generated!"}), 200
        else:
            # The geolocator function will print specific errors (400 level failures)
            print("Server: Returning 400 status. Check geolocator logs for specific data integrity details.")
            return jsonify({"message": "Data received, but failed to process packet or geolocate. Check server logs."}), 400

    except Exception as e:
        # Catches unexpected server errors (500 level failures)
        print(f"An unexpected internal server error occurred: {e}", file=sys.stderr)
        return jsonify({"message": f"Internal server error: {e}"}), 500

@app.route('/map', methods=['GET'])
def get_map():
    """
    Serves the latest generated Folium map file. This endpoint is accessed by a browser 
    and automatically refreshes every 10 seconds via a meta tag for live updates.
    """
    if os.path.exists(MAP_FILE_PATH):
        print(f"Serving latest map from {MAP_FILE_PATH}")
        return send_file(MAP_FILE_PATH, mimetype='text/html')
    else:
        # Initial map placeholder if no data has been received yet
        return "<h1>Waiting for first IoT Geolocation data packet...</h1><p>Please send data to the '/' endpoint.</p>", 202

if __name__ == '__main__':
    print(f"Starting Flask server on http://0.0.0.0:{port}...")
    print(f"View the live map updates at http://127.0.0.1/map")
    # NOTE: Running on port 80 typically requires 'sudo' or administrator privileges.
    # We set debug=False for a more production-like environment (as per spec 6.1)
    app.run(host='0.0.0.0', port=port, debug=False)