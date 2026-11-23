"""
Minecraft Server Launcher - starter version
Create vanilla Java servers, start/stop them, see the console, send commands.

Requires: Python 3.8+ and Java installed (java must work in a terminal).
Run with:  python launcher.py
"""
import json
import os
import queue
import shutil
import subprocess
import threading
import urllib.request
import tkinter as tk
from tkinter import ttk, messagebox

MANIFEST_URL = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
SERVERS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "servers")


def fetch_json(url):
    with urllib.request.urlopen(url, timeout=15) as r:
        return json.load(r)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("MC Server Launcher")
        self.geometry("950x600")
        self.proc = None
        self.versions = {}          # version id -> version json url
        self.q = queue.Queue()      # lets worker threads safely update the UI
        os.makedirs(SERVERS_DIR, exist_ok=True)

        self.build_ui()
        self.refresh_servers()
        threading.Thread(target=self.load_versions, daemon=True).start()
        self.after(100, self.drain_queue)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---------- UI ----------
    def build_ui(self):
        left = ttk.Frame(self, padding=10)
        left.pack(side="left", fill="y")
        right = ttk.Frame(self, padding=10)
        right.pack(side="right", fill="both", expand=True)

        # Left: server list + create
        ttk.Label(left, text="Your servers").pack(anchor="w")
        self.listbox = tk.Listbox(left, height=12, exportselection=False)
        self.listbox.pack(fill="x", pady=(0, 15))

        ttk.Label(left, text="Create new server").pack(anchor="w")
        self.name_var = tk.StringVar()
        ttk.Entry(left, textvariable=self.name_var).pack(fill="x", pady=2)
        self.version_var = tk.StringVar()
        self.version_box = ttk.Combobox(left, textvariable=self.version_var, state="readonly")
        self.version_box.pack(fill="x", pady=2)
        ttk.Button(left, text="Create server", command=self.create_server).pack(fill="x", pady=2)

        # Right: controls + console
        controls = ttk.Frame(right)
        controls.pack(fill="x")
        ttk.Button(controls, text="Start", command=self.start_server).pack(side="left")
        ttk.Button(controls, text="Stop", command=self.stop_server).pack(side="left", padx=5)
        ttk.Label(controls, text="RAM (MB):").pack(side="left", padx=(15, 2))
        self.ram_var = tk.IntVar(value=2048)
        ttk.Spinbox(controls, from_=512, to=32768, increment=512,
                    textvariable=self.ram_var, width=7).pack(side="left")

        self.console = tk.Text(right, state="disabled", bg="#111", fg="#ddd",
                               font=("Consolas", 10), wrap="word")
        self.console.pack(fill="both", expand=True, pady=10)

        cmd_row = ttk.Frame(right)
        cmd_row.pack(fill="x")
        self.cmd_var = tk.StringVar()
        entry = ttk.Entry(cmd_row, textvariable=self.cmd_var)
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<Return>", lambda e: self.send_command())
        ttk.Button(cmd_row, text="Send", command=self.send_command).pack(side="left", padx=5)

    # ---------- helpers ----------
    def log(self, text):
        """Safe to call from any thread."""
        def add():
            self.console.configure(state="normal")
            self.console.insert("end", text + "\n")
            self.console.see("end")
            self.console.configure(state="disabled")
        self.q.put(add)

    def drain_queue(self):
        while True:
            try:
                self.q.get_nowait()()
            except queue.Empty:
                break
        self.after(100, self.drain_queue)

    def refresh_servers(self):
        self.listbox.delete(0, "end")
        for name in sorted(os.listdir(SERVERS_DIR)):
            if os.path.isdir(os.path.join(SERVERS_DIR, name)):
                self.listbox.insert("end", name)

    def selected_server(self):
        sel = self.listbox.curselection()
        return self.listbox.get(sel[0]) if sel else None

    def is_running(self):
        return self.proc is not None and self.proc.poll() is None

    # ---------- versions ----------
    def load_versions(self):
        try:
            manifest = fetch_json(MANIFEST_URL)
            self.versions = {v["id"]: v["url"] for v in manifest["versions"]
                             if v["type"] == "release"}
            ids = list(self.versions.keys())  # newest first

            def update():
                self.version_box["values"] = ids
                if ids:
                    self.version_box.current(0)
            self.q.put(update)
        except Exception as e:
            self.log(f"Could not load version list: {e}")

    # ---------- create ----------
    def create_server(self):
        name = self.name_var.get().strip()
        version = self.version_var.get()
        if not name or not version:
            messagebox.showwarning("Missing info", "Enter a name and pick a version.")
            return
        if not name.replace("-", "").replace("_", "").replace(" ", "").isalnum():
            messagebox.showwarning("Bad name", "Use only letters, numbers, spaces, - and _.")
            return
        path = os.path.join(SERVERS_DIR, name)
        if os.path.exists(path):
            messagebox.showwarning("Exists", "A server with that name already exists.")
            return
        if not messagebox.askyesno(
                "Minecraft EULA",
                "Running a server means you agree to the Minecraft EULA:\n"
                "https://aka.ms/MinecraftEULA\n\nDo you accept?"):
            return

        def work():
            try:
                self.log(f"Looking up Minecraft {version}...")
                meta = fetch_json(self.versions[version])
                jar_url = meta["downloads"]["server"]["url"]
                os.makedirs(path)
                self.log("Downloading server.jar (this can take a moment)...")
                urllib.request.urlretrieve(jar_url, os.path.join(path, "server.jar"))
                with open(os.path.join(path, "eula.txt"), "w") as f:
                    f.write("eula=true\n")
                self.log(f"Server '{name}' created. Select it and press Start.")
                self.q.put(self.refresh_servers)
            except Exception as e:
                self.log(f"Error creating server: {e}")

        threading.Thread(target=work, daemon=True).start()

    # ---------- run ----------
    def start_server(self):
        if self.is_running():
            messagebox.showinfo("Already running", "A server is already running.")
            return
        name = self.selected_server()
        if not name:
            messagebox.showinfo("Pick a server", "Select a server from the list first.")
            return
        java = shutil.which("java")
        if not java:
            messagebox.showerror("Java not found",
                                 "Install Java (Java 21 for newest Minecraft) and try again.")
            return

        path = os.path.join(SERVERS_DIR, name)
        ram = self.ram_var.get()
        cmd = [java, f"-Xmx{ram}M", "-jar", "server.jar", "nogui"]
        self.log(f"--- Starting '{name}' ---")
        self.proc = subprocess.Popen(
            cmd, cwd=path, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        threading.Thread(target=self.read_output, args=(self.proc,), daemon=True).start()

    def read_output(self, proc):
        for line in proc.stdout:
            self.log(line.rstrip())
        proc.wait()
        self.log("--- Server stopped ---")

    def send_command(self):
        text = self.cmd_var.get().strip()
        if not text:
            return
        if not self.is_running():
            self.log("(No server running)")
            return
        self.proc.stdin.write(text + "\n")
        self.proc.stdin.flush()
        self.cmd_var.set("")

    def stop_server(self):
        if self.is_running():
            self.proc.stdin.write("stop\n")
            self.proc.stdin.flush()

    def on_close(self):
        if self.is_running():
            if not messagebox.askyesno("Server running", "Stop the server and quit?"):
                return
            self.stop_server()
            try:
                self.proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
