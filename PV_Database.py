import sqlite3
import time
import os

class PV_Database:
    def __init__(self, db_name="pv_data.db", registers_dict=None):
        """
        Initialisiert die Datenbankverbindung und erstellt die Tabelle, falls nicht vorhanden.
        :param db_name: Name der Datenbankdatei
        :param registers_dict: Das Dictionary aus registers.json, um die Spalten zu definieren
        """
        self.db_path = os.path.join(os.path.dirname(__file__), db_name)
        self.registers = registers_dict if registers_dict else {}
        self.buffer = []
        self.lock = False # Einfacher Schutz, falls nötig, hier reicht aber meist die Thread-Sicherheit von Listen
        
        # SQLite Verbindung aufbauen (check_same_thread=False erlaubt Zugriff aus verschiedenen Threads)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._create_table()

    def _create_table(self):
        """Erstellt die Tabelle basierend auf den Register-Keys dynamisch"""
        if not self.registers:
            return

        # Basis-Spalte Zeitstempel
        columns = ["timestamp INTEGER"]
        
        # Für jedes Register eine Spalte anlegen (Typ REAL für Durchschnittswerte)
        for key in self.registers.keys():
            columns.append(f"{key} REAL")
        
        col_str = ", ".join(columns)
        query = f"CREATE TABLE IF NOT EXISTS readings ({col_str})"
        
        try:
            with self.conn:
                self.conn.execute(query)
        except sqlite3.Error as e:
            print(f"Datenbank Fehler beim Erstellen der Tabelle: {e}")

    def prepare_data(self, data, timestamp):
        """
        Speichert Rohdaten temporär in einer Liste.
        :param data: Dictionary mit den Rohwerten
        :param timestamp: EPOCH Zeitstempel
        """
        if not data:
            return

        # Wir speichern eine Kopie der Daten zusammen mit dem Zeitstempel
        entry = data.copy()
        entry['timestamp'] = timestamp
        self.buffer.append(entry)

    def persist_data(self):
        """
        Berechnet den Mittelwert der gepufferten Daten und schreibt ihn in die DB.
        Wird zyklisch aufgerufen.
        """
        if not self.buffer:
            return

        # Daten aus dem Buffer holen und Buffer leeren (atomar-ähnlich)
        current_buffer = self.buffer
        self.buffer = []
        
        count = len(current_buffer)
        if count == 0:
            return

        # Durchschnittswerte berechnen
        avg_data = {}
        
        # Wir iterieren über alle bekannten Register
        for key in self.registers.keys():
            values = []
            for entry in current_buffer:
                val = entry.get(key)
                if val is not None and isinstance(val, (int, float)):
                    values.append(val)
            
            if values:
                avg_data[key] = sum(values) / len(values)
            else:
                avg_data[key] = None

        # Spezielle Anforderung: Print total_dc_power
        if 'total_dc_power' in avg_data and avg_data['total_dc_power'] is not None:
            print(f"DB Save: Durchschnitt total_dc_power: {avg_data['total_dc_power']:.2f} W")

        # Zeitstempel für den DB-Eintrag (wir nehmen den aktuellen Zeitpunkt des Schreibens)
        write_timestamp = int(time.time())

        # SQL Insert vorbereiten
        cols = ['timestamp']
        vals = [write_timestamp]
        placeholders = ['?']

        for key, val in avg_data.items():
            cols.append(key)
            vals.append(val)
            placeholders.append('?')

        query = f"INSERT INTO readings ({', '.join(cols)}) VALUES ({', '.join(placeholders)})"

        try:
            with self.conn:
                self.conn.execute(query, vals)
        except sqlite3.Error as e:
            print(f"Datenbank Fehler beim Schreiben: {e}")

    def close(self):
        self.conn.close()
