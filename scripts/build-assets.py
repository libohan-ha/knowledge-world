"""Draw original lossless isometric pixel assets. No reference screenshot is reused."""
import json
import math
import random
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "frontend/public/world-art"
OUT.mkdir(parents=True, exist_ok=True)
assets = []


def save(name, image, anchor, kind, stage=None):
    image.save(OUT / f"{name}.png")
    assets.append({"id": name, "type": kind, "size": list(image.size), "anchor": anchor, "footprint": [1, 1], "stage": stage, "source": "scripts/build-assets.py — original procedural pixel drawing", "license": "Project-owned original artwork", "version": "1.0.0"})


def tile(name, color, kind="terrain", seed=0):
    im = Image.new("RGBA", (128, 88))
    d = ImageDraw.Draw(im)
    d.polygon([(0, 32), (64, 64), (64, 84), (0, 52)], fill="#394950")
    d.polygon([(64, 64), (127, 32), (127, 52), (64, 84)], fill="#273b42")
    d.line([(0, 52), (64, 84), (127, 52)], fill="#25363f", width=2)
    d.polygon([(0, 32), (64, 0), (127, 32), (64, 64)], fill=color)
    rng = random.Random(seed)
    palette = ["#59776b", "#627f70", "#739079", "#48665f"] if kind == "terrain" else ["#aa947a", "#968773", "#baaa88"]
    for _ in range(110):
        x, y = rng.randint(4, 123), rng.randint(3, 60)
        if abs(x-64)/64+abs(y-32)/32 < .94:
            d.line((x, y, x+rng.randint(1, 3), y), fill=rng.choice(palette))
    if kind == "terrain":
        for x, y in [(15,32),(90,20),(62,48),(42,18)]:
            d.line((x,y,x,y-3),fill="#a0af87")
            d.point((x+1,y-2),fill="#cab997")
    save(name,im,[64,32],kind)


for i, color in enumerate(["#587567", "#5f7b6b", "#536f63"]):
    tile(f"grass-{i}",color,seed=i+5)
tile("path","#a38f76","path",12)
tile("stone","#8c908a","path",4)
im=Image.new("RGBA",(128,88));d=ImageDraw.Draw(im)
d.polygon([(0,32),(64,0),(127,32),(64,64)],fill="#395c70")
for x,y,w in [(30,26,22),(65,40,29),(73,21,18),(45,48,11),(44,14,10)]:
    d.line((x,y,x+w,y),fill="#76a5a6",width=1)
d.polygon([(0,32),(64,64),(64,81),(0,50)],fill="#304c5d")
d.polygon([(64,64),(127,32),(127,50),(64,81)],fill="#273d50")
save("river",im,[64,32],"terrain")


def tree(name, seed, pine=False):
    rng=random.Random(seed)
    im=Image.new("RGBA",(112,142));d=ImageDraw.Draw(im)
    d.ellipse((13,113,100,138),fill=(24,40,43,90))
    d.polygon([(51,128),(61,128),(63,72),(55,59),(50,91)],fill="#5b514a")
    d.line((53,124,56,65),fill="#887561",width=3)
    if pine:
        for n,(cx,cy,r) in enumerate([(55,22,27),(55,44,36),(55,68,43)]):
            d.polygon([(cx,cy-r),(cx-r,cy+r),(cx+5,cy+r+9),(cx+r,cy+r)],fill=["#547a68","#436958","#3c5d51"][n])
            d.polygon([(cx,cy-r),(cx-r,cy+r),(cx-2,cy+r-5)],fill=["#789377","#63866c","#547965"][n])
    else:
        for cx,cy,r in [(58,75,43),(32,55,28),(78,49,29),(50,32,32),(35,82,29),(80,80,25)]:
            d.ellipse((cx-r,cy-r,cx+r,cy+r),fill="#354e4b")
            d.ellipse((cx-r,cy-r,cx+r-8,cy+r-8),fill="#4e715e")
            d.ellipse((cx-r+3,cy-r+3,cx+12,cy+8),fill="#739172")
        for _ in range(210):
            x,y=rng.randint(8,100),rng.randint(5,109)
            if im.getpixel((x,y))[3] and im.getpixel((x,y))[:3] != (24,40,43):
                d.rectangle((x,y,x+2,y+1),fill=rng.choice(["#809b77","#668669","#4d705c","#93a580"]))
    save(name,im,[56,125],"plant")


tree("tree",12);tree("pine",4,True)


