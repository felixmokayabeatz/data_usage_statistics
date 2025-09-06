# net_usage_app.py
import os
import sqlite3
import psutil
import winreg

from kivy.app import App
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.clock import Clock
from kivy.core.window import Window

DB_FILE = "net_usage.db"

# --- Setup DB ---
conn = sqlite3.connect(DB_FILE)
cur = conn.cursor()
cur.execute("""
CREATE TABLE IF NOT EXISTS usage (
    adapter TEXT PRIMARY KEY,
    total_sent INTEGER,
    total_recv INTEGER,
    last_update TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")
conn.commit()


def add_to_startup(app_name="NetUsageApp"):
    """Register the app in Windows startup (runs once)."""
    exe_path = os.path.realpath(__file__).replace(".py", ".exe")
    key = winreg.HKEY_CURRENT_USER
    subkey = r"Software\Microsoft\Windows\CurrentVersion\Run"
    registry_key = winreg.OpenKey(key, subkey, 0, winreg.KEY_SET_VALUE)
    winreg.SetValueEx(registry_key, app_name, 0, winreg.REG_SZ, exe_path)
    winreg.CloseKey(registry_key)


class NetUsage(GridLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.cols = 1
        self.padding = 20
        self.spacing = 15
        self.labels = {}
        Window.clearcolor = (0.1, 0.1, 0.1, 1)  # dark background
        self.add_widget(Label(text="📡 Network Data Usage", font_size=28, bold=True, color=(0,1,0,1)))
        Clock.schedule_interval(self.update_labels, 5)

    def update_labels(self, *args):
        counters = psutil.net_io_counters(pernic=True)
        for adapter, stats in counters.items():
            sent, recv = stats.bytes_sent, stats.bytes_recv
            conn = sqlite3.connect(DB_FILE)
            cur = conn.cursor()
            cur.execute("SELECT total_sent, total_recv FROM usage WHERE adapter=?", (adapter,))
            row = cur.fetchone()

            if row:
                prev_sent, prev_recv = row
                total_sent = max(sent, prev_sent)
                total_recv = max(recv, prev_recv)
                cur.execute("UPDATE usage SET total_sent=?, total_recv=? WHERE adapter=?",
                            (total_sent, total_recv, adapter))
            else:
                total_sent, total_recv = sent, recv
                cur.execute("INSERT INTO usage(adapter,total_sent,total_recv) VALUES(?,?,?)",
                            (adapter, total_sent, total_recv))
            conn.commit()

            # Show in GB
            total_gb = (total_sent + total_recv) / (1024**3)

            text = f"[b]{adapter}[/b]\n{total_gb:.2f} GB total"
            if adapter not in self.labels:
                lbl = Label(text=text, font_size=20, markup=True, color=(1,1,1,1))
                self.labels[adapter] = lbl
                self.add_widget(lbl)
            else:
                self.labels[adapter].text = text


class NetUsageApp(App):
    def build(self):
        return NetUsage()


if __name__ == "__main__":
    add_to_startup()   # 🔹 Add to Windows startup
    NetUsageApp().run()
