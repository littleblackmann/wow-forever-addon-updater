from pathlib import Path
import gc
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch

import updater as u
import window as ui


class WindowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.game = Path(self.tmp.name) / '遊戲'
        (self.game / '_forever_').mkdir(parents=True)
        (self.game / '_forever_/Wow.exe').write_bytes(b'test')
        (self.game / '.build.info').write_text('Product|Active|Version\nwowf|1|1.60.1.1234\n')
        self.root = tk.Tk()
        self.root.withdraw()
        self.discovery_patch=patch.object(ui.UpdaterWindow,'check_online')
        self.discovery_patch.start()
        self.receipt_patch=patch.object(u,'APP',Path(self.tmp.name))
        self.receipt_patch.start()
        self.app = ui.UpdaterWindow(self.root)

    def tearDown(self):
        for callback in self.root.tk.call('after', 'info'):
            self.root.after_cancel(callback)
        self.root.update_idletasks()
        self.root.destroy()
        self.app = None
        self.root = None
        gc.collect()
        self.tmp.cleanup()
        self.discovery_patch.stop()
        self.receipt_patch.stop()

    def notice(self,minimum='1.2.2'):
        self.app.game=self.game
        self.app.notice=ui.notices.Notice('f'*64,minimum,'test',u.PACKAGES,{'id':'test','changes':['中文改善說明'],'descriptions':{}})

    def test_update_notice_does_not_repeat_and_manual_button_still_opens(self):
        self.notice()
        with patch.object(self.app,'show_update_news') as show:
            self.app.maybe_show_update_news();self.app.maybe_show_update_news()
            self.assertEqual(show.call_count,1)
        popup=self.app.show_update_news()
        self.assertIs(self.app.show_update_news(),popup)
        self.assertIsNone(self.root.grab_current())
        self.assertTrue(ui.notices.seen(ui.notices.receipt_key(self.game,self.app.notice)))

    def test_update_notice_game_running_does_not_install_and_popup_stays(self):
        self.notice();popup=self.app.show_update_news()
        buttons=[w for w in popup.winfo_children()[0].winfo_children() if isinstance(w,ui.ttk.Button)]
        primary=next(w for w in buttons if w.cget('text')=='一鍵更新遊戲插件')
        with patch.object(ui.u,'game_running',return_value=True),patch.object(self.app,'start') as start:
            primary.invoke();start.assert_not_called()
        self.assertTrue(popup.winfo_exists())

    def test_required_program_update_runs_first(self):
        self.notice('99.0.0');self.app.app_update={'version':'99.0.0'}
        popup=self.app.show_update_news()
        primary=next(w for w in popup.winfo_children()[0].winfo_children() if isinstance(w,ui.ttk.Button) and w.cget('text')=='先更新管理器程式')
        with patch.object(self.app,'update_program') as update,patch.object(self.app,'start') as start:
            primary.invoke();update.assert_called_once();start.assert_not_called()

    def test_no_auto_popup_during_update_and_no_duplicate_after_receipt(self):
        self.notice();self.app.busy=True
        with patch.object(self.app,'show_update_news') as show:
            self.app.maybe_show_update_news();show.assert_not_called()
            self.app.busy=False
            ui.notices.acknowledge(ui.notices.receipt_key(self.game,self.app.notice))
            self.app.maybe_show_update_news();show.assert_not_called()

    def test_required_program_unavailable_cannot_start_addon_install(self):
        self.notice('99.0.0');popup=self.app.show_update_news()
        primary=next(w for w in popup.winfo_children()[0].winfo_children() if isinstance(w,ui.ttk.Button) and w.cget('text')=='一鍵更新遊戲插件')
        self.assertIn('disabled',primary.state())

    def test_discovery_for_previous_game_is_ignored(self):
        self.notice();before=self.app.notice
        self.app.events.put(('discovery',(Path(self.tmp.name)/'different',None,None,None,None)))
        with patch.object(self.app,'maybe_show_update_news'):
            self.app.poll()
        self.assertIs(self.app.notice,before)

    def test_folder_picker_normalizes_and_remembers(self):
        with patch.object(ui.filedialog, 'askdirectory', return_value=str(self.game / '_forever_')), \
                patch.object(ui, 'remember_game') as save:
            self.app.choose_folder()
        self.assertEqual(self.app.game, self.game)
        self.assertEqual(self.app.game_text.get(), str(self.game))
        save.assert_called_once_with(self.game)

    def test_cancel_or_invalid_selection_keeps_previous_path(self):
        before = self.app.game
        for selection in ('', self.tmp.name):
            with patch.object(ui.filedialog, 'askdirectory', return_value=selection), \
                    patch.object(ui.messagebox, 'showerror'):
                self.app.choose_folder()
            self.assertEqual(self.app.game, before)

    def test_worker_uses_selected_target_and_locks_folder_selection(self):
        self.app.game = self.game
        with patch.object(ui, 'run_updates', return_value=(0, 0, 0)) as run, \
                patch.object(ui.online, 'sync_catalog', return_value=ui.online.Catalog(u.PACKAGES, u.CUSTOMIZATIONS, None, 'test')):
            self.app.start(False)
            self.assertIn('disabled', self.app.folder_button.state())
            deadline = time.monotonic() + 3
            while self.app.events.empty() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.app.poll()
            self.assertFalse(self.app.busy)
            self.assertNotIn('disabled', self.app.folder_button.state())
            self.assertEqual(run.call_args.kwargs['game'], self.game)
            self.assertFalse(run.call_args.args[0])

    def test_info_window_does_not_grab_main_or_create_duplicate_windows(self):
        popup = self.app.show_disclaimer()
        try:
            self.assertIsNone(self.root.grab_current())
            self.assertIs(self.app.show_disclaimer(), popup)
            with patch.object(self.root, 'destroy') as close:
                self.app.close()
                close.assert_called_once_with()
        finally:
            popup.destroy()

    def test_status_updates_keep_existing_canvas_and_background(self):
        items = self.app.surface.find_all()
        for index in range(20):
            self.app.status.set(f'Progress {index}')
        self.assertEqual(self.app.surface.find_all(), items)
        self.assertEqual(self.app.surface.itemcget(self.app._text_items['status'], 'text'), 'Progress 19')


if __name__ == '__main__':
    unittest.main()
