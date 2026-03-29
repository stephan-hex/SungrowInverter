from pymodbus.client import ModbusTcpClient
import json
import os
from PV_Web import PV_Web
from PV_Database import PV_Database
from PV_Logger import PV_Logger
import time
import threading
import signal
import datetime
from fritz_control import FritzControl

# Metadaten
APP_NAME = "Sungrow Inverter Monitor (Headless)"
VERSION = "1.1.1"

# Konfiguration
# Ersetzen Sie dies durch die tatsächliche IP-Adresse Ihres Wechselrichters oder WiNet-S Dongles
INVERTER_IP = '192.168.178.154' 
INVERTER_PORT = 502
SLAVE_ID = 1  # Standard Unit ID ist meistens 1
WEBSERVER_ON = True
DB_UPDATE_INTERVAL = 60 # Sekunden (Schreiben in die DB)
POLL_INTERVAL = 5 # Sekunden (Abfrageintervall, ersetzt den UI-Refresh)
LOGGING_ENABLED = True

# Debug-Einstellungen
DEBUG_FRITZ = True

CONFIG_FILE = os.path.join(os.path.dirname(__file__), 'main_config.json')
CHARGE_MODE = "NORMAL-CHARGING" # Default: Normal (Links), Intelligent (Rechts)

# --- Fritz!Box Integration für Web-Zentrale ---
try:
    _fritz_cfg_path = os.path.join(os.path.dirname(__file__), "fritz_config.json")
    with open(_fritz_cfg_path, "r", encoding="utf-8") as f:
        FRITZ_CFG = json.load(f)
    fritz_controller = FritzControl(FRITZ_CFG)
except:
    FRITZ_CFG = None
    fritz_controller = None

# Globaler Cache für Fritzbox-Zustände (wird vom Hintergrund-Thread befüllt)
fritz_data_cache = {'fritz_zisterne': 'inval', 'fritz_brunnen': 'inval', 'fritz_reserve': 'inval'}

# Register global laden
REGISTERS = {}
try:
    with open(os.path.join(os.path.dirname(__file__), 'registers.json'), 'r') as f:
        REGISTERS = json.load(f)
except Exception as e:
    print(f"Fehler beim Laden der registers.json: {e}")

# Logger initialisieren (oder einen Dummy, wenn deaktiviert)
if LOGGING_ENABLED:
    logger = PV_Logger()
else:
    class DummyLogger:
        def log_error(self, message):
            pass
    logger = DummyLogger()

# Datenbank initialisieren
pv_db = PV_Database(registers_dict=REGISTERS)

def load_config():
    """Lädt die Konfiguration (Lade-Modus) beim Start"""
    global CHARGE_MODE
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                data = json.load(f)
                val = data.get("charge_mode", "NORMAL-CHARGING")
                # Migration alter Werte
                if val == "Normal": val = "NORMAL-CHARGING"
                if val == "Surplus": val = "INTELLIGENT-CHARGING"
                CHARGE_MODE = val
    except Exception as e:
        print(f"Fehler beim Laden der Konfiguration: {e}")

def save_config():
    """Speichert den aktuellen Lade-Modus"""
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump({"charge_mode": CHARGE_MODE}, f)
    except Exception as e:
        print(f"Fehler beim Speichern der Konfiguration: {e}")

