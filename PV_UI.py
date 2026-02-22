import tkinter as tk
from tkinter import ttk
import threading

class PV_UI:
    def __init__(self, fetch_data_callback, update_interval=5000):
        """
        :param fetch_data_callback: Funktion, die ein Dictionary mit den Daten zurückgibt.
        :param update_interval: Zeit in ms zwischen den Updates (Standard: 5000ms)
        """
        self.fetch_data_callback = fetch_data_callback
        self.update_interval = update_interval
        self.data = {}

        # Hauptfenster
        self.root = tk.Tk()
        self.root.title("Sungrow Inverter Monitor")
        self.root.geometry("800x600")
        
        # Styling
        style = ttk.Style()
        style.configure("Big.TLabel", font=("Helvetica", 36, "bold"))
        style.configure("Header.TLabel", font=("Helvetica", 14))
        style.configure("Data.TLabel", font=("Helvetica", 12))
        style.configure("Value.TLabel", font=("Helvetica", 12, "bold"))

        # UI Aufbauen
        self._create_widgets()
        
        # Erster Start des Update-Loops
        self.root.after(100, self._update_loop)

    def _create_widgets(self):
        main_frame = ttk.Frame(self.root, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # --- Oberer Bereich (2 Spalten) ---
        top_frame = ttk.Frame(main_frame)
        top_frame.pack(fill=tk.X, pady=(0, 30))
        top_frame.columnconfigure(0, weight=1)
        top_frame.columnconfigure(1, weight=1)

        # Links: Total DC Power
        frame_dc = ttk.Frame(top_frame)
        frame_dc.grid(row=0, column=0, sticky="ew")
        ttk.Label(frame_dc, text="Aktuelle Leistung (DC)", style="Header.TLabel").pack()
        self.lbl_dc_power = ttk.Label(frame_dc, text="-- W", style="Big.TLabel", foreground="#2ecc71")
        self.lbl_dc_power.pack()

        # Rechts: Daily PV Generation
        frame_daily = ttk.Frame(top_frame)
        frame_daily.grid(row=0, column=1, sticky="ew")
        ttk.Label(frame_daily, text="Tagesertrag", style="Header.TLabel").pack()
        self.lbl_daily_pv = ttk.Label(frame_daily, text="-- kWh", style="Big.TLabel", foreground="#3498db")
        self.lbl_daily_pv.pack()

        # --- Unterer Bereich: Betriebsdaten ---
        bottom_frame = ttk.LabelFrame(main_frame, text="Betriebsdaten", padding="15")
        bottom_frame.pack(fill=tk.BOTH, expand=True)

        # Grid Konfiguration für Betriebsdaten (2 Spalten für Labels/Werte)
        self.labels_map = {}
        
        # Definition der anzuzeigenden Felder (Label Text -> JSON Key)
        # Hinweis: JSON Keys müssen exakt mit registers.json übereinstimmen
        fields = [
            ("Batterie SOC", "battery_soc"),
            ("Batterie Leistung", "battery_power"),
            ("Interne Temperatur", "internal_temperature"),
            ("Netzleistung (Active)", "meter_Active_power"), # Achtung: Case Sensitive aus registers.json
            ("Import heute", "daily_import_energy"),
            ("Export heute", "daily_export_energy"),
            ("Gesamtertrag", "total_pv_generation")
        ]

        for idx, (label_text, key) in enumerate(fields):
            row = idx // 2
            col = (idx % 2) * 2 # Spalte 0 und 2 für Labels, 1 und 3 für Werte

            ttk.Label(bottom_frame, text=label_text + ":", style="Data.TLabel").grid(row=row, column=col, sticky="w", padx=10, pady=10)
            
            val_label = ttk.Label(bottom_frame, text="--", style="Value.TLabel")
            val_label.grid(row=row, column=col+1, sticky="w", padx=(0, 40), pady=10)
            
            self.labels_map[key] = val_label

    def _update_loop(self):
        """Ruft Daten ab und aktualisiert die UI"""
        # Datenabruf im Hintergrund wäre besser, hier synchron für Einfachheit
        # (Tkinter friert kurz ein, wenn Netzwerk langsam ist)
        try:
            new_data = self.fetch_data_callback()
            if new_data:
                self._refresh_ui(new_data)
        except Exception as e:
            print(f"UI Update Fehler: {e}")

        # Nächsten Aufruf planen
        self.root.after(self.update_interval, self._update_loop)

    def _refresh_ui(self, data):
        # Top Area
        if "total_dc_power" in data:
            self.lbl_dc_power.config(text=data["total_dc_power"])
        
        if "daily_pv_generation" in data:
            self.lbl_daily_pv.config(text=data["daily_pv_generation"])

        # Bottom Area
        for key, label_widget in self.labels_map.items():
            # Fallback für meter_Active_power vs meter_active_power falls JSON variiert
            val = data.get(key, data.get(key.lower(), "N/A"))
            label_widget.config(text=val)

    def run(self):
        self.root.mainloop()