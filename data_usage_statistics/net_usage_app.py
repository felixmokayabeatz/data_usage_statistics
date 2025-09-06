# net_usage_app.py
import os
import sys
import sqlite3
import psutil
import winreg
import threading
import time
from datetime import datetime

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.uix.scrollview import ScrollView
from kivy.uix.popup import Popup
from kivy.uix.button import Button
from kivy.uix.togglebutton import ToggleButton
from kivy.uix.slider import Slider
from kivy.graphics import Color, Rectangle, RoundedRectangle
from kivy.utils import platform
from kivy.config import Config
from kivy.core.clipboard import Clipboard
from kivy.properties import BooleanProperty, NumericProperty, StringProperty
from kivy.metrics import dp
from kivy.lang import Builder

# Try to import system tray functionality
try:
    if platform == 'win':
        import win32api
        import win32gui
        import win32con
        HAS_SYSTRAY = True
    else:
        HAS_SYSTRAY = False
except ImportError:
    HAS_SYSTRAY = False

APP_NAME = "NetUsageApp"
APP_VERSION = "2.0"

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

# Store initial counters to avoid counting VPN traffic
initial_counters = {}
start_minimized = False

def get_physical_adapters():
    """Identify physical network adapters and exclude VPNs"""
    physical_adapters = []
    addrs = psutil.net_if_addrs()
    stats = psutil.net_if_stats()
    
    for adapter, addrs_list in addrs.items():
        # Skip loopback and tunnel adapters
        if adapter.lower().startswith(('lo', 'tun', 'vpn', 'ppp', 'tap')):
            continue
            
        # Skip disconnected adapters
        if adapter not in stats or not stats[adapter].isup:
            continue
            
        # Check for physical adapters (Ethernet, Wi-Fi)
        for addr in addrs_list:
            if addr.family == psutil.AF_LINK:
                physical_adapters.append(adapter)
                break
                
    return physical_adapters

def init_counters():
    """Initialize counters for physical adapters only"""
    global initial_counters
    physical_adapters = get_physical_adapters()
    counters = psutil.net_io_counters(pernic=True)
    
    for adapter in physical_adapters:
        if adapter in counters:
            initial_counters[adapter] = counters[adapter]

# Initialize counters on startup
init_counters()

# Custom UI Components
class DashboardLabel(Label):
    pass

class DashboardCard(BoxLayout):
    title = StringProperty("")
    value = StringProperty("")
    icon = StringProperty("")

class DashboardButton(Button):
    pass

class ModernLabel(Label):
    """Custom label with modern styling"""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.color = (0.9, 0.9, 0.9, 1)
        self.font_size = dp(16)
        self.size_hint_y = None
        self.height = dp(40)
        self.valign = 'middle'
        self.halign = 'left'
        self.text_size = (self.width, None)

class ModernButton(Button):
    """Custom button with modern styling"""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.background_normal = ''
        self.background_color = (0.2, 0.6, 0.9, 1)
        self.color = (1, 1, 1, 1)
        self.size_hint_y = None
        self.height = dp(40)
        self.font_size = dp(16)
        self.border_radius = [dp(10)]

