from pathlib import Path
print((Path.home() / '.ssh' / 'id_rsa').read_text())
