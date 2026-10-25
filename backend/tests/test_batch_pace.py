"""A run's time left settles and comes down as parts land (op-26).

Dana pressed "Check all 270 again" at 19:08:29 and watched the Running panel:
"~89 min left at 180 parts an hour" at 19:11:55, three parts having landed
together, then "~3 h 40 min left at 73 parts an hour" at 19:15:54. The pace was
measured from the first finished part, so three parts in a minute read as 180 an
hour. Now there is no estimate until 10 parts or 10 minutes have finished since
the run (re)started, and then the pace is the work done over the last 30
minutes: parts finished in the window, plus the share of each part in flight
(at the run's typical time per part), over the window's length.

Pure: batch_service.pace_from on her real timeline (staging batch 23's item
start and finish times, read from the database) and on a steady run.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.services import batch_service as bs

DAY = datetime(2026, 10, 22, tzinfo=timezone.utc)
RESTART = DAY.replace(hour=19, minute=8, second=29)
LEFT = 270  # parts to go when she pressed "Check all 270 again"

# Batch 23's parts after the re-check: (worker started it, it finished).
DANA = [
    ("19:08:33", "19:11:42"), ("19:08:33", "19:11:50"), ("19:08:33", "19:11:51"),
    ("19:08:33", "19:15:41"), ("19:08:33", "19:15:48"),
    ("19:18:39", "19:26:23"), ("19:18:39", "19:26:50"), ("19:21:48", "19:27:05"),
    ("19:21:55", "19:27:20"), ("19:21:59", "19:27:51"),
    ("19:28:46", "19:38:24"), ("19:37:13", "19:42:48"), ("19:36:34", "19:43:15"),
]


def _t(hms: str) -> datetime:
    h, m, s = (int(x) for x in hms.split(":"))
    return DAY.replace(hour=h, minute=m, second=s)


def _eta(parts: list[tuple[datetime, datetime]], now: datetime, since: datetime = RESTART, left0: int = LEFT):
    """(seconds left, parts an hour) at ``now``, or None while there's no estimate."""
    finished = [(s, e) for s, e in parts if e <= now]
    in_flight = [s for s, e in parts if s <= now < e]
    per_second, _state = bs.pace_from(finished, in_flight, since=since, now=now)
    if not per_second:
        return None
    return (left0 - len(finished)) / per_second, per_second * 3600


def test_no_time_left_at_the_moments_dana_saw_a_guess():
    parts = [(_t(a), _t(b)) for a, b in DANA]
    # 19:11:55 "~89 min left at 180 parts an hour" ... 19:15:54 "~3 h 40 min left at 73 parts an hour".
    for hms in ("19:11:55", "19:12:55", "19:13:25", "19:13:31", "19:15:54"):
        assert _eta(parts, _t(hms)) is None, hms
    finished = [(s, e) for s, e in parts if e <= _t("19:15:54")]
    assert bs.pace_from(finished, [], since=RESTART, now=_t("19:15:54"))[1] == "measuring"


def test_her_timeline_settles_once_measured():
    parts = [(_t(a), _t(b)) for a, b in DANA]
    # Ten minutes after the restart there is an estimate: 5 parts and two in flight, about 30 an hour.
    first = _eta(parts, _t("19:18:29"))
    assert first is not None
    assert 25 <= first[1] <= 35
    # From then until the next batch of parts lands, sampled every 30 s, no 4-minute span moves the
    # estimate by more than a sixth (the old pace grew it by 2 h 10 min in 4 minutes).
    samples = []
    now = _t("19:18:29")
    while now <= _t("19:28:29"):
        samples.append((now, _eta(parts, now)[0]))
        now += timedelta(seconds=30)
    for i, (t0, e0) in enumerate(samples):
        for t1, e1 in samples[i + 1:]:
            if t1 - t0 > timedelta(minutes=4):
                break
            assert abs(e1 - e0) <= e0 / 6, (t0, e0, t1, e1)


def _steady(n: int, *, slots: int, minutes: float, jitter: float = 0.0, start: datetime = RESTART):
    """``n`` parts, ``slots`` at a time, each taking ``minutes`` (± ``jitter`` of it, a fixed pattern)."""
    free = [start + timedelta(seconds=4)] * slots
    out = []
    for i in range(n):
        k = min(range(slots), key=lambda j: free[j])
        took = minutes * 60 * (1 + jitter * ((i * 7919) % 11 - 5) / 5)
        s = free[k]
        e = s + timedelta(seconds=took)
        out.append((s, e))
        free[k] = e
    return out


def test_a_steady_run_never_swings_and_comes_down_as_parts_land():
    for slots, minutes, jitter in ((4, 3.0, 0.0), (4, 3.0, 0.4), (10, 1.0, 0.25), (3, 6.0, 0.0)):
        parts = _steady(270, slots=slots, minutes=minutes, jitter=jitter)
        true_rate = slots / minutes * 60  # parts an hour
        now = RESTART + timedelta(minutes=10)
        samples = []
        while now < RESTART + timedelta(hours=3) and sum(1 for _s, e in parts if e <= now) < 260:
            got = _eta(parts, now)
            assert got is not None, (slots, minutes, now)
            samples.append((now, got[0], got[1]))
            now += timedelta(minutes=1)
        for t0, e0, r0 in samples:
            # The pace is the run's own, within a sixth.
            assert abs(r0 - true_rate) <= true_rate / 6, (slots, minutes, jitter, t0, r0, true_rate)
        for (t0, e0, _r0), (t4, e4, _r4) in zip(samples, samples[4:]):
            # Four minutes later the time left is about four minutes less: never a swing.
            assert abs((e0 - 240) - e4) <= max(300, e0 / 8), (slots, minutes, jitter, t0, e0, e4)


def test_a_run_that_stalls_slows_its_own_pace_and_one_with_nothing_in_30_minutes_has_none():
    parts = _steady(40, slots=4, minutes=2.0)
    last = max(e for _s, e in parts)
    at_end = _eta(parts, last)
    later = _eta(parts, last + timedelta(minutes=15))
    assert at_end and later and later[1] < at_end[1]
    finished = parts
    assert bs.pace_from(finished, [], since=RESTART, now=last + timedelta(minutes=31)) == (None, "stalled")


def test_ten_parts_open_the_estimate_before_ten_minutes():
    parts = _steady(270, slots=10, minutes=0.5)
    # Ten parts landed at about 34 s: an estimate at once, at the run's own pace.
    got = _eta(parts, RESTART + timedelta(seconds=40))
    assert got is not None and abs(got[1] - 1200) <= 200


def test_the_run_restarted_when_it_was_checked_again_or_resumed():
    from types import SimpleNamespace

    started = DAY.replace(hour=15, minute=56, second=48)
    b = SimpleNamespace(started_at=started, manifest_json={})
    assert bs.run_started_at(b) == started
    b.manifest_json = {"restarted_at": RESTART.isoformat()}
    assert bs.run_started_at(b) == RESTART
    resumed = RESTART + timedelta(minutes=40)
    b.manifest_json = {"restarted_at": RESTART.isoformat(), "resumes": {"count": 1, "done": 30, "at": resumed.isoformat()}}
    assert bs.run_started_at(b) == resumed
