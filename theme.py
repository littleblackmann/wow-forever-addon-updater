"""Stone and aged-metal Tk theme. Rendering assets contain no game data."""
import tkinter as tk
from tkinter import ttk

BG = '#171716'
INK = '#e9dfcc'
GOLD = '#e5bd67'
MUTED = '#b1a58e'
LINE = '#685b45'
FONT = 'Microsoft JhengHei UI'
TITLE_FONT = 'DFKai-SB'


class Theme:
    def __init__(self, root, resources):
        self.root = root
        folder = resources / 'theme-assets'
        self.stone = tk.PhotoImage(master=root, file=str(folder / 'stone.png'))
        self.images = {}
        self.badges = {name: tk.PhotoImage(master=root, file=str(folder / f'badge-{name}.png'))
                       for name in ('quest','loot','combat','map','dbm','utility')}
        style = ttk.Style(root)
        style.theme_use('clam')
        for variant, material in [('Metal','steel'),('Primary','crimson')]:
            for state in ('normal','active','pressed'):
                self.images[material,state] = tk.PhotoImage(master=root, file=str(folder / f'{material}-{state}.png'))
            disabled=tk.PhotoImage(master=root,file=str(folder/'disabled-normal.png'))
            self.images[material,'disabled']=disabled
            element=f'{variant}.surface'
            if element not in style.element_names():
                style.element_create(element, 'image', self.images[material,'normal'],
                                     ('disabled',disabled),('pressed',self.images[material,'pressed']),
                                     ('active',self.images[material,'active']), border=6, sticky='nsew')
            style.layout(f'{variant}.TButton',[(element,{'sticky':'nsew','children':[
                ('Button.focus',{'sticky':'nsew','children':[
                    ('Button.padding',{'sticky':'nsew','children':[
                        ('Button.label',{'sticky':'nsew'})]})]})]})])
            style.configure(f'{variant}.TButton',font=(TITLE_FONT,16,'bold') if variant=='Primary' else (TITLE_FONT,12,'bold'),
                            foreground=GOLD if variant=='Primary' else INK,background=BG,
                            padding=(12,0),borderwidth=0,focuscolor=GOLD,anchor='center',justify='center',width=0)
            style.map(f'{variant}.TButton',foreground=[('disabled','#827b6c'),('active','#fff0bf')])
        style.configure('TEntry',fieldbackground='#111110',foreground=INK,insertcolor=INK,
                        bordercolor=LINE,lightcolor=LINE,darkcolor='#090908',padding=8)
        style.map('TEntry',fieldbackground=[('readonly','#111110')],foreground=[('readonly',INK)])
        style.configure('Treeview',font=(FONT,11),rowheight=48,background='#191918',
                        foreground=INK,fieldbackground='#191918',borderwidth=0,relief='flat')
        style.layout('Treeview',[('Treeview.treearea',{'sticky':'nswe'})])
        style.configure('Treeview.Heading',font=(TITLE_FONT,15,'bold'),background='#383126',
                        foreground=GOLD,bordercolor=LINE,lightcolor='#8c7958',darkcolor='#171411',padding=(12,10))
        style.map('Treeview.Heading',background=[('active','#453b2c')])
        style.map('Treeview',background=[('selected','#51432c')],foreground=[('selected','#fff0cd')])
        style.configure('TScrollbar',troughcolor='#151513',background='#4a4337',bordercolor='#27241f',
                        arrowcolor='#c7b895',lightcolor='#6b5c46',darkcolor='#191715',arrowsize=13)
        for direction in ('Vertical','Horizontal'):
            style.map(f'{direction}.TScrollbar',background=[('disabled','#28251e'),('active','#796849')],
                      arrowcolor=[('disabled','#504938')],troughcolor=[('disabled','#151513')])
        style.configure('TProgressbar',troughcolor='#1c1a16',background='#b39453',bordercolor=LINE,
                        lightcolor=GOLD,darkcolor='#574627')

    def badge(self, name):
        lower=name.lower()
        key=('quest' if 'questie' in lower or '任務助手' in lower else
             'loot' if 'atlas' in lower else 'combat' if 'threat' in lower or '仇恨' in lower else
             'dbm' if 'dbm' in lower else 'map' if 'map' in lower or '地圖' in lower or '路線' in lower else 'utility')
        return self.badges[key]


