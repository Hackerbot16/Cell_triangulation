# app.py
from flask import Flask, request, jsonify
from geolocator import process_packet  # Import the function from the new file

app = Flask(__name__)
port = 5000

@app.route('/data', methods=['POST'])
def receive_data():
    """Handles incoming HTTP POST requests from the IoT device."""
    
    # 1. Check for valid JSON content type
    if not request.is_json:
        print("Error: Request must be JSON.")
        return jsonify({"message": "Missing or invalid JSON in request"}), 400

    try:
        data_packet_json = request.get_json()
        
        # 2. Extract the packet string from the expected key
        # The IoT device should send JSON like: { "packet_data": "26,404,40,B044,..." }
        csv_packet = data_packet_json.get('packet_data') 
        
        if not csv_packet or not isinstance(csv_packet, str):
            print("Error: 'packet_data' key not found or is not a string in the payload.")
            return jsonify({"message": "Invalid payload format. Expected {'packet_data': '...'}"}), 400

        print(f"\n--- Server: Received raw packet ---")
        # Print the first part of the CSV string for verification
        print(f"Packet Snippet: {csv_packet[:60]}...") 
        print("---------------------------------")
        
        # 3. Process the packet using the imported function
        success = process_packet(csv_packet)

        if success:
            return jsonify({"message": "Data received, processed, and map generated!"}), 200
        else:
            # The geolocator function will print specific errors
            return jsonify({"message": "Data received, but failed to process packet or geolocate. Check server logs."}), 500

    except Exception as e:
        print(f"An unexpected error occurred during server processing: {e}")
        return jsonify({"message": f"Internal server error: {e}"}), 500

if __name__ == '__main__':
    print(f"Starting Flask server on http://0.0.0.0:{port}...")
    # Use host='0.0.0.0' to allow external connections (from the IoT device)
    app.run(host='0.0.0.0', port=port, debug=True)