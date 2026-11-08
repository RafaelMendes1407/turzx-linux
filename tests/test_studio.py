from copy import deepcopy
from dataclasses import asdict, replace
import io
import json
import os
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from test_app import METRICS
from turzx.config import Config, load_config, save_config
from turzx.gpu import GPU
from turzx.metrics import CATALOG, reading
from turzx.render import render
from turzx.theme_render import editor_preview, render_theme
from turzx.themes import (EditorModel, Theme, decode_background, encode_background, from_dict,
                         list_themes, load_theme, read_theme, save_theme, starter, viewport_point)


class ThemeTests(unittest.TestCase):
    def test_starters_both_sizes_validate_and_render(self):
        for size in ((480, 320), (320, 480)):
            theme = starter(size)
            self.assertEqual(from_dict(asdict(theme)), theme)
            self.assertEqual(render_theme(theme, METRICS).size, size)

    def test_save_load_and_export_are_lossless(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"XDG_CONFIG_HOME": tmp}):
            theme = starter()
            theme.name = "Meu tema • ação"
            save_theme(theme)
            self.assertEqual(load_theme(theme.id), theme)
            self.assertIn((theme.id, theme.name), list_themes())
            exported = Path(tmp) / "export.json"
            save_theme(theme, exported)
            self.assertEqual(read_theme(exported), theme)

    def test_reject_malformed_and_unsafe_documents(self):
        theme = asdict(starter())
        cases = [dict(theme, id="../../x"), dict(theme, schema=999), dict(theme, width=0),
                 dict(theme, background="red"), dict(theme, containers={}), dict(theme, unknown=1)]
        for name, value in (("width", -5), ("opacity", 300), ("x", 1000), ("gpu_id", None)):
            bad = deepcopy(theme)
            bad["containers"][0][name] = value
            cases.append(bad)
        for name, value in (("metric", "not.real"), ("width", 999), ("font_family", []), ("font_size", float("nan")), ("bold", "yes")):
            bad = deepcopy(theme)
            bad["containers"][0]["items"][0][name] = value
            cases.append(bad)
        duplicate = deepcopy(theme)
        duplicate["containers"][1]["id"] = duplicate["containers"][0]["id"]
        cases.append(duplicate)
        for bad in cases:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                from_dict(bad)

    def test_invalid_library_entries_do_not_hide_good_themes(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"XDG_CONFIG_HOME": tmp}):
            theme = starter()
            save_theme(theme)
            (Path(tmp) / "turzx-linux/themes/bad.json").write_text("{broken")
            self.assertEqual(list_themes(), [(theme.id, theme.name)])

    def test_background_is_embedded_and_survives_source_removal(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "image.png"
            Image.new("RGB", (90, 60), "red").save(path)
            theme = Theme(background_image=encode_background(path, (480, 320)))
            path.unlink()
            self.assertEqual(render_theme(from_dict(asdict(theme)), METRICS).getpixel((0, 0)), (255, 0, 0))
            with self.assertRaises(ValueError):
                decode_background("not-base64!")

    def test_applied_snapshot_is_unchanged_by_saving_an_edit(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"XDG_CONFIG_HOME": tmp}):
            theme = starter()
            save_theme(theme)
            config = Config(mode="custom", custom_theme=theme.id, custom_theme_data=asdict(theme))
            save_config(config)
            before = render(load_config(), METRICS).tobytes()
            theme.background = "#ffffff"
            theme.containers.clear()
            save_theme(theme)
            self.assertEqual(render(load_config(), METRICS).tobytes(), before)
            save_config(replace(config, custom_theme_data=asdict(theme)))
            self.assertNotEqual(render(load_config(), METRICS).tobytes(), before)

    def test_orientation_mismatch_has_actionable_error(self):
        theme = starter((320, 480))
        config = Config(mode="custom", custom_theme=theme.id, custom_theme_data=asdict(theme), rotation=90)
        with self.assertRaisesRegex(ValueError, "orientação"):
            render(config, METRICS)

    def test_all_visual_styles_fonts_and_transparency(self):
        theme = starter()
        item = theme.containers[0].items[0]
        for style in ("line", "value", "bar"):
            for family in ("sans", "mono", "serif"):
                for align in ("left", "center", "right"):
                    item.style, item.font_family, item.align = style, family, align
                    theme.containers[0].opacity = 80
                    self.assertEqual(render_theme(theme, METRICS).mode, "RGB")

    def test_selection_and_grid_never_leak_into_usb_frame(self):
        model = EditorModel(starter())
        c = model.theme.containers[0]
        model.selection = c.id, None
        before = render_theme(model.theme, METRICS).tobytes()
        preview = editor_preview(model, METRICS, grid=True)
        self.assertNotEqual(preview.tobytes(), before)
        self.assertEqual(render_theme(model.theme, METRICS).tobytes(), before)


