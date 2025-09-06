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
from kivy.uix.progressbar import ProgressBar
from kivy.graphics import Color, Rectangle, RoundedRectangle, Line, Ellipse
from kivy.utils import platform
from kivy.config import Config
from kivy.core.clipboard import Clipboard
from kivy.properties import BooleanProperty, NumericProperty, StringProperty
from kivy.metrics import dp
from kivy.lang import Builder
from kivy.animation import Animation
from kivy.uix.widget import Widget

# Configure Kivy for better rendering
Config.set('graphics', 'multisamples', '0')

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
            initial_counters[adapter] = counters[adapter]

# Initialize counters on startup
init_counters()

# Kivy KV string for better styling
KV_STRING = '''
<ModernButton>:
    canvas.before:
        Color:
            rgba: 0.2, 0.6, 1.0, 1 if self.state == 'normal' else (0.15, 0.45, 0.8, 1)
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [15]
    color: 1, 1, 1, 1
    font_size: 16
    bold: True

<IconButton>:
    canvas.before:
        Color:
            rgba: 0.15, 0.15, 0.2, 0.9
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [self.height/2]
    color: 0.9, 0.9, 1, 1
    font_size: 20
    bold: True

<GlassCard>:
    canvas.before:
        Color:
            rgba: 0.12, 0.12, 0.15, 0.85
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [20]
        Color:
            rgba: 0.3, 0.3, 0.4, 0.3
        Line:
            rounded_rectangle: self.x, self.y, self.width, self.height, 20
            width: 1

<ModernLabel>:
    color: 0.9, 0.9, 0.9, 1
    font_size: 16
    text_size: self.width, None
    halign: 'left'
    valign: 'middle'
'''

Builder.load_string(KV_STRING)

class ModernButton(Button):
    """Modern styled button"""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.background_normal = ''
        self.background_down = ''
        self.size_hint_y = None
        self.height = dp(50)

class IconButton(Button):
    """Icon-style button"""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.background_normal = ''
        self.background_down = ''
        self.size_hint = (None, None)
        self.size = (dp(60), dp(60))

class GlassCard(BoxLayout):
    """Modern glass-morphism card widget"""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.padding = dp(20)
        self.spacing = dp(10)

class ModernLabel(Label):
    """Modern styled label"""
    pass

class SimpleChart(Widget):
    """Simple data visualization widget"""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.size_hint_y = None
        self.height = dp(80)
        self.data_points = []
        self.max_points = 30
        
    def add_data_point(self, value):
        """Add new data point and redraw"""
        self.data_points.append(float(value))
        if len(self.data_points) > self.max_points:
            self.data_points.pop(0)
        self.redraw()
        
    def redraw(self):
        """Redraw the chart"""
        self.canvas.clear()
        if len(self.data_points) < 2:
            return
            
        with self.canvas:
            # Chart background
            Color(0.08, 0.08, 0.12, 0.8)
            Rectangle(pos=self.pos, size=self.size)
            
            # Chart line
            Color(0.2, 0.8, 0.6, 1)
            max_val = max(self.data_points) if max(self.data_points) > 0 else 1
            
            points = []
            for i, val in enumerate(self.data_points):
                x = self.x + (i / (len(self.data_points) - 1)) * self.width
                y = self.y + (val / max_val) * self.height * 0.8 + self.height * 0.1
                points.extend([x, y])
            
            if len(points) >= 4:
                Line(points=points, width=2)

