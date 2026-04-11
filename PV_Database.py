import sqlite3
import time
import os
import datetime

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
        
        # SQLite Verbindung aufbauen mit Timeout (5 Sek) für bessere Concurrency
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=5)
        # WAL-Modus aktivieren: Erlaubt gleichzeitiges Lesen und Schreiben
        self.conn.execute("PRAGMA journal_mode=WAL;")
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

    def get_today_values(self, col_names=None, date_obj=None):
        """Gibt die historischen Werte eines bestimmten Tages für das Chart zurück"""
        # Default auf total_dc_power, falls nichts übergeben wird
        if not col_names:
            col_names = ["total_dc_power"]

        # Vorbereitete Datenstruktur
        data = {'labels': [], 'datasets': {}}
        # Sicherstellen, dass für jede angefragte Spalte ein (leerer) Eintrag existiert
        for col in col_names:
            if isinstance(col, str):
                data['datasets'][col] = []

        try:
            if date_obj is None:
                date_obj = datetime.date.today()

            # Start und Ende des Tages als Timestamp
            start_dt = datetime.datetime.combine(date_obj, datetime.time.min)
            end_dt = datetime.datetime.combine(date_obj, datetime.time.max)

            start_ts = start_dt.timestamp()
            end_ts = end_dt.timestamp()

            cursor = self.conn.cursor()

            # Nur valide Spaltennamen für die SQL-Abfrage verwenden
            valid_cols = [c for c in col_names if isinstance(c, str) and (c in self.registers or c == "total_dc_power")]
            if not valid_cols:
                return data # Leere Datenstruktur zurückgeben, wenn keine validen Spalten da sind

            cols_str = ", ".join(valid_cols)
            query = f"SELECT timestamp, {cols_str} FROM readings WHERE timestamp >= ? AND timestamp <= ? ORDER BY timestamp ASC"
            cursor.execute(query, (start_ts, end_ts))
            rows = cursor.fetchall()

            for row in rows:
                dt = datetime.datetime.fromtimestamp(row[0])
                data['labels'].append(dt.strftime("%H:%M"))
                # Werte den entsprechenden Datasets zuordnen
                for i, col in enumerate(valid_cols):
                    val = row[i + 1]
                    data['datasets'][col].append(val)
        except Exception as e:
            print(f"DB Read Error: {e}")
        
        return data

    def close(self):
        self.conn.close()
