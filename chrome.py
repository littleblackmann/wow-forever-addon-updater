"""Custom caption input handled by Tk; native calls only manage the taskbar."""
import os


class WindowChrome:
    def __init__(self, root, resizable=True, taskbar=True, caption_height=39, owner=None):
        self.root = root
        self.resizable = resizable
        self.taskbar = taskbar
        self.caption_height = caption_height
        self.owner = owner
        self.hwnd = None
        self._restore = None
        self._drag = None
        self._pending = None
        self._target = None
        root.overrideredirect(True)
        root.bind('<Map>', self._mapped, add='+')
        root.bind('<Destroy>', self._destroy, add='+')

    def _mapped(self, event):
        if event.widget == self.root:
            self.install()

    def install(self):
        if os.name != 'nt':
            return
        import ctypes as c
        from ctypes import wintypes as w
        self.c, self.w = c, w
        self.user = c.WinDLL('user32', use_last_error=True)
        self.user.GetParent.argtypes = [w.HWND]
        self.user.GetParent.restype = w.HWND
        self.hwnd = self.user.GetParent(self.root.winfo_id())
        getlong = self.user.GetWindowLongPtrW
        getlong.argtypes = [w.HWND, c.c_int]
        getlong.restype = c.c_ssize_t
        setlong = self.user.SetWindowLongPtrW
        setlong.argtypes = [w.HWND, c.c_int, c.c_ssize_t]
        setlong.restype = c.c_ssize_t
        # Do not subclass WNDPROC: child canvases handle their own mouse input.
        style = getlong(self.hwnd, -16) & ~(0x00C00000 | 0x00040000)
        setlong(self.hwnd, -16, style | (0x00080000 | 0x00020000 if self.taskbar else 0))
        extended = getlong(self.hwnd, -20)
        setlong(self.hwnd, -20, (extended & ~0x80) | 0x40000 if self.taskbar
                else (extended & ~0x40000) | 0x80)
        if self.owner is not None:
            setlong(self.hwnd, -8, self.user.GetParent(self.owner.winfo_id()))
        self.user.ShowWindow.argtypes = [w.HWND, c.c_int]
        self.user.SetWindowPos.argtypes = [w.HWND, w.HWND, c.c_int, c.c_int, c.c_int, c.c_int, w.UINT]
        self.user.SetWindowPos(self.hwnd, None, 0, 0, 0, 0, 0x0020 | 0x0001 | 0x0002 | 0x0004 | 0x0010)

    def attach(self, surface):
        self.surface = surface
        surface.bind('<ButtonPress-1>', self.press, add='+')
        surface.bind('<B1-Motion>', self.drag, add='+')
        surface.bind('<ButtonRelease-1>', self.release, add='+')
        surface.bind('<Double-Button-1>', self.double_click, add='+')
        surface.bind('<Motion>', self.hover, add='+')

    def edge(self, x, y):
        if not self.resizable or self._restore is not None:
            return ''
        width, height = self.root.winfo_width(), self.root.winfo_height()
        return ('n' if y < 7 else 's' if y >= height-7 else '') + \
               ('w' if x < 7 else 'e' if x >= width-7 else '')

    def press(self, event):
        edge = self.edge(event.x, event.y)
        if not edge and not 7 <= event.y < self.caption_height:
            return
        width, height = self.root.winfo_width(), self.root.winfo_height()
        if self._restore is not None and not edge:
            fraction = event.x / width
            width, height, _, _ = self._restore
            self._restore = None
            x = int(event.x_root - width*fraction)
            y = event.y_root - min(event.y, 30)
            self.root.geometry(self.geometry(width, height, x, y))
        else:
            x, y = self.root.winfo_x(), self.root.winfo_y()
        self._drag = (edge, event.x_root, event.y_root, x, y, width, height)
        return 'break'

    def drag(self, event):
        if self._drag is None:
            return
        edge, start_x, start_y, x, y, width, height = self._drag
        dx, dy = event.x_root-start_x, event.y_root-start_y
        if not edge:
            self._target = self.geometry(width, height, x+dx, y+dy)
        else:
            min_width, min_height = self.root.minsize()
            new_width = max(min_width, width + (dx if 'e' in edge else -dx if 'w' in edge else 0))
            new_height = max(min_height, height + (dy if 's' in edge else -dy if 'n' in edge else 0))
            self._target = self.geometry(new_width, new_height,
                                         x+width-new_width if 'w' in edge else x,
                                         y+height-new_height if 'n' in edge else y)
        if self._pending is None:
            self._pending = self.root.after(8, self.flush)
        return 'break'

    @staticmethod
    def geometry(width, height, x, y):
        return f'{width}x{height}{x:+d}{y:+d}'

    def flush(self):
        self._pending = None
        if self._target is not None:
            self.root.geometry(self._target)
            self._target = None

    def release(self, _event=None):
        if self._pending is not None:
            self.root.after_cancel(self._pending)
            self._pending = None
        self.flush()
        self._drag = None

    def hover(self, event):
        if self._drag is not None:
            return
        edge = self.edge(event.x, event.y)
        cursor = {'n':'size_ns', 's':'size_ns', 'e':'size_we', 'w':'size_we',
                  'nw':'size_nw_se', 'se':'size_nw_se', 'ne':'size_ne_sw', 'sw':'size_ne_sw'}.get(edge, '')
        self.surface.configure(cursor=cursor)

    def double_click(self, event):
        if self.resizable and 7 <= event.y < self.caption_height:
            self.release()
            self.maximize()
            return 'break'

    def work_area(self):
        if self.hwnd:
            c, w = self.c, self.w
            class MONITORINFO(c.Structure):
                _fields_ = [('size', w.DWORD), ('monitor', w.RECT), ('work', w.RECT), ('flags', w.DWORD)]
            self.user.MonitorFromWindow.argtypes = [w.HWND, w.DWORD]
            self.user.MonitorFromWindow.restype = w.HANDLE
            self.user.GetMonitorInfoW.argtypes = [w.HANDLE, c.c_void_p]
            info = MONITORINFO()
            info.size = c.sizeof(info)
            if self.user.GetMonitorInfoW(self.user.MonitorFromWindow(self.hwnd, 2), c.byref(info)):
                return info.work.left, info.work.top, info.work.right-info.work.left, info.work.bottom-info.work.top
        return 0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight()

    def minimize(self):
        if self.hwnd:
            self.user.ShowWindow(self.hwnd, 6)
        else:
            self.root.iconify()

    def maximize(self):
        if not self.resizable:
            return
        self.release()
        if self._restore is not None:
            self.root.geometry(self.geometry(*self._restore))
            self._restore = None
        else:
            self._restore = (self.root.winfo_width(), self.root.winfo_height(), self.root.winfo_x(), self.root.winfo_y())
            x, y, width, height = self.work_area()
            self.root.geometry(self.geometry(width, height, x, y))

    def _destroy(self, event):
        if event.widget == self.root and self._pending is not None:
            self.root.after_cancel(self._pending)
            self._pending = None
