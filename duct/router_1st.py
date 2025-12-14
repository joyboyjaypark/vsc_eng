# 요구사항 요약 (이 파일을 처음부터 다시 만들 때 빠짐없이 반영되어야 할 항목들)
#
# 1) 입력 위젯
#    - 풍량 Q (단위: m³/h), 기본값: 15,000 (화면에는 천단위 콤마 포함하여 '15,000' 표기)
#      * 입력 중 실시간으로 1,000단위 콤마를 표시한다 (타이핑할 때와 포커스 아웃 시).
#      * 내부 계산 시에는 콤마를 제거하고 숫자로 파싱한다.
#    - 정압 Δp (단위: mmAq/m), 기본값: 0.1
#    - Aspect Ratio 콤보박스 (b/a): 선택값(문자열) 중 하나를 사용
#      * 허용값: 1, 2, 3, 4, 6, 8 (기본: 2)
#
# 2) 계산식 및 규칙
#    - 등가원형(원형덕트) 이론치 D (mm):
#        D = 1000 * (C * Q^1.9 / Δp)^0.199
#      여기서 C = 3.295e-10, Q는 m³/h, Δp는 mmAq/m
#    - 원형덕트(규격화): 등가원형 이론치 D에서 50 mm 단위로 올림
#      (라운드 규격 단위는 코드의 `step` 변수로 변경 가능)
#    - 사각⇄등가원형 환산 식 (De 계산식, 단위 mm):
#        De = 1.30 * (a*b)^0.625 / (a + b)^0.25
#      여기서 a = 가로(mm), b = 세로(mm), 결과 De(mm)
#    - 등가원형 D를 기준으로 사각 덕트 이론치(a_theo,b_theo)를 역산:
#        a_theo = De * (1 + r)^0.25 / (1.30 * r^0.625)
#        b_theo = r * a_theo   (r = b/a = Aspect Ratio)
#
# 3) 사각 덕트 규격화 알고리즘 (기본 step = 50 mm)
#    1. 이론치 a_theo, b_theo 계산 (theo_big/theo_small = 정렬된 값)
#    2. 후보1: theo_small을 올림(small_up), theo_big을 내림(big_down) → De1 = rect_equiv_diameter(small_up, big_down)
#    3. 후보2: 둘 다 올림(a_up,b_up) → De2 = rect_equiv_diameter(a_up,b_up)
#    4. 최종 선택: 만약 De1 >= De_target(등가원형)이면 후보1 사용, 아니면 후보2 사용
#    5. 반환: (sel_big_mm, sel_small_mm, De_sel_mm, theo_big_mm, theo_small_mm)
#
# 4) 출력 표기 규칙
#    - 화면에 표시되는 모든 수치는 천단위 콤마로 표기 (예: 15,000)
#    - 결과 라벨 명칭 (명확히):
#        * 원형덕트 (이론치): 등가원형 식으로 계산된 D (mm)
#        * 원형덕트 (규격화): 50mm 단위 올림된 D (mm)
#        * 사각덕트 (이론치): 이론 a_theo x b_theo (mm)
#        * 사각덕트 (규격화): 규격화된 a x b (mm)
#          - 규격화된 사각 뒤에 별도로 `계산된 De`를 다음 줄에 출력
#
# 5) UI 동작 및 편의성
#    - 풍량 입력란은 키 입력마다(및 포커스 아웃 시) 천단위 콤마를 적용한다.
#    - 계산 시 콤마가 포함된 입력도 정상 파싱되도록 처리한다.
#    - 결과는 복사 가능한 텍스트 형태로 표시(현재는 Label에 표시).
#
# 6) 구현 세부
#    - 기본 규격 단위(step): 50 mm (코드 상에서 변경 가능)
#    - 모든 단위는 mm, m³/h, mmAq/m을 사용
#    - 예외 처리: 입력값이 0 이하이면 오류 메시지 출력
#
# 위 요구사항은 파일 상단에 문서화되어, 향후 이 모듈을 재구성할 때
# 누락 없이 반영되도록 합니다.


"""덕트 환산 툴 (router_1st.py)

간단한 GUI로 다음을 계산합니다:
 - 등가원형 직경 D (mm)
 - 규격화된 원형직경 (50 mm 단위 올림)
 - 환산(이론) 사각 치수 a x b (mm)
 - 규격화된 사각 치수 (50 mm 단위)

계산식 출처: 기존 `duct auto drawer.py`에 있던 경험식 사용
"""

import tkinter as tk
from tkinter import ttk, messagebox
import math


# ---------- 계산 함수들 ----------