class EditingTests(unittest.TestCase):
    def test_container_and_nested_information_can_be_created_and_hit(self):
        model = EditorModel(Theme())
        c = model.add_container("cpu", 50, 60)
        item = model.add_metric("cpu.temperature", 10, 35)
        self.assertEqual(model.hit(65, 100), (c.id, item.id))
        self.assertEqual(model.hit(65, 100, containers_only=True), (c.id, None))
        self.assertEqual(model.hit(60, 65), (c.id, None))
        self.assertIsNone(model.hit(0, 0))
        self.assertEqual(model.bounds(), (60, 95, 200, 26))

    def test_container_moves_children_and_stays_on_canvas(self):
        model = EditorModel(starter())
        c = model.theme.containers[0]
        relative = deepcopy(c.items)
        model.selection = c.id, None
        model.begin_drag()
        model.drag(1000, -1000)
        model.finish_drag()
        c, _ = model.selected()
        self.assertEqual(c.x, model.theme.width - c.width)
        self.assertEqual(c.y, 0)
        self.assertEqual(c.items, relative)
        model.theme.validate()

    def test_item_moves_in_parent_coordinates_and_resize_is_clamped(self):
        model = EditorModel(starter())
        c = model.theme.containers[0]
        model.selection = c.id, c.items[0].id
        model.begin_drag()
        model.drag(-999, 999)
        model.finish_drag()
        c, item = model.selected()
        self.assertEqual((item.x, item.y), (0, c.height - item.height))
        model.begin_drag()
        model.drag(999, 999, resize=True)
        model.finish_drag()
        c, item = model.selected()
        self.assertEqual((item.width, item.height), (c.width, 27))
        self.assertEqual((item.x, item.y), (0, c.height - 27))
        model.theme.validate()

    def test_drag_history_is_one_step_not_one_per_motion(self):
        model = EditorModel(starter())
        original = deepcopy(model.theme)
        model.selection = model.theme.containers[0].id, None
        model.begin_drag()
        for delta in (1, 5, 10, 20):
            model.drag(delta, delta)
        model.finish_drag()
        moved = deepcopy(model.theme)
        self.assertEqual(len(model.undo_stack), 1)
        model.undo()
        self.assertEqual(model.theme, original)
        model.redo()
        self.assertEqual(model.theme, moved)

    def test_noop_drag_does_not_modify_or_dirty_document(self):
        model = EditorModel(starter())
        model.selection = model.theme.containers[0].id, None
        model.begin_drag()
        model.drag(0, 0, grid=8)
        model.finish_drag()
        self.assertFalse(model.dirty)
        self.assertEqual(model.undo_stack, [])

    def test_duplicate_and_delete_preserve_unique_ids_and_undo(self):
        model = EditorModel(starter())
        model.selection = model.theme.containers[0].id, None
        model.duplicate()
        self.assertEqual(len(model.theme.containers), 5)
        model.theme.validate()
        model.delete()
        self.assertEqual(len(model.theme.containers), 4)
        model.undo()
        self.assertEqual(len(model.theme.containers), 5)

    def test_undo_then_edit_invalidates_redo(self):
        model = EditorModel(starter())
        model.add_container("gpu")
        model.undo()
        model.add_container("cpu")
        self.assertEqual(model.redo_stack, [])

    def test_container_resize_scales_children_and_rejects_bad_properties_atomically(self):
        model = EditorModel(starter())
        c = model.theme.containers[0]
        model.selection = c.id, None
        model.set_properties(width=96, height=64)
        model.theme.validate()
        before = deepcopy(model.theme)
        with self.assertRaises(ValueError):
            model.set_properties(background="invalid")
        self.assertEqual(model.theme, before)

    def test_orientation_change_keeps_all_components_inside_parent(self):
        model = EditorModel(starter())
        model.resize_canvas((320, 480))
        model.theme.validate()
        model.resize_canvas((480, 320))
        model.theme.validate()

    def test_layer_order_controls_hit_testing(self):
        model = EditorModel(Theme())
        first = model.add_container("cpu")
        second = model.add_container("gpu")
        self.assertEqual(model.hit(20, 20), (second.id, None))
        model.layer(-1)
        self.assertEqual(model.hit(20, 20), (first.id, None))

    def test_metric_is_free_without_parent_and_needs_space_inside_parent(self):
        model = EditorModel(Theme())
        model.add_metric("cpu.usage")
        self.assertEqual(len(model.theme.items), 1)
        model.add_container("cpu")
        for _ in range(3):
            model.add_metric("cpu.usage")
        with self.assertRaisesRegex(ValueError, "altura"):
            model.add_metric("cpu.usage")

    def test_canvas_coordinate_mapping_at_zoom_and_letterbox(self):
        self.assertEqual(viewport_point(100, 50, (960, 640), (480, 320)), (50, 25, 2))
        self.assertEqual(viewport_point(100, 180, (960, 960), (480, 320)), (50, 10, 2))

    def test_random_edit_sequences_keep_schema_valid(self):
        rng = random.Random(12)
        model = EditorModel(starter())
        for _ in range(80):
            c = rng.choice(model.theme.containers)
            item = rng.choice(c.items) if rng.choice([True, False]) else None
            model.selection = c.id, item.id if item else None
            model.begin_drag()
            model.drag(rng.randint(-500, 500), rng.randint(-500, 500), rng.choice([True, False]), grid=8)
            model.finish_drag()
            model.theme.validate()
        self.assertLessEqual(len(model.undo_stack), 60)


