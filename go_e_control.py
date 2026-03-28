import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import urllib.request
import urllib.error

# --- Konfiguration ---
#PV_API_URL      = "http://localhost:8080/api"
PV_API_URL      = "http://192.168.178.58:8080/api"
API_PORT        = 8081               # Port für die eigene API dieses Skripts

GOE_IP          = "192.168.178.142"  # <-- HIER BITTE DIE IP DES CHARGERS EINTRAGEN

SOC_START       = 80.0      # Ladevorgang STARTEN / 3-Phasen Modus
SOC_1PHASE      = 75.0      # Umschalten auf 1-phasig bei Unterschreitung
SOC_STOP        = 70.0      # Ladevorgang STOPPEN (Hysterese)
MAX_1P_AMP      = 12        # Maximaler Strom bei 1-phasiger Ladung
CHARGING_AMPS   = 6         # Ladestrom in Ampere (Konstant)
CHECK_INTERVAL  = 60        # Alle 60 Sekunden prüfen

# Globaler Speicher für den aktuellen Status (Thread-safe genug für diesen Zweck)
current_status_data = {
    "timestamp": "",
    "goe_connected": False,
    "car_status": "Unknown",
    "charged_energy_kwh": 0,
    "action": "idle",
    "wh": 0,
    "alw": 0,
    "pnp": 0,
    "pv_soc": 0,
    "pv_dc_power": 0,
    "charge_mode": "",
    "current_amps": CHARGING_AMPS
}

class StatusAPIHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/api/status':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(current_status_data).encode('utf-8'))
        else:
            self.send_error(404)
    
    def log_message(self, format, *args):
        pass # Kein Konsolen-Log für Requests

def start_api_server():
    server = HTTPServer(('0.0.0.0', API_PORT), StatusAPIHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"API Server läuft auf Port {API_PORT} (Endpunkt: /api/status)")

def get_pv_data():
    """Holt SOC, DC Power und Charge Mode von der lokalen PV-API."""
    try:
        with urllib.request.urlopen(PV_API_URL, timeout=5) as url:
            data = json.loads(url.read().decode())
            
            # SOC extrahieren
            soc_str = data.get("battery_soc", "0")
            soc_val = float(str(soc_str).split()[0])
            
            # DC Power extrahieren (z.B. "1234.56 W")
            power_str = data.get("total_dc_power", "0")
            power_val = float(str(power_str).split()[0])
            
            # Lademodus extrahieren
            charge_mode = data.get("charge_mode", "NORMAL-CHARGING")
            
            return {
                "soc": soc_val,
                "dc_power": power_val,
                "charge_mode": charge_mode
            }
    except Exception as e:
        print(f"WARNUNG: Fehler beim Abrufen der PV-Daten: {e}")
        return None

def get_goe_status():
    """Holt den aktuellen Status vom Go-eCharger."""
    try:
        # Filtert die API auf die relevanten Felder inkl. psm (Phase Switch Mode)
        url = f"http://{GOE_IP}/api/status?filter=car,wh,alw,eto,pnp,psm"
        with urllib.request.urlopen(url, timeout=5) as response:
            return json.loads(response.read().decode())
    except Exception as e:
        print(f"FEHLER beim Abrufen des Go-e Status: {e}")
        return None

def translate_car_status(status_code):
    """Übersetzt den 'car' Statuscode in einen lesbaren Text."""
    status_map = {
        "0": "Unknown/Error",
        "1": "Idle",
        "2": "Charging",
        "3": "WaitCar",
        "4": "Complete",
        "5": "Error"
    }
    return status_map.get(str(status_code), f"Unbekannt ({status_code})")

def set_goe_charging(enable, amps=6):
    """Sendet den Steuerbefehl an den Go-eCharger."""
    try:
        # API V2: /api/set?frc=X&amp=Y
        # frc=1 -> Nicht laden erzwingen
        # frc=2 -> Laden erzwingen
        frc_val = "2" if enable else "1"
        url = f"http://{GOE_IP}/api/set?frc={frc_val}"
        if enable:
            url += f"&amp={amps}"
        
        print(f" -> Sende an Go-e (V2): frc={frc_val}, amp={amps if enable else '-'}")
        with urllib.request.urlopen(url, timeout=5) as resp:
            resp.read()

        print("    Erfolgreich gesendet.")
        return True
            
    except Exception as e:
        print(f"FEHLER beim Steuern des Go-e Chargers: {e}")
        return False

def set_goe_phases(phases):
    """Stellt die Anzahl der Phasen ein (psm: 1=1-phasig, 2=3-phasig)."""
    try:
        url = f"http://{GOE_IP}/api/set?psm={phases}"
        print(f" -> Sende an Go-e (Phasen): psm={phases}")
        with urllib.request.urlopen(url, timeout=5) as resp:
            resp.read()
        print(f"    Phasenumschaltung auf {phases} erfolgreich.")
        return True
    except Exception as e:
        print(f"FEHLER beim Einstellen der Phasen: {e}")
        return False