def calc_circular_diameter(q_m3h: float, dp_mmAq_per_m: float) -> float:
	"""등가원형 덕트 직경 D (mm) 계산 (경험식)

	D = 1000 * (C * Q^1.9 / Δp)^0.199
	Q: m3/h, Δp: mmAq/m
	"""
	if q_m3h <= 0:
		raise ValueError("풍량(m³/h)은 0보다 커야 합니다.")
	if dp_mmAq_per_m <= 0:
		raise ValueError("정압값(mmAq/m)은 0보다 커야 합니다.")

	C = 3.295e-10
	D = ((C * q_m3h**1.9 / dp_mmAq_per_m) ** 0.199) * 1000.0
	return D


def round_step_up(x: float, step: float = 50.0) -> float:
	return math.ceil(x / step) * step


def round_step_down(x: float, step: float = 50.0) -> float:
	return math.floor(x / step) * step


def rect_equiv_diameter(a_mm: float, b_mm: float) -> float:
	"""사각 덕트 a,b(mm)에 대한 등가 원형 직경 De(mm) (경험식)

	De = 1.30 * (a*b)^0.625 / (a + b)^0.25
	"""
	if a_mm <= 0 or b_mm <= 0:
		raise ValueError("사각 덕트 변은 0보다 커야 합니다.")
	a, b = float(a_mm), float(b_mm)
	return 1.30 * (a * b) ** 0.625 / (a + b) ** 0.25


def size_rect_from_D1(D1: float, aspect_ratio: float, step: float = 50.0):
	"""등가원형 D1(mm)에서 이론 사각 a_theo,b_theo 계산 및 규격화 알고리즘

	반환: (sel_big_mm, sel_small_mm, De_sel_mm, theo_big_mm, theo_small_mm)
	sel_big/sel_small: 규격화된 (a,b) (mm, a>=b)
	De_sel: 규격화된 a,b로 계산한 등가원형(mm)
	theo_big/theo_small: 이론 계산값(mm)
	"""
	if D1 <= 0:
		raise ValueError("원형 덕트 직경은 0보다 커야 합니다.")
	if aspect_ratio <= 0:
		raise ValueError("종횡비(b/a)는 0보다 커야 합니다.")

	De_target = float(D1)
	r = float(aspect_ratio)

	# 이론치 계산 (a_theo는 가로 a, b는 세로이며 r = b/a)
	a_theo = De_target * (1 + r) ** 0.25 / (1.30 * r ** 0.625)
	b_theo = r * a_theo
	theo_big, theo_small = max(a_theo, b_theo), min(a_theo, b_theo)

	# 후보1: 작은 값 올림, 큰 값 내림
	small_up = round_step_up(theo_small, step)
	big_down = max(round_step_down(theo_big, step), step)
	De1 = rect_equiv_diameter(small_up, big_down)

	# 후보2: 둘 다 올림
	a_up = round_step_up(a_theo, step)
	b_up = round_step_up(b_theo, step)
	De2 = rect_equiv_diameter(a_up, b_up)

	# 최종 선택
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


# ---------- GUI ----------

def _format_q_entry(event=None):
	"""Entry에 입력되는 풍량값을 실시간으로 1,000단위 콤마로 포맷합니다.

	단순 구현: 포맷 후 커서를 끝으로 이동시킵니다.
	"""
	try:
		s = entry_q.get()
	except Exception:
		return

	raw = s.replace(',', '').strip()
	if raw == '' or raw == '-' or raw == '.' or raw == '-.':
		return

	# 허용 가능한 숫자 형태(정수 또는 소수)
	try:
		if '.' in raw:
			intpart, frac = raw.split('.', 1)
			if intpart == '' or intpart == '-':
				int_val = 0
			else:
				int_val = int(intpart)
			formatted = f"{int_val:,}" + '.' + frac
		else:
			int_val = int(raw)
			formatted = f"{int_val:,}"
	except ValueError:
		return

	if formatted != s:
		entry_q.delete(0, tk.END)
		entry_q.insert(0, formatted)
		entry_q.icursor(tk.END)