def read_raw_modbus_data():
    """Liest alle Register aus und gibt ein Dictionary mit Rohwerten (Zahlen) zurück"""
    client = ModbusTcpClient(INVERTER_IP, port=INVERTER_PORT)
    data_output = {}

    if client.connect():
        try:
            for name, data in REGISTERS.items():
                addr = data['address']
                dtype = data['type']
                factor = data['factor']
                
                # 32-Bit Werte benötigen 2 Register, sonst 1
                count = 2 if '32' in dtype else 1
                
                rr = None
                # Retry-Logik: Bis zu 3 Versuche pro Register, falls Verbindung abbricht (Broken Pipe)
                for attempt in range(3):
                    try:
                        # Robuste Methode für alle pymodbus Versionen
                        try:
                            rr = client.read_input_registers(address=addr, count=count, device_id=SLAVE_ID)
                        except TypeError:
                            try:
                                rr = client.read_input_registers(address=addr, count=count, slave=SLAVE_ID)
                            except TypeError:
                                rr = client.read_input_registers(address=addr, count=count, unit=SLAVE_ID)
                        
                        if not rr.isError():
                            break # Erfolgreich gelesen
                    except Exception as e:
                        # Bei Fehler (z.B. Broken Pipe) kurz warten und Reconnect
                        logger.log_error(f"Lese-Versuch {attempt+1} fehlgeschlagen für {name}: {e}")
                        time.sleep(0.5)
                        client.close()
                        time.sleep(0.5)
                        client.connect()
                
                # Kurze Pause, um den Wechselrichter/Dongle nicht zu überlasten (verhindert Connection Reset)
                time.sleep(0.05)
                
                if rr and not rr.isError():
                    regs = rr.registers
                    val = 0
                    
                    if dtype == 'uint16be':
                        val = regs[0]
                    elif dtype == 'int16be':
                        val = regs[0]
                        if val > 0x7FFF:  # Vorzeichenbehandlung für 16-Bit
                            val -= 0x10000
                    elif dtype == 'uint32sw':
                        # sw = Swapped Words. Sungrow nutzt oft (Low Word, High Word)
                        val = (regs[1] << 16) | regs[0]
                    elif dtype == 'int32sw':
                        val = (regs[1] << 16) | regs[0]
                        if val > 0x7FFFFFFF:
                            val -= 0x100000000
                    elif dtype == 'int8be':
                        val = regs[0] & 0xFF
                        if val > 0x7F:
                            val -= 0x100

                    final_val = val * factor
                    
                    # Rohwert speichern (für DB oder Weiterverarbeitung)
                    data_output[name] = final_val
                else:
                    data_output[name] = None # None ist besser für DB als "Error" String
        except Exception as e:
            msg = f"Fehler beim Lesen der Register: {e}"
            print(msg)
            logger.log_error(msg)
        finally:
            client.close()
    else:
        msg = "Keine Verbindung zum Wechselrichter möglich"
        print(msg)
        logger.log_error(msg)
    
    return data_output

def format_data_for_ui(raw_data):
    """Formatiert die Rohdaten für die Anzeige (Strings mit Einheiten)"""
    formatted = {}
    for name, val in raw_data.items():
        if val is None:
            formatted[name] = "Error"
            continue
            
        unit = REGISTERS.get(name, {}).get('unit', '')
        
        # Spezielle Umrechnung und Formatierung für Gesamtertrag in MWh
        if name == 'total_pv_generation':
            mwh_val = val / 1000
            formatted[name] = f"{mwh_val:.2f} MWh"
        elif isinstance(val, float):
            formatted[name] = f"{val:.2f} {unit}"
        else:
            formatted[name] = f"{val} {unit}"
    return formatted

# Cache der zuletzt gepollteten Daten für den Webserver
last_data_cache = {}

def read_modbus_data_callback():
    """Wrapper für Poll-Loop: Holt Rohdaten, aktualisiert DB-Puffer und Cache."""
    global last_data_cache
    raw = read_raw_modbus_data()
    
    # Daten für die Datenbank vorbereiten (sammeln)
    # Zeitstempel als EPOCH
    current_time = time.time()
    pv_db.prepare_data(raw, current_time)
    
    last_data_cache = format_data_for_ui(raw)
    
    # Lade-Modus zur API hinzufügen
    last_data_cache['charge_mode'] = CHARGE_MODE
    # Hilfsfeld für das Template, um die Checkbox beim Laden korrekt zu setzen
    last_data_cache['charge_mode_checked'] = "checked" if CHARGE_MODE == "INTELLIGENT-CHARGING" else ""
    
    # Fritz-Zustände aus dem Hintergrund-Cache in den Haupt-Cache mergen
    last_data_cache.update(fritz_data_cache)
    
    return last_data_cache

def fritz_poll_loop():
    """Hintergrund-Thread für das FritzBox-Polling (entlastet die Hauptschleife)"""
    print("[FritzThread] Hintergrund-Polling gestartet.")
    while running:
        if fritz_controller and FRITZ_CFG:
            s1 = fritz_controller.get_state(FRITZ_CFG['fritz_ain_zisterne'])
            s2 = fritz_controller.get_state(FRITZ_CFG['fritz_ain_brunnen'])
            s3 = fritz_controller.get_state(FRITZ_CFG['fritz_ain_reserve'])
            
            fritz_data_cache['fritz_zisterne'] = s1
            fritz_data_cache['fritz_brunnen'] = s2
            fritz_data_cache['fritz_reserve'] = s3
            
            if DEBUG_FRITZ:
                print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Fritz-Status (BG): Zisterne={s1}, Brunnen={s2}, Reserve={s3}")
        
        # Die FritzBox braucht nicht jede Sekunde gefragt werden, 10s ist ein guter Kompromiss
        stop_event.wait(timeout=10)

