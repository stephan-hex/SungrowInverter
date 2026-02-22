from pymodbus.client import ModbusTcpClient
import json
import os
from PV_UI import PV_UI
from PV_Web import PV_Web

# Konfiguration
# Ersetzen Sie dies durch die tatsächliche IP-Adresse Ihres Wechselrichters oder WiNet-S Dongles
INVERTER_IP = '192.168.178.154' 
INVERTER_PORT = 502
SLAVE_ID = 1  # Standard Unit ID ist meistens 1
WEBSERVER_ON = True

# Register global laden
REGISTERS = {}
try:
    with open(os.path.join(os.path.dirname(__file__), 'registers.json'), 'r') as f:
        REGISTERS = json.load(f)
except Exception as e:
    print(f"Fehler beim Laden der registers.json: {e}")

def read_modbus_data():
    """Liest alle Register aus und gibt ein Dictionary zurück"""
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
                    
                    # Formatierung: Float bei Faktor < 1, sonst Int-Darstellung (wenn möglich)
                    if name == 'total_pv_generation':
                        # Spezielle Umrechnung und Formatierung für Gesamtertrag in MWh
                        mwh_val = final_val / 1000
                        data_output[name] = f"{mwh_val:.2f} MWh"
                    elif isinstance(final_val, float):
                        data_output[name] = f"{final_val:.2f} {unit}"
                    else:
                        data_output[name] = f"{final_val} {unit}"
                else:
                    data_output[name] = "Error"
        except Exception as e:
            print(f"Fehler beim Lesen: {e}")
        finally:
            client.close()
    else:
        print("Keine Verbindung zum Wechselrichter")
    
    return data_output

def main():
    print("Starte UI...")
    
    if WEBSERVER_ON:
        web = PV_Web(fetch_data_callback=read_modbus_data)
        web.start()
        
    # UI initialisieren und die Lesefunktion übergeben
    app = PV_UI(fetch_data_callback=read_modbus_data, update_interval=5000)
    app.run()

if __name__ == "__main__":
    main()