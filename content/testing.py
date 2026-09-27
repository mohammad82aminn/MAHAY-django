"""Test helpers: a real (if tiny) MP4, so reading a video's length is tested on an actual file."""
import struct

from django.core.files.uploadedfile import SimpleUploadedFile


def _box(kind, payload):
    return struct.pack(">I4s", 8 + len(payload), kind) + payload


def mp4_bytes(seconds=60):
    """The two boxes a player (and mutagen) reads the length from: ftyp, then moov with its mvhd."""
    timescale = 1000
    mvhd = struct.pack(">B3xIIII", 0, 0, 0, timescale, round(seconds * timescale)) + b"\0" * 80
    return _box(b"ftyp", b"isom\0\0\0\0isommp41") + _box(b"moov", _box(b"mvhd", mvhd))


def mp4_upload(name="lesson.mp4", seconds=60):
    return SimpleUploadedFile(name, mp4_bytes(seconds), content_type="video/mp4")