def calculate_and_show():
	try:
		q_str = entry_q.get().replace(',', '').strip()
		q = float(q_str) if q_str != '' else 0.0
		dp = float(entry_dp.get())
	except ValueError:
		messagebox.showerror("입력 오류", "숫자를 올바르게 입력해주세요 (예: 15000, 0.1)")
		return

	try:
		r = float(combo_ar.get())
	except ValueError:
		r = 2.0

	try:
		D_exact = calc_circular_diameter(q, dp)
	except ValueError as e:
		messagebox.showerror("계산 오류", str(e))
		return

	D_rounded = round_step_up(D_exact, 50.0)

	# 사각 이론치 및 규격화
	sel_big, sel_small, De_sel, theo_big, theo_small = size_rect_from_D1(D_exact, r, 50.0)

	# 결과 텍스트 구성
	txt = []
	txt.append(f"[덕트 Sizing 결과값]")
	txt.append(f"- 원형덕트 (이론치): {D_exact:,.1f} mm")
	txt.append(f"- 원형덕트 (규격화): {D_rounded:,.0f} mm")
	txt.append(f"- 사각덕트 (이론치): {theo_big:,.1f} x {theo_small:,.1f} mm")
	txt.append(f"- 사각덕트 (규격화): {sel_big:,} x {sel_small:,} mm")
	txt.append(f"  (계산된 De: {De_sel:,.1f} mm)")

	try:
		result_text.delete('1.0', tk.END)
		result_text.insert(tk.END, "\n".join(txt))
	except Exception:
		# fallback: no result_text available
		pass


def on_close():
	root.destroy()


