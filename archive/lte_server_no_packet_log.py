from flask import Flask, request, jsonify, send_from_directory
from geolocator import process_packet, generate_live_map, HISTORY  # Import globals
import urllib.parse
import sys
import os

app = Flask(__name__)
port = 80  # Requires sudo
static_dir = "maps"

@app.route('/', defaults={'path': ''}, methods=['POST', 'GET'])
@app.route('/<path:path>', methods=['POST', 'GET'])
def receive_data(path):
    raw_data = None
    try:
        if request.method == 'POST':
            # Force raw read, skipping form parsing (key fix for urlencoded)
            raw_data = request.get_data(parse_form_data=False)
            print(f"📥 POST: Body len={len(raw_data)}, Type={request.content_type}, LenHeader={request.content_length}")
            if raw_data:
                print(f"   Hex preview: {raw_data[:50].hex()}...")
            else:
                print(f"   Form fallback check: {request.form}")  # Debug: If parsed, show what was there

        elif request.method == 'GET':
            if path:
                decoded = urllib.parse.unquote(path)
                if '%' in decoded:
                    decoded = urllib.parse.unquote(decoded)
                raw_data = decoded.encode('utf-8')
                print(f"📥 GET: Path len={len(raw_data)}")
            else:
                raw_data = request.query_string
                print(f"📥 GET: Query len={len(raw_data)}")

        if not raw_data:
            return jsonify({"error": "No data received"}), 400

        packet = raw_data.decode('utf-8', errors='ignore').strip()
        print(f"📦 Packet preview: {packet[:100]}...")

        result = process_packet(packet)
        if result:
            lat, lon, acc, addr, ts = result
            generate_live_map()  # Updates live map
            return jsonify({
                "status": "success",
                "lat": lat,
                "lon": lon,
                "accuracy_m": acc,
                "address": addr,
                "timestamp": ts,
                "history_count": len(HISTORY),
                "message": f"Updated live map! View at /live_map.html"
            }), 200
        else:
            return jsonify({"error": "Failed to process/triangulate packet"}), 400

    except Exception as e:
        print(f"💥 Server Error: {e}", file=sys.stderr)
        return jsonify({"error": f"Internal error: {str(e)}"}), 500

@app.route('/status')
def status():
    """JSON for JS polling: Latest update time."""
    latest_ts = HISTORY[-1][4] if HISTORY else None
    return jsonify({
        "updated_at": latest_ts,
        "history_count": len(HISTORY),
        "latest_lat": HISTORY[-1][0] if HISTORY else None,
        "latest_lon": HISTORY[-1][1] if HISTORY else None
    })

@app.route('/live_map.html')
def serve_live_map():
    """Serve the live map file."""
    return send_from_directory(static_dir, 'live_map.html')

if __name__ == '__main__':
    os.makedirs(static_dir, exist_ok=True)
    print(f"🚀 Starting Live LTE Triangulation Server on http://0.0.0.0:{port}")
    print("💡 Modem: Loop HTTP_Post_Data() every X seconds.")
    print("🖥️  Live View: http://your-ip:{port}/live_map.html (auto-refreshes)")
    app.run(host='0.0.0.0', port=port, debug=True)