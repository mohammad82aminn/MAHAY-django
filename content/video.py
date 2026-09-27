"""Reading the length of an uploaded lesson video, so nobody has to type it in."""
from mutagen import MutagenError
from mutagen.mp4 import MP4


def mp4_seconds(file):
    """
    Length of an MP4 in whole seconds, or None if it can't be read (not an MP4, damaged, missing).

    `file` is a FieldFile: a fresh upload or one already in storage. Only the header boxes are
    read, not the whole video, so this stays cheap even for a two-hour lesson.
    """
    fresh = not getattr(file, "_committed", True)
    try:
        file.open("rb")
        file.seek(0)
        length = MP4(file).info.length
    except (MutagenError, OSError, ValueError):
        return None
    finally:
        try:
            if fresh:
                file.seek(0)  # the upload is read again when it is written to storage
            else:
                file.close()
        except (OSError, ValueError):
            pass
    return round(length) if length and length > 0 else None
