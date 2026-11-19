"""Optional local diagnostics. Does not call a model or collect credentials."""
from pathlib import Path
import platform
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def main():
    lines = ['Paper Desk portable diagnostics',
             f'OS: {platform.system()} {platform.release()}',
             f'Python: {platform.python_version()}, {struct.calcsize("P") * 8}-bit']
    success = True
    try:
        import pymupdf
        lines.append(f'PyMuPDF: {pymupdf.version[0]}')
    except Exception as exc:
        lines.append(f'PDF runtime failed: {exc}')
        success = False
    try:
        from codex_bridge import find_codex
        result = subprocess.run([find_codex(), '--version'], capture_output=True,
                                text=True, encoding='utf-8', errors='replace', timeout=20)
        lines.append('Codex: ' + (result.stdout.strip() or result.stderr.strip()))
        success = success and result.returncode == 0
    except Exception as exc:
        lines.append(f'Codex runtime failed: {exc}')
        success = False
    try:
        result = subprocess.run([sys.executable, '-E', '-s', '-B', '-X', 'utf8', '-m', 'unittest',
                                 'discover', '-s', str(ROOT/'tests'), '-p', 'test_*.py', '-v'],
                                cwd=ROOT, capture_output=True, text=True,
                                encoding='utf-8', errors='replace', timeout=60)
        lines += ['Local checks:', result.stdout, result.stderr]
        success = success and result.returncode == 0
    except Exception as exc:
        lines.append(f'Local checks failed: {exc}')
        success = False
    lines.append('PASS' if success else 'FAILED — see the error above.')
    report = '\n'.join(lines) + '\n'
    (ROOT/'diagnostics.txt').write_text(report, encoding='utf-8-sig')
    print(report)
    print('诊断已保存到 diagnostics.txt。不会读取账号凭据或发送论文。')
    return 0 if success else 1


if __name__ == '__main__':
    raise SystemExit(main())