def building(name, stage=1, theme="forest"):
    im=Image.new("RGBA",(160,180));d=ImageDraw.Draw(im)
    d.ellipse((18,129,147,171),fill=(20,27,38,85))
    d.polygon([(23,125),(80,98),(140,130),(82,161)],fill="#777b73")
    d.polygon([(25,128),(82,157),(139,130),(139,136),(82,167),(25,137)],fill="#525a59")
    left,right="#b0a08a","#7e827a"
    if theme=="valley":left,right="#a7aaa0","#747f81"
    if theme=="plaza":left,right="#c0b196","#8d9084"
    d.polygon([(38,82),(81,60),(126,82),(126,126),(81,151),(38,128)],fill=right)
    d.polygon([(38,82),(81,103),(81,151),(38,128)],fill=left)
    # Stone foundation and lower timber trim follow the same two-to-one projection.
    for y in [118,127,137]:
        d.line((39,y-12,80,y+9),fill="#7c776b",width=2)
    d.line((82,143,124,121),fill="#526764",width=3)
    roof1,roof2,roof3=("#a17d68","#725b57","#c09877") if theme=="forest" else ("#697f80","#4a5e68","#93a1a0") if theme=="valley" else ("#89768b","#5f5b71","#b09a9f")
    d.polygon([(25,84),(66,33),(139,74),(84,110)],fill=roof2)
    d.polygon([(25,84),(66,33),(99,74),(84,110)],fill=roof1)
    d.line([(25,84),(66,33),(139,74)],fill=roof3,width=3)
    d.line((26,85,84,113),fill="#4b474d",width=4)
    d.line((84,113,138,80),fill="#45434b",width=3)
    for n in range(5):
        x=34+n*8;y=75-n*8
        d.line((x,y,x+50,y+28),fill=roof3,width=1)
    d.polygon([(108,48),(118,43),(125,46),(125,69),(117,74),(108,69)],fill="#8a8b80")
    d.polygon([(107,47),(117,42),(127,47),(117,52)],fill="#b8afa0")
    d.rectangle((109,43,124,46),fill="#615d62")
    # Window casements with warm interiors.
    d.polygon([(47,103),(59,109),(59,121),(47,115)],fill="#4c4d47")
    d.polygon([(49,105),(57,110),(57,117),(49,113)],fill="#e9c17f")
    d.line((53,107,53,116),fill="#8d7660")
    d.polygon([(104,103),(118,95),(118,113),(104,121)],fill="#454d4b")
    d.polygon([(106,104),(116,99),(116,110),(106,116)],fill="#ecd293")
    d.line((111,102,111,114),fill="#917b62",width=2)
    d.polygon([(67,119),(78,125),(78,148),(67,142)],fill="#645a52")
    d.line((70,121,70,142),fill="#938066")
    d.point((75,135),fill="#e2c088")
    d.polygon([(65,144),(79,150),(88,146),(88,152),(79,157),(65,150)],fill="#adab93")
    # Ivy, bushes and tiny flowers soften the silhouette.
    rng=random.Random(42+stage)
    for x,y in [(35,125),(125,126),(32,117),(90,150)]:
        d.ellipse((x-8,y-7,x+10,y+5),fill="#456555")
        for _ in range(10):
            px,py=x+rng.randint(-6,7),y+rng.randint(-5,3)
            d.rectangle((px,py,px+2,py+1),fill=rng.choice(["#8e9c77","#b8a37e","#6d8665"]))
    if stage>=2:
        d.polygon([(17,105),(30,98),(40,104),(40,128),(27,136),(17,131)],fill="#8e9684")
        d.polygon([(13,104),(29,85),(45,102),(28,113)],fill=roof1)
        d.polygon([(20,115),(27,118),(27,126),(20,123)],fill="#e6c486")
        d.line((131,102,131,139),fill="#aea58c",width=2)
        d.polygon([(133,103),(148,110),(142,119),(133,113)],fill="#d1b383")
    if stage>=3:
        d.polygon([(48,43),(64,17),(85,29),(81,58),(64,68),(48,60)],fill="#aaa58f")
        d.polygon([(43,42),(64,8),(90,32),(66,47)],fill=roof1)
        d.line([(43,42),(64,8),(90,32)],fill=roof3,width=2)
        d.rectangle((61,39,66,47),fill="#e9c987")
        for x,y in [(37,135),(117,139)]:
            d.line((x,y-12,x,y+3),fill="#b8a381",width=2)
            d.rectangle((x-3,y-16,x+3,y-9),fill="#f0cd91")
    save(name,im,[80,146],"structure",stage)


building("camp",0)
for theme in ["forest","valley","plaza"]:
    for stage in [1,2,3]:building(f"{theme}-{stage}",stage,theme)

for stage in [0,1,2]:
    im=Image.new("RGBA",(84,88));d=ImageDraw.Draw(im)
    d.polygon([(5,61),(42,43),(79,61),(42,79)],fill="#756756")
    for x,y in [(24,59),(43,64),(59,56)]:
        h=[9,20,33][stage]
        d.line((x,y,x,y-h),fill="#7e9b65",width=2)
        d.ellipse((x-9,y-h+3,x,y-h+9),fill="#a5b27a")
        d.ellipse((x+1,y-h+6,x+9,y-h+12),fill="#5d885f")
        if stage==2:
            d.ellipse((x-6,y-h-8,x+7,y-h+3),fill="#e9d3a2")
            d.rectangle((x-2,y-h-4,x+3,y-h),fill="#b59463")
    save(f"crop-{stage}",im,[42,66],"plant",stage)

