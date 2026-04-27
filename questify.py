import tkinter as tk
import threading
import time
import sys
import os
import ctypes


def hide_console():
    """Hides the black console window so only the UI is visible."""
    hwnd = ctypes.windll.kernel32.GetConsoleWindow()
    if hwnd:
        ctypes.windll.user32.ShowWindow(hwnd, 0)


class TimerWindow:
    def __init__(self, root):
        self.root = root
        self.root.title("Timer Pro")  # Discord will show this status
        self.root.geometry("250x120")
        self.root.resizable(False, False)

        # UI Elements
        self.label = tk.Label(root, text="Timer is Active", font=("Arial", 12, "bold"), pady=10)
        self.label.pack()

        self.status_label = tk.Label(root, text="Discord Synced", fg="green")
        self.status_label.pack()

        self.exit_btn = tk.Button(root, text="Close & Stop Timer", command=self.quit_app)
        self.exit_btn.pack(pady=10)

        # Start the timer logic in a background thread
        self.total_seconds = 15 * 60 + 30
        threading.Thread(target=self.run_timer, daemon=True).start()

    def run_timer(self):
        # Redirect stdout to avoid errors in windowed mode
        sys.stdout = open(os.devnull, 'w')

        while self.total_seconds > 0:
            time.sleep(1)
            self.total_seconds -= 1

            # Update window title with time (visible in taskbar)
            mins, secs = divmod(self.total_seconds, 60)
            self.root.title(f"Timer: {mins:02d}:{secs:02d}")

        # When timer hits 0
        self.label.config(text="Time's Up!", fg="red")

    def quit_app(self):
        """Standard exit for the UI and background thread."""
        os._exit(0)


if __name__ == "__main__":
    # 1. Hide the console
    hide_console()

    # 2. Run the window
    root = tk.Tk()

    # Optional: Keep it on top so it's easy to find at first
    root.attributes("-topmost", True)

    app = TimerWindow(root)
    root.mainloop()
