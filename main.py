from pymodbus.client import ModbusTcpClient
import json
import os
from PV_UI import PV_UI
from PV_Web import PV_Web
from PV_Database import PV_Database
import time
import threading

# Konfiguration
# Ersetzen Sie dies durch die tatsächliche IP-Adresse Ihres Wechselrichters oder WiNet-S Dongles
INVERTER_IP = '192.168.178.154' 
INVERTER_PORT = 502
SLAVE_ID = 1  # Standard Unit ID ist meistens 1
WEBSERVER_ON = True
DB_UPDATE_INTERVAL = 60 # Sekunden

# Register global laden
REGISTERS = {}
try:
    with open(os.path.join(os.path.dirname(__file__), 'registers.json'), 'r') as f:
        REGISTERS = json.load(f)
except Exception as e:
    print(f"Fehler beim Laden der registers.json: {e}")

# Datenbank initialisieren
pv_db = PV_Database(registers_dict=REGISTERS)

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
                unit = data['unit']
                
                # 32-Bit Werte benötigen 2 Register, sonst 1
                count = 2 if '32' in dtype else 1
                
                rr = client.read_input_registers(address=addr, count=count, slave=SLAVE_ID)
                
                if not rr.isError():
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
            print(f"Fehler beim Lesen: {e}")
        finally:
            client.close()
    else:
        print("Keine Verbindung zum Wechselrichter")
    
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

def read_modbus_data_callback():
    """Wrapper für UI/Web: Holt Rohdaten und formatiert sie."""
    raw = read_raw_modbus_data()
    
    # Daten für die Datenbank vorbereiten (sammeln)
    # Zeitstempel als EPOCH
    current_time = time.time()
    pv_db.prepare_data(raw, current_time)
    
    return format_data_for_ui(raw)

def db_persist_loop():
    """Hintergrund-Loop, der alle DB_UPDATE_INTERVAL Sekunden die Daten speichert"""
    while True:
        time.sleep(DB_UPDATE_INTERVAL)
        pv_db.persist_data()

def main():
    print("Starte UI...")
    print(f"Datenbank-Aufzeichnung aktiv (Intervall: {DB_UPDATE_INTERVAL}s)")
    
    if WEBSERVER_ON:
        web = PV_Web(fetch_data_callback=read_modbus_data_callback)
        web.start()
        
    # UI initialisieren und die Lesefunktion übergeben
    app = PV_UI(fetch_data_callback=read_modbus_data_callback, update_interval=5000)
    
    # Datenbank-Thread starten (Daemon, damit er beim Beenden des Programms mit stirbt)
    db_thread = threading.Thread(target=db_persist_loop, daemon=True)
    db_thread.start()
    
    app.run()

if __name__ == "__main__":
    main()