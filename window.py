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
import theme
import notices
import updater as u
from chrome import WindowChrome

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
        self.notice = None
        self.notice_error = None
        self._notice_popup = None
        self._automatic_notice = None
        self.game = remembered_game()
        root.title("小黑的永恆插件更新器")
        if APP_ICON.is_file():
            root.iconbitmap(str(APP_ICON))
        root.geometry("1160x940")
        root.minsize(960, 740)
        root.configure(bg=theme.BG)
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.theme = theme.Theme(root, RESOURCES)
        self.surface = theme.StoneCanvas(root, self.theme)
        self.surface.pack(fill="both", expand=True)
        self.chrome=WindowChrome(root,caption_height=148)
        self.chrome.attach(self.surface)
        self.caption_buttons=[theme.CaptionButton(self.surface,text=text,command=command,close=text=="×")
                              for text,command in (("—",self.chrome.minimize),("□",self.chrome.maximize),("×",self.close))]
        self.client_text = tk.StringVar()
        self.update_client_text()
        self.disclaimer_button = ttk.Button(self.surface, text="免責聲明", style="Metal.TButton", command=self.show_disclaimer)
        self.game_text = tk.StringVar(value=str(self.game))
        self.path_entry = ttk.Entry(self.surface, textvariable=self.game_text, state="readonly",font=(theme.FONT,11))
        self.folder_button = ttk.Button(self.surface, text="選擇資料夾…", style="Metal.TButton", command=self.choose_folder)
        self.guide_button = ttk.Button(self.surface,text="安裝說明",style="Metal.TButton",command=self.show_guide)
        self.addons_text = tk.StringVar()
        self.update_install_text()
        self.destination_entry=ttk.Entry(self.surface,textvariable=self.addons_text,state="readonly",font=(theme.FONT,10))
        self.update_button = ttk.Button(self.surface, text="一鍵更新遊戲插件", style="Primary.TButton", command=lambda: self.start(True))
        self.check_button = ttk.Button(self.surface, text="只檢查", style="Metal.TButton", command=lambda: self.start(False))
        self.backups_button=ttk.Button(self.surface, text="查看保留檔案",style="Metal.TButton",command=self.open_backups)
        self.program_button = ttk.Button(self.surface, text="更新管理器程式",style="Metal.TButton",command=self.update_program,state="disabled")
        self.news_button = ttk.Button(self.surface, text="查看本次更新", style="Metal.TButton", command=self.show_update_news)
        self.online_text = tk.StringVar(value=f"管理器程式 v{online.APP_VERSION}｜正在檢查新版本…")
        self.catalog_text = tk.StringVar(value="按「一鍵更新遊戲插件」同步清單並補裝缺少的插件。")
        self.body = body = tk.Frame(self.surface,bg=theme.BG)
        columns = ("addon", "local", "latest", "result")
        self.table = ttk.Treeview(body, columns=columns,displaycolumns=("local","latest","result"),show="tree headings",selectmode="browse")
        self.table.heading("#0",text="插件",anchor="w")
        self.table.column("#0",width=280,minwidth=230,stretch=False)
        for name, label, width, stretch in zip(columns, ("插件", "本機版本", "發布版本", "結果"),
                                               (0,124,124,460),(False,False,False,True)):
            self.table.heading(name, text=label, anchor="center" if name in ("local","latest") else "w")
            self.table.column(name, width=width, minwidth=0 if name=="addon" else 90, stretch=stretch,
                              anchor="center" if name in ("local","latest") else "w")
        self.table.tag_configure("alt", background="#302c23")
        scrollbar = ttk.Scrollbar(body, orient="vertical", command=self.table.yview)
        horizontal = ttk.Scrollbar(body, orient="horizontal", command=self.table.xview)
        self.table.configure(yscrollcommand=scrollbar.set, xscrollcommand=horizontal.set)
        self.table.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(0, weight=1)
        self.table.bind("<Double-1>", self.show_details)
        self.table.bind("<Return>",self.show_details)
        self.status = tk.StringVar(value="準備就緒")
        self.progress = ttk.Progressbar(self.surface, mode="indeterminate", length=120)
        self._layout_pending=None
        self._layout_size=None
        self._text_items={}
        self._text_variables={'client':self.client_text,'online':self.online_text,'catalog':self.catalog_text,'status':self.status}
        self.surface.bind("<Configure>",self.request_layout)
        for variable in (self.client_text,self.online_text,self.catalog_text,self.status):
            variable.trace_add("write",self.refresh_text)
        root.bind('<Alt-F4>',lambda e:self.close())
        self.layout()
        root.after(100, self.poll)
        root.after(200, self.check_online)

    def request_layout(self,event=None):
        if event is not None and (event.width,event.height)==self._layout_size:
            return
        if self._layout_pending is None:
            self._layout_pending=self.root.after(16,self.layout)

    def refresh_text(self,*_):
        for key,item in self._text_items.items():
            self.surface.itemconfigure(item,text=self._text_variables[key].get())
        if self.busy and self._layout_size:
            w,h=self._layout_size
            self.progress.place(x=w-280,y=h-27,width=120,height=6)
        else:
            self.progress.place_forget()

    def layout(self):
        self._layout_pending=None
        c=self.surface
        w=max(960,c.winfo_width());h=max(740,c.winfo_height())
        if (w,h)==self._layout_size:
            self.refresh_text()
            return
        self._layout_size=(w,h)
        c.delete("decoration")
        self._text_items.clear()
        c.material(w,h)
        c.frame(6,6,w-12,h-12)
        def text(x,y,value,size=10,color=theme.INK,**kw):
            return c.create_text(x,y,text=value,fill=color,font=(theme.FONT,size),anchor="nw",tags="decoration",**kw)
        c.create_rectangle(10,10,w-10,40,fill="#2d2a23",outline=theme.LINE,tags="decoration")
        if not hasattr(self,'caption_icon'):
            icon=tk.PhotoImage(master=self.root,file=str(RESOURCES/'圖示'/'WoW-Forever.png'))
            self.caption_icon=icon.subsample(max(1,(icon.width()+19)//20))
        c.create_image(26,25,image=self.caption_icon,tags='decoration')
        text(43,15,"小黑的永恆插件更新器",10,theme.INK)
        for i,button in enumerate(self.caption_buttons):
            button.place(x=w-148+i*45,y=10,width=42,height=29)
        c.create_text(32,68,text="小黑的永恆插件更新器",fill=theme.GOLD,
                      font=(theme.TITLE_FONT,28,"bold"),anchor="nw",tags="decoration")
        self._text_items['client']=text(36,116,self.client_text.get(),11)
        def place(widget,x,y,width,height):
            widget.place(x=x,y=y+40,width=width,height=height)
        place(self.disclaimer_button,w-151,35,117,44)
        c.create_line(27,148,w-27,148,fill=theme.LINE,tags="decoration")
        c.frame(27,169,w-54,121)
        text(47,193,"遊戲位置",12,theme.GOLD)
        place(self.path_entry,163,143,w-370,40)
        place(self.folder_button,w-194,142,146,43)
        text(47,247,"插件安裝位置",11)
        place(self.destination_entry,163,197,w-370,34)
        place(self.guide_button,w-194,194,146,43)
        place(self.update_button,29,270,234,50)
        place(self.check_button,275,270,105,50)
        place(self.program_button,w-399,273,211,46)
        place(self.backups_button,w-176,273,147,46)
        self._text_items['online']=text(32,376,self.online_text.get(),10,theme.MUTED,width=w-64)
        self._text_items['catalog']=text(32,402,self.catalog_text.get(),10,theme.MUTED,width=w-270)
        self.news_button.place(x=w-224,y=392,width=190,height=32)
        c.frame(27,433,w-54,h-502)
        place(self.body,33,399,w-66,h-514)
        c.create_line(27,h-56,w-27,h-56,fill=theme.LINE,tags="decoration")
        self._text_items['status']=text(32,h-43,self.status.get(),10,theme.GOLD,width=w-300)
        c.create_text(w-32,h-43,text="更新前請先關閉遊戲",fill=theme.MUTED,
                      font=(theme.FONT,10),anchor="ne",tags="decoration")
        if self.busy:
            self.progress.place(x=w-280,y=h-27,width=120,height=6)

    def show_disclaimer(self):
        return theme.dialog(self.root,self.theme,"免責聲明",
            "Questie、AtlasLoot、DBM 等插件皆由各原作者製作，並非本人開發。\n\n"
            "本人僅整理成方便下載、安裝與更新的非官方懶人包，並提供部分繁中內容。"
            "插件與相關內容的權利歸各原作者所有。",self.open_project_page)

    def show_guide(self):
        return theme.dialog(self.root,self.theme,"安裝說明",
            "1. 將更新器完整解壓到桌面等可寫入的位置。\n"
            "2. 選擇裡面有 _forever_ 的 World of Warcraft 資料夾。\n"
            "3. 確認插件安裝位置，可先按「只檢查」。\n"
            "4. 完全退出遊戲，再按「一鍵更新遊戲插件」。\n"
            "5. 完成後查看結果，再重新開啟遊戲。")

    def check_online(self):
        game = self.game
        def worker():
            update, app_error, notice, news_error = None, None, None, None
            try:
                update = online.check_app()
            except Exception as exc:
                app_error = process_error(exc)
            try:
                notice = notices.discover()
            except Exception as exc:
                news_error = process_error(exc)
                try:
                    notice = notices.cached()
                except Exception:
                    pass
            self.events.put(("discovery", (game, update, app_error, notice, news_error)))
        threading.Thread(target=worker, daemon=True).start()

    def maybe_show_update_news(self):
        if self.busy or (self._notice_popup is not None and self._notice_popup.winfo_exists()):
            return
        if not self.app_update and not self.notice:
            return
        key = notices.receipt_key(self.game, self.notice, self.app_update)
        if key == self._automatic_notice:
            return
        self._automatic_notice = key
        if notices.seen(key):
            return
        try:
            resolve_game(self.game)
        except Exception:
            return
        if not self.app_update and not notices.pending(self.notice, self.game):
            return
        self.show_update_news()

    def show_update_news(self):
        if self._notice_popup is not None and self._notice_popup.winfo_exists():
            self._notice_popup.lift()
            return self._notice_popup
        popup = tk.Toplevel(self.root)
        self._notice_popup = popup
        popup.withdraw()
        popup.title('整合包更新內容')
        popup.transient(self.root)
        popup.configure(bg=theme.BG)
        popup.chrome = WindowChrome(popup,resizable=False,taskbar=False,caption_height=80,owner=self.root)
        width, height = 760, min(660, max(440, self.chrome.work_area()[3]-40))
        surface = theme.StoneCanvas(popup,self.theme,width=width,height=height)
        surface.pack(fill='both',expand=True)
        popup.chrome.attach(surface)
        surface.material(width,height)
        surface.frame(7,7,width-14,height-14)
        title = '管理器程式有新版' if self.app_update else '整合包有新內容' if self.notice and notices.pending(self.notice,self.game) else '本次更新內容'
        surface.create_text(28,28,text=title,anchor='nw',fill=theme.GOLD,font=(theme.TITLE_FONT,22,'bold'))
        surface.create_line(28,79,width-28,79,fill=theme.LINE)
        content = tk.Frame(surface,bg=theme.BG)
        content.place(x=28,y=100,width=width-56,height=height-214)
        text = tk.Text(content,wrap='word',font=(theme.FONT,12),bg='#191816',fg=theme.INK,
                       relief='flat',padx=14,pady=12,spacing3=9,selectbackground='#574627',cursor='arrow')
        scroll = ttk.Scrollbar(content,orient='vertical',command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right',fill='y');text.pack(side='left',fill='both',expand=True)
        text.insert('1.0',notices.body(self.notice,self.game,self.app_update));text.configure(state='disabled')
        def dismiss():
            self._notice_popup = None
            popup.destroy()
        def apply():
            if self.busy:
                self.status.set('請等目前的檢查或更新完成。')
                return
            try:
                resolve_game(self.game)
            except Exception:
                dismiss();self.choose_folder();return
            if self.app_update:
                dismiss();self.update_program();return
            if self.notice and online.app_order(self.notice.minimum_app)>online.app_order(online.APP_VERSION):
                self.status.set('這批整合需要新版管理器，請稍後重新查詢管理器程式。')
                return
            if u.game_running():
                self.status.set('請先完全退出《魔獸世界》，再按「一鍵更新遊戲插件」。')
                hint.configure(text='偵測到遊戲仍在執行，請先退出遊戲；此視窗可保留。')
                return
            dismiss();self.start(True)
        close = theme.CaptionButton(surface,text='×',command=dismiss,close=True)
        close.place(x=width-65,y=24,width=42,height=28)
        primary = ttk.Button(surface,text='先更新管理器程式' if self.app_update else '一鍵更新遊戲插件',style='Primary.TButton',command=apply)
        try:
            resolve_game(self.game)
        except Exception:
            primary.configure(text='先選擇遊戲位置')
        primary.place(x=width-268,y=height-78,width=240,height=46)
        later = ttk.Button(surface,text='稍後再說',style='Metal.TButton',command=dismiss)
        later.place(x=28,y=height-78,width=130,height=46)
        hint = tk.Label(surface,text='安裝或更新遊戲插件前，請先完全退出遊戲。',bg=theme.BG,fg=theme.MUTED,font=(theme.FONT,10))
        hint.place(x=28,y=height-110)
        if self.busy or (self.notice and online.app_order(self.notice.minimum_app)>online.app_order(online.APP_VERSION) and not self.app_update):
            primary.state(['disabled'])
        popup.update_idletasks()
        popup.geometry(f'{width}x{height}+{max(0,self.root.winfo_rootx()+(self.root.winfo_width()-width)//2)}+{max(0,self.root.winfo_rooty()+60)}')
        popup.protocol('WM_DELETE_WINDOW',dismiss)
        popup.bind('<Escape>',lambda e:dismiss())
        popup.deiconify();popup.lift(self.root)
        key = notices.receipt_key(self.game,self.notice,self.app_update)
        self._automatic_notice = key
        try:
            notices.acknowledge(key)
        except OSError:
            self.status.set('無法儲存提醒紀錄，請確認管理器資料夾可寫入。')
        return popup

    def open_project_page(self, _event=None):
        webbrowser.open(PROJECT_URL)

    def update_program(self):
        if self.busy or self.app_update is None:
            return
        self.busy = True
        for button in (self.update_button, self.check_button, self.folder_button, self.program_button):
            button.state(["disabled"])
        self.status.set("正在下載新版管理器程式；驗證完成後會自動重新開啟。")
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
        if self._notice_popup is not None and self._notice_popup.winfo_exists():
            self._notice_popup.destroy()
            self._notice_popup = None
        self.notice = None
        self._automatic_notice = None
        self.check_online()
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
        self.request_layout()
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
                if kind == 'discovery':
                    game, update, app_error, notice, news_error = value
                    if game != self.game:
                        continue
                    self.notice, self.notice_error = notice, news_error
                    if notice:
                        self.catalog_text.set('離線顯示上次更新內容；可稍後再查詢。' if news_error else '整合包有新內容，請查看本次更新。' if notices.pending(notice,self.game) else '整合包已同步，可查看本次更新內容。')
                    else:
                        self.catalog_text.set('暫時無法查詢整合包更新，可稍後再按「只檢查」。')
                    kind, value = 'app_status', (update, app_error)
                if kind == "app_status":
                    self.app_update, error = value
                    text = (f"有新版 v{self.app_update['version']}，可按「更新管理器程式」" if self.app_update else
                            f"暫時無法查版：{error}" if error else "管理器程式已是最新版本")
                    self.online_text.set(f"管理器程式 v{online.APP_VERSION}｜{text}")
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
                    self.table.insert("", "end",text="  "+str(value[0]),image=self.theme.badge(str(value[0])),values=value,tags=stripe)
                    continue
                self.busy = False
                self.progress.stop()
                self.progress.place_forget()
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
        self.maybe_show_update_news()
        self.root.after(100, self.poll)

    def show_details(self, event):
        item = self.table.focus() if event.keysym=="Return" else self.table.identify_row(event.y)
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
