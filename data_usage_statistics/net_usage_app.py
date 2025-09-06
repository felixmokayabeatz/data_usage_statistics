# net_usage_app.py
import os
import sys
import sqlite3
import psutil
import winreg
import threading
import time
from datetime import datetime
import socket  # Added for computer name

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
from kivy.uix.progressbar import ProgressBar
from kivy.graphics import Color, Rectangle, RoundedRectangle, Line
from kivy.utils import platform
from kivy.config import Config
from kivy.properties import BooleanProperty, NumericProperty, StringProperty
from kivy.metrics import dp

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
            initial_counters[adapter] = {
                'bytes_sent': counters[adapter].bytes_sent,
                'bytes_recv': counters[adapter].bytes_recv
            }

# Initialize counters on startup
init_counters()

class ModernCard(BoxLayout):
    """Simple card with background"""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.padding = dp(15)
        self.spacing = dp(10)
        
        with self.canvas.before:
            Color(0.15, 0.15, 0.18, 1)  # Dark gray background
            self.bg = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(10)])
        
        self.bind(pos=self._update_bg, size=self._update_bg)
    
    def _update_bg(self, *args):
        self.bg.pos = self.pos
        self.bg.size = self.size

class StyledButton(Button):
    """Simple styled button that actually works"""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.background_normal = ''
        self.background_down = ''
        self.background_color = (0.2, 0.6, 1.0, 1)
        self.color = (1, 1, 1, 1)
        self.font_size = dp(14)
        self.bold = True
        self.size_hint_y = None
        self.height = dp(45)
        # Add rounded corners
        with self.canvas.before:
            Color(rgba=self.background_color)
            self.rect = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(8)])
        
        self.bind(pos=self._update_rect, size=self._update_rect)
    
    def _update_rect(self, *args):
        self.rect.pos = self.pos
        self.rect.size = self.size

class IconButton(StyledButton):
    """Simple icon button"""
    def __init__(self, button_text, **kwargs):
        super().__init__(**kwargs)
        self.text = button_text
        self.background_color = (0.3, 0.3, 0.35, 1)
        self.size_hint = (None, None)
        self.size = (dp(80), dp(40))
        self.font_size = dp(14)

