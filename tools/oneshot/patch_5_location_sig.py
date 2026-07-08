"""补全最后5个写入失败的人物地点意义。"""
import re
from pathlib import Path

STORY = Path("storymap/examples/story")

FIXES = [
    ("吕思勉", "常州（出生与少年求学）",
     "江南古城的人文底蕴为这位未来的史学宗师奠定了最初的学术根基，常州学派的求真传统浸润了他治学的底色"),
    ("吕思勉", "上海（光华大学时期）",
     "在光华大学二十余年的教学生涯，吕思勉于此完成《吕著中国通史》《先秦史》等扛鼎之作，将通贯古今的史识融入课堂"),
    ("吕思勉", "常州（抗战避难与著述期）",
     "抗战期间蛰居故乡，以'孤岛'中的寂寞书斋对抗战火——此间写成的断代史系列确立了其'史学四大家'之一的地位"),
    ("吕思勉", "上海（华东师范大学时期）",
     "新中国成立后在华东师大培养新一代史学人才，将毕生所学倾注于史料整理与教学传承，完成最后的学术总结"),
    ("吕思勉", "上海（晚年及去世）",
     "生命终章仍在伏案修订旧作，这位以一人之力通贯中国全史的学者，将最后的呼吸也留给了历史"),

    ("噶尔丹", "伊犁",
     "夺取准噶尔部统治权后以伊犁为汗庭——天山脚下的这片草原承载了噶尔丹统一厄鲁特四部的野心起点，也埋下了他与清帝国殊死较量的种子"),
    ("噶尔丹", "漠北喀尔喀",
     "东征喀尔喀蒙古得手——将游牧帝国的边界推向漠北，这一扩张彻底激怒了康熙帝，直接引发了此后近十年的清准大战"),
    ("噶尔丹", "乌兰布通（今内蒙古克什克腾旗）",
     "驼城防线在清军火炮下崩溃——乌兰布通之败是噶尔丹从不可一世的草原霸主走向末路的转折，康熙首征即重创其主力"),
    ("噶尔丹", "昭莫多（今蒙古国宗莫德）",
     "主力被歼于此役——昭莫多是清准战争的滑铁卢，康熙帝在此将噶尔丹的帝业梦想彻底击碎，草原枭雄再无还手之力"),
    ("噶尔丹", "漠西蒙古",
     "病亡于穷途末路——昔日纵横天山的可汗在荒漠中孤独咽下最后一口气，草原帝国的一代雄主落幕悲凉"),
    ("噶尔丹", "西北边疆",
     "雍正时期清准双方在此拉锯缠斗——噶尔丹虽死，准噶尔汗国未灭，后继者策妄阿拉布坦继续威胁清朝西北边疆"),
    ("噶尔丹", "伊犁",
     "乾隆出兵最终夷平准噶尔汗国——伊犁从噶尔丹的强权中心变成清帝国的驻防重镇，草原帝国彻底消失在历史地图上"),
    ("噶尔丹", "科布多及阿尔泰山南北",
     "科布多及阿尔泰山南北是准噶尔传统的游牧腹地，噶尔丹以此为根据地东征西讨、练兵养马，是其军事扩张的后勤生命线"),

    ("张三丰", "武当山（今湖北省十堰市武当山）",
     "在武当山创立内家拳法，融道家太极哲学于武术——从此武当与少林并立，成为中国武术两大圣山之一"),

    ("蒙毅", "陇西狄道（出生地）",
     "秦统一后中央集权扩张的起点——陇西边陲的少年凭才智与忠诚跨入大秦帝国的权力核心，一个出身西鄙的士人由此书写了自己在帝国机器中的浮沉"),
    ("蒙毅", "秦都咸阳（初期出仕）",
     "从陇西边陲来到大秦心脏——年轻的蒙毅在咸阳见证了帝国的崛起，也在此与权势滔天的赵高之流结下不解之仇"),
    ("蒙毅", "秦都咸阳（秦始皇三十七年）",
     "为秦始皇祷山川代罪而跪——这是君王对蒙氏忠臣的极限信任：以臣斋戒代天子承受死神的命运，蒙毅的忠与贵的顶峰皆凝聚于此"),
    ("蒙毅", "代郡（今河北蔚县一带，拘留待罪地）",
     "噩耗从沙丘传来，丞相之玺化作弑君者的刀——蒙毅被赵高以伪造罪名扣留在此，大秦最后的忠臣沦为血腥清洗祭坛上的第一头牺牲"),
    ("蒙毅", "秦都咸阳（被害处）",
     "蒙毅与兄长蒙恬同日被杀——咸阳宫阙间从此再无蒙氏忠骨，赵高通胡亥的刀在这场清洗中不仅砍向帝国的良将忠臣，更一刀斩断秦帝国的脊柱"),

    ("赵高", "秦宫（掖庭）",
     "以宦官之身出入掖庭教胡亥律令——赵高在秦宫最深处培植了对二世胡亥的绝对控制，帝国的一切杀戮都从这里腐朽的起点开始蔓延"),
    ("赵高", "秦始皇巡行（沙丘之变现场）",
     "与李斯合谋伪造遗诏，立胡亥为帝、赐死扶苏——沙丘阴谋颠覆了帝位的正统传承，也开启了赵高彻底走向秦王朝掌权者的血腥阶梯"),
    ("赵高", "秦宫（朝堂/望夷宫）",
     "指鹿为马——在望夷宫朝堂上公然试探群臣服从度，彻底架空秦二世，使大秦的中央权力沦为个人疯狂的工具"),
    ("赵高", "秦都咸阳（最后据点）",
     "暗杀秦二世胡亥、持皇帝玉玺欲称帝——被群臣以'天下反秦'为由逼上末路，从指鹿为马的巅峰跌入弑君自尽的深渊，赵高用三年时间毁掉了秦始皇十五年统一六国的心血"),
    ("赵高", "秦都咸阳（政治活动）",
     "指鹿为马的朝堂变乱——赵高在此颠倒了帝国纲常法度，以一己私欲驱使帝国走上自毁之路，成为秦朝速亡最致命的政治毒瘤"),
]


