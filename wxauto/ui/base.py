from wxauto import uiautomation as uia
from wxauto.param import PROJECT_NAME
from wxauto.logger import wxlog
from abc import ABC, abstractmethod
import win32gui
from typing import Union
import time

class BaseUIWnd(ABC):
    _ui_cls_name: str = None
    _ui_name: str = None
    control: uia.Control

    @abstractmethod
    def _lang(self, text: str):pass

    def __repr__(self):
        return f"<{PROJECT_NAME} - {self.__class__.__name__} at {hex(id(self))}>"
    
    def __eq__(self, other):
        return self.control == other.control
    
    def __bool__(self):
        return self.exists()

    def _get_window_handle(self):
        handle = getattr(self, 'HWND', None)
        if handle:
            return handle
        try:
            control = getattr(self, 'control', None)
            if control is None:
                return None
            handle = getattr(control, 'NativeWindowHandle', None)
            if handle:
                return handle
            if hasattr(control, 'GetTopLevelControl'):
                top = control.GetTopLevelControl()
                handle = getattr(top, 'NativeWindowHandle', None)
                if handle:
                    return handle
        except Exception:
            pass
        return None

    def _show(self, force_foreground: bool = False):
        hwnd = self._get_window_handle()
        if hwnd:
            try:
                win32gui.ShowWindow(hwnd, 9 if force_foreground else 1)
            except Exception:
                pass
            if force_foreground:
                try:
                    win32gui.BringWindowToTop(hwnd)
                except Exception:
                    pass
                try:
                    win32gui.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 3)
                    win32gui.SetWindowPos(hwnd, -2, 0, 0, 0, 0, 3)
                except Exception:
                    pass
                try:
                    win32gui.SetForegroundWindow(hwnd)
                except Exception:
                    pass
        if force_foreground:
            try:
                self.control.SwitchToThisWindow()
            except Exception:
                pass
            try:
                self.control.SetFocus()
            except Exception:
                pass
            time.sleep(0.05)

    def close(self):
        try:
            self.control.SendKeys('{Esc}')
        except:
            pass

    def exists(self, wait=0):
        try:
            result = self.control.Exists(wait)
            return result
        except:
            return False

class BaseUISubWnd(BaseUIWnd):
    root: BaseUIWnd
    parent: None

    def _lang(self, text: str):
        if getattr(self, 'parent'):
            return self.parent._lang(text)
        else:
            return self.root._lang(text)


