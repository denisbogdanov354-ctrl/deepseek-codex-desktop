import tkinter as tk
from tkinter import ttk, filedialog, simpledialog, messagebox
from tkinterdnd2 import TkinterDnD, DND_FILES
from PIL import Image, ImageTk, ImageGrab
import subprocess, os, sys, threading, queue, json, time, re, webbrowser, urllib.parse, shutil, ctypes, hashlib

ROOT = os.path.abspath(os.environ.get("DEEPSEEK_CODEX_PROJECTS_ROOT", os.path.join(os.path.expanduser("~"), "Documents")))
CODEX_HOME = os.path.abspath(os.environ.get("DEEPSEEK_CODEX_HOME", os.path.expanduser(r"~\.codex-deepseek")))

def resolve_codex():
    for name in ("codex.cmd","codex.exe","codex"):
        found=shutil.which(name)
        if found and os.path.exists(found): return found
    appdata=os.environ.get("APPDATA","")
    candidates=[
        os.path.join(appdata,"npm","codex.cmd") if appdata else "",
        os.path.expanduser(r"~\AppData\Roaming\npm\codex.cmd"),
    ]
    for path in candidates:
        if path and os.path.exists(path): return path
    return "codex"

CODEX = resolve_codex()
STATE = os.path.join(CODEX_HOME,"deepseek_gui_state.json")
q = queue.Queue()
_SINGLE_INSTANCE_MUTEX=None

def resource_path(relative):
    base=getattr(sys,"_MEIPASS",os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base,relative)

def acquire_single_instance():
    global _SINGLE_INSTANCE_MUTEX
    if os.name!="nt": return True
    try:
        from ctypes import wintypes
        kernel32=ctypes.WinDLL("kernel32",use_last_error=True)
        user32=ctypes.WinDLL("user32",use_last_error=True)
        create_mutex=kernel32.CreateMutexW
        create_mutex.argtypes=[ctypes.c_void_p,wintypes.BOOL,wintypes.LPCWSTR]
        create_mutex.restype=wintypes.HANDLE
        close_handle=kernel32.CloseHandle
        close_handle.argtypes=[wintypes.HANDLE]
        close_handle.restype=wintypes.BOOL
        find_window=user32.FindWindowW
        find_window.argtypes=[wintypes.LPCWSTR,wintypes.LPCWSTR]
        find_window.restype=wintypes.HWND
        ctypes.set_last_error(0)
        handle=create_mutex(None,False,"Local\\DeepSeekCodexDesktop_1_0")
        err=ctypes.get_last_error()
        if not handle: return True
        already_exists=(err==183)
        if already_exists:
            close_handle(handle)
            hwnd=find_window("TkTopLevel","DeepSeek Codex")
            if hwnd:
                user32.ShowWindow(hwnd,9)
                user32.SetForegroundWindow(hwnd)
            return False
        _SINGLE_INSTANCE_MUTEX=handle
        return True
    except Exception:
        return True

BG="#1b1b1d"
SIDE="#161618"
SURFACE="#2b2b2e"
BORDER="#36363a"
TEXT="#ececee"
MUTED="#9a9aa0"
ACCENT="#2f6fbd"
BOT_ACCENT="#7cc7ff"
UI_FONT="Segoe UI"
UI_SEMIBOLD="Segoe UI Semibold"
CODE_FONT="Consolas"

