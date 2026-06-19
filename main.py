import sys
import queue
import threading
import logging
import time

import requests

from queryer import Queryer
from grabber import Grabber


SPEEDS = {"极速 (0.25s)": 1, "中速 (5s)": 2, "捡漏 (100s)": 3}
DEFAULT_KW = ["软陶", "宇宙的奥秘", "民间剪纸", "三维建模", "AIGC 艺术鉴赏", "象棋"]


# ── shared ─────────────────────────────────────────────────
# 日志桥接和抢课核心逻辑，Flet / Textual 共用

class _QueueHandler(logging.Handler):
    def __init__(self, q):
        super().__init__()
        self.q = q

    def emit(self, r):
        self.q.put(self.format(r))


def _setup_logging(q):
    h = _QueueHandler(q)
    h.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%H:%M:%S"))
    logging.root.setLevel(logging.INFO)
    logging.root.handlers = [h]


def _check_cookie(cookie):
    try:
        q = Queryer()
        q.fetch_humanities(cookie)
        return len(q.courses) > 0
    except requests.RequestException:
        return False


def _run_grab(cookie, keywords, mode, limit, stop):
    try:
        q = Queryer()
        g = Grabber()
        for label, fn in [("人文", q.fetch_humanities),
                          ("自然", q.fetch_sciences),
                          ("班级", q.fetch_class_courses)]:
            if stop.is_set():
                return
            logging.info(f"查询{label}...")
            fn(cookie)

        logging.info(f"共查到 {len(q.courses)} 门课")
        q.filter_by_keywords(keywords)
        if not q.matched_courses:
            return logging.error("无匹配课程")

        logging.info(f"匹配 {len(q.matched_courses)} 门，开始抢课")
        ts = []
        for i, item in enumerate(q.matched_courses):
            if stop.is_set():
                return
            t = threading.Thread(
                target=g.grab_loop,
                args=(cookie, item, i + 1, mode),
                kwargs={"stop_event": stop, "max_attempts": limit},
                daemon=True,
            )
            ts.append(t)
            t.start()
        for t in ts:
            t.join()
    except Exception:
        logging.exception("异常")


# ── GUI: Flet ─────────────────────────────────────────────

try:
    import flet as ft
    HAS_FLET = True
except ImportError:
    HAS_FLET = False


