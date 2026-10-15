from pathlib import Path

path = Path(__file__).resolve().parent / 'web' / 'src' / 'App.tsx'
if not path.is_file():
    raise SystemExit('Simpan file ini di folder utama project, sejajar folder web.')
src = path.read_text(encoding='utf-8')
a = 'const PREVIEW_ENABLED = true'
b = 'const PREVIEW_ENABLED = false'
if a in src:
    path.write_text(src.replace(a, b, 1), encoding='utf-8')
    print('Mode login dinyalakan kembali. Refresh Vite atau rebuild Docker web.')
elif b in src:
    print('Mode login sudah aktif. Tidak perlu perubahan.')
else:
    raise SystemExit('Preview patch tidak terdeteksi. File tidak diubah.')
