"""Live dashboard: fetch projects from the API and draw them on the e-ink panel.

The layout from hardcode_dashboard.py, fed by the fetch from 03_wifi_fetch.py.
It polls every POLL_S seconds but only refreshes the panel when the picture
would actually change, so edits do not make the screen flash on every poll.
Ctrl-C stops it. Run it from mc-functions/ so both imports resolve against
the working tree:

    cd mc-functions
    mpremote mount . run dashboard.py

The API has to listen on the LAN, not just 127.0.0.1:

    uv run fastapi dev app/main.py --host 0.0.0.0
"""

import gc
import time

import network
import ntptime
import requests
from machine import Pin

from eink_display import EPD_2in9_Landscape

try:
    from lessons import config
except ImportError:
    # Easy to miss when installing: with no USB attached, an import error here
    # would leave the screen frozen with no explanation. connect() reports it.
    config = None

# MicroPython has no zoneinfo; Asia/Bangkok has no DST, so a constant holds.
TZ_OFFSET = 7 * 3600

POLL_S = 60  # how often to ask the API; cheap, the panel stays asleep
# Waveshare's guidance for this panel is no more than one full refresh per
# ~3 minutes. A change is drawn within POLL_S..MIN_REFRESH_S of happening,
# and a burst of edits collapses into one refresh instead of one per edit.
MIN_REFRESH_S = 180
# One dropped request should not flash "offline" and then flash straight back.
# The last good image stays up until this many fetches in a row have failed.
OFFLINE_AFTER = 3
NTP_EVERY_S = 24 * 3600  # the RP2350 clock drifts; resync once a day

SCREEN_H = 128  # landscape: 296 wide, 128 tall
LINE_X, LINE_W = 8, 280
RIGHT = LINE_X + LINE_W
FIRST_TASK_Y = 36
TASK_H = 48  # name row, bar, status row, gap
TASK_DRAWN_H = 38  # how far below its y a task actually draws

# 8px per glyph with the built-in font. The name shares its row with the
# right-aligned "100%", so it gets 5 fewer characters than the status line.
NAME_CHARS = (LINE_W - 5 * 8) // 8
STATUS_CHARS = LINE_W // 8


def connect(attempts=3, timeout_s=15):
    if config is None:
        raise OSError("no lessons/config.py")
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if wlan.isconnected():
        return wlan

    status = None
    for attempt in range(attempts):
        if attempt:
            # Measured on this board: the first join after power-up fails
            # (status -1), while a join after power-cycling the radio took
            # ~4.7s every time. So retry here, from a cold radio, instead of
            # waiting a whole POLL_S with "offline" on the screen.
            wlan.disconnect()
            wlan.active(False)
            time.sleep_ms(1000)
            wlan.active(True)
        print("connecting to", config.WIFI_SSID, "(attempt %d)" % (attempt + 1))
        wlan.connect(config.WIFI_SSID, config.WIFI_PASSWORD)

        # ticks_diff, never <, so the timeout survives the ticks_ms wraparound.
        deadline = time.ticks_add(time.ticks_ms(), timeout_s * 1000)
        while not wlan.isconnected():
            if time.ticks_diff(deadline, time.ticks_ms()) <= 0:
                break
            time.sleep_ms(200)
        if wlan.isconnected():
            print("ip:", wlan.ifconfig()[0])
            return wlan
        status = wlan.status()

    wlan.disconnect()  # leave the radio clean for the next poll
    raise OSError("wifi timeout, status=%d" % status)


def fetch_projects():
    r = requests.get(config.API_BASE + "/api/projects", timeout=10)
    try:
        if r.status_code != 200:
            raise OSError("HTTP %d" % r.status_code)
        return r.json()
    finally:
        r.close()  # an unclosed response leaks its socket


def local_today():
    # The board's clock is UTC after ntptime.settime(); shift it, then format.
    t = time.localtime(time.time() + TZ_OFFSET)
    return "%04d-%02d-%02d" % (t[0], t[1], t[2])


def eisenhower(p):
    """Sort key: urgent+important first, then important, then urgent."""
    return (not (p["urgent"] and p["important"]), not p["important"], not p["urgent"])


def text_right(epd, s, y):
    epd.text(s, RIGHT - len(s) * 8, y, 0x00)


def task(epd, name, prog, status, y):
    epd.text(name[:NAME_CHARS], LINE_X, y, 0x00)
    text_right(epd, "%d%%" % int(prog * 100), y)
    epd.rect(LINE_X, y + 12, LINE_W, 12, 0x00)
    epd.rect(LINE_X, y + 12, int(LINE_W * prog), 12, 0x00, True)
    epd.text(status[:STATUS_CHARS], LINE_X, y + 30, 0x00)
    return y + TASK_H


