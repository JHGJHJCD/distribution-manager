"""Generate icon.ico — run once: python create_icon.py"""
from PIL import Image, ImageDraw
import os


def _draw(px: int) -> Image.Image:
    s = px * 4  # supersample for smooth edges
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Blue rounded-square background
    d.rounded_rectangle([0, 0, s - 1, s - 1], radius=s // 6,
                        fill=(21, 101, 192, 255))

    pad = s // 6
    lw  = max(2, s // 20)
    W   = (255, 255, 255, 255)
    Wf  = (255, 255, 255, 55)   # faint white fill

    bx1, bx2 = pad, s - pad
    peak_y   = pad
    body_y1  = pad + (s - 2 * pad) // 3
    body_y2  = s - pad
    mid_x    = s // 2

    # Box body (filled faint + white outline)
    d.rectangle([bx1, body_y1, bx2, body_y2], fill=Wf, outline=W, width=lw)

    # Left lid flap
    d.polygon([(bx1, body_y1), (mid_x, peak_y), (mid_x, body_y1)],
              fill=Wf, outline=W)
    # Right lid flap
    d.polygon([(bx2, body_y1), (mid_x, peak_y), (mid_x, body_y1)],
              fill=Wf, outline=W)

    # Horizontal tape stripe across body
    ty = body_y1 + (body_y2 - body_y1) // 2
    d.rectangle([bx1, ty - lw, bx2, ty + lw], fill=W)
    # Vertical tape
    d.rectangle([mid_x - lw, body_y1, mid_x + lw, body_y2], fill=W)

    return img.resize((px, px), Image.LANCZOS)


def create_icon(dest: str) -> str:
    sizes = [256, 128, 64, 48, 32, 16]
    imgs  = [_draw(s) for s in sizes]
    imgs[0].save(dest, format="ICO",
                 sizes=[(s, s) for s in sizes],
                 append_images=imgs[1:])
    return dest


if __name__ == "__main__":
    out = os.path.join(os.path.dirname(__file__), "icon.ico")
    create_icon(out)
    print(f"נוצר: {out}")
