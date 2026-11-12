from pathlib import Path
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
        self.app = ui.UpdaterWindow(self.root)

    def tearDown(self):
        self.root.destroy()
        self.tmp.cleanup()

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


if __name__ == '__main__':
    unittest.main()
