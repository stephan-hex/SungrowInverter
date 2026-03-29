import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
import os
import time
import json
import socket
from urllib.parse import urlparse, parse_qs

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Erlaubt parallele Anfragen, damit die API den Seitenaufruf nicht blockiert."""
    daemon_threads = True

class PV_Web:
    def __init__(self, fetch_data_callback, action_callback=None, fetch_history_callback=None, port=8080):
        self.fetch_data_callback = fetch_data_callback
        self.action_callback = action_callback
        self.fetch_history_callback = fetch_history_callback
        self.port = port
        self.template_path = os.path.join(os.path.dirname(__file__), 'index.html') # Hub
        self.pv_template_path = os.path.join(os.path.dirname(__file__), 'pv.html')  # PV Details
        self.charge_template_path = os.path.join(os.path.dirname(__file__), 'charge.html')
        self.heating_template_path = os.path.join(os.path.dirname(__file__), 'heating-cooling.html')
        self.others_template_path = os.path.join(os.path.dirname(__file__), 'others.html')
        self.history_template_path = os.path.join(os.path.dirname(__file__), 'history.html')

    def start(self):
        handler_class = self._create_handler()
        ThreadedHTTPServer.allow_reuse_address = True
        server = ThreadedHTTPServer(('0.0.0.0', self.port), handler_class)
        
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
                    with open(pv_web_instance.history_template_path, 'rb') as f:
                        self.wfile.write(f.read())

                elif self.path in ['/', '/pv', '/charge.html', '/heating-cooling.html', '/others.html']:
                    self.send_response(200)
                    self.send_header('Content-type', 'text/html; charset=utf-8')
                    self.end_headers()

                    if self.path == '/pv':
                        t_path = pv_web_instance.pv_template_path
                    elif self.path == '/charge.html':
                        t_path = pv_web_instance.charge_template_path
                    elif self.path == '/heating-cooling.html':
                        t_path = pv_web_instance.heating_template_path
                    elif self.path == '/others.html':
                        t_path = pv_web_instance.others_template_path
                    else:
                        t_path = pv_web_instance.template_path

                    try:
                        with open(t_path, 'rb') as f:
                            self.wfile.write(f.read())
                    except Exception as e:
                        self.wfile.write(f"Fehler: {e}".encode('utf-8'))
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