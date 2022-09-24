import os
import locale


def get_local_datetime_fmt():
    # configure locale to get correct date and time formats
    old_lc_time = locale.getlocale(locale.LC_TIME)
    if old_lc_time[0] is None:
        locale.setlocale(locale.LC_TIME, locale.getlocale())
    result = (locale.nl_langinfo(locale.D_FMT), locale.nl_langinfo(locale.T_FMT))
    locale.setlocale(locale.LC_TIME, old_lc_time)
    return result


def shrink_path(path: str, max_entries: int):
    remaining = path
    collected = []
    for _ in range(max_entries):
        remaining, entry = os.path.split(remaining)
        collected.append(entry)
    if remaining not in ('', '/'):
        collected.append('...')
    else:
        collected.append(remaining)
    return os.path.join(*reversed(collected))