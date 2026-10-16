"""Decode the three fixed image/geometry assets from a legacy-compatible JSON bundle.

The original installed updater only accepts JSON/GLB under web/assets. Retain
that launcher, distribute a checksummed JSON envelope, and reconstruct exactly
the original three non-executable asset files before renderer import. No devices,
network requests, checkpoint changes, arbitrary output paths or executable data.
"""
from pathlib import Path
import base64
import hashlib
import json
import os
import tempfile

FILES = ('camera_lod.json.gz', 'room_fabric.png', 'room_wood.png')
MAX_BUNDLE = 2_000_000
MAX_ASSET = 750_000


def ensure_assets(root=None):
    root = Path(root) if root is not None else Path(__file__).resolve().parents[1]
    directory = root/'web'/'assets'
    if (root/'web').is_symlink() or directory.is_symlink():
        raise ValueError('Asset directory must be inside this application')
    bundle = directory/'release_assets_v11.json'
    if bundle.is_symlink() or bundle.stat().st_size > MAX_BUNDLE:
        raise ValueError('Invalid release asset bundle')
    value = json.loads(bundle.read_text(encoding='utf-8'))
    if (type(value) is not dict or set(value) != {'schema','files'}
            or value['schema'] != 'seizo-fixed-assets/v1'
            or type(value['files']) is not dict or set(value['files']) != set(FILES)):
        raise ValueError('Unknown release asset schema or files')
    decoded = {}
    for name in FILES:
        item = value['files'][name]
        if (type(item) is not dict or set(item) != {'sha256','size','base64'}
                or type(item['size']) is not int or not 0 < item['size'] <= MAX_ASSET
                or type(item['base64']) is not str or len(item['base64']) > MAX_ASSET*2):
            raise ValueError('Invalid asset envelope')
        raw = base64.b64decode(item['base64'], validate=True)
        if len(raw) != item['size'] or hashlib.sha256(raw).hexdigest() != item['sha256']:
            raise ValueError('Asset checksum mismatch')
        magic = b'\x1f\x8b' if name.endswith('.gz') else b'\x89PNG\r\n\x1a\n'
        if not raw.startswith(magic) or (directory/name).is_symlink():
            raise ValueError('Invalid fixed asset format or destination')
        decoded[name] = raw
    # All envelopes validated before any write. Filenames come only from FILES.
    changed = []
    for name, raw in decoded.items():
        destination = directory/name
        if destination.is_file() and destination.read_bytes() == raw:
            continue
        fd, tempname = tempfile.mkstemp(prefix='.asset-', dir=directory)
        try:
            with os.fdopen(fd, 'wb') as handle:
                handle.write(raw)
            os.replace(tempname, destination)
        finally:
            if os.path.exists(tempname):os.unlink(tempname)
        changed.append(name)
    return changed
