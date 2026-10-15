from flask import Flask, request, jsonify, send_from_directory
from geolocator import process_packet, generate_live_map, HISTORY, PACKET_LOG, save_logs_on_shutdown  # Import globals and shutdown func
import urllib.parse
import sys
import os
import atexit  # For shutdown hook
import signal  # For signal handling
from datetime import datetime  # For timestamps in server

app = Flask(__name__)
port = 80  # Requires sudo
static_dir = "maps"

# Register shutdown hook
atexit.register(save_logs_on_shutdown)
signal.signal(signal.SIGTERM, lambda s, f: save_logs_on_shutdown() or sys.exit(0))
signal.signal(signal.SIGINT, lambda s, f: save_logs_on_shutdown() or sys.exit(0))

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

        # Log packet with timestamp (pinned log)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        PACKET_LOG.append((timestamp, packet))
        if len(PACKET_LOG) > 100:  # Trim old packets
            PACKET_LOG.pop(0)

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
                "packet_count": len(PACKET_LOG),
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
        "packet_count": len(PACKET_LOG),
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
    print("📝 Packets logged in memory; HTML export on shutdown (Ctrl+C).")
    try:
        app.run(host='0.0.0.0', port=port, debug=True)
    finally:
        save_logs_on_shutdown()  # Ensure save on any exit