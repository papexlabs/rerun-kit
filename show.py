"""What the re-run kit draws in a terminal.

rerun.py prints plain lines, one after another, exactly as it always has. In a terminal a person
looks at (256 colours or more, UTF-8, at least 76 columns and 24 lines) this file draws the same run
instead: Papex's name, the checks of this computer, and the run inside a frame: its steps scanned
while they run and ticked when done, the running step's time in large digits, the files the list
names as a field of cells, and with --docker the container's network. At the end: whether Lean
accepted the proof, the result going to Papex, and what to do next. Everything else gets the plain
lines: a pipe, a log, an AI app running the kit, NO_COLOR, --plain, a terminal that does not say it
has 256 colours, or one that is too small.

Nothing is drawn that did not happen. A row is ticked only once the kit has gone past it; the files
light up only after the kit has found that every one has the list's SHA-256; the network line breaks
only when the kit has cut the container's network; a mark flies to Papex only after Papex took the
result. The words are the kit's own.

rerun.py runs without this file (in the container it is alone). Only the standard library is used.
"""

import math
import os
import random
import re
import shutil
import signal
import subprocess
import sys
import threading
import time

# Block letters with a shadow, six rows high: the full blocks are the letter, the box lines its shadow.
LOGO = (
    "██████╗  █████╗ ██████╗ ███████╗██╗  ██╗",
    "██╔══██╗██╔══██╗██╔══██╗██╔════╝╚██╗██╔╝",
    "██████╔╝███████║██████╔╝█████╗   ╚███╔╝ ",
    "██╔═══╝ ██╔══██║██╔═══╝ ██╔══╝   ██╔██╗ ",
    "██║     ██║  ██║██║     ███████╗██╔╝ ██╗",
    "╚═╝     ╚═╝  ╚═╝╚═╝     ╚══════╝╚═╝  ╚═╝",
)
DIGITS = {
    "0": (" ██████╗ ", "██╔═████╗", "██║██╔██║", "████╔╝██║", "╚██████╔╝", " ╚═════╝ "),
    "1": (" ██╗", "███║", "╚██║", " ██║", " ██║", " ╚═╝"),
    "2": ("██████╗ ", "╚════██╗", " █████╔╝", "██╔═══╝ ", "███████╗", "╚══════╝"),
    "3": ("██████╗ ", "╚════██╗", " █████╔╝", " ╚═══██╗", "██████╔╝", "╚═════╝ "),
    "4": ("██╗  ██╗", "██║  ██║", "███████║", "╚════██║", "     ██║", "     ╚═╝"),
    "5": ("███████╗", "██╔════╝", "███████╗", "╚════██║", "███████║", "╚══════╝"),
    "6": (" ██████╗ ", "██╔════╝ ", "███████╗ ", "██╔═══██╗", "╚██████╔╝", " ╚═════╝ "),
    "7": ("███████╗", "╚════██║", "    ██╔╝", "   ██╔╝ ", "   ██║  ", "   ╚═╝  "),
    "8": (" █████╗ ", "██╔══██╗", "╚█████╔╝", "██╔══██╗", "╚█████╔╝", " ╚════╝ "),
    "9": (" █████╗ ", "██╔══██╗", "╚██████║", " ╚═══██║", " █████╔╝", " ╚════╝ "),
    ":": ("   ", "██╗", "╚═╝", "██╗", "╚═╝", "   "),
}
CLOCK_WIDE = 39   # "00:00" in the large digits: four of the widest digits and the colon
LABEL = 11        # the width of a row's name
SPIN = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
RICH_TERMS = ("xterm-kitty", "xterm-ghostty", "alacritty", "wezterm", "foot", "contour")
ANSI = re.compile(r"\x1b\[[0-9;]*m")

# The kit's lines that start a step of a run, as rerun.py says them (on this computer, or inside the
# container with --docker): the row's name, whether the step runs until the next thing is said ("run")
# or is a fact the kit has just established ("fact"), whether it downloads, and the row's words once done.
STEPS = (
    (r"Preparing the container", "Container", "run", True, lambda m: "prepared"),
    (r"Lean's installer \((elan \S+)\)", "Installer", "run", True, lambda m: m.group(1) + ", checked by SHA-256"),
    (r"The repository at commit ([0-9a-f]+)", "Repository", "run", True, lambda m: "at commit " + m.group(1)),
    (r"(\d+) files match the list's SHA-256 values", "Files", "fact", False, lambda m: m.group(0)),
    (r"Text search: (.+)", "Search", "fact", False, lambda m: m.group(1)),
    (r"Lean (\S+) and Mathlib's ready-made build \(the long step\)", "Lean", "run", True,
     lambda m: f"Lean {m.group(1)} and Mathlib's ready-made build"),
    (r"The container's network is cut", "Network", "fact", False, lambda m: "the container's network is cut"),
    (r"Building the proof", "Build", "run", False, lambda m: "lake build passed"),
    (r"Asking Lean which axioms the theorem rests on", "Axioms", "run", False,
     lambda m: "only axioms the list permits"),
)
STEPS = tuple((re.compile(r"^  " + pattern + r"$"),) + tuple(rest) for pattern, *rest in STEPS)
HEARTBEAT = re.compile(r"^    … .+, (\d+ min \d\d s|\d+ s)$")   # "still at it", every 20 s: the clock says it


def wanted(plain=False, stream=None):
    """True when the show may be drawn: a person's terminal that has 256 colours or more, colour
    allowed, not asked to be plain. A terminal that does not say so gets the plain lines."""
    stream = stream or sys.stdout
    term = os.environ.get("TERM", "")
    if plain or os.environ.get("NO_COLOR") or term in ("", "dumb", "linux"):
        return False
    if not ("256color" in term or "direct" in term or term in RICH_TERMS
            or os.environ.get("COLORTERM", "").lower() in ("truecolor", "24bit")):
        return False
    try:
        return stream.isatty()
    except (AttributeError, ValueError):
        return False


