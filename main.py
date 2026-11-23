import flet as ft
import flet_audio as fta
import json
import random
import time
import math
import asyncio
import wave
import array
import unicodedata
import functools
from pathlib import Path


# ============================================================
#  CONFIGURACIÓN GLOBAL
# ============================================================
APP_DIR = Path(__file__).parent if "__file__" in globals() else Path.cwd()
ASSETS_DIR = APP_DIR / "assets"
ASSETS_DIR.mkdir(exist_ok=True)
PROGRESS_FILE = APP_DIR / "adviento_progreso.json"

# Paleta cálida navideña
COLOR_BG          = "#2C1810"
COLOR_BG_LIGHT    = "#5D4037"
COLOR_RED         = "#D32F2F"
COLOR_RED_DARK    = "#B71C1C"
COLOR_GREEN       = "#43A047"
COLOR_GREEN_DARK  = "#1B5E20"
COLOR_GOLD        = "#FFC107"
COLOR_GOLD_LIGHT  = "#FFE082"
COLOR_SNOW        = "#FAFAFA"
COLOR_BLUE_SNOW   = "#BBDEFB"
COLOR_CHIMNEY     = "#795548"
COLOR_ROOF        = "#3E2723"
COLOR_BLUE        = "#1976D2"
COLOR_PURPLE      = "#7B1FA2"

MUSIC_STATE = {"on": False}
AUDIO_REFS = {}
PAGE_REF = {}

# Tareas async activas para poder cancelarlas al cambiar de pantalla
SESSION = {"id": 0, "tasks": []}
ACTIVE_TASKS = {"list": []}
THREAD_STOP = {"flag": False}


# ============================================================
#  AUDIO (sin numpy, usando array + wave de la librería estándar)
# ============================================================
def _tone(freq, dur, vol=0.3, decay=6.0, sr=22050):
    """Tono senoidal con envolvente exponencial."""
    n = int(sr * dur)
    out = array.array('h')
    for i in range(n):
        t = i / sr
        env = math.exp(-t * decay)
        s = vol * env * math.sin(2 * math.pi * freq * t)
        out.append(max(-32767, min(32767, int(s * 32767))))
    return out


def _chirp(f0, f1, dur, vol=0.3, sr=22050):
    """Barrido lineal de frecuencia f0 -> f1."""
    n = int(sr * dur)
    out = array.array('h')
    phase = 0.0
    for i in range(n):
        t = i / sr
        freq = f0 + (f1 - f0) * t / dur
        phase += 2 * math.pi * freq / sr
        env = math.exp(-t * 4)
        s = vol * env * math.sin(phase)
        out.append(max(-32767, min(32767, int(s * 32767))))
    return out


def _concat(parts):
    out = array.array('h')
    for p in parts:
        out.extend(p)
    return out


def _save_wav(path, mono, sr=22050):
    """Guarda samples mono como WAV estéreo (mismo audio en ambos canales)."""
    stereo = array.array('h')
    for s in mono:
        stereo.append(s)
        stereo.append(s)
    with wave.open(str(path), "w") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(stereo.tobytes())


def _jingle_bells(sr=22050):
    """Melodía de Jingle Bells con armónicos suaves."""
    seq = [
        (329.63, 0.25), (329.63, 0.25), (329.63, 0.5),
        (329.63, 0.25), (329.63, 0.25), (329.63, 0.5),
        (329.63, 0.25), (392.00, 0.25), (261.63, 0.35),
        (293.66, 0.35), (329.63, 1.0),
        (0, 0.3),
        (349.23, 0.25), (349.23, 0.25), (349.23, 0.3), (349.23, 0.25),
        (349.23, 0.25), (329.63, 0.25), (329.63, 0.25), (329.63, 0.15),
        (329.63, 0.15), (293.66, 0.25), (293.66, 0.25), (329.63, 0.25),
        (293.66, 0.5), (392.00, 0.5),
    ]
    parts = []
    for f, d in seq:
        n = max(1, int(sr * d))
        if f == 0:
            parts.append(array.array('h', [0] * n))
        else:
            seg = array.array('h')
            for i in range(n):
                t = i / sr
                env = (1 - math.exp(-t * 30)) * math.exp(-t * 2.2)
                s = 0.22 * env * math.sin(2 * math.pi * f * t)
                s += 0.05 * env * math.sin(2 * math.pi * 3 * f * t)
                seg.append(max(-32767, min(32767, int(s * 32767))))
            parts.append(seg)
    full = _concat(parts)
    return _concat([full, full])  # repetir 2 veces


def ensure_assets():
    """Genera los audios si todavía no existen."""
    fx_files = {
        "fx_correct":  _chirp(523, 1046, 0.25, vol=0.35),
        "fx_error":    _tone(140, 0.30, vol=0.35, decay=4),
        "fx_tick":     _tone(1200, 0.04, vol=0.25, decay=40),
        "fx_drop":     _chirp(800, 200, 0.20, vol=0.30),
        "fx_click":    _tone(900, 0.04, vol=0.20, decay=40),
        "fx_shuffle":  _concat([
            _tone(400, 0.05, vol=0.20, decay=20),
            _tone(520, 0.05, vol=0.20, decay=20),
            _tone(640, 0.05, vol=0.20, decay=20),
            _tone(760, 0.05, vol=0.20, decay=20),
        ]),
        "fx_win": _concat([
            _tone(523, 0.15, vol=0.30, decay=4),
            _tone(659, 0.15, vol=0.30, decay=4),
            _tone(784, 0.15, vol=0.30, decay=4),
            _tone(1046, 0.40, vol=0.35, decay=2),
        ]),
        "fx_lose": _concat([
            _tone(300, 0.25, vol=0.30, decay=3),
            _tone(200, 0.40, vol=0.30, decay=2),
        ]),
    }
    for name, data in fx_files.items():
        p = ASSETS_DIR / f"{name}.wav"
        if not p.exists():
            _save_wav(p, data)
    music = ASSETS_DIR / "music_jingle.wav"
    if not music.exists():
        _save_wav(music, _jingle_bells())


# ============================================================
#  PROGRESO (JSON local)
# ============================================================
def load_progress():
    if PROGRESS_FILE.exists():
        try:
            return json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"completed": [], "scores": {}}


def save_progress(data):
    try:
        PROGRESS_FILE.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except Exception:
        pass


def mark_day_complete(day, score):
    data = load_progress()
    if day not in data["completed"]:
        data["completed"].append(day)
    cur = data["scores"].get(str(day), 0)
    if score > cur:
        data["scores"][str(day)] = score
    save_progress(data)


