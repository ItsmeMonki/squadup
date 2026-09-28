#!/usr/bin/env python3
"""
apply_design.py — установка дизайн-ассетов SQUADUP.

Что делает:
  1. читает design/tokens.json → пишет static/theme.css (цвета, радиусы, свечение, шрифты);
  2. копирует шрифты design/fonts/* → static/fonts/ и подключает @font-face;
  3. копирует логотипы design/brand/*.svg → static/brand/;
  4. генерирует из design/brand/icon-master.png все размеры иконок приложения
     (192, 512, maskable 512, apple-touch 180, favicon 32/64, .ico);
  5. копирует иконки интерфейса design/icons/*.svg → static/icons/ui/;
  6. обновляет theme_color / background_color в static/manifest.webmanifest;
  7. подключает theme.css в static/index.html (один раз, после встроенных стилей);
  8. печатает отчёт: что установлено, чего не хватает.

Запуск:
    python3 design/apply_design.py            # применить всё, что найдено
    python3 design/apply_design.py --check    # только проверить, ничего не менять
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DESIGN = os.path.join(BASE, "design")
STATIC = os.path.join(BASE, "static")

ICON_SIZES = [(192, "icon-192.png"), (512, "icon-512.png"),
              (180, "apple-touch-icon.png"), (64, "favicon-64.png"), (32, "favicon-32.png")]
ICON_SLOTS = ["search", "squads", "chat", "profile", "send", "bell", "mic", "mic-off",
              "star", "warn", "block", "plus", "close", "check"]

installed: list[str] = []
missing: list[str] = []
notes: list[str] = []


def say(ok: bool, text: str):
    print(f"  {'✅' if ok else '⚠️ '} {text}")


def hex_ok(value: str) -> bool:
    return bool(re.fullmatch(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})", (value or "").strip()))


def load_tokens() -> dict:
    path = os.path.join(DESIGN, "tokens.json")
    if not os.path.isfile(path):
        notes.append("design/tokens.json не найден — цвета и шрифты останутся текущими")
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception as exc:  # noqa: BLE001
        notes.append(f"tokens.json не читается ({exc}) — пропускаю")
        return {}
    return data


def build_theme_css(tokens: dict) -> str:
    colors = {k: v for k, v in (tokens.get("colors") or {}).items()
              if isinstance(v, str) and v.strip() and (hex_ok(v) or v.startswith(("rgba(", "rgb(", "linear-gradient", "radial-gradient")))}
    radius = tokens.get("radius") or {}
    glow = tokens.get("glow") or {}
    fonts = tokens.get("fonts") or {}
    sizes = fonts.get("sizes") or {}
    pwa = tokens.get("pwa") or {}

    lines = ["/* theme.css — генерируется design/apply_design.py из design/tokens.json.",
             "   Не правь руками: правь tokens.json и запусти скрипт заново. */",
             ""]

    # @font-face для локальных файлов: поддерживаем и старый плоский список, и два шрифта
    font_entries = []
    if fonts.get("files"):
        for f in fonts["files"]:
            if not f.get("family"):
                f = dict(f, family=fonts.get("stack", "").split(",")[0].strip('" '))
            font_entries.append(f)
    for key in ("heading", "body"):
        block = fonts.get(key) or {}
        for f in block.get("files") or []:
            if not f.get("family"):
                f = dict(f, family=block.get("family") or "")
            font_entries.append(f)
    seen = set()
    for f in font_entries:
        fam, fn = (f.get("family") or "").strip(), (f.get("file") or "").strip()
        if not fam or not fn or (fam, fn, f.get("weight")) in seen:
            continue
        seen.add((fam, fn, f.get("weight")))
        lines.append(f"""@font-face{{font-family:"{fam}";src:url("/fonts/{fn}") format("woff2");
  font-weight:{f.get('weight', 400)};font-style:{f.get('style', 'normal')};font-display:swap}}""")
    if seen:
        lines.append("")

    lines.append(":root{")
    mapping = {
        "bg": "--bg", "bg-deep": "--bg-deep", "surface": "--panel", "surface-2": "--panel-2",
        "border": "--border", "border-strong": "--border-strong", "text": "--text",
        "muted": "--muted", "muted-2": "--muted-2", "accent": "--acc", "accent-2": "--acc-2",
        "danger": "--acc-3", "success": "--green", "warning": "--amber",
        "accent-soft": "--acc-soft", "accent-contrast": "--acc-contrast",
    }
    for key, var in mapping.items():
        if colors.get(key):
            lines.append(f"  {var}:{colors[key]};")
    if radius.get("card"):
        lines.append(f"  --radius:{radius['card']};")
    if radius.get("button"):
        lines.append(f"  --radius-btn:{radius['button']};")
    if radius.get("pill"):
        lines.append(f"  --radius-pill:{radius['pill']};")
    if glow.get("shadow") or glow.get("card"):
        lines.append(f"  --shadow:{glow.get('shadow') or glow['card']};")
    if glow.get("accent"):
        lines.append(f"  --glow:{glow['accent']};")
    lines.append("}")
    lines.append("")

    body_stack = (fonts.get("body") or {}).get("stack") or fonts.get("stack")
    head_stack = (fonts.get("heading") or {}).get("stack")
    if body_stack:
        lines.append(f"body{{font-family:{body_stack};font-size:{sizes.get('base', '15px')};line-height:{sizes.get('line-height', '1.5')}}}")
        lines.append(f".hint,.meta,.page-sub,.lbl{{font-size:{sizes.get('small', '13px')}}}")
    if head_stack:
        lines.append(f"h1,h2,h3,h4,.hero h1,.page-title,.nick,.stat b,.mini b,.rate b,.gchip{{font-family:{head_stack}}}")
    if sizes.get("h1"):
        lines.append(".hero h1,.page-title{letter-spacing:-.02em}")
    lines.append("")
    if colors.get("accent"):
        lines.append("/* неоновый акцент: свечение у главных кнопок и активных состояний */")
        lines.append(".btn.primary{box-shadow:var(--glow, 0 0 24px rgba(255,106,0,.35));"
                     "border-color:transparent}")
        lines.append(".nav-btn.active{border-color:var(--acc);color:var(--text)}")
        lines.append(".card:hover{border-color:var(--border-strong)}")
        lines.append("")
    del pwa
    return "\n".join(lines)


def install_covers(check: bool) -> None:
    """Свои постеры игр: design/covers/<id>.(jpg|png|webp) → static/covers/.
    Файл с именем = id игры из каталога (cs2.jpg, dota2.jpg, valorant.jpg…) перекрывает
    официальную обложку. Пропорции лучше 2:3 (например 1200×1800)."""
    src = os.path.join(DESIGN, "covers")
    dst = os.path.join(STATIC, "covers")
    files = [f for f in os.listdir(src) if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))] if os.path.isdir(src) else []
    if not files:
        notes.append("своих постеров игр нет — оставляю официальные обложки")
        return
    if not check:
        os.makedirs(dst, exist_ok=True)
    for f in files:
        if not check:
            shutil.copy2(os.path.join(src, f), os.path.join(dst, f))
    done.append(f"постеры игр: {len(files)} шт. → /covers/ ({', '.join(sorted(files)[:6])}{'…' if len(files) > 6 else ''})")


def install_fonts(check: bool) -> None:
    src = os.path.join(DESIGN, "fonts")
    dst = os.path.join(STATIC, "fonts")
    files = [f for f in os.listdir(src) if re.search(r"\.(woff2|woff|ttf|otf)$", f, re.I)] if os.path.isdir(src) else []
    if not files:
        missing.append("шрифты (design/fonts/*.woff2) — нужны два: для заголовков и для текста")
        return
    if not check:
        os.makedirs(dst, exist_ok=True)
        for f in files:
            shutil.copy2(os.path.join(src, f), os.path.join(dst, f))
    installed.append(f"шрифты: {len(files)} файл(ов) → /fonts/  ({', '.join(files[:4])}{'…' if len(files) > 4 else ''})")


def install_brand(check: bool) -> None:
    src = os.path.join(DESIGN, "brand")
    dst = os.path.join(STATIC, "brand")
    svgs = [f for f in os.listdir(src) if f.lower().endswith(".svg")] if os.path.isdir(src) else []
    if svgs:
        if not check:
            os.makedirs(dst, exist_ok=True)
            for f in svgs:
                shutil.copy2(os.path.join(src, f), os.path.join(dst, f))
        installed.append(f"логотипы: {', '.join(svgs)} → /brand/")
    else:
        missing.append("логотип (design/brand/logo.svg, wordmark.svg)")

    master = os.path.join(src, "icon-master.png")
    if not os.path.isfile(master):
        missing.append("мастер иконки (design/brand/icon-master.png, 1024×1024) — без него иконки приложения не обновятся")
        return
    if check:
        installed.append("мастер иконки найден — будут сгенерированы все размеры")
        return
    try:
        from PIL import Image
    except ImportError:
        notes.append("нет библиотеки Pillow — иконки не сгенерированы (установлю и повторю)")
        return
    tokens = load_tokens()
    bg = ((tokens.get("pwa") or {}).get("background_color") or "#050506").strip()
    img = Image.open(master).convert("RGBA")
    side = min(img.size)
    left = (img.width - side) // 2
    top = (img.height - side) // 2
    img = img.crop((left, top, left + side, top + side))
    icons_dir = os.path.join(STATIC, "icons")
    os.makedirs(icons_dir, exist_ok=True)
    for size, name in ICON_SIZES:
        img.resize((size, size), Image.LANCZOS).save(os.path.join(icons_dir, name))
    # maskable: знак занимает ~76% холста, остальное — фон (безопасная зона Android)
    inner = int(512 * 0.76)
    canvas = Image.new("RGBA", (512, 512), bg)
    canvas.paste(img.resize((inner, inner), Image.LANCZOS), ((512 - inner) // 2, (512 - inner) // 2), img.resize((inner, inner), Image.LANCZOS))
    canvas.save(os.path.join(icons_dir, "icon-maskable-512.png"))
    img.resize((256, 256), Image.LANCZOS).save(os.path.join(icons_dir, "squadup.ico"),
                                               sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    installed.append("иконки приложения: 192, 512, maskable 512, apple-touch 180, favicon 32/64, .ico")


def install_ui_icons(check: bool) -> None:
    """Иконки интерфейса не обязательны: по решению дизайнера эмодзи убраны,
    интерфейс строится на типографике. Функция оставлена на случай, если набор всё же появится."""
    src = os.path.join(DESIGN, "icons")
    dst = os.path.join(STATIC, "icons", "ui")
    svgs = [f for f in os.listdir(src) if f.lower().endswith(".svg")] if os.path.isdir(src) else []
    if not svgs:
        notes.append("иконки интерфейса не нужны (интерфейс без иконок) — пропускаю")
        return
    if not check:
        os.makedirs(dst, exist_ok=True)
        for f in svgs:
            shutil.copy2(os.path.join(src, f), os.path.join(dst, f))
    have = {os.path.splitext(f)[0] for f in svgs}
    gaps = [s for s in ICON_SLOTS if s not in have]
    installed.append(f"иконки интерфейса: {len(svgs)} файл(ов) → /icons/ui/")
    if gaps:
        missing.append("иконки из обязательного списка: " + ", ".join(gaps))


def update_manifest(check: bool) -> None:
    tokens = load_tokens()
    pwa = tokens.get("pwa") or {}
    path = os.path.join(STATIC, "manifest.webmanifest")
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as fh:
        man = json.load(fh)
    changed = []
    for key in ("theme_color", "background_color"):
        val = (pwa.get(key) or "").strip()
        if val and hex_ok(val) and man.get(key) != val:
            man[key] = val
            changed.append(f"{key}={val}")
    if changed and not check:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(man, fh, ensure_ascii=False, indent=2)
    if changed:
        installed.append("манифест PWA: " + ", ".join(changed))


def wire_theme_css(check: bool) -> None:
    path = os.path.join(STATIC, "index.html")
    with open(path, encoding="utf-8") as fh:
        html = fh.read()
    if "/theme.css" in html:
        installed.append("theme.css уже подключён в index.html")
        return
    marker = "</style>"
    idx = html.find(marker)
    if idx == -1:
        notes.append("в index.html не найден </style> — подключи theme.css вручную")
        return
    if not check:
        insert_at = idx + len(marker)
        html = html[:insert_at] + '\n<link rel="stylesheet" href="/theme.css">' + html[insert_at:]
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(html)
    installed.append("theme.css подключён в index.html (после встроенных стилей)")


def main() -> int:
    check = "--check" in sys.argv
    print("=== ДИЗАЙН-АССЕТЫ: " + ("ПРОВЕРКА" if check else "УСТАНОВКА") + " ===\n")
    tokens = load_tokens()

    if tokens and not check:
        css = build_theme_css(tokens)
        target = os.path.join(STATIC, "theme.css")
        if os.path.isfile(target):
            with open(target, encoding="utf-8") as fh:
                if fh.read() == css:
                    installed.append("theme.css без изменений")
                else:
                    with open(target, "w", encoding="utf-8") as fh:
                        fh.write(css)
                    installed.append("theme.css обновлён из tokens.json")
        else:
            with open(target, "w", encoding="utf-8") as fh:
                fh.write(css)
            installed.append("theme.css создан из tokens.json")
    elif tokens:
        colors = tokens.get("colors") or {}
        acc = colors.get("accent") or "—"
        bg = colors.get("bg") or "—"
        installed.append(f"tokens.json: акцент {acc}, фон {bg}, шрифт {(tokens.get('fonts') or {}).get('stack', '—')[:40]}…")

    install_fonts(check)

    install_covers(check)
    install_brand(check)
    install_ui_icons(check)
    update_manifest(check)
    wire_theme_css(check)

    print("ГОТОВО:" if not check else "НАЙДЕНО:")
    for x in installed:
        print("  ✅ " + x)
    if missing:
        print("\nЖДЁМ ОТ ТЕБЯ:")
        for x in missing:
            print("  • " + x)
    if notes:
        print("\nЗАМЕТКИ:")
        for x in notes:
            print("  · " + x)
    if not missing:
        print("\nВсё на месте — можно прогонять тесты интерфейса.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
