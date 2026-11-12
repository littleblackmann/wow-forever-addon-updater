from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
import online
import self_update

from updater import (APP, RESOURCES, backup_location, client_patch, process_error,
                     remember_game, remembered_game, resolve_game, run_updates)


APP_ICON = RESOURCES / "圖示" / "WoW-Forever.ico"
PROJECT_URL = "https://littleblackmann.github.io/projects/forever-addon-manager.html"


class UpdaterWindow:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.events = queue.Queue()
        self.busy = False
        self.app_update = None
        self.game = remembered_game()
        root.title("小黑的永恆插件更新器")
        if APP_ICON.is_file():
            root.iconbitmap(str(APP_ICON))
        root.geometry("1040x740")
        root.minsize(850, 600)
        root.configure(bg="#f0f3f8")
        root.protocol("WM_DELETE_WINDOW", self.close)

        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("Treeview", font=("Microsoft JhengHei UI", 10), rowheight=30,
                        background="white", foreground="#152235", fieldbackground="white")
        style.configure("Treeview.Heading", font=("Microsoft JhengHei UI", 10, "bold"),
                        background="#e4eaf3", foreground="#203452", padding=(7, 6))
        style.map("Treeview", background=[("selected", "#dbeafe")], foreground=[("selected", "#102a43")])
        style.configure("Primary.TButton", font=("Microsoft JhengHei UI", 12, "bold"),
                        background="#235dc5", foreground="white", padding=(16, 9), borderwidth=0)
        style.map("Primary.TButton", background=[("disabled", "#9aaecb"), ("active", "#194a9f")])
        style.configure("TButton", font=("Microsoft JhengHei UI", 10), padding=(11, 7))

        header = tk.Frame(root, bg="#152742", padx=23, pady=16)
        header.pack(fill="x")
        header.columnconfigure(0, weight=1)
        heading = tk.Frame(header, bg="#152742")
        heading.grid(row=0, column=0, sticky="nw")
        tk.Label(heading, text="小黑的永恆插件更新器", bg="#152742", fg="white",
                 font=("Microsoft JhengHei UI", 19, "bold")).pack(anchor="w")
        self.client_text = tk.StringVar()
        self.update_client_text()
        tk.Label(heading, textvariable=self.client_text,
                 bg="#152742", fg="#d4e3f7", font=("Microsoft JhengHei UI", 10)).pack(anchor="w", pady=(4, 0))
        notice = tk.Frame(header, bg="#152742")
        notice.grid(row=0, column=1, sticky="ne", padx=(20, 0))
        tk.Label(notice, text="免責聲明", bg="#152742", fg="#f0d7ac",
                 font=("Microsoft JhengHei UI", 10, "bold")).pack(anchor="e")
        tk.Label(notice, text="插件皆由各原作者製作，並非本人開發。\n本人僅整理懶人包，方便下載與更新；本工具非官方提供。",
                 bg="#152742", fg="#d4e3f7", justify="right",
                 font=("Microsoft JhengHei UI", 9)).pack(anchor="e", pady=(2, 3))
        self.website_link = tk.Label(notice, text=PROJECT_URL, bg="#152742", fg="#a8d2ff",
                                    cursor="hand2", takefocus=True,
                                    font=("Microsoft JhengHei UI", 9, "underline"))
        self.website_link.pack(anchor="e")
        for event in ("<Button-1>", "<Return>", "<space>"):
            self.website_link.bind(event, self.open_project_page)

        location = tk.Frame(root, bg="#f0f3f8", padx=19, pady=10)
        location.pack(fill="x")
        tk.Label(location, text="遊戲位置", bg="#f0f3f8", fg="#203452",
                 font=("Microsoft JhengHei UI", 10)).pack(side="left", padx=(0, 10))
        self.game_text = tk.StringVar(value=str(self.game))
        self.path_entry = ttk.Entry(location, textvariable=self.game_text, state="readonly")
        self.path_entry.pack(side="left", fill="x", expand=True)
        self.folder_button = ttk.Button(location, text="選擇資料夾…", command=self.choose_folder)
        self.folder_button.pack(side="left", padx=(10, 0))

        guide = tk.Frame(root, bg="#f0f3f8", padx=19)
        guide.pack(fill="x")
        for text in (
            "更新器放哪裡：解壓到桌面等可寫入的資料夾即可。",
            "遊戲位置選哪裡：選「World of Warcraft」資料夾，裡面要看得到「_forever_」。",
        ):
            tk.Label(guide, text=text, bg="#f0f3f8", fg="#334a66",
                     font=("Microsoft JhengHei UI", 10), anchor="w").pack(fill="x", pady=(0, 4))
        destination = tk.Frame(guide, bg="#f0f3f8")
        destination.pack(fill="x", pady=(3, 0))
        tk.Label(destination, text="插件自動裝到", bg="#f0f3f8", fg="#203452",
                 font=("Microsoft JhengHei UI", 10)).pack(side="left", padx=(0, 10))
        self.addons_text = tk.StringVar()
        self.update_install_text()
        ttk.Entry(destination, textvariable=self.addons_text, state="readonly").pack(side="left", fill="x", expand=True)

        tools = tk.Frame(root, bg="#f0f3f8", padx=19, pady=13)
        tools.pack(fill="x")
        self.update_button = ttk.Button(tools, text="一鍵更新遊戲插件", style="Primary.TButton", command=lambda: self.start(True))
        self.check_button = ttk.Button(tools, text="只檢查", command=lambda: self.start(False))
        self.update_button.pack(side="left")
        self.check_button.pack(side="left", padx=8)
        ttk.Button(tools, text="查看保留檔案", command=self.open_backups).pack(side="right")
        self.program_button = ttk.Button(tools, text="更新管理器介面（UI）", command=self.update_program, state="disabled")
        self.program_button.pack(side="right", padx=8)

        self.online_text = tk.StringVar(value=f"管理器介面 v{online.APP_VERSION}｜正在檢查介面版本…")
        tk.Label(root, textvariable=self.online_text, bg="#f0f3f8", fg="#334a66",
                 font=("Microsoft JhengHei UI", 10), anchor="w").pack(fill="x", padx=19, pady=(0, 6))
        self.catalog_text = tk.StringVar(value="遊戲插件：按「一鍵更新遊戲插件」會同步整合清單，更新 AddOns 插件並補裝缺少的項目。")
        tk.Label(root, textvariable=self.catalog_text, bg="#f0f3f8", fg="#334a66",
                 font=("Microsoft JhengHei UI", 10), anchor="w", wraplength=800, justify="left").pack(fill="x", padx=19, pady=(0, 8))

        body = tk.Frame(root, bg="#f0f3f8")
        body.pack(fill="both", expand=True, padx=19)
        columns = ("addon", "local", "latest", "result")
        self.table = ttk.Treeview(body, columns=columns, show="headings", selectmode="browse")
        for name, label, width, stretch in zip(columns, ("插件", "本機版本", "發布版本", "結果"),
                                               (196, 94, 94, 458), (False, False, False, True)):
            self.table.heading(name, text=label, anchor="w")
            self.table.column(name, width=width, minwidth=75, stretch=stretch)
        self.table.tag_configure("alt", background="#f7f9fc")
        scrollbar = ttk.Scrollbar(body, orient="vertical", command=self.table.yview)
        horizontal = ttk.Scrollbar(body, orient="horizontal", command=self.table.xview)
        self.table.configure(yscrollcommand=scrollbar.set, xscrollcommand=horizontal.set)
        self.table.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(0, weight=1)
        self.table.bind("<Double-1>", self.show_details)

        foot = tk.Frame(root, bg="#f0f3f8", padx=20, pady=10)
        foot.pack(fill="x")
        self.status = tk.StringVar(value="先選遊戲位置並關閉遊戲，再按「一鍵更新遊戲插件」。管理器介面有新版時會另外提示。")
        tk.Label(foot, textvariable=self.status, bg="#f0f3f8", fg="#334a66",
                 font=("Microsoft JhengHei UI", 10), anchor="w").pack(side="left", fill="x", expand=True)
        self.progress = ttk.Progressbar(foot, mode="indeterminate", length=120)
        root.after(100, self.poll)
        root.after(200, self.check_online)

    def check_online(self):
        def worker():
            try:
                update = online.check_app()
                self.events.put(("app_status", (update, None)))
            except Exception as exc:
                self.events.put(("app_status", (None, process_error(exc))))
        threading.Thread(target=worker, daemon=True).start()

    def open_project_page(self, _event=None):
        webbrowser.open(PROJECT_URL)

    def update_program(self):
        if self.busy or self.app_update is None:
            return
        self.busy = True
        for button in (self.update_button, self.check_button, self.folder_button, self.program_button):
            button.state(["disabled"])
        self.status.set("正在下載新版管理器介面（UI）；驗證完成後會自動重新開啟。")
        update = self.app_update
        def worker():
            try:
                path = online.download_app(update)
                self.events.put(("self_update", (path, update["asset"]["digest"].removeprefix("sha256:"))))
            except Exception as exc:
                self.events.put(("error", process_error(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def update_client_text(self):
        try:
            patch, _ = client_patch(self.game)
            client = f"《魔獸世界：永恆》 {patch}"
        except Exception:
            client = "請先選擇《魔獸世界：永恆》的遊戲資料夾"
        self.client_text.set(client)

    def update_install_text(self):
        try:
            game = resolve_game(self.game)
            self.addons_text.set(str(game / "_forever_" / "Interface" / "AddOns"))
        except Exception:
            self.addons_text.set("請先選擇遊戲位置，這裡會顯示完整的插件安裝路徑。")

    def choose_folder(self):
        if self.busy:
            return
        selected = filedialog.askdirectory(title="選擇 World of Warcraft 資料夾（裡面要看得到 _forever_）",
                                           initialdir=str(self.game if self.game.is_dir() else APP), parent=self.root)
        if not selected:
            return
        try:
            game = resolve_game(Path(selected))
        except Exception as exc:
            messagebox.showerror("無法使用這個資料夾", process_error(exc), parent=self.root)
            return
        self.game = game
        self.game_text.set(str(game))
        self.update_client_text()
        self.update_install_text()
        self.table.delete(*self.table.get_children())
        try:
            remember_game(game)
            self.status.set("已選擇遊戲位置。可按「只檢查」，或關閉遊戲後按「一鍵更新遊戲插件」。")
        except OSError:
            self.status.set("本次已選擇遊戲位置；無法記住位置，請將更新器解壓到可寫入的資料夾。")

    def start(self, apply: bool):
        if self.busy:
            return
        try:
            game = resolve_game(self.game)
        except Exception as exc:
            messagebox.showerror("請先選擇遊戲位置", process_error(exc), parent=self.root)
            return
        self.busy = True
        self.table.delete(*self.table.get_children())
        self.status.set("正在檢查並安裝更新…" if apply else "正在查詢發布版本…")
        for button in (self.update_button, self.check_button, self.folder_button, self.program_button):
            button.state(["disabled"])
        self.progress.pack(side="right")
        self.progress.start(12)

        def worker():
            try:
                catalog = online.sync_catalog()
                self.events.put(("catalog", catalog.note))
                result = run_updates(apply, lambda *row: self.events.put(("row", row)), game=game, catalog=catalog)
                self.events.put(("done", result))
            except Exception as exc:
                self.events.put(("error", process_error(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def poll(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "app_status":
                    self.app_update, error = value
                    text = (f"介面有新版 v{self.app_update['version']}，可按「更新管理器介面（UI）」" if self.app_update else
                            f"暫時無法查版：{error}" if error else "管理器介面已是最新版本")
                    self.online_text.set(f"管理器介面 v{online.APP_VERSION}｜{text}")
                    if self.app_update is not None and not self.busy:
                        self.program_button.state(["!disabled"])
                    continue
                if kind == "catalog":
                    self.catalog_text.set(value)
                    continue
                if kind == "self_update":
                    try:
                        self_update.schedule(*value)
                    except Exception as exc:
                        self.events.put(("error", process_error(exc)))
                        continue
                    self.root.destroy()
                    return
                if kind == "row":
                    stripe = ("alt",) if len(self.table.get_children()) % 2 else ()
                    self.table.insert("", "end", values=value, tags=stripe)
                    continue
                self.busy = False
                self.progress.stop()
                self.progress.pack_forget()
                for button in (self.update_button, self.check_button, self.folder_button, self.program_button):
                    button.state(["!disabled"])
                if self.app_update is None:
                    self.program_button.state(["disabled"])
                if kind == "error":
                    self.status.set(value)
                    continue
                updated, available, skipped = value
                self.status.set(f"完成　已安裝／更新 {updated}　可安裝／更新 {available}　需查看 {skipped}（雙擊列看完整結果）")
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def show_details(self, event):
        item = self.table.identify_row(event.y)
        if item:
            name, current, latest, status = self.table.item(item, "values")
            messagebox.showinfo(name, f"本機 {current}　發布 {latest}\n\n{status}", parent=self.root)

    def open_backups(self):
        backups = backup_location(self.game)
        os.startfile(backups if backups.is_dir() else self.game.parent if self.game.parent.is_dir() else APP)

    def close(self):
        if self.busy:
            self.status.set("等這次檢查或更新完成，再關閉視窗。")
        else:
            self.root.destroy()


def show_window():
    if os.name == "nt":
        from ctypes import windll

        # Keep the updater's taskbar icon independent of other Python windows.
        windll.shell32.SetCurrentProcessExplicitAppUserModelID("XiaoHei.WoWForever.AddonUpdater")
    root = tk.Tk()
    UpdaterWindow(root)
    root.mainloop()


if __name__ == "__main__":
    show_window()
