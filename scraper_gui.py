"""
============================================================
 CONTRACTOR LEAD SCRAPER - GUI LAUNCHER
 Author : Saroj Bono
 Run   : python scraper_gui.py
============================================================
"""

import tkinter as tk
from tkinter import scrolledtext
import subprocess
import threading
import os
import glob


def find_latest_csv():
    files = glob.glob("*.csv") + glob.glob("C:/Users/bonos/Downloads/*.csv")
    if not files:
        return "No CSV found yet"
    return max(files, key=os.path.getmtime)


def run_script(script, log_widget, status_var, btn):
    def task():
        btn.config(state="disabled")
        status_var.set("Running...")
        log_widget.insert(tk.END, f"\n{'='*50}\nStarting {script}\n{'='*50}\n")
        log_widget.see(tk.END)
        try:
            proc = subprocess.Popen(
                ["python", script],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True, bufsize=1,
            )
            for line in proc.stdout:
                log_widget.insert(tk.END, line)
                log_widget.see(tk.END)
                log_widget.update()
            proc.wait()
            if proc.returncode == 0:
                status_var.set("Done!")
                log_widget.insert(tk.END, f"\nOutput saved: {find_latest_csv()}\n")
            else:
                status_var.set("Error - check log")
        except FileNotFoundError:
            log_widget.insert(tk.END, f"Script not found: {script}\n")
            status_var.set("Script not found")
        except Exception as e:
            log_widget.insert(tk.END, f"Error: {e}\n")
            status_var.set("Error")
        finally:
            btn.config(state="normal")
            log_widget.see(tk.END)

    threading.Thread(target=task, daemon=True).start()


root = tk.Tk()
root.title("Contractor Lead Scraper — Saroj Bono")
root.geometry("850x620")
root.configure(bg="#1e1e2e")

tk.Label(root, text="Contractor Lead Scraper",
         font=("Segoe UI", 16, "bold"),
         bg="#1e1e2e", fg="#cdd6f4").pack(pady=(15, 2))

tk.Label(root, text="Saroj Bono  |  Phillip Boykin (Upwork)",
         font=("Segoe UI", 9), bg="#1e1e2e", fg="#6c7086").pack(pady=(0, 10))

btn_frame = tk.Frame(root, bg="#1e1e2e")
btn_frame.pack(fill="x", padx=20, pady=5)

status_var = tk.StringVar(value="Ready")

atl_btn = tk.Button(btn_frame, text="Run Atlanta Permit Scraper",
    font=("Segoe UI", 11, "bold"), bg="#89b4fa", fg="#1e1e2e",
    relief="flat", padx=18, pady=8, cursor="hand2")
atl_btn.pack(side="left", padx=(0, 10))

ga_btn = tk.Button(btn_frame, text="Run Georgia SOS Scraper",
    font=("Segoe UI", 11, "bold"), bg="#a6e3a1", fg="#1e1e2e",
    relief="flat", padx=18, pady=8, cursor="hand2")
ga_btn.pack(side="left", padx=(0, 10))

tk.Button(btn_frame, text="Clear Log",
    font=("Segoe UI", 10), bg="#313244", fg="#cdd6f4",
    relief="flat", padx=12, pady=8, cursor="hand2",
    command=lambda: log.delete("1.0", tk.END)).pack(side="right")

tk.Label(root, textvariable=status_var, font=("Segoe UI", 10),
         bg="#313244", fg="#cdd6f4", padx=10, pady=5,
         anchor="w").pack(fill="x", padx=20, pady=(5, 0))

log = scrolledtext.ScrolledText(root, font=("Consolas", 9),
    bg="#181825", fg="#cdd6f4", relief="flat", padx=10, pady=10)
log.pack(fill="both", expand=True, padx=20, pady=(5, 15))
log.insert(tk.END, "Ready — press a button to start scraping.\n\n")
log.insert(tk.END, "Atlanta  → reads Record20260309.csv → atlanta_contractor_leads.csv\n")
log.insert(tk.END, "Georgia  → scrapes goals.sos.ga.gov  → georgia_sos_leads.csv\n\n")

atl_btn.config(command=lambda: run_script("atlanta_scraper.py", log, status_var, atl_btn))
ga_btn.config(command=lambda: run_script("ga_sos_full.py",      log, status_var, ga_btn))

root.mainloop()
