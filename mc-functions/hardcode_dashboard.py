import time
from eink_display import EPD_2in9_Landscape

# MicroPython has no datetime: localtime() returns a tuple,
# (year, month, day, hour, minute, second, weekday, yearday)
t = time.localtime()
today = "%04d-%02d-%02d" % (t[0], t[1], t[2])

LINE_X, LINE_W = 8, 280
RIGHT = LINE_X + LINE_W

def text_right(s, y, color=0x00):
    epd.text(s, RIGHT - len(s) * 8, y, color)


def task(task: str, prog: float, status: str, y: int) -> int:
    epd.text(task, LINE_X, y, 0x00)
    text_right(f"{(int(prog * 100))}%", y)
    epd.rect(LINE_X, y + 12, LINE_W, 12, 0x00)
    epd.rect(LINE_X, y + 12, int(LINE_W*prog), 12, 0x00, True)
    epd.text(status, LINE_X, y + 30, 0x00)
    return y + 48


epd = EPD_2in9_Landscape()
epd.Clear(0xFF)

epd.fill(0xFF)  # buffer = white (0x00 = black)
epd.text(today, LINE_X, 10, 0x00)  # draw in black
text_right("5 projects", 10)
epd.fill_rect(LINE_X, 24, LINE_W, 3, 0x00)  # 3px-thick horizontal line
next_task_start_at = task("EPaper Learning", 0.6, "Learn how to put on a display", 36)
next_task_start_at = task("Sanctuary", 0.3, "Design Webpage", next_task_start_at)
epd.display_Base(epd.buffer)  # now send it

time.sleep(2)
epd.sleep()  # park the panel when done