def get_cached_data():
    """Gibt den zuletzt gepollteten Datensatz zurück (kein Modbus-Zugriff)."""
    if last_data_cache:
        return last_data_cache
    return read_modbus_data_callback()

def db_persist_loop():
    """Hintergrund-Loop, der alle DB_UPDATE_INTERVAL Sekunden die Daten speichert"""
    while True:
        time.sleep(DB_UPDATE_INTERVAL)
        pv_db.persist_data()

# Globales Flag und Event für den sauberen Shutdown
running = True
stop_event = threading.Event()

def handle_sigterm(signum, frame):
    global running
    print(f"Signal {signum} empfangen (System-Shutdown/Reboot). Beende Schleife...")
    running = False
    stop_event.set()  # Poll-Loop sofort aufwecken

def handle_web_action(command):
    """Callback für Buttons auf der Webseite"""
    print(f"Web-Action empfangen: {command}")
    global CHARGE_MODE
    
    if command == "mode_normal":
        CHARGE_MODE = "NORMAL-CHARGING"
        save_config()
    elif command == "mode_surplus":
        CHARGE_MODE = "INTELLIGENT-CHARGING"
        save_config()
    
    # Beispiel für Fritz!Box Befehle (AIN aus fritz_config.json oder direkt)
    elif command.startswith("fritz_"):
        # Format: fritz_LOGISCHERNAME_on oder fritz_LOGISCHERNAME_off
        parts = command.split("_")
        if len(parts) == 3:
            device_key, state = parts[1], parts[2]
            if FRITZ_CFG and fritz_controller:
                # Mapping: 'zistern' -> 'fritz_ain_zisterne'
                cfg_key = f"fritz_ain_{device_key}"
                ain = FRITZ_CFG.get(cfg_key)
                if ain:
                    if fritz_controller:
                        success = fritz_controller.switch(ain, state == "on")
                        if success:
                            # Sofort den Cache aktualisieren, damit das UI nicht zurückspringt
                            fritz_data_cache[f"fritz_{device_key}"] = "1" if state == "on" else "0"

def get_history_data(date_str=None, cols=None):
    """Callback für Chart-Daten"""
    target_date = None
    if date_str:
        try:
            target_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            pass
    return pv_db.get_today_values(cols, target_date)

def main():
    print(f"Starte {APP_NAME} Version: {VERSION}")
    print(f"Datenbank-Aufzeichnung aktiv (Intervall: {DB_UPDATE_INTERVAL}s)")
    
    # Konfiguration laden
    load_config()
    
    # Signal-Handler früh registrieren, bevor Threads gestartet werden
    signal.signal(signal.SIGTERM, handle_sigterm)
    
    if WEBSERVER_ON:
        # Webserver bekommt den Cache-Callback – kein direkter Modbus-Zugriff
        # Und jetzt auch den Action-Callback für die Buttons
        web = PV_Web(fetch_data_callback=get_cached_data, action_callback=handle_web_action, fetch_history_callback=get_history_data)
        web.start()
    
    # Datenbank-Thread starten (Daemon, damit er beim Beenden des Programms mit stirbt)
    db_thread = threading.Thread(target=db_persist_loop, daemon=True)
    db_thread.start()
    
    # Fritz-Polling-Thread starten
    fritz_thread = threading.Thread(target=fritz_poll_loop, daemon=True)
    fritz_thread.start()
    
    print(f"Programm läuft. Daten werden alle {POLL_INTERVAL}s abgerufen. Drücke STRG+C zum Beenden.")
    
    try:
        while running:
            # Regelmäßiges Abfragen der Daten (ersetzt den UI-Loop)
            # Der Aufruf füllt den Puffer der Datenbankklasse
            read_modbus_data_callback()
            stop_event.wait(timeout=POLL_INTERVAL)  # unterbrechbarer Sleep
            stop_event.clear()
            
    except KeyboardInterrupt:
        print("\nManueller Abbruch (STRG+C)...")
    finally:
        # Dieser Block wird IMMER ausgeführt (bei Fehler, STRG+C oder SIGTERM)
        print("Führe Cleanup durch...")
        pv_db.persist_data() # Letzte Daten aus dem Puffer speichern
        pv_db.close()
        print("Datenbank geschlossen. Bye.")

if __name__ == "__main__":
    main()