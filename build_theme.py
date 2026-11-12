"""Build original, deterministic UI materials; Pillow is only needed by maintainers."""
from pathlib import Path
import math
import random
from PIL import Image, ImageDraw, ImageFilter


def build(folder=None):
    folder = folder or Path(__file__).parent / 'theme-assets'
    folder.mkdir(parents=True, exist_ok=True)
    rng = random.Random(31601)
    size = 512
    # Smooth toroidal fractal grain: mineral mottling without directional stripes.
    values=[0.0]*(size*size)
    for cells,amplitude in ((4,4),(8,4),(16,3),(32,2),(64,1.3),(128,.8)):
        grid=[[rng.uniform(-1,1) for _ in range(cells)] for _ in range(cells)]
        for y in range(size):
            gy=y*cells/size;iy=int(gy);fy=gy-iy;fy=fy*fy*(3-2*fy)
            for x in range(size):
                gx=x*cells/size;ix=int(gx);fx=gx-ix;fx=fx*fx*(3-2*fx)
                a=grid[iy][ix]*(1-fx)+grid[iy][(ix+1)%cells]*fx
                b=grid[(iy+1)%cells][ix]*(1-fx)+grid[(iy+1)%cells][(ix+1)%cells]*fx
                values[y*size+x]+=(a*(1-fy)+b*fy)*amplitude
    stone = Image.new('RGB', (size, size))
    stone.putdata([(max(9,round(23+n+rng.uniform(-1.5,1.5))),)*3 for n in values])
    stone.save(folder / 'stone.png', optimize=True)
    for kind, colors in {'steel':((60,56,48),(29,28,26)),
                         'crimson':((127,23,19),(63,9,9)),
                         'disabled':((37,36,32),(27,27,25))}.items():
        for state, delta in [('normal',0),('active',12),('pressed',-10)]:
            image = Image.new('RGB',(96,48))
            draw = ImageDraw.Draw(image)
            for y in range(48):
                f=y/47
                rgb=tuple(max(0,min(255,round(a*(1-f)+b*f)+delta)) for a,b in zip(*colors))
                draw.line((0,y,95,y),fill=rgb)
            draw.rectangle((0,0,95,47),outline='#090908',width=2)
            draw.rectangle((2,2,93,45),outline='#776952' if kind!='disabled' else '#454139')
            draw.line((4,3,91,3),fill='#c1ac81' if kind!='disabled' else '#68604f')
            draw.line((4,44,91,44),fill='#100d0b')
            draw.rectangle((5,5,90,42),outline='#3a3026' if kind=='steel' else '#9b6341' if kind=='crimson' else '#302f2b')
            image.resize((96,32),Image.Resampling.LANCZOS).save(folder / f'{kind}-{state}.png', optimize=True)
    # Distinct original badge art. No third-party game artwork is redistributed.
    for name, mark, color in [('quest','!', '#e5bd4d'),('loot','chest','#c58a44'),
                             ('combat','bars','#8da9a5'),('map','map','#7e9b73'),
                             ('dbm','shield','#c49a67'),('utility','diamond','#b7b1a4')]:
        im=Image.new('RGBA',(32,32)); d=ImageDraw.Draw(im)
        d.rounded_rectangle((1,1,30,30),radius=3,fill='#24221e',outline='#8d7956',width=1)
        d.line((4,3,27,3),fill='#c1ad84')
        if mark=='!':
            d.rounded_rectangle((14,7,18,19),radius=1,fill=color); d.ellipse((14,23,18,27),fill=color)
        elif mark=='chest':
            d.rectangle((7,13,25,25),fill='#634222',outline=color,width=2)
            d.arc((7,6,25,19),180,360,fill=color,width=2); d.rectangle((14,15,17,20),fill=color)
        elif mark=='bars':
            for j,w in enumerate((18,14,10,6)):d.rectangle((7,7+j*5,7+w,9+j*5),fill=color)
        elif mark=='map':
            d.polygon((6,8,12,6,20,9,26,6,26,24,20,27,12,24,6,26),outline=color)
            d.line((12,7,12,23),fill=color);d.line((20,10,20,25),fill=color)
        elif mark=='shield':
            d.polygon((7,7,16,4,25,7,24,20,16,27,8,20),outline=color,width=2)
            d.line((12,11,20,19),fill=color,width=2);d.line((20,11,12,19),fill=color,width=2)
        else:d.polygon((16,6,26,16,16,26,6,16),outline=color,width=2)
        im.save(folder / f'badge-{name}.png', optimize=True)
    print(folder)


if __name__ == '__main__':
    build()