def render(epd, projects, header_right, error=None):
    epd.fill(0xFF)  # white
    epd.text(local_today(), LINE_X, 10, 0x00)
    text_right(epd, header_right, 10)
    epd.fill_rect(LINE_X, 24, LINE_W, 3, 0x00)

    if projects is None:
        # On a power bank there is no serial console, so the panel is the only
        # place the reason can show up. Wrapped over up to three lines.
        if error:
            for i in range(3):
                line = error[i * STATUS_CHARS:(i + 1) * STATUS_CHARS]
                if line:
                    epd.text(line, LINE_X, FIRST_TASK_Y + i * 12, 0x00)
        return
    if not projects:
        epd.text("nothing active", LINE_X, FIRST_TASK_Y, 0x00)
        return

    # Only two tasks fit in 128px. The header still shows the full count, so
    # anything cut off here is visibly "more than shown", not silently lost.
    y = FIRST_TASK_Y
    for p in sorted(projects, key=eisenhower):
        if y + TASK_DRAWN_H > SCREEN_H:
            break
        # The next step is the useful line on a glanceable screen. Fall back to
        # status when there is none (no steps yet, or every step is done).
        detail = p.get("current_step") or p["status"]
        y = task(epd, p["name"], p["progress"], detail, y)


def show(epd):
    """One full refresh. The panel sleeps between refreshes; init() wakes it."""
    epd.init()
    epd.display_Base(epd.buffer)
    epd.sleep()  # holds the image unpowered; also waits the 2s it needs


def sync_clock():
    try:
        ntptime.settime()
        return True
    except Exception as e:  # blocked UDP 123 - a wrong date beats no dashboard
        print("ntp failed:", e)
        return False


def main():
    # The Pico 2 W has no power LED, and e-ink keeps its last image unpowered,
    # so a dead board and a running one look the same. The LED is lit while a
    # poll is in progress and dark while sleeping: a blink every POLL_S means
    # it's alive; never lit means no power. On from boot until the first poll.
    led = Pin("LED", Pin.OUT)
    led.on()

    epd = EPD_2in9_Landscape()
    epd.Clear(0xFF)
    epd.sleep()

    shown = None  # bytes of the image currently on the panel
    shown_ok = False  # is that image real data (not boot-blank or offline)?
    last_refresh = None  # ticks_ms of the last refresh
    synced_at = None  # ticks_ms of the last successful NTP sync
    failures = 0
    error = None

    while True:
        led.on()
        try:
            connect()
            if synced_at is None or time.ticks_diff(
                time.ticks_ms(), synced_at
            ) > NTP_EVERY_S * 1000:
                if sync_clock():
                    synced_at = time.ticks_ms()
            gc.collect()
            projects = fetch_projects()
            failures = 0
            error = None
            n = len(projects)
            header_right = "%d project%s" % (n, "" if n == 1 else "s")
        except Exception as e:
            failures += 1
            print("fetch failed (%d in a row):" % failures, e)
            projects = None
            header_right = "offline"
            # No retry count in here: the text has to stay the same between
            # polls, or every failed poll would count as a change and redraw.
            error = "%s: %s" % (type(e).__name__, e)

        # Before OFFLINE_AFTER, a failure leaves the last good image alone.
        # With nothing shown yet there is nothing to protect: say offline now.
        if projects is not None or failures >= OFFLINE_AFTER or shown is None:
            render(epd, projects, header_right, error)
            # Compare pixels, not data: that catches every visible change,
            # including the date rolling over at midnight, and ignores changes
            # that do not show (a third project, a step beyond the first undone).
            changed = shown is None or epd.buffer != shown
            # MIN_REFRESH_S exists to stop edits from causing constant flashing.
            # Getting real data up after boot or an outage is not that, so it
            # skips the wait; otherwise a power-up could spend 3 minutes on
            # "offline" after the network had already come back.
            recovering = projects is not None and not shown_ok
            due = recovering or last_refresh is None or time.ticks_diff(
                time.ticks_ms(), last_refresh
            ) >= MIN_REFRESH_S * 1000
            if changed and due:
                show(epd)
                shown = bytes(epd.buffer)
                shown_ok = projects is not None
                last_refresh = time.ticks_ms()
                print("refreshed:", header_right)
            elif changed:
                print("changed, waiting out MIN_REFRESH_S")

        gc.collect()
        led.off()
        time.sleep(POLL_S)


try:
    main()
except KeyboardInterrupt:
    # Ctrl-C, and how mpremote takes over to copy files: must never reboot.
    raise
except Exception as e:
    # Unattended on a power bank, a crash would otherwise leave the old image
    # up forever with nothing running behind it. Reboot and start over; the
    # pause stops a crash-at-boot from turning into a tight reset loop.
    import machine
    print("crashed, rebooting in 30s:", e)
    time.sleep(30)
    machine.reset()
