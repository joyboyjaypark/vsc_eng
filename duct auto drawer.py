import tkinter as tk
from tkinter import messagebox, ttk, simpledialog
import math

# =========================
# 계산 함수들
# =========================

def calc_circular_diameter(q_m3h: float, dp_mmAq_per_m: float) -> float:
    """등가 원형 덕트 직경 D1 (mm) 계산"""
    if q_m3h <= 0:
        raise ValueError("풍량(m³/h)은 0보다 커야 합니다.")
    if dp_mmAq_per_m <= 0:
        raise ValueError("정압값(mmAq/m)은 0보다 커야 합니다.")

    C = 3.295e-10  # 경험식 상수
    D = ((C * q_m3h**1.9 / dp_mmAq_per_m)**0.199) * 1000  # mm
    return round(D, 0)


def round_step_up(x: float, step: float = 50) -> float:
    return math.ceil(x / step) * step


def round_step_down(x: float, step: float = 50) -> float:
    return math.floor(x / step) * step


def rect_equiv_diameter(a_mm: float, b_mm: float) -> float:
    """사각 덕트 a,b(mm)에 대한 등가 원형 직경 De(mm) (ASHRAE)"""
    if a_mm <= 0 or b_mm <= 0:
        raise ValueError("사각 덕트 변은 0보다 커야 합니다.")
    a, b = float(a_mm), float(b_mm)
    return 1.30 * (a*b)**0.625 / (a + b)**0.25


def size_rect_from_D1(D1: float, aspect_ratio: float, step: float = 50):
    """
    1번(등가원형 D1)을 기준으로:
      - 4번: 이론 사각 (조정 전) [항상 큰값, 작은값 순서]
      - 3번: 4번 기반 50mm 조정 (규칙 적용) [항상 큰값, 작은값 순서]
    """
    if D1 <= 0:
        raise ValueError("원형 덕트 직경은 0보다 커야 합니다.")
    if aspect_ratio <= 0:
        raise ValueError("종횡비(b/a)는 0보다 커야 합니다.")

    De_target = float(D1)
    r = float(aspect_ratio)

    # --- 4번: 이론 사각 (조정 전) ---
    a_theo = De_target * (1 + r)**0.25 / (1.30 * r**0.625)
    b_theo = r * a_theo
    theo_big, theo_small = max(a_theo, b_theo), min(a_theo, b_theo)

    # --- 후보1: 작은 값 올림, 큰 값 내림 ---
    small_up = round_step_up(theo_small, step)
    big_down = max(round_step_down(theo_big, step), step)
    De1 = rect_equiv_diameter(small_up, big_down)

    # --- 후보2: 둘 다 올림 ---
    a_up = round_step_up(a_theo, step)
    b_up = round_step_up(b_theo, step)
    De2 = rect_equiv_diameter(a_up, b_up)

    # --- 최종 선택 (3번) ---
    if De1 >= De_target:
        sel_big, sel_small = max(small_up, big_down), min(small_up, big_down)
        De_sel = De1
    else:
        sel_big, sel_small = max(a_up, b_up), min(a_up, b_up)
        De_sel = De2

    return (
        int(round(sel_big)),
        int(round(sel_small)),
        round(De_sel, 1),
        round(theo_big, 1),
        round(theo_small, 1),
    )

# =========================
# 팔레트(Canvas) 관련 (모델 좌표 기반)
# =========================

GRID_STEP_MODEL = 0.5
INITIAL_SCALE = 40.0

class AirPoint:
    def __init__(self, mx, my, kind, flow):
        self.mx = mx  # model x (m)
        self.my = my  # model y (m)
        self.kind = kind  # "inlet" or "outlet"
        self.flow = flow  # m3/h
        self.canvas_id = None
        self.text_id = None


class DuctSegment:
    """종합 사이징으로 생성되는 덕트 구간 데이터(모델 좌표 기준)"""
    def __init__(self, mx1, my1, mx2, my2, label_text, duct_w_mm, duct_h_mm,
                 flow_m3h, vertical_only=False, circular_diameter_mm=0):
        self.mx1 = mx1
        self.my1 = my1
        self.mx2 = mx2
        self.my2 = my2
        self.label_text = label_text
        self.duct_w_mm = duct_w_mm
        self.duct_h_mm = duct_h_mm
        self.flow = flow_m3h
        self.vertical_only = vertical_only   # True: 순수 수직, False: 순수 수평
        self.circular_diameter_mm = circular_diameter_mm  # 원형덕트 직경
        self.line_ids = []
        self.text_id = None
        self.leader_id = None

        # 상호작용 상태
        self.is_hovered = False
        self.is_dragging = False
        self.drag_start_model = None  # (mx, my) 드래그 시작점(모델좌표)

    def length_m(self):
        dx = self.mx2 - self.mx1
        dy = self.my2 - self.my1
        return math.sqrt(dx*dx + dy*dy)


