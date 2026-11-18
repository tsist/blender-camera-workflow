"""Pure conservative text-width estimates, not font/pixel measurement or input handling."""
import math
import unicodedata


def columns(region_width=244, ui_scale=1., inset=0):
    """Physical region pixels -> logical UI width; reserve padding and scrollbar."""
    if type(region_width) not in (int, float) or not math.isfinite(region_width) or region_width <= 0:
        region_width = 244
    if type(ui_scale) not in (int, float) or not math.isfinite(ui_scale) or ui_scale <= 0:
        ui_scale = 1.
    return max(1, min(120, int((region_width / ui_scale - 48 - inset) / 9)))


def clusters(text):
    """Keep common combining, variation, emoji-modifier and ZWJ sequences together."""
    held = ''
    for char in text:
        mark = unicodedata.category(char) in ('Mn', 'Mc', 'Me') or 0x1F3FB <= ord(char) <= 0x1F3FF
        regional_pair = (len(held) == 1 and 0x1F1E6 <= ord(held) <= 0x1F1FF and 0x1F1E6 <= ord(char) <= 0x1F1FF)
        if held and (mark or char == '\u200d' or held.endswith('\u200d') or regional_pair):
            held += char
        else:
            if held:
                yield held
            held = char
    if held:
        yield held


def units(text):
    total = 0.
    for char in text:
        if unicodedata.category(char) in ('Mn', 'Mc', 'Me', 'Cf'):
            continue
        total += 2 if unicodedata.east_asian_width(char) in ('W', 'F', 'A') else 1.4 if char in 'MW@%#&' else .5 if char.isspace() else 1
    return total


def wrap_text(text, region_width=244, ui_scale=1., inset=0):
    budget = columns(region_width, ui_scale, inset)
    result = []
    for paragraph in str(text).replace('\r\n', '\n').replace('\r', '\n').expandtabs(4).split('\n'):
        line = []
        for part in clusters(paragraph):
            while line and units(''.join(line) + part) > budget:
                spaces = [i for i, value in enumerate(line) if value.isspace()]
                cut = spaces[-1] if spaces and spaces[-1] > 0 else len(line)
                result.append(''.join(line[:cut]).rstrip())
                line = line[cut + 1:] if cut < len(line) else []
            if not line and part.isspace():
                continue
            line.append(part)
        result.append(''.join(line).rstrip())
    return tuple(result)


def status_text(state, message):
    title = {'IDLE': 'Ready', 'STARTING': 'Starting', 'RUNNING': 'Previewing',
             'HELD': 'Holding', 'RESTORING': 'Restoring', 'CONFLICT': 'Stopped: conflict'}.get(state, state)
    brief = {
        'Ready. This is timer-driven viewport preview, not native playback.': 'Choose a range, then Start.',
        'End frame held. Restore or Release to start again.': 'End frame held. Restore or Release.',
        'Stopped at current frame. Restore or Release to start again.': 'Stopped here. Restore or Release.',
        'Original frame/subframe and held viewport restored.': 'Original time and view restored.',
        'Baseline released; current scene time and viewport left untouched.': 'Released. Current values kept.',
    }
    # Unknown errors remain visible in full; no silent six-line truncation.
    return title, brief.get(message, message)
