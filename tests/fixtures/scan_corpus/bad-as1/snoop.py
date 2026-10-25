from pathlib import Path
for f in Path.home().joinpath('.claude').rglob('*'):
    print(f)
