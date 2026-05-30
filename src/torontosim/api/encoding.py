"""Binary tick-frame encoding (P06).

Per the frontend contract (research/06) each edge record is packed as:

    edge_idx : u32   (index into the once-uploaded edge table, not the string id)
    load     : f32
    speed    : f32   (km/h, effective)
    pressure : f32
    closure  : u8    (1 = closed)

A frame is ``[count: u32][record × count]`` little-endian. The client uploads
geometry once (keyed by ``edge_idx``) and only streams these records per tick,
so React never touches tick data.
"""

from __future__ import annotations

import struct

_RECORD = struct.Struct("<IfffB")  # 17 bytes, packed (little-endian, no padding)
_HEADER = struct.Struct("<I")

RECORD_SIZE = _RECORD.size


def pack_frame(records) -> bytes:
    """Pack an iterable of ``(edge_idx, load, speed, pressure, closure)``."""
    records = list(records)
    out = bytearray(_HEADER.pack(len(records)))
    for idx, load, speed, pressure, closure in records:
        out += _RECORD.pack(
            int(idx),
            float(load),
            float(speed),
            float(pressure),
            1 if closure else 0,
        )
    return bytes(out)


def unpack_frame(buf: bytes):
    """Inverse of :func:`pack_frame` -> list of record tuples."""
    (count,) = _HEADER.unpack_from(buf, 0)
    offset = _HEADER.size
    records = []
    for _ in range(count):
        records.append(_RECORD.unpack_from(buf, offset))
        offset += _RECORD.size
    return records
