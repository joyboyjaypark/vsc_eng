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

	result_var.set("\n".join(txt))


def on_close():
	root.destroy()


if __name__ == '__main__':
	root = tk.Tk()
	root.title("덕트 환산 툴 (간단)")

	frm = tk.Frame(root, padx=10, pady=10)
	frm.pack(fill='both', expand=True)

	# 입력
	tk.Label(frm, text="풍량 Q (m³/h):").grid(row=0, column=0, sticky='w')
	entry_q = tk.Entry(frm, width=12)
	entry_q.grid(row=0, column=1, sticky='w', padx=6, pady=4)
	entry_q.insert(0, "15,000")
	# 실시간 콤마 포맷 바인딩
	entry_q.bind('<KeyRelease>', lambda e: _format_q_entry(e))
	entry_q.bind('<FocusOut>', lambda e: _format_q_entry(e))

	tk.Label(frm, text="정압 Δp (mmAq/m):").grid(row=1, column=0, sticky='w')
	entry_dp = tk.Entry(frm, width=12)
	entry_dp.grid(row=1, column=1, sticky='w', padx=6, pady=4)
	entry_dp.insert(0, "0.1")

	tk.Label(frm, text="Aspect Ratio (b/a):").grid(row=2, column=0, sticky='w')
	combo_ar = ttk.Combobox(frm, values=["1","2","3","4","6","8"], width=8, state='readonly')
	combo_ar.grid(row=2, column=1, sticky='w', padx=6, pady=4)
	combo_ar.set("2")

	btn_calc = tk.Button(frm, text="계산", command=calculate_and_show)
	btn_calc.grid(row=3, column=0, columnspan=2, pady=8)

	# 결과
	result_var = tk.StringVar()
	result_label = tk.Label(frm, textvariable=result_var, justify='left', anchor='w', bg='white', bd=1, relief='solid', padx=6, pady=6)
	result_label.grid(row=4, column=0, columnspan=2, sticky='we')

	root.protocol("WM_DELETE_WINDOW", on_close)
	root.mainloop()