def fits(stream=None):
    """Whether this terminal has the characters and the room for the show."""
    stream = stream or sys.stdout
    encoding = (getattr(stream, "encoding", "") or "").lower().replace("-", "")
    size = shutil.get_terminal_size((80, 24))
    return encoding.startswith("utf") and size.columns >= 76 and size.lines >= 24


def make(plain=False):
    """The show for this terminal, or None for the plain lines."""
    if not wanted(plain) or not fits():
        return None
    return Stage()


def seen(text):
    """How many columns a painted text takes on the screen."""
    return len(ANSI.sub("", text))


def mix(a, b, t):
    t = 0.0 if t < 0 else 1.0 if t > 1 else t
    return (int(a[0] + (b[0] - a[0]) * t), int(a[1] + (b[1] - a[1]) * t), int(a[2] + (b[2] - a[2]) * t))


def wrap(text, width):
    """Words to lines of at most `width`; a short part in brackets, such as "(the long step)", stays
    on one line."""
    text = re.sub(r"\([^()]{1,20}\)", lambda m: m.group().replace(" ", "\x00"), text)
    lines, line = [], ""
    for word in text.split():
        if line and len(line) + 1 + len(word) > width:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    return [part.replace("\x00", " ") for part in lines + ([line] if line else [])]


def clauses(text, width):
    """A sentence to lines at its commas where they fit, so each line reads as a piece of it."""
    parts = text.replace(", ", ",\x01").split("\x01")
    if any(len(part) > width for part in parts):
        return wrap(text, width)
    lines = [parts[0]]
    for part in parts[1:]:
        if len(lines[-1]) + 1 + len(part) <= width:
            lines[-1] += " " + part
        else:
            lines.append(part)
    return lines


def took_text(seconds):
    """A step's time as the kit writes times: 4.2 s, 2 min 05 s."""
    if seconds is None:
        return ""
    if seconds < 60:
        return f"{seconds:.1f} s"
    seconds = int(seconds)
    return f"{seconds // 60} min {seconds % 60:02d} s"


def clock_rows(seconds):
    """Minutes and seconds in the large digits, as six rows of text."""
    seconds = max(0, int(seconds))
    text = f"{seconds // 60:02d}:{seconds % 60:02d}"
    return ["".join(DIGITS[ch][row] for ch in text) for row in range(6)]


