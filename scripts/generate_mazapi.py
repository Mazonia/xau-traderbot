import math
from PIL import Image, ImageDraw, ImageFont, ImageFilter

def create_mazapi_banner(output_path):
    w, h = 1280, 640
    # Create base dark image
    img = Image.new("RGBA", (w, h), (8, 13, 26, 255))
    draw = ImageDraw.Draw(img)

    # 1. Subtle Cyber Grid
    grid_color = (16, 185, 129, 12)
    grid_size = 40
    for x in range(0, w, grid_size):
        draw.line([(x, 0), (x, h)], fill=grid_color, width=1)
    for y in range(0, h, grid_size):
        draw.line([(0, y), (w, y)], fill=grid_color, width=1)

    # 2. Glowing Ambient Orbs
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    
    # Emerald glow on right
    glow_draw.ellipse([800, 40, 1250, 490], fill=(16, 185, 129, 45))
    # Cyan glow on bottom left
    glow_draw.ellipse([50, 350, 500, 800], fill=(6, 182, 212, 35))
    glow = glow.filter(ImageFilter.GaussianBlur(60))
    img = Image.alpha_composite(img, glow)
    draw = ImageDraw.Draw(img)

    # Load system fonts
    font_bold = "C:/Windows/Fonts/segoeuib.ttf"
    font_reg = "C:/Windows/Fonts/segoeui.ttf"
    font_semi = "C:/Windows/Fonts/seguisb.ttf"
    font_mono = "C:/Windows/Fonts/consola.ttf"

    title_font = ImageFont.truetype(font_bold, 76)
    subtitle_font = ImageFont.truetype(font_semi, 22)
    desc_font = ImageFont.truetype(font_reg, 18)
    badge_font = ImageFont.truetype(font_bold, 13)
    pill_font = ImageFont.truetype(font_semi, 15)
    card_title_font = ImageFont.truetype(font_bold, 18)
    stat_label_font = ImageFont.truetype(font_reg, 15)
    stat_val_font = ImageFont.truetype(font_bold, 16)
    mono_font = ImageFont.truetype(font_mono, 13)

    # Left Side: Header Badge
    badge_x, badge_y = 80, 95
    badge_w, badge_h = 320, 36
    draw.rounded_rectangle([badge_x, badge_y, badge_x + badge_w, badge_y + badge_h], radius=18, 
                           fill=(16, 185, 129, 30), outline=(16, 185, 129, 90), width=1)
    draw.ellipse([badge_x + 14, badge_y + 13, badge_x + 24, badge_y + 23], fill=(16, 185, 129, 255))
    draw.text((badge_x + 34, badge_y + 8), "ENTERPRISE API & AI SECURITY", font=badge_font, fill=(52, 211, 153, 255))

    # Title: MazAPI
    title_y = 150
    draw.text((80, title_y), "Maz", font=title_font, fill=(255, 255, 255, 255))
    maz_w = draw.textlength("Maz", font=title_font)
    draw.text((80 + maz_w, title_y), "API", font=title_font, fill=(16, 185, 129, 255))

    # Subtitle & Description
    draw.text((82, 245), "Autonomous Security Intelligence Platform", font=subtitle_font, fill=(148, 163, 184, 255))
    draw.text((82, 280), "AST Route Discovery • AI-BOM Supply Chain • MCP Security", font=desc_font, fill=(100, 116, 139, 255))

    # Feature Pills
    pills = [
        "🛡️ AST Route Discovery",
        "📦 AI-BOM Dependency Audit",
        "⚡ MCP Protocol Guard",
        "🎯 OWASP API Top 10 DAST"
    ]
    pill_y = 345
    for i, pill in enumerate(pills):
        px = 82 if (i % 2 == 0) else 330
        py = pill_y + (i // 2) * 52
        draw.rounded_rectangle([px, py, px + 235, py + 42], radius=10,
                               fill=(255, 255, 255, 12), outline=(255, 255, 255, 25), width=1)
        draw.text((px + 16, py + 10), pill, font=pill_font, fill=(226, 232, 240, 255))

    # Verified Footer Badge
    draw.text((82, 530), "Python 3.11+  |  OWASP API 2024  |  Multi-Agent Hardened", font=desc_font, fill=(71, 85, 105, 255))

    # Right Side: Interactive Glassmorphic Security HUD Card
    cx, cy = 680, 85
    cw, ch = 520, 470

    # Glass Card Background
    card_overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    c_draw = ImageDraw.Draw(card_overlay)
    c_draw.rounded_rectangle([cx, cy, cx + cw, cy + ch], radius=24,
                             fill=(15, 23, 42, 210), outline=(16, 185, 129, 90), width=2)
    card_overlay = card_overlay.filter(ImageFilter.GaussianBlur(1))
    img = Image.alpha_composite(img, card_overlay)
    draw = ImageDraw.Draw(img)

    # Redraw crisp border
    draw.rounded_rectangle([cx, cy, cx + cw, cy + ch], radius=24,
                           fill=None, outline=(16, 185, 129, 100), width=2)

    # Card Header
    draw.text((cx + 28, cy + 24), "🛡️ MazAPI Live Security Engine", font=card_title_font, fill=(248, 250, 252, 255))
    # Active Badge
    draw.rounded_rectangle([cx + cw - 140, cy + 22, cx + cw - 28, cy + 50], radius=8,
                           fill=(16, 185, 129, 35), outline=(16, 185, 129, 180), width=1)
    draw.text((cx + cw - 128, cy + 27), "SHIELD ACTIVE", font=badge_font, fill=(52, 211, 153, 255))

    # Divider
    draw.line([(cx + 28, cy + 66), (cx + cw - 28, cy + 66)], fill=(255, 255, 255, 25), width=1)

    # Telemetry Rows
    metrics = [
        ("AST Route Analysis", "1,420 Endpoints Mapped", (56, 189, 248, 255)),
        ("AI-BOM Supply Chain", "42 Dependencies Verified", (167, 139, 250, 255)),
        ("MCP Protocol Scanner", "Zero Leakage Gate PASSED", (52, 211, 153, 255)),
        ("OWASP API 2024 Audit", "10 / 10 Vectors Cleared", (16, 185, 129, 255)),
    ]

    for i, (label, val, col) in enumerate(metrics):
        ry = cy + 85 + i * 56
        draw.rounded_rectangle([cx + 28, ry, cx + cw - 28, ry + 46], radius=10,
                               fill=(255, 255, 255, 10), outline=(255, 255, 255, 20), width=1)
        draw.text((cx + 44, ry + 12), label, font=stat_label_font, fill=(148, 163, 184, 255))
        val_w = draw.textlength(val, font=stat_val_font)
        draw.text((cx + cw - 44 - val_w, ry + 12), val, font=stat_val_font, fill=col)

    # Terminal CLI Preview Box
    ty = cy + 325
    draw.rounded_rectangle([cx + 28, ty, cx + cw - 28, ty + 115], radius=12,
                           fill=(0, 0, 0, 160), outline=(255, 255, 255, 25), width=1)
    draw.text((cx + 44, ty + 14), "$ mazapi scan --all --mcp-guard --ai-bom", font=mono_font, fill=(52, 211, 153, 255))
    draw.text((cx + 44, ty + 38), "[✓] AST Route Inspection: 0 vulnerabilities found", font=mono_font, fill=(226, 232, 240, 255))
    draw.text((cx + 44, ty + 62), "[✓] MCP Protocol Sandbox: Enforced with 0 CVE leaks", font=mono_font, fill=(56, 189, 248, 255))
    draw.text((cx + 44, ty + 86), "[★] Overall Security Posture: INSTITUTIONAL GRADE (A+)", font=mono_font, fill=(52, 211, 153, 255))

    # Convert to RGB and save
    final_img = img.convert("RGB")
    final_img.save(output_path, "JPEG", quality=95)
    print(f"Saved to {output_path}")

create_mazapi_banner("assets/social_previews/mazapi_preview.jpg")
