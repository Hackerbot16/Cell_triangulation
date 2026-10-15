from flask import Flask, request, jsonify
from geolocator import process_packet # Import the function from geolocator.py

app = Flask(__name__)
port = 80


# --- ROBUST ROUTING CONFIGURATION ---
# 1. Matches the base URL ('/') and sets path='' (for testing base URL).
# 2. Matches any path that follows, capturing it in the 'path' variable (for modem packets).
@app.route('/', defaults={'path': ''}, methods=['POST', 'GET'])
@app.route('/<path:path>', methods=['POST', 'GET'])
def receive_data(path):
    """
    Handles incoming data packets. 
    It checks for POST data in the body or GET data in the captured path variable.
    """
    raw_data = None
    
    try:
        if request.method == 'POST':
            # 1. POST: Read from the raw request body (standard method)
            raw_data = request.data
            print("Server: Processing as POST request (Body Data)")

        elif request.method == 'GET':
            # 2. GET: Use the path argument captured by the robust route definition
            if path:
                # The 'path' argument already contains the data string (e.g., "$PVT,KRI1,...")
                raw_data = path.encode('utf-8')
                print("Server: Processing as GET request (Path Data)")
            else:
                 # Fallback check for query string if path is empty (e.g., GET /?data=...)
                 raw_data = request.query_string
                 print("Server: Processing as GET request (Query String Fallback)")


        if not raw_data:
            print("Error: Empty request data received.")
            return jsonify({"message": "Empty request data received"}), 400

        # Decode the raw bytes into the CSV packet string
        csv_packet = raw_data.decode('utf-8').strip()
        
        # NOTE: Dev Tunnels might escape '%' in 'IND%20airtel' to '%2520'.
        # We perform basic URL decoding to normalize common characters like spaces.
        import urllib.parse
        csv_packet = urllib.parse.unquote(csv_packet)


        print(f"\n--- Server: Successfully Captured Packet ---")
        print(f"Source Method: {request.method}")
        print(f"Packet Snippet: {csv_packet[:60]}...") 
        print("------------------------------------------")
        
        # Process the packet using the imported function (in geolocator.py)
        success = process_packet(csv_packet)

        if success:
            return jsonify({"message": "Data received and processed successfully!"}), 200
        else:
            print("Server: Failed to process valid packet structure. Check geolocator logs for details.")
            return jsonify({"message": "Data received, but failed to process packet or geolocate."}), 400

    except Exception as e:
        print(f"An unexpected error occurred during server processing: {e}")
        return jsonify({"message": f"Internal server error: {e}"}), 500

if __name__ == '__main__':
    print(f"Starting Flask server on http://0.0.0.0:{port}...")
    # NOTE: Running on port 80 requires 'sudo' or administrator privileges on most systems.
    app.run(host='0.0.0.0', port=port, debug=True)