class ReadingTests(unittest.TestCase):
    def test_gpu_selection_uses_identity_not_changing_order(self):
        a = GPU("pci:a", "AMD A", "AMD", usage=20)
        b = GPU("pci:b", "AMD B", "AMD", usage=80)
        metrics = replace(METRICS, gpus=[a, b])
        self.assertEqual(reading("gpu.usage", metrics, "pci:b").text, "80 %")
        self.assertEqual(reading("gpu.usage", replace(metrics, gpus=[b, a]), "pci:b").text, "80 %")
        value = reading("gpu.usage", replace(metrics, gpus=[a]), "pci:b")
        self.assertFalse(value.available)
        self.assertEqual(value.text, "N/D")

    def test_missing_sensors_are_not_zero(self):
        for key in ("gpu.temperature", "gpu.fan_rpm", "gpu.memory_percent"):
            self.assertFalse(reading(key, METRICS).available)
        self.assertFalse(reading("cpu.temperature", replace(METRICS, temperature=None)).available)

    def test_per_thread_usage_and_physical_cores_are_distinct(self):
        data = replace(METRICS, cores=12, threads=24, per_core=[30, 90])
        self.assertEqual(reading("cpu.core.1", data).text, "90 %")
        self.assertEqual(reading("cpu.cores", data).text, "12")
        self.assertEqual(reading("cpu.threads", data).text, "24")
        self.assertFalse(reading("cpu.core.24", data).available)

    def test_all_catalog_entries_produce_a_reading(self):
        for key in CATALOG:
            self.assertIsInstance(reading(key, METRICS).text, str)
