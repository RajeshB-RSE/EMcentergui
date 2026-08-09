"""
EMControl GUI (customtkinter build)
====================================

Standalone customtkinter app to control an ETS-Lindgren EMCenter chassis
(mast/turntable positioner cards only -- no scanning, no instruments).

Built on customtkinter instead of PySide6 because customtkinter only
needs itself + darkdetect + packaging (all pure Python, tiny wheels) --
much easier to install on an air-gapped machine from a local wheel
folder than PySide6, which needs the much larger PySide6-Essentials
and PySide6-Addons wheels on top of the wrapper package.

- Enter the chassis IP, click Connect (last-used IP is remembered).
- Connection indicator glows green + shows "Connected successfully"
  once *IDN? responds.
- Each configured axis (mast, turntable, ...) gets its own panel with
  one-click preset buttons, a manual move field, a speed box (S1-S8),
  and a Scan button that sweeps between the axis's configured hard
  limits (with a confirmation prompt first).
- The position readout turns red if a polled position is outside the
  axis's configured hard limits.

Two files live in the user's Application Support folder (NOT inside
the app bundle, so they survive updates and are easy to hand-edit):

  ~/Library/Application Support/EMCenter/config.json
      Axes, presets, hard limits, default speed -- seeded from the
      bundled config.json on first run, then always loaded/edited
      from here after that.

  ~/Library/Application Support/EMCenter/settings.json
      Auto-saved runtime state: last-used IP, last speed per axis.

Author: Rajesh (GUI scaffolding by Claude)
"""

import sys
import json
import os
import logging
import platform

import customtkinter as ctk
from tkinter import messagebox

from EMCenter import EMCenter, EMCenterError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("EMControlGUI")

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")

APP_VERSION = "1.0.0"

BG_COLOR = "#EEF1F4"       # app background
CARD_COLOR = "#FFFFFF"     # panel/card background (axis boxes, log, connection bar)

# ------------------------------------------------------------
# Persistent, user-editable/writable files
# ------------------------------------------------------------

APP_SUPPORT_DIR = os.path.join(
    os.path.expanduser("~"), "Library", "Application Support", "EMCenter"
)
USER_CONFIG_PATH = os.path.join(APP_SUPPORT_DIR, "config.json")
SETTINGS_PATH = os.path.join(APP_SUPPORT_DIR, "settings.json")


def _app_support_dir():
    if platform.system() == "Windows":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
        return os.path.join(base, "EMCenter")
    return os.path.join(os.path.expanduser("~"), "Library", "Application Support", "EMCenter")

APP_SUPPORT_DIR = _app_support_dir()
def bundled_resource_path(filename):
    """Find a file bundled alongside the script/app, whether running
    as a script or a frozen PyInstaller app."""
    if getattr(sys, "frozen", False):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, filename)


def ensure_user_config():
    """Seed ~/Library/Application Support/EMCenter/config.json from the
    bundled default the first time the app runs. After that, the user
    copy is always what's loaded/edited -- editing the bundled one
    inside a packaged .app wouldn't persist across relaunches."""
    os.makedirs(APP_SUPPORT_DIR, exist_ok=True)
    if not os.path.exists(USER_CONFIG_PATH):
        with open(bundled_resource_path("config.json"), "r") as f:
            default_content = f.read()
        with open(USER_CONFIG_PATH, "w") as f:
            f.write(default_content)
        logger.info("Seeded default config at %s", USER_CONFIG_PATH)


def load_config():
    ensure_user_config()
    with open(USER_CONFIG_PATH, "r") as f:
        return json.load(f)


