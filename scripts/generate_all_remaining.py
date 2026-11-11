import os
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# Font references
FONT_BOLD = "C:/Windows/Fonts/segoeuib.ttf"
FONT_REG = "C:/Windows/Fonts/segoeui.ttf"
FONT_SEMI = "C:/Windows/Fonts/seguisb.ttf"
FONT_MONO = "C:/Windows/Fonts/consola.ttf"

def render_banner(config):
    w, h = 1280, 640
    img = Image.new("RGBA", (w, h), config["bg_color"])
    draw = ImageDraw.Draw(img)

    # 1. Subtle Cyber Grid
    grid_color = config["grid_color"]
    grid_size = 40
    for x in range(0, w, grid_size):
        draw.line([(x, 0), (x, h)], fill=grid_color, width=1)
    for y in range(0, h, grid_size):
        draw.line([(0, y), (w, y)], fill=grid_color, width=1)

    # 2. Glowing Ambient Orbs
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    glow_draw.ellipse(config["glow_1_rect"], fill=config["glow_1_color"])
    glow_draw.ellipse(config["glow_2_rect"], fill=config["glow_2_color"])
    glow = glow.filter(ImageFilter.GaussianBlur(60))
    img = Image.alpha_composite(img, glow)
    draw = ImageDraw.Draw(img)

    # Fonts
    title_font = ImageFont.truetype(FONT_BOLD, 74)
    subtitle_font = ImageFont.truetype(FONT_SEMI, 21)
    desc_font = ImageFont.truetype(FONT_REG, 17)
    badge_font = ImageFont.truetype(FONT_BOLD, 13)
    pill_font = ImageFont.truetype(FONT_SEMI, 15)
    card_title_font = ImageFont.truetype(FONT_BOLD, 18)
    stat_label_font = ImageFont.truetype(FONT_REG, 15)
    stat_val_font = ImageFont.truetype(FONT_BOLD, 16)
    mono_font = ImageFont.truetype(FONT_MONO, 13)

    # Left Badge
    badge_x, badge_y = 80, 95
    badge_w, badge_h = config["badge_width"], 36
    draw.rounded_rectangle([badge_x, badge_y, badge_x + badge_w, badge_y + badge_h], radius=18, 
                           fill=config["badge_bg"], outline=config["badge_border"], width=1)
    draw.ellipse([badge_x + 14, badge_y + 13, badge_x + 24, badge_y + 23], fill=config["accent_color"])
    draw.text((badge_x + 34, badge_y + 8), config["badge_text"], font=badge_font, fill=config["accent_light"])

    # Title with split highlight
    title_y = 150
    t_prefix, t_highlight = config["title_parts"]
    draw.text((80, title_y), t_prefix, font=title_font, fill=(255, 255, 255, 255))
    prefix_w = draw.textlength(t_prefix, font=title_font)
    draw.text((80 + prefix_w, title_y), t_highlight, font=title_font, fill=config["accent_color"])

    # Subtitle & Sub-tagline
    draw.text((82, 245), config["subtitle"], font=subtitle_font, fill=(148, 163, 184, 255))
    draw.text((82, 280), config["tagline"], font=desc_font, fill=(100, 116, 139, 255))

    # Feature Pills
    pill_y = 345
    for i, pill in enumerate(config["pills"]):
        px = 82 if (i % 2 == 0) else 330
        py = pill_y + (i // 2) * 52
        draw.rounded_rectangle([px, py, px + 235, py + 42], radius=10,
                               fill=(255, 255, 255, 12), outline=(255, 255, 255, 25), width=1)
        draw.text((px + 16, py + 10), pill, font=pill_font, fill=(226, 232, 240, 255))

    # Verified Footer
    draw.text((82, 530), config["footer"], font=desc_font, fill=(71, 85, 105, 255))

    # Right Card
    cx, cy = 680, 85
    cw, ch = 520, 470

    card_overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    c_draw = ImageDraw.Draw(card_overlay)
    c_draw.rounded_rectangle([cx, cy, cx + cw, cy + ch], radius=24,
                             fill=config["card_bg"], outline=config["card_border"], width=2)
    card_overlay = card_overlay.filter(ImageFilter.GaussianBlur(1))
    img = Image.alpha_composite(img, card_overlay)
    draw = ImageDraw.Draw(img)

    draw.rounded_rectangle([cx, cy, cx + cw, cy + ch], radius=24,
                           fill=None, outline=config["card_border"], width=2)

    # Card Header
    draw.text((cx + 28, cy + 24), config["card_header"], font=card_title_font, fill=(248, 250, 252, 255))
    # Header Status Badge
    draw.rounded_rectangle([cx + cw - 140, cy + 22, cx + cw - 28, cy + 50], radius=8,
                           fill=config["badge_bg"], outline=config["badge_border"], width=1)
    draw.text((cx + cw - 130, cy + 27), config["card_status"], font=badge_font, fill=config["accent_light"])

    # Divider
    draw.line([(cx + 28, cy + 66), (cx + cw - 28, cy + 66)], fill=(255, 255, 255, 25), width=1)

    # Metrics
    for i, (label, val, col) in enumerate(config["metrics"]):
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
    
    for idx, (t_text, t_color) in enumerate(config["terminal_lines"]):
        draw.text((cx + 44, ty + 14 + idx * 24), t_text, font=mono_font, fill=t_color)

    # Save
    final_img = img.convert("RGB")
    final_img.save(config["output_path"], "JPEG", quality=95)
    print(f"Generated {config['output_path']}")

configs = [
    # 1. portfolio-website
    {
        "output_path": "assets/social_previews/portfolio_website_preview.jpg",
        "bg_color": (9, 11, 28, 255),
        "grid_color": (129, 140, 248, 12),
        "glow_1_rect": [800, 40, 1250, 490],
        "glow_1_color": (99, 102, 241, 45),
        "glow_2_rect": [50, 350, 500, 800],
        "glow_2_color": (6, 182, 212, 35),
        "badge_width": 310,
        "badge_bg": (99, 102, 241, 30),
        "badge_border": (99, 102, 241, 90),
        "badge_text": "DEVELOPER PORTFOLIO & LAB",
        "accent_color": (129, 140, 248, 255),
        "accent_light": (199, 210, 254, 255),
        "title_parts": ("Mazonia", " .dev"),
        "subtitle": "Full-Stack Developer • Cybersecurity & AI Engineer",
        "tagline": "Autonomous Trading Bots • Zero-Trust Security • Spatial Vision AI",
        "pills": [
            "🧠 Autonomous AI Bots",
            "🛡️ Offensive Cyber Defense",
            "⚡ Real-Time WebSockets",
            "🚀 High-Scale APIs"
        ],
        "footer": "TypeScript  •  Python  •  FastAPI  •  Flutter  •  Active Directory Labs",
        "card_bg": (15, 23, 42, 215),
        "card_border": (99, 102, 241, 90),
        "card_header": "💻 Mazonia Engineering Portfolio",
        "card_status": "PORTFOLIO LIVE",
        "metrics": [
            ("Core Focus", "Autonomous AI & Cybersecurity", (129, 140, 248, 255)),
            ("Algorithmic Bots", "MT5 Gold AI • Telegram Daemons", (56, 189, 248, 255)),
            ("Security Audits", "OWASP API Top 10 • Red Teaming", (52, 211, 153, 255)),
            ("Code Architecture", "100% Production Ready & Tested", (244, 114, 182, 255)),
        ],
        "terminal_lines": [
            ("> mazonia.profile.get_focus()", (129, 140, 248, 255)),
            ("[+] Systems: Quantitative Trading, APIs & Distributed DAOs", (226, 232, 240, 255)),
            ("[+] Security: Certified Red Team Penetration Testing Labs", (52, 211, 153, 255)),
            ("[★] Status: Open for institutional and visionary projects", (56, 189, 248, 255)),
        ]
    },

    # 2. vehicle-rental-system (ApexDrive)
    {
        "output_path": "assets/social_previews/vehicle_rental_system_preview.jpg",
        "bg_color": (10, 15, 29, 255),
        "grid_color": (14, 165, 233, 12),
        "glow_1_rect": [800, 40, 1250, 490],
        "glow_1_color": (14, 165, 233, 40),
        "glow_2_rect": [50, 350, 500, 800],
        "glow_2_color": (99, 102, 241, 35),
        "badge_width": 310,
        "badge_bg": (14, 165, 233, 30),
        "badge_border": (14, 165, 233, 90),
        "badge_text": "FLEET & RESERVATION ENGINE",
        "accent_color": (14, 165, 233, 255),
        "accent_light": (186, 230, 253, 255),
        "title_parts": ("Apex", "Drive"),
        "subtitle": "Enterprise Java OOP Fleet & Vehicle Rental System",
        "tagline": "Dynamic Reservation Scheduling • GPS Fleet Telemetry • Smart Billing",
        "pills": [
            "🚗 Fleet Lifecycle Sync",
            "📅 Reservation Dispatch",
            "💳 Automated Deposits",
            "📊 Vehicle Maintenance"
        ],
        "footer": "Java 17+  •  Object-Oriented Design  •  Swing / JavaFX  •  MySQL",
        "card_bg": (15, 23, 42, 215),
        "card_border": (14, 165, 233, 90),
        "card_header": "🚘 ApexDrive Fleet Telemetry",
        "card_status": "FLEET ONLINE",
        "metrics": [
            ("Active Fleet", "450 Vehicles Tracked", (14, 165, 233, 255)),
            ("Dispatch Latency", "< 85ms Real-Time Allocation", (52, 211, 153, 255)),
            ("Billing Engine", "Tiered Dynamic Pricing Engine", (129, 140, 248, 255)),
            ("Predictive Service", "100% Maintenance Cleared", (244, 114, 182, 255)),
        ],
        "terminal_lines": [
            ("$ java -jar apexdrive.jar --dispatch-fleet", (14, 165, 233, 255)),
            ("[OK] Connected to Central Vehicle Fleet Database", (226, 232, 240, 255)),
            ("[OK] Dynamic reservation scheduler loaded (0 conflicts)", (52, 211, 153, 255)),
            ("[★] Fleet Telemetry Status: OPTIMAL & DISPATCH READY", (186, 230, 253, 255)),
        ]
    },

    # 3. library-management-system (Bibliotheca)
    {
        "output_path": "assets/social_previews/library_management_system_preview.jpg",
        "bg_color": (8, 20, 18, 255),
        "grid_color": (16, 185, 129, 12),
        "glow_1_rect": [800, 40, 1250, 490],
        "glow_1_color": (16, 185, 129, 45),
        "glow_2_rect": [50, 350, 500, 800],
        "glow_2_color": (217, 119, 6, 35),
        "badge_width": 310,
        "badge_bg": (16, 185, 129, 30),
        "badge_border": (16, 185, 129, 90),
        "badge_text": "ACADEMIC KNOWLEDGE SYSTEM",
        "accent_color": (52, 211, 153, 255),
        "accent_light": (167, 243, 208, 255),
        "title_parts": ("Biblio", "theca"),
        "subtitle": "Enterprise PHP & MySQL Library Management System",
        "tagline": "Catalog Discovery • RFID/Barcode Circulation • Overdue Analytics",
        "pills": [
            "📚 50,000+ Titles Indexed",
            "🔍 Full-Text Catalog Search",
            "🏷️ Circulation QR/Barcodes",
            "💰 Fine & Penalty Engine"
        ],
        "footer": "PHP 8.2+  •  MySQL InnoDB  •  Bootstrap UI  •  RBAC Auth",
        "card_bg": (15, 28, 24, 215),
        "card_border": (16, 185, 129, 90),
        "card_header": "📖 Bibliotheca Circulation Hub",
        "card_status": "CATALOG READY",
        "metrics": [
            ("Catalog Volumes", "52,400 Records Active", (52, 211, 153, 255)),
            ("Search Latency", "1.4ms InnoDB Full-Text Index", (56, 189, 248, 255)),
            ("Active Loans", "Dynamic Borrower Tracking", (251, 191, 36, 255)),
            ("Member Access", "Role-Based Student/Staff Auth", (167, 139, 250, 255)),
        ],
        "terminal_lines": [
            ("$ php artisan bibliotheca:sync-loans", (52, 211, 153, 255)),
            ("[INFO] Indexed 52,400 catalog volumes across branches", (226, 232, 240, 255)),
            ("[INFO] Automated SMS & Email return reminders dispatched", (251, 191, 36, 255)),
            ("[★] Database Integrity: VERIFIED (0 record discrepancies)", (167, 243, 208, 255)),
        ]
    },

    # 4. photonx
    {
        "output_path": "assets/social_previews/photonx_preview.jpg",
        "bg_color": (12, 10, 26, 255),
        "grid_color": (217, 70, 239, 12),
        "glow_1_rect": [800, 40, 1250, 490],
        "glow_1_color": (217, 70, 239, 45),
        "glow_2_rect": [50, 350, 500, 800],
        "glow_2_color": (6, 182, 212, 40),
        "badge_width": 310,
        "badge_bg": (217, 70, 239, 30),
        "badge_border": (217, 70, 239, 90),
        "badge_text": "QUANTUM OPTICAL SIMULATION",
        "accent_color": (232, 121, 249, 255),
        "accent_light": (245, 208, 254, 255),
        "title_parts": ("Photon", "X"),
        "subtitle": "High-Energy Optical Computing & Photonics Engine",
        "tagline": "Laser Coherence Modeling • Prismatic FDTD Solvers • Terabit Channels",
        "pills": [
            "⚡ Sub-Nanosecond Latency",
            "🌈 Prismatic Refraction",
            "🔬 Wavefront Simulation",
            "💡 Terabit Optical Interconnect"
        ],
        "footer": "Optical Computing  •  Quantum Photonics  •  FDTD Wave Solvers  •  CUDA",
        "card_bg": (20, 15, 36, 215),
        "card_border": (217, 70, 239, 90),
        "card_header": "🔮 PhotonX Optical Core",
        "card_status": "BEAM LOCKED",
        "metrics": [
            ("Laser Coherence", "99.98% Phase Fidelity", (232, 121, 249, 255)),
            ("Optical Interconnect", "Terabit/sec Channel Bandwidth", (56, 189, 248, 255)),
            ("Solver Timestep", "0.02 Femtosecond Resolution", (52, 211, 153, 255)),
            ("Phase Noise", "Zero Optical Jitter Gate", (251, 191, 36, 255)),
        ],
        "terminal_lines": [
            ("$ photonx --simulate-beam --wavelength=1550nm", (232, 121, 249, 255)),
            ("[OPTICS] Wavefront matrix converged (FDTD 3D Mesh)", (226, 232, 240, 255)),
            ("[OPTICS] Prismatic refractive index validated: n=1.444", (56, 189, 248, 255)),
            ("[★] Quantum optical channel verified: BEAM COHERENT", (245, 208, 254, 255)),
        ]
    }
]

for cfg in configs:
    render_banner(cfg)
