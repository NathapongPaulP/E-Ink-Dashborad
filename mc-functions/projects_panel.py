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
    config = None

TIMEZONE_OFFSET = 7 * 3600

POLL_SECOND = 60  # How often to ask the API
MIN_REFRESH_SECOND = 180
OFFLINE_AFTER = 3  # Last good image stays up until

# Pico have no idea what time it is IRL
# So ask the iternet time server NTP_EVERY_SECOND
NTP_EVERY_SECOND = 24 * 3600
SCREEN_H = 128
LINE_X, LINE_W = 8, 280
RIGHT = LINE_X + LINE_W
FIRST_TASK_Y = 36
TASK_H = 48
TASK_DRAWN_H = 38
NAME_CHARS = (LINE_W - 5 * 8) // 8
STATUS_CHARS = LINE_W // 8


def connect(attempts: int = 3, timeout_second: int = 15):
    if not config:
        raise OSError("no lessons/config.py")

    # STA_IF => Station Interface
    # PICO join someone's else WIFI
    # AP_IF => PICO create its own WIFI
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if wlan.isconnected():
        return wlan

    # If wlan.isconnected not True
    status = None
    for attempt in range(attempts):
        # attemp starts at 0 so one loop then if statement
        # The first WiFi connection after power-up always failed
        # Turning WiFi on and off so dont have to wait a whole POLL_SECOND
        if attempt:
            wlan.disconnect()
            wlan.active(False)
            time.sleep_ms(1000)
            wlan.active(True)
        print("connecting to", config.WIFI_SSID, f"(attempt {attempt + 1})")
        wlan.connect(config.WIFI_SSID, config.WIFI_PASSWORD)

        deadline = time.ticks_add(time.ticks_ms(), timeout_second * 1000)
        while not wlan.isconnected():
            if time.ticks_diff(deadline, time.ticks_ms()) <= 0:
                break
            time.sleep_ms(200)
        if wlan.isconnected():
            print("ip:", wlan.ifconfig()[0])
            return wlan
        status = wlan.status()

    # Ran out of attempts
    wlan.disconnect()
    raise OSError(f"WiFi Timeout, Status = {status}")


def fetch_projects():
    r = requests.get(config.API_BASE + "/api/projects", timeout=10)
    try:
        if r.status_code != 200:
            raise OSError(f"HTTP {r.status_code}")
        return r.json()
    finally:
        r.close()


def local_toaday():
    t = time.localtime(time.time() + TIMEZONE_OFFSET)
    return f"{t[0]:04d}-{t[1]:02d}-{t[2]:02d}"


def eisenhower(project):
    """
    Sort Projects according to eisonhower
    """
    return (
        not (project["urgent"] and project["important"]),
        not project["important"],
        not project["urgent"],
    )


def text_right(epd: EPD_2in9_Landscape, text: str, y: int) -> None:
    # 0x00 black ink
    epd.text(text, RIGHT - len(text) * 8, y, 0x00)


def eisenhow_tags(imp: bool, urge: bool) -> list:
    return [label for label, on in (("urge", urge), ("imp", imp)) if on]


def eisenhow_tag(epd: EPD_2in9_Landscape, name: str, imp: bool, urge: bool, y: int):
    x = LINE_X + len(name) * 8 + 6
    for label in eisenhow_tags(imp, urge):
        width = len(label) * 8 + 8
        epd.fill_rect(x, y - 2, width, 12, 0x00)
        epd.text(label, x + 3, y, 0xFF)
        x += width + 6


def task(epd: EPD_2in9_Landscape, name: str, imp: bool, urge: bool, prog: float, status: str, y: int) -> int:
    percent = f"{round(prog * 100)}%"
    tags_width = sum(len(label) * 8 + 14 for label in eisenhow_tags(imp, urge))
    fits = (RIGHT - len(percent) * 8 - 8 - LINE_X - tags_width) // 8
    name = name[:min(NAME_CHARS, fits)]
    epd.text(name, LINE_X, y, 0x00)
    eisenhow_tag(epd, name, imp, urge, y)
    text_right(epd, percent, y)
    epd.rect(LINE_X, y + 12, LINE_W, 12, 0x00)
    epd.rect(LINE_X, y + 12, int(LINE_W * prog), 12, 0x00, True)
    epd.text(status[:STATUS_CHARS], LINE_X, y + 30, 0x00)
    return y + TASK_H


def render(epd: EPD_2in9_Landscape, projects: list[dict], header_right: str, error=None):
    epd.fill(0xFF)
    epd.text(local_toaday(), LINE_X, 10, 0x00)
    text_right(epd, header_right, 10)
    epd.fill_rect(LINE_X, 24, LINE_W, 3, 0x00)

    if projects is None:
        if error:
            for i in range(3):
                line = error[i * STATUS_CHARS:(i + 1) * STATUS_CHARS]
                if line:
                    epd.text(line, LINE_X, FIRST_TASK_Y + i * 12, 0x00)

        return
    if not projects:
        epd.text("nothing active", LINE_X, FIRST_TASK_Y, 0x00)
        return

    y = FIRST_TASK_Y
    for p in sorted(projects, key=eisenhower):
        if y + TASK_DRAWN_H > SCREEN_H:
            break
        detail = p.get("current_step") or p["status"]
        y = task(epd, p["name"], p["important"], p["urgent"], p["progress"], detail, y)


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
    led = Pin("LED", Pin.OUT)
    led.on()

    epd = EPD_2in9_Landscape()
    epd.Clear(0xFF)
    epd.sleep()

    shown = None # Image on the panel (bytes)
    shown_ok = False # boot-blink or offline?
    last_refresh = None # tick_ms of the last refresh
    synced_at = None # ticks_ms of the last successful NTP sync
    failures = 0
    error = None

    while True:
        led.on()
        try:
            connect()
            if synced_at is None or time.ticks_diff(
                time.ticks_ms(), synced_at
            ) > NTP_EVERY_SECOND * 1000:
                if sync_clock():
                    synced_at = time.ticks_ms()
            gc.collect()
            projects = fetch_projects()
            failures = 0
            error = None
            n = len(projects)
            header_right = f"{n} project{"s" if n != 1 else ""}"
        except Exception as e:
            failures += 1
            print(f"fetch failed ({failures} in a row) {e}")
            projects = None
            header_right = "offline"
            error = f"{str(type(e).__name__)}: {str(e)}"

        if projects is not None or failures >= OFFLINE_AFTER or not shown:
            render(epd, projects, header_right, error)
            changed = not shown or epd.buffer != shown
            recovering = projects is not None and not shown_ok
            due = recovering or last_refresh is None or time.ticks_diff(
                time.ticks_ms(), last_refresh
            ) >= MIN_REFRESH_SECOND * 1000
            if changed and due:
                show(epd)
                shown = bytes(epd.buffer)
                shown_ok = projects is not None
                last_refresh = time.ticks_ms()
                print("refreshed:", header_right)
            elif changed:
                print("changed, waiting out", MIN_REFRESH_SECOND)

        gc.collect()
        led.off()
        time.sleep(POLL_SECOND)


try: 
    main()
except KeyboardInterrupt:
    raise
except Exception as e:
    import machine
    print("crashed, rebooting in 30s", e)
    time.sleep(30)
    machine.reset()