if __name__ == '__main__':
	root = tk.Tk()
	root.title("덕트 환산 툴 (간단)")

	# 메인 프레임을 좌/우로 분할: 왼쪽 = 입력/결과, 오른쪽 = 팔레트(격자 캔버스)
	main_frame = tk.Frame(root)
	main_frame.pack(fill='both', expand=True)

	# 왼쪽 영역 컨테이너: 상단 메인덕트 프레임과 하단 자동 Sizing 프레임을 수직 배치
	LEFT_FRAME_WIDTH_PX = 320
	left_container = tk.Frame(main_frame)
	left_container.pack(side='left', fill='y', padx=8, pady=8)

	# 상단: 왼쪽 레이블박스 (입력, 버튼, 결과)
	left_frame = tk.LabelFrame(left_container, text='메인덕트 Sizing', padx=10, pady=10, width=LEFT_FRAME_WIDTH_PX)
	left_frame.pack(side='top', fill='x')
	left_frame.pack_propagate(True)

	right_frame = tk.Frame(main_frame, bd=1, relief='solid')
	right_frame.pack(side='right', fill='both', expand=True, padx=10, pady=10)

	# 캔버스(팔레트) 및 그리드 설정
	# 물리 단위로 격자 간격을 지정합니다 (격자간격 = 0.2 m)
	PIXELS_PER_M = 100  # 캔버스 상에서 1미터가 몇 픽셀인지 (조정 가능)
	GRID_STEP_M = 0.2   # 격자 간격 (미터)
	GRID_STEP_PX = int(GRID_STEP_M * PIXELS_PER_M)  # 캔버스 상의 격자 간격 (픽셀)
	palette_canvas = tk.Canvas(right_frame, bg='white')
	palette_canvas.pack(fill='both', expand=True)

	# 캔버스 스케일 및 상호작용 상태
	canvas_scale = 1.0
	ZOOM_STEP = 1.1
	MIN_SCALE = 0.1
	MAX_SCALE = 10.0

	def _draw_canvas_grid(event=None):
		palette_canvas.delete('grid')
		w = palette_canvas.winfo_width()
		h = palette_canvas.winfo_height()
		if w <= 0 or h <= 0:
			return

		# 현재 스케일을 반영한 격자 간격(픽셀)
		spacing = max(1, int(GRID_STEP_PX * canvas_scale))

		# 보이는 영역의 캔버스 좌표(스크롤 오프셋 포함)를 계산
		x0 = int(palette_canvas.canvasx(0))
		x1 = int(palette_canvas.canvasx(w))
		y0 = int(palette_canvas.canvasy(0))
		y1 = int(palette_canvas.canvasy(h))

		# 시작점은 보이는 영역에서 spacing의 배수로 맞춤
		start_x = (x0 // spacing) * spacing
		x = start_x
		while x <= x1:
			palette_canvas.create_line(x, y0, x, y1, fill='#e8e8e8', tags='grid')
			x += spacing

		start_y = (y0 // spacing) * spacing
		y = start_y
		while y <= y1:
			palette_canvas.create_line(x0, y, x1, y, fill='#e8e8e8', tags='grid')
			y += spacing

	# 줌 (마우스 휠) 핸들러
	def _on_mousewheel(event):
		global canvas_scale
		# Windows: event.delta (양수=위로, 음수=아래로)
		if hasattr(event, 'delta'):
			if event.delta > 0:
				scale = ZOOM_STEP
			else:
				scale = 1.0 / ZOOM_STEP
		else:
			# Linux/OSX fallback: Button-4/up, Button-5/down handled separately
			return

		# 중심점을 마우스 포인터로 설정
		x = palette_canvas.canvasx(event.x)
		y = palette_canvas.canvasy(event.y)

		# 새 스케일 계산 및 범위 제한
		new_scale = canvas_scale * scale
		if new_scale < MIN_SCALE:
			scale = MIN_SCALE / canvas_scale
			canvas_scale = MIN_SCALE
		elif new_scale > MAX_SCALE:
			scale = MAX_SCALE / canvas_scale
			canvas_scale = MAX_SCALE
		else:
			canvas_scale = new_scale

		# 캔버스의 모든 항목을 스케일
		palette_canvas.scale('all', x, y, scale, scale)
		_draw_canvas_grid()

	# Linux/other 마우스 휠 이벤트 (Button-4/5)
	def _on_button4(event):
		# scroll up
		event.delta = 1
		_on_mousewheel(event)

	def _on_button5(event):
		# scroll down
		event.delta = -1
		_on_mousewheel(event)

	# 팬(드래그) - 중간 버튼(휠) 드래그로 이동
	def _start_pan(event):
		palette_canvas.scan_mark(event.x, event.y)

	def _do_pan(event):
		palette_canvas.scan_dragto(event.x, event.y, gain=1)
		_draw_canvas_grid()

	palette_canvas.bind('<Configure>', _draw_canvas_grid)
	# 줌 바인딩 (Windows)
	palette_canvas.bind('<MouseWheel>', _on_mousewheel)
	# 줌 바인딩 (Linux)
	palette_canvas.bind('<Button-4>', _on_button4)
	palette_canvas.bind('<Button-5>', _on_button5)
	# 팬 바인딩 (중간 버튼)
	palette_canvas.bind('<ButtonPress-2>', _start_pan)
	palette_canvas.bind('<B2-Motion>', _do_pan)

	# --- 팔레트 상의 점/선 데이터 구조 및 유틸 ---
	points_list = []  # 각 점: dict { 'oval': oid, 'type': 'inlet'|'outlet' }
	item_to_point = {}  # oval_id -> index in points_list

	def get_grid_spacing():
		global canvas_scale
		return max(1, int(GRID_STEP_PX * canvas_scale))

	def snap_to_grid_canvas(cx, cy):
		spacing = get_grid_spacing()
		gx = round(cx / spacing) * spacing
		gy = round(cy / spacing) * spacing
		return gx, gy

	def _point_center(oval_id):
		coords = palette_canvas.coords(oval_id)
		if not coords or len(coords) < 4:
			return None, None
		x = (coords[0] + coords[2]) / 2.0
		y = (coords[1] + coords[3]) / 2.0
		return x, y

	def _add_point_at(cx, cy):
		# cx,cy : canvas coordinates
		gx, gy = snap_to_grid_canvas(cx, cy)
		# 중복 점 방지
		eps = 1e-6
		for p in points_list:
			px, py = _point_center(p['oval'])
			if px is None:
				continue
			if abs(px - gx) < eps and abs(py - gy) < eps:
				return

		ptype = 'inlet' if len(points_list) == 0 else 'outlet'
		color = 'red' if ptype == 'inlet' else 'green'
		r = max(3, int(5 * canvas_scale))
		oid = palette_canvas.create_oval(gx - r, gy - r, gx + r, gy + r, fill=color, outline='')
		entry = {'oval': oid, 'type': ptype}
		points_list.append(entry)
		item_to_point[oid] = len(points_list) - 1


	def delete_point(idx, popup=None):
		if idx < 0 or idx >= len(points_list):
			if popup:
				popup.destroy()
			return
		p = points_list[idx]
		# 삭제: 점 제거 (연결선 추적/삭제 없음 — 선 자동생성 기능 제거)
		try:
			palette_canvas.delete(p['oval'])
		except Exception:
			pass
		item_to_point.pop(p['oval'], None)
		points_list.pop(idx)

		# 남아있는 점들의 item_to_point 인덱스 갱신
		for i, pt in enumerate(points_list):
			item_to_point[pt['oval']] = i

		# 첫 점은 항상 inlet(빨강), 나머지는 outlet(녹색)
		for i, pt in enumerate(points_list):
			expected = 'inlet' if i == 0 else 'outlet'
			if pt['type'] != expected:
				pt['type'] = expected
				color = 'red' if expected == 'inlet' else 'green'
				palette_canvas.itemconfig(pt['oval'], fill=color)

		if popup:
			popup.destroy()

	def _on_left_click(event):
		cx = palette_canvas.canvasx(event.x)
		cy = palette_canvas.canvasy(event.y)
		_add_point_at(cx, cy)
		_draw_canvas_grid()

	def _on_right_click(event):
		cx = palette_canvas.canvasx(event.x)
		cy = palette_canvas.canvasy(event.y)
		found = palette_canvas.find_overlapping(cx - 2, cy - 2, cx + 2, cy + 2)
		for item in found:
			if item in item_to_point:
				idx = item_to_point[item]
				# 팝업 생성
				popup = tk.Toplevel(root)
				popup.wm_overrideredirect(True)
				px = root.winfo_pointerx()
				py = root.winfo_pointery()
				popup.geometry(f"+{px}+{py}")
				btn = tk.Button(popup, text="점 삭제", command=lambda i=idx, p=popup: delete_point(i, p))
				btn.pack()
				return

	# 왼쪽/오른쪽 버튼 바인딩
	palette_canvas.bind('<Button-1>', _on_left_click)
	palette_canvas.bind('<Button-3>', _on_right_click)

	# 입력
	tk.Label(left_frame, text="풍량 Q (m³/h):").grid(row=0, column=0, sticky='w')
	entry_q = tk.Entry(left_frame, width=8)
	entry_q.grid(row=0, column=1, sticky='w', padx=6, pady=4)
	entry_q.insert(0, "15,000")
	# 실시간 콤마 포맷 바인딩
	entry_q.bind('<KeyRelease>', lambda e: _format_q_entry(e))
	entry_q.bind('<FocusOut>', lambda e: _format_q_entry(e))

	tk.Label(left_frame, text="정압 Δp (mmAq/m):").grid(row=1, column=0, sticky='w')
	entry_dp = tk.Entry(left_frame, width=8)
	entry_dp.grid(row=1, column=1, sticky='w', padx=6, pady=4)
	entry_dp.insert(0, "0.1")

	tk.Label(left_frame, text="Aspect Ratio (b/a):").grid(row=2, column=0, sticky='w')
	combo_ar = ttk.Combobox(left_frame, values=["1","2","3","4","6","8"], width=6, state='readonly')
	combo_ar.grid(row=2, column=1, sticky='w', padx=6, pady=4)
	combo_ar.set("2")

	btn_calc = tk.Button(left_frame, text="계산", command=calculate_and_show)
	btn_calc.grid(row=2, column=2, sticky='w', padx=6, pady=4)

	# 결과: 텍스트 박스(6줄) + 수직 스크롤바
	# left_frame 너비에 비례한 텍스트 위젯 문자폭 계산 (한글/영문 차이 감안하여 약 7px/char 사용)
	approx_char_px = 7
	text_chars = max(20, int((LEFT_FRAME_WIDTH_PX - 40) / approx_char_px))
	result_text = tk.Text(left_frame, height=6, wrap='none', bg='white', bd=1, relief='solid', width=text_chars)
	result_scroll = tk.Scrollbar(left_frame, orient='vertical', command=result_text.yview)
	result_text.configure(yscrollcommand=result_scroll.set)
	result_text.grid(row=3, column=0, columnspan=3, sticky='we', padx=2, pady=6)
	result_scroll.grid(row=3, column=3, sticky='ns', pady=6)

	# 하단: 자동 Sizing & Routing 레이블박스 추가 (상단 프레임 아래에 표시)
	bottom_frame = tk.LabelFrame(left_container, text='자동 Sizing & Routing', padx=10, pady=10, width=LEFT_FRAME_WIDTH_PX)
	bottom_frame.pack(side='top', fill='x', pady=(6,0))
	bottom_frame.pack_propagate(True)
	# 하단 프레임에 '풍량분배' 버튼 추가
	btn_flow_dist = tk.Button(bottom_frame, text='풍량분배', width=14, command=lambda: messagebox.showinfo('풍량분배', '풍량분배 기능은 아직 구현되지 않았습니다.'))
	btn_flow_dist.pack(side='left', padx=4, pady=2)

	# 실행시 최초 창 크기를 기본 레이아웃 크기의 1.5배로 설정
	root.update_idletasks()
	cur_w = root.winfo_width()
	cur_h = root.winfo_height()
	# 일부 환경에서는 레이아웃 계산 전 너비/높이가 1로 반환될 수 있으므로 예비값 적용
	if cur_w <= 1 or cur_h <= 1:
		cur_w, cur_h = 800, 600
	new_w = int(cur_w * 1.5)
	new_h = int(cur_h * 1.5)
	root.geometry(f"{new_w}x{new_h}")

	root.protocol("WM_DELETE_WINDOW", on_close)
	root.mainloop()


