import tkinter as tk
from tkinter import ttk, simpledialog, messagebox, filedialog
from math import sqrt
import json

# Shapely 관련 import
from shapely.geometry import Polygon, LineString
from shapely.ops import unary_union, polygonize


class RectShape:
    """하나의 직사각형 도형 + 치수 정보를 관리하는 클래스"""
    def __init__(self, shape_id, coords, rect_id, side_ids, dim_items,
                 editable=True, color="black"):
        self.shape_id = shape_id
        self.coords = coords          # (x1, y1, x2, y2)
        self.rect_id = rect_id        # canvas rectangle id
        self.side_ids = side_ids      # {"top": line_id, ...}
        self.dim_items = dim_items    # {"top": {...}, "left": {...}}
        self.editable = editable
        self.color = color
        self.snap_highlight_sides = set()  # 스냅으로 강조된 변 이름들


class RectCanvas:
    """팔레트 하나(캔버스)와 그 안의 모든 도형/동작을 관리하는 클래스"""

    def __init__(self, parent, app, width=900, height=600):
        self.app = app
        self.canvas = tk.Canvas(parent, bg="white", width=width, height=height)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        # 상태
        self.shapes = []
        self.next_shape_id = 1

        self.scale = 20.0  # 1m = 20px
        self.unit = "m"

        # 변 드래그
        self.active_shape = None
        self.active_side_name = None
        self.drag_start_mouse_pos = None
        self.drag_start_coords = None

        # 도형 이동(모서리)
        self.corner_snap_tolerance = 8
        self.corner_highlight_id = None
        self.corner_hover_shape = None
        self.corner_hover_index = None
        self.moving_shape = None
        self.move_start_mouse_pos = None
        self.move_start_shape_coords = None

        # 하이라이트 / 툴팁
        self.highlight_line_id = None
        self.tooltip_id = None

        # 패닝
        self.panning = False
        self.pan_last_pos = None

        # 스냅
        self.snap_tolerance = 8

        # Undo
        self.history = []

        # 코너 삭제용 팝업 메뉴
        self.corner_menu = tk.Menu(self.canvas, tearoff=0)
        self.corner_menu.add_command(label="삭제하기",
                                     command=self.delete_corner_shape)
        self.corner_menu_target_shape = None

        # 자동생성 공간 라벨
        # 각 원소: {"polygon": shapely Polygon,
        #           "name_id":..., "heat_norm_id":..., "heat_equip_id":..., "area_id":...}
        self.generated_space_labels = []

        # 이벤트 바인딩
        self.canvas.bind("<Motion>", self.on_mouse_move)
        self.canvas.bind("<ButtonPress-1>", self.on_left_down)
        self.canvas.bind("<B1-Motion>", self.on_left_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_left_up)

        self.canvas.bind("<ButtonPress-3>", self.on_right_click)

        self.canvas.bind("<MouseWheel>", self.on_mouse_wheel)
        self.canvas.bind("<Button-4>", self.on_mouse_wheel_linux)
        self.canvas.bind("<Button-5>", self.on_mouse_wheel_linux)

        self.canvas.bind("<ButtonPress-2>", self.on_middle_button_down)
        self.canvas.bind("<B2-Motion>", self.on_middle_button_drag)
        self.canvas.bind("<ButtonRelease-2>", self.on_middle_button_up)

        self.canvas.tag_bind("dim_width", "<Button-1>", self.on_dim_width_click)
        self.canvas.tag_bind("dim_height", "<Button-1>", self.on_dim_height_click)

        # 자동생성 텍스트 클릭(편집)
        self.canvas.tag_bind("space_name", "<Button-1>", self.on_space_name_click)
        self.canvas.tag_bind("space_heat_norm", "<Button-1>", self.on_space_heat_norm_click)
        self.canvas.tag_bind("space_heat_equip", "<Button-1>", self.on_space_heat_equip_click)

    # -------- 기본 유틸 --------

    def pixel_to_meter(self, length_px: float) -> float:
        return length_px / self.scale

    def meter_to_pixel(self, length_m: float) -> float:
        return length_m * self.scale

    def push_history(self):
        snapshot = {
            "scale": self.scale,
            "next_shape_id": self.next_shape_id,
            "shapes": [],
            "generated_space_labels": []
        }
        for s in self.shapes:
            snapshot["shapes"].append({
                "shape_id": s.shape_id,
                "coords": tuple(s.coords),
                "editable": s.editable,
                "color": s.color
            })

        # 자동생성 라벨 저장
        for lab in self.generated_space_labels:
            name_bbox = self.canvas.bbox(lab["name_id"])
            heat_norm_bbox = self.canvas.bbox(lab["heat_norm_id"])
            heat_equip_bbox = self.canvas.bbox(lab["heat_equip_id"])
            area_bbox = self.canvas.bbox(lab["area_id"])
            snapshot["generated_space_labels"].append({
                "polygon_coords": list(lab["polygon"].exterior.coords),
                "name_text": self.canvas.itemcget(lab["name_id"], "text"),
                "heat_norm_text": self.canvas.itemcget(lab["heat_norm_id"], "text"),
                "heat_equip_text": self.canvas.itemcget(lab["heat_equip_id"], "text"),
                "area_text": self.canvas.itemcget(lab["area_id"], "text"),
                "name_pos": name_bbox,
                "heat_norm_pos": heat_norm_bbox,
                "heat_equip_pos": heat_equip_bbox,
                "area_pos": area_bbox,
            })

        self.history.append(snapshot)

    def undo(self):
        if not self.history:
            return

        snapshot = self.history.pop()
        self.canvas.delete("all")
        self.shapes.clear()
        self.generated_space_labels.clear()
        self.highlight_line_id = None
        self.tooltip_id = None
        self.corner_highlight_id = None

        self.scale = snapshot["scale"]
        self.next_shape_id = snapshot["next_shape_id"]

        # 도형 복원
        for info in snapshot["shapes"]:
            s = self.create_rect_shape(
                info["coords"][0], info["coords"][1],
                info["coords"][2], info["coords"][3],
                editable=info["editable"],
                color=info["color"],
                push_to_history=False
            )
            s.shape_id = info["shape_id"]

        # 공간 라벨 복원
        for lab in snapshot["generated_space_labels"]:
            poly = Polygon(lab["polygon_coords"])
            if not lab["name_pos"]:
                continue

            x1, y1, x2, y2 = lab["name_pos"]
            name_id = self.canvas.create_text(
                (x1 + x2) / 2, (y1 + y2) / 2,
                text=lab["name_text"], fill="blue", font=("Arial", 11, "bold"),
                tags=("space_name",)
            )

            hx1, hy1, hx2, hy2 = lab["heat_norm_pos"]
            heat_norm_id = self.canvas.create_text(
                (hx1 + hx2) / 2, (hy1 + hy2) / 2,
                text=lab["heat_norm_text"], fill="darkred", font=("Arial", 10),
                tags=("space_heat_norm",)
            )

            ex1, ey1, ex2, ey2 = lab["heat_equip_pos"]
            heat_equip_id = self.canvas.create_text(
                (ex1 + ex2) / 2, (ey1 + ey2) / 2,
                text=lab["heat_equip_text"], fill="darkred", font=("Arial", 10),
                tags=("space_heat_equip",)
            )

            ax1, ay1, ax2, ay2 = lab["area_pos"]
            area_id = self.canvas.create_text(
                (ax1 + ax2) / 2, (ay1 + ay2) / 2,
                text=lab["area_text"], fill="green", font=("Arial", 10)
            )

            self.generated_space_labels.append({
                "polygon": poly,
                "name_id": name_id,
                "heat_norm_id": heat_norm_id,
                "heat_equip_id": heat_equip_id,
                "area_id": area_id
            })

        # 태그 바인딩 복원
        self.canvas.tag_bind("dim_width", "<Button-1>", self.on_dim_width_click)
        self.canvas.tag_bind("dim_height", "<Button-1>", self.on_dim_height_click)
        self.canvas.tag_bind("space_name", "<Button-1>", self.on_space_name_click)
        self.canvas.tag_bind("space_heat_norm", "<Button-1>", self.on_space_heat_norm_click)
        self.canvas.tag_bind("space_heat_equip", "<Button-1>", self.on_space_heat_equip_click)

        self.active_shape = None
        self.active_side_name = None
        self.app.update_selected_area_label(self)

    # -------- 도형 생성/그리기 --------

    def draw_square_from_area(self, area: float):
        if area <= 0:
            return

        self.push_history()

        side_m = sqrt(area)
        side_px = self.meter_to_pixel(side_m)

        cw = int(self.canvas["width"])
        ch = int(self.canvas["height"])

        x1 = cw / 2 - side_px / 2
        y1 = ch / 2 - side_px / 2
        x2 = cw / 2 + side_px / 2
        y2 = ch / 2 + side_px / 2

        shape = self.create_rect_shape(x1, y1, x2, y2, editable=True, color="black",
                                       push_to_history=False)
        self.set_active_shape(shape)

    def create_rect_shape(self, x1, y1, x2, y2,
                          editable=True, color="black",
                          push_to_history=True):
        if x2 < x1:
            x1, x2 = x2, x1
        if y2 < y1:
            y1, y2 = y2, y1

        shape_id = self.next_shape_id
        self.next_shape_id += 1

        rect_id = self.canvas.create_rectangle(
            x1, y1, x2, y2,
            outline=color,
            width=2,
            dash=() if color == "black" else (3, 2)
        )

        top_id = self.canvas.create_line(x1, y1, x2, y1, fill=color, width=3)
        bottom_id = self.canvas.create_line(x1, y2, x2, y2, fill=color, width=3)
        left_id = self.canvas.create_line(x1, y1, x1, y2, fill=color, width=3)
        right_id = self.canvas.create_line(x2, y1, x2, y2, fill=color, width=3)

        side_ids = {"top": top_id, "bottom": bottom_id,
                    "left": left_id, "right": right_id}
        for side_name, lid in side_ids.items():
            self.canvas.addtag_withtag(f"shape_{shape_id}", lid)
            self.canvas.addtag_withtag(f"side_{shape_id}_{side_name}", lid)

        dim_items = self.draw_dimensions_for_shape(shape_id, x1, y1, x2, y2, color=color)

        shape = RectShape(shape_id, (x1, y1, x2, y2),
                          rect_id, side_ids, dim_items,
                          editable=editable, color=color)

        self.shapes.append(shape)
        self.bring_shape_to_front(shape)
        return shape

    def bring_shape_to_front(self, shape: RectShape):
        ids = [shape.rect_id]
        ids.extend(shape.side_ids.values())
        for part in shape.dim_items.values():
            ids.extend(part["lines"])
            ids.extend(part["ticks"])
            ids.append(part["text"])
        for item_id in ids:
            if item_id in self.canvas.find_all():
                self.canvas.tag_raise(item_id)

    def draw_dimensions_for_shape(self, shape_id, x1, y1, x2, y2, color="black"):
        dim_items = {}
        offset = 30
        tick_len = 8
        text_offset = 4

        # 가로
        width_px = x2 - x1
        width_m = self.pixel_to_meter(width_px)
        dim_y = y1 - offset

        dim_line_top = self.canvas.create_line(x1, dim_y, x2, dim_y,
                                               fill=color, width=1)
        left_tick_top = self.canvas.create_line(
            x1, dim_y - tick_len / 2, x1, dim_y + tick_len / 2,
            fill=color, width=1)
        right_tick_top = self.canvas.create_line(
            x2, dim_y - tick_len / 2, x2, dim_y + tick_len / 2,
            fill=color, width=1)
        text_x = (x1 + x2) / 2
        text_y = dim_y - text_offset

        width_text_id = self.canvas.create_text(
            text_x, text_y,
            text=f"{width_m:.2f} {self.unit}",
            fill=color,
            font=("Arial", 10),
            tags=("dim_width", f"dim_width_{shape_id}")
        )

        dim_items["top"] = {
            "lines": [dim_line_top],
            "ticks": [left_tick_top, right_tick_top],
            "text": width_text_id
        }

        # 세로
        height_px = y2 - y1
        height_m = self.pixel_to_meter(height_px)
        dim_x = x1 - offset

        dim_line_left = self.canvas.create_line(dim_x, y1, dim_x, y2,
                                                fill=color, width=1)
        top_tick_left = self.canvas.create_line(
            dim_x - tick_len / 2, y1, dim_x + tick_len / 2, y1,
            fill=color, width=1)
        bottom_tick_left = self.canvas.create_line(
            dim_x - tick_len / 2, y2, dim_x + tick_len / 2, y2,
            fill=color, width=1)
        text_x2 = dim_x - text_offset
        text_y2 = (y1 + y2) / 2

        height_text_id = self.canvas.create_text(
            text_x2, text_y2,
            text=f"{height_m:.2f} {self.unit}",
            fill=color,
            font=("Arial", 10),
            angle=90,
            tags=("dim_height", f"dim_height_{shape_id}")
        )

        dim_items["left"] = {
            "lines": [dim_line_left],
            "ticks": [top_tick_left, bottom_tick_left],
            "text": height_text_id
        }

        for item in [dim_line_top, left_tick_top, right_tick_top,
                     dim_line_left, top_tick_left, bottom_tick_left,
                     width_text_id, height_text_id]:
            self.canvas.addtag_withtag(f"shape_{shape_id}", item)

        return dim_items

    # -------- 선택/하이라이트 --------

    def get_shape_by_id(self, shape_id):
        for s in self.shapes:
            if s.shape_id == shape_id:
                return s
        return None

    def set_active_shape(self, shape):
        self.active_shape = shape
        self.app.update_selected_area_label(self)
        if shape:
            self.bring_shape_to_front(shape)

    def find_side_under_mouse(self, x, y, tol=5):
        best_shape = None
        best_side = None
        best_dist2 = None

        for shape in reversed(self.shapes):
            x1, y1, x2, y2 = shape.coords
            candidates = []
            if x1 <= x <= x2:
                candidates.append(("top", (y - y1) ** 2, abs(y - y1)))
                candidates.append(("bottom", (y - y2) ** 2, abs(y - y2)))
            if y1 <= y <= y2:
                candidates.append(("left", (x - x1) ** 2, abs(x - x1)))
                candidates.append(("right", (x - x2) ** 2, abs(x - x2)))

            for side_name, d2, absd in candidates:
                if absd <= tol:
                    if best_dist2 is None or d2 < best_dist2:
                        best_dist2 = d2
                        best_shape = shape
                        best_side = side_name
        return best_shape, best_side

    def highlight_side(self, shape, side_name):
        if self.highlight_line_id and self.highlight_line_id in self.canvas.find_all():
            self.canvas.itemconfigure(self.highlight_line_id, width=3)
        self.highlight_line_id = None

        if not shape or not side_name:
            return

        line_id = shape.side_ids.get(side_name)
        if line_id:
            self.canvas.itemconfigure(line_id, width=4)
            self.highlight_line_id = line_id

    # -------- 모서리 감지 --------

    def clear_corner_highlight(self):
        if self.corner_highlight_id and self.corner_highlight_id in self.canvas.find_all():
            self.canvas.delete(self.corner_highlight_id)
        self.corner_highlight_id = None
        self.corner_hover_shape = None
        self.corner_hover_index = None

    def detect_corner_under_mouse(self, x, y):
        tol = self.corner_snap_tolerance
        best_shape = None
        best_index = None
        best_cx = best_cy = None
        best_d2 = None

        for shape in self.shapes:
            x1, y1, x2, y2 = shape.coords
            corners = [(x1, y1), (x2, y1), (x1, y2), (x2, y2)]
            for idx, (cx, cy) in enumerate(corners):
                dx = x - cx
                dy = y - cy
                d2 = dx * dx + dy * dy
                if abs(dx) <= tol and abs(dy) <= tol:
                    if best_d2 is None or d2 < best_d2:
                        best_d2 = d2
                        best_shape = shape
                        best_index = idx
                        best_cx, best_cy = cx, cy
        return best_shape, best_index, best_cx, best_cy

    # -------- 스냅 하이라이트 --------

    def clear_edge_snap_highlight(self, shape: RectShape):
        for side in shape.snap_highlight_sides:
            lid = shape.side_ids.get(side)
            if lid in self.canvas.find_all():
                self.canvas.itemconfigure(lid, fill=shape.color)
        shape.snap_highlight_sides.clear()

    def highlight_edge_snap(self, shape: RectShape, snapped_sides):
        self.clear_edge_snap_highlight(shape)
        for side in snapped_sides:
            lid = shape.side_ids.get(side)
            if lid in self.canvas.find_all():
                self.canvas.itemconfigure(lid, fill="orange")
                shape.snap_highlight_sides.add(side)

    # -------- 툴팁 --------

    def show_length_tooltip(self, shape, side_name, mx, my):
        x1, y1, x2, y2 = shape.coords
        if side_name in ("top", "bottom"):
            length_px = x2 - x1
        else:
            length_px = y2 - y1
        length_m = self.pixel_to_meter(length_px)
        text = f"{length_m:.2f} {self.unit}"

        if self.tooltip_id and self.tooltip_id in self.canvas.find_all():
            self.canvas.delete(self.tooltip_id)
            self.tooltip_id = None

        offset = 15
        self.tooltip_id = self.canvas.create_text(
            mx + offset, my - offset,
            text=text,
            fill="darkgreen",
            font=("Arial", 10, "bold"),
            anchor="sw"
        )

    def hide_length_tooltip(self):
        if self.tooltip_id and self.tooltip_id in self.canvas.find_all():
            self.canvas.delete(self.tooltip_id)
        self.tooltip_id = None

    # -------- 공유 변 판정 --------

    def find_shared_vertical_edges(self, shape):
        x1, y1, x2, y2 = shape.coords
        shared = {"left": False, "right": False}
        for other in self.shapes:
            if other is shape:
                continue
            ox1, oy1, ox2, oy2 = other.coords
            if abs(ox1 - x1) < 1e-6 or abs(ox2 - x1) < 1e-6:
                overlap = min(y2, oy2) - max(y1, oy1)
                if overlap > 0:
                    shared["left"] = True
            if abs(ox1 - x2) < 1e-6 or abs(ox2 - x2) < 1e-6:
                overlap = min(y2, oy2) - max(y1, oy1)
                if overlap > 0:
                    shared["right"] = True
        return shared

    def find_shared_horizontal_edges(self, shape):
        x1, y1, x2, y2 = shape.coords
        shared = {"top": False, "bottom": False}
        for other in self.shapes:
            if other is shape:
                continue
            ox1, oy1, ox2, oy2 = other.coords
            if abs(oy1 - y1) < 1e-6 or abs(oy2 - y1) < 1e-6:
                overlap = min(x2, ox2) - max(x1, ox1)
                if overlap > 0:
                    shared["top"] = True
            if abs(oy1 - y2) < 1e-6 or abs(oy2 - y2) < 1e-6:
                overlap = min(x2, ox2) - max(x1, ox1)
                if overlap > 0:
                    shared["bottom"] = True
        return shared

    # -------- 코너 팝업 삭제 --------

    def delete_corner_shape(self):
        shape = self.corner_menu_target_shape
        if not shape or not shape.editable:
            return

        self.push_history()

        self.canvas.delete(shape.rect_id)
        for lid in shape.side_ids.values():
            self.canvas.delete(lid)
        for part in shape.dim_items.values():
            for lid in part["lines"] + part["ticks"] + [part["text"]]:
                self.canvas.delete(lid)

        if shape in self.shapes:
            self.shapes.remove(shape)

        if self.active_shape is shape:
            self.active_shape = None
        if self.corner_hover_shape is shape:
            self.clear_corner_highlight()

        self.app.update_selected_area_label(self)
        self.corner_menu_target_shape = None

    # -------- 마우스 이벤트 --------

    def on_mouse_move(self, event):
        if self.moving_shape:
            return

        shape, idx, cx, cy = self.detect_corner_under_mouse(event.x, event.y)
        if shape:
            if not self.corner_highlight_id or self.corner_highlight_id not in self.canvas.find_all():
                r = 4
                self.corner_highlight_id = self.canvas.create_oval(
                    cx - r, cy - r, cx + r, cy + r,
                    fill="red", outline=""
                )
            else:
                r = 4
                self.canvas.coords(self.corner_highlight_id,
                                   cx - r, cy - r, cx + r, cy + r)
            self.corner_hover_shape = shape
            self.corner_hover_index = idx
        else:
            self.clear_corner_highlight()

        if self.active_side_name is None and not self.corner_hover_shape:
            s, side = self.find_side_under_mouse(event.x, event.y, tol=5)
            self.highlight_side(s, side)

    def on_left_down(self, event):
        if self.corner_hover_shape is not None:
            self.push_history()
            self.moving_shape = self.corner_hover_shape
            self.move_start_mouse_pos = (event.x, event.y)
            self.move_start_shape_coords = self.moving_shape.coords
            self.set_active_shape(self.moving_shape)
            return

        shape, side = self.find_side_under_mouse(event.x, event.y, tol=5)
        if shape and side and shape.editable:
            self.push_history()
            self.set_active_shape(shape)
            self.active_side_name = side
            self.drag_start_mouse_pos = (event.x, event.y)
            self.drag_start_coords = shape.coords

    def on_left_drag(self, event):
        # 도형 전체 이동
        if self.moving_shape and self.move_start_mouse_pos and self.move_start_shape_coords:
            dx = event.x - self.move_start_mouse_pos[0]
            dy = event.y - self.move_start_mouse_pos[1]
            x1, y1, x2, y2 = self.move_start_shape_coords
            tentative = (x1 + dx, y1 + dy, x2 + dx, y2 + dy)

            snapped_sides = []
            tentative2, s_left = self.apply_snap_edge(self.moving_shape, "left", tentative)
            if s_left:
                snapped_sides.append("left")
                tentative = tentative2
            tentative2, s_right = self.apply_snap_edge(self.moving_shape, "right", tentative)
            if s_right:
                snapped_sides.append("right")
                tentative = tentative2
            tentative2, s_top = self.apply_snap_edge(self.moving_shape, "top", tentative)
            if s_top:
                snapped_sides.append("top")
                tentative = tentative2
            tentative2, s_bottom = self.apply_snap_edge(self.moving_shape, "bottom", tentative)
            if s_bottom:
                snapped_sides.append("bottom")
                tentative = tentative2

            self.moving_shape.coords = tentative
            self.redraw_shape(self.moving_shape)
            self.highlight_edge_snap(self.moving_shape, snapped_sides)
            self.app.update_selected_area_label(self)
            return

        # 변 드래그
        if not self.active_shape or not self.active_side_name or not self.drag_start_coords:
            return
        if not self.active_shape.editable:
            return

        x1, y1, x2, y2 = self.drag_start_coords
        dx = event.x - self.drag_start_mouse_pos[0]
        dy = event.y - self.drag_start_mouse_pos[1]
        min_size_px = 20
        side = self.active_side_name

        if side == "top":
            new_y1 = y1 + dy
            if new_y1 > y2 - min_size_px:
                new_y1 = y2 - min_size_px
            tentative = (x1, new_y1, x2, y2)
        elif side == "bottom":
            new_y2 = y2 + dy
            if new_y2 < y1 + min_size_px:
                new_y2 = y1 + min_size_px
            tentative = (x1, y1, x2, new_y2)
        elif side == "left":
            new_x1 = x1 + dx
            if new_x1 > x2 - min_size_px:
                new_x1 = x2 - min_size_px
            tentative = (new_x1, y1, x2, y2)
        elif side == "right":
            new_x2 = x2 + dx
            if new_x2 < x1 + min_size_px:
                new_x2 = x1 + min_size_px
            tentative = (x1, y1, new_x2, y2)
        else:
            return

        snapped_coords, snapped = self.apply_snap_edge(self.active_shape, side, tentative)
        self.active_shape.coords = snapped_coords

        self.redraw_shape(self.active_shape)
        self.bring_shape_to_front(self.active_shape)
        if snapped:
            self.highlight_edge_snap(self.active_shape, [side])
        else:
            self.clear_edge_snap_highlight(self.active_shape)

        self.highlight_side(self.active_shape, side)
        self.show_length_tooltip(self.active_shape, side, event.x, event.y)
        self.app.update_selected_area_label(self)

    def on_left_up(self, event):
        if self.moving_shape:
            self.clear_edge_snap_highlight(self.moving_shape)
        self.moving_shape = None
        self.move_start_mouse_pos = None
        self.move_start_shape_coords = None

        if self.active_shape:
            self.clear_edge_snap_highlight(self.active_shape)
        self.active_side_name = None
        self.drag_start_mouse_pos = None
        self.drag_start_coords = None
        self.hide_length_tooltip()

    # -------- 스냅 --------

    def apply_snap_edge(self, shape, side, coords):
        x1, y1, x2, y2 = coords
        snap = self.snap_tolerance

        candidate_positions = []
        for other in self.shapes:
            if other is shape:
                continue
            ox1, oy1, ox2, oy2 = other.coords
            if side in ("top", "bottom"):
                candidate_positions.extend([oy1, oy2])
            else:
                candidate_positions.extend([ox1, ox2])

        if not candidate_positions:
            return coords, False

        snapped = False
        if side in ("top", "bottom"):
            cur_y = y1 if side == "top" else y2
            best_y = cur_y
            best_diff = None
            for py in candidate_positions:
                diff = abs(py - cur_y)
                if diff <= snap and (best_diff is None or diff < best_diff):
                    best_diff = diff
                    best_y = py
            if best_diff is not None:
                snapped = True
                if side == "top":
                    y1 = best_y
                else:
                    y2 = best_y
        else:
            cur_x = x1 if side == "left" else x2
            best_x = cur_x
            best_diff = None
            for px in candidate_positions:
                diff = abs(px - cur_x)
                if diff <= snap and (best_diff is None or diff < best_diff):
                    best_diff = diff
                    best_x = px
            if best_diff is not None:
                snapped = True
                if side == "left":
                    x1 = best_x
                else:
                    x2 = best_x

        return (x1, y1, x2, y2), snapped

    # -------- 다시 그리기 --------

    def redraw_shape(self, shape):
        self.canvas.delete(shape.rect_id)
        for lid in shape.side_ids.values():
            self.canvas.delete(lid)
        for part in shape.dim_items.values():
            for lid in part["lines"] + part["ticks"] + [part["text"]]:
                self.canvas.delete(lid)

        x1, y1, x2, y2 = shape.coords
        color = shape.color

        rect_id = self.canvas.create_rectangle(
            x1, y1, x2, y2,
            outline=color,
            width=2,
            dash=() if color == "black" else (3, 2)
        )
        top_id = self.canvas.create_line(x1, y1, x2, y1, fill=color, width=3)
        bottom_id = self.canvas.create_line(x1, y2, x2, y2, fill=color, width=3)
        left_id = self.canvas.create_line(x1, y1, x1, y2, fill=color, width=3)
        right_id = self.canvas.create_line(x2, y1, x2, y2, fill=color, width=3)
        side_ids = {"top": top_id, "bottom": bottom_id, "left": left_id, "right": right_id}

        for side_name, lid in side_ids.items():
            self.canvas.addtag_withtag(f"shape_{shape.shape_id}", lid)
            self.canvas.addtag_withtag(f"side_{shape.shape_id}_{side_name}", lid)

        dim_items = self.draw_dimensions_for_shape(shape.shape_id, x1, y1, x2, y2, color=color)

        shape.rect_id = rect_id
        shape.side_ids = side_ids
        shape.dim_items = dim_items

        self.bring_shape_to_front(shape)

    # -------- 치수 클릭 (공유벽 고정 규칙 포함) --------

    def on_dim_width_click(self, event):
        closest_id = event.widget.find_closest(event.x, event.y)[0]
        tags = self.canvas.gettags(closest_id)
        shape_id = None
        for t in tags:
            if t.startswith("dim_width_"):
                shape_id = int(t.split("_")[2])
                break
        if shape_id is None:
            return
        shape = self.get_shape_by_id(shape_id)
        if not shape or not shape.editable:
            return

        x1, y1, x2, y2 = shape.coords
        cur_w_m = self.pixel_to_meter(x2 - x1)

        new_w_m = simpledialog.askfloat(
            "가로 길이 변경",
            f"새 가로 길이({self.unit})를 입력하세요 (현재: {cur_w_m:.2f} {self.unit}):",
            minvalue=0.01
        )
        if new_w_m is None:
            return

        shared = self.find_shared_vertical_edges(shape)
        shared_count = sum(1 for k in ("left", "right") if shared[k])

        if shared_count > 1:
            messagebox.showwarning(
                "변경 불가",
                "좌우 변이 모두 다른 도형과 공유되고 있어 가로 길이를 변경할 수 없습니다."
            )
            return

        self.push_history()
        self.set_active_shape(shape)

        new_w_px = self.meter_to_pixel(new_w_m)
        new_x1 = x1
        new_x2 = x2

        if shared_count == 1:
            if shared["left"]:
                new_x1 = x1
                new_x2 = x1 + new_w_px
            else:
                new_x2 = x2
                new_x1 = x2 - new_w_px
        else:
            new_x1 = x1
            new_x2 = x1 + new_w_px

        min_size_px = 20
        if new_x2 - new_x1 < min_size_px:
            if shared_count == 1 and shared["right"]:
                new_x1 = new_x2 - min_size_px
            else:
                new_x2 = new_x1 + min_size_px

        shape.coords = (new_x1, y1, new_x2, y2)
        self.redraw_shape(shape)
        self.app.update_selected_area_label(self)

    def on_dim_height_click(self, event):
        closest_id = event.widget.find_closest(event.x, event.y)[0]
        tags = self.canvas.gettags(closest_id)
        shape_id = None
        for t in tags:
            if t.startswith("dim_height_"):
                shape_id = int(t.split("_")[2])
                break
        if shape_id is None:
            return
        shape = self.get_shape_by_id(shape_id)
        if not shape or not shape.editable:
            return

        x1, y1, x2, y2 = shape.coords
        cur_h_m = self.pixel_to_meter(y2 - y1)

        new_h_m = simpledialog.askfloat(
            "세로 길이 변경",
            f"새 세로 길이({self.unit})를 입력하세요 (현재: {cur_h_m:.2f} {self.unit}):",
            minvalue=0.01
        )
        if new_h_m is None:
            return

        shared = self.find_shared_horizontal_edges(shape)
        shared_count = sum(1 for k in ("top", "bottom") if shared[k])

        if shared_count > 1:
            messagebox.showwarning(
                "변경 불가",
                "위·아래 변이 모두 다른 도형과 공유되고 있어 세로 길이를 변경할 수 없습니다."
            )
            return

        self.push_history()
        self.set_active_shape(shape)

        new_h_px = self.meter_to_pixel(new_h_m)
        new_y1 = y1
        new_y2 = y2

        if shared_count == 1:
            if shared["top"]:
                new_y1 = y1
                new_y2 = y1 + new_h_px
            else:
                new_y2 = y2
                new_y1 = y2 - new_h_px
        else:
            new_y1 = y1
            new_y2 = y1 + new_h_px

        min_size_px = 20
        if new_y2 - new_y1 < min_size_px:
            if shared_count == 1 and shared["bottom"]:
                new_y1 = new_y2 - min_size_px
            else:
                new_y2 = new_y1 + min_size_px

        shape.coords = (x1, new_y1, x2, new_y2)
        self.redraw_shape(shape)
        self.app.update_selected_area_label(self)

    # -------- 공간 텍스트 수정 --------

    def _find_space_label_by_item(self, item_id):
        for lab in self.generated_space_labels:
            if item_id in (
                lab["name_id"],
                lab["heat_norm_id"],
                lab["heat_equip_id"],
                lab["area_id"],
            ):
                return lab
        return None

    def on_space_name_click(self, event):
        item_id = event.widget.find_closest(event.x, event.y)[0]
        lab = self._find_space_label_by_item(item_id)
        if not lab:
            return
        old = self.canvas.itemcget(lab["name_id"], "text")
        new = simpledialog.askstring("공간 이름 변경", "새로운 공간 이름:", initialvalue=old)
        if not new:
            return
        self.push_history()
        self.canvas.itemconfigure(lab["name_id"], text=new.strip())

    def on_space_heat_norm_click(self, event):
        item_id = event.widget.find_closest(event.x, event.y)[0]
        lab = self._find_space_label_by_item(item_id)
        if not lab:
            return
        old_text = self.canvas.itemcget(lab["heat_norm_id"], "text")
        try:
            num_str = old_text.split(":")[1].replace("kW/m²", "").strip()
            old_val = float(num_str)
        except Exception:
            old_val = 0.0
        new_val = simpledialog.askfloat(
            "일반 발열량 변경",
            "새 일반 발열량 (kW/m²)을 입력하세요:",
            initialvalue=old_val,
            minvalue=0.0
        )
        if new_val is None:
            return
        self.push_history()
        self.canvas.itemconfigure(
            lab["heat_norm_id"],
            text=f"Norm: {new_val:.2f} kW/m²"
        )

    def on_space_heat_equip_click(self, event):
        item_id = event.widget.find_closest(event.x, event.y)[0]
        lab = self._find_space_label_by_item(item_id)
        if not lab:
            return
        old_text = self.canvas.itemcget(lab["heat_equip_id"], "text")
        try:
            num_str = old_text.split(":")[1].replace("kW/m²", "").strip()
            old_val = float(num_str)
        except Exception:
            old_val = 0.0
        new_val = simpledialog.askfloat(
            "장비 발열량 변경",
            "새 장비 발열량 (kW/m²)을 입력하세요:",
            initialvalue=old_val,
            minvalue=0.0
        )
        if new_val is None:
            return
        self.push_history()
        self.canvas.itemconfigure(
            lab["heat_equip_id"],
            text=f"Equip: {new_val:.2f} kW/m²"
        )

    # -------- 오른쪽 클릭 --------

    def on_right_click(self, event):
        px, py = event.x, event.y
        shape, idx, cx, cy = self.detect_corner_under_mouse(px, py)
        if shape is not None:
            self.corner_menu_target_shape = shape
            try:
                self.corner_menu.tk_popup(event.x_root, event.y_root)
            finally:
                self.corner_menu.grab_release()
            return

        if not self.shapes:
            return

        best_corner = None
        best_d2 = None
        for shape in self.shapes:
            x1, y1, x2, y2 = shape.coords
            corners = [(x1, y1), (x2, y1), (x1, y2), (x2, y2)]
            for cx, cy in corners:
                d2 = (cx - px) ** 2 + (cy - py) ** 2
                if best_d2 is None or d2 < best_d2:
                    best_d2 = d2
                    best_corner = (cx, cy)

        if best_corner is None:
            return

        self.push_history()
        cx, cy = best_corner
        new_shape = self.create_rect_shape(cx, cy, px, py, editable=True, color="blue",
                                           push_to_history=False)
        self.set_active_shape(new_shape)

    # -------- Shapely 기반 자동 공간 생성 (텍스트 유지/새로 생성 규칙) --------

    def auto_generate_space_labels(self):
        if not self.shapes:
            messagebox.showinfo("자동생성", "도형이 없습니다.")
            return

        # 1. 모든 사각형의 경계선을 LineString으로 모음
        lines = []
        for s in self.shapes:
            x1, y1, x2, y2 = s.coords
            lines.append(LineString([[x1, y1], [x2, y1]]))
            lines.append(LineString([[x2, y1], [x2, y2]]))
            lines.append(LineString([[x2, y2], [x1, y2]]))
            lines.append(LineString([[x1, y2], [x1, y1]]))

        merged = unary_union(lines)
        polys = list(polygonize(merged))

        if not polys:
            messagebox.showinfo("자동생성", "밀폐된 공간을 찾지 못했습니다.")
            return

        valid_polys = []
        for p in polys:
            area_px2 = p.area
            area_m2 = area_px2 / (self.scale * self.scale)
            if area_m2 > 0.01:
                valid_polys.append((p, area_m2))

        if not valid_polys:
            messagebox.showinfo("자동생성", "유효한 공간이 없습니다.")
            return

        self.push_history()

        # 면적 기준 정렬
        valid_polys.sort(key=lambda x: x[1])

        # 기존 라벨의 중심점 목록
        existing_centers = []
        for lab in self.generated_space_labels:
            poly_old = lab["polygon"]
            rep_old = poly_old.representative_point()
            existing_centers.append((lab, rep_old.x, rep_old.y))

        used_existing = []   # dict는 set에 넣을 수 없으므로 리스트로 관리
        new_labels = []

        # 현재까지 사용된 Room 번호 최대값 계산
        max_room_index = 0
        for lab in self.generated_space_labels:
            name_text = self.canvas.itemcget(lab["name_id"], "text")
            if name_text.lower().startswith("room"):
                try:
                    idx = int(name_text.split()[1])
                    if idx > max_room_index:
                        max_room_index = idx
                except Exception:
                    pass

        next_room_index = max_room_index + 1 if max_room_index > 0 else 1

        for p, area_m2 in valid_polys:
            rep = p.representative_point()
            cx, cy = rep.x, rep.y

            matched = None
            min_dist2 = None

            for lab, ex, ey in existing_centers:
                if lab in used_existing:
                    continue
                dx = cx - ex
                dy = cy - ey
                d2 = dx*dx + dy*dy
                if min_dist2 is None or d2 < min_dist2:
                    min_dist2 = d2
                    matched = lab

            # 매칭 허용 거리: 5px 반경
            if matched is not None and min_dist2 < (5 * 5):
                # 기존 라벨 유지, 면적만 갱신
                name_id = matched["name_id"]
                heat_norm_id = matched["heat_norm_id"]
                heat_equip_id = matched["heat_equip_id"]
                area_id = matched["area_id"]

                self.canvas.itemconfigure(area_id, text=f"{area_m2:.2f} m²")

                new_labels.append({
                    "polygon": p,
                    "name_id": name_id,
                    "heat_norm_id": heat_norm_id,
                    "heat_equip_id": heat_equip_id,
                    "area_id": area_id
                })
                used_existing.append(matched)
            else:
                # 새 공간 → 새 Room 번호 부여
                name_text = f"Room {next_room_index}"
                next_room_index += 1

                heat_norm_text = "Norm: 0.00 kW/m²"
                heat_equip_text = "Equip: 0.00 kW/m²"
                area_text = f"{area_m2:.2f} m²"

                name_id = self.canvas.create_text(
                    cx, cy,
                    text=name_text,
                    fill="blue",
                    font=("Arial", 11, "bold"),
                    tags=("space_name",)
                )
                heat_norm_id = self.canvas.create_text(
                    cx, cy + 14,
                    text=heat_norm_text,
                    fill="darkred",
                    font=("Arial", 10),
                    tags=("space_heat_norm",)
                )
                heat_equip_id = self.canvas.create_text(
                    cx, cy + 28,
                    text=heat_equip_text,
                    fill="darkred",
                    font=("Arial", 10),
                    tags=("space_heat_equip",)
                )
                area_id = self.canvas.create_text(
                    cx, cy + 42,
                    text=area_text,
                    fill="green",
                    font=("Arial", 10)
                )

                new_labels.append({
                    "polygon": p,
                    "name_id": name_id,
                    "heat_norm_id": heat_norm_id,
                    "heat_equip_id": heat_equip_id,
                    "area_id": area_id
                })

        # 기존 라벨 중 사용되지 않은 것 삭제
        for lab in self.generated_space_labels:
            if lab not in used_existing:
                self.canvas.delete(lab["name_id"])
                self.canvas.delete(lab["heat_norm_id"])
                self.canvas.delete(lab["heat_equip_id"])
                self.canvas.delete(lab["area_id"])

        self.generated_space_labels = new_labels

    # -------- 저장/불러오기용 직렬화 --------

    def to_dict(self):
        """현재 RectCanvas 상태를 JSON 직렬화용 dict로 반환"""
        data = {
            "scale": self.scale,
            "shapes": [],
            "labels": []
        }
        for s in self.shapes:
            data["shapes"].append({
                "coords": list(s.coords),
                "editable": s.editable,
                "color": s.color
            })

        for lab in self.generated_space_labels:
            # 텍스트와 위치
            name_x, name_y = self.canvas.coords(lab["name_id"])
            norm_x, norm_y = self.canvas.coords(lab["heat_norm_id"])
            equip_x, equip_y = self.canvas.coords(lab["heat_equip_id"])
            area_x, area_y = self.canvas.coords(lab["area_id"])
            data["labels"].append({
                "polygon_coords": list(lab["polygon"].exterior.coords),
                "name_text": self.canvas.itemcget(lab["name_id"], "text"),
                "heat_norm_text": self.canvas.itemcget(lab["heat_norm_id"], "text"),
                "heat_equip_text": self.canvas.itemcget(lab["heat_equip_id"], "text"),
                "area_text": self.canvas.itemcget(lab["area_id"], "text"),
                "name_pos": [name_x, name_y],
                "heat_norm_pos": [norm_x, norm_y],
                "heat_equip_pos": [equip_x, equip_y],
                "area_pos": [area_x, area_y],
            })
        return data

    def load_from_dict(self, data: dict):
        """JSON dict로부터 RectCanvas 상태 복원"""
        self.canvas.delete("all")
        self.shapes.clear()
        self.generated_space_labels.clear()
        self.highlight_line_id = None
        self.tooltip_id = None
        self.corner_highlight_id = None

        self.scale = data.get("scale", 20.0)
        self.next_shape_id = 1

        # 도형 복원
        for info in data.get("shapes", []):
            coords = info.get("coords", [0, 0, 0, 0])
            editable = info.get("editable", True)
            color = info.get("color", "black")
            s = self.create_rect_shape(
                coords[0], coords[1], coords[2], coords[3],
                editable=editable, color=color, push_to_history=False
            )

        # 라벨 복원
        for lab in data.get("labels", []):
            poly = Polygon(lab["polygon_coords"])

            name_x, name_y = lab["name_pos"]
            norm_x, norm_y = lab["heat_norm_pos"]
            equip_x, equip_y = lab["heat_equip_pos"]
            area_x, area_y = lab["area_pos"]

            name_id = self.canvas.create_text(
                name_x, name_y,
                text=lab["name_text"], fill="blue", font=("Arial", 11, "bold"),
                tags=("space_name",)
            )
            heat_norm_id = self.canvas.create_text(
                norm_x, norm_y,
                text=lab["heat_norm_text"], fill="darkred", font=("Arial", 10),
                tags=("space_heat_norm",)
            )
            heat_equip_id = self.canvas.create_text(
                equip_x, equip_y,
                text=lab["heat_equip_text"], fill="darkred", font=("Arial", 10),
                tags=("space_heat_equip",)
            )
            area_id = self.canvas.create_text(
                area_x, area_y,
                text=lab["area_text"], fill="green", font=("Arial", 10)
            )

            self.generated_space_labels.append({
                "polygon": poly,
                "name_id": name_id,
                "heat_norm_id": heat_norm_id,
                "heat_equip_id": heat_equip_id,
                "area_id": area_id
            })

        # 태그 바인딩 복원
        self.canvas.tag_bind("dim_width", "<Button-1>", self.on_dim_width_click)
        self.canvas.tag_bind("dim_height", "<Button-1>", self.on_dim_height_click)
        self.canvas.tag_bind("space_name", "<Button-1>", self.on_space_name_click)
        self.canvas.tag_bind("space_heat_norm", "<Button-1>", self.on_space_heat_norm_click)
        self.canvas.tag_bind("space_heat_equip", "<Button-1>", self.on_space_heat_equip_click)

        self.active_shape = None
        self.active_side_name = None
        self.app.update_selected_area_label(self)

    # -------- 줌 / 팬 --------

    def on_mouse_wheel(self, event):
        zoom_in = event.delta > 0
        self.apply_zoom(zoom_in, event.x, event.y)

    def on_mouse_wheel_linux(self, event):
        zoom_in = (event.num == 4)
        self.apply_zoom(zoom_in, event.x, event.y)

    def apply_zoom(self, zoom_in, cx, cy):
        factor = 1.1 if zoom_in else 1 / 1.1
        new_scale = self.scale * factor
        if new_scale < 2.0 or new_scale > 200.0:
            return

        self.push_history()

        self.canvas.scale("all", cx, cy, factor, factor)
        for shape in self.shapes:
            x1, y1, x2, y2 = shape.coords
            x1 = cx + (x1 - cx) * factor
            y1 = cy + (y1 - cy) * factor
            x2 = cx + (x2 - cx) * factor
            y2 = cy + (y2 - cy) * factor
            shape.coords = (x1, y1, x2, y2)

        self.scale = new_scale
        self.app.update_selected_area_label(self)

    def on_middle_button_down(self, event):
        self.push_history()
        self.panning = True
        self.pan_last_pos = (event.x, event.y)

    def on_middle_button_drag(self, event):
        if not self.panning or self.pan_last_pos is None:
            return
        last_x, last_y = self.pan_last_pos
        dx = event.x - last_x
        dy = event.y - last_y

        self.canvas.move("all", dx, dy)
        for shape in self.shapes:
            x1, y1, x2, y2 = shape.coords
            shape.coords = (x1 + dx, y1 + dy, x2 + dx, y2 + dy)
        self.pan_last_pos = (event.x, event.y)

    def on_middle_button_up(self, event):
        self.panning = False
        self.pan_last_pos = None