def field_columns(total, width):
    """About four cells wide for each one high; two columns of the screen for each cell."""
    return max(1, min(total, 30, (max(width, 4) + 1) // 2, math.ceil(math.sqrt(total * 4))))


def light_background(stream):
    """True when the terminal says its background is light, False when dark, None when it does not say.

    Asked the usual way (OSC 11) and waited for a fifth of a second at most; a terminal that does not
    answer is taken as dark, which most are. PAPEX_KIT_BACKGROUND=light or dark says it instead."""
    said = os.environ.get("PAPEX_KIT_BACKGROUND", "").lower()
    if said in ("light", "dark"):
        return said == "light"
    try:
        import select
        import termios
        import tty
        if not sys.stdin.isatty() or not stream.isatty():
            return None
        fd = sys.stdin.fileno()
        before = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            stream.write("\x1b]11;?\x07")
            stream.flush()
            answer, until = b"", time.monotonic() + 0.2
            while time.monotonic() < until:
                ready, _, _ = select.select([fd], [], [], max(0.0, until - time.monotonic()))
                if not ready:
                    break
                answer += os.read(fd, 64)
                if answer.endswith(b"\x07") or answer.endswith(b"\x1b\\"):
                    break
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, before)
        found = re.search(rb"rgb:([0-9a-fA-F]+)/([0-9a-fA-F]+)/([0-9a-fA-F]+)", answer)
        if not found:
            return None
        r, g, b = (int(part[:2], 16) for part in found.groups())
        return 0.299 * r + 0.587 * g + 0.114 * b > 140
    except Exception:  # never worth stopping a run for
        return None


class Stage:
    """The kit's run, drawn. rerun.py talks to it as it talks to its plain printer: say() with the
    kit's own line (and, for some lines, what the line is about), step() around a check of this
    computer, phase() for a part of the run inside the container, fail() with the kit's last word."""

    def __init__(self, stream=None):
        self.out = stream or sys.stdout
        self.true_colour = os.environ.get("COLORTERM", "").lower() in ("truecolor", "24bit")
        ground = light_background(self.out)
        self.light = ground is True
        if ground is True:     # a light terminal: the same hues, darker, and the flash goes to petrol
            self.stops = [(9, 58, 58), (15, 107, 102), (36, 145, 136), (40, 160, 165)]
            self.flash, self.edge, self.seal = (4, 34, 34), (120, 160, 156), (166, 58, 18)
        elif ground is False:  # a dark terminal: up to the pale teal, and the flash is white
            self.stops = [(15, 107, 102), (36, 145, 136), (79, 182, 194), (170, 235, 225)]
            self.flash, self.edge, self.seal = (244, 252, 250), (24, 88, 84), (232, 130, 90)
        else:                  # a terminal that does not say: teals that read on dark and on light
            self.stops = [(15, 107, 102), (36, 145, 136), (60, 165, 170), (79, 182, 194)]
            self.flash, self.edge, self.seal = (140, 225, 215), (40, 110, 106), (201, 88, 47)
        self.paper, self.plate = (244, 246, 246), (9, 58, 58)
        self.lock = threading.Lock()
        self.region = 0           # lines of the part that is painted again and again
        self.painter = None
        self.stop_painting = threading.Event()
        self.cursor_hidden = False
        self.opened = False
        self.leaving = []         # the kit's sentence about what leaves this computer, until the opening
        self.early = []           # what the kit said before the opening
        self.later = []           # what another thread said, for the main thread to show
        self.unit = None          # the run being drawn in its frame
        self.pending = None       # a check of this computer waiting for its words
        self.result_path = None
        self.after = []           # the "Next" box

    # ---------------------------------------------------------------- colour and writing

    def code(self, rgb, ground=False):
        if self.true_colour:
            return ("48" if ground else "38") + ";2;%d;%d;%d" % rgb
        # The 256 colours' cube has the levels 0, 95, 135, 175, 215, 255 for each of red, green and blue.
        r, g, b = (0 if c < 48 else 1 if c < 115 else (c - 35) // 40 for c in rgb)
        return ("48" if ground else "38") + ";5;%d" % (16 + 36 * r + 6 * g + b)

    def ink(self, text, fg=None, bg=None, bold=False, dim=False):
        codes = (["1"] if bold else []) + (["2"] if dim else [])
        if fg:
            codes.append(self.code(fg))
        if bg:
            codes.append(self.code(bg, True))
        return f"\x1b[{';'.join(codes)}m{text}\x1b[0m" if codes and text else text

    def grad(self, t):
        """Papex's teals, from the deep one (0) to the pale one (1)."""
        t = 0.0 if t < 0 else 1.0 if t > 1 else t
        at = t * (len(self.stops) - 1)
        i = min(int(at), len(self.stops) - 2)
        return mix(self.stops[i], self.stops[i + 1], at - i)

    def shaded(self, rows, body):
        """Rows of block letters as text: body(x, y) colours a full block, the box lines are its shadow."""
        lines = []
        for y, row in enumerate(rows):
            out = []
            for x, ch in enumerate(row):
                if ch == " ":
                    out.append(" ")
                    continue
                colour = body(x, y)
                out.append(self.ink(ch, fg=colour if ch == "█" else mix(colour, self.edge, 0.72)))
            lines.append("".join(out))
        return lines

    def width(self):
        return max(40, min(shutil.get_terminal_size((80, 24)).columns, 100))

    def write(self, text):
        """Write all of `text`. Ctrl-C in the middle of a picture would leave half of it and the
        cursor inside it, so it is held back for the length of one write and acted on right after."""
        hold = threading.current_thread() is threading.main_thread() and hasattr(signal, "pthread_sigmask")
        before = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT}) if hold else None
        try:
            self.out.write(text)
            self.out.flush()
        finally:
            if hold:
                signal.pthread_sigmask(signal.SIG_SETMASK, before)

    def cursor(self, shown):
        if shown == self.cursor_hidden:
            self.write("\x1b[?25h" if shown else "\x1b[?25l")
            self.cursor_hidden = not shown

    def lines_out(self, text, indent=2, colour=None, dim=False, bold=False):
        """A text of the kit's, wrapped to the terminal, each line indented."""
        for part in wrap(text, self.width() - indent - 2):
            self.write(" " * indent + self.ink(part, fg=colour, dim=dim, bold=bold) + "\n")

    # ---------------------------------------------------------------- the part painted in place

    def repaint(self, lines):
        """Draw `lines` over what was drawn the last time (the lock is held by the caller)."""
        text = f"\x1b[{self.region}F" if self.region else ""
        text += "".join("\x1b[2K" + line + "\n" for line in lines)
        text += "\x1b[J" if len(lines) < self.region else ""
        self.region = len(lines)
        self.write(text)

    def paint_loop(self, frame, rate):
        tick = 0
        while not self.stop_painting.wait(1.0 / rate):
            tick += 1
            with self.lock:
                self.repaint(frame(tick))

    def start_painting(self, frame, rate=15):
        self.stop_painting.clear()
        self.cursor(False)
        with self.lock:
            self.region = 0
            self.repaint(frame(0))
        self.painter = threading.Thread(target=self.paint_loop, args=(frame, rate), daemon=True)
        self.painter.start()

    def halt(self):
        """Stop the painter; what it drew last stays until it is drawn once more."""
        if self.painter:
            self.stop_painting.set()
            self.painter.join(1.0)
            self.painter = None

    def end_painting(self, frame):
        """Stop the painter and leave the last picture standing as ordinary lines."""
        self.halt()
        with self.lock:
            self.repaint(frame(-1))
            self.region = 0
        self.cursor(True)

    def play(self, frame, seconds, rate=30):
        """Paint frame(t) for `seconds`, then leave its last picture standing as ordinary lines."""
        self.cursor(False)
        start = time.monotonic()
        try:
            with self.lock:
                self.region = 0
            while True:
                t = time.monotonic() - start
                with self.lock:
                    self.repaint(frame(min(t, seconds)))
                if t >= seconds:
                    break
                time.sleep(1.0 / rate)
        except KeyboardInterrupt:   # stopped half-way: the finished picture, whole, and the cursor under it
            with self.lock:
                self.repaint(frame(seconds))
            raise
        finally:
            with self.lock:
                self.region = 0
            self.cursor(True)

    # ---------------------------------------------------------------- the opening

    def open(self, name=None):
        """PAPEX assembles out of sparks, a light passes over it, and the line under it is typed."""
        self.opened = True
        width = self.width()
        high, wide = len(LOGO), len(LOGO[0])
        rnd = random.Random(11)
        born = [[x / wide * 0.5 + rnd.random() * 0.28 for x in range(wide)] for _ in range(high)]
        words = ("Run it yourself", f"  ·  {name}" if name else "")
        typed_all = len(words[0]) + len(words[1])
        rule = min(wide, width - 4)
        flicker = random.Random()

        def frame(t):
            sweep = (t - 0.95) / 0.6 * 1.5 - 0.25   # the light's place, across and a little down
            lines = [""]
            for y, row in enumerate(LOGO):
                out = ["  "]
                for x, ch in enumerate(row):
                    age = t - born[y][x]
                    if ch == " " or age < 0:
                        out.append(" ")
                        continue
                    base = self.grad(0.12 + 0.82 * x / wide)
                    if age < 0.3:   # a cell arrives as a spark, flickering through shades, and cools into place
                        out.append(self.ink("░▒▓"[flicker.randrange(3)], fg=mix(self.flash, base, age / 0.3)))
                        continue
                    glow = max(0.0, 1 - abs((x / wide + 0.05 * y) - sweep) / 0.09)
                    lit = mix(base, self.flash, glow * 0.9)
                    out.append(self.ink(ch, fg=lit if ch == "█" else mix(lit, self.edge, 0.72)))
                lines.append("".join(out))
            lines.append("")
            typed = max(0, min(typed_all, int((t - 0.9) * 70)))
            first, second = words[0][:typed], words[1][:max(0, typed - len(words[0]))]
            caret = self.ink("▌", fg=self.grad(0.9)) if 0 < typed < typed_all else ""
            lines.append("  " + self.ink(first, bold=True) + self.ink(second, dim=True) + caret)
            drawn = max(0, min(rule, int((t - 1.15) / 0.45 * rule)))
            lines.append("  " + "".join(
                self.ink("◢◣"[i % 2], fg=mix(self.grad(0.1 + 0.6 * i / rule), self.flash,
                                             max(0.0, 1 - abs(i - drawn) / 3) if drawn < rule else 0.0))
                for i in range(drawn)))
            lines.append("")
            return lines

        self.play(frame, 1.75)

    def begin(self, name=None):
        """The opening, once, then what the kit said before it: what leaves this computer, and notes."""
        if self.opened:
            return
        self.open(name)
        self.show_said()

    def show_said(self):
        if self.leaving:
            self.lines_out(" ".join(self.leaving), dim=True)
            self.write("\n")
            self.leaving = []
        for note in self.early:
            self.lines_out(note.strip(), colour=self.seal)
        if self.early:
            self.write("\n")
        self.early = []

    # ---------------------------------------------------------------- what the kit says

    def say(self, line="", event=None, **facts):
        if threading.current_thread() is not threading.main_thread():
            with self.lock:   # said while the run waits for it: shown by the main thread next
                self.later.append((line, event, facts))
            return
        for said in self.take_later():
            self.hear(*said)
        self.hear(line, event, facts)

    def take_later(self):
        with self.lock:
            later, self.later = self.later, []
        return later

    def hear(self, line, event, facts):
        if event == "leaves":
            if line:
                self.leaving.append(line)
        elif event == "check":
            self.checked(facts.get("good"), facts.get("detail", line))
        elif event == "ready":
            self.ready(facts.get("good"), line)
        elif event == "unit":
            self.start_unit(line, facts)
        elif event == "repo":
            pass   # in the frame's top edge
        elif event in ("passed", "failed"):
            self.outcome(line, event == "passed", facts.get("record") or {})
        elif event == "axioms":
            self.axioms_line(line, facts.get("name", ""))
        elif event == "log":
            self.lines_out(line.strip(), colour=self.seal)
        elif event == "result":
            if facts.get("path"):
                self.result_path = facts["path"]
        elif event == "sent":
            self.sent(line)
        elif event == "page":
            self.after.append(facts.get("url", line.strip()))
        elif event == "unsent":
            self.write("\n  " + self.ink("✗", fg=self.seal, bold=True) + f" {'Result':<{LABEL}}  "
                       + self.ink(f"not sent ({facts.get('why', '')})", fg=self.seal) + "\n")
        elif event == "advice":
            self.after = clauses(line.strip(), min(60, self.width() - 10))
        elif event == "end":
            self.finish(facts.get("path", ""))
        else:
            self.heard(line)

    def heard(self, line, inside=False):
        """A line without a name: a step of the run, a sign of life, or a note."""
        text = line.rstrip("\r\n")
        if not text.strip() or HEARTBEAT.match(text):
            return
        for pattern, label, kind, downloads, done in STEPS:
            m = pattern.match(text)
            if m and self.unit is not None:
                with self.lock:
                    self.step_begins(label, kind, downloads, text.strip(), done(m).strip())
                return
        self.note(text, inside)

    def note(self, text, inside=False):
        if self.unit is not None and self.unit["live"]:
            with self.lock:
                self.unit["notes"].append((text, inside))
        elif not self.opened:
            self.early.append(text)
        else:
            self.lines_out(text.strip(), colour=self.seal)

    # ---------------------------------------------------------------- checks of this computer

    def scanner(self, t, cells=14):
        """A light that runs back and forth along a short track while a step is at work."""
        at = (t * 1.4) % 2
        head = (at if at < 1 else 2 - at) * (cells - 1)
        return "".join(self.ink("━", fg=mix(self.edge, self.flash, max(0.0, 1 - abs(i - head) / 3.2)))
                       for i in range(cells))

    def check_lines(self, row):
        mark = {"ok": self.ink("✓", fg=self.grad(0.75), bold=True), "no": self.ink("✗", fg=self.seal, bold=True),
                "info": self.ink("○", fg=self.grad(0.5)), "stop": self.ink("·", dim=True)}
        head = f" {row['label']:<{LABEL}}  "
        if row["state"] == "run":
            t = time.monotonic() - row["start"]
            return ["  " + self.ink(SPIN[int(t * 14) % len(SPIN)], fg=self.grad(0.8)) + head + self.scanner(t)]
        if row["state"] == "stop":
            return ["  " + mark["stop"] + head + self.ink("stopped", dim=True)]
        room = self.width() - 4 - 2 - LABEL - 2
        if row["state"] == "no":   # what is wrong, in the kit's words, whole
            parts = wrap(row["detail"], room) or [""]
            return ["  " + (mark["no"] + head if n == 0 else " " * (len(head) + 1)) + self.ink(part, fg=self.seal)
                    for n, part in enumerate(parts)]
        detail = row["detail"]
        path = re.search(r"/\S+", detail)
        if len(detail) > room and path and len(path.group()) > len(detail) - room + 8:
            # a long path loses its beginning, not the folder it ends in
            keep = path.group()[len(detail) - room + 1:]
            detail = detail.replace(path.group(), "…" + keep)
        if len(detail) > room:
            detail = detail[:room - 1] + "…"
        return ["  " + mark[row["state"]] + head + self.ink(detail, dim=True)]

    def step(self, label, work):
        """One check of this computer: scanned while it runs, at least long enough to be seen. The
        kit's next line says what it found (checked)."""
        self.begin()
        row = {"label": label, "state": "run", "start": time.monotonic(), "detail": ""}
        self.pending = row
        self.start_painting(lambda tick: self.check_lines(row), rate=24)
        try:
            return work()
        except KeyboardInterrupt:
            row["state"] = "stop"
            self.pending = None
            self.end_painting(lambda tick: self.check_lines(row))
            raise
        finally:
            while row["state"] == "run" and time.monotonic() - row["start"] < 0.45:
                time.sleep(0.02)

    def checked(self, good, detail):
        row = self.pending
        if row is None:
            self.begin()
            row = {"label": "", "state": "run", "start": time.monotonic(), "detail": ""}
            self.start_painting(lambda tick: self.check_lines(row), rate=24)
        row["state"] = "ok" if good else "info" if good is None else "no"
        row["detail"] = detail
        self.pending = None
        self.end_painting(lambda tick: self.check_lines(row))

    def banner(self, text, seconds=0.8):
        """A petrol plate with one line on it, and a light that passes over it once."""
        span = min(self.width() - 4, max(56, len(text) + 8))
        pad = (span - len(text)) // 2

        def frame(t):
            sweep = t / (seconds - 0.1) * 1.4 - 0.2

            def cell(i, ch):
                ground = mix(mix(self.plate, self.stops[1] if not self.light else self.stops[2], i / span * 0.9),
                             (190, 235, 228), max(0.0, 1 - abs(i / span - sweep) / 0.1) * 0.55)
                return self.ink(ch, fg=self.paper, bg=ground, bold=True)

            middle = " " * pad + text + " " * (span - pad - len(text))
            blank = " " * span
            return [""] + ["  " + "".join(cell(i, ch) for i, ch in enumerate(row)) for row in (blank, middle, blank)] + [""]

        self.play(frame, seconds)

    def ready(self, good, line):
        if good:
            self.banner("✓  THIS COMPUTER CAN DO A RUN")
        else:
            self.write("\n")
            self.lines_out(line, colour=self.seal, bold=True)
            self.write("\n")

    # ---------------------------------------------------------------- a run, in its frame

    def start_unit(self, title, facts):
        repo = re.sub(r"^https://github\.com/|\.git$", "", str(facts.get("repo", "")))
        short = re.split(r"[,:]", title)[0].strip()
        self.begin(short if 0 < len(short) <= 30 else None)
        if self.unit is not None:          # a batch of more than one: the one before stays above
            self.write("\n")
        self.unit = {"title": title, "facts": f"{repo} at {str(facts.get('commit', ''))[:12]}",
                     "files": int(facts.get("files") or 0), "docker": bool(facts.get("docker")),
                     "rows": [], "files_at": None, "cut_at": None, "notes": [], "final": None,
                     "live": True, "ripple": None, "marquee": None, "columns": 1}
        self.start_painting(self.frame_lines, rate=15)

    def step_begins(self, label, kind, downloads, sentence, done):
        """A step of the run starts, or (a fact) has just been established; the one before it is done."""
        unit, now = self.unit, time.monotonic()
        self.tick_running(now)
        if label == "Files":
            unit["files_at"] = now
        if label == "Network":
            unit["cut_at"] = now
        unit["rows"].append({"label": label, "kind": kind, "downloads": downloads, "sentence": sentence,
                             "done": done, "start": now, "took": None,
                             "state": "run" if kind == "run" else "ok"})

    def tick_running(self, now):
        for row in self.unit["rows"]:
            if row["state"] == "run":
                row["state"] = "ok"
                if row["took"] is None:
                    row["took"] = now - row["start"]

    def running(self):
        if self.unit is None:
            return None
        return next((row for row in reversed(self.unit["rows"]) if row["state"] == "run"), None)

    def phase(self, cmd):
        """A part of the run inside the container: its lines come here instead of the terminal, and
        are drawn as the lines of a run on this computer are. Returns the exit code."""
        with self.lock:
            if self.unit is not None:
                self.tick_running(time.monotonic())   # what the kit did before this part is done
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                             encoding="utf-8", errors="replace")
        try:
            for line in iter(p.stdout.readline, ""):
                self.heard(line, inside=True)
            code = p.wait()
        except BaseException:
            p.kill()
            p.wait()
            self.settle(stopped=True)
            raise
        with self.lock:
            row = self.running()
            if row is not None and row["took"] is None:   # its time ends with the part; the kit goes on
                row["took"] = time.monotonic() - row["start"]
        return code

    def dash_cell(self, n, columns, t):
        """One of the files the list names: a dot until the kit has found that every one matches."""
        unit = self.unit
        x, y = n % columns, n // columns
        if unit["files_at"] is None:
            return self.ink("·", dim=True)
        lit = unit["files_at"] + 0.08 + (x + 0.6 * y) / max(1, columns) * 0.55   # the sweep reaches it
        if t < lit:
            return self.ink("·", dim=True)
        base = self.grad(0.42 + 0.3 * math.sin(x * 0.42 + y * 0.8 - t * 1.7))   # light moving on water
        age = t - lit
        if age < 0.5:
            base = mix(self.flash, base, age / 0.5)
        if unit["ripple"] is not None:      # the finale: a ring of light widening through the files
            ox, oy, radius = unit["ripple"]
            ring = max(0.0, 1 - abs(math.hypot(x - ox, (y - oy) * 2.0) - radius) / 1.6)
            base = mix(base, self.flash, ring)
        return self.ink("■", fg=base)

    def field(self, t, room):
        """The files the list names, one cell each, and what the kit has found about them."""
        total = self.unit["files"]
        if not total or room < 7:
            return []
        columns = self.unit["columns"] = field_columns(total, room)
        rows = [" ".join(self.dash_cell(n, columns, t) for n in range(start, min(total, start + columns)))
                for start in range(0, total, columns)]
        if self.unit["files_at"] is not None and t >= self.unit["files_at"] + 0.7:
            label = self.ink(f"{total} of {total} files match", fg=self.grad(0.75))
        else:
            label = self.ink(f"{total} file{'s' if total != 1 else ''} on the list", dim=True)
        return rows + [label]

    def big_clock(self, seconds, t, mode):
        """Minutes and seconds in the large digits. A light passes over them now and then while they run."""
        sweep = ((t % 5.0) / 1.1) * 1.4 - 0.2
        colon = sum(len(DIGITS[ch][0]) for ch in f"{max(0, int(seconds)) // 60:02d}")
        beat = max(0.0, seconds) % 1.0   # the colon is lit as each second begins and fades through it

        def body(x, y):
            base = self.grad(0.95 - 0.45 * y / 6)
            if mode == "still":
                return mix(base, self.edge, 0.5)
            if mode == "run":
                if colon <= x < colon + 3:
                    return mix(self.flash, mix(base, self.edge, 0.6), min(1.0, beat * 1.4))
                return mix(base, self.flash, max(0.0, 1 - abs(x / CLOCK_WIDE - sweep) / 0.07) * 0.6)
            return base

        rows = clock_rows(seconds)
        wide = max(CLOCK_WIDE, len(rows[0]))   # a step of 100 minutes or more has a third digit
        return [line + " " * (wide - seen(line)) for line in self.shaded(rows, body)]

    def clock_lines(self, t, inner, compact=False):
        """The running step's time, what the step is, and the list's files beside it."""
        unit = self.unit
        row = self.running()
        if unit["final"]:
            seconds, sentence, caption, mode = unit["final"]
        elif row is not None:
            frozen = row["took"] is not None
            seconds = row["took"] if frozen else t - row["start"]
            sentence, caption, mode = row["sentence"], "this step" if frozen else "this step, so far", \
                "still" if frozen else "run"
        else:   # between steps, or after the last: the step before, its time standing still
            done = [r for r in unit["rows"] if r["kind"] == "run" and r["took"] is not None]
            seconds = done[-1]["took"] if done else 0
            sentence, caption, mode = (done[-1]["sentence"], "this step", "still") if done else ("", "", "still")
        if mode == "done":
            sentence_ink = lambda s: self.ink(s, fg=self.grad(0.8), bold=True)  # noqa: E731
        else:
            sentence_ink = lambda s: self.ink(s, bold=True)  # noqa: E731
        if compact:
            whole = max(0, int(seconds))
            text = f"{whole // 60:02d}:{whole % 60:02d}  "
            room = inner - len(text)
            return [self.ink(text, bold=True) + sentence_ink(sentence[:room])
                    + self.ink(f"  {caption}"[:max(0, room - len(sentence))], dim=True)]
        digits = self.big_clock(seconds, t, mode)
        wide = seen(digits[0])
        side = inner - wide - 4
        if side >= 24:
            words = [sentence_ink(part) for part in wrap(sentence, side)] \
                + [self.ink(part, dim=True) for part in wrap(caption, side)]
            files = self.field(t, side)
            right = words + ([""] if words and files else []) + files
            rows = max(len(digits), len(right))
            return [(digits[n] if n < len(digits) else " " * wide) + "    " + (right[n] if n < len(right) else "")
                    for n in range(rows)]
        files = self.field(t, inner)
        words = [sentence_ink(part) for part in wrap(sentence, inner)] + [self.ink(part, dim=True) for part in wrap(caption, inner)]
        return digits + words + ([""] + files if files else [])

    def net_line(self, t, inner):
        """The container's way to the internet: marks come down it while a step downloads; it breaks
        when the kit cuts the network."""
        unit = self.unit
        left = self.ink("container ", dim=True) + self.ink("◀", fg=self.grad(0.7))
        right = self.ink("●", fg=self.grad(0.45)) + self.ink(" internet", dim=True)
        if unit["cut_at"] is not None:
            said = "   " + self.ink("network cut:", bold=True) + " the build runs offline"
            track = max(9, min(30, inner - seen(left) - seen(right) - seen(said)))
            age = t - unit["cut_at"]
            half = (track - 5) // 2
            gap = "  " + self.ink("✕", fg=mix(self.flash, self.grad(0.8), min(1.0, age / 0.6)), bold=True) + "  "
            line = self.ink("─" * half, fg=self.edge) + gap + self.ink("─" * (track - 5 - half), fg=self.edge)
            return left + line + right + said
        row = self.running()
        coming = row is not None and row["downloads"] and row["took"] is None
        said = "   " + self.ink("network on", dim=True) + (self.ink("  ·  downloading", dim=True) if coming else "")
        track = max(9, min(30, inner - seen(left) - seen(right) - len("   network on  ·  downloading")))
        cells = []
        for i in range(track):
            if coming:
                # marks travel from the internet (right) to the container (left), a tail of light behind each
                at = (i + (t - row["start"]) * 14) % 9
                if at < 1:
                    cells.append(self.ink("◆", fg=self.flash, bold=True))
                    continue
                if at < 4.5:
                    cells.append(self.ink("━", fg=mix(self.flash, self.edge, (at - 1) / 3.5)))
                    continue
            cells.append(self.ink("─", fg=self.edge))
        return left + "".join(cells) + right + said

    def row_line(self, row, t, inner):
        head = f" {row['label']:<{LABEL}}  "
        if row["state"] == "run":
            spin = SPIN[int((t - row["start"]) * 14) % len(SPIN)]
            return self.ink(spin, fg=self.grad(0.8)) + head + self.scanner(t - row["start"])
        if row["state"] == "stop":
            return self.ink("·", dim=True) + head + self.ink("stopped", dim=True)
        took = took_text(row["took"]) if row["kind"] == "run" else ""
        room = inner - 2 - LABEL - 2 - 13
        if row["state"] == "no":
            detail = row.get("why") or row["sentence"]
            detail = detail if len(detail) <= room else detail[:room - 1] + "…"
            return (self.ink("✗", fg=self.seal, bold=True) + head + self.ink(detail, fg=self.seal)
                    + " " * (room - len(detail)) + self.ink(f"{took:>13}", dim=True))
        detail = row["done"] if len(row["done"]) <= room else row["done"][:room - 1] + "…"
        return (self.ink("✓", fg=self.grad(0.75), bold=True) + head + self.ink(detail, dim=True)
                + " " * (room - len(detail)) + self.ink(f"{took:>13}", dim=True))

    def frame_lines(self, tick):
        """The run inside its frame. `tick` below zero asks for the picture that stays."""
        unit, t = self.unit, time.monotonic()
        size = shutil.get_terminal_size((80, 24))
        width = max(40, min(size.columns - 2, 100))
        inner = width - 4
        title = f" {unit['title']} "
        if len(title) > width - 6:
            title = title[:width - 8] + "… "
        facts = f" {unit['facts']} "
        in_edge = len(title) + len(facts) + 6 <= width
        parts = []
        if not in_edge:
            parts.append(("facts", self.ink(unit["facts"], dim=True)))
        parts.append(("blank", ""))
        parts += [("row", self.row_line(row, t, inner)) for row in unit["rows"]]
        parts.append(("blank", ""))
        clock = self.clock_lines(t, inner)
        parts += [("clock", line) for line in clock]
        if unit["docker"] and unit["rows"]:   # once the container is there
            parts += [("blank", ""), ("net", self.net_line(t, inner))]
        if tick >= 0 and unit["notes"]:
            parts.append(("blank", ""))
            notes = [part for text, _ in unit["notes"][-2:] for part in wrap(text.strip(), inner)][-2:]
            parts += [("note", self.ink(part, fg=self.seal)) for part in notes]
        parts.append(("blank", ""))

        # Taller than the screen: fewer blank lines, then the time on one line, then the last rows only.
        room = size.lines - 3
        while len(parts) > room and any(kind == "blank" for kind, _ in parts):
            parts.remove(next(p for p in parts if p[0] == "blank"))
        if len(parts) > room:
            at = next(n for n, p in enumerate(parts) if p[0] == "clock")
            parts = [p for p in parts if p[0] != "clock"]
            parts[at:at] = [("clock", line) for line in self.clock_lines(t, inner, compact=True)]
        while len(parts) > room and any(kind == "row" for kind, _ in parts):
            parts.remove(next(p for p in parts if p[0] == "row"))
        parts = parts[-room:] if room > 0 else []

        # The frame: the proof's title in its top edge; at the end of a run that passed a light runs once around it.
        rows = len(parts)
        around = 2 * width + 2 * rows

        def edge(index, ch):
            if unit["marquee"] is None:
                return self.ink(ch, fg=self.edge)
            behind = (unit["marquee"] - index) % around
            return self.ink(ch, fg=mix(self.flash, self.edge, behind / 14) if behind < 14 else self.edge)

        shown_facts = facts if in_edge else ""
        fill = width - 2 - 1 - len(title) - len(shown_facts) - 1
        top = (edge(0, "╭") + edge(1, "─") + self.ink(title, bold=True)
               + "".join(edge(2 + len(title) + i, "─") for i in range(fill)) + self.ink(shown_facts, dim=True)
               + edge(width - 2, "─") + edge(width - 1, "╮"))
        hint = " Ctrl-C stops; the same command goes on " if tick >= 0 else ""
        low_fill = width - 2 - len(hint) - 1
        low = (edge(2 * width + rows - 1, "╰")
               + "".join(edge(2 * width + rows - 2 - i, "─") for i in range(low_fill))
               + self.ink(hint, dim=True) + edge(width + rows, "─") + edge(width + rows - 1, "╯"))
        lines = [" " + top]
        for n, (_, text) in enumerate(parts):
            lines.append(" " + edge(around - 1 - n, "│") + " " + text + " " * max(0, inner - seen(text)) + " "
                         + edge(width + n, "│"))
        lines.append(" " + low)
        return lines

    def settle(self, outcome=None, stopped=False, record=None, line=""):
        """The run is over: the picture that stays. A run that passed ends with a light round the frame."""
        unit = self.unit
        if unit is None or not unit["live"]:
            return
        self.halt()
        now = time.monotonic()
        with self.lock:
            unit["live"] = False
            row = self.running()
            record = record or {}
            if outcome == "passed":
                self.tick_running(now)
                for r in unit["rows"]:   # the kit's own measure of the build and of the axioms check
                    if r["label"] == "Build" and "buildSeconds" in record:
                        r["took"] = record["buildSeconds"]
                    if r["label"] == "Axioms" and "checkSeconds" in record:
                        r["took"] = record["checkSeconds"]
                total = record.get("buildSeconds", 0) + record.get("checkSeconds", 0)
                unit["final"] = (total, line.strip(), "Lean's build and the axioms check", "done")
            elif row is not None:
                row["took"] = row["took"] if row["took"] is not None else now - row["start"]
                if stopped:
                    row["state"] = "stop"
                else:
                    row["state"] = "no"
                    if outcome == "failed" and record.get("problems"):
                        row["why"] = "; ".join(record["problems"])
                if row["label"] == "Build" and "buildSeconds" in record:
                    row["took"] = record["buildSeconds"]
        if outcome == "passed" and self.region:
            total, columns = unit["files"], max(1, unit["columns"])
            reach = math.hypot(columns, math.ceil(total / columns) * 2.0) + 2
            start = time.monotonic()
            while total and time.monotonic() - start < 0.6:   # a ring of light widens through the files
                unit["ripple"] = (0, 0, (time.monotonic() - start) / 0.6 * reach)
                with self.lock:
                    self.repaint(self.frame_lines(-1))
                time.sleep(1 / 30)
            unit["ripple"] = None
            around = 2 * max(40, min(shutil.get_terminal_size((80, 24)).columns - 2, 100)) + 2 * (self.region - 2)
            start = time.monotonic()
            while time.monotonic() - start < 0.8:    # and a light runs once around the frame
                unit["marquee"] = int((time.monotonic() - start) / 0.8 * (around + 14))
                with self.lock:
                    self.repaint(self.frame_lines(-1))
                time.sleep(1 / 30)
            unit["marquee"] = None
        self.end_painting(self.frame_lines)
        notes = [text for text, _ in unit["notes"]]
        if notes:
            self.write("\n")
            for text in notes:
                lead = len(text) - len(text.lstrip())
                for part in wrap(text.strip(), self.width() - 4 - lead) or [""]:
                    self.write("  " + " " * lead + self.ink(part, fg=self.seal) + "\n")

    def outcome(self, line, passed, record):
        if passed:
            self.settle("passed", record=record, line=line)
            self.banner("✓  PASSED: LEAN ACCEPTED A PROOF OF THE STATED SENTENCE", 0.9)
        else:
            self.settle("failed", record=record, line=line)
            self.write("\n")
            self.lines_out(line.strip(), colour=self.seal, bold=True)

    def axioms_line(self, line, name):
        text = line.strip()
        rest = text[len(name):] if name and text.startswith(name) else ""
        said = rest.replace(" rests on: ", "", 1) if rest.startswith(" rests on: ") else None
        if said is None:
            self.lines_out(text)
            return
        room = self.width() - 4
        head = name + " rests on: "
        if len(head) + len(said) <= room:
            self.write("  " + self.ink(name, bold=True) + self.ink(" rests on: ", dim=True) + said + "\n")
        else:
            self.write("  " + self.ink(name, bold=True) + self.ink(" rests on:", dim=True) + "\n")
            for part in wrap(said, room - 4):
                self.write("      " + part + "\n")

    # ---------------------------------------------------------------- the end of a run

    def flight(self, label, seconds=0.55, track=22):
        """A mark flies from this computer to Papex: something was just sent, and Papex took it."""
        def frame(t):
            head = t / seconds * track
            line = "".join(self.ink("◆", fg=self.flash, bold=True) if abs(i - head) < 0.6
                           else self.ink("━", fg=mix(self.flash, self.edge, (head - i) / 5)) if 0 <= head - i < 5
                           else self.ink("─", fg=self.edge) for i in range(track))
            return ["  " + self.ink(SPIN[int(t * 14) % len(SPIN)], fg=self.grad(0.8)) + f" {label:<{LABEL}}  "
                    + self.ink("this computer ", dim=True) + self.ink("●", fg=self.grad(0.7)) + line
                    + self.ink("▶ ", fg=self.grad(0.7)) + self.ink("Papex", bold=True)]
        self.play(frame, seconds)
        with self.lock:
            self.write("\x1b[1F\x1b[2K")   # the flight's line is replaced by what it led to

    def sent(self, line):
        """Papex answered that it has the result."""
        self.write("\n")
        self.flight("Result")
        self.write("  " + self.ink("✓", fg=self.grad(0.75), bold=True) + f" {'Result':<{LABEL}}  "
                   + self.ink("with Papex", dim=True) + "\n")
        words = line.strip()
        words = words[len("Sent to Papex."):].strip() if words.startswith("Sent to Papex.") else words
        self.after = clauses(words, min(60, self.width() - 10))

    def box(self, title, lines):
        """What to do next, in a frame whose edge carries the gradient."""
        inner = max(len(line) for line in lines + [title]) + 2
        edge = lambda text, at: self.ink(text, fg=self.grad(0.25 + 0.6 * at))  # noqa: E731
        top = "╭─ " + title + " " + "─" * (inner - len(title) - 3) + "╮"
        self.write("  " + "".join(self.ink(ch, bold=True) if 3 <= i < 3 + len(title) else edge(ch, i / len(top))
                                  for i, ch in enumerate(top)) + "\n")
        for line in lines:
            link = line.startswith("http") or line.startswith("/")
            self.write("  " + edge("│", 0) + " " + (self.ink(line, fg=self.grad(0.85), bold=True) if link else line)
                       + " " * (inner - 1 - len(line)) + edge("│", 1) + "\n")
        low = "╰" + "─" * inner + "╯"
        self.write("  " + "".join(edge(ch, i / len(low)) for i, ch in enumerate(low)) + "\n\n")

    def place(self, name, path, note=None):
        """A file or folder the kit names, and (dim, under it) what to do with it."""
        if 15 + len(path) <= self.width():
            self.write("  " + self.ink(f"{name:<13}", dim=True) + path + "\n")
        else:   # no room beside the name: the path on its own line, whole, so that it can be copied
            self.write("  " + self.ink(name, dim=True) + "\n  " + path + "\n")
        if note:
            for part in wrap(note, self.width() - 17):
                self.write(" " * 15 + self.ink(part, dim=True) + "\n")

    def finish(self, work_root):
        if self.after:
            self.write("\n")
            self.box("Next", self.after)
        if self.result_path:
            self.place("Result file", self.result_path)
        self.place("Work folder", work_root, "Delete it with: python3 rerun.py --clean")
        self.write("\n")

    # ---------------------------------------------------------------- whatever ends it

    def fail(self, message):
        """The kit's last word (why it stops), wrapped to the terminal, after the picture is settled."""
        for said in self.take_later():
            self.hear(*said)
        calm = message.lstrip().startswith("Stopped")
        if self.pending is not None:
            row, self.pending = self.pending, None
            row["state"] = "stop" if calm else "no"
            self.end_painting(lambda tick: self.check_lines(row))
        self.settle(stopped=calm)
        self.close()
        self.write("\r\x1b[2K")   # the terminal's own "^C", where the cursor stood
        if not self.opened:
            self.show_said()
        for line in message.split("\n"):
            lead = len(line) - len(line.lstrip())
            for part in wrap(line.strip(), self.width() - 4 - lead) if line.strip() else [""]:
                text = " " * lead + part
                self.write("  " + (text if calm or lead else self.ink(text, fg=self.seal)) + "\n")
        return True

    def close(self):
        """Whatever ended the run: stop painting, and give the terminal its cursor back."""
        self.halt()
        if self.unit is not None:
            self.unit["live"] = False
        self.cursor(True)