# ============================================================
#  AUDIO HELPERS
#  En Flet 1.x Audio debe añadirse a page.overlay para vincularse
#  a la página y poder reproducirse.
# ============================================================
def init_audio(page):
    """Inicializa audio y monta los controles en page.overlay."""
    PAGE_REF["page"] = page
    fx_names = ["correct", "error", "tick", "drop", "click", "shuffle", "win", "lose"]
    try:
        for n in fx_names:
            p = ASSETS_DIR / f"fx_{n}.wav"
            a = fta.Audio(src=str(p), autoplay=False)
            AUDIO_REFS[n] = a
            page.overlay.append(a)
        music_path = ASSETS_DIR / "music_jingle.wav"
        music = fta.Audio(
            src=str(music_path),
            autoplay=False,
            release_mode=fta.ReleaseMode.LOOP,
        )
        AUDIO_REFS["music"] = music
        page.overlay.append(music)
    except Exception as exc:
        print(f"Audio desactivado: {exc}")
        AUDIO_REFS.clear()


def _schedule_audio(awaitable):
    """Programa operaciones async de audio en el loop correspondiente."""
    if not awaitable:
        return
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(awaitable)
        return
    except RuntimeError:
        pass

    page = PAGE_REF.get("page")
    if page:
        try:
            loop = page.session.connection.loop
            if loop and loop.is_running():
                asyncio.run_coroutine_threadsafe(awaitable, loop)
                return
        except Exception:
            pass

    close = getattr(awaitable, "close", None)
    if close:
        close()


def play_fx(name):
    audio = AUDIO_REFS.get(name)
    if audio:
        try:
            _schedule_audio(audio.play())
        except Exception:
            pass


def set_music(on):
    MUSIC_STATE["on"] = on
    music = AUDIO_REFS.get("music")
    if not music:
        return
    try:
        operation = music.play() if on else music.pause()
        _schedule_audio(operation)
    except Exception:
        pass


# ============================================================
#  NAVEGACIÓN Y TAREAS ASYNC
# ============================================================
def safe_update(*controls):
    """Actualiza controles de forma segura, ignorando errores si no están montados."""
    for c in controls:
        if c:
            try:
                c.update()
            except Exception:
                pass


def safe_focus(ctrl):
    """Llama a focus() y programa su corrutina si es asíncrona."""
    if ctrl and hasattr(ctrl, "focus"):
        try:
            res = ctrl.focus()
            if asyncio.iscoroutine(res):
                _schedule_audio(res)
        except Exception:
            pass


def start_task(page, handler):
    """Inicia una tarea asíncrona ligada a la sesión de pantalla activa."""
    my_session = SESSION["id"]

    @functools.wraps(handler)
    async def wrapped_task():
        current = asyncio.current_task()
        if current:
            SESSION["tasks"].append(current)
        try:
            if SESSION["id"] == my_session and not THREAD_STOP["flag"]:
                await handler()
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            print(f"Error en tarea async ({getattr(handler, '__name__', 'anon')}): {exc}")
        finally:
            if current and current in SESSION["tasks"]:
                SESSION["tasks"].remove(current)

    THREAD_STOP["flag"] = False
    task = page.run_task(wrapped_task)
    ACTIVE_TASKS["list"].append(task)
    return task


def stop_all_tasks(page=None):
    """Detiene las tareas de la pantalla anterior antes de navegar."""
    SESSION["id"] += 1
    THREAD_STOP["flag"] = True

    for task in list(SESSION["tasks"]):
        try:
            task.cancel()
        except Exception:
            pass
    SESSION["tasks"].clear()

    for task in list(ACTIVE_TASKS["list"]):
        try:
            task.cancel()
        except Exception:
            pass
    ACTIVE_TASKS["list"].clear()

    if page:
        try:
            while page.pop_dialog():
                pass
        except Exception:
            pass


def go_to(page, builder):
    stop_all_tasks(page)
    page.controls.clear()
    page.add(builder(page))
    page.update()


def make_back_button(page):
    return ft.Button(
        "← Volver al calendario",
        on_click=lambda e: go_to(page, build_home),
        bgcolor=COLOR_BG_LIGHT, color="white",
        icon=ft.Icons.HOME,
    )