class AdapterCard(ModernCard):
    """Network adapter display card"""
    def __init__(self, adapter_name, **kwargs):
        super().__init__(**kwargs)
        self.adapter_name = adapter_name
        self.size_hint_y = None
        self.height = dp(160)
        self.orientation = 'vertical'
        
        # Header with adapter name
        header = BoxLayout(size_hint_y=None, height=dp(35))
        
        # Connection type indicator
        conn_type = "WiFi" if any(x in adapter_name.lower() for x in ["wi-fi", "wireless", "wifi"]) else "Ethernet"
        type_label = Label(
            text=f"[{conn_type}]",
            font_size=dp(12),
            color=(0.6, 0.8, 1, 1),
            size_hint_x=None,
            width=dp(80),
            bold=True
        )
        header.add_widget(type_label)
        
        # Adapter name (truncated if too long)
        display_name = adapter_name[:30] + "..." if len(adapter_name) > 30 else adapter_name
        name_label = Label(
            text=display_name,
            font_size=dp(14),
            bold=True,
            color=(0.9, 0.9, 1, 1),
            halign='left',
            text_size=(None, None)
        )
        header.add_widget(name_label)
        
        self.add_widget(header)
        
        # Stats display
        stats_layout = GridLayout(cols=2, spacing=dp(10), size_hint_y=None, height=dp(80))
        
        # Upload section
        upload_box = BoxLayout(orientation='vertical', spacing=dp(5))
        upload_box.add_widget(Label(
            text="UPLOAD",
            font_size=dp(11),
            color=(0.7, 0.7, 0.8, 1),
            size_hint_y=None,
            height=dp(20),
            bold=True
        ))
        self.upload_label = Label(
            text="0 MB",
            font_size=dp(16),
            bold=True,
            color=(1, 0.5, 0.5, 1),
            size_hint_y=None,
            height=dp(25)
        )
        upload_box.add_widget(self.upload_label)
        stats_layout.add_widget(upload_box)
        
        # Download section
        download_box = BoxLayout(orientation='vertical', spacing=dp(5))
        download_box.add_widget(Label(
            text="DOWNLOAD",
            font_size=dp(11),
            color=(0.7, 0.7, 0.8, 1),
            size_hint_y=None,
            height=dp(20),
            bold=True
        ))
        self.download_label = Label(
            text="0 MB",
            font_size=dp(16),
            bold=True,
            color=(0.5, 1, 0.5, 1),
            size_hint_y=None,
            height=dp(25)
        )
        download_box.add_widget(self.download_label)
        stats_layout.add_widget(download_box)
        
        self.add_widget(stats_layout)
        
        # Total usage
        total_layout = BoxLayout(orientation='vertical', spacing=dp(5))
        total_layout.add_widget(Label(
            text="TOTAL USAGE",
            font_size=dp(11),
            color=(0.7, 0.7, 0.8, 1),
            size_hint_y=None,
            height=dp(20),
            bold=True
        ))
        
        self.total_label = Label(
            text="0.00 GB",
            font_size=dp(18),
            bold=True,
            color=(0.3, 0.9, 0.6, 1),
            size_hint_y=None,
            height=dp(30)
        )
        total_layout.add_widget(self.total_label)
        
        self.add_widget(total_layout)
    
    def update_stats(self, sent_mb, recv_mb, total_gb):
        """Update card with new statistics"""
        self.upload_label.text = f"{sent_mb:.1f} MB"
        self.download_label.text = f"{recv_mb:.1f} MB"
        self.total_label.text = f"{total_gb:.2f} GB"

