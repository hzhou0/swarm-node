from collections import namedtuple
from datetime import timedelta, datetime
from struct import Struct
from warnings import warn

dTAI_GPS = timedelta(seconds=19)  # constant offset
NTP_EPOCH = datetime(1900, 1, 1)

LeapSecond = namedtuple("LeapSecond", "utc dTAI_UTC")  # tai = utc + dTAI_UTC
sentinel = LeapSecond(utc=datetime.max, dTAI_UTC=timedelta(0))


def leapseconds(
    tzfiles=None,
    use_fallback=False,
):
    """Extract leap seconds from *tzfiles*.
    >>> leapseconds()[0]
    LeapSecond(utc=datetime.datetime(1972, 1, 1, 0, 0), dTAI_UTC=datetime.timedelta(seconds=10))
    >>> leapseconds(tzfiles=["non-existent"])[27]
    Traceback (most recent call last):
    ...
    ValueError: Unable to open any tzfile: ['non-existent']
    >>> leapseconds(tzfiles=["non-existent"], use_fallback=True)[27]
    LeapSecond(utc=datetime.datetime(2017, 1, 1, 0, 0), dTAI_UTC=datetime.timedelta(seconds=37))
    """
    if tzfiles is None:
        tzfiles = [
            "/usr/share/zoneinfo/leap-seconds.list",
            "/usr/share/zoneinfo/right/UTC",
            "/usr/lib/zoneinfo/right/UTC",
        ]
    for filename in tzfiles:
        try:
            file = open(filename, "rb")
        except IOError:
            continue
        else:
            break
    else:  # no break
        if not use_fallback:
            raise ValueError("Unable to open any tzfile: %s" % (tzfiles,))
        else:
            return _fallback()

    with file:
        header = Struct(">4s c 15x 6i")  # see struct tzhead above
        (magic, version, _, _, leapcnt, timecnt, typecnt, charcnt) = header.unpack_from(
            file.read(header.size)
        )
        if magic != "TZif".encode():
            # assume /usr/share/zoneinfo/leap-seconds.list like file
            file.seek(0)  # rewind
            return leapseconds_from_listfile(file)
        if version not in "\x0023".encode():
            warn("Unsupported version %r in tzfile: %s" % (version, file.name), RuntimeWarning)
        if leapcnt == 0:
            raise ValueError("No leap seconds in tzfile: %s" % (file.name))

        """# from tzfile.h[2] (the file is in public domain)
         . . .header followed by. . .
         tzh_timecnt (char [4])s  coded transition times a la time(2)
         tzh_timecnt (unsigned char)s types of local time starting at above
         tzh_typecnt repetitions of
           one (char [4])  coded UT offset in seconds
           one (unsigned char) used to set tm_isdst
           one (unsigned char) that's an abbreviation list index
         tzh_charcnt (char)s  '\0'-terminated zone abbreviations
         tzh_leapcnt repetitions of
           one (char [4])  coded leap second transition times
           one (char [4])  total correction after above
        """
        file.read(timecnt * 5 + typecnt * 6 + charcnt)  # skip

        result = [LeapSecond(datetime(1972, 1, 1), timedelta(seconds=10))]
        nleap_seconds = 10
        tai_epoch_as_tai = datetime(1970, 1, 1, 0, 0, 10)
        buf = Struct(">2i")
        for _ in range(leapcnt):  # read leap seconds
            t, cnt = buf.unpack_from(file.read(buf.size))
            dTAI_UTC = nleap_seconds + cnt
            utc = tai_epoch_as_tai + timedelta(seconds=t - dTAI_UTC + 1)
            assert utc - datetime(utc.year, utc.month, utc.day) == timedelta(0)
            result.append(LeapSecond(utc, timedelta(seconds=dTAI_UTC)))
        result.append(sentinel)
        return result


def leapseconds_from_listfile(file, comment="#".encode()):
    """Extract leap seconds from *file*
    See /usr/share/zoneinfo/leap-seconds.list
    """
    result = []
    for line in file:
        if not line.startswith(comment):  # skip comments
            # ntp time, dtai, # day month year
            ntp_time, dtai = line.partition(comment)[0].split()
            utc = NTP_EPOCH + timedelta(seconds=int(ntp_time))
            result.append(LeapSecond(utc, timedelta(seconds=int(dtai))))
    result.append(sentinel)
    return result