class Palette:
    def __init__(self, parent):
        self.canvas = tk.Canvas(parent, bg="white")
        self.canvas.pack(expand=True, fill="both", padx=10, pady=10)

        self.points: list[AirPoint] = []
        self.inlet_flow = 0.0

        self.scale_factor = INITIAL_SCALE
        self.offset_x = 0.0
        self.offset_y = 0.0

        self.grid_tag = "grid"
        self.pan_start_screen = None

        self.segments: list[DuctSegment] = []

        # 라인 hover/drag 상태
        self.hovered_segment: DuctSegment | None = None
        self.dragging_segment: DuctSegment | None = None

        self.canvas.bind("<Button-1>", self.on_left_click)
        self.canvas.bind("<Button-3>", self.on_right_click)
        self.canvas.bind("<MouseWheel>", self.on_mousewheel)
        self.canvas.bind("<Button-2>", self.on_middle_press)
        self.canvas.bind("<B2-Motion>", self.on_middle_drag)
        self.canvas.bind("<Configure>", self.on_resize)

        # 마우스 이동 및 왼쪽 드래그
        self.canvas.bind("<Motion>", self.on_mouse_move)
        self.canvas.bind("<B1-Motion>", self.on_left_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_left_release)

        self.redraw_all()

    # ---------- 좌표 변환 ----------

    def model_to_screen(self, mx, my):
        sx = mx * self.scale_factor + self.offset_x
        sy = my * self.scale_factor + self.offset_y
        return sx, sy

    def screen_to_model(self, sx, sy):
        mx = (sx - self.offset_x) / self.scale_factor
        my = (sy - self.offset_y) / self.scale_factor
        return mx, my

    # ---------- 격자/그리기 ----------

    def draw_grid(self):
        self.canvas.delete(self.grid_tag)

        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        if w <= 0 or h <= 0:
            return

        mx_min, my_min = self.screen_to_model(0, 0)
        mx_max, my_max = self.screen_to_model(w, h)

        x_start = math.floor(mx_min / GRID_STEP_MODEL) * GRID_STEP_MODEL
        x_end = math.ceil(mx_max / GRID_STEP_MODEL) * GRID_STEP_MODEL
        y_start = math.floor(my_min / GRID_STEP_MODEL) * GRID_STEP_MODEL
        y_end = math.ceil(my_max / GRID_STEP_MODEL) * GRID_STEP_MODEL

        x = x_start
        while x <= x_end:
            sx1, sy1 = self.model_to_screen(x, y_start)
            sx2, sy2 = self.model_to_screen(x, y_end)
            self.canvas.create_line(
                sx1, sy1, sx2, sy2,
                fill="#e0e0e0",
                tags=self.grid_tag
            )
            x += GRID_STEP_MODEL

        y = y_start
        while y <= y_end:
            sx1, sy1 = self.model_to_screen(x_start, y)
            sx2, sy2 = self.model_to_screen(x_end, y)
            self.canvas.create_line(
                sx1, sy1, sx2, sy2,
                fill="#e0e0e0",
                tags=self.grid_tag
            )
            y += GRID_STEP_MODEL

    def redraw_all(self):
        self.canvas.delete("all")
        self.draw_grid()

        # 점 + 풍량 라벨
        for p in self.points:
            sx, sy = self.model_to_screen(p.mx, p.my)
            color = "red" if p.kind == "inlet" else "blue"
            r = 5
            p.canvas_id = self.canvas.create_oval(
                sx - r, sy - r, sx + r, sy + r,
                fill=color, outline=""
            )
            label = f"{p.flow:.1f}"
            p.text_id = self.canvas.create_text(
                sx + 10, sy - 10,
                text=label,
                fill="black",
                font=("Arial", 8, "bold")
            )

        # 덕트 구간
        for seg in self.segments:
            seg.line_ids.clear()
            seg.text_id = None
            seg.leader_id = None

            mx1, my1, mx2, my2 = seg.mx1, seg.my1, seg.mx2, seg.my2
            sx1, sy1 = self.model_to_screen(mx1, my1)
            sx2, sy2 = self.model_to_screen(mx2, my2)

            # hover 시 굵게
            line_width = 3 if seg.is_hovered else 1
            line_color = "gray50"

            if seg.vertical_only:
                seg.line_ids.append(
                    self.canvas.create_line(
                        sx1, sy1, sx2, sy2,
                        fill=line_color,
                        width=line_width,
                        tags=("duct_line",)
                    )
                )
                horizontal_len = 0.0
                vertical_len = abs(my2 - my1)
            else:
                seg.line_ids.append(
                    self.canvas.create_line(
                        sx1, sy1, sx2, sy2,
                        fill=line_color,
                        width=line_width,
                        tags=("duct_line",)
                    )
                )
                horizontal_len = abs(mx2 - mx1)
                vertical_len = 0.0

            # 기준축 선택
            if vertical_len > horizontal_len:
                use_vertical = True
            else:
                use_vertical = False

            leader_length_px = 15
            text_offset_px = 5

            if use_vertical:
                # 세로 기준: 중앙점에서 수평 지시선
                mid_mx_v = mx1
                mid_my_v = (my1 + my2) / 2.0
                vx, vy = self.model_to_screen(mid_mx_v, mid_my_v)

                seg.leader_id = self.canvas.create_line(
                    vx, vy,
                    vx + leader_length_px, vy,
                    fill="blue"
                )

                tx = vx + leader_length_px + text_offset_px
                ty = vy

                # 두 줄 텍스트: 덕트 사이즈 + 풍량
                label_with_flow = f"{seg.label_text}\n{seg.flow:.0f} m³/h"
                
                seg.text_id = self.canvas.create_text(
                    tx, ty,
                    text=label_with_flow,
                    fill="blue",
                    font=("Arial", 8, "bold"),
                    anchor="w"
                )
            else:
                # 가로 기준: 중앙점에서 수직 지시선
                mid_mx_h = (mx1 + mx2) / 2.0
                mid_my_h = my1
                hx, hy = self.model_to_screen(mid_mx_h, mid_my_h)

                seg.leader_id = self.canvas.create_line(
                    hx, hy,
                    hx, hy - leader_length_px,
                    fill="blue"
                )

                tx = hx
                ty = hy - leader_length_px - text_offset_px

                # 두 줄 텍스트: 덕트 사이즈 + 풍량
                label_with_flow = f"{seg.label_text}\n{seg.flow:.0f} m³/h"
                
                seg.text_id = self.canvas.create_text(
                    tx, ty,
                    text=label_with_flow,
                    fill="blue",
                    font=("Arial", 8, "bold"),
                    anchor="s"
                )

    def on_resize(self, event):
        self.redraw_all()

    # ---------- 스냅 ----------

    def snap_model(self, mx, my):
        smx = round(mx / GRID_STEP_MODEL) * GRID_STEP_MODEL
        smy = round(my / GRID_STEP_MODEL) * GRID_STEP_MODEL
        return smx, smy

    # ---------- 팬 ----------

    def on_middle_press(self, event):
        self.pan_start_screen = (event.x, event.y)

    def on_middle_drag(self, event):
        if self.pan_start_screen is None:
            return
        sx0, sy0 = self.pan_start_screen
        dx = event.x - sx0
        dy = event.y - sy0
        self.pan_start_screen = (event.x, event.y)
        self.offset_x += dx
        self.offset_y += dy
        self.redraw_all()

    # ---------- 줌 ----------

    def on_mousewheel(self, event):
        factor = 1.1 if event.delta > 0 else 0.9
        new_scale = self.scale_factor * factor
        if not (10.0 <= new_scale <= 400.0):
            return

        sx, sy = event.x, event.y
        mx, my = self.screen_to_model(sx, sy)

        self.scale_factor = new_scale
        self.offset_x = sx - mx * self.scale_factor
        self.offset_y = sy - my * self.scale_factor

        self.redraw_all()

    # ---------- 덕트 라인 히트 테스트 ----------

    def _hit_test_segment(self, mx, my, tol=0.1):
        """
        mx,my (모델좌표)가 어떤 DuctSegment 위에 있는지 판정.
        tol: 덕트 중심선에서의 허용 거리 (모델 좌표, m).
        수직 덕트면 x만, 수평 덕트면 y만 비교.
        """
        for seg in self.segments:
            if seg.vertical_only:
                # x = 상수, y 범위
                if min(seg.my1, seg.my2) - tol <= my <= max(seg.my1, seg.my2) + tol:
                    if abs(mx - seg.mx1) <= tol:
                        return seg
            else:
                # y = 상수, x 범위
                if min(seg.mx1, seg.mx2) - tol <= mx <= max(seg.mx1, seg.mx2) + tol:
                    if abs(my - seg.my1) <= tol:
                        return seg
        return None

    # ---------- 점/풍량 ----------

    def set_inlet_flow(self, flow):
        self.inlet_flow = float(flow)
        if self.points:
            p0 = self.points[0]
            if p0.kind == "inlet":
                p0.flow = self.inlet_flow
        self.redraw_all()

    def on_left_click(self, event):
        # 먼저, 덕트 위인지 확인: 라인 위라면 점 생성 안 함
        mx, my = self.screen_to_model(event.x, event.y)
        seg = self._hit_test_segment(mx, my, tol=0.15)
        if seg is not None:
            return  # 라인 위 클릭은 점 추가하지 않음

        sx, sy = event.x, event.y
        mx, my = self.screen_to_model(sx, sy)
        mx, my = self.snap_model(mx, my)

        if not self.points:
            flow = self.inlet_flow if self.inlet_flow > 0 else 0.0
            p = AirPoint(mx, my, "inlet", flow)
            self.points.append(p)
        else:
            p = AirPoint(mx, my, "outlet", 0.0)
            self.points.append(p)

        self.segments.clear()
        self.redraw_all()

    def on_right_click(self, event):
        sx, sy = event.x, event.y
        mx, my = self.screen_to_model(sx, sy)

        target = self._find_point_near_model(mx, my, tol_model=0.3)
        if target is None:
            return

        if target.kind == "inlet":
            messagebox.showinfo("정보", "Air inlet의 풍량은 좌측 텍스트 값을 사용합니다.")
            return

        remaining = self._calc_remaining_flow(exclude=target)
        current = target.flow

        msg = (
            f"Air inlet 풍량: {self.inlet_flow:.1f} m³/h\n"
            f"다른 outlet에 분배된 풍량 합계: {self._sum_outlet_flow(exclude=target):.1f} m³/h\n"
            f"남은 풍량(참고용): {remaining:.1f} m³/h\n"
            f"현 지점(outlet) 현재 풍량: {current:.1f} m³/h\n\n"
            f"이 outlet의 풍량을 입력하세요:"
        )

        answer = simpledialog.askstring("Air outlet 풍량 입력", msg)
        if answer is None:
            return

        try:
            new_flow = float(answer)
            if new_flow < 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("입력 오류", "0 이상 숫자로 입력해주세요.")
            return

        target.flow = new_flow
        self.segments.clear()
        self.redraw_all()

    def _find_point_near_model(self, mx, my, tol_model=0.3):
        for p in self.points:
            if (p.mx - mx)**2 + (p.my - my)**2 <= tol_model**2:
                return p
        return None

    def _sum_outlet_flow(self, exclude=None):
        s = 0.0
        for p in self.points:
            if p.kind == "outlet" and p is not exclude:
                s += p.flow
        return s

    def _calc_remaining_flow(self, exclude=None):
        return self.inlet_flow - self._sum_outlet_flow(exclude=exclude)

    # ---------- 마우스 이동 / 드래그 ----------

    def on_mouse_move(self, event):
        # 모델 좌표로 변환
        mx, my = self.screen_to_model(event.x, event.y)

        # 이미 드래그 중이면 hover는 굳이 다시 안 바꿔도 됨
        if self.dragging_segment is not None:
            return

        seg = self._hit_test_segment(mx, my, tol=0.15)

        # 기존 hover 해제
        if self.hovered_segment is not None and self.hovered_segment is not seg:
            self.hovered_segment.is_hovered = False
            self.hovered_segment = None

        # 새 hover 설정
        if seg is not None:
            seg.is_hovered = True
            self.hovered_segment = seg

        # 화면 갱신
        self.redraw_all()

    def on_left_drag(self, event):
        mx, my = self.screen_to_model(event.x, event.y)

        # 드래그 시작
        if self.dragging_segment is None:
            seg = self._hit_test_segment(mx, my, tol=0.15)
            if seg is None:
                return
            self.dragging_segment = seg
            seg.is_dragging = True
            seg.drag_start_model = (mx, my)

        seg = self.dragging_segment
        if seg is None:
            return

        cur_mx, cur_my = mx, my
        start_mx, start_my = seg.drag_start_model

        # 덕트 방향에 따라 한 축만 이동 (격자 스냅 포함)
        if seg.vertical_only:
            # 수직 세그먼트: x만 이동
            dx_raw = cur_mx - start_mx
            base_x = (seg.mx1 + seg.mx2) / 2.0
            new_x = base_x + dx_raw
            # 격자 스냅
            snapped_x, _ = self.snap_model(new_x, 0.0)
            dx = snapped_x - base_x
            if abs(dx) < 1e-9:
                return

            # 연결된 세그먼트 전체를 x 방향으로 이동
            self._move_connected_segments(seg, dx=dx, dy=0.0)

            seg.drag_start_model = (cur_mx, start_my)

        else:
            # 수평 세그먼트: y만 이동
            dy_raw = cur_my - start_my
            base_y = (seg.my1 + seg.my2) / 2.0
            new_y = base_y + dy_raw
            # 격자 스냅
            _, snapped_y = self.snap_model(0.0, new_y)
            dy = snapped_y - base_y
            if abs(dy) < 1e-9:
                return

            # 연결된 세그먼트 전체를 y 방향으로 이동
            self._move_connected_segments(seg, dx=0.0, dy=dy)

            seg.drag_start_model = (start_mx, cur_my)

        self.redraw_all()

    def on_left_release(self, event):
        if self.dragging_segment is not None:
            self.dragging_segment.is_dragging = False
            self.dragging_segment.drag_start_model = None
            self.dragging_segment = None
        # 드래그 끝난 후 hover 재판정
        self.on_mouse_move(event)

    # ---------- 연결된 세그먼트 이동 (inlet/outlet 고정) ----------

    def _move_connected_segments(self, base_seg: DuctSegment, dx: float, dy: float):
        """
        base_seg와 연결된 세그먼트 전체를 dx, dy만큼 평행 이동.
        다만 inlet / outlet 점과 '정확히 붙어 있는' 세그먼트 끝점은 고정.
        사선이 생기는 경우 가로/세로 라인으로 분할.
        """
        # 세그먼트 간 연결은 '공통 끝점 좌표가 같은 경우'로 판단
        def seg_endpoints(seg: DuctSegment):
            return [(seg.mx1, seg.my1), (seg.mx2, seg.my2)]

        # BFS로 연결된 세그먼트 찾기
        connected = set()
        queue = [base_seg]
        connected.add(base_seg)

        while queue:
            cur = queue.pop(0)
            cur_ends = seg_endpoints(cur)
            for other in self.segments:
                if other in connected:
                    continue
                other_ends = seg_endpoints(other)
                if any(
                    (abs(ex1 - ex2) < 1e-9 and abs(ey1 - ey2) < 1e-9)
                    for (ex1, ey1) in cur_ends
                    for (ex2, ey2) in other_ends
                ):
                    connected.add(other)
                    queue.append(other)

        # inlet / outlet 점 위치 목록
        point_positions = [(p.mx, p.my) for p in self.points]

        def is_attached_to_point(x, y):
            for px, py in point_positions:
                if abs(px - x) < 1e-9 and abs(py - y) < 1e-9:
                    return True
            return False

        # 실제 이동
        segments_to_split = []
        
        for seg in connected:
            # 끝점 1과 2의 이동 가능 여부 확인
            pt1_fixed = is_attached_to_point(seg.mx1, seg.my1)
            pt2_fixed = is_attached_to_point(seg.mx2, seg.my2)
            
            # 한쪽만 고정된 경우 사선이 생길 수 있음
            if pt1_fixed and not pt2_fixed:
                # 끝점2만 이동 → 사선 가능성
                new_x2 = seg.mx2 + dx
                new_y2 = seg.my2 + dy
                
                # 사선인지 확인 (수평도 수직도 아닌 경우)
                is_diagonal = (abs(seg.mx1 - new_x2) > 1e-9 and abs(seg.my1 - new_y2) > 1e-9)
                
                if is_diagonal:
                    # 가로+세로로 분할
                    segments_to_split.append({
                        'original': seg,
                        'pt1': (seg.mx1, seg.my1),
                        'pt2': (new_x2, new_y2),
                        'fixed': 'pt1'
                    })
                else:
                    seg.mx2 = new_x2
                    seg.my2 = new_y2
                    
            elif pt2_fixed and not pt1_fixed:
                # 끝점1만 이동 → 사선 가능성
                new_x1 = seg.mx1 + dx
                new_y1 = seg.my1 + dy
                
                is_diagonal = (abs(new_x1 - seg.mx2) > 1e-9 and abs(new_y1 - seg.my2) > 1e-9)
                
                if is_diagonal:
                    # 가로+세로로 분할
                    segments_to_split.append({
                        'original': seg,
                        'pt1': (new_x1, new_y1),
                        'pt2': (seg.mx2, seg.my2),
                        'fixed': 'pt2'
                    })
                else:
                    seg.mx1 = new_x1
                    seg.my1 = new_y1
                    
            elif not pt1_fixed and not pt2_fixed:
                # 둘 다 이동 가능 → 평행 이동
                seg.mx1 += dx
                seg.my1 += dy
                seg.mx2 += dx
                seg.my2 += dy
            # 둘 다 고정인 경우는 이동 안 함
        
        # 사선 세그먼트를 가로+세로로 분할
        for split_info in segments_to_split:
            seg = split_info['original']
            pt1 = split_info['pt1']
            pt2 = split_info['pt2']
            
            # 원본 세그먼트 제거
            if seg in self.segments:
                self.segments.remove(seg)
            
            # 가로 세그먼트 + 세로 세그먼트 생성
            # 중간점: 한 좌표는 pt1, 다른 좌표는 pt2
            if abs(dx) > 1e-9:  # x 방향 이동
                # 먼저 수평, 그 다음 수직
                mid_x, mid_y = pt2[0], pt1[1]
                
                # 수평 세그먼트
                if abs(pt1[0] - mid_x) > 1e-9:
                    seg_h = DuctSegment(
                        pt1[0], pt1[1], mid_x, mid_y,
                        seg.label_text,
                        duct_w_mm=seg.duct_w_mm,
                        duct_h_mm=seg.duct_h_mm,
                        flow_m3h=seg.flow,
                        vertical_only=False,
                        circular_diameter_mm=seg.circular_diameter_mm
                    )
                    self.segments.append(seg_h)
                
                # 수직 세그먼트
                if abs(mid_y - pt2[1]) > 1e-9:
                    seg_v = DuctSegment(
                        mid_x, mid_y, pt2[0], pt2[1],
                        seg.label_text,
                        duct_w_mm=seg.duct_w_mm,
                        duct_h_mm=seg.duct_h_mm,
                        flow_m3h=seg.flow,
                        vertical_only=True,
                        circular_diameter_mm=seg.circular_diameter_mm
                    )
                    self.segments.append(seg_v)
                    
            else:  # y 방향 이동
                # 먼저 수직, 그 다음 수평
                mid_x, mid_y = pt1[0], pt2[1]
                
                # 수직 세그먼트
                if abs(pt1[1] - mid_y) > 1e-9:
                    seg_v = DuctSegment(
                        pt1[0], pt1[1], mid_x, mid_y,
                        seg.label_text,
                        duct_w_mm=seg.duct_w_mm,
                        duct_h_mm=seg.duct_h_mm,
                        flow_m3h=seg.flow,
                        vertical_only=True,
                        circular_diameter_mm=seg.circular_diameter_mm
                    )
                    self.segments.append(seg_v)
                
                # 수평 세그먼트
                if abs(mid_x - pt2[0]) > 1e-9:
                    seg_h = DuctSegment(
                        mid_x, mid_y, pt2[0], pt2[1],
                        seg.label_text,
                        duct_w_mm=seg.duct_w_mm,
                        duct_h_mm=seg.duct_h_mm,
                        flow_m3h=seg.flow,
                        vertical_only=False,
                        circular_diameter_mm=seg.circular_diameter_mm
                    )
                    self.segments.append(seg_h)

    # ---------- 종합 사이징 (inlet 높이 수평 메인 + 좌/우 메인 + 수직 브랜치) ----------

    def draw_duct_network(self, dp_mmAq_per_m: float, aspect_ratio: float):
        if len(self.points) < 2:
            messagebox.showwarning("경고", "점이 2개 이상 있어야 종합 사이징을 할 수 있습니다.")
            return

        self.segments.clear()

        inlet = self.points[0]
        if inlet.kind != "inlet":
            messagebox.showwarning("경고", "첫 번째 점은 Air inlet이어야 합니다.")
            return

        Q_inlet = inlet.flow
        if Q_inlet <= 0:
            messagebox.showwarning("경고", "Air inlet 풍량이 0 이하입니다. 좌측 풍량 값을 확인해주세요.")
            return

        outlets = [p for p in self.points[1:] if p.kind == "outlet"]
        if not outlets:
            messagebox.showwarning("경고", "Air outlet 점이 없습니다.")
            return

        # outlet 총 풍량과 inlet 풍량 비교 (안내용)
        total_out = sum(ot.flow for ot in outlets)
        if abs(total_out - Q_inlet) > 1e-6:
            messagebox.showwarning(
                "경고",
                f"Air outlet 총 풍량({total_out:.1f} m³/h)가 "
                f"inlet 풍량({Q_inlet:.1f} m³/h)과 다릅니다.\n"
                "그래도 계산을 계속 진행합니다."
            )

        # --- 1) 메인선 y좌표: inlet 높이로 고정 ---
        y_main = inlet.my

        # --- 2) inlet에서 메인선까지 수직 리저 (이론상 필요 없지만 안전하게 유지) ---
        if abs(inlet.my - y_main) > 1e-9:
            Q_riser = Q_inlet
            try:
                D1 = calc_circular_diameter(Q_riser, dp_mmAq_per_m)
                D1_rounded = round_step_up(D1, 50)
                sel_big, sel_small, De_sel, theo_big, theo_small = size_rect_from_D1(
                    D1, aspect_ratio, 50
                )
                label_text = f"{sel_big}x{sel_small} (Ø{D1_rounded:.0f})"
                seg_riser = DuctSegment(
                    inlet.mx, inlet.my, inlet.mx, y_main,
                    label_text,
                    duct_w_mm=sel_big,
                    duct_h_mm=sel_small,
                    flow_m3h=Q_riser,
                    vertical_only=True,
                    circular_diameter_mm=D1_rounded
                )
                self.segments.append(seg_riser)
            except ValueError:
                pass

        # --- 3) 좌우 outlet 분리 ---
        left_outlets = [ot for ot in outlets if ot.mx < inlet.mx - 1e-9]
        right_outlets = [ot for ot in outlets if ot.mx > inlet.mx + 1e-9]
        center_outlets = [ot for ot in outlets if abs(ot.mx - inlet.mx) <= 1e-9]

        # --- 4) outlet 그룹화 (y좌표 기준) ---
        def group_outlets_by_y(outlet_list, y_tolerance=0.5):
            """y 좌표가 가까운 outlet들을 그룹화"""
            if not outlet_list:
                return []
            
            sorted_by_y = sorted(outlet_list, key=lambda p: p.my)
            groups = []
            current_group = [sorted_by_y[0]]
            
            for i in range(1, len(sorted_by_y)):
                if abs(sorted_by_y[i].my - current_group[0].my) <= y_tolerance:
                    current_group.append(sorted_by_y[i])
                else:
                    groups.append(current_group)
                    current_group = [sorted_by_y[i]]
            groups.append(current_group)
            return groups

        # 그룹 정보 생성
        right_groups = group_outlets_by_y(right_outlets)
        left_groups = group_outlets_by_y(left_outlets)

        # 각 그룹의 대표 x 좌표와 전체 풍량을 매핑
        right_group_map = {}  # {대표_x: 그룹_전체_풍량}
        for group in right_groups:
            group_sorted = sorted(group, key=lambda p: p.mx)
            first_x = group_sorted[0].mx
            total_flow = sum(ot.flow for ot in group)
            right_group_map[first_x] = total_flow

        left_group_map = {}
        for group in left_groups:
            group_sorted = sorted(group, key=lambda p: p.mx, reverse=True)
            first_x = group_sorted[0].mx
            total_flow = sum(ot.flow for ot in group)
            left_group_map[first_x] = total_flow

        # --- 5) 오른쪽 메인 (inlet.x → 가장 오른쪽 outlet.x) ---
        if right_outlets:
            # 메인 덕트 노드는 각 그룹의 대표 x좌표만 사용
            x_nodes_right = [inlet.mx] + list(right_group_map.keys())
            x_nodes_right = sorted(set(x_nodes_right))

            def flow_downstream_from_right(x_pos: float) -> float:
                """x_pos보다 오른쪽에 있는 그룹들의 전체 풍량"""
                s = 0.0
                for group_x, group_flow in right_group_map.items():
                    if group_x > x_pos + 1e-9:
                        s += group_flow
                return s

            for i in range(len(x_nodes_right) - 1):
                x1 = x_nodes_right[i]
                x2 = x_nodes_right[i + 1]
                if abs(x2 - x1) < 1e-9:
                    continue

                # inlet 위치에서 시작하는 경우: 오른쪽 방향 outlet들의 전체 풍량
                if abs(x1 - inlet.mx) < 1e-9:
                    Q_main = sum(right_group_map.values())
                else:
                    Q_main = flow_downstream_from_right(x1)
                    
                if Q_main <= 0:
                    continue

                try:
                    D1 = calc_circular_diameter(Q_main, dp_mmAq_per_m)
                    D1_rounded = round_step_up(D1, 50)
                    sel_big, sel_small, De_sel, theo_big, theo_small = size_rect_from_D1(
                        D1, aspect_ratio, 50
                    )
                except ValueError:
                    continue

                label_text = f"{sel_big}x{sel_small} (Ø{D1_rounded:.0f})"

                seg = DuctSegment(
                    x1, y_main, x2, y_main,
                    label_text,
                    duct_w_mm=sel_big,
                    duct_h_mm=sel_small,
                    flow_m3h=Q_main,
                    vertical_only=False,
                    circular_diameter_mm=D1_rounded
                )
                self.segments.append(seg)

        # --- 6) 왼쪽 메인 (inlet.x → 가장 왼쪽 outlet.x) ---
        if left_outlets:
            # 메인 덕트 노드는 각 그룹의 대표 x좌표만 사용
            x_nodes_left = [inlet.mx] + list(left_group_map.keys())
            x_nodes_left = sorted(set(x_nodes_left), reverse=True)

            def flow_downstream_from_left(x_pos: float) -> float:
                """x_pos보다 왼쪽에 있는 그룹들의 전체 풍량"""
                s = 0.0
                for group_x, group_flow in left_group_map.items():
                    if group_x < x_pos - 1e-9:
                        s += group_flow
                return s

            for i in range(len(x_nodes_left) - 1):
                x1 = x_nodes_left[i]
                x2 = x_nodes_left[i + 1]
                if abs(x2 - x1) < 1e-9:
                    continue

                # inlet 위치에서 시작하는 경우: 왼쪽 방향 outlet들의 전체 풍량
                if abs(x1 - inlet.mx) < 1e-9:
                    Q_main = sum(left_group_map.values())
                else:
                    Q_main = flow_downstream_from_left(x1)
                    
                if Q_main <= 0:
                    continue

                try:
                    D1 = calc_circular_diameter(Q_main, dp_mmAq_per_m)
                    D1_rounded = round_step_up(D1, 50)
                    sel_big, sel_small, De_sel, theo_big, theo_small = size_rect_from_D1(
                        D1, aspect_ratio, 50
                    )
                except ValueError:
                    continue

                label_text = f"{sel_big}x{sel_small} (Ø{D1_rounded:.0f})"

                seg = DuctSegment(
                    x1, y_main, x2, y_main,
                    label_text,
                    duct_w_mm=sel_big,
                    duct_h_mm=sel_small,
                    flow_m3h=Q_main,
                    vertical_only=False,
                    circular_diameter_mm=D1_rounded
                )
                self.segments.append(seg)

        # --- 7) 브랜치 수직 세그먼트 최적화 (같은 y 좌표 그룹은 하나의 분기로 처리) ---
        # 오른쪽 outlet 그룹 처리
        if right_outlets:
            for group in right_groups:
                # 그룹 내에서 x좌표로 정렬
                group_sorted = sorted(group, key=lambda p: p.mx)
                group_y = group[0].my  # 그룹의 y좌표
                
                # 그룹 전체 풍량
                group_flow = sum(ot.flow for ot in group)
                
                if len(group) == 1:
                    # 단일 outlet: 기존 방식대로 메인에서 직접 연결
                    ot = group[0]
                    Q_branch = ot.flow
                    if Q_branch <= 0:
                        continue
                    
                    try:
                        D1 = calc_circular_diameter(Q_branch, dp_mmAq_per_m)
                        D1_rounded = round_step_up(D1, 50)
                        sel_big, sel_small, De_sel, theo_big, theo_small = size_rect_from_D1(
                            D1, aspect_ratio, 50
                        )
                    except ValueError:
                        continue
                    
                    label_text = f"{sel_big}x{sel_small} (Ø{D1_rounded:.0f})"
                    
                    seg = DuctSegment(
                        ot.mx, y_main, ot.mx, ot.my,
                        label_text,
                        duct_w_mm=sel_big,
                        duct_h_mm=sel_small,
                        flow_m3h=Q_branch,
                        vertical_only=True,
                        circular_diameter_mm=D1_rounded
                    )
                    self.segments.append(seg)
                else:
                    # 다중 outlet: 최적화된 분기 방식
                    # 1) 첫 번째 outlet 위치에서 메인에서 수직 분기
                    first_x = group_sorted[0].mx
                    
                    try:
                        D1_main = calc_circular_diameter(group_flow, dp_mmAq_per_m)
                        D1_main_rounded = round_step_up(D1_main, 50)
                        sel_big_main, sel_small_main, _, _, _ = size_rect_from_D1(
                            D1_main, aspect_ratio, 50
                        )
                    except ValueError:
                        continue
                    
                    label_text_main = f"{sel_big_main}x{sel_small_main} (Ø{D1_main_rounded:.0f})"
                    
                    # 메인에서 분기점까지 수직 세그먼트
                    seg_vertical = DuctSegment(
                        first_x, y_main, first_x, group_y,
                        label_text_main,
                        duct_w_mm=sel_big_main,
                        duct_h_mm=sel_small_main,
                        flow_m3h=group_flow,
                        vertical_only=True,
                        circular_diameter_mm=D1_main_rounded
                    )
                    self.segments.append(seg_vertical)
                    
                    # 2) 분기점에서 각 outlet까지 수평 + 수직 연결
                    for i, ot in enumerate(group_sorted):
                        Q_branch = ot.flow
                        if Q_branch <= 0:
                            continue
                        
                        if i < len(group_sorted) - 1:
                            # 마지막이 아닌 경우: 현재 outlet 이후의 풍량으로 수평 세그먼트
                            # 다음 outlet부터 끝까지의 풍량
                            remaining_flow = sum(group_sorted[j].flow for j in range(i + 1, len(group_sorted)))
                            
                            x1 = group_sorted[i].mx
                            x2 = group_sorted[i + 1].mx
                            
                            try:
                                D1_horiz = calc_circular_diameter(remaining_flow, dp_mmAq_per_m)
                                D1_horiz_rounded = round_step_up(D1_horiz, 50)
                                sel_big_h, sel_small_h, _, _, _ = size_rect_from_D1(
                                    D1_horiz, aspect_ratio, 50
                                )
                            except ValueError:
                                continue
                            
                            label_text_h = f"{sel_big_h}x{sel_small_h} (Ø{D1_horiz_rounded:.0f})"
                            
                            seg_horiz = DuctSegment(
                                x1, group_y, x2, group_y,
                                label_text_h,
                                duct_w_mm=sel_big_h,
                                duct_h_mm=sel_small_h,
                                flow_m3h=remaining_flow,
                                vertical_only=False,
                                circular_diameter_mm=D1_horiz_rounded
                            )
                            self.segments.append(seg_horiz)
                        
                        # 분기점에서 outlet까지 수직 세그먼트 (y좌표가 다른 경우만)
                        if abs(group_y - ot.my) > 1e-9:
                            try:
                                D1_vert = calc_circular_diameter(Q_branch, dp_mmAq_per_m)
                                D1_vert_rounded = round_step_up(D1_vert, 50)
                                sel_big_v, sel_small_v, _, _, _ = size_rect_from_D1(
                                    D1_vert, aspect_ratio, 50
                                )
                            except ValueError:
                                continue
                            
                            label_text_v = f"{sel_big_v}x{sel_small_v} (Ø{D1_vert_rounded:.0f})"
                            
                            seg_vert = DuctSegment(
                                ot.mx, group_y, ot.mx, ot.my,
                                label_text_v,
                                duct_w_mm=sel_big_v,
                                duct_h_mm=sel_small_v,
                                flow_m3h=Q_branch,
                                vertical_only=True,
                                circular_diameter_mm=D1_vert_rounded
                            )
                            self.segments.append(seg_vert)

        # 왼쪽 outlet 그룹 처리
        if left_outlets:
            for group in left_groups:
                # 그룹 내에서 x좌표로 정렬 (왼쪽이므로 역순)
                group_sorted = sorted(group, key=lambda p: p.mx, reverse=True)
                group_y = group[0].my
                
                group_flow = sum(ot.flow for ot in group)
                
                if len(group) == 1:
                    # 단일 outlet
                    ot = group[0]
                    Q_branch = ot.flow
                    if Q_branch <= 0:
                        continue
                    
                    try:
                        D1 = calc_circular_diameter(Q_branch, dp_mmAq_per_m)
                        D1_rounded = round_step_up(D1, 50)
                        sel_big, sel_small, De_sel, theo_big, theo_small = size_rect_from_D1(
                            D1, aspect_ratio, 50
                        )
                    except ValueError:
                        continue
                    
                    label_text = f"{sel_big}x{sel_small} (Ø{D1_rounded:.0f})"
                    
                    seg = DuctSegment(
                        ot.mx, y_main, ot.mx, ot.my,
                        label_text,
                        duct_w_mm=sel_big,
                        duct_h_mm=sel_small,
                        flow_m3h=Q_branch,
                        vertical_only=True,
                        circular_diameter_mm=D1_rounded
                    )
                    self.segments.append(seg)
                else:
                    # 다중 outlet
                    first_x = group_sorted[0].mx
                    
                    try:
                        D1_main = calc_circular_diameter(group_flow, dp_mmAq_per_m)
                        D1_main_rounded = round_step_up(D1_main, 50)
                        sel_big_main, sel_small_main, _, _, _ = size_rect_from_D1(
                            D1_main, aspect_ratio, 50
                        )
                    except ValueError:
                        continue
                    
                    label_text_main = f"{sel_big_main}x{sel_small_main} (Ø{D1_main_rounded:.0f})"
                    
                    seg_vertical = DuctSegment(
                        first_x, y_main, first_x, group_y,
                        label_text_main,
                        duct_w_mm=sel_big_main,
                        duct_h_mm=sel_small_main,
                        flow_m3h=group_flow,
                        vertical_only=True,
                        circular_diameter_mm=D1_main_rounded
                    )
                    self.segments.append(seg_vertical)
                    
                    for i, ot in enumerate(group_sorted):
                        Q_branch = ot.flow
                        if Q_branch <= 0:
                            continue
                        
                        if i < len(group_sorted) - 1:
                            # 다음 outlet부터 끝까지의 풍량
                            remaining_flow = sum(group_sorted[j].flow for j in range(i + 1, len(group_sorted)))
                            
                            x1 = group_sorted[i].mx
                            x2 = group_sorted[i + 1].mx
                            
                            try:
                                D1_horiz = calc_circular_diameter(remaining_flow, dp_mmAq_per_m)
                                D1_horiz_rounded = round_step_up(D1_horiz, 50)
                                sel_big_h, sel_small_h, _, _, _ = size_rect_from_D1(
                                    D1_horiz, aspect_ratio, 50
                                )
                            except ValueError:
                                continue
                            
                            label_text_h = f"{sel_big_h}x{sel_small_h} (Ø{D1_horiz_rounded:.0f})"
                            
                            seg_horiz = DuctSegment(
                                x1, group_y, x2, group_y,
                                label_text_h,
                                duct_w_mm=sel_big_h,
                                duct_h_mm=sel_small_h,
                                flow_m3h=remaining_flow,
                                vertical_only=False,
                                circular_diameter_mm=D1_horiz_rounded
                            )
                            self.segments.append(seg_horiz)
                        
                        if abs(group_y - ot.my) > 1e-9:
                            try:
                                D1_vert = calc_circular_diameter(Q_branch, dp_mmAq_per_m)
                                D1_vert_rounded = round_step_up(D1_vert, 50)
                                sel_big_v, sel_small_v, _, _, _ = size_rect_from_D1(
                                    D1_vert, aspect_ratio, 50
                                )
                            except ValueError:
                                continue
                            
                            label_text_v = f"{sel_big_v}x{sel_small_v} (Ø{D1_vert_rounded:.0f})"
                            
                            seg_vert = DuctSegment(
                                ot.mx, group_y, ot.mx, ot.my,
                                label_text_v,
                                duct_w_mm=sel_big_v,
                                duct_h_mm=sel_small_v,
                                flow_m3h=Q_branch,
                                vertical_only=True,
                                circular_diameter_mm=D1_vert_rounded
                            )
                            self.segments.append(seg_vert)

        # 중앙 outlet 처리 (inlet과 같은 x 좌표)
        for ot in center_outlets:
            Q_branch = ot.flow
            if Q_branch <= 0:
                continue

            try:
                D1 = calc_circular_diameter(Q_branch, dp_mmAq_per_m)
                D1_rounded = round_step_up(D1, 50)
                sel_big, sel_small, De_sel, theo_big, theo_small = size_rect_from_D1(
                    D1, aspect_ratio, 50
                )
            except ValueError:
                continue

            label_text = f"{sel_big}x{sel_small} (Ø{D1_rounded:.0f})"

            seg = DuctSegment(
                ot.mx, y_main, ot.mx, ot.my,
                label_text,
                duct_w_mm=sel_big,
                duct_h_mm=sel_small,
                flow_m3h=Q_branch,
                vertical_only=True,
                circular_diameter_mm=D1_rounded
            )
            self.segments.append(seg)

        self.redraw_all()

    # ---------- Undo & Clear & 균등 배분 ----------

    def undo_last_point(self):
        if not self.points:
            messagebox.showinfo("Undo", "되돌릴 점이 없습니다.")
            return
        self.points.pop()
        self.segments.clear()
        self.redraw_all()

    def clear_all(self):
        self.points.clear()
        self.segments.clear()
        self.redraw_all()

    def distribute_equal_flow(self):
        if not self.points:
            messagebox.showwarning("경고", "먼저 Air inlet을 포함한 점을 찍어주세요.")
            return
        if len(self.points) < 2:
            messagebox.showwarning("경고", "최소 2개 이상의 점이 있어야 균등 배분이 가능합니다.")
            return

        Q_in = self.inlet_flow
        if Q_in <= 0:
            messagebox.showwarning("경고", "Air inlet 풍량이 0 이하입니다. 좌측 풍량 값을 확인해주세요.")
            return

        n_out = len(self.points) - 1
        Q_each = Q_in / n_out

        for idx, p in enumerate(self.points):
            if idx == 0:
                p.flow = Q_in
            else:
                p.flow = Q_each

        self.segments.clear()
        self.redraw_all()

