# net_usage_app.py
import os
import sys
import sqlite3
import psutil
import winreg

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.uix.scrollview import ScrollView

APP_NAME = "NetUsageApp"

# --- Persistent folder in AppData ---
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.join(os.environ.get("LOCALAPPDATA"), APP_NAME)
else:
    BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), APP_NAME)
os.makedirs(BASE_DIR, exist_ok=True)
DB_FILE = os.path.join(BASE_DIR, "net_usage.db")

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


def add_to_startup(app_name=APP_NAME):
    """Register the app in Windows startup (runs once)."""
    if getattr(sys, 'frozen', False):
        exe_path = sys.executable
    else:
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
        self.spacing = 10

        # Dark modern background
        Window.clearcolor = (0.12, 0.12, 0.14, 1)

        # Scrollable layout for many adapters
        self.scroll = ScrollView(size_hint=(1, 1))
        self.grid = GridLayout(cols=1, spacing=10, size_hint_y=None)
        self.grid.bind(minimum_height=self.grid.setter('height'))
        self.scroll.add_widget(self.grid)
        self.add_widget(self.scroll)

        # Title
        self.title = Label(
            text="📡 Network Data Usage",
            font_size=32,
            bold=True,
            color=(0.2, 0.9, 0.3, 1),
            size_hint_y=None,
            height=50
        )
        self.grid.add_widget(self.title)

        # Total usage label
        self.total_label = Label(
            text="Total: 0.00 GB",
            font_size=24,
            bold=True,
            color=(0.7, 0.7, 1, 1),
            size_hint_y=None,
            height=40
        )
        self.grid.add_widget(self.total_label)

        self.labels = {}  # adapter -> label
        Clock.schedule_interval(self.update_labels, 5)

    def update_labels(self, *args):
        counters = psutil.net_io_counters(pernic=True)
        total_bytes = 0

        for adapter, stats in counters.items():
            sent, recv = stats.bytes_sent, stats.bytes_recv
            cur.execute("SELECT total_sent, total_recv FROM usage WHERE adapter=?", (adapter,))
            row = cur.fetchone()

            if row:
                prev_sent, prev_recv = row
                total_sent = max(sent, prev_sent)
                total_recv = max(recv, prev_recv)
                cur.execute("UPDATE usage SET total_sent=?, total_recv=?, last_update=CURRENT_TIMESTAMP WHERE adapter=?",
                            (total_sent, total_recv, adapter))
            else:
                total_sent, total_recv = sent, recv
                cur.execute("INSERT INTO usage(adapter,total_sent,total_recv) VALUES(?,?,?)",
                            (adapter, total_sent, total_recv))

            total_bytes += total_sent + total_recv
            total_gb = (total_sent + total_recv) / (1024**3)

            text = f"[b]{adapter}[/b]\n{total_gb:.2f} GB used"
            if adapter not in self.labels:
                lbl = Label(
                    text=text,
                    font_size=20,
                    markup=True,
                    color=(1, 1, 1, 1),
                    size_hint_y=None,
                    height=60
                )
                self.labels[adapter] = lbl
                self.grid.add_widget(lbl)
            else:
                self.labels[adapter].text = text

        # Update total
        total_gb_all = total_bytes / (1024**3)
        self.total_label.text = f"Total: {total_gb_all:.2f} GB"

        conn.commit()


class NetUsageApp(App):
    def build(self):
        return NetUsage()


if __name__ == "__main__":
    add_to_startup()
    NetUsageApp().run()
