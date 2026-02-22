from pymodbus.client import ModbusTcpClient
import json
import os

# Konfiguration
# Ersetzen Sie dies durch die tatsächliche IP-Adresse Ihres Wechselrichters oder WiNet-S Dongles
INVERTER_IP = '192.168.178.154' 
INVERTER_PORT = 502
SLAVE_ID = 1  # Standard Unit ID ist meistens 1

def main():
    # Client initialisieren
    client = ModbusTcpClient(INVERTER_IP, port=INVERTER_PORT)
    
    print(f"Verbinde zu {INVERTER_IP} auf Port {INVERTER_PORT}...")
    
    if client.connect():
        print("Verbindung erfolgreich hergestellt!")
        
        try:
            # Register aus JSON-Datei laden
            with open(os.path.join(os.path.dirname(__file__), 'registers.json'), 'r') as f:
                REGISTERS = json.load(f)

            print(f"Lese {len(REGISTERS)} definierte Register...")
            
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
                    elif dtype == 'int8be':
                        val = regs[0] & 0xFF
                        if val > 0x7F:
                            val -= 0x100

                    final_val = val * factor
                    
                    # Formatierung: Float bei Faktor < 1, sonst Int-Darstellung (wenn möglich)
                    if isinstance(final_val, float):
                        print(f"{name:<25}: {final_val:.2f} {unit}")
                    else:
                        print(f"{name:<25}: {final_val} {unit}")
                else:
                    print(f"Fehler bei {name} (Addr {addr}): {rr}")
                
        except Exception as e:
            print(f"Ein Fehler ist aufgetreten: {e}")
        finally:
            client.close()
            print("Verbindung geschlossen.")
    else:
        print("Verbindung konnte nicht hergestellt werden. Bitte IP und Netzwerk prüfen.")

if __name__ == "__main__":
    main()