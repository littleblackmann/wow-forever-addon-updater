"""Windows integration test of the replacement helper in an isolated directory."""
from pathlib import Path
import hashlib
import subprocess
import sys
import time


def verify(folder: Path):
    folder.mkdir(parents=True)
    staged_dir = folder / '.updates'
    staged_dir.mkdir()
    source = folder / 'Probe.cs'
    source.write_text('''using System; using System.IO;
class Probe { static void Main() { File.WriteAllText(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "probe-ok.txt"), "updated"); } }
''', encoding='utf-8')
    new = staged_dir / 'probe.exe'
    compiler = Path(r'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe')
    subprocess.run([str(compiler), '/nologo', '/target:winexe', '/out:' + str(new), str(source)], check=True, timeout=20)
    raw = new.read_bytes()
    target = folder / '永恆插件更新器.exe'
    target.write_bytes(b'MZprevious executable fixture')
    code = '''from pathlib import Path
import sys
import updater as u
import self_update
u.APP=Path(sys.argv[1])
self_update.schedule(Path(sys.argv[2]),sys.argv[3])
'''
    subprocess.run([sys.executable, '-B', '-c', code, str(folder), str(new), hashlib.sha256(raw).hexdigest()], check=True, timeout=10)
    until = time.monotonic() + 20
    while not (folder / 'probe-ok.txt').is_file() and time.monotonic() < until:
        time.sleep(0.2)
    assert (folder / 'probe-ok.txt').read_text() == 'updated'
    assert target.read_bytes() == raw
    old = list(staged_dir.glob('previous-*.exe'))
    assert len(old) == 1 and old[0].read_bytes() == b'MZprevious executable fixture'
    print('PASS: helper waited for old process, replaced verified executable, retained previous exe and launched new probe')


if __name__ == '__main__':
    verify(Path(sys.argv[1]))
