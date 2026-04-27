import os
import sys
import re
import shutil
import time
import threading
import subprocess
import tkinter as tk
from tkinter import messagebox, ttk
import requests
import traceback

# ── Constants ──────────────────────────────────────────────────────────────────
VERSION      = "4.0 (Multi-Task)"
GITHUB_REPO  = "orqz/questify"
TIMEOUT      = 15 * 60 + 30

BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
QUESTIFY_EXE = os.path.join(BASE_DIR, "questify.exe")

# ── Discord Palette ────────────────────────────────────────────────────────────
BG_DARKEST   = "#202225"
BG_DARK      = "#2F3136"
BG_MID       = "#36393F"
BG_LIGHT     = "#40444B"
BG_HOVER     = "#34373C"
ACCENT       = "#5865F2"
ACCENT_HOVER = "#4752C4"
GREEN        = "#57F287"
RED          = "#ED4245"
RED_BG       = "#3a1f20"
YELLOW       = "#FEE75C"
TEXT_NORMAL  = "#DCDDDE"
TEXT_MUTED   = "#72767D"
TEXT_WHITE   = "#FFFFFF"
DIVIDER      = "#1e1f22"

# Avatar palette cycles for game icons
AVATAR_COLORS = ["#5865F2", "#1ABC9C", "#E91E63", "#E67E22", "#9B59B6", "#2ECC71", "#E74C3C", "#3498DB"]

FONT_NORMAL  = ("Segoe UI", 10)
FONT_BOLD    = ("Segoe UI", 10, "bold")
FONT_SMALL   = ("Segoe UI", 9)
FONT_TITLE   = ("Segoe UI", 15, "bold")
FONT_LABEL   = ("Segoe UI", 8, "bold")
FONT_MONO    = ("Consolas", 9)
FONT_TIMER   = ("Consolas", 11, "bold")


def make_initials(name):
    """Return up to 2 uppercase initials from a game name."""
    words = name.split()
    if len(words) >= 2:
        return (words[0][0] + words[1][0]).upper()
    return name[:2].upper()


def pick_avatar_color(name):
    """Deterministically pick a color from the palette based on the name."""
    return AVATAR_COLORS[sum(ord(c) for c in name) % len(AVATAR_COLORS)]