class SettingsPopup(Popup):
    """Settings popup window"""
    def __init__(self, main_app, **kwargs):
        super().__init__(**kwargs)
        self.main_app = main_app
        self.title = "Settings"
        self.title_size = dp(20)
        self.title_color = (1, 1, 1, 1)
        self.size_hint = (0.8, 0.6)
        self.separator_color = (0.2, 0.6, 0.9, 1)
        self.separator_height = dp(2)
        self.background = 'transparent'
        
        with self.canvas.before:
            Color(0.15, 0.15, 0.18, 1)
            RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(15)])
        
        layout = BoxLayout(orientation='vertical', padding=dp(20), spacing=dp(15))
        layout.bind(size=self._update_bg, pos=self._update_bg)
        
        # Refresh interval slider
        layout.add_widget(DashboardLabel(text="Refresh Interval (seconds):", font_size=dp(18)))
        self.interval_slider = Slider(min=1, max=60, value=main_app.refresh_interval)
        layout.add_widget(self.interval_slider)
        self.interval_label = DashboardLabel(text=f"Current: {self.interval_slider.value} seconds", font_size=dp(16))
        layout.add_widget(self.interval_label)
        self.interval_slider.bind(value=self.on_slider_change)
        
        # Startup toggle
        self.startup_toggle = ToggleButton(text="Start with Windows", state='normal', 
                                          size_hint_y=None, height=dp(40))
        self.startup_toggle.bind(state=self.on_startup_toggle)
        layout.add_widget(self.startup_toggle)
        
        # Check current startup status
        self.check_startup_status()
        
        # Close button
        close_btn = ModernButton(text="Close")
        close_btn.bind(on_release=self.dismiss)
        layout.add_widget(close_btn)
        
        self.content = layout
    
    def _update_bg(self, instance, value):
        self.canvas.before.clear()
        with self.canvas.before:
            Color(0.15, 0.15, 0.18, 1)
            RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(15)])
    
    def check_startup_status(self):
        """Check if app is set to start with Windows"""
        if platform == 'win':
            try:
                key = winreg.HKEY_CURRENT_USER
                subkey = r"Software\Microsoft\Windows\CurrentVersion\Run"
                registry_key = winreg.OpenKey(key, subkey, 0, winreg.KEY_READ)
                try:
                    winreg.QueryValueEx(registry_key, APP_NAME)
                    self.startup_toggle.state = 'down'
                except FileNotFoundError:
                    self.startup_toggle.state = 'normal'
                winreg.CloseKey(registry_key)
            except Exception:
                self.startup_toggle.state = 'normal'
    
    def on_slider_change(self, instance, value):
        self.interval_label.text = f"Current: {int(value)} seconds"
        self.main_app.refresh_interval = int(value)
    
    def on_startup_toggle(self, instance, value):
        if platform == 'win':
            if value == 'down':  # Add to startup
                self.add_to_startup()
            else:  # Remove from startup
                self.remove_from_startup()
    
    def add_to_startup(self):
        """Register the app in Windows startup (minimized to tray)"""
        if getattr(sys, 'frozen', False):
            exe_path = sys.executable
        else:
            exe_path = os.path.realpath(__file__).replace(".py", ".exe")
            if not os.path.exists(exe_path):
                # Fallback to Python script
                exe_path = sys.executable
                script_path = os.path.realpath(__file__)
                args = f'"{exe_path}" "{script_path}" --minimized'
                
                # Create a batch file to run the Python script
                batch_content = f'@echo off\nstart "" /min {args}'
                batch_path = os.path.join(BASE_DIR, "start_minimized.bat")
                
                with open(batch_path, 'w') as f:
                    f.write(batch_content)
                
                exe_path = batch_path

        key = winreg.HKEY_CURRENT_USER
        subkey = r"Software\Microsoft\Windows\CurrentVersion\Run"
        try:
            registry_key = winreg.OpenKey(key, subkey, 0, winreg.KEY_SET_VALUE)
            winreg.SetValueEx(registry_key, APP_NAME, 0, winreg.REG_SZ, f'"{exe_path}" --minimized')
            winreg.CloseKey(registry_key)
        except Exception as e:
            print(f"Error adding to startup: {e}")
    
    def remove_from_startup(self):
        """Remove the app from Windows startup"""
        if platform == 'win':
            try:
                key = winreg.HKEY_CURRENT_USER
                subkey = r"Software\Microsoft\Windows\CurrentVersion\Run"
                registry_key = winreg.OpenKey(key, subkey, 0, winreg.KEY_SET_VALUE)
                try:
                    winreg.DeleteValue(registry_key, APP_NAME)
                except FileNotFoundError:
                    pass  # Already not in startup
                winreg.CloseKey(registry_key)
            except Exception as e:
                print(f"Error removing from startup: {e}")