class SettingsPopup(Popup):
    """Settings popup window"""
    def __init__(self, main_app, **kwargs):
        super().__init__(**kwargs)
        self.main_app = main_app
        self.title = "Settings"
        self.title_size = dp(18)
        self.title_color = (1, 1, 1, 1)
        self.size_hint = (0.8, 0.7)
        self.separator_color = (0.3, 0.3, 0.4, 1)
        self.separator_height = dp(2)
        
        # Main layout
        main_layout = BoxLayout(orientation='vertical', padding=dp(20), spacing=dp(15))
        
        # Refresh interval section
        refresh_card = ModernCard(orientation='vertical', size_hint_y=None, height=dp(120))
        
        refresh_card.add_widget(Label(
            text="Refresh Interval",
            font_size=dp(16),
            bold=True,
            color=(0.3, 0.8, 1, 1),
            size_hint_y=None,
            height=dp(30)
        ))
        
        self.interval_slider = Slider(
            min=1, 
            max=60, 
            value=main_app.refresh_interval,
            size_hint_y=None,
            height=dp(40)
        )
        refresh_card.add_widget(self.interval_slider)
        
        self.interval_label = Label(
            text=f"Update every {self.interval_slider.value:.0f} seconds",
            font_size=dp(14),
            color=(0.8, 0.8, 0.9, 1),
            size_hint_y=None,
            height=dp(25)
        )
        refresh_card.add_widget(self.interval_label)
        self.interval_slider.bind(value=self.on_slider_change)
        
        main_layout.add_widget(refresh_card)
        
        # Windows startup section
        startup_card = ModernCard(orientation='vertical', size_hint_y=None, height=dp(100))
        
        startup_card.add_widget(Label(
            text="Windows Startup",
            font_size=dp(16),
            bold=True,
            color=(0.3, 0.8, 1, 1),
            size_hint_y=None,
            height=dp(35)
        ))
        
        self.startup_toggle = ToggleButton(
            text="Start with Windows",
            state='normal',
            size_hint_y=None,
            height=dp(40),
            background_normal='',
            background_down='',
            background_color=(0.4, 0.4, 0.45, 1),
            color=(1, 1, 1, 1)
        )
        self.startup_toggle.bind(state=self.on_startup_toggle)
        startup_card.add_widget(self.startup_toggle)
        
        main_layout.add_widget(startup_card)
        
        # Database info
        db_card = ModernCard(orientation='vertical', size_hint_y=None, height=dp(80))
        
        db_card.add_widget(Label(
            text="Database Information",
            font_size=dp(16),
            bold=True,
            color=(0.3, 0.8, 1, 1),
            size_hint_y=None,
            height=dp(30)
        ))
        
        db_info = Label(
            text=f"Storage: {os.path.basename(DB_FILE)}",
            font_size=dp(12),
            color=(0.7, 0.7, 0.8, 1),
            size_hint_y=None,
            height=dp(25)
        )
        db_card.add_widget(db_info)
        
        main_layout.add_widget(db_card)
        
        # Check startup status
        self.check_startup_status()
        
        # Action buttons
        button_layout = BoxLayout(size_hint_y=None, height=dp(50), spacing=dp(15))
        
        reset_btn = StyledButton(text="Reset Data")
        reset_btn.background_color = (0.8, 0.3, 0.3, 1)
        reset_btn.bind(on_release=self.reset_data)
        button_layout.add_widget(reset_btn)
        
        close_btn = StyledButton(text="Save & Close")
        close_btn.bind(on_release=self.dismiss)
        button_layout.add_widget(close_btn)
        
        main_layout.add_widget(button_layout)
        self.content = main_layout
    
    def reset_data(self, *args):
        """Reset all usage data"""
        cur.execute("DELETE FROM usage")
        conn.commit()
        init_counters()
        self.dismiss()
    
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
                    self.startup_toggle.background_color = (0.3, 0.7, 0.3, 1)
                except FileNotFoundError:
                    self.startup_toggle.state = 'normal'
                    self.startup_toggle.background_color = (0.4, 0.4, 0.45, 1)
                winreg.CloseKey(registry_key)
            except Exception:
                self.startup_toggle.state = 'normal'
                self.startup_toggle.background_color = (0.4, 0.4, 0.45, 1)
    
    def on_slider_change(self, instance, value):
        self.interval_label.text = f"Update every {int(value)} seconds"
        self.main_app.refresh_interval = int(value)
    
    def on_startup_toggle(self, instance, value):
        if platform == 'win':
            if value == 'down':
                self.add_to_startup()
                self.startup_toggle.background_color = (0.3, 0.7, 0.3, 1)
            else:
                self.remove_from_startup()
                self.startup_toggle.background_color = (0.4, 0.4, 0.45, 1)
    
    def add_to_startup(self):
        """Add to Windows startup"""
        if getattr(sys, 'frozen', False):
            exe_path = sys.executable
        else:
            exe_path = os.path.realpath(__file__).replace(".py", ".exe")
            if not os.path.exists(exe_path):
                exe_path = sys.executable
                script_path = os.path.realpath(__file__)
                args = f'"{exe_path}" "{script_path}" --minimized'
                
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
        """Remove from Windows startup"""
        if platform == 'win':
            try:
                key = winreg.HKEY_CURRENT_USER
                subkey = r"Software\Microsoft\Windows\CurrentVersion\Run"
                registry_key = winreg.OpenKey(key, subkey, 0, winreg.KEY_SET_VALUE)
                try:
                    winreg.DeleteValue(registry_key, APP_NAME)
                except FileNotFoundError:
                    pass
                winreg.CloseKey(registry_key)
            except Exception as e:
                print(f"Error removing from startup: {e}")

