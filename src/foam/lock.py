"""One heavy compute job at a time on this machine (meshing, solving)."""
from contextlib import contextmanager
import fcntl
from pathlib import Path


@contextmanager
def compute_lock(root, blocking=False):
    folder = Path(root) / 'runs'
    folder.mkdir(exist_ok=True)
    with (folder / '.job.lock').open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError:
            raise RuntimeError('Another compute job holds runs/.job.lock; wait for it to finish.')
        yield