class StoneCanvas(tk.Canvas):
    def __init__(self,parent,theme,**kw):
        super().__init__(parent,bg=BG,highlightthickness=0,**kw)
        self.theme=theme
        self._tiles={}

    def material(self,w,h):
        required={(x,y) for y in range(0,h,512) for x in range(0,w,512)}
        for position in self._tiles.keys()-required:
            self.delete(self._tiles.pop(position))
        for x,y in required-self._tiles.keys():
            self._tiles[x,y]=self.create_image(x,y,image=self.theme.stone,anchor='nw',tags='material')
        self.tag_lower('material')

    def frame(self,x,y,w,h,tag='decoration',gold=False):
        self.create_rectangle(x,y,x+w,y+h,outline='#080807',width=5,tags=tag)
        self.create_rectangle(x+1,y+1,x+w-1,y+h-1,outline='#8b826e' if not gold else '#a58a55',tags=tag)
        self.create_rectangle(x+3,y+3,x+w-3,y+h-3,outline='#38352e',tags=tag)
        self.create_line(x+4,y+4,x+w-4,y+4,fill='#b3a58a',tags=tag)
        for cx,cy,dx,dy in ((x,y,1,1),(x+w,y,-1,1),(x,y+h,1,-1),(x+w,y+h,-1,-1)):
            self.create_polygon(cx,cy+11*dy,cx+11*dx,cy,cx+16*dx,cy,cx,cy+16*dy,
                                fill='#514d42',outline='#b3a58a',tags=tag)

    def link(self,text,command,**kw):
        button=ttk.Button(self,text=text,command=command,style='Metal.TButton',takefocus=True,**kw)
        return button


class CaptionButton(tk.Canvas):
    def __init__(self,parent,text,command,close=False):
        super().__init__(parent,width=42,height=28,bg='#29261f',highlightthickness=0,takefocus=True,cursor='hand2')
        self.command=command
        self.create_rectangle(1,1,41,27,fill='#46201b' if close else '#302c24',outline='#9d8963')
        self.create_line(3,3,39,3,fill='#c5ae7e')
        self.create_text(21,14,text=text,fill=INK,font=('Segoe UI',13),anchor='center')
        self.bind('<ButtonRelease-1>',lambda e:command() if 0 <= e.x < self.winfo_width() and 0 <= e.y < self.winfo_height() else None)
        self.bind('<Return>',lambda e:command())
        self.bind('<space>',lambda e:command())
        self.bind('<Enter>',lambda e:self.configure(bg='#60503b'))
        self.bind('<Leave>',lambda e:self.configure(bg='#29261f'))
        self.bind('<FocusIn>',lambda e:self.configure(highlightthickness=1,highlightbackground=GOLD))
        self.bind('<FocusOut>',lambda e:self.configure(highlightthickness=0))


def dialog(parent,theme,title,text,website=None):
    """Owned information window, with no grab that can block the parent."""
    existing=getattr(parent,'_info_windows',{}).get(title)
    if existing is not None and existing.winfo_exists():
        existing.lift()
        return existing
    window=tk.Toplevel(parent)
    window.withdraw()
    window.title(title)
    window.transient(parent)
    window.configure(bg=BG)
    window.resizable(False,False)
    from chrome import WindowChrome
    window.chrome=WindowChrome(window,resizable=False,taskbar=False,caption_height=79,owner=parent)
    try:window.iconbitmap(parent.iconbitmap())
    except tk.TclError:pass
    width,height=600,350
    surface=StoneCanvas(window,theme,width=width,height=height)
    surface.pack(fill='both',expand=True)
    window.chrome.attach(surface)
    surface.material(width,height)
    surface.frame(7,7,width-14,height-14)
    surface.create_text(30,30,text=title,fill=GOLD,font=(TITLE_FONT,22,'bold'),anchor='nw')
    dismiss=CaptionButton(surface,text='×',command=window.destroy,close=True)
    surface.create_window(width-44,38,window=dismiss,width=42,height=28)
    surface.create_line(30,79,width-30,79,fill=LINE)
    surface.create_text(30,101,text=text,fill=INK,font=(FONT,11),width=width-60,anchor='nw',justify='left')
    close=ttk.Button(surface,text='我知道了',style='Primary.TButton',command=window.destroy)
    surface.create_window(width-30,height-29,window=close,anchor='se',width=130,height=46)
    if website:
        link=ttk.Button(surface,text='小黑的網站 ↗',style='Metal.TButton',command=website)
        surface.create_window(30,height-29,window=link,anchor='sw',width=160,height=46)
    window.update_idletasks()
    x=parent.winfo_rootx()+max(0,(parent.winfo_width()-width)//2)
    y=parent.winfo_rooty()+max(0,(parent.winfo_height()-height)//2)
    window.geometry(f'{width}x{height}+{x}+{y}')
    window.bind('<Escape>',lambda e:window.destroy())
    close.bind('<Return>',lambda e:window.destroy())
    if website:
        link.bind('<Return>',lambda e:website())
    if not hasattr(parent,'_info_windows'):parent._info_windows={}
    parent._info_windows[title]=window
    window.bind('<Destroy>',lambda e:parent._info_windows.pop(title,None) if e.widget==window else None,add='+')
    window.protocol('WM_DELETE_WINDOW',window.destroy)
    window.deiconify()
    window.lift(parent)
    close.focus_set()
    return window
