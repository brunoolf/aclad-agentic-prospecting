"""Private local files, atomically replaced without following managed symlinks."""
from pathlib import Path
import os
import tempfile
from .models import GateError


def check_path(path: Path) -> None:
    path = Path(path).absolute()
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise GateError('workspace_path_unavailable')


def atomic_write(path: Path, content: str) -> None:
    path = Path(path)
    check_path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, name = tempfile.mkstemp(prefix='.aclad-', dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def write_managed(path: Path, content: str, block: str) -> None:
    check_path(path)
    start, end = f'<!-- {block}_START -->', f'<!-- {block}_END -->'
    existing = Path(path).read_text(encoding='utf-8') if Path(path).exists() else ''
    if (existing.count(start), existing.count(end)) not in {(0, 0), (1, 1)}:
        raise GateError('workspace_conflict')
    managed = start + '\n' + content.rstrip() + '\n' + end
    if start in existing:
        left, right = existing.index(start), existing.index(end)
        if right < left:
            raise GateError('workspace_conflict')
        updated = existing[:left] + managed + existing[right + len(end):]
    else:
        updated = existing + ('\n' if existing and not existing.endswith('\n') else '') + managed + '\n'
    if updated != existing:
        atomic_write(Path(path), updated)