# ============================================================
#  PANTALLA INICIO · Árbol navideño + 5 regalos
# ============================================================
def build_home(page):
    progress = load_progress()
    completed = set(progress.get("completed", []))
    scores = progress.get("scores", {})

    title = ft.Text(
        "🎄 Calendario de Adviento 🎄",
        size=42, weight=ft.FontWeight.BOLD,
        color=COLOR_GOLD, text_align=ft.TextAlign.CENTER,
    )
    subtitle = ft.Text(
        "Toca un regalo para abrir el día",
        size=18, color=COLOR_SNOW, text_align=ft.TextAlign.CENTER,
    )

    star = ft.Text("⭐", size=48, text_align=ft.TextAlign.CENTER)

    layers = []
    for i, (w, col) in enumerate([(200, COLOR_GREEN), (160, "#2E7D32"), (120, COLOR_GREEN_DARK)]):
        layers.append(ft.Container(
            width=w, height=90, bgcolor=col,
            border_radius=ft.BorderRadius.only(top_left=100, top_right=100),
            margin=ft.Margin.only(top=-45 if i > 0 else 0),
        ))
    tree = ft.Column(layers, alignment=ft.MainAxisAlignment.CENTER,
                     horizontal_alignment=ft.CrossAxisAlignment.CENTER)

    baubles = ft.Stack([
        ft.Text("🔴", size=18, left=20, top=120),
        ft.Text("🟡", size=18, left=170, top=100),
        ft.Text("🔵", size=18, left=80, top=180),
        ft.Text("🔴", size=18, left=130, top=200),
        ft.Text("🟡", size=18, left=60, top=240),
    ], width=220, height=280)

    trunk = ft.Container(width=40, height=60, bgcolor="#5D4037", border_radius=5)

    gifts = ft.Row(
        [build_gift(page, d, completed, scores) for d in range(1, 6)],
        alignment=ft.MainAxisAlignment.CENTER, spacing=15,
    )

    def toggle_music(btn):
        new_state = not MUSIC_STATE["on"]
        set_music(new_state)
        btn.content = "🎵 Música" if new_state else "🔇 Música"
        safe_update(btn)

    music_btn = ft.Button(
        content="🎵 Música" if MUSIC_STATE["on"] else "🔇 Música",
        on_click=lambda e: toggle_music(e.control),
        bgcolor=COLOR_RED, color="white",
    )

    reset_btn = ft.Button(
        "Reiniciar progreso", icon=ft.Icons.RESTART_ALT,
        on_click=lambda e: reset_progress(page),
    )

    topbar = ft.Row([music_btn, reset_btn], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)

    return ft.Column([
        topbar, title, subtitle,
        ft.Container(
            content=ft.Column([
                ft.Container(content=star, alignment=ft.Alignment.CENTER),
                ft.Stack([tree, baubles], width=220, height=280),
                trunk, gifts,
            ], alignment=ft.MainAxisAlignment.CENTER,
               horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            alignment=ft.Alignment.CENTER, expand=True,
        ),
    ], alignment=ft.MainAxisAlignment.START,
       horizontal_alignment=ft.CrossAxisAlignment.CENTER)


def build_gift(page, day, completed, scores):
    colors = [COLOR_RED, COLOR_GREEN, COLOR_GOLD, COLOR_BLUE, COLOR_PURPLE]
    bow = [COLOR_GOLD, COLOR_SNOW, COLOR_RED, COLOR_GOLD, COLOR_GREEN]
    box_color = colors[day - 1]
    bow_color = bow[day - 1]
    score = scores.get(str(day), 0)

    gift_box = ft.Stack([
        ft.Container(width=80, height=80, bgcolor=box_color, border_radius=8),
        ft.Container(width=12, height=80, bgcolor=bow_color, left=34),
        ft.Container(width=80, height=12, bgcolor=bow_color, top=34),
        ft.Container(
            content=ft.Text(str(day), size=28, weight=ft.FontWeight.BOLD, color="white"),
            alignment=ft.Alignment.CENTER, width=80, height=80,
        ),
        ft.Container(
            content=ft.Icon(ft.Icons.CHECK_CIRCLE, color=COLOR_GREEN, size=28),
            left=52, top=-12, width=28, height=28,
            visible=day in completed,
            bgcolor="white", border_radius=14, padding=0,
            alignment=ft.Alignment.CENTER,
        ),
    ], width=80, height=80)

    clickable = ft.Container(
        content=gift_box,
        on_click=lambda e, d=day: open_day(page, d),
        ink=True, border_radius=8,
    )

    return ft.Column([
        clickable,
        ft.Text(f"Día {day}", size=13, color=COLOR_SNOW,
                text_align=ft.TextAlign.CENTER, weight=ft.FontWeight.BOLD),
        ft.Text(f"⭐ {score}" if score else " ", size=11, color=COLOR_GOLD),
    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER,
       alignment=ft.MainAxisAlignment.CENTER)


def open_day(page, day):
    builders = {1: build_day1, 2: build_day2, 3: build_day3,
                4: build_day4, 5: build_day5}
    go_to(page, builders[day])


def reset_progress(page):
    save_progress({"completed": [], "scores": {}})
    go_to(page, build_home)


# ============================================================
#  DÍA 1 · SANTA TIRA REGALOS POR CHIMENEAS
# ============================================================
def build_day1(page):
    state = {
        "score": 0, "time_left": 120, "running": True,
        "santa_x": 50, "santa_y": 60, "santa_dir": 1,
        "gifts": [], "buildings": [],
    }

    building_w, gap, city_top = 120, 20, 220
    for i in range(6):
        bx = 30 + i * (building_w + gap)
        chim_w, chim_h = 30, 25
        chim_x = bx + random.randint(20, building_w - chim_w - 20)
        bh = random.randint(150, 220)
        roof_top = city_top + (220 - bh) - 18
        state["buildings"].append({
            "x": bx, "w": building_w, "h": bh,
            "chim_x": chim_x, "chim_w": chim_w, "chim_h": chim_h,
            "chim_top": roof_top - chim_h,
            "color": random.choice(["#5D4037", "#6D4C41", "#795548", "#4E342E"]),
        })

    title = ft.Text("DÍA 1 · Regalos por las chimeneas",
                    size=28, weight=ft.FontWeight.BOLD, color=COLOR_GOLD)
    score_txt = ft.Text("🎁 Regalos: 0", size=22, color=COLOR_SNOW, weight=ft.FontWeight.BOLD)
    timer_txt = ft.Text("⏱ 02:00", size=22, color=COLOR_GOLD, weight=ft.FontWeight.BOLD)

    santa = ft.Container(
        content=ft.Row([
            ft.Text("🦌", size=36), ft.Text("🦌", size=36), ft.Text("🎅🛷", size=40),
        ], spacing=0),
        left=state["santa_x"], top=state["santa_y"],
        width=200, height=50,
    )

    def drop_gift(e=None):
        if not state["running"] or THREAD_STOP["flag"]:
            return
        gx = state["santa_x"] + 130
        gy = state["santa_y"] + 50
        gift_ctrl = ft.Container(
            content=ft.Text("🎁", size=30),
            left=gx, top=gy, width=36, height=36,
        )
        play_area.controls.append(gift_ctrl)
        state["gifts"].append({"x": gx, "y": gy, "vy": 0, "ctrl": gift_ctrl})
        play_fx("drop")
        safe_update(play_area)

    # Contenedor de fondo que sí recibe clics en el cielo
    sky_bg = ft.Container(
        width=900, height=480,
        gradient=ft.LinearGradient(
            begin=ft.Alignment.TOP_CENTER, end=ft.Alignment.BOTTOM_CENTER,
            colors=["#1A237E", "#283593", "#3949AB"],
        ),
        on_click=lambda e: drop_gift(),
    )

    stack_children = [sky_bg]

    for _ in range(30):
        stack_children.append(ft.Text("✦", size=random.randint(8, 14), color="#FFE082",
                                       left=random.randint(0, 880), top=random.randint(0, 200)))

    for b in state["buildings"]:
        stack_children.append(ft.Container(
            width=b["w"], height=b["h"], bgcolor=b["color"],
            left=b["x"], top=city_top + (220 - b["h"]),
            border_radius=ft.BorderRadius.only(top_left=6, top_right=6),
        ))
        for wy in range(0, b["h"] - 30, 30):
            for wx in range(10, b["w"] - 20, 30):
                if random.random() < 0.6:
                    stack_children.append(ft.Container(
                        width=14, height=14, bgcolor="#FFE082",
                        left=b["x"] + wx, top=city_top + (220 - b["h"]) + wy + 10,
                    ))
        stack_children.append(ft.Container(
            width=b["w"], height=18, bgcolor=COLOR_ROOF,
            left=b["x"], top=city_top + (220 - b["h"]) - 18,
        ))
        stack_children.append(ft.Container(
            width=b["chim_w"], height=b["chim_h"], bgcolor=COLOR_CHIMNEY,
            left=b["chim_x"], top=b["chim_top"],
            border_radius=ft.BorderRadius.only(top_left=4, top_right=4),
        ))
        stack_children.append(ft.Text("💨", size=18, left=b["chim_x"] - 5, top=b["chim_top"] - 20))

    stack_children.append(santa)

    snowflakes_ui = []
    for _ in range(40):
        sf = ft.Text("❄", size=random.randint(10, 18), color="#E0F7FA",
                     left=random.randint(0, 880), top=random.randint(0, 480))
        snowflakes_ui.append(sf)
        stack_children.append(sf)

    play_area = ft.Stack(stack_children, width=900, height=480)

    drop_btn = ft.Button(
        "🎁 Soltar regalo  (o clic en el cielo)",
        on_click=drop_gift, bgcolor=COLOR_RED, color="white",
        icon=ft.Icons.CARD_GIFTCARD,
    )

    async def game_loop():
        last = time.time()
        while state["running"] and state["time_left"] > 0 and not THREAD_STOP["flag"]:
            now = time.time()
            dt = min(0.1, now - last)
            last = now

            state["santa_x"] += 90 * dt * state["santa_dir"]
            if state["santa_x"] > 700:
                state["santa_x"] = 700
                state["santa_dir"] = -1
            elif state["santa_x"] < 50:
                state["santa_x"] = 50
                state["santa_dir"] = 1
            state["santa_y"] = 60 + 10 * math.sin(now * 2)
            santa.left = state["santa_x"]
            santa.top = state["santa_y"]

            new_gifts = []
            score_changed = False
            for g in state["gifts"]:
                prev_y = g["y"]
                g["vy"] += 200 * dt
                g["y"] += g["vy"] * dt
                landed = False
                for b in state["buildings"]:
                    if (prev_y <= b["chim_top"] + 15 and g["y"] >= b["chim_top"] - 5 and
                        b["chim_x"] - 5 <= g["x"] + 18 <= b["chim_x"] + b["chim_w"] + 5):
                        state["score"] += 1
                        score_changed = True
                        play_fx("correct")
                        try:
                            play_area.controls.remove(g["ctrl"])
                        except Exception:
                            pass
                        landed = True
                        break
                if landed:
                    continue
                if g["y"] > 470:
                    try:
                        play_area.controls.remove(g["ctrl"])
                    except Exception:
                        pass
                    continue
                g["ctrl"].top = g["y"]
                g["ctrl"].left = g["x"]
                new_gifts.append(g)
            state["gifts"] = new_gifts

            if score_changed:
                score_txt.value = f"🎁 Regalos: {state['score']}"
                safe_update(score_txt)

            for sf in snowflakes_ui:
                cur_top = sf.top + 30 * dt * 2
                if cur_top > 480:
                    cur_top = -10
                    sf.left = random.randint(0, 880)
                sf.top = cur_top

            safe_update(play_area)
            await asyncio.sleep(0.03)

        if state["time_left"] <= 0 and state["running"] and not THREAD_STOP["flag"]:
            end_game()

    async def timer_loop():
        while state["running"] and state["time_left"] > 0 and not THREAD_STOP["flag"]:
            await asyncio.sleep(1)
            if THREAD_STOP["flag"] or not state["running"]:
                return
            state["time_left"] -= 1
            m, s = divmod(state["time_left"], 60)
            timer_txt.value = f"⏱ {m:02d}:{s:02d}"
            if state["time_left"] <= 10 and state["time_left"] > 0:
                play_fx("tick")
            safe_update(timer_txt)
        if state["time_left"] <= 0 and state["running"] and not THREAD_STOP["flag"]:
            end_game()

    def end_game():
        if not state["running"] or THREAD_STOP["flag"]:
            return
        state["running"] = False
        mark_day_complete(1, state["score"])
        play_fx("win")
        dlg = ft.AlertDialog(
            title=ft.Text("⏱ ¡Tiempo agotado!", color=COLOR_RED),
            content=ft.Text(f"Regalos entregados: {state['score']}\n¡Buen trabajo, Santa!", size=18),
            actions=[
                ft.TextButton("Volver", on_click=lambda e: (page.pop_dialog(), go_to(page, build_home))),
                ft.TextButton("Reintentar", on_click=lambda e: (page.pop_dialog(), go_to(page, build_day1))),
            ],
        )
        page.show_dialog(dlg)

    start_task(page, game_loop)
    start_task(page, timer_loop)

    return ft.Column([
        make_back_button(page), title,
        ft.Row([score_txt, timer_txt], alignment=ft.MainAxisAlignment.SPACE_EVENLY),
        drop_btn,
        ft.Container(content=play_area, alignment=ft.Alignment.CENTER),
    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER)


# ============================================================
#  DÍA 2 · ADIVINANZA DE CAJAS (shell game)
# ============================================================
def build_day2(page):
    state = {
        "n_boxes": 0, "boxes": [], "target": None,
        "shuffling": False, "won": False, "hits": 0, "round_id": 0,
    }

    title = ft.Text("DÍA 2 · ¿Dónde está el regalo?",
                    size=28, weight=ft.FontWeight.BOLD, color=COLOR_GOLD)

    def choose_diff(n, e):
        if state["shuffling"]:
            return
        state["n_boxes"] = n
        play_fx("click")
        setup_round()

    diff_card = ft.Container(
        content=ft.Column([
            ft.Text("Elige dificultad", size=22, color=COLOR_SNOW,
                    weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER),
            ft.Row([
                ft.Button(content="😊 Fácil\n(3 cajas)", on_click=lambda e: choose_diff(3, e),
                          bgcolor=COLOR_GREEN, color="white"),
                ft.Button(content="😎 Medio\n(5 cajas)", on_click=lambda e: choose_diff(5, e),
                          bgcolor=COLOR_GOLD, color="black"),
                ft.Button(content="🔥 Difícil\n(7 cajas)", on_click=lambda e: choose_diff(7, e),
                          bgcolor=COLOR_RED, color="white"),
            ], alignment=ft.MainAxisAlignment.CENTER),
            ft.Text("Acierta 3 veces para ganar ⭐", size=14, color=COLOR_GOLD_LIGHT,
                    text_align=ft.TextAlign.CENTER),
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
        padding=20, border_radius=15, bgcolor=COLOR_BG_LIGHT,
    )

    game_area = ft.Stack(width=720, height=320)
    info_txt = ft.Text("Selecciona una dificultad para empezar",
                       size=18, color=COLOR_SNOW, text_align=ft.TextAlign.CENTER)
    attempts_txt = ft.Text("Aciertos: 0/3", size=18, color=COLOR_GOLD)

    GIFTS = ["🧸", "🍬", "⚽", "🪀", "🚂", "🪁", "🎨"]

    def make_box_content(box_color, center):
        if center == "?":
            center_ctrl = ft.Text("?", size=32, color="white", left=24, top=18)
        else:
            center_ctrl = ft.Text(center, size=36, left=18, top=15)
        return ft.Stack([
            ft.Container(width=70, height=70, bgcolor=box_color, border_radius=6),
            ft.Container(width=10, height=70, bgcolor=COLOR_GOLD, left=30),
            ft.Container(width=70, height=10, bgcolor=COLOR_GOLD, top=30),
            center_ctrl,
        ], width=70, height=70)

    def setup_round():
        state["round_id"] += 1
        my_round = state["round_id"]

        game_area.controls.clear()
        state["boxes"] = []
        state["target"] = None
        state["shuffling"] = True
        state["won"] = False
        info_txt.value = "Mira bien dónde se guarda el regalo..."
        info_txt.color = COLOR_SNOW
        safe_update(info_txt)

        n = state["n_boxes"]
        gift_emoji = random.choice(GIFTS)
        target_idx = random.randint(0, n - 1)
        box_w = 70
        spacing = max(40, (720 - n * box_w) // (n + 1))
        positions = []
        x = spacing
        for _ in range(n):
            positions.append(x)
            x += box_w + spacing

        for i in range(n):
            box_color = random.choice([COLOR_RED, COLOR_BLUE, COLOR_GREEN, COLOR_PURPLE, COLOR_GOLD])
            show_gift = gift_emoji if i == target_idx else ""
            content = make_box_content(box_color, show_gift)
            ctrl = ft.Container(
                content=content, left=positions[i], top=150,
                width=70, height=70,
                animate=ft.Animation(400, ft.AnimationCurve.EASE_IN_OUT),
            )
            game_area.controls.append(ctrl)
            state["boxes"].append({
                "idx": i, "ctrl": ctrl, "pos_x": positions[i],
                "has_gift": (i == target_idx), "color": box_color,
            })
        state["target"] = state["boxes"][target_idx]
        safe_update(game_area)

        start_task(page, close_and_shuffle)

    async def close_and_shuffle():
        my_round = state["round_id"]
        await asyncio.sleep(1.6)
        if THREAD_STOP["flag"] or state["round_id"] != my_round:
            return
        for b in state["boxes"]:
            b["ctrl"].content = make_box_content(b["color"], "?")
        info_txt.value = "¡Observa cómo se mezclan!"
        safe_update(info_txt)
        play_fx("shuffle")
        safe_update(game_area)
        await asyncio.sleep(0.6)
        for _ in range(4 + state["n_boxes"]):
            if THREAD_STOP["flag"] or state["round_id"] != my_round:
                return
            a, b = random.sample(state["boxes"], 2)
            a["pos_x"], b["pos_x"] = b["pos_x"], a["pos_x"]
            a["ctrl"].left = a["pos_x"]
            b["ctrl"].left = b["pos_x"]
            safe_update(game_area)
            await asyncio.sleep(0.45)
        if THREAD_STOP["flag"] or state["round_id"] != my_round:
            return
        info_txt.value = "¡Haz clic en la caja que crees que tiene el regalo!"
        state["shuffling"] = False
        safe_update(info_txt)
        for bx in state["boxes"]:
            bx["ctrl"].on_click = lambda e, b=bx: on_pick(b)

    def on_pick(box):
        if state["shuffling"] or state["won"]:
            return
        state["shuffling"] = True
        for bx in state["boxes"]:
            bx["ctrl"].on_click = None

        if box["has_gift"]:
            state["hits"] += 1
            attempts_txt.value = f"Aciertos: {state['hits']}/3"
            play_fx("correct")
            box["ctrl"].content = make_box_content(box["color"], "✅")
            info_txt.value = "¡Correcto! 🎉"
            info_txt.color = COLOR_GREEN
            safe_update(attempts_txt, box["ctrl"], info_txt)
            if state["hits"] >= 3:
                state["won"] = True
                mark_day_complete(2, state["hits"])
                play_fx("win")
                dlg = ft.AlertDialog(
                    title=ft.Text("¡Felicidades! 🎉", color=COLOR_GREEN),
                    content=ft.Text(f"Adivinaste el regalo {state['hits']} veces.\n¡Día 2 superado!", size=18),
                    actions=[
                        ft.TextButton("Volver", on_click=lambda e: (page.pop_dialog(), go_to(page, build_home))),
                    ],
                )
                page.show_dialog(dlg)
                return
        else:
            play_fx("error")
            box["ctrl"].content = make_box_content(box["color"], "❌")
            t = state["target"]
            if t:
                t["ctrl"].content = make_box_content(t["color"], "🎁")
                safe_update(t["ctrl"])
            info_txt.value = "¡Incorrecto! Estaba en otra caja."
            info_txt.color = COLOR_RED
            safe_update(box["ctrl"], info_txt)

        async def next_round():
            my_round = state["round_id"]
            await asyncio.sleep(1.8)
            if THREAD_STOP["flag"] or state["won"] or state["round_id"] != my_round:
                return
            setup_round()

        start_task(page, next_round)

    return ft.Column([
        make_back_button(page), title,
        ft.Container(content=diff_card, alignment=ft.Alignment.CENTER),
        info_txt, attempts_txt,
        ft.Container(content=game_area, alignment=ft.Alignment.CENTER),
    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER)


# ============================================================
#  DÍA 3 · BUSCAR 20 DUENDES EN 70 SEGUNDOS
# ============================================================
def build_day3(page):
    state = {"found": 0, "time_left": 70, "running": True}

    title = ft.Text("DÍA 3 · Encuentra los 20 duendes",
                    size=26, weight=ft.FontWeight.BOLD, color=COLOR_GOLD)
    found_txt = ft.Text("🧝 Encontrados: 0/20", size=20, color=COLOR_SNOW, weight=ft.FontWeight.BOLD)
    timer_txt = ft.Text("⏱ 70s", size=20, color=COLOR_GOLD, weight=ft.FontWeight.BOLD)

    W, H = 900, 480

    stack_children = [ft.Container(
        width=W, height=H,
        gradient=ft.LinearGradient(
            begin=ft.Alignment.TOP_CENTER, end=ft.Alignment.BOTTOM_CENTER,
            colors=["#1A237E", "#3949AB", "#90CAF9", "#E3F2FD"],
        ),
    )]

    for _ in range(15):
        stack_children.append(ft.Text("✦", size=10, color="#FFE082",
            left=random.randint(0, W-10), top=random.randint(0, 100)))

    stack_children.append(ft.Container(
        width=W, height=80, bgcolor="#FAFAFA", left=0, top=H-80,
        border_radius=ft.BorderRadius.only(top_left=60, top_right=60),
    ))

    for mx, mw, mh in [(0, 200, 120), (150, 220, 140), (350, 180, 100),
                       (500, 240, 130), (700, 200, 110)]:
        stack_children.append(ft.Container(
            width=mw, height=mh, bgcolor="#90CAF9",
            left=mx, top=H-80-mh+40,
            border_radius=ft.BorderRadius.only(top_left=mw//2, top_right=mw//2),
        ))

    for _ in range(14):
        tx = random.randint(20, W-80)
        ty = random.randint(180, H-120)
        ts = random.randint(40, 70)
        tree = ft.Stack([
            ft.Container(width=ts, height=ts, bgcolor=COLOR_GREEN_DARK,
                         border_radius=ft.BorderRadius.only(top_left=ts//2, top_right=ts//2),
                         top=ts//3),
            ft.Container(width=int(ts*0.8), height=int(ts*0.8), bgcolor=COLOR_GREEN,
                         border_radius=ft.BorderRadius.only(top_left=int(ts*0.4), top_right=int(ts*0.4)),
                         top=ts//2, left=int(ts*0.1)),
            ft.Container(width=int(ts*0.15), height=int(ts*0.25), bgcolor="#5D4037",
                         left=int(ts*0.42), top=ts+ts//3-5),
            ft.Container(width=ts//2, height=8, bgcolor="white",
                         border_radius=ft.BorderRadius.only(top_left=ts//4, top_right=ts//4),
                         left=int(ts*0.25), top=ts//3),
        ], width=ts, height=int(ts*1.5))
        stack_children.append(ft.Container(content=tree, left=tx, top=ty))

    house_w = 90
    house = ft.Stack([
        ft.Container(width=house_w, height=60, bgcolor=COLOR_RED_DARK, left=0, top=20),
        ft.Container(width=house_w+10, height=25, bgcolor=COLOR_SNOW,
                     border_radius=ft.BorderRadius.only(top_left=house_w//2+5, top_right=house_w//2+5),
                     left=-5, top=0),
        ft.Container(width=20, height=30, bgcolor=COLOR_GOLD, left=35, top=40),
    ], width=house_w+10, height=90)
    stack_children.append(ft.Container(content=house, left=700, top=250))

    gnome_emojis = ["🧝", "🧙", "🎅", "⛄", "🧑‍🎄"]
    gnome_positions = []
    min_dist = 50
    tries = 0
    while len(gnome_positions) < 20:
        gx = random.randint(20, W-40)
        gy = random.randint(150, H-50)
        if all((gx-px)**2 + (gy-py)**2 > min_dist*min_dist for px, py in gnome_positions):
            gnome_positions.append((gx, gy))
        tries += 1
        if tries > 200 and min_dist > 25:
            min_dist -= 5
            tries = 0

    gnomes = []
    for i, (gx, gy) in enumerate(gnome_positions):
        size = random.randint(20, 30)
        gnome = ft.Container(
            content=ft.Text(random.choice(gnome_emojis), size=size),
            left=gx, top=gy, width=size+4, height=size+4,
            on_click=lambda e, idx=i: find_gnome(idx),
            ink=True, border_radius=4, opacity=0.55,
            animate=ft.Animation(300, ft.AnimationCurve.EASE_OUT),
        )
        stack_children.append(gnome)
        gnomes.append({"ctrl": gnome, "found": False, "idx": i})

    play_area = ft.Stack(stack_children, width=W, height=H)

    def find_gnome(idx):
        if THREAD_STOP["flag"] or not state["running"]:
            return
        g = gnomes[idx]
        if g["found"]:
            return
        g["found"] = True
        state["found"] += 1
        found_txt.value = f"🧝 Encontrados: {state['found']}/20"
        g["ctrl"].opacity = 1.0
        g["ctrl"].border = ft.Border.all(3, COLOR_GOLD)
        safe_update(g["ctrl"], found_txt)
        play_fx("correct")
        if state["found"] >= 20:
            state["running"] = False
            mark_day_complete(3, state["found"])
            play_fx("win")
            dlg = ft.AlertDialog(
                title=ft.Text("¡Genial! 🎉", color=COLOR_GREEN),
                content=ft.Text(f"Encontraste los 20 duendes con "
                                f"{state['time_left']}s de sobra.\n¡Día 3 superado!", size=18),
                actions=[
                    ft.TextButton("Volver", on_click=lambda e: (page.pop_dialog(), go_to(page, build_home))),
                ],
            )
            page.show_dialog(dlg)

    async def timer_thread():
        while state["running"] and state["time_left"] > 0 and not THREAD_STOP["flag"]:
            await asyncio.sleep(1)
            if THREAD_STOP["flag"] or not state["running"]:
                return
            state["time_left"] -= 1
            timer_txt.value = f"⏱ {state['time_left']}s"
            if state["time_left"] <= 10 and state["time_left"] > 0:
                play_fx("tick")
            safe_update(timer_txt)
        if state["time_left"] <= 0 and state["running"] and not THREAD_STOP["flag"]:
            state["running"] = False
            play_fx("lose")
            dlg = ft.AlertDialog(
                title=ft.Text("DUENDES GANAN", size=26, color=COLOR_RED,
                              weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER),
                content=ft.Text(f"Solo encontraste {state['found']} de 20.\n"
                                "¡Los duendes se burlan de ti! 🧝🧝🧝",
                                size=18, text_align=ft.TextAlign.CENTER),
                actions=[
                    ft.TextButton("Volver", on_click=lambda e: (page.pop_dialog(), go_to(page, build_home))),
                    ft.TextButton("Reintentar", on_click=lambda e: (page.pop_dialog(), go_to(page, build_day3))),
                ],
            )
            page.show_dialog(dlg)

    start_task(page, timer_thread)

    return ft.Column([
        make_back_button(page), title,
        ft.Row([found_txt, timer_txt], alignment=ft.MainAxisAlignment.SPACE_EVENLY),
        ft.Container(content=play_area, alignment=ft.Alignment.CENTER),
    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER)


# ============================================================
#  DÍA 4 · PASAPALABRA NAVIDEÑO (12 letras A-M sin K)
# ============================================================
def build_day4(page):
    WORDS = [
        ("A", "ÁNGEL",     "Ser celestial que anuncia el nacimiento."),
        ("B", "BELÉN",     "Pueblo donde nació Jesús."),
        ("C", "CARTA",     "Lo escribes a Santa para pedir regalos."),
        ("D", "DULCE",     "Golosina típica de estas fechas."),
        ("E", "ESTRELLA",  "Brillaba sobre el pesebre la nochebuena."),
        ("F", "FUEGO",     "Calienta la chimenea en Nochebuena."),
        ("G", "GUIRNALDA", "Adorno circular colgado en la puerta."),
        ("H", "HIELO",     "Aparece cuando nieva y hace frío."),
        ("I", "INCIENSO",  "Resina aromática quemada por los Reyes."),
        ("J", "JUGUETE",   "Regalo clásico para los niños."),
        ("L", "LUCES",     "Bombillas que decoran el árbol."),
        ("M", "MAGOS",     "Los tres que llevaron oro, incienso y mirra."),
    ]

    state = {"current": 0, "results": [None] * len(WORDS), "finished": False}

    title = ft.Text("DÍA 4 · Pasapalabra Navideño",
                    size=28, weight=ft.FontWeight.BOLD, color=COLOR_GOLD)

    letter_buttons = []
    for i, (letra, _, _) in enumerate(WORDS):
        btn = ft.Container(
            content=ft.Text(letra, size=22, weight=ft.FontWeight.BOLD, color="white"),
            width=50, height=50, bgcolor=COLOR_BG_LIGHT, border_radius=25,
            alignment=ft.Alignment.CENTER,
            on_click=lambda e, idx=i: select_letter(idx),
            animate=ft.Animation(200, ft.AnimationCurve.EASE_OUT),
        )
        letter_buttons.append(btn)

    left_col = ft.Column(letter_buttons[:6], alignment=ft.MainAxisAlignment.CENTER, spacing=8)
    right_col = ft.Column(letter_buttons[6:], alignment=ft.MainAxisAlignment.CENTER, spacing=8)

    current_letter_txt = ft.Text("", size=48, weight=ft.FontWeight.BOLD, color=COLOR_GOLD)
    current_def_txt = ft.Text("", size=18, color=COLOR_SNOW, text_align=ft.TextAlign.CENTER, width=420)
    answer_input = ft.TextField(
        label="Tu respuesta", autofocus=True, width=300,
        text_align=ft.TextAlign.CENTER, text_size=20,
        on_submit=lambda e: check_answer(),
    )

    def _normalize(text):
        if not text:
            return ""
        return "".join(
            c for c in unicodedata.normalize("NFD", text.strip().upper())
            if unicodedata.category(c) != "Mn"
        )

    def update_letter_colors():
        for i, btn in enumerate(letter_buttons):
            res = state["results"][i]
            if i == state["current"]:
                btn.bgcolor = COLOR_GOLD
                btn.content.color = "black"
            elif res == "ok":
                btn.bgcolor = COLOR_GREEN
                btn.content.color = "white"
            elif res == "fail":
                btn.bgcolor = COLOR_RED
                btn.content.color = "white"
            else:
                btn.bgcolor = COLOR_BG_LIGHT
                btn.content.color = "white"
            safe_update(btn)

    def select_letter(idx):
        if state["finished"]:
            return
        state["current"] = idx
        show_current()
        update_letter_colors()

    def show_current():
        if state["finished"]:
            return
        idx = state["current"]
        letra, _, defn = WORDS[idx]
        current_letter_txt.value = f"Letra {letra}"
        current_def_txt.value = defn
        answer_input.value = ""
        safe_update(current_letter_txt, current_def_txt, answer_input)
        safe_focus(answer_input)

    def check_answer():
        if state["finished"]:
            return
        idx = state["current"]
        _, palabra, _ = WORDS[idx]
        ans = (answer_input.value or "").strip()
        if _normalize(ans) == _normalize(palabra):
            state["results"][idx] = "ok"
            play_fx("correct")
        else:
            state["results"][idx] = "fail"
            play_fx("error")
        update_letter_colors()
        next_letter()

    def pasapalabra():
        if state["finished"]:
            return
        play_fx("click")
        next_letter()

    def next_letter():
        if state["finished"]:
            return
        n = len(WORDS)
        for offset in range(1, n + 1):
            ni = (state["current"] + offset) % n
            if state["results"][ni] is None:
                state["current"] = ni
                show_current()
                update_letter_colors()
                return
        finish_game()

    def finish_game():
        state["finished"] = True
        ok = sum(1 for r in state["results"] if r == "ok")
        fail = sum(1 for r in state["results"] if r == "fail")
        mark_day_complete(4, ok)
        play_fx("win")
        dlg = ft.AlertDialog(
            title=ft.Text("📋 Pasapalabra completado", color=COLOR_GOLD),
            content=ft.Text(
                f"✅ Aciertos: {ok}/12\n❌ Errores: {fail}\n¡Día 4 superado!", size=18),
            actions=[
                ft.TextButton("Volver", on_click=lambda e: (page.pop_dialog(), go_to(page, build_home))),
                ft.TextButton("Reintentar", on_click=lambda e: (page.pop_dialog(), go_to(page, build_day4))),
            ],
        )
        page.show_dialog(dlg)

    answer_btn = ft.Button(content="Responder", on_click=lambda e: check_answer(),
                           bgcolor=COLOR_GREEN, color="white", icon=ft.Icons.CHECK)
    pass_btn = ft.Button(content="Pasapalabra", on_click=lambda e: pasapalabra(),
                         bgcolor=COLOR_GOLD, color="black", icon=ft.Icons.ARROW_FORWARD)

    state["current"] = 0

    async def init_later():
        await asyncio.sleep(0.1)
        if THREAD_STOP["flag"]:
            return
        show_current()
        update_letter_colors()
    start_task(page, init_later)

    center_panel = ft.Container(
        content=ft.Column([
            current_letter_txt, current_def_txt, answer_input,
            ft.Row([answer_btn, pass_btn], alignment=ft.MainAxisAlignment.CENTER),
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, alignment=ft.MainAxisAlignment.CENTER),
        padding=30, border_radius=15, bgcolor=COLOR_BG_LIGHT, width=480,
    )

    rosco = ft.Row([left_col, center_panel, right_col],
                   alignment=ft.MainAxisAlignment.CENTER, spacing=20)

    return ft.Column([
        make_back_button(page), title,
        ft.Text("Empieza con la letra A y responde o salta con Pasapalabra",
                size=14, color=COLOR_GOLD_LIGHT, text_align=ft.TextAlign.CENTER),
        rosco,
    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER)


# ============================================================
#  DÍA 5 · ROMPECABEZAS COPO DE NIEVE (12 PIEZAS, 20s)
# ============================================================
SNOWFLAKE_CHARS = ["❄", "❅", "❆", "✻", "✼", "❉", "❊", "✢", "✤", "✥", "✦", "✧"]


def build_day5(page):
    title = ft.Text("DÍA 5 · Rompecabezas Navideño",
                    size=28, weight=ft.FontWeight.BOLD, color=COLOR_GOLD)

    state = {
        "puzzle_started": False,
        "pieces": [], "selected": None,
        "time_left": 20, "running": False,
        "solved": False, "attempts": 0,
    }

    thanks_dlg = ft.AlertDialog(
        title=ft.Text("💌 Gracias por jugar", color=COLOR_GOLD,
                      weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER),
        content=ft.Column([
            ft.Text("¡Gracias por disfrutar nuestro Calendario de Adviento!",
                    size=18, text_align=ft.TextAlign.CENTER),
            ft.Text("Como último reto: arma el copo de nieve en 20 segundos.",
                    size=16, text_align=ft.TextAlign.CENTER, color=COLOR_BLUE_SNOW),
            ft.Text("Si no lo logras, las piezas se desordenarán y tendrás otra oportunidad. ¡Hasta que lo consigas!",
                    size=14, text_align=ft.TextAlign.CENTER),
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
        actions=[
            ft.Button(content="¡Vamos! 🧩", on_click=lambda e: (page.pop_dialog(), start_puzzle()),
                      bgcolor=COLOR_GREEN, color="white"),
        ],
    )

    info_txt = ft.Text("Preparando...", size=18, color=COLOR_SNOW)
    timer_txt = ft.Text("⏱ 20s", size=22, color=COLOR_GOLD, weight=ft.FontWeight.BOLD)
    attempts_txt = ft.Text("Intentos: 0", size=14, color=COLOR_GOLD_LIGHT)

    grid = ft.Row([], alignment=ft.MainAxisAlignment.CENTER, wrap=True)
    grid_wrap = ft.Container(content=grid, padding=10, border_radius=12,
                             bgcolor=COLOR_BG_LIGHT, width=460)

    # Vista previa organizada en 4x3 para que coincida exactamente con la cuadrícula
    preview = ft.Container(
        content=ft.Column([
            ft.Text("Modelo", size=14, color=COLOR_GOLD_LIGHT),
            ft.Row([ft.Text(c, size=22, color=COLOR_BLUE_SNOW) for c in SNOWFLAKE_CHARS[0:4]],
                   spacing=4, alignment=ft.MainAxisAlignment.CENTER),
            ft.Row([ft.Text(c, size=22, color=COLOR_BLUE_SNOW) for c in SNOWFLAKE_CHARS[4:8]],
                   spacing=4, alignment=ft.MainAxisAlignment.CENTER),
            ft.Row([ft.Text(c, size=22, color=COLOR_BLUE_SNOW) for c in SNOWFLAKE_CHARS[8:12]],
                   spacing=4, alignment=ft.MainAxisAlignment.CENTER),
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
        padding=10, border_radius=12, bgcolor=COLOR_BG_LIGHT, width=200,
    )

    PIECE_SIZE = 90

    def make_piece(pos, orig):
        char = SNOWFLAKE_CHARS[orig]
        p_data = {"current_pos": pos, "original_pos": orig, "ctrl": None}
        ctrl = ft.Container(
            width=PIECE_SIZE, height=PIECE_SIZE,
            bgcolor=COLOR_BG, border_radius=8,
            border=ft.Border.all(1, COLOR_BG_LIGHT),
            content=ft.Text(char, size=44, color=COLOR_BLUE_SNOW),
            alignment=ft.Alignment.CENTER,
            on_click=lambda e, piece=p_data: on_click_piece(piece),
            animate=ft.Animation(150, ft.AnimationCurve.EASE_OUT),
        )
        p_data["ctrl"] = ctrl
        return p_data

    def build_pieces():
        state["pieces"] = []
        grid.controls.clear()
        order = list(range(12))
        random.shuffle(order)
        while order == list(range(12)):
            random.shuffle(order)

        for pos, orig in enumerate(order):
            piece = make_piece(pos, orig)
            state["pieces"].append(piece)
            grid.controls.append(piece["ctrl"])

    def refresh_grid():
        grid.controls.clear()
        for p in sorted(state["pieces"], key=lambda x: x["current_pos"]):
            grid.controls.append(p["ctrl"])
        safe_update(grid)

    def on_click_piece(piece):
        if state["solved"] or not state["running"]:
            return

        if state["selected"] is None:
            state["selected"] = piece
            piece["ctrl"].border = ft.Border.all(3, COLOR_GOLD)
            safe_update(piece["ctrl"])
            play_fx("click")
        else:
            if state["selected"] is piece:
                piece["ctrl"].border = ft.Border.all(1, COLOR_BG_LIGHT)
                safe_update(piece["ctrl"])
                state["selected"] = None
                return

            sel = state["selected"]
            sel["ctrl"].border = ft.Border.all(1, COLOR_BG_LIGHT)
            piece["ctrl"].border = ft.Border.all(1, COLOR_BG_LIGHT)
            sel["current_pos"], piece["current_pos"] = piece["current_pos"], sel["current_pos"]
            state["selected"] = None
            play_fx("shuffle")
            refresh_grid()
            check_solved()

    def check_solved():
        for p in state["pieces"]:
            if p["current_pos"] != p["original_pos"]:
                return False
        state["solved"] = True
        state["running"] = False
        mark_day_complete(5, max(1, 10 - state["attempts"]))
        play_fx("win")
        dlg = ft.AlertDialog(
            title=ft.Text("¡Copo completo! ❄️", color=COLOR_BLUE_SNOW,
                          weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER),
            content=ft.Column([
                ft.Text(f"Lo lograste en {state['attempts']} intentos.", size=18,
                        text_align=ft.TextAlign.CENTER),
                ft.Text("¡Gracias por completar el calendario de adviento! 🎄",
                        size=16, text_align=ft.TextAlign.CENTER, color=COLOR_GOLD),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            actions=[
                ft.TextButton("Volver al inicio", on_click=lambda e: (page.pop_dialog(), go_to(page, build_home))),
            ],
        )
        page.show_dialog(dlg)
        return True

    async def timer_thread():
        while state["running"] and not state["solved"] and not THREAD_STOP["flag"]:
            await asyncio.sleep(1)
            if THREAD_STOP["flag"] or state["solved"] or not state["running"]:
                return
            state["time_left"] -= 1
            timer_txt.value = f"⏱ {state['time_left']}s"
            if state["time_left"] <= 5 and state["time_left"] > 0:
                play_fx("tick")
            safe_update(timer_txt)
            if state["time_left"] <= 0 and state["running"] and not state["solved"]:
                shuffle_again()

    def shuffle_again():
        state["running"] = False
        if state["selected"]:
            try:
                state["selected"]["ctrl"].border = ft.Border.all(1, COLOR_BG_LIGHT)
            except Exception:
                pass
            state["selected"] = None

        state["attempts"] += 1
        attempts_txt.value = f"Intentos: {state['attempts']}"
        play_fx("lose")
        info_txt.value = "⏱ ¡Se acabó el tiempo! Mezclando de nuevo..."
        info_txt.color = COLOR_RED
        safe_update(attempts_txt, info_txt)

        positions = list(range(12))
        random.shuffle(positions)
        while positions == [p["current_pos"] for p in state["pieces"]]:
            random.shuffle(positions)

        for p, new_pos in zip(state["pieces"], positions):
            p["current_pos"] = new_pos
        refresh_grid()
        state["time_left"] = 20
        timer_txt.value = "⏱ 20s"
        safe_update(timer_txt)
        start_task(page, _after_shuffle)

    async def _after_shuffle():
        await asyncio.sleep(1.2)
        if THREAD_STOP["flag"] or state["solved"]:
            return
        state["running"] = True
        info_txt.value = "¡Otra oportunidad! Toca dos piezas para intercambiarlas."
        info_txt.color = COLOR_SNOW
        safe_update(info_txt)

    def start_puzzle():
        if state["puzzle_started"]:
            return
        state["puzzle_started"] = True
        state["running"] = True
        state["solved"] = False
        state["selected"] = None
        state["attempts"] = 0
        attempts_txt.value = "Intentos: 0"
        info_txt.value = "Toca dos piezas para intercambiarlas. ¡Armá el copo!"
        info_txt.color = COLOR_SNOW
        build_pieces()
        refresh_grid()
        safe_update(info_txt, attempts_txt)
        start_task(page, timer_thread)

    async def show_thanks_later():
        await asyncio.sleep(0.2)
        if THREAD_STOP["flag"]:
            return
        page.show_dialog(thanks_dlg)

    start_task(page, show_thanks_later)

    return ft.Column([
        make_back_button(page), title,
        ft.Row([timer_txt, attempts_txt], alignment=ft.MainAxisAlignment.CENTER, spacing=30),
        info_txt,
        ft.Row([preview, grid_wrap], alignment=ft.MainAxisAlignment.CENTER, spacing=30),
    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER)


# ============================================================
#  MAIN
# ============================================================
def main(page: ft.Page):
    PAGE_REF["page"] = page
    page.title = "🎄 Calendario de Adviento"
    page.bgcolor = COLOR_BG
    page.padding = 20
    page.scroll = ft.ScrollMode.AUTO

    try:
        page.window.width = 1100
        page.window.height = 780
        page.window.resizable = True
    except Exception:
        pass

    ensure_assets()
    init_audio(page)
    MUSIC_STATE["on"] = True

    page.add(build_home(page))
    page.update()
    set_music(True)


if __name__ == "__main__":
    ft.run(main, assets_dir=str(ASSETS_DIR))