# =========================
# GUI 이벤트 함수
# =========================

def calculate():
    try:
        q = float(cubic_meter_hour_entry.get())
        dp = float(resistance_entry.get())

        D1 = calc_circular_diameter(q, dp)
        D2 = round_step_up(D1, 50)

        try:
            r = float(aspect_ratio_combo.get())
        except ValueError:
            r = 2.0

        sel_big, sel_small, De_sel, theo_big, theo_small = size_rect_from_D1(D1, r, 50)

        text = (
            f"※ 팔레트 격자 1칸 = 0.5 m (가로/세로)\n"
            f"※ 덕트 사이즈 단위는 mm 입니다.\n"
            f"1. 등가원형 직경 (mm) : {D1:.0f}\n"
            f"2. 원형직경 (mm)     : {D2}\n"
            f"3. 사각덕트 사이즈 (mm X mm, 50mm 조정) : {sel_big} X {sel_small}\n"
            f"4. 사각덕트 사이즈 (mm X mm, 조정 전)  : {theo_big:.1f} X {theo_small:.1f}"
        )
        results_text_widget.delete("1.0", tk.END)
        results_text_widget.insert("1.0", text)

        palette.set_inlet_flow(q)

    except ValueError as e:
        messagebox.showerror("입력 오류", f"입력값을 확인하세요!\n\n{e}")
    except Exception as e:
        messagebox.showerror("알 수 없는 오류", f"알 수 없는 오류가 발생했습니다:\n\n{e}")


