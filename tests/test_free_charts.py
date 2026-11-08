from copy import deepcopy
from dataclasses import asdict, replace
import unittest

from PIL import Image

from test_app import METRICS
from turzx.charts import render_chart
from turzx.gpu import GPU
from turzx.history import History
from turzx.metrics import CATALOG, history_key
from turzx.palette import groups
from turzx.theme_render import editor_preview, render_theme
from turzx.themes import EditorModel, Item, Theme, from_dict, starter


class FreeElementTests(unittest.TestCase):
    def test_text_has_no_container_and_transparent_background(self):
        model = EditorModel(Theme())
        item = model.add_text(20, 40)
        model.set_properties(text="LINUX", width=130)
        self.assertEqual(model.theme.containers, [])
        self.assertEqual(model.bounds(), (20, 40, 130, 36))
        rendered = render_theme(model.theme, METRICS)
        self.assertEqual(rendered.getpixel((22, 74)), (11, 18, 32))
        self.assertEqual(model.hit(30, 50), (None, item.id))
        self.assertIsNone(model.hit(30, 50, containers_only=True))

    def test_text_button_is_free_even_when_container_selected(self):
        model = EditorModel(starter())
        model.selection = model.theme.containers[0].id, None
        model.add_text()
        self.assertIsNone(model.selection[0])
        self.assertEqual(len(model.theme.items), 1)

    def test_move_resize_duplicate_delete_undo_free_item(self):
        model = EditorModel(Theme())
        item = model.add_text()
        model.begin_drag()
        model.drag(20, 30)
        model.finish_drag()
        self.assertEqual(model.bounds()[:2], (30, 42))
        model.begin_drag()
        model.drag(40, 20, resize=True)
        model.finish_drag()
        self.assertEqual(model.bounds()[2:], (260, 56))
        model.duplicate()
        self.assertEqual(len(model.theme.items), 2)
        model.delete()
        self.assertEqual(len(model.theme.items), 1)
        model.undo()
        self.assertEqual(len(model.theme.items), 2)
        model.theme.validate()

    def test_free_element_and_container_share_layer_order(self):
        model = EditorModel(Theme())
        container = model.add_container("cpu", 10, 12)
        item = model.add_text()
        self.assertEqual(model.hit(15, 15), (None, item.id))
        model.layer(-1)
        self.assertEqual(model.hit(15, 15), (container.id, None))
        model.layer(1)
        self.assertEqual(model.hit(15, 15), (None, item.id))

    def test_schema_one_migrates_without_changing_rendered_output(self):
        theme = starter()
        old = asdict(theme)
        old["schema"] = 1
        old.pop("items")
        for c in old["containers"]:
            c.pop("z")
            for i in c["items"]:
                for key in ("z", "gpu_id", "chart_window", "chart_max", "chart_line_width", "chart_grid"):
                    i.pop(key)
        migrated = from_dict(old)
        self.assertEqual(migrated.schema, 2)
        self.assertEqual(render_theme(migrated, METRICS).tobytes(), render_theme(theme, METRICS).tobytes())

    def test_schema_roundtrip_free_gpu_and_charts(self):
        model = EditorModel(Theme())
        model.add_chart(key="gpu.usage")
        model.set_properties(gpu_id="pci:second")
        model.add_text()
        self.assertEqual(from_dict(asdict(model.theme)), model.theme)

    def test_invalid_free_geometry_and_chart_source_are_rejected(self):
        model = EditorModel(Theme())
        model.add_chart()
        for key, value in (("metric", "text"), ("chart_max", float("nan")), ("chart_window", 0)):
            before = deepcopy(model.theme)
            with self.assertRaises(ValueError):
                model.set_properties(**{key: value})
            self.assertEqual(before, model.theme)
        duplicate = asdict(model.theme)
        duplicate["items"].append(deepcopy(duplicate["items"][0]))
        with self.assertRaises(ValueError):
            from_dict(duplicate)

    def test_resize_chart_preserves_minimum_and_canvas_orientation(self):
        model = EditorModel(Theme())
        model.add_chart()
        model.begin_drag()
        model.drag(-900, -900, resize=True)
        model.finish_drag()
        self.assertEqual(model.bounds()[2:], (80, 60))
        model.resize_canvas((320, 480))
        model.theme.validate()