class NetUsage(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.orientation = 'vertical'
        self.padding = dp(20)
        self.spacing = dp(15)
        self.refresh_interval = 5
        self.adapter_cards = {}
        self.last_update_time = time.time()

        # Set window properties
        Window.size = (600, 700)
        Window.minimum_width = 550
        Window.minimum_height = 650
        Window.clearcolor = (0.08, 0.08, 0.1, 1)
        
        self._create_header()
        self._create_overview()
        self._create_adapters_section()

    def _create_header(self):
        """Create header section"""
        header_card = ModernCard(orientation='vertical', size_hint_y=None, height=dp(100))
        
        # Top row with computer name and date
        top_row = BoxLayout(size_hint_y=None, height=dp(25))
        
        # Computer name
        computer_name = socket.gethostname()
        computer_label = Label(
            text=f"Computer: {computer_name}",
            font_size=dp(12),
            color=(0.3, 0.8, 1, 1),  # Bright blue color
            size_hint_x=None,
            width=dp(200),
            halign='left',
            bold=True
        )
        top_row.add_widget(computer_label)
        
        # Current date
        self.date_label = Label(
            text=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            font_size=dp(12),
            color=(0.9, 0.7, 0.3, 1),  # Golden yellow color
            size_hint_x=None,
            width=dp(200),
            halign='right',
            bold=True
        )
        top_row.add_widget(self.date_label)
        
        header_card.add_widget(top_row)
        
        # Middle row with title
        title_layout = BoxLayout(orientation='vertical', size_hint_y=None, height=dp(35))
        
        main_title = Label(
            text="Network Data Monitor",
            font_size=dp(22),
            bold=True,
            color=(1, 1, 1, 1),
            size_hint_y=None,
            height=dp(35)
        )
        title_layout.add_widget(main_title)
        
        header_card.add_widget(title_layout)
        
        # Bottom row with subtitle and buttons
        bottom_row = BoxLayout(size_hint_y=None, height=dp(30))
        
        subtitle = Label(
            text="Real-time network usage tracking",
            font_size=dp(12),
            color=(0.7, 0.7, 0.8, 1),
            halign='left'
        )
        bottom_row.add_widget(subtitle)
        
        # Control buttons
        controls = BoxLayout(size_hint_x=None, width=dp(280), spacing=dp(10))
        
        settings_btn = IconButton("Settings")
        settings_btn.background_color = (0.2, 0.6, 1.0, 1)  # Blue color
        settings_btn.bind(on_release=self.show_settings)
        controls.add_widget(settings_btn)
        
        refresh_btn = IconButton("Refresh")
        refresh_btn.background_color = (0.3, 0.7, 0.3, 1)  # Green color
        refresh_btn.bind(on_release=self.force_refresh)
        controls.add_widget(refresh_btn)
        
        if HAS_SYSTRAY:
            tray_btn = IconButton("Hide")
            tray_btn.background_color = (0.8, 0.3, 0.3, 1)  # Red color
            tray_btn.bind(on_release=self.minimize_to_tray)
            controls.add_widget(tray_btn)
        
        bottom_row.add_widget(controls)
        header_card.add_widget(bottom_row)
        
        self.add_widget(header_card)

    def _create_overview(self):
        """Create overview section"""
        overview_card = ModernCard(orientation='horizontal', size_hint_y=None, height=dp(90))
        
        # Total usage section
        total_section = BoxLayout(orientation='vertical')
        
        total_section.add_widget(Label(
            text="TOTAL DATA USAGE",
            font_size=dp(12),
            bold=True,
            color=(0.7, 0.7, 0.8, 1),
            size_hint_y=None,
            height=dp(25)
        ))
        
        self.total_label = Label(
            text="0.00 GB",
            font_size=dp(26),
            bold=True,
            color=(0.3, 0.9, 0.6, 1),
            size_hint_y=None,
            height=dp(40)
        )
        total_section.add_widget(self.total_label)
        
        overview_card.add_widget(total_section)
        
        # Stats section
        stats_section = BoxLayout(orientation='vertical')
        
        stats_section.add_widget(Label(
            text="STATUS & INFO",
            font_size=dp(12),
            bold=True,
            color=(0.7, 0.7, 0.8, 1),
            size_hint_y=None,
            height=dp(25)
        ))
        
        self.adapters_count = Label(
            text="0 network adapters",
            font_size=dp(13),
            color=(0.8, 0.8, 0.9, 1),
            size_hint_y=None,
            height=dp(20)
        )
        stats_section.add_widget(self.adapters_count)
        
        self.status_label = Label(
            text="Monitoring active",
            font_size=dp(11),
            color=(0.3, 0.8, 1, 1),
            size_hint_y=None,
            height=dp(20)
        )
        stats_section.add_widget(self.status_label)
        
        overview_card.add_widget(stats_section)
        self.add_widget(overview_card)

    def _create_adapters_section(self):
        """Create adapters section"""
        # Section header
        header_layout = BoxLayout(size_hint_y=None, height=dp(35))
        header_layout.add_widget(Label(
            text="NETWORK ADAPTERS",
            font_size=dp(16),
            bold=True,
            color=(0.9, 0.9, 1, 1),
            halign='left'
        ))
        self.add_widget(header_layout)
        
        # Scrollable adapters list
        self.scroll = ScrollView()
        self.adapters_layout = BoxLayout(
            orientation='vertical',
            spacing=dp(10),
            size_hint_y=None
        )
        self.adapters_layout.bind(minimum_height=self.adapters_layout.setter('height'))
        
        self.scroll.add_widget(self.adapters_layout)
        self.add_widget(self.scroll)
        
        # Start the update cycle
        Clock.schedule_interval(self.update_data, self.refresh_interval)
        # Update date every second
        Clock.schedule_interval(self.update_date, 1)

    def update_date(self, *args):
        """Update the date label"""
        self.date_label.text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def show_settings(self, *args):
        """Show settings popup"""
        popup = SettingsPopup(self)
        popup.open()

    def minimize_to_tray(self, *args):
        """Minimize to system tray"""
        if HAS_SYSTRAY and platform == 'win':
            Window.hide()
        else:
            App.get_running_app().stop()

    def force_refresh(self, *args):
        """Force data refresh - only update display, don't save to DB"""
        self.update_display_only()

    def update_display_only(self):
        """Update display without saving to database"""
        try:
            counters = psutil.net_io_counters(pernic=True)
            total_bytes = 0
            active_adapters = 0
            physical_adapters = get_physical_adapters()

            for adapter in physical_adapters:
                if adapter not in counters:
                    continue
                    
                active_adapters += 1
                current_stats = counters[adapter]
                
                # Get the stored total from database
                cur.execute("SELECT total_sent, total_recv FROM usage WHERE adapter=?", (adapter,))
                row = cur.fetchone()

                if row:
                    total_sent, total_recv = row
                else:
                    total_sent, total_recv = 0, 0

                total_bytes += total_sent + total_recv
                
                # Convert to display units
                sent_mb = total_sent / (1024**2)
                recv_mb = total_recv / (1024**2)
                total_gb = (total_sent + total_recv) / (1024**3)

                # Create or update adapter card
                if adapter not in self.adapter_cards:
                    card = AdapterCard(adapter)
                    self.adapter_cards[adapter] = card
                    self.adapters_layout.add_widget(card)
                
                # Update the card
                self.adapter_cards[adapter].update_stats(sent_mb, recv_mb, total_gb)

            # Update overview
            total_gb_all = total_bytes / (1024**3)
            self.total_label.text = f"{total_gb_all:.2f} GB"
            self.adapters_count.text = f"{active_adapters} network adapters"
            self.status_label.text = "Monitoring active"
            
            # Remove cards for disconnected adapters
            current_adapters = set(physical_adapters)
            old_adapters = set(self.adapter_cards.keys())
            
            for old_adapter in old_adapters - current_adapters:
                if old_adapter in self.adapter_cards:
                    self.adapters_layout.remove_widget(self.adapter_cards[old_adapter])
                    del self.adapter_cards[old_adapter]
                    
        except Exception as e:
            print(f"Error updating display: {e}")
            self.status_label.text = "Error updating data"

    def update_data(self, *args):
        """Update network data and save to database"""
        try:
            current_time = time.time()
            time_diff = current_time - self.last_update_time
            self.last_update_time = current_time
            
            counters = psutil.net_io_counters(pernic=True)
            total_bytes = 0
            active_adapters = 0
            physical_adapters = get_physical_adapters()

            for adapter in physical_adapters:
                if adapter not in counters:
                    continue
                    
                active_adapters += 1
                current_stats = counters[adapter]
                
                # Calculate usage from initial counters
                if adapter in initial_counters:
                    initial_stats = initial_counters[adapter]
                    sent = max(0, current_stats.bytes_sent - initial_stats['bytes_sent'])
                    recv = max(0, current_stats.bytes_recv - initial_stats['bytes_recv'])
                else:
                    sent, recv = current_stats.bytes_sent, current_stats.bytes_recv
                    initial_counters[adapter] = {
                        'bytes_sent': current_stats.bytes_sent,
                        'bytes_recv': current_stats.bytes_recv
                    }

                # Update database only if we have new data
                if sent > 0 or recv > 0:
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
                else:
                    # Just get the existing values
                    cur.execute("SELECT total_sent, total_recv FROM usage WHERE adapter=?", (adapter,))
                    row = cur.fetchone()
                    if row:
                        total_sent, total_recv = row
                    else:
                        total_sent, total_recv = 0, 0

                total_bytes += total_sent + total_recv
                
                # Convert to display units
                sent_mb = total_sent / (1024**2)
                recv_mb = total_recv / (1024**2)
                total_gb = (total_sent + total_recv) / (1024**3)

                # Create or update adapter card
                if adapter not in self.adapter_cards:
                    card = AdapterCard(adapter)
                    self.adapter_cards[adapter] = card
                    self.adapters_layout.add_widget(card)
                
                # Update the card
                self.adapter_cards[adapter].update_stats(sent_mb, recv_mb, total_gb)

            # Update overview
            total_gb_all = total_bytes / (1024**3)
            self.total_label.text = f"{total_gb_all:.2f} GB"
            self.adapters_count.text = f"{active_adapters} network adapters"
            self.status_label.text = "Monitoring active"

            conn.commit()
            
            # Remove cards for disconnected adapters
            current_adapters = set(physical_adapters)
            old_adapters = set(self.adapter_cards.keys())
            
            for old_adapter in old_adapters - current_adapters:
                if old_adapter in self.adapter_cards:
                    self.adapters_layout.remove_widget(self.adapter_cards[old_adapter])
                    del self.adapter_cards[old_adapter]
                    
        except Exception as e:
            print(f"Error updating data: {e}")
            self.status_label.text = "Error updating data"


class NetUsageApp(App):
    refresh_interval = NumericProperty(5)
    minimized = BooleanProperty(False)
    
    def build(self):
        self.title = "Network Data Monitor"
        self.icon = os.path.join(BASE_DIR, 'icon.png') if os.path.exists(os.path.join(BASE_DIR, 'icon.png')) else None
        
        # Check if we should start minimized
        if '--minimized' in sys.argv:
            self.minimized = True
            Clock.schedule_once(self.minimize_to_tray, 0.1)
        
        return NetUsage()

    def on_stop(self):
        """Save settings when app closes"""
        try:
            if not Config.has_section('netusage'):
                Config.add_section('netusage')
            
            Config.set('netusage', 'refresh_interval', str(self.root.refresh_interval))
            Config.write()
        except Exception as e:
            print(f"Error saving config: {e}")

    def minimize_to_tray(self, dt):
        """Minimize the app to system tray"""
        if HAS_SYSTRAY and platform == 'win':
            Window.hide()
        else:
            self.stop()


if __name__ == "__main__":
    # Check if we should start minimized
    if '--minimized' in sys.argv:
        start_minimized = True
    
    # Initialize and run the app
    try:
        app = NetUsageApp()
        app.run()
    except Exception as e:
        print(f"Error starting app: {e}")
        input("Press Enter to exit...")