def total_sizing():
    try:
        dp = float(resistance_entry.get())
    except ValueError:
        messagebox.showerror("입력 오류", "정압값을 올바르게 입력해주세요.")
        return

    try:
        r = float(aspect_ratio_combo.get())
    except ValueError:
        r = 2.0

    palette.draw_duct_network(dp_mmAq_per_m=dp, aspect_ratio=r)

    total_area_m2 = 0.0
    total_area_circular_m2 = 0.0
    
    for seg in palette.segments:
        L = seg.length_m()
        
        # 사각덕트 철판 소요량
        w_m = seg.duct_w_mm / 1000.0
        h_m = seg.duct_h_mm / 1000.0
        area = (w_m + h_m) * 2 * L
        total_area_m2 += area
        
        # 원형덕트 철판 소요량
        if seg.circular_diameter_mm > 0:
            d_m = seg.circular_diameter_mm / 1000.0
            area_circular = math.pi * d_m * L
            total_area_circular_m2 += area_circular

    base = results_text_widget.get("1.0", tk.END).strip()
    if base:
        base += "\n"
    base += f"5. 덕트 철판 소요량 (사각, 원형)[m²] : {total_area_m2:.1f}, {total_area_circular_m2:.1f}"

    results_text_widget.delete("1.0", tk.END)
    results_text_widget.insert("1.0", base)