class HistoryAndChartTests(unittest.TestCase):
    def test_history_is_bounded_in_time_and_snapshots_do_not_mutate(self):
        history = History()
        original = history.record(METRICS, 0)
        for i in range(1, 800):
            current = history.record(replace(METRICS, cpu=i % 100), i)
        self.assertEqual(original["cpu.usage"], ((0, METRICS.cpu),))
        self.assertLessEqual(len(current["cpu.usage"]), 301)
        self.assertGreaterEqual(current["cpu.usage"][0][0], 499)

    def test_missing_gpu_creates_gap_and_no_cross_device_history(self):
        history = History()
        metrics = replace(METRICS, gpus=[GPU("one", "GPU 1", "AMD", usage=10), GPU("two", "GPU 2", "AMD", usage=90)])
        first = history.record(metrics, 1)
        self.assertEqual(first["gpu.usage@one"][-1][1], 10)
        self.assertEqual(first["gpu.usage@two"][-1][1], 90)
        second = history.record(replace(metrics, gpus=metrics.gpus[:1]), 2)
        self.assertIsNone(second["gpu.usage@two"][-1][1])
        self.assertEqual(history_key("gpu.usage", metrics, "two"), "gpu.usage@two")

    def test_every_chart_renders_real_samples_and_handles_missing(self):
        history = History()
        metrics = METRICS
        for t, value in enumerate((0, 25, None, 80, 40)):
            metrics = replace(METRICS, temperature=value, sampled_at=t)
            metrics.history = history.record(metrics, t)
        for style in ("chart_line", "chart_area", "chart_bars"):
            item = Item(metric="cpu.temperature", width=220, height=110, style=style, chart_window=10)
            image = render_chart(item, metrics, "auto")
            self.assertEqual(image.size, (220, 110))
            self.assertTrue(image.getbbox())
            empty = render_chart(item, replace(metrics, history={}, temperature=None), "auto")
            self.assertNotEqual(image.tobytes(), empty.tobytes())

    def test_plot_gap_is_not_interpolated(self):
        metrics = replace(METRICS, sampled_at=10, history={"cpu.usage": ((0, 50), (4, 50), (5, None), (6, 50), (10, 50))})
        item = Item(width=220, height=100, style="chart_line", chart_window=10, chart_grid=False)
        image = render_chart(item, metrics, "auto")
        # Plot midpoint (t=5) must remain transparent while adjacent segments exist.
        x = round((31 + 217) / 2)
        y = round((21 + 86) / 2)
        self.assertEqual(image.getpixel((x, y))[3], 0)

    def test_editing_points_stay_visible_when_snapping_is_disabled(self):
        model = EditorModel(Theme())
        model.add_text()
        model.selection = None
        plain = render_theme(model.theme, METRICS)
        self.assertNotEqual(editor_preview(model, METRICS, False).tobytes(), plain.tobytes())
        self.assertEqual(editor_preview(model, METRICS, False).tobytes(), editor_preview(model, METRICS, True).tobytes())
        self.assertEqual(plain.tobytes(), render_theme(model.theme, METRICS).tobytes())


class LibraryTests(unittest.TestCase):
    def test_memory_and_network_list_without_search(self):
        memory = groups(list(CATALOG), selected="memory")
        network = groups(list(CATALOG), selected="network")
        self.assertEqual(memory["memory"], ["memory.usage", "memory.used", "memory.total"])
        self.assertEqual(network["network"], ["network.download", "network.upload"])

    def test_search_crosses_categories_and_accepts_missing_accents(self):
        self.assertIn("memory.usage", groups(list(CATALOG), selected="cpu", query="memoria")["memory"])
        self.assertIn("cpu.cores", groups(list(CATALOG), selected="network", query="nucleos")["cpu"])

    def test_graph_history_is_not_exported_in_theme(self):
        model = EditorModel(Theme())
        model.add_chart()
        document = asdict(model.theme)
        self.assertNotIn("history", document)
        self.assertNotIn("history", document["items"][0])