# ================= 상위 App =================

class ResizableRectApp:
    def __init__(self, root):
        self.root = root
        self.root.title("도형 편집기 (여러 탭, 도형 편집기)")

        top_frame = tk.Frame(root)
        top_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=5)

        tk.Label(top_frame, text="면적 (m²):").pack(side=tk.LEFT)
        self.area_entry = tk.Entry(top_frame, width=10)
        self.area_entry.pack(side=tk.LEFT, padx=5)

        draw_btn = tk.Button(top_frame, text="정사각형 그리기",
                             command=self.draw_square_from_area_current)
        draw_btn.pack(side=tk.LEFT, padx=5)

        self.area_entry.bind("<Return>", lambda e: self.draw_square_from_area_current())

        self.area_label_var = tk.StringVar()
        self.area_label_var.set("선택 도형 면적: - m²")
        area_label = tk.Label(top_frame, textvariable=self.area_label_var, fg="blue")
        area_label.pack(side=tk.LEFT, padx=20)

        undo_btn = tk.Button(top_frame, text="되돌리기 (Ctrl+Z)",
                             command=self.undo_current)
        undo_btn.pack(side=tk.LEFT, padx=10)

        add_tab_btn = tk.Button(top_frame, text="팔레트 추가",
                                command=self.add_new_tab)
        add_tab_btn.pack(side=tk.LEFT, padx=10)

        delete_tab_btn = tk.Button(top_frame, text="팔레트 삭제",
                                   command=self.delete_current_tab)
        delete_tab_btn.pack(side=tk.LEFT, padx=5)

        auto_btn = tk.Button(top_frame, text="자동생성",
                             command=self.auto_generate_current)
        auto_btn.pack(side=tk.LEFT, padx=10)

        # 저장/불러오기 버튼
        save_btn = tk.Button(top_frame, text="저장하기",
                             command=self.save_current)
        save_btn.pack(side=tk.LEFT, padx=5)

        load_btn = tk.Button(top_frame, text="불러오기",
                             command=self.load_current)
        load_btn.pack(side=tk.LEFT, padx=5)

        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        self.rect_canvases = []
        self.add_new_tab()

        self.root.bind_all("<Control-z>",
                           lambda e: self.undo_current())

    def get_current_rect_canvas(self) -> RectCanvas | None:
        if not self.notebook.tabs():
            return None
        idx = self.notebook.index(self.notebook.select())
        if 0 <= idx < len(self.rect_canvases):
            return self.rect_canvases[idx]
        return None

    def add_new_tab(self):
        tab = tk.Frame(self.notebook)
        self.notebook.add(tab, text=f"팔레트 {len(self.rect_canvases)+1}")
        self.notebook.select(len(self.rect_canvases))
        rc = RectCanvas(tab, app=self)
        self.rect_canvases.append(rc)

    def delete_current_tab(self):
        if not self.rect_canvases:
            return

        current_index = self.notebook.index(self.notebook.select())
        if len(self.rect_canvases) == 1:
            messagebox.showinfo(
                "삭제 불가",
                "마지막 팔레트는 삭제할 수 없습니다.\n새 팔레트를 추가한 후 삭제해 주세요."
            )
            return

        answer = messagebox.askyesno(
            "팔레트 삭제 확인",
            "현재 선택된 팔레트를 정말로 삭제하시겠습니까?\n"
            "이 작업은 되돌릴 수 없습니다."
        )
        if not answer:
            return

        tab_id = self.notebook.tabs()[current_index]
        self.notebook.forget(tab_id)
        del self.rect_canvases[current_index]

        rc = self.get_current_rect_canvas()
        self.update_selected_area_label(rc)

    def draw_square_from_area_current(self):
        rc = self.get_current_rect_canvas()
        if not rc:
            return
        s = self.area_entry.get().strip()
        try:
            area = float(s)
        except ValueError:
            return
        rc.draw_square_from_area(area)

    def undo_current(self):
        rc = self.get_current_rect_canvas()
        if rc:
            rc.undo()

    def auto_generate_current(self):
        rc = self.get_current_rect_canvas()
        if rc:
            rc.auto_generate_space_labels()

    def save_current(self):
        rc = self.get_current_rect_canvas()
        if not rc:
            return
        file_path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON 파일", "*.json"), ("모든 파일", "*.*")]
        )
        if not file_path:
            return
        data = rc.to_dict()
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            messagebox.showinfo("저장 완료", f"현재 팔레트를 저장했습니다.\n{file_path}")
        except Exception as e:
            messagebox.showerror("저장 오류", f"파일 저장 중 오류가 발생했습니다.\n{e}")

    def load_current(self):
        rc = self.get_current_rect_canvas()
        if not rc:
            return
        file_path = filedialog.askopenfilename(
            defaultextension=".json",
            filetypes=[("JSON 파일", "*.json"), ("모든 파일", "*.*")]
        )
        if not file_path:
            return
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            rc.load_from_dict(data)
            messagebox.showinfo("불러오기 완료", f"팔레트를 불러왔습니다.\n{file_path}")
        except Exception as e:
            messagebox.showerror("불러오기 오류", f"파일 불러오기 중 오류가 발생했습니다.\n{e}")

    def update_selected_area_label(self, rc: RectCanvas | None):
        if not rc or not rc.active_shape:
            self.area_label_var.set("선택 도형 면적: - m²")
            return
        x1, y1, x2, y2 = rc.active_shape.coords
        w = rc.pixel_to_meter(x2 - x1)
        h = rc.pixel_to_meter(y2 - y1)
        self.area_label_var.set(f"선택 도형 면적: {w*h:.3f} m²")


if __name__ == "__main__":
    root = tk.Tk()
    app = ResizableRectApp(root)
    root.mainloop()