def clear_palette():
    palette.clear_all()


def equal_distribution():
    try:
        q = float(cubic_meter_hour_entry.get())
        palette.set_inlet_flow(q)
    except ValueError:
        messagebox.showerror("입력 오류", "풍량 값을 올바르게 입력해주세요.")
        return

    palette.distribute_equal_flow()


def undo_point():
    palette.undo_last_point()

# =========================
# GUI 구성
# =========================

root = tk.Tk()
root.title("덕트 사이징 프로그램 (Grid 0.5m, mm 덕트, 철판 소요량)")

# 창 크기 설정 (가로 1.5배, 세로 1.1배)
root.geometry("900x440")

main_frame = tk.Frame(root)
main_frame.pack(fill="both", expand=True, padx=10, pady=10)

root.bind("<Control-z>", lambda event: undo_point())

left_frame = tk.Frame(main_frame)
left_frame.pack(side="left", anchor="w")

right_frame = tk.Frame(main_frame, bg="#f5f5f5", bd=1, relief="solid")
right_frame.pack(side="right", fill="both", expand=True)

tk.Label(left_frame, text="풍량 (m³/h):").grid(row=0, column=0, padx=5, pady=5, sticky="w")
cubic_meter_hour_entry = tk.Entry(left_frame, width=10)
cubic_meter_hour_entry.grid(row=0, column=1, padx=5, pady=5, sticky="w")
cubic_meter_hour_entry.insert(0, "40000")