def main():
    print("--- Go-e Charger PV-Control gestartet ---")
    print(f"PV API:  {PV_API_URL}")
    print(f"Go-e IP: {GOE_IP}")
    print(f"Go-e API: http://localhost:{API_PORT}/api/status")
    print(f"Regel:   Start > {SOC_START}% | Stop < {SOC_STOP}%")
    print(f"Strom:   {CHARGING_AMPS} A")
    print("-------------------------------------------")
    start_api_server()

    last_pv_soc = None
    last_charge_mode = None
    active_amps = CHARGING_AMPS

    while True:
        pv_data = get_pv_data()
        goe_status = get_goe_status()
        timestamp = time.strftime("%H:%M:%S")
        
        current_status_data["timestamp"] = timestamp
        current_status_data["goe_connected"] = (goe_status is not None)

        if pv_data:
            soc = pv_data["soc"]
            charge_mode = pv_data["charge_mode"]
            current_status_data["pv_soc"] = soc
            current_status_data["pv_dc_power"] = pv_data["dc_power"]
            current_status_data["charge_mode"] = charge_mode
            
            if goe_status:
                car_status_code = goe_status.get('car')
                car_status_text = translate_car_status(car_status_code)
                
                # Basierend auf translate_car_status sind 1, 2 und 4 "gesteckt"
                is_plugged = str(car_status_code) in ["1", "2", "4"]
                is_charging = str(car_status_code) == "2"
                current_psm = goe_status.get('psm')
                
                charged_energy_kwh = goe_status.get('eto', 0) / 10.0
                current_status_data["car_status"] = car_status_text
                current_status_data["charged_energy_kwh"] = charged_energy_kwh
                current_status_data["wh"] = goe_status.get('wh', 0)
                current_status_data["alw"] = goe_status.get('alw', 0)
                current_status_data["pnp"] = goe_status.get('pnp', 0)
                
                status_info = f"SOC: {soc:.1f}%, Mode: {charge_mode}, Car: {car_status_text}, Phasen: {current_psm}, Amp: {active_amps}A"
                
                # Ausgabe des aktuellen Status bei jedem Intervall
                print(f"[{timestamp}] {status_info}")
                
                # Ladestrategie nur bei INTELLIGENT-CHARGING
                if charge_mode == "INTELLIGENT-CHARGING":
                    # Reset bei Wechsel von Normal zu Intelligent
                    if last_charge_mode == "NORMAL-CHARGING":
                        print(f"[{timestamp}] Modus-Wechsel erkannt: NORMAL -> INTELLIGENT")
                        print(f"    -> Setze Basis-Ladestrom: {CHARGING_AMPS}A")
                        active_amps = CHARGING_AMPS
                        # Falls das Fahrzeug bereits lädt, passen wir den Strom sofort an
                        if is_charging:
                            set_goe_charging(True, active_amps)

                    if is_plugged:
                        if soc >= SOC_START:
                            if not is_charging:
                                print(f"    -> AKTION: START (SOC >= {SOC_START}%) - Initial 3-Phasig")
                                set_goe_phases(2)
                                active_amps = CHARGING_AMPS
                                set_goe_charging(True, active_amps)
                                current_status_data["action"] = "charging_start"
                            else:
                                # Wenn bereits geladen wird und SOC_START erreicht ist -> Sicherstellen 3-phasig
                                if current_psm == 1:
                                    print(f"    -> AKTION: WECHSEL auf 3-Phasig (SOC >= {SOC_START}%)")
                                    set_goe_phases(2)
                                    active_amps = CHARGING_AMPS
                                    set_goe_charging(True, active_amps)
                                current_status_data["action"] = "charging_active"

                        elif soc < SOC_STOP:
                            if is_charging:
                                print(f"    -> AKTION: STOP (SOC < {SOC_STOP}%) - Reset auf 3-Phasig")
                                set_goe_charging(False)
                                set_goe_phases(2)
                                active_amps = CHARGING_AMPS
                                current_status_data["action"] = "charging_stop"
                            else:
                                current_status_data["action"] = "idle_low_soc"

                        elif is_charging:
                            # Hysteresebereich zwischen SOC_STOP und SOC_START
                            if soc < SOC_1PHASE:
                                if current_psm != 1:
                                    print(f"    -> AKTION: WECHSEL auf 1-Phasig (SOC < {SOC_1PHASE}%)")
                                    set_goe_phases(1)
                                    active_amps = CHARGING_AMPS
                                    set_goe_charging(True, active_amps)
                                    current_status_data["action"] = "charging_active_1p"
                                
                                # Stromstärke erhöhen, wenn SOC ansteigt
                                elif last_pv_soc is not None and soc > last_pv_soc:
                                    if active_amps < MAX_1P_AMP:
                                        active_amps = min(active_amps + 2, MAX_1P_AMP)
                                        print(f"    -> AKTION: SOC steigt ({last_pv_soc:.1f}% -> {soc:.1f}%). Erhöhe Strom auf {active_amps}A")
                                        set_goe_charging(True, active_amps)
                                        current_status_data["action"] = "charging_active_1p_boost"
                                    else:
                                        current_status_data["action"] = "charging_active_1p_max"
                                else:
                                    current_status_data["action"] = "charging_active_1p_stable"
                            else:
                                current_status_data["action"] = "hysteresis_charging"

                        else:
                            current_status_data["action"] = "hysteresis_wait"
                    else:
                        print("    -> Status: Kein Fahrzeug gesteckt")
                        current_status_data["action"] = "no_car_connected"
                else:
                    # NORMAL-CHARGING: Normalerweise keine Befehle, außer beim Modus-Wechsel (Reset)
                    if last_charge_mode == "INTELLIGENT-CHARGING":
                        print(f"[{timestamp}] Modus-Wechsel erkannt: INTELLIGENT -> NORMAL")
                        print("    -> Führe Reset durch: 3 Phasen, 16 Ampere")
                        set_goe_phases(2)
                        active_amps = 16
                        set_goe_charging(True, active_amps)
                        current_status_data["action"] = "manual_mode_reset_done"
                    else:
                        current_status_data["action"] = "manual_mode_no_action"
                    
                    print("    -> Status: Passiv (Manueller Modus)")
            
            # Merken des aktuellen SOC für den nächsten Vergleich
            last_pv_soc = soc
            last_charge_mode = charge_mode
            current_status_data["current_amps"] = active_amps

        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()