class AdapterCard(GlassCard):
    """Enhanced adapter card"""
    def __init__(self, adapter_name, **kwargs):
        super().__init__(**kwargs)
        self.adapter_name = adapter_name
        self.size_hint_y = None
        self.height = dp(200)
        self.orientation = 'vertical'
        
        # Header
        header = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(10))
        
        # Network icon
        icon_text = "📶" if any(x in adapter_name.lower() for x in ["wi-fi", "wireless", "wifi"]) else "🔌"
        icon_label = Label(
            text=icon_text,
            font_size=dp(24),
            size_hint_x=None,
            width=dp(40),
            color=(0.2, 0.8, 1, 1)
        )
        header.add_widget(icon_label)
        
        # Adapter name
        name_label = Label(
            text=adapter_name[:25] + "..." if len(adapter_name) > 25 else adapter_name,
            font_size=dp(16),
            bold=True,
            color=(0.9, 0.9, 1, 1),
            text_size=(None, None),
            halign='left'
        )
        header.add_widget(name_label)
        
        self.add_widget(header)
        
        # Stats row
        stats_row = BoxLayout(size_hint_y=None, height=dp(60), spacing=dp(20))
        
        # Upload stats
        upload_box = BoxLayout(orientation='vertical', spacing=dp(5))
        upload_box.add_widget(Label(
            text="⬆ Upload",
            font_size=dp(12),
            color=(0.7, 0.7, 0.8, 1),
            size_hint_y=None,
            height=dp(20)
        ))
        self.upload_label = Label(
            text="0 MB",
            font_size=dp(14),
            bold=True,
            color=(1, 0.4, 0.4, 1),
            size_hint_y=None,
            height=dp(25)
        )
        upload_box.add_widget(self.upload_label)
        stats_row.add_widget(upload_box)
        
        # Download stats
        download_box = BoxLayout(orientation='vertical', spacing=dp(5))
        download_box.add_widget(Label(
            text="⬇ Download",
            font_size=dp(12),
            color=(0.7, 0.7, 0.8, 1),
            size_hint_y=None,
            height=dp(20)
        ))
        self.download_label = Label(
            text="0 MB",
            font_size=dp(14),
            bold=True,
            color=(0.4, 1, 0.4, 1),
            size_hint_y=None,
            height=dp(25)
        )
        download_box.add_widget(self.download_label)
        stats_row.add_widget(download_box)
        
        self.add_widget(stats_row)
        
        # Total usage
        total_box = BoxLayout(orientation='vertical', spacing=dp(5))
        total_box.add_widget(Label(
            text="📊 Total Usage",
            font_size=dp(12),
            color=(0.7, 0.7, 0.8, 1),
            size_hint_y=None,
            height=dp(20)
        ))
        
        self.total_label = Label(
            text="0.00 GB",
            font_size=dp(18),
            bold=True,
            color=(0.2, 0.9, 0.6, 1),
            size_hint_y=None,
            height=dp(30)
        )
        total_box.add_widget(self.total_label)
        
        # Progress bar
        self.progress = ProgressBar(
            max=1000,
            size_hint_y=None,
            height=dp(8)
        )
        # Style the progress bar
        with self.progress.canvas.before:
            Color(0.2, 0.2, 0.3, 1)
            self.progress_bg = Rectangle(pos=self.progress.pos, size=self.progress.size)
        self.progress.bind(pos=self.update_progress_bg, size=self.update_progress_bg)
        
        total_box.add_widget(self.progress)
        self.add_widget(total_box)
        
        # Simple chart
        self.chart = SimpleChart()
        self.add_widget(self.chart)
    
    def update_progress_bg(self, *args):
        self.progress_bg.pos = self.progress.pos
        self.progress_bg.size = self.progress.size
    
    def update_stats(self, sent_mb, recv_mb, total_gb):
        """Update card statistics"""
        self.upload_label.text = f"{sent_mb:.1f} MB"
        self.download_label.text = f"{recv_mb:.1f} MB"
        self.total_label.text = f"{total_gb:.2f} GB"
        
        # Update progress (scale for visual effect)
        self.progress.value = min(total_gb * 50, 1000)
        
        # Add data point to chart
        self.chart.add_data_point(total_gb)

