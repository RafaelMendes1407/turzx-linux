"""Exercise actual GTK controller callbacks using a canvas allocation stand-in.

This verifies DnD payload routing and zoom math without needing a display server.
The native window's visual smoke test is separate (--smoke-gui).
"""

from types import SimpleNamespace
import unittest

from turzx.editor import StudioWindow
from turzx.themes import EditorModel, Theme, viewport_point


class CanvasHarness:
    def __init__(self):
        self.model = EditorModel(Theme())
        self.messages = []
        self.picture = SimpleNamespace(grab_focus=lambda: None)
        self.grid = SimpleNamespace(get_active=lambda: False)
        self.dragging = False

    def point(self, x, y):
        return viewport_point(x, y, (960, 640), self.model.theme.size)

    def refresh(self, *args):
        pass

    def show_message(self, message):
        self.messages.append(message)

    def add_container(self, category, x, y):
        self.model.add_container(category, x, y)

    def add_metric(self, metric, x, y):
        self.model.add_metric(metric, x, y)

    def add_text(self, x, y):
        self.model.add_text(x, y)

    def add_chart(self, style, x, y):
        self.model.add_chart(style, x=x, y=y)


class EditorEventTests(unittest.TestCase):
    def test_drop_container_then_metric_at_zoom_200(self):
        canvas = CanvasHarness()
        self.assertTrue(StudioWindow.drop(canvas, None, "container:cpu", 80, 100))
        container = canvas.model.theme.containers[0]
        self.assertEqual((container.x, container.y), (40, 50))
        self.assertTrue(StudioWindow.drop(canvas, None, "metric:cpu.temperature", 100, 170))
        item = container.items[0]
        self.assertEqual((item.x, item.y, item.metric), (10, 35, "cpu.temperature"))
        canvas.model.theme.validate()

    def test_unknown_payload_or_drop_outside_canvas_is_rejected(self):
        canvas = CanvasHarness()
        for payload, x, y in [("container:invalid", 20, 20),
                              ("metric:unknown", 20, 20), ("container:gpu", -10, 20)]:
            self.assertFalse(StudioWindow.drop(canvas, None, payload, x, y))
        self.assertEqual(canvas.model.theme.containers, [])

    def test_metric_text_and_chart_can_be_dropped_on_bare_canvas(self):
        canvas = CanvasHarness()
        for payload in ("metric:cpu.usage", "free:text", "chart:chart_line"):
            self.assertTrue(StudioWindow.drop(canvas, None, payload, 40, 60))
        self.assertEqual(len(canvas.model.theme.items), 3)
        self.assertEqual(canvas.model.theme.containers, [])
        canvas.model.theme.validate()

    def test_actual_drag_callbacks_move_and_resize_nested_item(self):
        canvas = CanvasHarness()
        c = canvas.model.add_container("cpu", 40, 50)
        item = canvas.model.add_metric("cpu.usage", 10, 35)
        StudioWindow.drag_begin(canvas, None, 110, 180)
        StudioWindow.drag_update(canvas, None, 20, 10)
        StudioWindow.drag_end(canvas)
        c, item = canvas.model.selected()
        self.assertEqual((item.x, item.y), (20, 40))
        # Bottom-right resize handle, mapped to twice the panel's native resolution.
        x, y, width, height = canvas.model.bounds()
        StudioWindow.drag_begin(canvas, None, 2 * (x + width - 1), 2 * (y + height - 1))
        self.assertTrue(canvas.resize_drag)
        StudioWindow.drag_update(canvas, None, -40, 20)
        StudioWindow.drag_end(canvas)
        _, item = canvas.model.selected()
        self.assertEqual((item.width, item.height), (180, 36))
        canvas.model.theme.validate()

    def test_simple_click_selects_header_and_blank_clears(self):
        canvas = CanvasHarness()
        c = canvas.model.add_container("gpu", 40, 50)
        StudioWindow.canvas_click(canvas, None, 1, 100, 110)
        self.assertEqual(canvas.model.selection, (c.id, None))
        StudioWindow.canvas_click(canvas, None, 1, 0, 0)
        self.assertIsNone(canvas.model.selection)