def _fallback():
    """Leap seconds list if no tzfiles are available."""
    return [
        LeapSecond(utc=datetime(1972, 1, 1, 0, 0), dTAI_UTC=timedelta(0, 10)),
        LeapSecond(utc=datetime(1972, 7, 1, 0, 0), dTAI_UTC=timedelta(0, 11)),
        LeapSecond(utc=datetime(1973, 1, 1, 0, 0), dTAI_UTC=timedelta(0, 12)),
        LeapSecond(utc=datetime(1974, 1, 1, 0, 0), dTAI_UTC=timedelta(0, 13)),
        LeapSecond(utc=datetime(1975, 1, 1, 0, 0), dTAI_UTC=timedelta(0, 14)),
        LeapSecond(utc=datetime(1976, 1, 1, 0, 0), dTAI_UTC=timedelta(0, 15)),
        LeapSecond(utc=datetime(1977, 1, 1, 0, 0), dTAI_UTC=timedelta(0, 16)),
        LeapSecond(utc=datetime(1978, 1, 1, 0, 0), dTAI_UTC=timedelta(0, 17)),
        LeapSecond(utc=datetime(1979, 1, 1, 0, 0), dTAI_UTC=timedelta(0, 18)),
        LeapSecond(utc=datetime(1980, 1, 1, 0, 0), dTAI_UTC=timedelta(0, 19)),
        LeapSecond(utc=datetime(1981, 7, 1, 0, 0), dTAI_UTC=timedelta(0, 20)),
        LeapSecond(utc=datetime(1982, 7, 1, 0, 0), dTAI_UTC=timedelta(0, 21)),
        LeapSecond(utc=datetime(1983, 7, 1, 0, 0), dTAI_UTC=timedelta(0, 22)),
        LeapSecond(utc=datetime(1985, 7, 1, 0, 0), dTAI_UTC=timedelta(0, 23)),
        LeapSecond(utc=datetime(1988, 1, 1, 0, 0), dTAI_UTC=timedelta(0, 24)),
        LeapSecond(utc=datetime(1990, 1, 1, 0, 0), dTAI_UTC=timedelta(0, 25)),
        LeapSecond(utc=datetime(1991, 1, 1, 0, 0), dTAI_UTC=timedelta(0, 26)),
        LeapSecond(utc=datetime(1992, 7, 1, 0, 0), dTAI_UTC=timedelta(0, 27)),
        LeapSecond(utc=datetime(1993, 7, 1, 0, 0), dTAI_UTC=timedelta(0, 28)),
        LeapSecond(utc=datetime(1994, 7, 1, 0, 0), dTAI_UTC=timedelta(0, 29)),
        LeapSecond(utc=datetime(1996, 1, 1, 0, 0), dTAI_UTC=timedelta(0, 30)),
        LeapSecond(utc=datetime(1997, 7, 1, 0, 0), dTAI_UTC=timedelta(0, 31)),
        LeapSecond(utc=datetime(1999, 1, 1, 0, 0), dTAI_UTC=timedelta(0, 32)),
        LeapSecond(utc=datetime(2006, 1, 1, 0, 0), dTAI_UTC=timedelta(0, 33)),
        LeapSecond(utc=datetime(2009, 1, 1, 0, 0), dTAI_UTC=timedelta(0, 34)),
        LeapSecond(utc=datetime(2012, 7, 1, 0, 0), dTAI_UTC=timedelta(0, 35)),
        LeapSecond(utc=datetime(2015, 7, 1, 0, 0), dTAI_UTC=timedelta(0, 36)),
        LeapSecond(utc=datetime(2017, 1, 1, 0, 0), dTAI_UTC=timedelta(0, 37)),
        sentinel,
    ]


def dTAI_UTC_from_utc(utc_time):
    """TAI time = utc_time + dTAI_UTC_from_utc(utc_time)."""
    return _dTAI_UTC(utc_time, lambda ls: ls.utc)


def dTAI_UTC_from_tai(tai_time):
    """UTC time = tai_time - dTAI_UTC_from_tai(tai_time)."""
    return _dTAI_UTC(tai_time, lambda ls: ls.utc + ls.dTAI_UTC)


def _dTAI_UTC(time, leapsecond_to_time, leapseconds=leapseconds):
    """Get TAI-UTC difference in seconds for a given time.
    >>> from datetime import datetime, timedelta
    >>> _dTAI_UTC(datetime(1972, 1, 1), lambda ls: ls.utc)
    datetime.timedelta(seconds=10)
    >>> tai = lambda ls: ls.utc + ls.dTAI_UTC
    >>> _dTAI_UTC(datetime(2015, 7, 1, 0, 0, 34), tai)
    datetime.timedelta(seconds=35)
    >>> _dTAI_UTC(datetime(2015, 7, 1, 0, 0, 35), tai) # leap second
    datetime.timedelta(seconds=35)
    >>> _dTAI_UTC(datetime(2015, 7, 1, 0, 0, 36), tai)
    datetime.timedelta(seconds=36)
    Bulletin C 67 says "NO leap second will be introduced at the end
    of June 2024."[4] and therefore TAI-UTC is still 37s as of 10 June
    2024:
    >>> _dTAI_UTC(datetime(2024, 6, 10), lambda ls: ls.utc)
    datetime.timedelta(seconds=37)
    """
    leapseconds_list = leapseconds()
    transition_times = list(map(leapsecond_to_time, leapseconds_list))
    if time < transition_times[0]:
        raise ValueError("Dates before %s are not supported, got %r" % (transition_times[0], time))
    for i, (start, end) in enumerate(zip(transition_times, transition_times[1:])):
        if start <= time < end:
            return leapseconds_list[i].dTAI_UTC
    assert 0


def tai_to_utc(tai_time):
    """Convert TAI time given as datetime object to UTC time."""
    return tai_time - dTAI_UTC_from_tai(tai_time)


def utc_to_tai(utc_time):
    """Convert UTC time given as datetime object to TAI time."""
    return utc_time + dTAI_UTC_from_utc(utc_time)


def gps_to_utc(gps_time):
    """Convert GPS time given as datetime object to UTC time."""
    return tai_to_utc(gps_to_tai(gps_time))


def utc_to_gps(utc_time: datetime) -> datetime:
    """Convert UTC time given as datetime object to GPS time."""
    return tai_to_gps(utc_to_tai(utc_time))


def tai_to_gps(tai_time):
    """Convert TAI time given as datetime object to GPS time."""
    return tai_time - dTAI_GPS


def gps_to_tai(gps_time):
    """Convert GPS time given as datetime object to TAI time."""
    return gps_time + dTAI_GPS


if __name__ == "__main__":
    a = utc_to_gps(datetime.utcnow())
    b = datetime.utcnow()
    print(a, b)
