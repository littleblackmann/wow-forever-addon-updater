"""Replace only this updater after its UI has closed; keep its previous exe."""
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid

import updater as u


SCRIPT = r'''
$ErrorActionPreference = 'Stop'
$target = $env:XIAOHEI_UPDATE_TARGET
$staged = $env:XIAOHEI_UPDATE_STAGED
$backup = $env:XIAOHEI_UPDATE_BACKUP
$log = $env:XIAOHEI_UPDATE_LOG
$oldProcessId = [int]$env:XIAOHEI_UPDATE_PID
$movedOld = $false
$movedNew = $false
try {
    $hasher = [System.Security.Cryptography.SHA256]::Create()
    $actualHash = [BitConverter]::ToString($hasher.ComputeHash([IO.File]::ReadAllBytes($staged))).Replace('-', '').ToLowerInvariant()
    $hasher.Dispose()
    if ($actualHash -ne $env:XIAOHEI_UPDATE_SHA) {
        throw 'Downloaded updater hash changed'
    }
    $process = $null
    try { $process = [Diagnostics.Process]::GetProcessById($oldProcessId) } catch {}
    if ($process -and -not $process.WaitForExit(60000)) { throw 'Updater did not exit' }
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        try {
            if ([IO.File]::Exists($target)) {
                [IO.File]::Move($target, $backup)
                $movedOld = $true
            }
            break
        } catch {
            if ($attempt -eq 29) { throw }
            [Threading.Thread]::Sleep(500)
        }
    }
    [IO.File]::Move($staged, $target)
    $movedNew = $true
    $start = New-Object Diagnostics.ProcessStartInfo
    $start.FileName = $target
    $start.WorkingDirectory = [IO.Path]::GetDirectoryName($target)
    $start.UseShellExecute = $false
    [void][Diagnostics.Process]::Start($start)
    [IO.File]::WriteAllText($log, 'Updated successfully. Previous executable: ' + $backup)
} catch {
    $failure = $_.Exception.Message
    if ($movedNew -and [IO.File]::Exists($target)) {
        try { [IO.File]::Move($target, $staged) } catch {}
    }
    if ($movedOld -and -not [IO.File]::Exists($target)) {
        try { [IO.File]::Move($backup, $target) } catch {}
    }
    [IO.File]::WriteAllText($log, $failure)
}
'''


def schedule(path: Path, sha256: str):
    folder = u.APP / '.updates'
    if path.resolve().parent != folder.resolve() or not re.fullmatch(r'[0-9a-f]{64}', sha256):
        raise u.SkipUpdate('程式更新暫存位置無效')
    u.assert_plain(path)
    if hashlib.sha256(path.read_bytes()).hexdigest() != sha256:
        raise u.SkipUpdate('程式更新暫存雜湊不符')
    target = Path(sys.executable) if getattr(sys, 'frozen', False) else u.APP / '永恆插件更新器.exe'
    if target.resolve().parent != u.APP.resolve() or target.suffix.lower() != '.exe':
        raise u.SkipUpdate('程式更新目標位置無效')
    env = dict(os.environ, XIAOHEI_UPDATE_TARGET=str(target), XIAOHEI_UPDATE_STAGED=str(path),
               XIAOHEI_UPDATE_BACKUP=str(folder / f'previous-{uuid.uuid4().hex}.exe'),
               XIAOHEI_UPDATE_LOG=str(folder / 'last-update.log'), XIAOHEI_UPDATE_SHA=sha256,
               XIAOHEI_UPDATE_PID=str(os.getpid()))
    powershell = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    # Fixed source code, all paths through env vars; no shell interpolation of paths.
    subprocess.Popen([str(powershell), '-NoProfile', '-NonInteractive', '-WindowStyle', 'Hidden', '-Command', SCRIPT],
                     env=env, creationflags=u.NO_WINDOW, close_fds=True)
