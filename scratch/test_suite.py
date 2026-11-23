import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import main
import flet as ft


class MockPage:
    def __init__(self):
        self.controls = []
        self.overlay = []
        self._dialogs = []
        self.last_dlg = None

    def run_task(self, coro_fn, *args, **kwargs):
        self.last_task = coro_fn
        return coro_fn

    def add(self, ctrl):
        self.controls.append(ctrl)

    def update(self):
        pass

    def show_dialog(self, dlg):
        self.last_dlg = dlg
        self._dialogs.append(dlg)

    def pop_dialog(self):
        if self._dialogs:
            return self._dialogs.pop()
        return None


def test_audio():
    print("Testing audio...")
    p = MockPage()
    main.ensure_assets()
    main.init_audio(p)
    assert len(main.AUDIO_REFS) > 0, "AUDIO_REFS should not be empty"
    assert len(p.overlay) == len(main.AUDIO_REFS), "All audios should be mounted in page.overlay"
    main.play_fx("click")
    main.set_music(True)
    main.set_music(False)
    print("Audio test passed.")


def test_build_home():
    print("Testing build_home...")
    p = MockPage()
    col = main.build_home(p)
    assert isinstance(col, ft.Column)
    print("build_home test passed.")


def test_day1():
    print("Testing Day 1...")
    p = MockPage()
    col = main.build_day1(p)
    assert isinstance(col, ft.Column)
    # Check sky container has on_click
    play_area_container = col.controls[4]
    stack = play_area_container.content
    sky_bg = stack.controls[0]
    assert sky_bg.on_click is not None, "Sky background should have on_click"
    # Trigger drop gift
    sky_bg.on_click(None)
    print("Day 1 test passed.")


def test_day2():
    print("Testing Day 2...")
    p = MockPage()
    col = main.build_day2(p)
    assert isinstance(col, ft.Column)
    # Trigger difficulty button
    diff_card = col.controls[2].content
    row_buttons = diff_card.content.controls[1]
    easy_btn = row_buttons.controls[0]
    easy_btn.on_click(None)
    print("Day 2 test passed.")


def test_day3():
    print("Testing Day 3...")
    p = MockPage()
    col = main.build_day3(p)
    assert isinstance(col, ft.Column)
    # Find a gnome and click it
    play_area = col.controls[3].content
    gnome_found = False
    for ctrl in play_area.controls:
        if isinstance(ctrl, ft.Container) and ctrl.on_click is not None and getattr(ctrl, "opacity", None) == 0.55:
            # Click gnome
            ctrl.on_click(None)
            assert ctrl.border is not None, "Border should be set"
            assert ctrl.border.top.color == main.COLOR_GOLD, "Border color should be gold"
            gnome_found = True
            break
    assert gnome_found, "At least one clickable gnome should be found"
    print("Day 3 test passed.")


def test_day4():
    print("Testing Day 4...")
    p = MockPage()
    col = main.build_day4(p)
    assert isinstance(col, ft.Column)
    rosco = col.controls[3]
    center_panel = rosco.controls[1].content
    answer_input = center_panel.controls[2]
    buttons_row = center_panel.controls[3]
    answer_btn = buttons_row.controls[0]
    pass_btn = buttons_row.controls[1]

    # Letter A is "ÁNGEL". Test typing "angel" without accent
    answer_input.value = "angel"
    answer_btn.on_click(None)

    left_col = rosco.controls[0]
    assert left_col.controls[0].bgcolor == main.COLOR_GREEN, "Unaccented answer 'angel' should be accepted for 'ÁNGEL'"

    # Test pasapalabra
    pass_btn.on_click(None)
    print("Day 4 test passed.")


def test_day5():
    print("Testing Day 5...")
    p = MockPage()
    col = main.build_day5(p)
    assert isinstance(col, ft.Column)
    # Execute the scheduled show_thanks_later task
    import asyncio
    asyncio.run(p.last_task())
    assert p.last_dlg is not None, "Thanks dialog should have opened"
    action_btn = p.last_dlg.actions[0]
    action_btn.on_click(None)

    # Grid should be populated with 12 pieces
    grid_wrap = col.controls[4].controls[1]
    grid = grid_wrap.content
    assert len(grid.controls) == 12, "Grid should have 12 pieces"

    # Test clicking piece 0 (selects it)
    p0 = grid.controls[0]
    p0.on_click(None)
    assert p0.border.top.color == main.COLOR_GOLD, "Selected piece should have gold border"

    # Test clicking piece 1 (swaps piece 0 and 1)
    p1 = grid.controls[1]
    p1.on_click(None)
    assert p0.border.top.color == main.COLOR_BG_LIGHT, "After swap, border should return to normal"
    assert p1.border.top.color == main.COLOR_BG_LIGHT, "After swap, border should return to normal"

    # Now click p0 again (it was swapped, but clicking it should still work and select IT, not the other piece!)
    p0.on_click(None)
    assert p0.border.top.color == main.COLOR_GOLD, "Clicking swapped piece should correctly select it"
    # Unselect it
    p0.on_click(None)
    assert p0.border.top.color == main.COLOR_BG_LIGHT, "Unselecting piece should reset border"
    print("Day 5 test passed.")


def test_task_lifecycle():
    print("Testing task lifecycle...")
    p = MockPage()
    main.stop_all_tasks(p)
    assert main.THREAD_STOP["flag"] is True
    print("Task lifecycle test passed.")


if __name__ == "__main__":
    test_audio()
    test_build_home()
    test_day1()
    test_day2()
    test_day3()
    test_day4()
    test_day5()
    test_task_lifecycle()
    print("\nALL 8 TEST SUITES PASSED SUCCESSFULLY!")
