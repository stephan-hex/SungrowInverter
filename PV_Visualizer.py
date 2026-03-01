import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import sqlite3
import datetime
import os
import bisect
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
import matplotlib.dates as mdates

# Konfiguration
DB_NAME = "pv_data.db"

class PVVisualizer:
    def __init__(self, root):
        self.root = root
        self.root.title("PV Datenbank Visualizer")
        self.root.geometry("1200x800")
        
        self.db_path = os.path.join(os.path.dirname(__file__), DB_NAME)
        
        # Status-Variablen
        self.available_columns = []
        self.check_vars = {} # Speichert den Status der Checkboxen {col_name: BooleanVar}
        self.time_range_mode = "24h" # Default
        self.custom_days = 1
        self.cursor_line = None
        self.plot_x_nums = []
        self.plot_timestamps = []
        self.plot_data_map = {}
        
        # GUI Aufbau
        self._setup_layout()
        
        # Daten laden
        if self._connect_db_and_fetch_columns():
            self._create_checkboxes()
            self.refresh_plot()
        else:
            messagebox.showerror("Fehler", f"Konnte Datenbank nicht lesen: {self.db_path}")

    def _setup_layout(self):
        # --- Toolbar oben (Zeitraum) ---
        toolbar_frame = ttk.Frame(self.root, padding=5)
        toolbar_frame.pack(side=tk.TOP, fill=tk.X)
        
        ttk.Label(toolbar_frame, text="Zeitraum: ").pack(side=tk.LEFT)
        
        modes = [
            ("Letzte 24h", "24h"),
            ("Letzte Woche", "week"),
            ("Letzter Monat", "month"),
            ("Letztes Jahr", "year"),
            ("Benutzerdefiniert (Tage)", "custom")
        ]
        
        self.mode_var = tk.StringVar(value="24h")
        for text, mode in modes:
            rb = ttk.Radiobutton(toolbar_frame, text=text, variable=self.mode_var, value=mode, command=self._on_mode_change)
            rb.pack(side=tk.LEFT, padx=10)

        ttk.Button(toolbar_frame, text="Aktualisieren", command=self.refresh_plot).pack(side=tk.RIGHT, padx=10)

        # --- Hauptbereich (Split: Links Controls, Rechts Plot) ---
        main_pane = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_pane.pack(fill=tk.BOTH, expand=True)
        
        # Linke Seite: Scrollbare Liste der Register
        left_frame = ttk.Frame(main_pane, width=250)
        main_pane.add(left_frame, weight=1)
        
        ttk.Label(left_frame, text="Register auswählen:", font=("Arial", 10, "bold")).pack(pady=5)
        
        # Scrollbar Logik für Checkboxen
        canvas = tk.Canvas(left_frame)
        scrollbar = ttk.Scrollbar(left_frame, orient="vertical", command=canvas.yview)
        self.scrollable_frame = ttk.Frame(canvas)
        
        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Rechte Seite: Split Vertikal (Plot oben, Daten unten)
        right_pane = ttk.PanedWindow(main_pane, orient=tk.VERTICAL)
        main_pane.add(right_pane, weight=4)
        
        # Plot Bereich (Oben)
        plot_frame = ttk.Frame(right_pane)
        right_pane.add(plot_frame, weight=3)

        # Matplotlib Figure
        self.fig, self.ax = plt.subplots(figsize=(5, 4), dpi=100)
        self.canvas_plot = FigureCanvasTkAgg(self.fig, master=plot_frame)
        self.canvas_plot.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        
        # Matplotlib Toolbar (Zoom, Pan, Save)
        toolbar = NavigationToolbar2Tk(self.canvas_plot, plot_frame)
        toolbar.update()
        self.canvas_plot.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        
        # Maus-Rad Zoom aktivieren
        self.canvas_plot.mpl_connect('scroll_event', self._on_scroll)
        self.canvas_plot.mpl_connect('motion_notify_event', self._on_mouse_move)

        # Daten Bereich (Unten)
        self.data_frame = ttk.Frame(right_pane, padding=10)
        right_pane.add(self.data_frame, weight=1)
        
        ttk.Label(self.data_frame, text="Werte am Cursor:", font=("Arial", 10, "bold")).pack(anchor="w")
        self.values_container = ttk.Frame(self.data_frame)
        self.values_container.pack(fill=tk.BOTH, expand=True)
        self.lbl_cursor_time = None
        self.value_labels = {}

    def _connect_db_and_fetch_columns(self):
        """Liest die Spaltennamen aus der Tabelle readings"""
        if not os.path.exists(self.db_path):
            return False
            
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            # Metadaten der Tabelle abrufen
            cursor.execute("PRAGMA table_info(readings)")
            columns_info = cursor.fetchall()
            conn.close()
            
            # Spalten extrahieren (Name ist an Index 1)
            # Wir ignorieren 'timestamp', da das unsere X-Achse ist
            self.available_columns = [col[1] for col in columns_info if col[1] != 'timestamp']
            return True
        except Exception as e:
            print(f"DB Error: {e}")
            return False

    def _create_checkboxes(self):
        """Erstellt dynamisch Checkboxen für alle gefundenen Spalten"""
        for col in self.available_columns:
            var = tk.BooleanVar(value=False)
            # Standardmäßig total_dc_power aktivieren, falls vorhanden
            if col == "total_dc_power":
                var.set(True)
                
            cb = ttk.Checkbutton(self.scrollable_frame, text=col, variable=var, command=self.refresh_plot)
            cb.pack(anchor="w", padx=5, pady=2)
            self.check_vars[col] = var

    def _on_mode_change(self):
        mode = self.mode_var.get()
        if mode == "custom":
            days = simpledialog.askinteger("Zeitraum", "Anzahl der Tage eingeben:", parent=self.root, minvalue=1, maxvalue=3650)
            if days:
                self.custom_days = days
            else:
                # Fallback auf 24h wenn abgebrochen
                self.mode_var.set("24h")
                return
        self.refresh_plot()

    def _get_time_range(self):
        mode = self.mode_var.get()
        now = datetime.datetime.now()
        end_ts = now.timestamp()
        
        start_dt = now
        if mode == "24h":
            start_dt = now - datetime.timedelta(hours=24)
        elif mode == "week":
            start_dt = now - datetime.timedelta(weeks=1)
        elif mode == "month":
            start_dt = now - datetime.timedelta(days=30)
        elif mode == "year":
            start_dt = now - datetime.timedelta(days=365)
        elif mode == "custom":
            start_dt = now - datetime.timedelta(days=self.custom_days)
            
        start_ts = start_dt.timestamp()
        return start_ts, end_ts

    def _on_scroll(self, event):
        """Zoomt in/out bei Mausrad-Bewegung (fokussiert auf X-Achse/Zeit)"""
        if event.inaxes != self.ax:
            return
            
        # Zoom-Faktor (up = reinzoomen, down = rauszoomen)
        scale_factor = 0.8 if event.button == 'up' else 1.2
        
        cur_xlim = self.ax.get_xlim()
        cur_xrange = (cur_xlim[1] - cur_xlim[0])
        xdata = event.xdata
        
        new_xrange = cur_xrange * scale_factor
        new_xmin = xdata - new_xrange * (xdata - cur_xlim[0]) / cur_xrange
        new_xmax = new_xmin + new_xrange
        
        self.ax.set_xlim([new_xmin, new_xmax])
        self.canvas_plot.draw()

    def _on_mouse_move(self, event):
        """Bewegt den vertikalen Cursor"""
        if not event.inaxes or not self.cursor_line:
            if self.cursor_line and self.cursor_line.get_visible():
                self.cursor_line.set_visible(False)
                self.canvas_plot.draw_idle()
            return

        self.cursor_line.set_xdata([event.xdata, event.xdata])
        self.cursor_line.set_visible(True)
        self.canvas_plot.draw_idle()
        
        # Daten unter dem Plot aktualisieren
        if len(self.plot_x_nums) == 0:
            return
            
        # Nächstgelegenen Index finden
        x = event.xdata
        idx = bisect.bisect_left(self.plot_x_nums, x)
        
        # Grenzen prüfen und nächsten Nachbarn wählen
        if idx >= len(self.plot_x_nums):
            idx = len(self.plot_x_nums) - 1
        elif idx > 0:
            if abs(self.plot_x_nums[idx] - x) > abs(self.plot_x_nums[idx-1] - x):
                idx = idx - 1
        
        # Zeitstempel aktualisieren
        current_ts = self.plot_timestamps[idx]
        if self.lbl_cursor_time:
            self.lbl_cursor_time.config(text=f"Zeit: {current_ts.strftime('%d.%m.%Y %H:%M:%S')}")
            
        # Werte aktualisieren
        for col, label in self.value_labels.items():
            val = self.plot_data_map[col][idx]
            label.config(text=f"{val:.2f}" if val is not None else "N/A")

    def refresh_plot(self):
        # 1. Welche Spalten sind aktiv?
        selected_cols = [col for col, var in self.check_vars.items() if var.get()]
        
        if not selected_cols:
            self.ax.clear()
            self.ax.text(0.5, 0.5, "Keine Daten ausgewählt", ha='center', va='center')
            self.canvas_plot.draw()
            return

        # 2. Zeitraum berechnen
        start_ts, end_ts = self._get_time_range()

        # 3. Daten aus DB holen
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Debug: Anzahl der Werte prüfen
            cursor.execute("SELECT COUNT(*) FROM readings")
            row_count = cursor.fetchone()[0]
            print(f"Anzahl der Datensätze in der Datenbank: {row_count}")
            
            # SQL Injection verhindern: Spaltennamen sind sicher, da sie aus PRAGMA kamen, 
            # aber wir bauen den String trotzdem vorsichtig.
            cols_str = ", ".join(selected_cols)
            query = f"SELECT timestamp, {cols_str} FROM readings WHERE timestamp BETWEEN ? AND ? ORDER BY timestamp ASC"
            
            cursor.execute(query, (start_ts, end_ts))
            rows = cursor.fetchall()
            conn.close()
        except Exception as e:
            print(f"Fehler beim Lesen der Daten: {e}")
            return

        if not rows:
            self.ax.clear()
            self.ax.text(0.5, 0.5, "Keine Daten im gewählten Zeitraum", ha='center', va='center')
            self.canvas_plot.draw()
            return

        # 4. Daten aufbereiten für Plot
        timestamps = [datetime.datetime.fromtimestamp(row[0]) for row in rows]
        self.plot_timestamps = timestamps
        self.plot_x_nums = mdates.date2num(timestamps)
        
        data_map = {col: [] for col in selected_cols}
        
        for row in rows:
            # row[0] ist timestamp, row[1:] sind die Werte
            for idx, col in enumerate(selected_cols):
                val = row[idx + 1]
                data_map[col].append(val)
        self.plot_data_map = data_map

        # 5. Plotten
        self.ax.clear()
        
        for col in selected_cols:
            # Einfache Logik: Wenn "power" im Namen, auf linker Achse, sonst... 
            # (Hier plotten wir erstmal alles auf eine Achse, Matplotlib handled Skalierung automatisch, 
            # aber bei gemischten Einheiten (V vs W) sieht es evtl. komisch aus. 
            # Der User sollte sinnvolle Kombinationen wählen.)
            self.ax.plot(timestamps, data_map[col], label=col)

        # Cursor-Linie initialisieren (versteckt)
        # Wir nutzen den ersten Zeitstempel als Startwert, damit die Skalierung (1970 vs Heute) nicht kaputt geht
        if timestamps:
            self.cursor_line = self.ax.axvline(x=timestamps[0], color='gray', linestyle='--', linewidth=1)
            self.cursor_line.set_visible(False)

        # Formatierung
        self.ax.set_title(f"Verlauf ({self.mode_var.get()})", fontsize=10)
        self.ax.set_xlabel("Zeit", fontsize=8)
        self.ax.set_ylabel("Wert", fontsize=8)
        self.ax.tick_params(axis='both', which='major', labelsize=7)
        self.ax.legend(loc='upper left', fontsize=7)
        self.ax.grid(True, linestyle='--', alpha=0.7)

        # Datumsformatierung auf der X-Achse
        self.ax.xaxis.set_major_formatter(mdates.DateFormatter('%d.%m. %H:%M'))
        self.fig.autofmt_xdate() # Rotiert die Labels damit sie nicht überlappen

        self.canvas_plot.draw()
        
        # Labels für Datenanzeige neu aufbauen
        for widget in self.values_container.winfo_children():
            widget.destroy()
            
        self.lbl_cursor_time = ttk.Label(self.values_container, text="Zeit: --", font=("Arial", 10, "bold"))
        self.lbl_cursor_time.grid(row=0, column=0, sticky="w", padx=10, pady=5)
        
        self.value_labels = {}
        for idx, col in enumerate(selected_cols):
            # Grid Layout: 2 Spalten für Werte
            row = (idx // 2) + 1
            col_idx = (idx % 2) * 2 
            
            ttk.Label(self.values_container, text=f"{col}:").grid(row=row, column=col_idx, sticky="e", padx=(10, 5), pady=2)
            lbl_val = ttk.Label(self.values_container, text="--")
            lbl_val.grid(row=row, column=col_idx+1, sticky="w", padx=(0, 10), pady=2)
            self.value_labels[col] = lbl_val

if __name__ == "__main__":
    root = tk.Tk()
    app = PVVisualizer(root)
    root.mainloop()
