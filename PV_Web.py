import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import os
import time
import json
import socket
from urllib.parse import urlparse, parse_qs

class PV_Web:
    def __init__(self, fetch_data_callback, action_callback=None, fetch_history_callback=None, port=8080):
        self.fetch_data_callback = fetch_data_callback
        self.action_callback = action_callback
        self.fetch_history_callback = fetch_history_callback
        self.port = port
        self.template_path = os.path.join(os.path.dirname(__file__), 'index.html')
        self.history_template_path = os.path.join(os.path.dirname(__file__), 'history.html')

    def start(self):
        handler_class = self._create_handler()
        # Erlaubt den sofortigen Neustart des Ports
        HTTPServer.allow_reuse_address = True
        server = HTTPServer(('0.0.0.0', self.port), handler_class)
        
        # Eigene IP-Adresse im Netzwerk ermitteln (für die Anzeige)
        host_ip = "localhost"
        try:
            # Dummy-Verbindung aufbauen (sendet keine Daten), um die lokale IP zu finden
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0.1)
            s.connect(("8.8.8.8", 80))
            host_ip = s.getsockname()[0]
            s.close()
        except Exception:
            pass

        thread = threading.Thread(target=server.serve_forever)
        thread.daemon = True
        thread.start()
        print(f"Webserver läuft. Erreichbar unter:\n  Lokal:    http://localhost:{self.port}\n  Netzwerk: http://{host_ip}:{self.port}")

    def _enrich_data(self, data):
        """Fügt berechnete Felder (Flow-State, Zeitstempel) zu den Daten hinzu."""
        enriched = data.copy()
        
        # Batterie Status für Animation berechnen
        batt_power_str = data.get("battery_power", "0 W")
        flow_state = "idle"
        
        try:
            val = float(batt_power_str.split()[0])
            if val < -10:
                flow_state = "charging"
            elif val > 10:
                flow_state = "discharging"
        except (ValueError, IndexError):
            pass

        enriched['flow_state'] = flow_state
        enriched['timestamp'] = time.strftime("%H:%M:%S")
        return enriched

    def _create_handler(self):
        pv_web_instance = self
        
        class PVHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == '/api':
                    # Daten für AJAX Abfrage
                    raw_data = pv_web_instance.fetch_data_callback()
                    data = pv_web_instance._enrich_data(raw_data)
                    
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json; charset=utf-8')
                    self.end_headers()
                    self.wfile.write(json.dumps(data).encode('utf-8'))
                
                elif self.path.startswith('/api/history'):
                    # Query Parameter parsen (?date=YYYY-MM-DD&cols=a,b)
                    query_components = parse_qs(urlparse(self.path).query)
                    date_str = query_components.get('date', [None])[0]
                    cols_param = query_components.get('cols', [None])[0]
                    
                    cols = None
                    if cols_param:
                        cols = cols_param.split(',')
                    
                    data = {}
                    if pv_web_instance.fetch_history_callback:
                        data = pv_web_instance.fetch_history_callback(date_str, cols)
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json; charset=utf-8')
                    self.end_headers()
                    self.wfile.write(json.dumps(data).encode('utf-8'))
                
                elif self.path == '/history':
                    self.send_response(200)
                    self.send_header('Content-type', 'text/html; charset=utf-8')
                    self.end_headers()
                    
                    # Template laden
                    content = ""
                    try:
                        if os.path.exists(pv_web_instance.history_template_path):
                            with open(pv_web_instance.history_template_path, 'r', encoding='utf-8') as f:
                                content = f.read()
                        else:
                            content = "<h1>Fehler: history.html nicht gefunden</h1>"
                    except Exception as e:
                        content = f"<h1>Fehler beim Lesen der Datei: {e}</h1>"
                    
                    # Auch hier Platzhalter ersetzen (z.B. für Timestamp im Footer)
                    raw_data = pv_web_instance.fetch_data_callback()
                    replacements = pv_web_instance._enrich_data(raw_data)
                    for key, val in replacements.items():
                        content = content.replace(f"{{{key}}}", str(val))
                        
                    self.wfile.write(content.encode('utf-8'))

                elif self.path == '/':
                    self.send_response(200)
                    self.send_header('Content-type', 'text/html; charset=utf-8')
                    self.end_headers()
                    
                    # Aktuelle Daten holen
                    raw_data = pv_web_instance.fetch_data_callback()
                    replacements = pv_web_instance._enrich_data(raw_data)
                    
                    # Template laden
                    content = ""
                    try:
                        if os.path.exists(pv_web_instance.template_path):
                            with open(pv_web_instance.template_path, 'r', encoding='utf-8') as f:
                                content = f.read()
                        else:
                            content = "<h1>Fehler: index.html nicht gefunden</h1>"
                    except Exception as e:
                        content = f"<h1>Fehler beim Lesen der Datei: {e}</h1>"

                    # Platzhalter im HTML ersetzen
                    for key, val in replacements.items():
                        content = content.replace(f"{{{key}}}", str(val))
                    
                    self.wfile.write(content.encode('utf-8'))
                else:
                    self.send_error(404)
            
            def do_POST(self):
                if self.path == '/action':
                    content_length = int(self.headers['Content-Length'])
                    post_data = self.rfile.read(content_length)
                    
                    response_msg = "Keine Aktion definiert"
                    
                    try:
                        data = json.loads(post_data.decode('utf-8'))
                        command = data.get('command')
                        
                        if pv_web_instance.action_callback:
                            pv_web_instance.action_callback(command)
                            response_msg = f"Aktion '{command}' ausgeführt"
                        else:
                            response_msg = "Kein Callback konfiguriert"
                            
                    except Exception as e:
                        response_msg = f"Fehler: {e}"

                    self.send_response(200)
                    self.send_header('Content-type', 'text/plain')
                    self.end_headers()
                    self.wfile.write(response_msg.encode('utf-8'))
            
            def log_message(self, format, *args):
                pass # Kein Logging in der Konsole, um Output sauber zu halten
                
        return PVHandler