class ScrollableFrame(tk.Frame):
    """A vertically scrollable frame container."""
    def __init__(self, parent, bg, **kwargs):
        super().__init__(parent, bg=bg, **kwargs)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.scrollbar = tk.Scrollbar(self, orient="vertical", command=self.canvas.yview,
                                       bg=bg, troughcolor=bg, relief="flat", bd=0, width=6)
        self.inner = tk.Frame(self.canvas, bg=bg)

        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        self.window_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")

        self.inner.bind("<Configure>", self._on_frame_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _on_frame_configure(self, _):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self.canvas.itemconfig(self.window_id, width=event.width)

    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")


class AvatarLabel(tk.Frame):
    """A colored circle-like square with initials, mimicking Discord's game icon."""
    def __init__(self, parent, name, size=36, **kwargs):
        color = pick_avatar_color(name)
        super().__init__(parent, bg=color, width=size, height=size, **kwargs)
        self.pack_propagate(False)
        initials = make_initials(name)
        tk.Label(self, text=initials, bg=color, fg=TEXT_WHITE,
                 font=("Segoe UI", max(8, size // 4), "bold")).pack(expand=True)


class SessionCard(tk.Frame):
    """A Discord-style card representing one active game session."""
    def __init__(self, parent, name, on_stop, **kwargs):
        super().__init__(parent, bg=BG_DARK, pady=0, **kwargs)
        self.name = name
        self.timeout = TIMEOUT
        self._running = True

        # ── Card inner padding frame ──────────────────────────────────────────
        inner = tk.Frame(self, bg=BG_DARK, padx=14, pady=10)
        inner.pack(fill="x")

        # Game icon / avatar
        icon_frame = tk.Frame(inner, bg=pick_avatar_color(name), width=42, height=42)
        icon_frame.pack(side="left", padx=(0, 12))
        icon_frame.pack_propagate(False)
        tk.Label(icon_frame, text=make_initials(name), bg=pick_avatar_color(name),
                 fg=TEXT_WHITE, font=("Segoe UI", 12, "bold")).pack(expand=True)

        # Info column
        info = tk.Frame(inner, bg=BG_DARK)
        info.pack(side="left", fill="both", expand=True)

        self.name_lbl = tk.Label(info, text=name, fg=TEXT_WHITE, bg=BG_DARK,
                                  font=FONT_BOLD, anchor="w")
        self.name_lbl.pack(fill="x")

        self.sub_lbl = tk.Label(info, text="Initializing...", fg=TEXT_MUTED, bg=BG_DARK,
                                 font=FONT_SMALL, anchor="w")
        self.sub_lbl.pack(fill="x")

        # Progress bar (slim, custom-drawn on a canvas)
        pb_frame = tk.Frame(info, bg=BG_DARK)
        pb_frame.pack(fill="x", pady=(5, 0))
        self.pb_canvas = tk.Canvas(pb_frame, height=4, bg=BG_LIGHT,
                                    highlightthickness=0, bd=0)
        self.pb_canvas.pack(fill="x")
        self.pb_bar = self.pb_canvas.create_rectangle(0, 0, 0, 4, fill=ACCENT, width=0)
        self.pb_canvas.bind("<Configure>", self._redraw_bar)

        # Right-side: timer + stop button
        right = tk.Frame(inner, bg=BG_DARK)
        right.pack(side="right", padx=(12, 0))

        self.timer_lbl = tk.Label(right, text="--:--", fg=GREEN, bg=BG_DARK,
                                   font=FONT_TIMER)
        self.timer_lbl.pack(anchor="e")

        self.stop_btn = tk.Label(right, text="■  Stop", fg=RED, bg=BG_DARK,
                                  font=FONT_SMALL, cursor="hand2", padx=6, pady=3)
        self.stop_btn.pack(anchor="e", pady=(4, 0))
        self.stop_btn.bind("<Enter>", lambda e: self.stop_btn.config(bg=RED_BG))
        self.stop_btn.bind("<Leave>", lambda e: self.stop_btn.config(bg=BG_DARK))
        self.stop_btn.bind("<Button-1>", lambda e: on_stop(name))

        # Bottom border / divider
        tk.Frame(self, bg=DIVIDER, height=1).pack(fill="x")

        self._elapsed = 0
        self._progress = 0.0

    def _redraw_bar(self, _=None):
        w = self.pb_canvas.winfo_width()
        fill_w = int(w * self._progress)
        self.pb_canvas.coords(self.pb_bar, 0, 0, fill_w, 4)

    def update_timer(self, remaining, elapsed):
        self._elapsed = elapsed
        self._progress = (TIMEOUT - remaining) / TIMEOUT
        m, s = divmod(remaining, 60)
        self.timer_lbl.config(text=f"{m:02d}:{s:02d}")
        elapsed_m, elapsed_s = divmod(elapsed, 60)
        self.sub_lbl.config(text=f"Running · {elapsed_m:02d}:{elapsed_s:02d} elapsed")

        # Color the timer: green → yellow → red as time runs out
        pct = remaining / TIMEOUT
        if pct > 0.5:
            self.timer_lbl.config(fg=GREEN)
        elif pct > 0.2:
            self.timer_lbl.config(fg=YELLOW)
        else:
            self.timer_lbl.config(fg=RED)

        self._redraw_bar()

    def destroy(self):
        self._running = False
        super().destroy()


class QuestifyApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Questify Multi-Manager")
        self.overrideredirect(True)   # Remove Windows default titlebar & border
        self.geometry("920x660")
        self.minsize(800, 560)
        self.configure(bg=BG_DARKEST)

        # Center on screen
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x  = (sw - 920) // 2
        y  = (sh - 660) // 2
        self.geometry(f"920x660+{x}+{y}")

        self.gamelist    = []
        self.all_names   = []
        self.matches     = []
        self.active_sessions = {}   # name -> {"card": SessionCard, "active": bool}
        self._session_count = 0

        self._build_ui()
        self._load_games()

    # ── UI Construction ────────────────────────────────────────────────────────

    def _build_ui(self):
        self._build_titlebar()

        body = tk.Frame(self, bg=BG_MID)
        body.pack(fill="both", expand=True)

        self._build_sidebar(body)
        self._build_main(body)

    def _build_titlebar(self):
        bar = tk.Frame(self, bg=BG_DARKEST, height=38)
        bar.pack(fill="x")
        bar.pack_propagate(False)

        # Window drag simulation
        bar.bind("<Button-1>", self._start_move)
        bar.bind("<B1-Motion>", self._do_move)

        tk.Label(bar, text="⬡", fg=ACCENT, bg=BG_DARKEST,
                 font=("Segoe UI", 14)).pack(side="left", padx=(12, 4), pady=4)
        tk.Label(bar, text=f"Questify  ·  v{VERSION}", fg=TEXT_MUTED,
                 bg=BG_DARKEST, font=FONT_SMALL).pack(side="left", pady=4)

        # Close button
        close_lbl = tk.Label(bar, text="  ✕  ", fg=TEXT_MUTED, bg=BG_DARKEST,
                              font=FONT_NORMAL, cursor="hand2")
        close_lbl.pack(side="right", padx=4)
        close_lbl.bind("<Enter>", lambda e: close_lbl.config(bg=RED, fg=TEXT_WHITE))
        close_lbl.bind("<Leave>", lambda e: close_lbl.config(bg=BG_DARKEST, fg=TEXT_MUTED))
        close_lbl.bind("<Button-1>", lambda e: self.destroy())

        # Minimize button
        min_lbl = tk.Label(bar, text="  —  ", fg=TEXT_MUTED, bg=BG_DARKEST,
                            font=FONT_NORMAL, cursor="hand2")
        min_lbl.pack(side="right")
        min_lbl.bind("<Enter>", lambda e: min_lbl.config(bg=BG_LIGHT))
        min_lbl.bind("<Leave>", lambda e: min_lbl.config(bg=BG_DARKEST))
        min_lbl.bind("<Button-1>", lambda e: self.iconify())

        tk.Frame(self, bg=DIVIDER, height=1).pack(fill="x")

    def _build_sidebar(self, parent):
        sidebar = tk.Frame(parent, bg=BG_DARK, width=252)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        tk.Frame(sidebar, bg=DIVIDER, width=1).pack(side="right", fill="y")

        # Search header
        hdr = tk.Frame(sidebar, bg=BG_DARK, padx=12, pady=10)
        hdr.pack(fill="x")

        tk.Label(hdr, text="SEARCH GAMES", fg=TEXT_MUTED, bg=BG_DARK,
                 font=FONT_LABEL).pack(anchor="w", pady=(0, 6))

        search_wrap = tk.Frame(hdr, bg=BG_LIGHT, padx=8, pady=6)
        search_wrap.pack(fill="x")

        tk.Label(search_wrap, text="⌕", fg=TEXT_MUTED, bg=BG_LIGHT,
                 font=("Segoe UI", 11)).pack(side="left")

        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", self._on_search)
        ent = tk.Entry(search_wrap, textvariable=self.search_var, bg=BG_LIGHT,
                       fg=TEXT_WHITE, relief="flat", insertbackground=TEXT_WHITE,
                       font=FONT_NORMAL, bd=0)
        ent.pack(side="left", fill="x", expand=True, padx=(6, 0))

        tk.Frame(sidebar, bg=DIVIDER, height=1).pack(fill="x", padx=0)

        # Game list
        list_outer = tk.Frame(sidebar, bg=BG_DARK)
        list_outer.pack(fill="both", expand=True, padx=6, pady=6)

        self.listbox = tk.Listbox(
            list_outer,
            bg=BG_DARK, fg=TEXT_NORMAL,
            selectbackground=BG_LIGHT, selectforeground=TEXT_WHITE,
            activestyle="none", relief="flat",
            highlightthickness=0, bd=0,
            font=FONT_NORMAL,
        )
        self.listbox.pack(fill="both", expand=True)
        self.listbox.bind("<<ListboxSelect>>", self._on_listbox_select)
        self.listbox.bind("<Double-Button-1>", lambda e: self._start_selected())
        self.listbox.bind("<Return>", lambda e: self._start_selected())

        # Start button pinned at bottom
        btn_frame = tk.Frame(sidebar, bg=BG_DARK, padx=12, pady=10)
        btn_frame.pack(fill="x")

        self.start_btn = tk.Label(
            btn_frame,
            text="▶   START SELECTED GAME",
            bg=ACCENT, fg=TEXT_WHITE,
            font=FONT_BOLD, cursor="hand2",
            pady=9, anchor="center",
        )
        self.start_btn.pack(fill="x")
        self.start_btn.bind("<Enter>",  lambda e: self.start_btn.config(bg=ACCENT_HOVER))
        self.start_btn.bind("<Leave>",  lambda e: self.start_btn.config(bg=ACCENT))
        self.start_btn.bind("<Button-1>", lambda e: self._start_selected())

    def _build_main(self, parent):
        main = tk.Frame(parent, bg=BG_MID)
        main.pack(side="left", fill="both", expand=True)

        # Main header
        hdr = tk.Frame(main, bg=BG_MID, padx=20, pady=10)
        hdr.pack(fill="x")

        tk.Label(hdr, text="◈  ACTIVE SESSIONS", fg=TEXT_WHITE, bg=BG_MID,
                 font=FONT_BOLD).pack(side="left")

        self.count_badge = tk.Label(hdr, text="0 running", fg=TEXT_WHITE,
                                     bg=ACCENT, font=FONT_LABEL, padx=8, pady=3)
        self.count_badge.pack(side="left", padx=(10, 0))

        tk.Frame(main, bg=DIVIDER, height=1).pack(fill="x")

        # Scrollable sessions area
        self.sessions_scroll = ScrollableFrame(main, bg=BG_MID)
        self.sessions_scroll.pack(fill="both", expand=True)

        self.sessions_container = self.sessions_scroll.inner

        # Empty state placeholder
        self.empty_frame = tk.Frame(self.sessions_container, bg=BG_MID, pady=60)
        self.empty_frame.pack(fill="x")
        tk.Label(self.empty_frame, text="No active sessions",
                 fg=TEXT_MUTED, bg=BG_MID, font=("Segoe UI", 12)).pack()
        tk.Label(self.empty_frame, text="Select a game from the left and press Start",
                 fg=TEXT_MUTED, bg=BG_MID, font=FONT_SMALL).pack(pady=4)

        # ── Console log at bottom ──────────────────────────────────────────────
        tk.Frame(main, bg=DIVIDER, height=1).pack(fill="x")

        log_area = tk.Frame(main, bg=BG_DARKEST)
        log_area.pack(fill="x")

        log_hdr = tk.Frame(log_area, bg=BG_DARKEST, padx=14, pady=6)
        log_hdr.pack(fill="x")

        # Green dot
        dot_canvas = tk.Canvas(log_hdr, width=8, height=8, bg=BG_DARKEST,
                                highlightthickness=0)
        dot_canvas.create_oval(1, 1, 7, 7, fill=GREEN, outline="")
        dot_canvas.pack(side="left", pady=1)

        tk.Label(log_hdr, text="  CONSOLE", fg=TEXT_MUTED, bg=BG_DARKEST,
                 font=FONT_LABEL).pack(side="left")

        self.log_text = tk.Text(
            log_area,
            bg=BG_DARKEST, fg=TEXT_NORMAL,
            height=7, font=FONT_MONO,
            state="disabled", relief="flat",
            bd=0, padx=14, pady=4,
            wrap="word",
        )
        self.log_text.pack(fill="x")

        # Tag colors
        self.log_text.tag_config("time",  foreground=ACCENT)
        self.log_text.tag_config("ok",    foreground=GREEN)
        self.log_text.tag_config("err",   foreground=RED)
        self.log_text.tag_config("warn",  foreground=YELLOW)
        self.log_text.tag_config("info",  foreground=TEXT_NORMAL)

    # ── Window drag (custom titlebar) ──────────────────────────────────────────

    def _start_move(self, event):
        self._drag_x = event.x_root - self.winfo_x()
        self._drag_y = event.y_root - self.winfo_y()

    def _do_move(self, event):
        x = event.x_root - self._drag_x
        y = event.y_root - self._drag_y
        self.geometry(f"+{x}+{y}")

    # ── Logging ────────────────────────────────────────────────────────────────

    def _log(self, msg, level="info"):
        def _write():
            self.log_text.configure(state="normal")
            ts = time.strftime("%H:%M:%S")
            self.log_text.insert("end", f"[", "info")
            self.log_text.insert("end", ts, "time")
            self.log_text.insert("end", "]  ", "info")
            self.log_text.insert("end", msg + "\n", level)
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        self.after(0, _write)

    # ── Game list loading ──────────────────────────────────────────────────────

    def _load_games(self):
        self._log("Fetching games from Discord API...", "warn")
        def fetch():
            try:
                r = requests.get("https://discord.com/api/applications/detectable", timeout=10)
                self.gamelist = r.json()
                self.all_names = sorted([a["name"] for a in self.gamelist if a.get("name")])
                self._log(f"Loaded {len(self.all_names)} games.", "ok")
                self.after(0, self._populate_list)
            except Exception as e:
                self._log(f"API Error: {e}", "err")
        threading.Thread(target=fetch, daemon=True).start()

    def _populate_list(self, names=None):
        self.listbox.delete(0, "end")
        self.matches = names if names is not None else self.all_names[:80]
        for name in self.matches:
            self.listbox.insert("end", f"  {name}")

    def _on_search(self, *_):
        q = self.search_var.get().lower()
        if not q:
            self._populate_list()
            return
        filtered = [n for n in self.all_names if q in n.lower()][:50]
        self._populate_list(filtered)

    def _on_listbox_select(self, _):
        pass  # Could highlight or preview — left as hook

    # ── Session management ─────────────────────────────────────────────────────

    def _start_selected(self):
        sel = self.listbox.curselection()
        if not sel:
            return
        raw = self.matches[sel[0]]
        game_name = raw.strip()

        if game_name in self.active_sessions:
            self._log(f"{game_name} is already running!", "warn")
            return

        exename = None
        for app in self.gamelist:
            if app.get("name") == game_name:
                for exe in app.get("executables", []):
                    if exe.get("os") == "win32":
                        exename = exe["name"]
                        break

        if not exename:
            self._log(f"No Windows EXE found for: {game_name}", "err")
            return

        safe_name = re.sub(r'[<>:"/\\|?*]', '', game_name).strip()
        parts     = exename.split("/")
        folder    = os.path.join(BASE_DIR, parts[0] if len(parts) > 1 else safe_name)
        dst       = os.path.join(folder, parts[-1])

        threading.Thread(target=self._run_task, args=(game_name, folder, dst), daemon=True).start()

    def _add_session_card(self, name):
        """Must be called from the main thread."""
        # Hide empty state
        self.empty_frame.pack_forget()

        card = SessionCard(self.sessions_container, name, on_stop=self._stop_session)
        card.pack(fill="x", padx=10, pady=(6, 0))
        self.active_sessions[name]["card"] = card
        self._update_badge()

    def _remove_session_card(self, name):
        """Must be called from the main thread."""
        if name in self.active_sessions:
            card = self.active_sessions[name].get("card")
            if card:
                try:
                    card.destroy()
                except Exception:
                    pass
            del self.active_sessions[name]

        if not self.active_sessions:
            self.empty_frame.pack(fill="x")
        self._update_badge()

    def _update_badge(self):
        n = len(self.active_sessions)
        self.count_badge.config(text=f"{n} running")
        self.count_badge.config(bg=ACCENT if n > 0 else BG_LIGHT)

    def _stop_session(self, name):
        if name in self.active_sessions:
            self.active_sessions[name]["active"] = False
            self._log(f"Stopping {name}...", "warn")

    # ── Task runner ────────────────────────────────────────────────────────────

    def _run_task(self, name, folder, dst):
        """
        name:   The game name (e.g., "Where Winds Meet")
        folder: The unique path for this session
        dst:    The full path to the renamed exe (e.g., folder/WWM.exe)
        """
        self.active_sessions[name] = {"card": None, "active": True, "process": None}

        try:
            # 1. KILL GHOSTS: Ensure no old questify.exe is locking the source file
            # This is a bit aggressive but prevents the PermissionError effectively
            try:
                subprocess.run(["taskkill", "/F", "/IM", "questify.exe", "/T"],
                               capture_output=True, check=False)
            except:
                pass

            # 2. Setup the directory
            os.makedirs(folder, exist_ok=True)

            # 3. SAFE COPY: Try to copy with retries if the file is locked
            max_retries = 5
            copied = False
            for i in range(max_retries):
                try:
                    # QUESTIFY_EXE should point to your compiled C# 'questify.exe'
                    shutil.copy2(QUESTIFY_EXE, dst)
                    copied = True
                    break
                except PermissionError:
                    self._log(f"File locked by OS/Antivirus, retrying ({i + 1}/5)...", "warn")
                    time.sleep(1)  # Give the OS time to finish scanning/releasing the file

            if not copied:
                raise Exception("Could not copy executable: File is locked by another process.")

            time.sleep(0.5)

            # 4. Launch the C# Ghost Process
            # 0x00000008 = DETACHED_PROCESS (Separates it from the parent console)
            proc = subprocess.Popen(
                [dst, name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                creationflags=0x00000008,
                shell=False
            )

            self.active_sessions[name]["process"] = proc
            self._log(f"Started Ghost Process: {name}", "ok")

            # 5. UI Setup
            self.after(0, self._add_session_card, name)

            elapsed = 0
            remaining = TIMEOUT

            # 6. Monitor Loop
            while remaining > 0 and self.active_sessions.get(name, {}).get("active", False):
                if proc.poll() is not None:
                    self._log(f"Process for {name} was closed.", "warn")
                    break

                card = self.active_sessions.get(name, {}).get("card")
                if card:
                    self.after(0, card.update_timer, remaining, elapsed)

                time.sleep(1)
                remaining -= 1
                elapsed += 1

        except Exception:
            self._log(f"Task error ({name}): {traceback.format_exc()}", "err")

        finally:
            # 7. Shutdown Process
            current_proc = self.active_sessions.get(name, {}).get("process")
            if current_proc:
                try:
                    current_proc.terminate()
                    current_proc.wait(timeout=2)
                except:
                    try:
                        current_proc.kill()
                    except:
                        pass

            # 8. Clean Cleanup
            # We wait 2 seconds because Windows is slow at releasing file handles
            time.sleep(2.0)
            try:
                if os.path.exists(folder):
                    shutil.rmtree(folder, ignore_errors=True)
                    self._log(f"Cleaned folder: {os.path.basename(folder)}", "info")
            except Exception as e:
                self._log(f"Cleanup Warning: {e}", "warn")

            self._log(f"Session Finished: {name}", "info")
            self.after(0, self._remove_session_card, name)

# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = QuestifyApp()

    # Style the ttk progressbar (unused now, but kept for compatibility)
    style = ttk.Style()
    style.theme_use("clam")
    style.configure("TProgressbar",
                    thickness=4,
                    background=ACCENT,
                    troughcolor=BG_LIGHT,
                    borderwidth=0)

    app.mainloop()