def load_settings():
    if os.path.exists(SETTINGS_PATH):
        try:
            with open(SETTINGS_PATH, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Could not read settings.json (%s) -- starting fresh", e)
    return {}


def save_settings(settings):
    os.makedirs(APP_SUPPORT_DIR, exist_ok=True)
    try:
        with open(SETTINGS_PATH, "w") as f:
            json.dump(settings, f, indent=2)
    except OSError as e:
        logger.warning("Could not save settings.json: %s", e)


class StatusDot(ctk.CTkLabel):
    """Small colored circle indicator (faked with a rounded-corner
    label sized to a square)."""

    def __init__(self, master):
        super().__init__(master, text="", width=15, height=15, corner_radius=8,
                          fg_color="grey")

    def set_color(self, color):
        self.configure(fg_color=color)


class AxisPanel(ctk.CTkFrame):
    """One panel per axis: position readout, manual move, presets,
    speed box, jog/stop, and limit-to-limit scan."""

    def __init__(self, master, axis_cfg, get_em, log_fn, initial_speed, save_speed_fn):
        super().__init__(master, corner_radius=9, fg_color=CARD_COLOR)
        self.cfg = axis_cfg
        self.slot = axis_cfg["slot"]
        self.device = axis_cfg["device"]
        self.kind = axis_cfg["kind"]  # "tower" or "turntable"
        self.unit = axis_cfg.get("unit", "")
        self.low_limit = axis_cfg.get("low_limit")
        self.high_limit = axis_cfg.get("high_limit")
        self.home = axis_cfg.get("home", self.low_limit)
        self.scan_cycles = axis_cfg.get("scan_cycles", 999)
        self.axis_key = f"{self.slot}{self.device}"
        self.get_em = get_em  # callable -> EMCenter instance or None
        self.log = log_fn
        self.save_speed_fn = save_speed_fn
        self.scanning = False

        title = ctk.CTkLabel(self, text=axis_cfg["name"],
                              font=ctk.CTkFont(size=13, weight="bold"))
        title.grid(row=0, column=0, columnspan=6, sticky="w", padx=8, pady=(6, 1))

        self.pos_label = ctk.CTkLabel(self, text="Position: -- ",
                                       font=ctk.CTkFont(size=12, weight="bold"))
        self.pos_label.grid(row=1, column=0, columnspan=6, sticky="w", padx=8)
        self.default_pos_color = self.pos_label.cget("text_color")

        if self.low_limit is not None and self.high_limit is not None:
            limit_text = f"Hard limits: {self.low_limit}-{self.high_limit}{self.unit}"
        else:
            limit_text = "Hard limits: not set"
        self.limit_label = ctk.CTkLabel(self, text=limit_text, text_color="gray60",
                                         font=ctk.CTkFont(size=10))
        self.limit_label.grid(row=2, column=0, columnspan=6, sticky="w", padx=8)

        # -- preset buttons --
        preset_row = ctk.CTkFrame(self, fg_color="transparent")
        preset_row.grid(row=3, column=0, columnspan=6, sticky="w", padx=4, pady=4)
        for i, val in enumerate(axis_cfg.get("presets", [])):
            btn = ctk.CTkButton(
                preset_row, text=f"Move {val}{self.unit}", width=90, height=26,
                font=ctk.CTkFont(size=11),
                command=lambda v=val: self.move_to(v),
            )
            btn.grid(row=0, column=i, padx=3)

        # -- manual move --
        manual_row = ctk.CTkFrame(self, fg_color="transparent")
        manual_row.grid(row=4, column=0, columnspan=6, sticky="w", padx=4, pady=(0, 4))
        ctk.CTkLabel(manual_row, text="Manual:", font=ctk.CTkFont(size=11)).grid(
            row=0, column=0, padx=(4, 2))
        self.manual_entry = ctk.CTkEntry(manual_row, width=70, height=26,
                                          placeholder_text=self.unit)
        self.manual_entry.grid(row=0, column=1, padx=3)
        manual_move_btn = ctk.CTkButton(manual_row, text="Move", width=55, height=26,
                                         font=ctk.CTkFont(size=11),
                                         command=self.move_to_manual)
        manual_move_btn.grid(row=0, column=2, padx=3)

        # -- speed --
        ctk.CTkLabel(manual_row, text="Speed:", font=ctk.CTkFont(size=11)).grid(
            row=0, column=3, padx=(12, 2))
        self.speed_entry = ctk.CTkEntry(manual_row, width=50, height=26,
                                         placeholder_text="S1-S8")
        self.speed_entry.insert(0, f"S{initial_speed}")
        self.speed_entry.grid(row=0, column=4, padx=3)
        speed_btn = ctk.CTkButton(manual_row, text="Set", width=45, height=26,
                                   font=ctk.CTkFont(size=11),
                                   command=self.set_speed_from_entry)
        speed_btn.grid(row=0, column=5, padx=3)

        # -- jog / stop / scan --
        control_row = ctk.CTkFrame(self, fg_color="transparent")
        control_row.grid(row=5, column=0, columnspan=6, sticky="w", padx=4, pady=(0, 6))
        if self.kind == "turntable":
            up_label, dn_label = "CW", "CCW"
        else:
            up_label, dn_label = "UP", "DOWN"

        jog_dn = ctk.CTkButton(control_row, text=dn_label, width=55, height=26,
                                font=ctk.CTkFont(size=11), command=self.jog_down)
        jog_dn.grid(row=0, column=0, padx=3)
        jog_up = ctk.CTkButton(control_row, text=up_label, width=55, height=26,
                                font=ctk.CTkFont(size=11), command=self.jog_up)
        jog_up.grid(row=0, column=1, padx=3)
        stop_btn = ctk.CTkButton(control_row, text="STOP", width=55, height=26,
                                  font=ctk.CTkFont(size=11),
                                  fg_color="#c0392b", hover_color="#992d22",
                                  command=self.stop_axis)
        stop_btn.grid(row=0, column=2, padx=3)

        self.scan_btn = ctk.CTkButton(control_row, text="Scan", width=75, height=26,
                                       font=ctk.CTkFont(size=11),
                                       fg_color="#8e44ad", hover_color="#6c3483",
                                       command=self.toggle_scan)
        self.scan_btn.grid(row=0, column=3, padx=(10, 3))
        if self.low_limit is None or self.high_limit is None:
            self.scan_btn.configure(state="disabled")

        # -- polarization (towers only) --
        self.pol_label = None
        if self.kind == "tower":
            v_btn = ctk.CTkButton(control_row, text="V", width=32, height=26,
                                   font=ctk.CTkFont(size=11),
                                   fg_color="#16697a", hover_color="#0f4c58",
                                   command=self.set_vertical)
            v_btn.grid(row=0, column=4, padx=(10, 2))
            h_btn = ctk.CTkButton(control_row, text="H", width=32, height=26,
                                   font=ctk.CTkFont(size=11),
                                   fg_color="#16697a", hover_color="#0f4c58",
                                   command=self.set_horizontal)
            h_btn.grid(row=0, column=5, padx=2)
            self.pol_label = ctk.CTkLabel(control_row, text="Pol: --",
                                           font=ctk.CTkFont(size=11))
            self.pol_label.grid(row=0, column=6, padx=(8, 3))

    # -- polarization actions (towers only) --

    def set_vertical(self):
        em = self._em_or_warn()
        if not em:
            return
        try:
            em.vertical(self.slot, self.device)
            self.log(f"[{self.cfg['name']}] Set to VERTICAL.")
        except EMCenterError as e:
            self.log(f"[{self.cfg['name']}] Failed to set vertical: {e}")

    def set_horizontal(self):
        em = self._em_or_warn()
        if not em:
            return
        try:
            em.horizontal(self.slot, self.device)
            self.log(f"[{self.cfg['name']}] Set to HORIZONTAL.")
        except EMCenterError as e:
            self.log(f"[{self.cfg['name']}] Failed to set horizontal: {e}")

    def refresh_polarization(self):
        if self.pol_label is None:
            return
        em = self.get_em()
        if em is None or not em.is_connected():
            return
        try:
            pol = em.polarization(self.slot, self.device)
            self.pol_label.configure(text=f"Pol: {pol[:1]}")  # "V" or "H"
        except EMCenterError:
            pass  # transient poll error -- don't spam the log

    # -- actions --

    def _em_or_warn(self):
        em = self.get_em()
        if em is None or not em.is_connected():
            self.log(f"[{self.cfg['name']}] Not connected -- connect first.")
            return None
        return em

    def _clamp_to_limits(self, value):
        if self.low_limit is not None and value < self.low_limit:
            self.log(f"[{self.cfg['name']}] {value}{self.unit} below low limit "
                      f"{self.low_limit}{self.unit} -- clamped.")
            return self.low_limit
        if self.high_limit is not None and value > self.high_limit:
            self.log(f"[{self.cfg['name']}] {value}{self.unit} above high limit "
                      f"{self.high_limit}{self.unit} -- clamped.")
            return self.high_limit
        return value

    def move_to_manual(self):
        text = self.manual_entry.get().strip()
        if not text:
            return
        try:
            value = float(text)
        except ValueError:
            self.log(f"[{self.cfg['name']}] Invalid manual value: '{text}'")
            return
        self.move_to(value)

    def home_axis(self):
        if self.home is None:
            self.log(f"[{self.cfg['name']}] No home position configured -- skipped.")
            return
        self.move_to(self.home)

    def move_to(self, value):
        em = self._em_or_warn()
        if not em:
            return
        value = self._clamp_to_limits(value)
        try:
            ok = em.seek(self.slot, self.device, value)
            self.log(f"[{self.cfg['name']}] Seek to {value}{self.unit} -> "
                      f"{'OK' if ok else 'NOT OK'}")
        except EMCenterError as e:
            self.log(f"[{self.cfg['name']}] Move failed: {e}")

    def jog_up(self):
        em = self._em_or_warn()
        if not em:
            return
        try:
            if self.kind == "turntable":
                em.clockwise(self.slot, self.device)
            else:
                em.jog_up(self.slot, self.device)
        except EMCenterError as e:
            self.log(f"[{self.cfg['name']}] Jog failed: {e}")

    def jog_down(self):
        em = self._em_or_warn()
        if not em:
            return
        try:
            if self.kind == "turntable":
                em.counter_clockwise(self.slot, self.device)
            else:
                em.jog_down(self.slot, self.device)
        except EMCenterError as e:
            self.log(f"[{self.cfg['name']}] Jog failed: {e}")

    def stop_axis(self):
        em = self._em_or_warn()
        if not em:
            return
        try:
            em.stop(self.slot, self.device)
            self.log(f"[{self.cfg['name']}] STOP sent.")
        except EMCenterError as e:
            self.log(f"[{self.cfg['name']}] Stop failed: {e}")
        if self.scanning:
            self.scanning = False
            self.scan_btn.configure(text="Scan", fg_color="#8e44ad", hover_color="#6c3483")

    # -- speed --

    def _parse_speed(self, text):
        """Accepts 'S1'..'S8' or plain '1'..'8'. Returns int 1-8 or None."""
        cleaned = text.strip().upper().lstrip("S")
        try:
            value = int(cleaned)
        except ValueError:
            return None
        if 1 <= value <= 8:
            return value
        return None

    def set_speed_from_entry(self):
        text = self.speed_entry.get()
        preset = self._parse_speed(text)
        if preset is None:
            messagebox.showwarning(
                "EMControl", "User input speed range is S1-S8."
            )
            return
        self.speed_entry.delete(0, "end")
        self.speed_entry.insert(0, f"S{preset}")
        self.save_speed_fn(self.axis_key, preset)
        em = self.get_em()
        if em and em.is_connected():
            try:
                em.set_speed(self.slot, self.device, preset)
                self.log(f"[{self.cfg['name']}] Speed set to S{preset}.")
            except EMCenterError as e:
                self.log(f"[{self.cfg['name']}] Failed to set speed: {e}")
        else:
            self.log(f"[{self.cfg['name']}] Speed S{preset} saved -- "
                      f"will apply on connect.")

    def apply_saved_speed(self):
        """Called right after a successful connection to push whatever
        speed is currently shown in the box to the card."""
        em = self.get_em()
        if not em or not em.is_connected():
            return
        preset = self._parse_speed(self.speed_entry.get())
        if preset is None:
            return
        try:
            em.set_speed(self.slot, self.device, preset)
            self.log(f"[{self.cfg['name']}] Applied saved speed S{preset}.")
        except EMCenterError as e:
            self.log(f"[{self.cfg['name']}] Failed to apply saved speed: {e}")

    # -- scan --

    def toggle_scan(self):
        if self.scanning:
            self.stop_scan()
        else:
            self.start_scan()

    def start_scan(self):
        em = self._em_or_warn()
        if not em:
            return
        if self.low_limit is None or self.high_limit is None:
            self.log(f"[{self.cfg['name']}] No hard limits set in config.json -- "
                      f"can't scan.")
            return

        confirmed = messagebox.askyesno(
            "Confirm Scan",
            f"Start scan on {self.cfg['name']}?\n\n"
            f"Range: {self.low_limit}{self.unit} <-> {self.high_limit}{self.unit}\n"
            f"Cycles: {self.scan_cycles}",
        )
        if not confirmed:
            self.log(f"[{self.cfg['name']}] Scan cancelled by user.")
            return

        try:
            # Push the configured hard limits to the card, set cycle
            # count, then trigger the card's own limit-to-limit scan
            # (LL/UL + CY + SC commands) -- this runs on the
            # controller itself, not a software loop.
            em.set_limits(self.slot, self.device, self.low_limit, self.high_limit)
            em.set_scan_cycles(self.slot, self.device, self.scan_cycles)
            em.scan(self.slot, self.device)
            self.scanning = True
            self.scan_btn.configure(text="Stop Scan", fg_color="#c0392b",
                                     hover_color="#992d22")
            self.log(f"[{self.cfg['name']}] Scan started: "
                      f"{self.low_limit}-{self.high_limit}{self.unit}, "
                      f"{self.scan_cycles} cycles.")
        except EMCenterError as e:
            self.log(f"[{self.cfg['name']}] Scan failed to start: {e}")

    def stop_scan(self):
        em = self._em_or_warn()
        if em:
            try:
                em.stop(self.slot, self.device)
            except EMCenterError as e:
                self.log(f"[{self.cfg['name']}] Stop failed: {e}")
        self.scanning = False
        self.scan_btn.configure(text="Scan", fg_color="#8e44ad", hover_color="#6c3483")
        self.log(f"[{self.cfg['name']}] Scan stopped.")

    # -- polling --

    def refresh_position(self):
        em = self.get_em()
        if em is None or not em.is_connected():
            return
        try:
            pos = em.position(self.slot, self.device)
            out_of_range = (
                (self.low_limit is not None and pos < self.low_limit) or
                (self.high_limit is not None and pos > self.high_limit)
            )
            if out_of_range:
                self.pos_label.configure(
                    text=f"Position: {pos:.1f} {self.unit}  \u26a0 OUT OF LIMITS",
                    text_color="#e74c3c",
                )
            else:
                self.pos_label.configure(
                    text=f"Position: {pos:.1f} {self.unit}",
                    text_color=self.default_pos_color,
                )
        except EMCenterError:
            pass  # transient poll error -- don't spam the log

    def refresh(self):
        """Called once per poll tick -- refreshes position and,
        for towers, polarization."""
        self.refresh_position()
        self.refresh_polarization()


class MainWindow(ctk.CTk):
    def __init__(self, config, settings):
        super().__init__()
        self.config_data = config
        self.settings = settings
        self.em = None

        self.title(f"EMControl v{APP_VERSION}")
        self.geometry("860x670")
        self.configure(fg_color=BG_COLOR)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # ---------------- Connection bar ----------------
        conn_box = ctk.CTkFrame(self, corner_radius=9, fg_color=CARD_COLOR)
        conn_box.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 5))

        ctk.CTkLabel(conn_box, text="IP:").grid(row=0, column=0, padx=(8, 3), pady=8)
        self.ip_entry = ctk.CTkEntry(conn_box, width=150, height=28)
        last_ip = self.settings.get("last_ip") or config.get("default_ip", "")
        self.ip_entry.insert(0, last_ip)
        self.ip_entry.grid(row=0, column=1, padx=3, pady=8)

        self.connect_btn = ctk.CTkButton(conn_box, text="Connect", width=90, height=28,
                                          command=self.toggle_connection)
        self.connect_btn.grid(row=0, column=2, padx=6, pady=8)

        self.status_dot = StatusDot(conn_box)
        self.status_dot.grid(row=0, column=3, padx=(6, 3), pady=8)

        self.status_text = ctk.CTkLabel(conn_box, text="Disconnected")
        self.status_text.grid(row=0, column=4, padx=3, pady=8, sticky="w")

        conn_box.grid_columnconfigure(5, weight=1)

        stop_all_btn = ctk.CTkButton(conn_box, text="STOP ALL", width=90, height=28,
                                      fg_color="#c0392b", hover_color="#992d22",
                                      command=self.stop_all)
        stop_all_btn.grid(row=0, column=6, padx=(8, 4), pady=8)

        home_all_btn = ctk.CTkButton(conn_box, text="HOME ALL", width=90, height=28,
                                      fg_color="#2980b9", hover_color="#1f6391",
                                      command=self.home_all)
        home_all_btn.grid(row=0, column=7, padx=4, pady=8)

        version_label = ctk.CTkLabel(conn_box, text=f"v{APP_VERSION}",
                                      text_color="gray55", font=ctk.CTkFont(size=10))
        version_label.grid(row=0, column=8, padx=(8, 10), pady=8)

        # ---------------- Tabs ----------------
        # "Manual Control" holds today's per-axis panels. "Advanced" is
        # an empty placeholder for future modes (timer-based scan, grid
        # scan, sweep scan, combine scan, etc.) -- added now so those
        # can be dropped in later without restructuring the layout.
        tabview = ctk.CTkTabview(self, corner_radius=9, fg_color=CARD_COLOR,
                                  segmented_button_selected_color="#2980b9",
                                  segmented_button_selected_hover_color="#1f6391")
        tabview.grid(row=1, column=0, sticky="nsew", padx=8, pady=5)
        manual_tab = tabview.add("Manual Control")
        advanced_tab = tabview.add("Advanced")
        manual_tab.grid_columnconfigure(0, weight=1)
        manual_tab.grid_rowconfigure(0, weight=1)

        # ---------------- Axis panels ----------------
        # Layout: tower axes (masts) side by side in one row, turntable
        # axes below spanning the same width. Sized to fit the default
        # 3-axis (1A, 1B, 2A) config without scrolling; still wrapped
        # in a scrollable frame as a safety net if more axes are added.
        scroll = ctk.CTkFrame(manual_tab, corner_radius=0, fg_color=BG_COLOR)
        scroll.grid(row=0, column=0, sticky="nsew")

        axes = config.get("axes", [])
        towers = [a for a in axes if a.get("kind") == "tower"]
        turntables = [a for a in axes if a.get("kind") != "tower"]
        n_cols = max(len(towers), 1)
        for c in range(n_cols):
            scroll.grid_columnconfigure(c, weight=1)

        axis_speeds = self.settings.get("axis_speeds", {})
        self.axis_panels = []

        def make_panel(parent, axis_cfg):
            key = f"{axis_cfg['slot']}{axis_cfg['device']}"
            initial_speed = axis_speeds.get(key, axis_cfg.get("default_speed", 4))
            return AxisPanel(parent, axis_cfg, self.get_em, self.log,
                              initial_speed, self.save_axis_speed)

        for col, axis_cfg in enumerate(towers):
            panel = make_panel(scroll, axis_cfg)
            panel.grid(row=0, column=col, sticky="new", padx=5, pady=5)
            self.axis_panels.append(panel)

        for i, axis_cfg in enumerate(turntables):
            panel = make_panel(scroll, axis_cfg)
            panel.grid(row=1 + i, column=0, columnspan=n_cols,
                       sticky="new", padx=5, pady=5)
            self.axis_panels.append(panel)

        # placeholder content for the future tab
        ctk.CTkLabel(
            advanced_tab, justify="left", text_color="gray45",
            font=ctk.CTkFont(size=12),
            text=("Coming soon:\n\n"
                  "  \u2022 Timer-based scan\n"
                  "  \u2022 Grid scan\n"
                  "  \u2022 Sweep scan\n"
                  "  \u2022 Combine scan"),
        ).grid(row=0, column=0, sticky="nw", padx=16, pady=16)

        # ---------------- Log pane ----------------
        log_box = ctk.CTkFrame(self, corner_radius=9, fg_color=CARD_COLOR)
        log_box.grid(row=2, column=0, sticky="ew", padx=8, pady=(5, 8))
        log_box.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(log_box, text="Log", font=ctk.CTkFont(size=11)).grid(
            row=0, column=0, sticky="w", padx=8, pady=(6, 0))
        self.log_view = ctk.CTkTextbox(log_box, height=70, font=ctk.CTkFont(size=11))
        self.log_view.grid(row=1, column=0, sticky="ew", padx=8, pady=(2, 8))
        self.log_view.configure(state="disabled")

        # ---------------- Position polling loop ----------------
        self.poll_interval_ms = config.get("poll_interval_ms", 750)
        self.polling = False

        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # -- connection handling --

    def get_em(self):
        return self.em

    def toggle_connection(self):
        if self.em is not None and self.em.is_connected():
            self.disconnect_chassis()
        else:
            self.connect_chassis()

    def connect_chassis(self):
        ip = self.ip_entry.get().strip()
        if not ip:
            messagebox.showwarning("EMControl", "Enter an IP address first.")
            return

        resource = f"TCPIP0::{ip}::inst0::INSTR"
        self.connect_btn.configure(state="disabled")
        self.status_text.configure(text="Connecting...")
        self.status_dot.set_color("orange")
        self.update_idletasks()

        em = EMCenter(resource=resource)
        try:
            em.connect()
            idn = em.identify()
            self.em = em
            self.status_dot.set_color("#27ae60")  # green
            self.status_text.configure(text="Connected successfully")
            self.connect_btn.configure(text="Disconnect")
            self.log(f"Connected to {ip} -- ID: {idn}")

            # remember this IP for next launch
            self.settings["last_ip"] = ip
            save_settings(self.settings)

            # push each panel's currently shown speed to the card
            for panel in self.axis_panels:
                panel.apply_saved_speed()

            self.start_polling()
        except Exception as e:
            self.em = None
            self.status_dot.set_color("#c0392b")  # red
            self.status_text.configure(text="Connection failed")
            self.log(f"Connection to {ip} failed: {e}")
            messagebox.showerror("EMControl", f"Connection failed:\n{e}")
        finally:
            self.connect_btn.configure(state="normal")

    def disconnect_chassis(self):
        self.polling = False
        if self.em:
            try:
                self.em.disconnect()
            except Exception as e:
                self.log(f"Error during disconnect: {e}")
        self.em = None
        self.status_dot.set_color("grey")
        self.status_text.configure(text="Disconnected")
        self.connect_btn.configure(text="Connect")
        self.log("Disconnected.")

    def save_axis_speed(self, axis_key, preset):
        speeds = self.settings.setdefault("axis_speeds", {})
        speeds[axis_key] = preset
        save_settings(self.settings)

    def stop_all(self):
        if not self.em or not self.em.is_connected():
            return
        for panel in self.axis_panels:
            panel.stop_axis()

    def home_all(self):
        if not self.em or not self.em.is_connected():
            self.log("Not connected -- connect first.")
            return
        for panel in self.axis_panels:
            panel.home_axis()

    def start_polling(self):
        self.polling = True
        self.poll_positions()

    def poll_positions(self):
        if not self.polling:
            return
        for panel in self.axis_panels:
            panel.refresh()
        self.after(self.poll_interval_ms, self.poll_positions)

    def log(self, message):
        logger.info(message)
        self.log_view.configure(state="normal")
        self.log_view.insert("end", message + "\n")
        self.log_view.see("end")
        self.log_view.configure(state="disabled")

    def on_close(self):
        self.polling = False
        if self.em is not None:
            try:
                self.em.disconnect()
            except Exception:
                pass
        self.destroy()


def main():
    config = load_config()
    settings = load_settings()
    app = MainWindow(config, settings)
    app.mainloop()


if __name__ == "__main__":
    main()