for state in ["idle","happy","scarf"]:
    im=Image.new("RGBA",(64,66));d=ImageDraw.Draw(im)
    d.ellipse((9,50,58,63),fill=(24,32,42,95))
    d.polygon([(37,44),(49,37),(58,41),(61,50),(53,56),(39,53)],fill="#b5a080")
    d.polygon([(54,39),(61,44),(61,51),(56,53),(52,46)],fill="#ece0bd")
    d.ellipse((16,30,47,58),fill="#a59b7d")
    d.polygon([(14,32),(13,11),(24,20),(37,20),(44,11),(48,35),(36,47),(25,46)],fill="#cfb992")
    d.polygon([(15,15),(21,23),(16,26)],fill="#7d7469")
    d.polygon([(43,16),(39,25),(45,26)],fill="#7d7469")
    d.polygon([(19,34),(30,40),(41,33),(36,45),(27,46)],fill="#eee0bb")
    d.rectangle((23,30,25,32),fill="#343e43")
    d.rectangle((36,29,38,31),fill="#343e43")
    d.rectangle((30,36,32,38),fill="#4e514b")
    d.rectangle((19,54,25,58),fill="#726e61")
    d.rectangle((35,55,41,59),fill="#726e61")
    if state=="happy":
        d.line((28,40,32,42,36,39),fill="#726e61",width=1)
    if state=="scarf":
        d.rectangle((18,42,44,46),fill="#748d7a")
        d.polygon([(37,43),(42,43),(44,54),(39,56)],fill="#9baa83")
    save(f"fox-{state}",im,[32,55],"companion")

im=Image.new("RGBA",(56,112));d=ImageDraw.Draw(im)
d.ellipse((9,91,46,104),fill=(20,30,40,80))
d.line((29,93,29,30),fill="#5b6060",width=4)
d.line([(29,31),(29,18),(39,13)],fill="#84877c",width=3)
d.polygon([(29,23),(39,17),(48,23),(39,29)],fill="#5f6763")
d.polygon([(31,24),(38,28),(38,42),(31,38)],fill="#d9b16f")
d.polygon([(40,28),(46,24),(46,37),(40,42)],fill="#f3d28a")
d.line([(30,40),(39,45),(48,39)],fill="#596361",width=2)
save("lamp",im,[28,93],"decoration")
im=Image.new("RGBA",(128,96));d=ImageDraw.Draw(im)
d.polygon([(6,37),(68,7),(121,35),(59,68)],fill="#a59a7e")
for n in range(12):d.line((10+n*5,37-n*2,61+n*5,64-n*2),fill="#695f55",width=2)
for a,b in [((8,28),(68,0)),((61,56),(123,24))]:
    d.line((a,b),fill="#a6a08b",width=3)
    for i in range(5):
        x=a[0]+i*(b[0]-a[0])//4;y=a[1]+i*(b[1]-a[1])//4
        d.line((x,y,x,y+18),fill="#777568",width=3)
save("bridge",im,[64,42],"structure")

im=Image.new("RGBA",(64,88));d=ImageDraw.Draw(im)
d.line((16,12,16,74),fill="#bca681",width=3)
d.polygon([(18,14),(50,12),(48,40),(35,35),(18,40)],fill="#536d61")
d.line((21,17,47,15,45,35),fill="#9eaf88",width=2)
d.polygon([(32,21),(37,28),(32,34),(27,28)],fill="#ecd2a0")
for x,y in [(11,48),(17,56),(10,65),(22,68)]:
    d.line((16,74,x,y),fill="#6a8067",width=2)
    d.ellipse((x-4,y-3,x+4,y+3),fill="#8da07a")
save("garden-upgrade",im,[16,74],"upgrade")

im=Image.open(OUT/"crop-2.png").copy();d=ImageDraw.Draw(im)
d.polygon([(24,61),(59,61),(54,80),(30,80)],fill="#b49676")
d.rectangle((23,60,60,64),fill="#d1b58c")
d.line((30,67,53,67),fill="#e6cda4",width=2)
save("flower-collectible",im,[42,80],"collectible")

(OUT/"manifest.json").write_text(json.dumps({"projection":"isometric_2_to_1","tile_size":[128,64],"light_direction":"upper_left","sampling":"nearest_neighbor","assets":assets},ensure_ascii=False,indent=2),encoding="utf-8")
print(f"Generated {len(assets)} original PNG assets and manifest")