def apply_fix(md_path, loc_name, sig):
    text = md_path.read_text(encoding="utf-8")

    # Find the location block starting with this name
    header = f"重要地点：{loc_name}"
    # Try exact match
    for hdr_pattern in [
        f"### 📍 重要地点：{loc_name}",
        f"### 重要地点：{loc_name}",
    ]:
        idx = text.find(hdr_pattern)
        if idx >= 0:
            # Find end of this block (next ### or end)
            rest = text[idx:]
            next_sec = re.search(r"\n###\s", rest[len(hdr_pattern):])
            if next_sec:
                block_end = idx + len(hdr_pattern) + next_sec.start()
                block = text[idx:block_end]
            else:
                block = rest

            # Insert **意义** after the last field line
            lines = block.split("\n")
            new_lines = []
            inserted = False
            for i, line in enumerate(lines):
                new_lines.append(line)
                if not inserted:
                    is_last_field = line.strip().startswith("- **") and (i + 1 >= len(lines) or not lines[i + 1].strip().startswith("- **"))
                    next_is_end = i + 1 >= len(lines) or not lines[i + 1].strip() or lines[i + 1].startswith("###")
                    if is_last_field or next_is_end:
                        new_lines.append(f"- **意义**：{sig}")
                        inserted = True

            if inserted:
                new_block = "\n".join(new_lines)
                text = text[:idx] + new_block + text[idx + len(block):]
                md_path.write_text(text, encoding="utf-8")
                return True

    return False


def main():
    for person, loc_name, sig in FIXES:
        md_path = STORY / f"{person}.md"
        if md_path.exists():
            ok = apply_fix(md_path, loc_name, sig)
            if ok:
                print(f"  ✓ {person}/{loc_name}")
            else:
                print(f"  ✗ {person}/{loc_name}: block not found")
        else:
            print(f"  ? {person}.md not found")

    print("\nDone!")


if __name__ == "__main__":
    main()