def flet_main(page: ft.Page):
    page.title = "CQUPT 抢课助手"
    page.window.width = 640
    page.window.height = 620
    page.theme_mode = ft.ThemeMode.SYSTEM
    page.padding = 24

    log_queue = queue.Queue()
    _setup_logging(log_queue)
    stop = threading.Event()
    running = False

    # ── widgets ──

    page.add(ft.Text("CQUPT 抢课助手", size=22, weight=ft.FontWeight.BOLD))

    page.add(ft.Divider(height=12))

    cookie = ft.TextField(
        label="Cookie",
        hint_text="PHPSESSID=...",
        text_style=ft.TextStyle(size=12, font_family="monospace"),
        password=True,
        can_reveal_password=True,
    )
    page.add(cookie)

    cookie_status = ft.Text(size=13)
    check_btn = ft.Button("检测 Cookie", icon=ft.Icons.VERIFIED_USER)
    page.add(ft.Row([check_btn, cookie_status], spacing=12))

    page.add(ft.Divider(height=12))

    kw = ft.TextField(
        label="课程关键词（一行一个）",
        value="\n".join(DEFAULT_KW),
        multiline=True,
        min_lines=4,
        max_lines=6,
        text_style=ft.TextStyle(size=13, font_family="monospace"),
    )
    page.add(kw)

    page.add(ft.Divider(height=12))

    speed = ft.Dropdown(
        label="抢课速度",
        options=[ft.dropdown.Option(k) for k in SPEEDS],
        value=list(SPEEDS)[0],
        width=200,
    )
    max_retry = ft.TextField(label="最大次数 (0=无限)", value="0", width=140)
    page.add(ft.Row([speed, max_retry], spacing=16))

    start_btn = ft.Button("开始抢课", icon=ft.Icons.PLAY_ARROW)
    stop_btn = ft.OutlinedButton("停止", icon=ft.Icons.STOP, disabled=True)
    page.add(ft.Row([start_btn, stop_btn], spacing=12))

    page.add(ft.Divider(height=12))
    page.add(ft.Text("运行日志", size=14, weight=ft.FontWeight.BOLD))

    log_view = ft.ListView(expand=True, spacing=2, auto_scroll=True)
    page.add(log_view)

    # ── helpers ──

    def _add_log(msg, color=None):
        c = color or (ft.Colors.GREY_400 if page.theme_mode == ft.ThemeMode.DARK else ft.Colors.GREY_600)
        log_view.controls.append(ft.Text(msg, size=12, color=c, font_family="monospace"))

    def _drain():
        changed = False
        while True:
            try:
                msg = log_queue.get_nowait()
                if "抢课成功" in msg:
                    _add_log(msg, ft.Colors.GREEN_ACCENT)
                elif "ERROR" in msg or "异常" in msg or "失败" in msg or "无效" in msg:
                    _add_log(msg, ft.Colors.RED_ACCENT)
                else:
                    _add_log(msg)
                changed = True
            except queue.Empty:
                break
        return changed

    def _poll_forever():
        # Flet 没有内置定时器 API，用独立线程持续拉取日志队列并刷新 UI
        while running or not log_queue.empty():
            if _drain():
                page.update()
            time.sleep(0.3)

    # ── callbacks ──

    def on_check(e):
        c = cookie.value.strip()
        if not c:
            cookie_status.value = "请先填写 Cookie"
            cookie_status.color = ft.Colors.RED
            page.update()
            return
        cookie_status.value = "检测中..."
        cookie_status.color = ft.Colors.ORANGE
        check_btn.disabled = True
        page.update()

        def task():
            ok = _check_cookie(c)
            cookie_status.value = "✓ Cookie 有效" if ok else "✗ Cookie 无效，请重新获取"
            cookie_status.color = ft.Colors.GREEN if ok else ft.Colors.RED
            check_btn.disabled = False
            page.update()

        threading.Thread(target=task, daemon=True).start()

    def on_start(e):
        nonlocal running
        c = cookie.value.strip()
        if not c:
            cookie_status.value = "请填写 Cookie"
            page.update()
            return
        keys = [x.strip() for x in kw.value.splitlines() if x.strip()]
        if not keys:
            return
        mode_val = SPEEDS[speed.value]
        try:
            limit = int(max_retry.value)
        except ValueError:
            limit = 0

        stop.clear()
        running = True
        start_btn.disabled = True
        stop_btn.disabled = False
        page.update()

        def grab_task():
            nonlocal running
            _run_grab(c, keys, mode_val, limit, stop)
            time.sleep(0.3)
            _drain()
            running = False
            start_btn.disabled = False
            stop_btn.disabled = True
            page.update()

        threading.Thread(target=grab_task, daemon=True).start()
        threading.Thread(target=_poll_forever, daemon=True).start()

    def on_stop(e):
        nonlocal running
        stop.set()
        logging.info("用户请求停止")
        running = False
        start_btn.disabled = False
        stop_btn.disabled = True
        _drain()
        page.update()

    check_btn.on_click = on_check
    start_btn.on_click = on_start
    stop_btn.on_click = on_stop
    page.update()


# ── TUI: Textual ──────────────────────────────────────────