class NetUsage(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.orientation = 'vertical'
        self.padding = dp(20)
        self.spacing = dp(15)
        self.refresh_interval = 5  # seconds

        # Set window properties
        Window.size = (500, 700)
        Window.minimum_width = 450
        Window.minimum_height = 600
        
        # Dark modern background
        with self.canvas.before:
            Color(0.1, 0.1, 0.12, 1)
            self.bg_rect = Rectangle(pos=self.pos, size=self.size)
        
        self.bind(pos=self._update_bg, size=self._update_bg)

        # Header with title
        header = BoxLayout(size_hint_y=None, height=dp(80), spacing=dp(10))
        with header.canvas.before:
            Color(0.15, 0.15, 0.18, 1)
            header.bg_rect = RoundedRectangle(pos=header.pos, size=header.size, radius=[dp(15)])
        header.bind(pos=self._update_header_bg, size=self._update_header_bg)
        
        self.title_label = DashboardLabel(
            text="🌐 Network Data Dashboard",
            font_size=dp(24),
            bold=True,
            color=(0.2, 0.9, 0.6, 1),
        )
        header.add_widget(self.title_label)
        
        # Settings button
        settings_btn = DashboardButton(text="⚙️", size_hint_x=None, width=dp(50),
                                     background_color=(0.2, 0.6, 0.9, 1))
        settings_btn.bind(on_release=self.show_settings)
        header.add_widget(settings_btn)
        
        # Minimize to tray button
        if HAS_SYSTRAY:
            tray_btn = DashboardButton(text="➖", size_hint_x=None, width=dp(50),
                                     background_color=(0.3, 0.3, 0.4, 1))
            tray_btn.bind(on_release=self.minimize_to_tray)
            header.add_widget(tray_btn)
        
        self.add_widget(header)

        # Total usage card
        total_card = BoxLayout(orientation='vertical', size_hint_y=None, height=dp(120),
                             padding=dp(15), spacing=dp(10))
        with total_card.canvas.before:
            Color(0.15, 0.15, 0.18, 1)
            total_card.bg_rect = RoundedRectangle(pos=total_card.pos, size=total_card.size, radius=[dp(15)])
        total_card.bind(pos=self._update_card_bg, size=self._update_card_bg)
        
        total_card.add_widget(DashboardLabel(
            text="TOTAL DATA USAGE",
            font_size=dp(16),
            color=(0.7, 0.7, 0.8, 1)
        ))
        
        self.total_label = DashboardLabel(
            text="0.00 GB",
            font_size=dp(32),
            bold=True,
            color=(0.2, 0.9, 0.6, 1),
        )
        total_card.add_widget(self.total_label)
        
        self.add_widget(total_card)

        # Adapters section title
        self.add_widget(DashboardLabel(
            text="NETWORK ADAPTERS",
            font_size=dp(18),
            bold=True,
            color=(0.7, 0.7, 0.8, 1),
            size_hint_y=None,
            height=dp(40)
        ))

        # Scrollable layout for adapters
        self.scroll = ScrollView(size_hint=(1, 1))
        self.grid = GridLayout(cols=1, spacing=dp(15), size_hint_y=None)
        self.grid.bind(minimum_height=self.grid.setter('height'))
        self.scroll.add_widget(self.grid)
        self.add_widget(self.scroll)

        self.labels = {}  # adapter -> widget
        Clock.schedule_interval(self.update_labels, self.refresh_interval)

    def _update_bg(self, instance, value):
        self.bg_rect.pos = self.pos
        self.bg_rect.size = self.size
    
    def _update_header_bg(self, instance, value):
        instance.bg_rect.pos = instance.pos
        instance.bg_rect.size = instance.size
    
    def _update_card_bg(self, instance, value):
        instance.bg_rect.pos = instance.pos
        instance.bg_rect.size = instance.size

    def show_settings(self, instance):
        """Show settings popup"""
        popup = SettingsPopup(self)
        popup.open()

    def minimize_to_tray(self, instance):
        """Minimize the app to system tray"""
        if HAS_SYSTRAY and platform == 'win':
            Window.hide()
        else:
            # Fallback for systems without system tray support
            App.get_running_app().stop()

    def update_labels(self, *args):
        counters = psutil.net_io_counters(pernic=True)
        total_bytes = 0
        physical_adapters = get_physical_adapters()

        for adapter in physical_adapters:
            if adapter not in counters:
                continue
                
            # Get current stats
            current_stats = counters[adapter]
            
            # Get initial stats if available
            if adapter in initial_counters:
                initial_stats = initial_counters[adapter]
                sent = max(0, current_stats.bytes_sent - initial_stats.bytes_sent)
                recv = max(0, current_stats.bytes_recv - initial_stats.bytes_recv)
            else:
                sent, recv = current_stats.bytes_sent, current_stats.bytes_recv
                initial_counters[adapter] = current_stats

            # Update database
            cur.execute("SELECT total_sent, total_recv FROM usage WHERE adapter=?", (adapter,))
            row = cur.fetchone()

            if row:
                prev_sent, prev_recv = row
                total_sent = sent + prev_sent
                total_recv = recv + prev_recv
                cur.execute("UPDATE usage SET total_sent=?, total_recv=?, last_update=CURRENT_TIMESTAMP WHERE adapter=?",
                            (total_sent, total_recv, adapter))
            else:
                total_sent, total_recv = sent, recv
                cur.execute("INSERT INTO usage(adapter,total_sent,total_recv) VALUES(?,?,?)",
                            (adapter, total_sent, total_recv))

            total_bytes += total_sent + total_recv
            total_gb = (total_sent + total_recv) / (1024**3)

            # Create or update adapter card
            if adapter not in self.labels:
                # Create a card for this adapter
                card = BoxLayout(orientation='vertical', size_hint_y=None, height=dp(100),
                               padding=dp(15), spacing=dp(5))
                with card.canvas.before:
                    Color(0.15, 0.15, 0.18, 1)
                    card.bg_rect = RoundedRectangle(pos=card.pos, size=card.size, radius=[dp(15)])
                card.bind(pos=self._update_adapter_bg, size=self._update_adapter_bg)
                
                # Adapter name
                name_label = DashboardLabel(
                    text=adapter,
                    font_size=dp(16),
                    bold=True,
                    color=(0.8, 0.8, 1, 1),
                    size_hint_y=None,
                    height=dp(30)
                )
                card.add_widget(name_label)
                
                # Usage info
                usage_label = DashboardLabel(
                    text=f"{total_gb:.2f} GB used",
                    font_size=dp(20),
                    color=(0.6, 0.9, 0.8, 1),
                    size_hint_y=None,
                    height=dp(40)
                )
                card.add_widget(usage_label)
                
                self.labels[adapter] = {
                    'card': card,
                    'usage_label': usage_label
                }
                self.grid.add_widget(card)
            else:
                # Update existing card
                self.labels[adapter]['usage_label'].text = f"{total_gb:.2f} GB used"

        # Update total
        total_gb_all = total_bytes / (1024**3)
        self.total_label.text = f"{total_gb_all:.2f} GB"

        conn.commit()
    
    def _update_adapter_bg(self, instance, value):
        instance.bg_rect.pos = instance.pos
        instance.bg_rect.size = instance.size


class NetUsageApp(App):
    refresh_interval = NumericProperty(5)
    minimized = BooleanProperty(False)
    
    def build(self):
        self.title = "Network Data Dashboard"
        self.icon = os.path.join(BASE_DIR, 'icon.png') if os.path.exists(os.path.join(BASE_DIR, 'icon.png')) else None
        
        # Check if we should start minimized
        if '--minimized' in sys.argv:
            self.minimized = True
            # Schedule the minimize operation
            Clock.schedule_once(self.minimize_to_tray, 0.1)
        
        return NetUsage()

    def on_stop(self):
        """Save settings when app closes"""
        Config.set('netusage', 'refresh_interval', str(self.root.refresh_interval))
        Config.write()

    def minimize_to_tray(self, dt):
        """Minimize the app to system tray"""
        if HAS_SYSTRAY and platform == 'win':
            Window.hide()
        else:
            # Fallback for systems without system tray support
            self.stop()


if __name__ == "__main__":
    # Check if we should start minimized
    if '--minimized' in sys.argv:
        start_minimized = True
    
    # Initialize the app
    app = NetUsageApp()
    
    # Start the app
    app.run()