tk.Label(left_frame, text="정압값 (mmAq/m):").grid(row=1, column=0, padx=5, pady=5, sticky="w")
resistance_entry = tk.Entry(left_frame, width=10)
resistance_entry.grid(row=1, column=1, padx=5, pady=5, sticky="w")
resistance_entry.insert(0, "0.1")

tk.Label(left_frame, text="사각 덕트 종횡비 (b/a):").grid(row=2, column=0, padx=5, pady=5, sticky="w")
aspect_ratio_combo = ttk.Combobox(left_frame, values=["1", "2", "3", "4"], state="readonly", width=5)
aspect_ratio_combo.current(1)
aspect_ratio_combo.grid(row=2, column=1, padx=5, pady=5, sticky="w")

tk.Button(left_frame, text="계산하기", command=calculate).grid(
    row=3, column=0, columnspan=2, pady=5, sticky="w"
)
tk.Button(left_frame, text="균등 풍량 배분", command=equal_distribution).grid(
    row=4, column=0, columnspan=2, pady=5, sticky="w"
)
tk.Button(left_frame, text="종합 사이징", command=total_sizing).grid(
    row=5, column=0, columnspan=2, pady=5, sticky="w"
)
tk.Button(left_frame, text="팔레트 전체 지우기", command=clear_palette).grid(
    row=6, column=0, columnspan=2, pady=5, sticky="w"
)

# 결과값 텍스트박스 (스크롤 가능)
results_frame = tk.Frame(left_frame)
results_frame.grid(row=7, column=0, columnspan=2, padx=5, pady=5, sticky="w")

results_text_widget = tk.Text(
    results_frame,
    width=52,
    height=9,
    bg="white",
    relief="solid",
    wrap="word"
)
results_text_widget.pack(side="left", fill="both", expand=True)

results_scrollbar = tk.Scrollbar(results_frame, command=results_text_widget.yview)
results_scrollbar.pack(side="right", fill="y")
results_text_widget.config(yscrollcommand=results_scrollbar.set)

palette = Palette(right_frame)

root.mainloop()