def tui_main():
    from textual.app import App, ComposeResult
    from textual.containers import Horizontal, Vertical
    from textual.widgets import (
        Header, Footer, Input, TextArea, Select, Button, RichLog, Label,
    )

    log_queue = queue.Queue()
    _setup_logging(log_queue)
    stop = threading.Event()

    class GrabTui(App):
        CSS = """
        #main {
            padding: 0 2;
            height: 1fr;
            overflow-y: auto;
        }

        #cookie { margin-top: 1; }
        #cookie-status { margin-left: 1; }

        #kw {
            height: 5;
            margin-top: 1;
            border: solid $surface;
        }

        #settings {
            margin-top: 1;
            height: 3;
            align: left middle;
        }
        #settings Select { width: 24; }
        #settings Input { width: 18; margin-left: 1; }

        #actions {
            margin-top: 1;
            height: 3;
            align: left middle;
        }
        #actions Button { margin-right: 1; }

        #log {
            height: 1fr;
            margin-top: 1;
            border: solid $surface;
            background: $surface;
        }
        """

        def compose(self) -> ComposeResult:
            yield Header()
            with Vertical(id="main"):
                yield Label("Cookie")
                yield Input(id="cookie", placeholder="PHPSESSID=...")
                with Horizontal():
                    yield Button("检测 Cookie", id="check")
                    yield Label("", id="cookie-status")

                yield Label("课程关键词（一行一个）")
                yield TextArea("\n".join(DEFAULT_KW), id="kw")

                with Horizontal(id="settings"):
                    yield Select([(k, k) for k in SPEEDS], id="speed", value=list(SPEEDS)[0])
                    yield Input(placeholder="最大次数 (0=无限)", id="max_retry", value="0")

                with Horizontal(id="actions"):
                    yield Button("开始抢课", id="start", variant="primary")
                    yield Button("停止", id="stop", disabled=True)

                yield RichLog(id="log", wrap=True, highlight=True, markup=True)
            yield Footer()

        def on_mount(self):
            self._stop = stop
            self._lq = log_queue
            self._drain()

        def _drain(self):
            log = self.query_one("#log", RichLog)
            while True:
                try:
                    msg = self._lq.get_nowait()
                    log.write(msg)
                except queue.Empty:
                    break
            self.set_timer(0.3, self._drain)

        def on_button_pressed(self, event: Button.Pressed):
            getattr(self, f"_on_{event.button.id}")()

        def _on_check(self):
            c = self.query_one("#cookie", Input).value.strip()
            status = self.query_one("#cookie-status", Label)
            if not c:
                status.update("请先填写 Cookie")
                return
            status.update("检测中...")
            self.query_one("#check", Button).disabled = True

            def task():
                ok = _check_cookie(c)
                def cb():
                    s = self.query_one("#cookie-status", Label)
                    s.update("Cookie 有效" if ok else "Cookie 无效，请重新获取")
                    self.query_one("#check", Button).disabled = False
                self.call_from_thread(cb)
            self.run_worker(task, thread=True)

        def _on_start(self):
            c = self.query_one("#cookie", Input).value.strip()
            if not c:
                return
            keys = [x.strip() for x in self.query_one("#kw", TextArea).text.splitlines() if x.strip()]
            if not keys:
                return
            mode = SPEEDS[self.query_one("#speed", Select).value]
            try:
                limit = int(self.query_one("#max_retry", Input).value)
            except ValueError:
                limit = 0

            stop.clear()
            self.query_one("#start", Button).disabled = True
            self.query_one("#stop", Button).disabled = False

            def task():
                _run_grab(c, keys, mode, limit, stop)
                self.call_from_thread(self._done)
            self.run_worker(task, thread=True)

        def _on_stop(self):
            stop.set()
            logging.info("用户请求停止")
            self.query_one("#start", Button).disabled = False
            self.query_one("#stop", Button).disabled = True

        def _done(self):
            self.query_one("#start", Button).disabled = False
            self.query_one("#stop", Button).disabled = True

    GrabTui().run()


# ── entry ────────────────────────────────────────────────

if __name__ == "__main__":
    if "--tui" in sys.argv:
        tui_main()
    else:
        if not HAS_FLET:
            print("flet 未安装，请运行: uv sync")
            sys.exit(1)
        ft.run(flet_main)
