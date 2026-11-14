WAIT_MARKER = '-wait-'


def is_wait_recording(filename: str) -> bool:
    return WAIT_MARKER in filename.lower()