class App(TkinterDnD.Tk):
    def __init__(self):
        super().__init__()
        self.title("DeepSeek Codex")
        try:
            icon=resource_path(os.path.join("assets","deepseek_codex.ico"))
            if os.path.exists(icon): self.iconbitmap(icon)
        except Exception: pass
        self.geometry("1260x820")
        self.minsize(960,650)
        self.cwd = ROOT
        self.chats = {}
        self.active_chats = {}
        self.custom_projects = []
        self.last_project = ROOT
        self.load_state()
        self.busy = False
        self.current_process = None
        self.cancel_requested = False
        self.link_seq = 0
        self.attachments = []
        self.attachment_images = []
        self.generated_attachments = set()
        self.show_actions = False
        self.show_changes = False
        self.show_files = False
        self.show_terminal = False
        self.terminal_busy = False
        self.terminal_process = None
        self.project_files = []
        self.filtered_project_files = []
        self.build()
        self.apply_pointer_cursors(self)
        self.configure(bg=BG); self.enable_dark_titlebar()
        self.refresh_projects(); self.restore_last_project()

    def apply_pointer_cursors(self,widget):
        for child in widget.winfo_children():
            try:
                if isinstance(child,tk.Button): child.config(cursor="hand2")
            except Exception: pass
            self.apply_pointer_cursors(child)

    def enable_dark_titlebar(self):
        if os.name!="nt": return
        try:
            self.update_idletasks()
            hwnd=ctypes.windll.user32.GetParent(self.winfo_id())
            value=ctypes.c_int(1)
            for attr in (20,19):
                try:
                    ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd,attr,ctypes.byref(value),ctypes.sizeof(value))
                    break
                except Exception: pass
        except Exception: pass

    def _rounded_rect(self,canvas,x1,y1,x2,y2,r,**kwargs):
        points=[
            x1+r,y1, x2-r,y1, x2,y1, x2,y1+r,
            x2,y2-r, x2,y2, x2-r,y2, x1+r,y2,
            x1,y2, x1,y2-r, x1,y1+r, x1,y1
        ]
        return canvas.create_polygon(points,smooth=True,splinesteps=24,**kwargs)

    def _resize_composer(self,event):
        w=max(40,event.width); h=max(40,event.height); r=16
        x1=y1=2; x2=w-2; y2=h-2
        points=[
            x1+r,y1, x2-r,y1, x2,y1, x2,y1+r,
            x2,y2-r, x2,y2, x2-r,y2, x1+r,y2,
            x1,y2, x1,y2-r, x1,y1+r, x1,y1
        ]
        self.composer_shell.coords(self.composer_outline,*points)
        self.composer_shell.itemconfigure(self.composer_window,width=max(20,w-12),height=max(20,h-12))
        self.composer_shell.coords(self.composer_window,6,6)

    def _set_composer_border(self,color):
        try: self.composer_shell.itemconfig(self.composer_outline,outline=color)
        except Exception: pass

    def load_state(self):
        try:
            with open(STATE,"r",encoding="utf-8") as fh: data=json.load(fh)
            self.chats=data.get("chats",{})
            self.active_chats=data.get("active_chats",{})
            self.custom_projects=data.get("custom_projects",[])
            self.last_project=data.get("last_project",ROOT)
            self.agent_mode=data.get("agent_mode","edit") if data.get("agent_mode") in ("edit","analysis") else "edit"
            self.usage=data.get("usage",{}) if isinstance(data.get("usage",{}),dict) else {}
            for key in ("requests","input_tokens","cached_input_tokens","cache_write_input_tokens","output_tokens","reasoning_output_tokens"):
                self.usage[key]=int(self.usage.get(key,0) or 0)
            if not self.chats:
                old_sessions=data.get("sessions",{}); old_histories=data.get("histories",{})
                for cwd in set(old_sessions) | set(old_histories):
                    msgs=old_histories.get(cwd,[])
                    title="Предыдущий чат"
                    for who,msg in msgs:
                        if who=="user" and msg.strip():
                            title=msg.strip().splitlines()[0][:38]; break
                    self.chats[cwd]=[{"id":"legacy","title":title,"session":old_sessions.get(cwd),"messages":msgs}]
                    self.active_chats[cwd]="legacy"
        except Exception:
            self.chats={}; self.active_chats={}; self.custom_projects=[]; self.last_project=ROOT
            self.agent_mode="edit"; self.usage={"requests":0,"input_tokens":0,"cached_input_tokens":0,"cache_write_input_tokens":0,"output_tokens":0,"reasoning_output_tokens":0}

    def save_state(self):
        try:
            os.makedirs(CODEX_HOME,exist_ok=True)
            with open(STATE,"w",encoding="utf-8") as fh:
                json.dump({"chats":self.chats,"active_chats":self.active_chats,"custom_projects":self.custom_projects,"last_project":self.last_project,"agent_mode":self.agent_mode,"usage":self.usage},fh,ensure_ascii=False,indent=2)
        except Exception: pass

    def build(self):
        self.columnconfigure(1, weight=1); self.rowconfigure(0, weight=1)
        side=tk.Frame(self, width=820, bg=SIDE,highlightthickness=1,highlightbackground="#2a2a2d"); side.grid(row=0,column=0,sticky="nsew")
        side.grid_propagate(False)
        tk.Label(side,text="DeepSeek Codex",fg=TEXT,bg=SIDE,font=(UI_SEMIBOLD,14)).pack(padx=16,pady=(18,12),anchor="w")
        tk.Button(side,text="＋  Новый чат",command=self.new_chat,bg=SIDE,fg=TEXT,activebackground=SURFACE,activeforeground=TEXT,relief="flat",bd=0,font=(UI_FONT,10),anchor="w").pack(fill="x",padx=8,pady=(4,8),ipadx=8,ipady=8)
        tk.Label(side,text="ПРОЕКТЫ",fg=MUTED,bg=SIDE,font=(UI_SEMIBOLD,8)).pack(padx=16,pady=(20,6),anchor="w")
        self.projects=tk.Listbox(side,height=6,bg=SIDE,fg="#d0d0d4",selectbackground="#2a2d33",selectforeground=TEXT,bd=0,highlightthickness=0,font=(UI_FONT,10),activestyle="none")
        self.projects.pack(fill="x",padx=12); self.projects.bind("<<ListboxSelect>>",self.pick_project); self.projects.configure(cursor="hand2")
        prow=tk.Frame(side,bg=SIDE); prow.pack(fill="x",padx=12,pady=(8,0))
        tk.Button(prow,text="＋  Проект",command=self.choose_project,bg=SIDE,fg="#c8c8cd",activebackground=SURFACE,activeforeground=TEXT,relief="flat",bd=0,font=(UI_FONT,9),anchor="w").pack(side="left",fill="x",expand=True,ipadx=8,ipady=7)
        tk.Button(prow,text="↗",command=self.open_project,bg=SIDE,fg=MUTED,activebackground=SIDE,activeforeground="#c8c8cc",relief="flat",bd=0,font=(UI_FONT,11),width=3).pack(side="right",padx=(6,0))
        tk.Label(side,text="ЧАТЫ",fg=MUTED,bg=SIDE,font=(UI_SEMIBOLD,8)).pack(padx=16,pady=(18,6),anchor="w")
        self.chat_search=tk.Entry(side,bg="#202023",fg="#b3b3b8",insertbackground=TEXT,relief="flat",bd=0,font=(UI_FONT,9),highlightthickness=1,highlightbackground="#202023",highlightcolor=ACCENT)
        self.chat_search.pack(fill="x",padx=12,pady=(0,8),ipady=5)
        self.chat_search.insert(0,"Поиск чатов")
        self.chat_search.bind("<FocusIn>",self.on_search_focus)
        self.chat_search.bind("<FocusOut>",self.on_search_blur)
        self.chat_search.bind("<KeyRelease>",lambda e:self.refresh_chat_list())
        self.chat_list=tk.Listbox(side,bg=SIDE,fg="#ccccd1",selectbackground="#2a2d33",selectforeground=TEXT,bd=0,highlightthickness=0,font=(UI_FONT,9),activestyle="none")
        self.chat_list.pack(fill="both",expand=True,padx=12,pady=(0,10)); self.chat_list.bind("<<ListboxSelect>>",self.pick_chat); self.chat_list.configure(cursor="hand2")
        self.chat_list.bind("<Button-3>",self.show_chat_menu)
        self.chat_menu=tk.Menu(self,tearoff=0,bg=SURFACE,fg=TEXT,activebackground="#333338",activeforeground=TEXT,bd=0)
        self.chat_menu.add_command(label="Закрепить",command=self.toggle_pin_chat)
        self.chat_menu.add_separator()
        self.chat_menu.add_command(label="Переименовать",command=self.rename_chat)
        self.chat_menu.add_command(label="Удалить",command=self.delete_chat)
        main=tk.Frame(self,bg=BG); main.grid(row=0,column=1,sticky="nsew"); main.columnconfigure(0,weight=1); main.columnconfigure(1,weight=0); main.rowconfigure(1,weight=1)
        top=tk.Frame(main,bg=BG); top.grid(row=0,column=0,sticky="ew",padx=40,pady=(14,10)); top.columnconfigure(0,weight=1)
        title_row=tk.Frame(top,bg=BG); title_row.grid(row=0,column=0,sticky="w")
        self.head_project=tk.Label(title_row,text=os.path.basename(ROOT),fg=TEXT,bg=BG,font=(UI_SEMIBOLD,11))
        self.head_project.pack(side="left")
        self.head_meta=tk.Label(title_row,text="  ·  DeepSeek Flash",fg=MUTED,bg=BG,font=(UI_FONT,9))
        self.head_meta.pack(side="left")
        self.branch_button=tk.Button(top,text="Ветка ▾",command=self.show_branch_menu,bg=BG,fg=MUTED,activebackground=SURFACE,activeforeground="#c2c2c6",relief="flat",bd=0,font=(UI_FONT,9))
        self.branch_button.grid(row=0,column=1,padx=(10,0),ipadx=5,ipady=2)
        self.branch_menu=tk.Menu(self,tearoff=0,bg=SURFACE,fg=TEXT,activebackground="#333338",activeforeground=TEXT,bd=0)
        self.checkpoint_button=tk.Button(top,text="Точки ▾",command=self.show_checkpoint_menu,bg=BG,fg=MUTED,activebackground=SURFACE,activeforeground="#c2c2c6",relief="flat",bd=0,font=(UI_FONT,9))
        self.checkpoint_button.grid(row=0,column=2,padx=(6,0),ipadx=5,ipady=2)
        self.checkpoint_menu=tk.Menu(self,tearoff=0,bg=SURFACE,fg=TEXT,activebackground="#333338",activeforeground=TEXT,bd=0)
        self.actions_button=tk.Button(top,text="Действия ▸",command=self.toggle_actions,bg=BG,fg=MUTED,activebackground=SURFACE,activeforeground="#c2c2c6",relief="flat",bd=0,font=(UI_FONT,9))
        self.actions_button.grid(row=0,column=3,padx=(6,0),ipadx=5,ipady=2)
        self.changes_button=tk.Button(top,text="Изменения ▸",command=self.toggle_changes,bg=BG,fg=MUTED,activebackground=SURFACE,activeforeground="#c2c2c6",relief="flat",bd=0,font=(UI_FONT,9))
        self.changes_button.grid(row=0,column=4,padx=(6,0),ipadx=5,ipady=2)
        self.files_button=tk.Button(top,text="Файлы ▸",command=self.toggle_files,bg=BG,fg=MUTED,activebackground=SURFACE,activeforeground="#c2c2c6",relief="flat",bd=0,font=(UI_FONT,9))
        self.files_button.grid(row=0,column=5,padx=(6,0),ipadx=5,ipady=2)
        self.terminal_button=tk.Button(top,text="Терминал ▸",command=self.toggle_terminal,bg=BG,fg=MUTED,activebackground=SURFACE,activeforeground="#c2c2c6",relief="flat",bd=0,font=(UI_FONT,9))
        self.terminal_button.grid(row=0,column=6,padx=(6,0),ipadx=5,ipady=2)
        tk.Button(top,text="↗",command=self.open_project,bg=BG,fg=MUTED,activebackground=SURFACE,activeforeground="#c2c2c6",relief="flat",bd=0,font=(UI_FONT,11),width=2).grid(row=0,column=7,padx=(4,0),ipady=2)
        self.chat=tk.Text(main,bg=BG,fg=TEXT,insertbackground=TEXT,wrap="word",bd=0,font=(UI_FONT,12),padx=32,pady=22,spacing1=2,spacing2=2,spacing3=6)
        self.chat.grid(row=1,column=0,sticky="nsew",padx=(90,90),pady=(12,0))
        self.chat.tag_configure("user_hdr",foreground="#9ca3af",background=BG,font=(UI_SEMIBOLD,8),spacing1=1,spacing3=2)
        self.chat.tag_configure("bot_hdr",foreground="#b7c8dc",background=BG,font=(UI_SEMIBOLD,8),spacing1=1,spacing3=2)
        self.chat.tag_configure("system_hdr",foreground="#8f8f96",background=BG,font=(UI_SEMIBOLD,8),spacing1=1,spacing3=2)
        self.chat.tag_configure("card_user",background=BG,borderwidth=0,relief="flat",lmargin1=12,lmargin2=12,rmargin=12,spacing1=2,spacing3=3)
        self.chat.tag_configure("card_bot",background=BG,borderwidth=0,relief="flat",lmargin1=12,lmargin2=12,rmargin=12,spacing1=2,spacing3=3)
        self.chat.tag_configure("card_system",background=BG,borderwidth=0,relief="flat",lmargin1=12,lmargin2=12,rmargin=12,spacing1=2,spacing3=3)
        self.chat.tag_configure("code",foreground="#e1e1e4",background="#242427",font=(CODE_FONT,10),lmargin1=16,lmargin2=16,rmargin=160,spacing1=6,spacing3=6)
        self.chat.tag_configure("inline_code",foreground="#eeeeef",background="#303035",font=(CODE_FONT,10))
        self.chat.tag_configure("action",foreground="#71717a",font=(UI_FONT,8,"italic"),lmargin1=12,lmargin2=12,elide=True)
        self.chat.tag_configure("h1",foreground="#f4f4f6",font=(UI_SEMIBOLD,15),spacing1=12,spacing3=6)
        self.chat.tag_configure("h2",foreground="#f0f0f2",font=(UI_SEMIBOLD,13),spacing1=10,spacing3=4)
        self.chat.tag_configure("h3",foreground="#e8e8ea",font=(UI_SEMIBOLD,11),spacing1=8,spacing3=3)
        self.chat.tag_configure("bold",font=(UI_SEMIBOLD,12))
        self.chat.tag_configure("link",foreground="#8ab4f8",underline=True)
        self.chat.tag_configure("table",foreground="#e1e1e4",background="#242427",font=(CODE_FONT,10),lmargin1=16,lmargin2=16,rmargin=160,spacing1=3,spacing3=3)
        self.chat.tag_configure("empty_title",foreground="#ececef",font=(UI_SEMIBOLD,18),justify="center",spacing3=8)
        self.chat.tag_configure("empty_sub",foreground="#77777d",font=(UI_FONT,10),justify="center")
        self.chat.configure(state="disabled")
        self.chat_menu_copy=tk.Menu(self,tearoff=0,bg=SURFACE,fg=TEXT,activebackground="#333338",activeforeground=TEXT,bd=0)
        self.chat_menu_copy.add_command(label="Копировать выделенное",command=self.copy_chat_selection)
        self.chat_menu_copy.add_command(label="Копировать последний ответ DeepSeek",command=self.copy_last_bot_message)
        self.chat.bind("<Button-3>",self.show_chat_copy_menu)
        bottom=tk.Frame(main,bg=BG); bottom.grid(row=2,column=0,sticky="ew",padx=130,pady=(8,34)); bottom.columnconfigure(1,weight=1)
        self.attach_frame=tk.Frame(bottom,bg=BG)
        self.attach_frame.grid(row=0,column=0,columnspan=3,sticky="ew",pady=(0,6)); self.attach_frame.grid_remove()
        self.composer_shell=tk.Canvas(bottom,height=132,bg=BG,highlightthickness=0,bd=0)
        self.composer_shell.grid(row=1,column=0,columnspan=3,sticky="ew")
        self.composer_outline=self._rounded_rect(self.composer_shell,2,2,100,130,16,fill=SURFACE,outline="#333338",width=1)
        self.composer=tk.Frame(self.composer_shell,bg=SURFACE,bd=0,highlightthickness=0)
        self.composer.columnconfigure(0,weight=1)
        self.composer_window=self.composer_shell.create_window(6,6,anchor="nw",window=self.composer)
        self.composer_shell.bind("<Configure>",self._resize_composer)
        self.input=tk.Text(self.composer,height=3,bg=SURFACE,fg=TEXT,insertbackground=TEXT,wrap="word",font=(UI_FONT,11),relief="flat",padx=18,pady=14,highlightthickness=0)
        self.input.grid(row=0,column=0,sticky="ew",padx=2,pady=(2,0)); self.input.bind("<Return>",self.on_enter)
        self.input_placeholder="Сообщение DeepSeek…"; self.input.insert("1.0",self.input_placeholder); self.input.config(fg="#8f8f96")
        self.input.bind("<FocusIn>",self.on_input_focus); self.input.bind("<FocusOut>",self.on_input_blur)
        self.input.drop_target_register(DND_FILES); self.input.dnd_bind("<<Drop>>",self.on_drop_files)
        self.input.dnd_bind("<<DropEnter>>",self.on_drag_enter); self.input.dnd_bind("<<DropLeave>>",self.on_drag_leave)
        self.bind_all("<Control-KeyPress>",self.ctrl_key,add="+")
        self.chat.bind("<Control-KeyPress>",self.ctrl_key,add="+")
        self.input.bind_all("<Shift-Insert>",self.paste,add="+"); self.input.bind("<<Paste>>",self.paste)

        controls=tk.Frame(self.composer,bg=SURFACE); controls.grid(row=1,column=0,sticky="ew",padx=10,pady=(0,9)); controls.columnconfigure(5,weight=1)
        self.attach_button=tk.Button(controls,text="+",command=self.add_attachment,bg=SURFACE,fg="#d8d8dc",activebackground="#303034",activeforeground=TEXT,relief="flat",bd=0,font=(UI_SEMIBOLD,13),width=3,cursor="hand2")
        self.attach_button.grid(row=0,column=0,padx=(0,4),sticky="w")
        tk.Label(controls,text="DeepSeek Flash",fg="#c4c4ca",bg=SURFACE,font=(UI_FONT,9)).grid(row=0,column=1,padx=(2,8),sticky="w")
        self.agent_mode_button=tk.Button(controls,text="",command=self.show_agent_mode_menu,bg=SURFACE,fg="#bfc0c5",activebackground="#303034",activeforeground=TEXT,relief="flat",bd=0,font=(UI_FONT,9),cursor="hand2")
        self.agent_mode_button.grid(row=0,column=2,padx=(0,8),sticky="w")
        self.agent_mode_menu=tk.Menu(self,tearoff=0,bg=SURFACE,fg=TEXT,activebackground="#333338",activeforeground=TEXT,bd=0)
        self.usage_button=tk.Button(controls,text="",command=self.show_usage,bg=SURFACE,fg="#85858c",activebackground="#303034",activeforeground="#c8c8cc",relief="flat",bd=0,font=(UI_FONT,8),cursor="hand2")
        self.usage_button.grid(row=0,column=3,padx=(0,8),sticky="w")
        self.status=tk.Label(controls,text="",fg="#77777d",bg=SURFACE,font=(UI_FONT,9),anchor="w")
        self.status.grid(row=0,column=4,sticky="w")
        self.update_agent_mode_button(); self.update_usage_button()
        self.send_button=tk.Canvas(controls,width=36,height=36,bg=SURFACE,highlightthickness=0,bd=0,cursor="hand2")
        self.send_circle=self.send_button.create_oval(4,4,32,32,fill=ACCENT,outline="")
        self.send_button.create_text(18,18,text="↑",fill="white",font=(UI_SEMIBOLD,12))
        self.send_button.bind("<Button-1>",lambda e:self.send())
        self.send_button.bind("<Enter>",lambda e:self.send_button.itemconfig(self.send_circle,fill="#3b82d0"))
        self.send_button.bind("<Leave>",lambda e:self.send_button.itemconfig(self.send_circle,fill=ACCENT))
        self.send_button.grid(row=0,column=6,padx=(8,0),sticky="e")
        self.stop_button=tk.Button(controls,text="■",command=self.stop_agent,bg="#493030",fg="#f5f5f5",activebackground="#5a3838",activeforeground="white",relief="flat",bd=0,font=(UI_SEMIBOLD,10),width=3,height=1)
        self.stop_button.grid(row=0,column=6,padx=(8,0),sticky="e"); self.stop_button.grid_remove()
        self.changes_panel=tk.Frame(main,width=420,bg=SIDE,highlightthickness=1,highlightbackground=BORDER)
        self.changes_panel.grid(row=0,column=1,rowspan=4,sticky="nsew"); self.changes_panel.grid_propagate(False); self.changes_panel.grid_remove()
        ctop=tk.Frame(self.changes_panel,bg=SIDE); ctop.pack(fill="x",padx=14,pady=(14,9))
        tk.Label(ctop,text="Изменения",fg=TEXT,bg=SIDE,font=(UI_SEMIBOLD,11)).pack(side="left")
        tk.Button(ctop,text="↻",command=self.refresh_changes,bg=SIDE,fg=MUTED,activebackground=SIDE,activeforeground=TEXT,relief="flat",bd=0,font=(UI_FONT,11)).pack(side="right")
        self.change_list=tk.Listbox(self.changes_panel,height=8,bg=SIDE,fg="#c8c8cc",selectbackground="#2a2d33",selectforeground=TEXT,bd=0,highlightthickness=0,font=(CODE_FONT,9),activestyle="none")
        self.change_list.pack(fill="x",padx=10,pady=(0,6)); self.change_list.bind("<<ListboxSelect>>",self.show_selected_diff)
        self.change_list.bind("<Double-Button-1>",lambda e:self.open_selected_change())
        change_tools=tk.Frame(self.changes_panel,bg=SIDE); change_tools.pack(fill="x",padx=10,pady=(0,8))
        tk.Button(change_tools,text="Открыть",command=self.open_selected_change,bg=SURFACE,fg="#d6d6da",activebackground="#343438",activeforeground=TEXT,relief="flat",bd=0,font=(UI_FONT,8)).pack(side="left",ipadx=7,ipady=4)
        tk.Button(change_tools,text="Копировать diff",command=self.copy_selected_diff,bg=SURFACE,fg="#d6d6da",activebackground="#343438",activeforeground=TEXT,relief="flat",bd=0,font=(UI_FONT,8)).pack(side="left",padx=(6,0),ipadx=7,ipady=4)
        tk.Button(change_tools,text="Откатить",command=self.revert_selected_change,bg=SIDE,fg="#d68b8b",activebackground="#392525",activeforeground="#ffd6d6",relief="flat",bd=0,font=(UI_FONT,8)).pack(side="right",ipadx=7,ipady=4)
        self.diff_view=tk.Text(self.changes_panel,bg="#202023",fg="#d8d8dc",wrap="none",bd=0,font=(CODE_FONT,9),padx=12,pady=12)
        self.diff_view.pack(fill="both",expand=True,padx=10,pady=(0,10)); self.diff_view.configure(state="disabled")
        self.diff_view.tag_configure("add",foreground="#7bd88f"); self.diff_view.tag_configure("del",foreground="#ff7b72"); self.diff_view.tag_configure("hunk",foreground="#79a7ff"); self.diff_view.tag_configure("meta",foreground="#777777")

        self.files_panel=tk.Frame(main,width=420,bg=SIDE,highlightthickness=1,highlightbackground=BORDER)
        self.files_panel.grid(row=0,column=1,rowspan=4,sticky="nsew"); self.files_panel.grid_propagate(False); self.files_panel.grid_remove()
        ftop=tk.Frame(self.files_panel,bg=SIDE); ftop.pack(fill="x",padx=14,pady=(14,8))
        tk.Label(ftop,text="Файлы проекта",fg=TEXT,bg=SIDE,font=(UI_SEMIBOLD,11)).pack(side="left")
        tk.Button(ftop,text="↻",command=self.refresh_project_files,bg=SIDE,fg=MUTED,activebackground=SIDE,activeforeground=TEXT,relief="flat",bd=0,font=(UI_FONT,11)).pack(side="right")
        self.file_search=tk.Entry(self.files_panel,bg="#202023",fg="#b3b3b8",insertbackground=TEXT,relief="flat",bd=0,font=(UI_FONT,9),highlightthickness=1,highlightbackground="#202023",highlightcolor=ACCENT)
        self.file_search.pack(fill="x",padx=10,pady=(0,8),ipady=5)
        self.file_search.insert(0,"Поиск файлов")
        self.file_search.bind("<FocusIn>",self.on_file_search_focus); self.file_search.bind("<FocusOut>",self.on_file_search_blur); self.file_search.bind("<KeyRelease>",lambda e:self.filter_project_files())
        self.file_list=tk.Listbox(self.files_panel,height=12,bg=SIDE,fg="#c8c8cc",selectbackground="#2a2d33",selectforeground=TEXT,bd=0,highlightthickness=0,font=(CODE_FONT,9),activestyle="none")
        self.file_list.pack(fill="x",padx=10,pady=(0,6)); self.file_list.bind("<<ListboxSelect>>",self.preview_selected_file); self.file_list.bind("<Double-Button-1>",lambda e:self.open_selected_project_file())
        ftools=tk.Frame(self.files_panel,bg=SIDE); ftools.pack(fill="x",padx=10,pady=(0,8))
        tk.Button(ftools,text="Открыть",command=self.open_selected_project_file,bg=SURFACE,fg="#d6d6da",activebackground="#343438",activeforeground=TEXT,relief="flat",bd=0,font=(UI_FONT,8)).pack(side="left",ipadx=7,ipady=4)
        tk.Button(ftools,text="+ В контекст",command=self.add_selected_file_to_context,bg=SURFACE,fg="#d6d6da",activebackground="#343438",activeforeground=TEXT,relief="flat",bd=0,font=(UI_FONT,8)).pack(side="left",padx=(6,0),ipadx=7,ipady=4)
        self.file_preview=tk.Text(self.files_panel,bg="#202023",fg="#d8d8dc",wrap="none",bd=0,font=(CODE_FONT,9),padx=12,pady=12)
        self.file_preview.pack(fill="both",expand=True,padx=10,pady=(0,10)); self.file_preview.configure(state="disabled")

        self.terminal_panel=tk.Frame(main,width=500,bg=SIDE,highlightthickness=1,highlightbackground=BORDER)
        self.terminal_panel.grid(row=0,column=1,rowspan=4,sticky="nsew"); self.terminal_panel.grid_propagate(False); self.terminal_panel.grid_remove()
        ttop=tk.Frame(self.terminal_panel,bg=SIDE); ttop.pack(fill="x",padx=14,pady=(14,8))
        tk.Label(ttop,text="Терминал",fg=TEXT,bg=SIDE,font=(UI_SEMIBOLD,11)).pack(side="left")
        self.terminal_cwd_label=tk.Label(ttop,text="",fg=MUTED,bg=SIDE,font=(UI_FONT,8))
        self.terminal_cwd_label.pack(side="left",padx=(8,0))
        tk.Button(ttop,text="Очистить",command=self.clear_terminal,bg=SIDE,fg=MUTED,activebackground=SURFACE,activeforeground=TEXT,relief="flat",bd=0,font=(UI_FONT,8)).pack(side="right")
        self.terminal_output=tk.Text(self.terminal_panel,bg="#111113",fg="#d7d7da",insertbackground=TEXT,wrap="word",bd=0,font=(CODE_FONT,9),padx=12,pady=12)
        self.terminal_output.pack(fill="both",expand=True,padx=10,pady=(0,8)); self.terminal_output.configure(state="disabled")
        trow=tk.Frame(self.terminal_panel,bg=SIDE); trow.pack(fill="x",padx=10,pady=(0,10))
        self.terminal_input=tk.Entry(trow,bg="#202023",fg=TEXT,insertbackground=TEXT,relief="flat",bd=0,font=(CODE_FONT,9),highlightthickness=1,highlightbackground="#2d2d31",highlightcolor=ACCENT)
        self.terminal_input.pack(side="left",fill="x",expand=True,ipady=6); self.terminal_input.bind("<Return>",lambda e:self.run_terminal_command())
        self.terminal_run_button=tk.Button(trow,text="Запустить",command=self.run_terminal_command,bg=SURFACE,fg=TEXT,activebackground="#343438",activeforeground=TEXT,relief="flat",bd=0,font=(UI_FONT,8))
        self.terminal_run_button.pack(side="left",padx=(6,0),ipadx=8,ipady=5)
        self.terminal_stop_button=tk.Button(trow,text="Стоп",command=self.stop_terminal,bg="#493030",fg="#f5f5f5",activebackground="#5a3838",activeforeground="white",relief="flat",bd=0,font=(UI_FONT,8))
        self.terminal_stop_button.pack(side="left",padx=(6,0),ipadx=8,ipady=5); self.terminal_stop_button.pack_forget()
        # Empty state is rendered by show_history().

    def refresh_projects(self):
        self.projects.delete(0,"end"); self.project_paths=[]
        try:
            base=[]
            for x in sorted(os.listdir(ROOT)):
                path=os.path.normpath(os.path.join(ROOT,x))
                if os.path.isdir(path) and x!="DeepSeekCodexGUI": base.append(path)
            extra=[]
            for path in self.custom_projects:
                path=os.path.normpath(path)
                if os.path.isdir(path) and path not in base and path not in extra: extra.append(path)
            self.custom_projects=extra
            self.project_paths=base+extra
            for path in self.project_paths:
                label=os.path.basename(path) or path
                if path in extra: label+="  ↗"
                self.projects.insert("end",label)
        except Exception as e: self.say("system",str(e))

    def update_head(self):
        name=os.path.basename(self.cwd) or self.cwd
        code,out,_=self.git_run(["branch","--show-current"])
        branch=out.strip() if code==0 else ""
        self.head_project.config(text=name)
        self.head_meta.config(text=(f"  ·  {branch}  ·  DeepSeek Flash" if branch else "  ·  DeepSeek Flash"))
        if hasattr(self,"branch_button"):
            self.branch_button.config(text=((branch+" ▾") if branch else "Ветка ▾"),fg=(MUTED if branch else "#666"))

    def activate_project(self,path):
        path=os.path.normpath(path)
        if not os.path.isdir(path): return
        if self.cwd!=path and self.terminal_busy: self.stop_terminal()
        if self.cwd!=path and self.attachments: self.clear_attachments()
        self.cwd=path; self.last_project=path
        self.project_files=[]; self.filtered_project_files=[]
        self.update_head()
        self.refresh_chat_list(); self.show_history(); self.save_state(); self.refresh_changes()
        if self.show_files: self.refresh_project_files()
        else: self.update_files_button()
        self.update_checkpoint_button()
        if hasattr(self,"terminal_cwd_label"): self.terminal_cwd_label.config(text=os.path.basename(self.cwd) or self.cwd)

    def restore_last_project(self):
        target=self.last_project if os.path.isdir(self.last_project) else ROOT
        self.activate_project(target)
        for i,path in enumerate(getattr(self,"project_paths",[])):
            if os.path.normcase(path)==os.path.normcase(target):
                self.projects.selection_clear(0,"end"); self.projects.selection_set(i); self.projects.activate(i); self.projects.see(i); break

    def choose_project(self):
        if self.busy: return
        path=filedialog.askdirectory(title="Открыть проект",initialdir=self.cwd if os.path.isdir(self.cwd) else ROOT)
        if not path: return
        path=os.path.normpath(path)
        root_children=[os.path.normpath(os.path.join(ROOT,x)) for x in os.listdir(ROOT) if os.path.isdir(os.path.join(ROOT,x))]
        if path not in root_children and path!=os.path.normpath(ROOT) and path not in self.custom_projects:
            self.custom_projects.append(path)
        self.refresh_projects(); self.activate_project(path)
        for i,p in enumerate(self.project_paths):
            if os.path.normcase(p)==os.path.normcase(path):
                self.projects.selection_clear(0,"end"); self.projects.selection_set(i); self.projects.activate(i); self.projects.see(i); break

    def open_project(self):
        try:
            os.startfile(self.cwd)
        except Exception as e:
            self.say("system","Не удалось открыть папку: "+str(e))

    def show_chat_copy_menu(self,event):
        has_selection=True
        try: self.chat.get("sel.first","sel.last")
        except tk.TclError: has_selection=False
        try: self.chat_menu_copy.entryconfig(0,state=("normal" if has_selection else "disabled"))
        except Exception: pass
        try: self.chat_menu_copy.tk_popup(event.x_root,event.y_root)
        finally:
            try: self.chat_menu_copy.grab_release()
            except Exception: pass

    def copy_chat_selection(self):
        try:
            text=self.chat.get("sel.first","sel.last")
            self.clipboard_clear(); self.clipboard_append(text); self.update()
            self.status.config(text="Скопировано")
            self.after(1500,lambda:self.status.config(text="" if not self.busy else self.status.cget("text")))
        except tk.TclError: pass

    def copy_last_bot_message(self):
        chat=self.current_chat(False)
        if not chat: return
        for who,msg in reversed(chat.get("messages",[])):
            if who=="bot" and str(msg).strip():
                try:
                    self.clipboard_clear(); self.clipboard_append(str(msg)); self.update()
                    self.status.config(text="Ответ DeepSeek скопирован")
                    self.after(1500,lambda:self.status.config(text="" if not self.busy else self.status.cget("text")))
                except Exception: pass
                return
        messagebox.showinfo("Копирование","В этом чате пока нет ответа DeepSeek.",parent=self)

    def show_chat_menu(self,event):
        if self.busy: return
        if self.chat_list.size()==0: return
        idx=self.chat_list.nearest(event.y)
        self.chat_list.selection_clear(0,"end"); self.chat_list.selection_set(idx); self.chat_list.activate(idx)
        if idx < len(getattr(self,"chat_ids",[])):
            self.active_chats[self.cwd]=self.chat_ids[idx]; self.save_state(); self.show_history()
            chat=self.current_chat(False)
            self.chat_menu.entryconfig(0,label=("Открепить" if chat and chat.get("pinned") else "Закрепить"))
            self.chat_menu.tk_popup(event.x_root,event.y_root)

    def toggle_pin_chat(self):
        if self.busy: return
        chat=self.current_chat(False)
        if not chat: return
        chat["pinned"]=not bool(chat.get("pinned"))
        chat["updated"]=time.time()
        self.save_state(); self.refresh_chat_list()

    def rename_chat(self):
        if self.busy: return
        chat=self.current_chat(False)
        if not chat: return
        name=simpledialog.askstring("Переименовать чат","Новое название:",initialvalue=chat.get("title",""),parent=self)
        if name and name.strip():
            chat["title"]=name.strip()[:60]; self.save_state(); self.refresh_chat_list()

    def delete_chat(self):
        if self.busy: return
        chat=self.current_chat(False)
        if not chat: return
        if not messagebox.askyesno("Удалить чат",f'Удалить чат "{chat.get("title","Новый чат")}"?',parent=self): return
        self.chats[self.cwd]=[x for x in self.chats.get(self.cwd,[]) if x.get("id")!=chat.get("id")]
        if self.chats[self.cwd]: self.active_chats[self.cwd]=self.chats[self.cwd][0]["id"]
        else: self.active_chats.pop(self.cwd,None)
        self.save_state(); self.refresh_chat_list(); self.show_history()

    def get_chat(self,cwd,cid):
        for chat in self.chats.get(cwd,[]):
            if chat.get("id")==cid: return chat
        return None

    def current_chat(self,create=False):
        cid=self.active_chats.get(self.cwd); chat=self.get_chat(self.cwd,cid) if cid else None
        if not chat and self.chats.get(self.cwd):
            chat=self.chats[self.cwd][0]; self.active_chats[self.cwd]=chat["id"]
        if not chat and create: chat=self.create_chat()
        return chat

    def create_chat(self):
        cid=str(time.time_ns())
        chat={"id":cid,"title":"Новый чат","session":None,"messages":[],"updated":time.time()}
        self.chats.setdefault(self.cwd,[]).insert(0,chat); self.active_chats[self.cwd]=cid
        self.save_state(); self.refresh_chat_list()
        return chat

    def on_search_focus(self,event=None):
        if self.chat_search.get()=="Поиск чатов":
            self.chat_search.delete(0,"end"); self.chat_search.config(fg=TEXT)

    def on_search_blur(self,event=None):
        if not self.chat_search.get().strip():
            self.chat_search.insert(0,"Поиск чатов"); self.chat_search.config(fg=MUTED)

    def refresh_chat_list(self):
        self.chat_list.delete(0,"end"); self.chat_ids=[]
        active=self.active_chats.get(self.cwd)
        query=""
        if hasattr(self,"chat_search"):
            raw=self.chat_search.get().strip()
            if raw and raw!="Поиск чатов": query=raw.lower()
        chats=self.chats.get(self.cwd,[])
        chats.sort(key=lambda c:(not bool(c.get("pinned")), -float(c.get("updated",0))))
        shown=0
        for chat in chats:
            title=chat.get("title") or "Новый чат"
            if query:
                hay=[title]
                for who,msg in chat.get("messages",[]):
                    if who!="action" and msg: hay.append(str(msg))
                if query not in "\n".join(hay).lower(): continue
            shown_title=("★  "+title) if chat.get("pinned") else title
            self.chat_ids.append(chat["id"]); self.chat_list.insert("end",shown_title)
            if chat["id"]==active:
                self.chat_list.selection_set(shown); self.chat_list.activate(shown)
            shown+=1

    def pick_project(self,event=None):
        if self.busy: return
        s=self.projects.curselection()
        if s and s[0] < len(getattr(self,"project_paths",[])):
            self.activate_project(self.project_paths[s[0]])

    def pick_chat(self,event=None):
        s=self.chat_list.curselection()
        if s and s[0] < len(getattr(self,"chat_ids",[])):
            self.active_chats[self.cwd]=self.chat_ids[s[0]]; self.save_state(); self.show_history()

    def open_target(self,target):
        target=urllib.parse.unquote(target)
        try:
            if target.startswith(("http://","https://")):
                webbrowser.open(target); return
            if target.startswith("file://"): target=target[7:]
            if re.match(r"^/[A-Za-z]:/",target): target=target[1:]
            path=target.replace("/",os.sep)
            if not os.path.isabs(path): path=os.path.join(self.cwd,path)
            if not os.path.exists(path): path=re.sub(r":\\d+(?::\\d+)?$","",path)
            if os.path.exists(path): os.startfile(path)
        except Exception: pass

    def insert_link(self,label,target):
        self.link_seq+=1; tag=f"link_{self.link_seq}"
        self.chat.tag_configure(tag,foreground="#8ab4f8",underline=True)
        self.chat.tag_bind(tag,"<Enter>",lambda e:self.chat.config(cursor="hand2"))
        self.chat.tag_bind(tag,"<Leave>",lambda e:self.chat.config(cursor=""))
        self.chat.tag_bind(tag,"<Button-1>",lambda e,t=target:self.open_target(t))
        self.chat.insert("end",label,tag)

    def insert_inline(self,text):
        pattern=r"(\*\*[^*\n]+\*\*|`[^`\n]+`|\[[^\]\n]+\]\([^\)\n]+\))"
        for chunk in re.split(pattern,text):
            if not chunk: continue
            if chunk.startswith("**") and chunk.endswith("**"):
                self.chat.insert("end",chunk[2:-2],"bold")
            elif chunk.startswith("`") and chunk.endswith("`"):
                self.chat.insert("end",chunk[1:-1],"inline_code")
            elif chunk.startswith("[") and "](" in chunk and chunk.endswith(")"):
                pos=chunk.index("]("); self.insert_link(chunk[1:pos],chunk[pos+2:-1])
            else:
                self.chat.insert("end",chunk)

    def insert_formatted(self,msg):
        parts=msg.split("```")
        for i,part in enumerate(parts):
            if i % 2:
                lines=part.splitlines()
                if lines and re.fullmatch(r"[A-Za-z0-9_+.#-]{1,20}",lines[0].strip() or ""): lines=lines[1:]
                code="\n".join(lines).strip("\n")
                if code: self.chat.insert("end","\n"+code+"\n","code")
            else:
                for line in part.splitlines(keepends=True):
                    raw=line.rstrip("\r\n"); ending="\n" if line.endswith(("\n","\r")) else ""
                    if raw.startswith("### "):
                        self.chat.insert("end",raw[4:]+ending,"h3")
                    elif raw.startswith("## "):
                        self.chat.insert("end",raw[3:]+ending,"h2")
                    elif raw.startswith("# "):
                        self.chat.insert("end",raw[2:]+ending,"h1")
                    elif raw.strip().startswith("|") and raw.strip().endswith("|"):
                        cells=[c.strip() for c in raw.strip().strip("|").split("|")]
                        if not cells or not all(re.fullmatch(r":?-{3,}:?",c or "---") for c in cells):
                            self.chat.insert("end","  │  ".join(cells)+ending,"table")
                    elif re.match(r"^\s*[-*]\s+",raw):
                        prefix=re.match(r"^(\s*)[-*]\s+",raw).group(1)
                        body=re.sub(r"^\s*[-*]\s+","",raw)
                        self.chat.insert("end",prefix+"• "); self.insert_inline(body); self.chat.insert("end",ending)
                    else:
                        self.insert_inline(raw); self.chat.insert("end",ending)

    def insert_message(self,who,msg):
        if who=="action":
            self.chat.insert("end","\n⚙  "+msg+"\n","action"); return
        if who=="user":
            prefix="YOU"; hdr="user_hdr"; card="card_user"
        elif who=="bot":
            prefix="DEEPSEEK"; hdr="bot_hdr"; card="card_bot"
        else:
            prefix="SYSTEM"; hdr="system_hdr"; card="card_system"
        self.chat.insert("end","\n")
        start=self.chat.index("end-1c")
        self.chat.insert("end",prefix+"\n",hdr)
        self.insert_formatted(msg)
        self.chat.insert("end","\n")
        end=self.chat.index("end-1c")
        self.chat.tag_add(card,start,end)

    def action_count(self):
        chat=self.current_chat(False)
        return sum(1 for who,_ in chat.get("messages",[]) if who=="action") if chat else 0

    def update_action_button(self):
        count=self.action_count()
        arrow="▾" if self.show_actions else "▸"
        text=f"Действия {count} {arrow}" if count else f"Действия {arrow}"
        self.actions_button.config(text=text,fg="#9a9a9a" if count else "#666")

    def toggle_actions(self):
        self.show_actions=not self.show_actions
        self.chat.tag_configure("action",elide=not self.show_actions)
        self.update_action_button()

    def update_agent_mode_button(self):
        if not hasattr(self,"agent_mode_button"): return
        if self.agent_mode=="analysis":
            self.agent_mode_button.config(text="Только анализ ▾",fg="#aeb7c4")
        else:
            self.agent_mode_button.config(text="Редактирование ▾",fg="#bfc0c5")

    def show_agent_mode_menu(self):
        self.agent_mode_menu.delete(0,"end")
        edit_label=("✓  Редактирование" if self.agent_mode=="edit" else "Редактирование")
        analysis_label=("✓  Только анализ" if self.agent_mode=="analysis" else "Только анализ")
        self.agent_mode_menu.add_command(label=edit_label,command=lambda:self.set_agent_mode("edit"))
        self.agent_mode_menu.add_command(label=analysis_label,command=lambda:self.set_agent_mode("analysis"))
        self.agent_mode_menu.add_separator()
        self.agent_mode_menu.add_command(label="В режиме анализа файлы проекта доступны только для чтения.",state="disabled")
        try:
            x=self.agent_mode_button.winfo_rootx()
            y=self.agent_mode_button.winfo_rooty()+self.agent_mode_button.winfo_height()
            self.agent_mode_menu.tk_popup(x,y)
        finally:
            try: self.agent_mode_menu.grab_release()
            except Exception: pass

    def set_agent_mode(self,mode):
        if mode not in ("edit","analysis"): return
        if self.busy:
            messagebox.showinfo("Режим агента","Сначала дождись завершения текущего ответа.",parent=self); return
        self.agent_mode=mode
        self.update_agent_mode_button(); self.save_state()

    def _fmt_tokens(self,value):
        value=int(value or 0)
        if value>=1000000: return f"{value/1000000:.1f}M"
        if value>=1000: return f"{value/1000:.1f}k"
        return str(value)

    def update_usage_button(self):
        if not hasattr(self,"usage_button"): return
        req=int(self.usage.get("requests",0) or 0)
        inp=int(self.usage.get("input_tokens",0) or 0)
        out=int(self.usage.get("output_tokens",0) or 0)
        self.usage_button.config(text=f"API {req} · {self._fmt_tokens(inp)}↓ {self._fmt_tokens(out)}↑")

    def record_usage(self,usage=None,count_request=True):
        if count_request: self.usage["requests"]=int(self.usage.get("requests",0) or 0)+1
        if isinstance(usage,dict):
            for key in ("input_tokens","cached_input_tokens","cache_write_input_tokens","output_tokens","reasoning_output_tokens"):
                try: self.usage[key]=int(self.usage.get(key,0) or 0)+int(usage.get(key,0) or 0)
                except Exception: pass
        self.save_state(); self.update_usage_button()

    def show_usage(self):
        u=self.usage
        menu=tk.Menu(self,tearoff=0,bg=SURFACE,fg=TEXT,activebackground="#333338",activeforeground=TEXT,bd=0)
        menu.add_command(label=f"Запросов: {int(u.get('requests',0) or 0):,}".replace(","," "),state="disabled")
        menu.add_command(label=f"Input tokens: {int(u.get('input_tokens',0) or 0):,}".replace(","," "),state="disabled")
        menu.add_command(label=f"↳ cached: {int(u.get('cached_input_tokens',0) or 0):,}".replace(","," "),state="disabled")
        menu.add_command(label=f"Output tokens: {int(u.get('output_tokens',0) or 0):,}".replace(","," "),state="disabled")
        reasoning=int(u.get("reasoning_output_tokens",0) or 0)
        if reasoning: menu.add_command(label=f"↳ reasoning: {reasoning:,}".replace(","," "),state="disabled")
        menu.add_separator()
        menu.add_command(label="Сбросить счётчик…",command=self.reset_usage)
        try:
            x=self.usage_button.winfo_rootx()
            y=self.usage_button.winfo_rooty()+self.usage_button.winfo_height()
            menu.tk_popup(x,y)
        finally:
            try: menu.grab_release()
            except Exception: pass

    def reset_usage(self):
        if not messagebox.askyesno("Счётчик API","Сбросить накопленную статистику использования DeepSeek?",parent=self): return
        self.usage={"requests":0,"input_tokens":0,"cached_input_tokens":0,"cache_write_input_tokens":0,"output_tokens":0,"reasoning_output_tokens":0}
        self.save_state(); self.update_usage_button()

    def _checkpoint_key(self,cwd):
        raw=os.path.normcase(os.path.abspath(cwd)).encode("utf-8",errors="replace")
        return hashlib.sha1(raw).hexdigest()[:16]

    def _checkpoint_base(self,cwd):
        return os.path.join(CODEX_HOME,"checkpoints",self._checkpoint_key(cwd))

    def _checkpoint_files(self,cwd):
        skip_dirs={".git","node_modules","__pycache__",".venv","venv","env","dist","build",".idea",".vscode",".pytest_cache",".mypy_cache",".deepseek_attachments"}
        root=os.path.abspath(cwd)
        for base,dirs,names in os.walk(root,followlinks=False):
            dirs[:]=[x for x in dirs if x not in skip_dirs and not os.path.islink(os.path.join(base,x))]
            for name in names:
                full=os.path.join(base,name)
                try:
                    if os.path.islink(full) or os.path.getsize(full)>25*1024*1024: continue
                    yield os.path.relpath(full,root),full
                except Exception: continue

    def prune_checkpoints(self,cwd,keep=5):
        base=self._checkpoint_base(cwd)
        try:
            entries=[os.path.join(base,x) for x in os.listdir(base) if os.path.isdir(os.path.join(base,x))]
            entries.sort(key=lambda p:os.path.getmtime(p),reverse=True)
            for old in entries[keep:]: shutil.rmtree(old,ignore_errors=True)
        except Exception: pass

    def create_checkpoint(self,cwd,label="Контрольная точка",prune=True):
        root=os.path.abspath(cwd)
        base=self._checkpoint_base(root)
        cp=os.path.join(base,str(time.time_ns()))
        files_dir=os.path.join(cp,"files")
        manifest=[]
        try:
            os.makedirs(files_dir,exist_ok=False)
            for rel,src in self._checkpoint_files(root):
                dst=os.path.join(files_dir,rel)
                os.makedirs(os.path.dirname(dst),exist_ok=True)
                shutil.copy2(src,dst)
                manifest.append(rel)
            meta={"cwd":root,"created":time.time(),"label":(label or "Контрольная точка")[:120],"manifest":manifest}
            with open(os.path.join(cp,"meta.json"),"w",encoding="utf-8") as fh: json.dump(meta,fh,ensure_ascii=False,indent=2)
            if prune: self.prune_checkpoints(root)
            return cp,None
        except Exception as e:
            shutil.rmtree(cp,ignore_errors=True)
            return None,str(e)

    def checkpoint_entries(self,cwd=None):
        cwd=os.path.abspath(cwd or self.cwd); base=self._checkpoint_base(cwd); result=[]
        try:
            for name in os.listdir(base):
                cp=os.path.join(base,name); meta_path=os.path.join(cp,"meta.json")
                if not os.path.isfile(meta_path): continue
                try:
                    with open(meta_path,"r",encoding="utf-8") as fh: meta=json.load(fh)
                    if os.path.normcase(os.path.abspath(meta.get("cwd","")))==os.path.normcase(cwd): result.append((cp,meta))
                except Exception: pass
        except Exception: pass
        result.sort(key=lambda x:float(x[1].get("created",0)),reverse=True)
        return result

    def update_checkpoint_button(self):
        if not hasattr(self,"checkpoint_button"): return
        count=len(self.checkpoint_entries())
        self.checkpoint_button.config(text=(f"Точки {count} ▾" if count else "Точки ▾"),fg=(MUTED if count else "#777"))

    def show_checkpoint_menu(self):
        self.checkpoint_menu.delete(0,"end")
        self.checkpoint_menu.add_command(label="Создать точку сейчас",command=self.manual_checkpoint)
        entries=self.checkpoint_entries()
        if entries:
            self.checkpoint_menu.add_separator()
            for cp,meta in entries[:5]:
                stamp=time.strftime("%d.%m %H:%M",time.localtime(float(meta.get("created",0))))
                label=str(meta.get("label") or "Контрольная точка").replace("\n"," ").strip()
                if len(label)>34: label=label[:31]+"..."
                self.checkpoint_menu.add_command(label=f"{stamp} · {label}",command=lambda p=cp:self.restore_checkpoint(p))
        else:
            self.checkpoint_menu.add_separator(); self.checkpoint_menu.add_command(label="Сохранённых точек нет",state="disabled")
        try:
            x=self.checkpoint_button.winfo_rootx()
            y=self.checkpoint_button.winfo_rooty()+self.checkpoint_button.winfo_height()
            self.checkpoint_menu.tk_popup(x,y)
        finally:
            try: self.checkpoint_menu.grab_release()
            except Exception: pass

    def manual_checkpoint(self):
        if self.busy or self.terminal_busy:
            messagebox.showinfo("Контрольная точка","Сначала дождись завершения текущей операции.",parent=self); return
        cwd=self.cwd; self.status.config(text="Создаю контрольную точку…")
        threading.Thread(target=self._manual_checkpoint_worker,args=(cwd,),daemon=True).start()

    def _manual_checkpoint_worker(self,cwd):
        cp,err=self.create_checkpoint(cwd,"Создано вручную")
        self.after(0,lambda:self._checkpoint_created(cp,err,cwd))

    def _checkpoint_created(self,cp,err,cwd):
        if self.cwd==cwd: self.update_checkpoint_button()
        self.status.config(text=("Контрольная точка создана" if cp else "Не удалось создать точку"))
        if err: messagebox.showerror("Контрольная точка","Не удалось создать контрольную точку:\n"+err,parent=self)
        self.after(2200,lambda:self.status.config(text="" if not self.busy else self.status.cget("text")))

    def restore_checkpoint(self,cp):
        if self.busy or self.terminal_busy:
            messagebox.showinfo("Контрольная точка","Сначала дождись завершения текущей операции.",parent=self); return
        meta_path=os.path.join(cp,"meta.json")
        try:
            with open(meta_path,"r",encoding="utf-8") as fh: meta=json.load(fh)
        except Exception as e:
            messagebox.showerror("Контрольная точка","Не удалось прочитать точку:\n"+str(e),parent=self); return
        cwd=os.path.abspath(meta.get("cwd",""))
        if os.path.normcase(cwd)!=os.path.normcase(os.path.abspath(self.cwd)):
            messagebox.showerror("Контрольная точка","Эта точка относится к другому проекту.",parent=self); return
        stamp=time.strftime("%d.%m.%Y %H:%M",time.localtime(float(meta.get("created",0))))
        label=meta.get("label") or "Контрольная точка"
        text=(f"Восстановить проект до состояния:\n\n{stamp} · {label}\n\n"
              "Файлы, созданные после этой точки, будут удалены из восстанавливаемой части проекта. "
              "Перед восстановлением я автоматически создам ещё одну защитную точку.")
        if not messagebox.askyesno("Восстановить проект",text,parent=self): return
        self.status.config(text="Восстанавливаю контрольную точку…")
        threading.Thread(target=self._restore_checkpoint_worker,args=(cp,meta,cwd),daemon=True).start()

    def _restore_checkpoint_worker(self,cp,meta,cwd):
        safety,_=self.create_checkpoint(cwd,"Перед восстановлением",prune=False)
        err=None
        try:
            target=set(meta.get("manifest",[]))
            current={rel for rel,_ in self._checkpoint_files(cwd)}
            for rel in current-target:
                path=os.path.join(cwd,rel)
                try:
                    if os.path.isfile(path): os.remove(path)
                except Exception: pass
            files_dir=os.path.join(cp,"files")
            for rel in target:
                src=os.path.join(files_dir,rel); dst=os.path.join(cwd,rel)
                if not os.path.isfile(src): continue
                os.makedirs(os.path.dirname(dst),exist_ok=True); shutil.copy2(src,dst)
            for base,dirs,files in os.walk(cwd,topdown=False):
                if base==cwd: continue
                try:
                    if not os.listdir(base): os.rmdir(base)
                except Exception: pass
            self.prune_checkpoints(cwd)
        except Exception as e: err=str(e)
        self.after(0,lambda:self._checkpoint_restored(err,cwd))

    def _checkpoint_restored(self,err,cwd):
        if err:
            messagebox.showerror("Контрольная точка","Восстановление завершилось с ошибкой:\n"+err,parent=self)
            self.status.config(text="Ошибка восстановления")
        else:
            self.status.config(text="Проект восстановлен")
            if self.cwd==cwd:
                self.update_head(); self.refresh_changes()
                if self.show_files: self.refresh_project_files()
                self.update_checkpoint_button()
        self.after(2500,lambda:self.status.config(text="" if not self.busy else self.status.cget("text")))

    def show_branch_menu(self):
        self.branch_menu.delete(0,"end")
        code,inside,_=self.git_run(["rev-parse","--is-inside-work-tree"])
        if code!=0 or inside.strip()!="true":
            self.branch_menu.add_command(label="Не Git-репозиторий",state="disabled")
        else:
            _,cur,_=self.git_run(["branch","--show-current"]); current=cur.strip()
            code,out,err=self.git_run(["for-each-ref","--format=%(refname:short)","refs/heads/"])
            branches=sorted([x.strip() for x in out.splitlines() if x.strip()],key=str.lower) if code==0 else []
            self.branch_menu.add_command(label="Создать новую ветку…",command=self.create_branch)
            self.branch_menu.add_separator()
            if not branches:
                self.branch_menu.add_command(label="Локальных веток нет",state="disabled")
            else:
                shown=branches[:30]
                for branch in shown:
                    label=("✓  "+branch) if branch==current else branch
                    self.branch_menu.add_command(label=label,state=("disabled" if branch==current else "normal"),command=lambda b=branch:self.switch_branch(b))
                if len(branches)>len(shown):
                    self.branch_menu.add_separator()
                    self.branch_menu.add_command(label=f"Ещё {len(branches)-len(shown)} веток…",state="disabled")
        try:
            x=self.branch_button.winfo_rootx()
            y=self.branch_button.winfo_rooty()+self.branch_button.winfo_height()
            self.branch_menu.tk_popup(x,y)
        finally:
            try: self.branch_menu.grab_release()
            except Exception: pass

    def branch_change_blocked(self):
        if self.busy:
            messagebox.showinfo("Git-ветки","Сначала дождись завершения ответа DeepSeek.",parent=self); return True
        if self.terminal_busy:
            messagebox.showinfo("Git-ветки","Сначала останови выполняющуюся команду в терминале.",parent=self); return True
        changes=self.get_changes()
        if changes:
            messagebox.showwarning("Git-ветки",
                f"В проекте есть незакоммиченные изменения ({len(changes)}).\n\n"
                "Для безопасного переключения сначала закоммить, откати или спрячь изменения.",
                parent=self)
            return True
        return False

    def switch_branch(self,name):
        if self.branch_change_blocked(): return
        code,out,err=self.git_run(["switch",name])
        if code!=0:
            code,out,err=self.git_run(["checkout",name])
        if code!=0:
            messagebox.showerror("Переключить ветку",(err or out or "Git не смог переключить ветку.").strip(),parent=self); return
        self.update_head(); self.refresh_changes()
        if self.show_files: self.refresh_project_files()
        self.status.config(text=f"Ветка: {name}")
        self.after(1800,lambda:self.status.config(text="" if not self.busy else self.status.cget("text")))

    def create_branch(self):
        if self.branch_change_blocked(): return
        name=simpledialog.askstring("Новая ветка","Название новой ветки:",parent=self)
        if not name or not name.strip(): return
        name=name.strip()
        code,_,err=self.git_run(["check-ref-format","--branch",name])
        if code!=0:
            messagebox.showerror("Новая ветка","Недопустимое имя ветки.\n\n"+(err or ""),parent=self); return
        code,out,err=self.git_run(["show-ref","--verify","--quiet",f"refs/heads/{name}"])
        if code==0:
            messagebox.showinfo("Новая ветка",f'Ветка "{name}" уже существует.',parent=self); return
        code,out,err=self.git_run(["switch","-c",name])
        if code!=0:
            code,out,err=self.git_run(["checkout","-b",name])
        if code!=0:
            messagebox.showerror("Новая ветка",(err or out or "Git не смог создать ветку.").strip(),parent=self); return
        self.update_head(); self.refresh_changes()
        if self.show_files: self.refresh_project_files()
        self.status.config(text=f"Создана ветка: {name}")
        self.after(1800,lambda:self.status.config(text="" if not self.busy else self.status.cget("text")))

    def git_run(self,args):
        try:
            r=subprocess.run(["git","-C",self.cwd,"-c","core.quotepath=false"]+args,capture_output=True,text=True,encoding="utf-8",errors="replace",creationflags=(subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0),timeout=8)
            return r.returncode,r.stdout,r.stderr
        except Exception as e:
            return 1,"",str(e)

    def get_changes(self):
        code,out,_=self.git_run(["status","--porcelain=v1"])
        if code!=0: return []
        result=[]
        for line in out.splitlines():
            if len(line)<4: continue
            status=line[:2]; path=line[3:]
            if " -> " in path: path=path.split(" -> ",1)[1]
            result.append((status,path))
        return result

    def update_changes_button(self,changes=None):
        changes=self.get_changes() if changes is None else changes
        count=len(changes); arrow="▾" if self.show_changes else "▸"
        self.changes_button.config(text=(f"Изменения {count} {arrow}" if count else f"Изменения {arrow}"),fg=("#a8a8a8" if count else "#666"))

    def toggle_changes(self):
        self.show_changes=not self.show_changes
        if self.show_changes:
            if self.show_files:
                self.show_files=False; self.files_panel.grid_remove(); self.update_files_button()
            if self.show_terminal:
                self.show_terminal=False; self.terminal_panel.grid_remove(); self.update_terminal_button()
            self.changes_panel.grid(); self.refresh_changes()
        else:
            self.changes_panel.grid_remove(); self.update_changes_button()

    def update_files_button(self):
        arrow="▾" if self.show_files else "▸"
        count=len(getattr(self,"project_files",[]))
        self.files_button.config(text=(f"Файлы {count} {arrow}" if count else f"Файлы {arrow}"),fg=("#a8a8a8" if count else "#777"))

    def toggle_files(self):
        self.show_files=not self.show_files
        if self.show_files:
            if self.show_changes:
                self.show_changes=False; self.changes_panel.grid_remove(); self.update_changes_button()
            if self.show_terminal:
                self.show_terminal=False; self.terminal_panel.grid_remove(); self.update_terminal_button()
            self.files_panel.grid(); self.refresh_project_files()
        else:
            self.files_panel.grid_remove(); self.update_files_button()

    def update_terminal_button(self):
        arrow="▾" if self.show_terminal else "▸"
        self.terminal_button.config(text=f"Терминал {arrow}",fg=("#a8a8a8" if self.show_terminal else MUTED))

    def toggle_terminal(self):
        self.show_terminal=not self.show_terminal
        if self.show_terminal:
            if self.show_changes:
                self.show_changes=False; self.changes_panel.grid_remove(); self.update_changes_button()
            if self.show_files:
                self.show_files=False; self.files_panel.grid_remove(); self.update_files_button()
            self.terminal_panel.grid()
            self.terminal_cwd_label.config(text=os.path.basename(self.cwd) or self.cwd)
            self.terminal_input.focus_set()
        else:
            self.terminal_panel.grid_remove()
        self.update_terminal_button()

    def append_terminal(self,text):
        if not text: return
        self.terminal_output.configure(state="normal")
        self.terminal_output.insert("end",text)
        self.terminal_output.see("end")
        self.terminal_output.configure(state="disabled")

    def clear_terminal(self):
        self.terminal_output.configure(state="normal"); self.terminal_output.delete("1.0","end"); self.terminal_output.configure(state="disabled")

    def run_terminal_command(self):
        if self.terminal_busy: return
        command=self.terminal_input.get().strip()
        if not command: return
        cwd=self.cwd
        self.terminal_input.delete(0,"end")
        self.append_terminal(f"PS {cwd}> {command}\n")
        self.terminal_busy=True
        self.terminal_run_button.pack_forget()
        self.terminal_stop_button.pack(side="left",padx=(6,0),ipadx=8,ipady=5)
        threading.Thread(target=self._terminal_worker,args=(command,cwd),daemon=True).start()

    def _terminal_worker(self,command,cwd):
        prefix='[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new(); $OutputEncoding=[Console]::OutputEncoding; '
        try:
            flags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0
            p=subprocess.Popen(["powershell.exe","-NoLogo","-NoProfile","-ExecutionPolicy","Bypass","-Command",prefix+command],
                cwd=cwd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding="utf-8",errors="replace",
                stdin=subprocess.DEVNULL,bufsize=1,creationflags=flags)
            self.terminal_process=p
            for line in p.stdout:
                self.after(0,lambda x=line:self.append_terminal(x))
            code=p.wait()
            self.after(0,lambda c=code:self.finish_terminal(c))
        except Exception as e:
            err=str(e)
            self.after(0,lambda x=err:self.append_terminal("Ошибка запуска: "+x+"\n"))
            self.after(0,lambda:self.finish_terminal(-1))

    def stop_terminal(self):
        p=self.terminal_process
        if not self.terminal_busy or not p: return
        self.append_terminal("\n[остановка команды]\n")
        try:
            if os.name=="nt":
                subprocess.run(["taskkill","/PID",str(p.pid),"/T","/F"],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW,timeout=5)
            elif p.poll() is None: p.terminate()
        except Exception: pass

    def finish_terminal(self,code):
        self.terminal_process=None; self.terminal_busy=False
        self.terminal_stop_button.pack_forget()
        self.terminal_run_button.pack(side="left",padx=(6,0),ipadx=8,ipady=5)
        self.append_terminal(f"\n[код завершения: {code}]\n\n")
        self.refresh_changes()
        if self.show_files: self.refresh_project_files()
        self.terminal_input.focus_set()

    def on_file_search_focus(self,event=None):
        if self.file_search.get()=="Поиск файлов":
            self.file_search.delete(0,"end"); self.file_search.config(fg=TEXT)

    def on_file_search_blur(self,event=None):
        if not self.file_search.get().strip():
            self.file_search.insert(0,"Поиск файлов"); self.file_search.config(fg=MUTED)

    def refresh_project_files(self):
        skip_dirs={".git","node_modules","__pycache__",".venv","venv","env","dist","build",".idea",".vscode",".pytest_cache",".mypy_cache"}
        files=[]
        root=os.path.abspath(self.cwd)
        try:
            for base,dirs,names in os.walk(root):
                dirs[:]=[x for x in dirs if x not in skip_dirs and not x.startswith(".deepseek_attachments")]
                for name in names:
                    full=os.path.join(base,name)
                    rel=os.path.relpath(full,root)
                    files.append(rel)
                    if len(files)>=2500: break
                if len(files)>=2500: break
        except Exception: files=[]
        self.project_files=sorted(files,key=lambda x:x.lower())
        self.filter_project_files(); self.update_files_button()

    def filter_project_files(self):
        query=""
        if hasattr(self,"file_search"):
            raw=self.file_search.get().strip()
            if raw and raw!="Поиск файлов": query=raw.lower()
        self.filtered_project_files=[p for p in self.project_files if not query or query in p.lower()]
        self.file_list.delete(0,"end")
        for rel in self.filtered_project_files[:1000]: self.file_list.insert("end",rel)
        self.set_file_preview("" if self.filtered_project_files else "Файлы не найдены.")

    def selected_project_file(self):
        s=self.file_list.curselection()
        if not s or s[0]>=len(self.filtered_project_files): return None
        return os.path.normpath(os.path.join(self.cwd,self.filtered_project_files[s[0]]))

    def set_file_preview(self,text):
        self.file_preview.configure(state="normal"); self.file_preview.delete("1.0","end"); self.file_preview.insert("1.0",text); self.file_preview.configure(state="disabled")

    def preview_selected_file(self,event=None):
        path=self.selected_project_file()
        if not path or not os.path.isfile(path): return
        try:
            size=os.path.getsize(path)
            if size>300000:
                self.set_file_preview(f"{os.path.relpath(path,self.cwd)}\n\nФайл слишком большой для предпросмотра ({size//1024} КБ)."); return
            with open(path,"rb") as fh: raw=fh.read(300000)
            if b"\x00" in raw:
                self.set_file_preview(f"{os.path.relpath(path,self.cwd)}\n\nБинарный файл. Предпросмотр недоступен."); return
            text=raw.decode("utf-8",errors="replace")
            self.set_file_preview(text)
        except Exception as e:
            self.set_file_preview("Не удалось прочитать файл:\n"+str(e))

    def open_selected_project_file(self):
        path=self.selected_project_file()
        if not path: return
        try: os.startfile(path)
        except Exception as e: messagebox.showerror("Открыть файл","Не удалось открыть файл:\n"+str(e),parent=self)

    def add_selected_file_to_context(self):
        path=self.selected_project_file()
        if not path: return
        self.add_attachment_paths([path])
        self.status.config(text="Файл добавлен в контекст")
        self.after(1800,lambda:self.status.config(text="" if not self.busy else self.status.cget("text")))

    def set_diff_text(self,text):
        self.diff_view.configure(state="normal"); self.diff_view.delete("1.0","end")
        for line in text.splitlines(True):
            tag=None
            if line.startswith("+++") or line.startswith("---"): tag="meta"
            elif line.startswith("+"): tag="add"
            elif line.startswith("-"): tag="del"
            elif line.startswith("@@"): tag="hunk"
            elif line.startswith(("diff ","index ")): tag="meta"
            self.diff_view.insert("end",line,tag)
        self.diff_view.configure(state="disabled")

    def refresh_changes(self):
        changes=self.get_changes(); self.change_items=changes
        self.change_list.delete(0,"end")
        for status,path in changes: self.change_list.insert("end",f"{status}  {path}")
        self.update_changes_button(changes)
        if not changes:
            self.set_diff_text("Нет незакоммиченных изменений." if os.path.isdir(os.path.join(self.cwd,".git")) else "Проект не является Git-репозиторием.")
        elif self.show_changes:
            self.change_list.selection_set(0); self.change_list.activate(0); self.show_selected_diff()

    def show_selected_diff(self,event=None):
        s=self.change_list.curselection()
        if not s or s[0]>=len(getattr(self,"change_items",[])): return
        status,path=self.change_items[s[0]]
        if status=="??":
            full=os.path.join(self.cwd,path)
            try:
                if os.path.getsize(full)>250000: text=f"Новый файл: {path}\n\nФайл слишком большой для предпросмотра."
                else:
                    with open(full,"r",encoding="utf-8",errors="replace") as fh: text=f"Новый файл: {path}\n\n"+fh.read(200000)
            except Exception:
                text=f"Новый файл: {path}\n\nБинарный файл или предпросмотр недоступен."
        else:
            _,work,_=self.git_run(["diff","--",path]); _,staged,_=self.git_run(["diff","--cached","--",path])
            text=(staged+("\n" if staged and work else "")+work).strip() or f"{status}  {path}\n\nТекстовый diff недоступен."
        self.set_diff_text(text)

    def selected_change(self):
        s=self.change_list.curselection()
        if not s or s[0]>=len(getattr(self,"change_items",[])): return None
        return self.change_items[s[0]]

    def open_selected_change(self):
        item=self.selected_change()
        if not item: return
        _,path=item
        full=os.path.normpath(os.path.join(self.cwd,path))
        if not os.path.exists(full):
            messagebox.showinfo("Открыть файл","Файл сейчас отсутствует в рабочей папке. Возможно, он удалён или переименован.",parent=self)
            return
        try: os.startfile(full)
        except Exception as e: messagebox.showerror("Открыть файл","Не удалось открыть файл:\n"+str(e),parent=self)

    def copy_selected_diff(self):
        item=self.selected_change()
        if not item: return
        text=self.diff_view.get("1.0","end-1c").strip()
        if not text: return
        try:
            self.clipboard_clear(); self.clipboard_append(text); self.update()
            self.status.config(text="Diff скопирован")
            self.after(1800,lambda:self.status.config(text="" if not self.busy else self.status.cget("text")))
        except Exception as e:
            messagebox.showerror("Копировать diff","Не удалось скопировать diff:\n"+str(e),parent=self)

    def revert_selected_change(self):
        item=self.selected_change()
        if not item: return
        status,path=item
        if status=="??":
            messagebox.showinfo("Откатить файл","Новый неотслеживаемый файл Git откатить не может. Я не удаляю такие файлы автоматически.",parent=self)
            return
        warning=(f"Вернуть файл к состоянию последнего коммита?\n\n{path}\n\n"
                 "Будут удалены все локальные изменения этого файла, включая staged-изменения. Это действие нельзя отменить через DeepSeek Codex.")
        if not messagebox.askyesno("Откатить изменения",warning,parent=self): return
        code,out,err=self.git_run(["restore","--source=HEAD","--staged","--worktree","--",path])
        if code!=0:
            messagebox.showerror("Откатить изменения",(err or out or "Git не смог откатить файл.").strip(),parent=self)
            return
        self.refresh_changes()
        self.status.config(text="Файл восстановлен")
        self.after(1800,lambda:self.status.config(text="" if not self.busy else self.status.cget("text")))

    def show_history(self):
        self.chat.configure(state="normal"); self.chat.delete("1.0","end")
        chat=self.current_chat(False)
        messages=chat.get("messages",[]) if chat else []
        if messages:
            for who,msg in messages: self.insert_message(who,msg)
        else:
            self.chat.insert("end","\n\n\n\nЧем займёмся?\n","empty_title")
            self.chat.insert("end",(os.path.basename(self.cwd) or self.cwd)+"  ·  DeepSeek Flash","empty_sub")
        self.chat.tag_configure("action",elide=not self.show_actions)
        self.chat.configure(state="disabled")
        if messages: self.chat.see("end")
        self.update_action_button()

    def new_chat(self):
        if self.busy: return
        self.create_chat(); self.show_history(); self.input.focus_set()

    def say(self,who,msg):
        self.chat.configure(state="normal"); self.insert_message(who,msg)
        self.chat.see("end"); self.chat.configure(state="disabled")

    def on_input_focus(self,event=None):
        self._set_composer_border(ACCENT)
        if self.input.get("1.0","end-1c")==self.input_placeholder:
            self.input.delete("1.0","end"); self.input.config(fg=TEXT)

    def on_input_blur(self,event=None):
        self._set_composer_border("#333338")
        if not self.input.get("1.0","end-1c").strip():
            self.input.delete("1.0","end"); self.input.insert("1.0",self.input_placeholder); self.input.config(fg="#8f8f96")

    def input_text(self):
        value=self.input.get("1.0","end-1c")
        return "" if value==self.input_placeholder else value.strip()

    def ctrl_key(self,event):
        # Physical keycodes make Ctrl shortcuts work on RU/EN layouts.
        widget=self.focus_get()
        if event.keycode == 86 and widget == self.input: return self.paste(event)
        if event.keycode == 67 and widget in (self.input,self.chat):
            try:
                text=widget.get("sel.first","sel.last"); self.clipboard_clear(); self.clipboard_append(text)
            except tk.TclError: pass
            return "break"
        if event.keycode == 65 and widget in (self.input,self.chat):
            widget.tag_add("sel","1.0","end-1c"); return "break"
        if event.keycode == 75:
            self.chat_search.focus_set(); self.chat_search.selection_range(0,"end"); return "break"
        if event.keycode == 78:
            self.new_chat(); return "break"

    def add_attachment(self):
        if self.busy: return
        files=filedialog.askopenfilenames(title="Прикрепить файлы",initialdir=self.cwd)
        self.add_attachment_paths(files)

    def add_attachment_paths(self,paths):
        added=False
        for path in paths:
            path=os.path.normpath(path)
            if os.path.isfile(path) and path not in self.attachments:
                self.attachments.append(path); added=True
        if added: self.update_attachment_bar()

    def on_drag_enter(self,event):
        self._set_composer_border(ACCENT); return event.action

    def on_drag_leave(self,event):
        self._set_composer_border("#333338"); return event.action

    def on_drop_files(self,event):
        self._set_composer_border("#333338")
        if self.busy: return event.action
        try: paths=self.tk.splitlist(event.data)
        except Exception: paths=[]
        self.add_attachment_paths(paths)
        return event.action

    def cleanup_generated_source(self,path):
        if path in self.generated_attachments:
            try:
                if os.path.isfile(path): os.remove(path)
            except Exception: pass
            self.generated_attachments.discard(path)

    def remove_attachment(self,path):
        self.attachments=[x for x in self.attachments if x!=path]; self.cleanup_generated_source(path); self.update_attachment_bar()

    def clear_attachments(self):
        for path in list(self.attachments): self.cleanup_generated_source(path)
        self.attachments=[]; self.update_attachment_bar()

    def update_attachment_bar(self):
        for child in self.attach_frame.winfo_children(): child.destroy()
        self.attachment_images=[]
        if not self.attachments:
            self.attach_frame.grid_remove(); return
        self.attach_frame.grid()
        for path in self.attachments[:5]:
            chip=tk.Frame(self.attach_frame,bg=SURFACE,highlightthickness=1,highlightbackground=BORDER)
            chip.pack(side="left",padx=(0,7))
            ext=os.path.splitext(path)[1].lower()
            if ext in (".png",".jpg",".jpeg",".gif",".bmp",".webp"):
                try:
                    im=Image.open(path); im.thumbnail((34,34))
                    photo=ImageTk.PhotoImage(im.copy()); self.attachment_images.append(photo)
                    tk.Label(chip,image=photo,bg=SURFACE).pack(side="left",padx=(6,4),pady=5)
                except Exception: pass
            name=os.path.basename(path)
            shown=name if len(name)<=25 else name[:22]+"..."
            tk.Label(chip,text=shown,fg="#e6e6e9",bg=SURFACE,font=(UI_FONT,9)).pack(side="left",padx=(5,3),pady=7)
            tk.Button(chip,text="×",command=lambda p=path:self.remove_attachment(p),bg=SURFACE,fg=MUTED,activebackground="#303034",activeforeground=TEXT,relief="flat",bd=0,font=(UI_FONT,11),width=2).pack(side="left",padx=(0,3))
        if len(self.attachments)>5:
            tk.Label(self.attach_frame,text=f"+{len(self.attachments)-5}",fg="#bdbdbd",bg="#292929",font=("Segoe UI",9)).pack(side="left",padx=(0,7),ipadx=8,ipady=7)
        tk.Button(self.attach_frame,text="Очистить",command=self.clear_attachments,bg=BG,fg=MUTED,activebackground=BG,activeforeground="#c2c2c6",relief="flat",bd=0,font=(UI_FONT,8)).pack(side="left")

    def prepare_attachments(self,files,cwd):
        staged=[]; temp_dir=None
        root=os.path.abspath(cwd); holder=os.path.join(root,".deepseek_attachments")
        try:
            git_dir=os.path.join(root,".git")
            if os.path.isdir(git_dir):
                info=os.path.join(git_dir,"info"); os.makedirs(info,exist_ok=True)
                exclude=os.path.join(info,"exclude")
                current=open(exclude,encoding="utf-8").read() if os.path.exists(exclude) else ""
                if ".deepseek_attachments/" not in current:
                    with open(exclude,"a",encoding="utf-8") as fh: fh.write("\n.deepseek_attachments/\n")
            if os.path.isdir(holder):
                cutoff=time.time()-86400
                for name in os.listdir(holder):
                    path=os.path.join(holder,name)
                    if os.path.isdir(path) and os.path.getmtime(path)<cutoff: shutil.rmtree(path,ignore_errors=True)
        except Exception: pass
        for src in files:
            src=os.path.abspath(src)
            try: inside=os.path.commonpath([src,root])==root
            except ValueError: inside=False
            if inside:
                staged.append(src); continue
            if temp_dir is None:
                temp_dir=os.path.join(root,".deepseek_attachments",str(time.time_ns()))
                os.makedirs(temp_dir,exist_ok=True)
            base=os.path.basename(src); name=base; n=1
            while os.path.exists(os.path.join(temp_dir,name)):
                stem,ext=os.path.splitext(base); name=f"{stem}_{n}{ext}"; n+=1
            dst=os.path.join(temp_dir,name); shutil.copy2(src,dst); staged.append(dst)
        return staged,temp_dir

    def cleanup_attachments(self,temp_dir):
        if not temp_dir: return
        try:
            shutil.rmtree(temp_dir,ignore_errors=True)
            parent=os.path.dirname(temp_dir)
            if os.path.isdir(parent) and not os.listdir(parent): os.rmdir(parent)
        except Exception: pass

    def paste(self,event=None):
        try:
            clip=ImageGrab.grabclipboard()
            if isinstance(clip,Image.Image):
                cache=os.path.join(CODEX_HOME,"clipboard_attachments"); os.makedirs(cache,exist_ok=True)
                cutoff=time.time()-86400
                for name in os.listdir(cache):
                    path=os.path.join(cache,name)
                    try:
                        if os.path.isfile(path) and os.path.getmtime(path)<cutoff: os.remove(path)
                    except Exception: pass
                path=os.path.join(cache,f"clipboard_{time.time_ns()}.png")
                clip.save(path,"PNG"); self.generated_attachments.add(path); self.add_attachment_paths([path])
                return "break"
            if isinstance(clip,list):
                files=[x for x in clip if os.path.isfile(x)]
                if files: self.add_attachment_paths(files); return "break"
        except Exception: pass
        try:
            self.on_input_focus(); self.input.insert("insert",self.clipboard_get())
        except tk.TclError: pass
        return "break"

    def on_enter(self,event):
        if event.state & 1: return
        self.send(); return "break"

    def send(self):
        if self.busy:return
        prompt=self.input_text()
        files=list(self.attachments)
        if not prompt and not files:return
        visible=prompt or "Проанализируй прикреплённые файлы."
        if files:
            visible += "\n\n📎 " + ", ".join(os.path.basename(x) for x in files)
        chat=self.current_chat(True); cwd=self.cwd; cid=chat["id"]
        try:
            staged,temp_dir=self.prepare_attachments(files,cwd) if files else ([],None)
        except Exception as e:
            self.say("system","Не удалось подготовить вложения: "+str(e)); return
        if chat.get("title")=="Новый чат":
            base=prompt.splitlines()[0][:38] if prompt else os.path.basename(files[0])[:38]
            chat["title"]=base or "Новый чат"; self.refresh_chat_list()
        agent_prompt=prompt or "Проанализируй прикреплённые файлы."
        if staged:
            agent_prompt += "\n\nК сообщению прикреплены локальные файлы. Открой и проанализируй именно их:\n"
            agent_prompt += "\n".join(f'- "{x}"' for x in staged)
            agent_prompt += "\n\nЕсли для чтения вложений нужны вспомогательные команды или скрипты, не оставляй их в проекте после анализа. Предпочитай одноразовые команды; временные служебные файлы создавай только внутри .deepseek_attachments и удаляй до завершения ответа."
        self.busy=True; self.cancel_requested=False; self.send_button.grid_remove(); self.stop_button.grid(); self.status.config(text="DeepSeek работает…")
        self.input.delete("1.0","end"); self.say("user",visible)
        chat.setdefault("messages",[]).append(["user",visible]); chat["updated"]=time.time(); self.clear_attachments(); self.save_state(); self.refresh_chat_list()
        mode=self.agent_mode
        threading.Thread(target=self.run_agent,args=(agent_prompt,cwd,cid,temp_dir,mode,visible),daemon=True).start()

    def stop_agent(self):
        if not self.busy: return
        self.cancel_requested=True; self.status.config(text="Останавливаю…")
        p=self.current_process
        try:
            if p and p.poll() is None: p.terminate()
        except Exception: pass

    def run_agent(self,prompt,cwd,cid,temp_dir=None,mode="edit",checkpoint_label=""):
        env=os.environ.copy(); env["CODEX_HOME"]=CODEX_HOME
        chat=self.get_chat(cwd,cid); sid=chat.get("session") if chat else None
        sandbox="read-only" if mode=="analysis" else "workspace-write"
        if mode=="edit":
            self.after(0,lambda:self.status.config(text="Создаю контрольную точку…"))
            label=(checkpoint_label or "Перед запросом").splitlines()[0][:100]
            cp,cp_err=self.create_checkpoint(cwd,label)
            if cp:
                if chat: chat["last_checkpoint"]=cp; self.save_state()
                self.after(0,lambda:self.update_checkpoint_button() if self.cwd==cwd else None)
            elif cp_err:
                self.after(0,lambda e=cp_err:self.status.config(text="Точка не создана: "+e[:70]))
        self.after(0,lambda:self.status.config(text=("DeepSeek анализирует…" if mode=="analysis" else "DeepSeek работает…")))
        if sid:
            cmd=[CODEX,"exec","resume",sid,"-m","deepseek-flash","-c",f'sandbox_mode="{sandbox}"',"--skip-git-repo-check","--json",prompt]
        else:
            cmd=[CODEX,"exec","-m","deepseek-flash","-C",cwd,"--sandbox",sandbox,"--skip-git-repo-check","--json",prompt]
        request_started=False; usage_data=None
        try:
            flags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0
            p=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding="utf-8",errors="replace",env=env,creationflags=flags,stdin=subprocess.DEVNULL,bufsize=1,cwd=cwd)
            request_started=True; self.current_process=p
            answer=[]; found=sid
            for line in p.stdout:
                try:
                    ev=json.loads(line)
                    if ev.get("type")=="thread.started": found=ev.get("thread_id") or found
                    if ev.get("type")=="turn.completed" and isinstance(ev.get("usage"),dict): usage_data=ev.get("usage")
                    item=ev.get("item",{}); typ=item.get("type","")
                    if ev.get("type")=="item.started": self.after(0,lambda t=typ,i=item,c=cwd,x=cid:self.show_action(t,i,c,x))
                    if ev.get("type")=="item.completed" and typ=="agent_message": answer.append(item.get("text",""))
                except Exception: pass
            p.wait(); err=(p.stderr.read() or "").strip()
            if found and chat: chat["session"]=found; self.save_state()
            msg="Остановлено пользователем." if self.cancel_requested else ("\n".join(x for x in answer if x).strip() or err or "(no output)")
            self.after(0,lambda m=msg,u=usage_data,r=request_started:self.finish(m,cwd,cid,u,r))
        except Exception as e:
            err_text=str(e)
            self.after(0,lambda t=err_text,u=usage_data,r=request_started:self.finish("Ошибка запуска: "+t,cwd,cid,u,r))
        finally:
            self.cleanup_attachments(temp_dir)

    def show_action(self,typ,item,cwd,cid):
        labels={"command_execution":"Выполняет команду","file_change":"Изменяет файлы","mcp_tool_call":"Использует инструмент","reasoning":"Анализирует"}
        label=labels.get(typ)
        if label:
            detail=item.get("command") or item.get("name") or ""
            if isinstance(detail,list): detail=" ".join(str(x) for x in detail)
            if len(str(detail))>100: detail=str(detail)[:97]+"..."
            action=label+((": "+str(detail)) if detail else "…")
            self.status.config(text=action)
            chat=self.get_chat(cwd,cid)
            if chat:
                messages=chat.setdefault("messages",[])
                if not messages or messages[-1] != ["action",action]:
                    messages.append(["action",action]); self.save_state()
                    if self.cwd==cwd and self.active_chats.get(cwd)==cid:
                        self.say("action",action); self.update_action_button()

    def finish(self,msg,cwd,cid,usage_data=None,count_request=False):
        if count_request: self.record_usage(usage_data,True)
        chat=self.get_chat(cwd,cid)
        if chat: chat.setdefault("messages",[]).append(["bot",msg]); chat["updated"]=time.time(); self.save_state()
        if self.cwd==cwd and self.active_chats.get(cwd)==cid:
            self.say("bot",msg); self.refresh_chat_list(); self.update_action_button(); self.refresh_changes()
            if self.show_files: self.refresh_project_files()
            self.update_checkpoint_button()
        self.current_process=None; self.busy=False; self.stop_button.grid_remove(); self.send_button.grid(); self.status.config(text="Готов"); self.input.focus_set()

if __name__=="__main__":
    if acquire_single_instance(): App().mainloop()