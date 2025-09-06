# file: net_usage_app.py
import kivy
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.clock import Clock
import psutil
import sqlite3
import time

DB_FILE = "net_usage.db"

# --- Setup DB ---
conn = sqlite3.connect(DB_FILE)
cur = conn.cursor()
cur.execute("""
CREATE TABLE IF NOT EXISTS usage (
    adapter TEXT,
    total_sent INTEGER,
    total_recv INTEGER,
    last_update TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")
conn.commit()

class NetUsage(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.orientation = "vertical"
        self.labels = {}
        self.update_labels()
        Clock.schedule_interval(self.update_labels, 5)  # update every 5s

    def update_labels(self, *args):
        counters = psutil.net_io_counters(pernic=True)
        for adapter, stats in counters.items():
            sent, recv = stats.bytes_sent, stats.bytes_recv

            # Check if adapter exists in DB
            conn = sqlite3.connect(DB_FILE)
            cur = conn.cursor()
            cur.execute("SELECT total_sent, total_recv FROM usage WHERE adapter=?", (adapter,))
            row = cur.fetchone()

            if row:
                prev_sent, prev_recv = row
                delta_sent = sent - prev_sent
                delta_recv = recv - prev_recv
                total_sent = prev_sent + max(delta_sent, 0)
                total_recv = prev_recv + max(delta_recv, 0)
                cur.execute("UPDATE usage SET total_sent=?, total_recv=?, last_update=CURRENT_TIMESTAMP WHERE adapter=?",
                            (total_sent, total_recv, adapter))
            else:
                total_sent, total_recv = sent, recv
                cur.execute("INSERT INTO usage(adapter, total_sent, total_recv) VALUES(?,?,?)",
                            (adapter, total_sent, total_recv))
            conn.commit()

            # Update GUI
            total_gb = (total_sent + total_recv) / (1024**3)
            if adapter not in self.labels:
                lbl = Label(text=f"{adapter}: {total_gb:.2f} GB", font_size=20)
                self.labels[adapter] = lbl
                self.add_widget(lbl)
            else:
                self.labels[adapter].text = f"{adapter}: {total_gb:.2f} GB"

class NetUsageApp(App):
    def build(self):
        return NetUsage()

if __name__ == "__main__":
    NetUsageApp().run()