class SettingsPopup(Popup):
    """Enhanced settings popup"""
    def __init__(self, main_app, **kwargs):
        super().__init__(**kwargs)
        self.main_app = main_app
        self.title = "Settings & Configuration"
        self.title_size = dp(20)
        self.title_color = (1, 1, 1, 1)
        self.size_hint = (0.8, 0.7)
        self.separator_color = (0.2, 0.6, 0.9, 1)
        self.separator_height = dp(2)
        
        # Main layout
        main_layout = BoxLayout(orientation='vertical', padding=dp(20), spacing=dp(20))
        
        # Refresh interval section
        refresh_card = GlassCard(orientation='vertical', size_hint_y=None, height=dp(120))
        refresh_card.add_widget(Label(
            text="🔄 Refresh Interval",
            font_size=dp(18),
            bold=True,
            color=(0.2, 0.8, 1, 1),
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
        
        # Startup section
        startup_card = GlassCard(orientation='vertical', size_hint_y=None, height=dp(100))
        startup_card.add_widget(Label(
            text="🚀 Windows Startup",
            font_size=dp(18),
            bold=True,
            color=(0.2, 0.8, 1, 1),
            size_hint_y=None,
            height=dp(40)
        ))
        
        self.startup_toggle = ToggleButton(
            text="Start with Windows",
            state='normal',
            size_hint_y=None,
            height=dp(40),
            background_normal='',
            background_down=''
        )
        
        # Custom styling for toggle
        with self.startup_toggle.canvas.before:
            Color(0.3, 0.3, 0.4, 1)
            self.startup_bg = RoundedRectangle(
                pos=self.startup_toggle.pos,
                size=self.startup_toggle.size,
                radius=[dp(10)]
            )
        
        self.startup_toggle.bind(
            pos=self.update_startup_bg,
            size=self.update_startup_bg,
            state=self.on_startup_toggle
        )
        
        startup_card.add_widget(self.startup_toggle)
        main_layout.add_widget(startup_card)
        
        # Database info
        db_card = GlassCard(orientation='vertical', size_hint_y=None, height=dp(80))
        db_card.add_widget(Label(
            text="💾 Data Storage",
            font_size=dp(16),
            bold=True,
            color=(0.2, 0.8, 1, 1),
            size_hint_y=None,
            height=dp(30)
        ))
        
        db_info = Label(
            text=f"Database: {os.path.basename(DB_FILE)}",
            font_size=dp(12),
            color=(0.7, 0.7, 0.8, 1),
            size_hint_y=None,
            height=dp(30)
        )
        db_card.add_widget(db_info)
        main_layout.add_widget(db_card)
        
        # Check startup status
        self.check_startup_status()
        
        # Action buttons
        button_layout = BoxLayout(size_hint_y=None, height=dp(60), spacing=dp(15))
        
        reset_btn = ModernButton(text="🔄 Reset Data")
        reset_btn.bind(on_release=self.reset_data)
        button_layout.add_widget(reset_btn)
        
        close_btn = ModernButton(text="✓ Save & Close")
        close_btn.bind(on_release=self.dismiss)
        button_layout.add_widget(close_btn)
        
        main_layout.add_widget(button_layout)
        self.content = main_layout
    
    def update_startup_bg(self, *args):
        self.startup_bg.pos = self.startup_toggle.pos
        self.startup_bg.size = self.startup_toggle.size
        
        # Change color based on state
        if self.startup_toggle.state == 'down':
            self.startup_toggle.canvas.before.children[0].rgba = (0.2, 0.7, 0.3, 1)
        else:
            self.startup_toggle.canvas.before.children[0].rgba = (0.3, 0.3, 0.4, 1)
    
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
                except FileNotFoundError:
                    self.startup_toggle.state = 'normal'
                winreg.CloseKey(registry_key)
            except Exception:
                self.startup_toggle.state = 'normal'
        
        self.update_startup_bg()
    
    def on_slider_change(self, instance, value):
        self.interval_label.text = f"Update every {int(value)} seconds"
        self.main_app.refresh_interval = int(value)
    
    def on_startup_toggle(self, instance, value):
        if platform == 'win':
            if value == 'down':
                self.add_to_startup()
            else:
                self.remove_from_startup()
        self.update_startup_bg()
    
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

        # Set window properties
        Window.size = (650, 800)
        Window.minimum_width = 600
        Window.minimum_height = 700
        Window.clearcolor = (0.05, 0.05, 0.08, 1)
        
        self._create_header()
        self._create_overview()
        self._create_adapters_section()

    def _create_header(self):
        """Create header section"""
        header_card = GlassCard(orientation='horizontal', size_hint_y=None, height=dp(80))
        
        # Title section
        title_layout = BoxLayout(orientation='vertical', spacing=dp(5))
        
        main_title = Label(
            text="🌐 Network Monitor",
            font_size=dp(24),
            bold=True,
            color=(1, 1, 1, 1),
            size_hint_y=None,
            height=dp(35)
        )
        title_layout.add_widget(main_title)
        
        subtitle = Label(
            text="Real-time data usage tracking",
            font_size=dp(12),
            color=(0.7, 0.7, 0.8, 1),
            size_hint_y=None,
            height=dp(20)
        )
        title_layout.add_widget(subtitle)
        
        header_card.add_widget(title_layout)
        
        # Control buttons
        controls = BoxLayout(size_hint_x=None, width=dp(200), spacing=dp(10))
        
        settings_btn = IconButton(text="⚙")
        settings_btn.bind(on_release=self.show_settings)
        controls.add_widget(settings_btn)
        
        refresh_btn = IconButton(text="🔄")
        refresh_btn.bind(on_release=self.force_refresh)
        controls.add_widget(refresh_btn)
        
        if HAS_SYSTRAY:
            tray_btn = IconButton(text="➖")
            tray_btn.bind(on_release=self.minimize_to_tray)
            controls.add_widget(tray_btn)
        
        header_card.add_widget(controls)
        self.add_widget(header_card)

    def _create_overview(self):
        """Create overview section"""
        overview_card = GlassCard(orientation='horizontal', size_hint_y=None, height=dp(100))
        
        # Total usage
        total_section = BoxLayout(orientation='vertical', spacing=dp(5))
        total_section.add_widget(Label(
            text="📊 TOTAL USAGE",
            font_size=dp(14),
            bold=True,
            color=(0.7, 0.7, 0.8, 1),
            size_hint_y=None,
            height=dp(25)
        ))
        
        self.total_label = Label(
            text="0.00 GB",
            font_size=dp(28),
            bold=True,
            color=(0.2, 0.9, 0.6, 1),
            size_hint_y=None,
            height=dp(40)
        )
        total_section.add_widget(self.total_label)
        
        overview_card.add_widget(total_section)
        
        # Stats section
        stats_section = BoxLayout(orientation='vertical', spacing=dp(5))
        
        stats_section.add_widget(Label(
            text="📈 STATISTICS",
            font_size=dp(14),
            bold=True,
            color=(0.7, 0.7, 0.8, 1),
            size_hint_y=None,
            height=dp(25)
        ))
        
        self.adapters_count = Label(
            text="🔌 0 adapters",
            font_size=dp(14),
            color=(0.8, 0.8, 0.9, 1),
            size_hint_y=None,
            height=dp(20)
        )
        stats_section.add_widget(self.adapters_count)
        
        self.status_label = Label(
            text="🟢 Active monitoring",
            font_size=dp(12),
            color=(0.2, 0.8, 1, 1),
            size_hint_y=None,
            height=dp(20)
        )
        stats_section.add_widget(self.status_label)
        
        overview_card.add_widget(stats_section)
        self.add_widget(overview_card)

    def _create_adapters_section(self):
        """Create adapters section"""
        # Section header
        header_layout = BoxLayout(size_hint_y=None, height=dp(40))
        header_layout.add_widget(Label(
            text="🌐 NETWORK ADAPTERS",
            font_size=dp(18),
            bold=True,
            color=(0.9, 0.9, 1, 1),
            halign='left'
        ))
        self.add_widget(header_layout)
        
        # Scrollable adapters
        self.scroll = ScrollView()
        self.adapters_layout = BoxLayout(
            orientation='vertical',
            spacing=dp(15),
            size_hint_y=None
        )
        self.adapters_layout.bind(minimum_height=self.adapters_layout.setter('height'))
        
        self.scroll.add_widget(self.adapters_layout)
        self.add_widget(self.scroll)
        
        # Start updates
        Clock.schedule_interval(self.update_data, self.refresh_interval)

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
        """Force data refresh"""
        self.update_data()

    def update_data(self, *args):
        """Update network data"""
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
                
                # Calculate usage from initial counters
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
            self.adapters_count.text = f"🔌 {active_adapters} adapters"
            self.status_label.text = "🟢 Active monitoring"

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
            self.status_label.text = "🔴 Error updating"


class NetUsageApp(App):
    refresh_interval = NumericProperty(5)
    minimized = BooleanProperty(False)
    
    def build(self):
        self.title = "Network Monitor Dashboard"
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