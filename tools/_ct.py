"""精确复现层层叠加的半透明底，并为每个芯片选出最终令牌。"""
def hx(h):
    h = h.lstrip('#')
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

def over(fg, bg, a):
    return tuple(a*f + (1-a)*b for f, b in zip(fg, bg))

def lin(c):
    c = c/255.0
    return c/12.92 if c <= 0.03928 else ((c+0.055)/1.055)**2.4

def lum(rgb):
    r, g, b = [lin(x) for x in rgb]
    return 0.2126*r + 0.7152*g + 0.0722*b

def cr(fg, bg):
    l1, l2 = lum(fg), lum(bg)
    if l1 < l2:
        l1, l2 = l2, l1
    return (l1+0.05)/(l2+0.05)

PANEL  = hx('#FAF8F3')
PANEL2 = hx('#F3EFE6')
PANEL3 = hx('#EAE5D8')
BG     = hx('#EDE9E0')
WARN   = hx('#8A5714')
TEAL   = hx('#0B6B5C')
AMBER  = hx('#8A5714')
ROSE   = hx('#A83E58')
INDIGO = hx('#3B4FA8')

print('=== ans-state 最坏情况：层级叠加后的真实底板 ===')
base = PANEL
for name, a in [('details.answer 5%', 0.05), ('summary hover 9%', 0.09)]:
    base = over(WARN, base, a)
    print(f'  叠加 {name:20s} -> {tuple(round(x,1) for x in base)}  亮={lum(base):.4f}')
print()
for label, chip_a in [('芯片 18% warn', 0.18), ('芯片 16% warn', 0.16), ('芯片 12% warn', 0.12),
                      ('芯片 10% warn', 0.10), ('芯片 0% (仅描边)', 0.0)]:
    b = over(WARN, base, chip_a)
    print(f'  {label:18s} 底={tuple(round(x,1) for x in b)}  当前色 #8A5714 -> {cr(WARN,b):.2f}')
print()
print('  —— 换用更深的琥珀墨色（芯片 18% 底）——')
b18 = over(WARN, base, 0.18)
for h in ['#8A5714', '#7C4D10', '#6E440D', '#603B0A', '#523209']:
    print(f'    {h} -> {cr(hx(h), b18):.2f}')
print()
print('  —— 芯片改用不透明底 color-mix(X 18%, var(--panel)) ——')
for h in ['#8A5714', '#7C4D10', '#6E440D']:
    b = over(WARN, PANEL, 0.18)
    print(f'    {h} -> {cr(hx(h), b):.2f}')
print()
print('  —— 不透明底 + 叠加父级仍为半透明（父级在面板上，芯片不透明 -> 与父级无关）——')
print('    结论：不透明底让对比度与父级叠加完全解耦')
print()

print('=== 逐个芯片：现色 vs 加深一档 vs 加深两档（对各自底板）===')
chips = [
    ('parse-tag (accent 14%)', PANEL2, TEAL,   0.14, ['#0B6B5C', '#0A5F52', '#095349']),
    ('.b-base teal 15%',       PANEL2, TEAL,   0.15, ['#0B6B5C', '#0A5F52', '#095349']),
    ('.b-adv amber 17%',       PANEL2, AMBER,  0.17, ['#8A5714', '#7C4D10', '#6E440D']),
    ('.b-chal rose 16%',       PANEL2, ROSE,   0.16, ['#A83E58', '#98354E', '#882C44']),
    ('.nav-badge warn 20%',    BG,     WARN,   0.20, ['#8A5714', '#7C4D10', '#6E440D']),
    ('.nav-badge on panel2 20%', PANEL2, WARN, 0.20, ['#8A5714', '#7C4D10', '#6E440D']),
]
for name, b0, tok, a, inks in chips:
    b = over(tok, b0, a)
    out = '  '.join(f'{h}:{cr(hx(h), b):.2f}' for h in inks)
    print(f'  {name:26s} {out}')

print()
print('=== indigo 强调色下的 parse-tag（14% 底）===')
for h in ['#3B4FA8', '#33468F', '#2B3C7B']:
    b = over(INDIGO, PANEL2, 0.14)
    print(f'  {h} -> {cr(hx(h), b):.2f}')

print()
print('=== 深色主题回归校验（应保持通过）===')
D_PANEL  = hx('#141F22')
D_PANEL2 = hx('#19272A')
D_BG     = hx('#0D1517')
for name, b0, tok, a in [
    ('parse-tag teal-d', D_PANEL2, hx('#4FD1B4'), 0.14),
    ('.b-base teal-d',   D_PANEL2, hx('#4FD1B4'), 0.15),
    ('.b-adv amber-d',   D_PANEL2, hx('#E5B061'), 0.17),
    ('.b-chal rose-d',   D_PANEL2, hx('#EF8FA6'), 0.16),
    ('.nav-badge warn-d',D_BG,     hx('#E5B061'), 0.20),
]:
    b = over(tok, b0, a)
    print(f'  {name:20s} -> {cr(tok, b):.2f}')
