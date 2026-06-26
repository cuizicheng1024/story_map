/* ===== 回到大宋当宰相 · 游戏引擎 ===== */

const CN_NUM = ['零','一','二','三','四','五','六','七','八','九','十'];

// 六维状态。finance(财政压力) 与 oldParty(旧党反弹) 越高越危险。
const INIT = { emperor:80, court:35, people:55, finance:80, reform:0, oldParty:60 };

// 状态元数据：name 名称；type 颜色风格；invert=true 表示数值越低越好
const STAT_META = [
  { key:'emperor',  name:'皇帝信任', type:'good',   invert:false },
  { key:'court',    name:'朝廷支持', type:'gold',   invert:false },
  { key:'people',   name:'民间承受', type:'good',   invert:false },
  { key:'finance',  name:'财政压力', type:'danger', invert:true  },
  { key:'reform',   name:'改革推进', type:'gold',   invert:false },
  { key:'oldParty', name:'旧党反弹', type:'danger', invert:true  },
];

const clamp = v => Math.max(0, Math.min(100, v));

/* ============ 出场人物 ============ */
const CHARS = {
  wanganshi:{ name:'王安石', role:'你 · 参知政事', img:'p_wanganshi' },
  shenzong: { name:'宋神宗', role:'当今官家',      img:'p_shenzong'  },
  simaguang:{ name:'司马光', role:'旧党领袖',      img:'p_simaguang' },
  zhengxia: { name:'郑　侠', role:'监安上门小吏',  img:'p_zhengxia'  },
  sushi:    { name:'苏　轼', role:'通判杭州 · 文豪', img:'p_sushi'    },
};

/* ============ 剧情图谱 ============ */
const SCENES = {

  /* —— 第一幕 —— */
  s1: {
    turn:1, img:'court', tag:'朝堂', char:'wanganshi', title:'第一幕 · 早朝前夜',
    text:
`三司密札就摊在你案上，墨迹未干。

<span class="quote">河北、陕西边费日重。民间青黄不接，多向豪右借贷，息重至倍。若朝廷不出手，田产兼并日甚。</span>

农民缺钱，豪强放贷。若朝廷在春耕时低息借钱给农户，秋收后连本带息收回，理论上能一举三得：<span class="em2">少被盘剥、增加国用、削弱豪强</span>。

可你比谁都清楚，麻烦从不在纸面上。门外中使又传一句话——

<span class="quote">官家有旨：今日朝会，欲先问相公，新法当从何处起？</span>`,
    choices:[
      { k:'甲', t:'先推青苗法', d:'从民间借贷入手，最快见效，但执行风险极高。', fx:{finance:-15,reform:20,oldParty:20,people:-10}, next:'qm' },
      { k:'乙', t:'先推均输市易法', d:'整顿漕运与商业流通，冲击相对间接。',     fx:{finance:-10,reform:12,court:-5,oldParty:10}, next:'sy' },
      { k:'丙', t:'先整军政推保甲', d:'从基层组织与兵役下手，减养兵之费。',     fx:{reform:12,oldParty:12,people:-8,finance:-4,court:5}, next:'bj' },
      { k:'丁', t:'暂缓大法，州县试点', d:'拿数据与案例说话，稳健但易被讥为软弱。', fx:{oldParty:-12,people:6,reform:5,emperor:-8}, next:'pilot' },
    ]
  },

  /* —— 第二幕：四条支线 —— */
  qm: {
    turn:2, img:'farm', tag:'青苗 · 田垄', char:'simaguang', title:'第二幕 · 青苗下乡',
    text:
`诏令一下，青苗钱发往诸路。江南春田一片新绿，本是好景。

可旬日之间，告状的文书就堆到了门下。有的县官为求政绩，<span class="em">强令上户下户一概借贷</span>，不借者鞭笞；胥吏从中抽头，借一贯实到手七百。司马光在朝堂冷笑：此乃与民争利。

新法要落地，先得管住这只伸进农户口袋的手。`,
    choices:[
      { k:'甲', t:'严禁抑配，宁可少收', d:'明令不得强行摊派，收益打折但保住民心。', fx:{reform:-6,people:14,oldParty:-6,finance:6}, next:'locust' },
      { k:'乙', t:'给诸路定额，确保见效', d:'层层下指标，财政立竿见影，却埋下民怨。', fx:{finance:-12,reform:12,people:-16,oldParty:14}, next:'locust' },
      { k:'丙', t:'遣提举官巡察执行', d:'设专员监察州县，慢一点，但稳一点。',     fx:{court:-5,people:9,reform:6,emperor:5}, next:'locust' },
    ]
  },

  sy: {
    turn:2, img:'market', tag:'市易 · 街衢', title:'第二幕 · 通货平准',
    text:
`市易务设于汴京，朝廷出钱收滞销之货、贷本于小商，平抑物价、收取息利。均输法则让发运使统筹东南六路赋税，就近变易，省去重复转运。

账面上漂亮极了。可不出一月，大商行联名喊冤——朝廷既当裁判又下场踢球，<span class="em">官市一开，私商无路</span>。有御史上奏：此与桑弘羊何异？

钱袋鼓了，可你动的是天下商贾的奶酪。`,
    choices:[
      { k:'甲', t:'放宽市易，只取大宗', d:'让利于小商，缓和工商，息利随之缩水。', fx:{reform:-5,people:8,oldParty:-8,court:5,finance:4}, next:'locust' },
      { k:'乙', t:'扩大官营，广收息钱', d:'把利润做到极致，国库丰盈，树敌更多。', fx:{finance:-14,reform:13,oldParty:16,court:-8}, next:'locust' },
      { k:'丙', t:'立法定价，明示规矩', d:'公布平准则例，减少胥吏上下其手。',     fx:{reform:7,people:6,court:4,emperor:4}, next:'locust' },
    ]
  },

  bj: {
    turn:2, img:'militia', tag:'保甲 · 校场', title:'第二幕 · 寓兵于农',
    text:
`保甲法行于乡里：十家为保，闲时耕种、农隙操练，渐以民兵替代部分募兵，养兵之费可省大半。

构想宏大。可秋收刚过，逃亡的文书就来了——壮丁苦于操练耽误农时，有人自断手指以避征调；乡间豪强趁机把持保正之位，<span class="em">兵未强，乡已乱</span>。枢密院里也有人嘀咕：把锄头变成刀，是好是坏？`,
    choices:[
      { k:'甲', t:'减操练之繁，顺农时', d:'放宽训练强度，扰民减轻，战力提升放缓。', fx:{reform:-6,people:12,oldParty:-5,finance:3}, next:'locust' },
      { k:'乙', t:'严格按籍，强力推行', d:'雷厉风行铺开全境，省费显著，民怨陡增。', fx:{finance:-10,reform:14,people:-15,oldParty:12}, next:'locust' },
      { k:'丙', t:'择良吏掌保正，杜豪强', d:'整顿基层人选，慢工出细活。',         fx:{reform:6,people:8,court:-4,emperor:5}, next:'locust' },
    ]
  },

  pilot: {
    turn:2, img:'minister', tag:'相府 · 灯下', char:'shenzong', title:'第二幕 · 试点观效',
    text:
`你按下了全面铺开的念头，只在京东、淮南数州先行试点，命人详录每一笔账、每一桩案。

旧党的反对声小了，可另一种压力来了。官家在崇政殿召你对答，话里带着急切：

<span class="quote">卿言三年可见成效，如今半年过去，天下只见数州动静。朕等得，国库等不得。</span>

试点的数据确实漂亮——息利可观、民怨极少。但若一直小打小闹，皇帝的耐心会先于成效耗尽。`,
    choices:[
      { k:'甲', t:'以试点佳绩奏请推广', d:'用真实数据说服官家，稳中求进。',     fx:{reform:14,emperor:8,court:6,finance:-8}, next:'locust' },
      { k:'乙', t:'再观一季，求稳为上', d:'继续蛰伏，风险最低，却最磨皇帝耐心。', fx:{reform:-4,people:8,oldParty:-8,emperor:-12}, next:'locust' },
      { k:'丙', t:'扩大试点至十余州', d:'折中推进，边走边看。',                 fx:{reform:9,finance:-6,oldParty:6,emperor:3}, next:'locust' },
    ]
  },

  /* —— 第三幕：旱极而蝗（灾情升级过场） —— */
  locust: {
    turn:3, img:'pdf_img5', tag:'熙宁七年 · 蝗', title:'第三幕 · 旱极而蝗',
    text:
`<span class="em">熙宁七年的春天，雨水似乎更加吝啬。</span>自去冬至今，京东、河北诸路滴雨未落，麦苗焦枯。

<span class="quote">六月，大风裹挟着沙尘席卷京师，风沙过后，席子上落满的尘土厚达一寸以上。</span>

旱极而蝗。遮天蔽日的蝗群压境，<span class="em">蝗虫所到之处，就连草根也被噬食一空</span>。乡间已是十人之中就有九人担心饿死，只得以树皮草根充饥。

灾情如火，奏报却各执一词。你须先定一个调子。`,
    choices:[
      { k:'甲', t:'悬赏捕蝗，掘卵除根', d:'发钱粮募民捕蝗、官府督办，务实救急，耗费不小。', fx:{people:14,finance:-8,reform:6,emperor:4}, next:'sushi' },
      { k:'乙', t:'信「蝗不为灾」之说', d:'有人称蝗「为民除草」、不必张皇，按下不报，粉饰太平。', fx:{people:-16,oldParty:10,reform:4,emperor:6}, next:'sushi' },
      { k:'丙', t:'设坛祈禳，下诏罪己', d:'循祖宗故事祭天禳灾、安抚人心，治标不治本。',       fx:{people:8,emperor:6,court:5,reform:-3}, next:'sushi' },
    ]
  },

  /* —— 第四幕：苏子寄诗（苏轼自杭州发声） —— */
  sushi: {
    turn:4, img:'market', tag:'江湖 · 苏子', char:'sushi', title:'第四幕 · 苏子寄诗',
    text:
`旱蝗未歇，一封自杭州来的书札却先送进了相府。

写信的是<span class="em">苏轼</span>。当年他上《上神宗皇帝书》，直陈青苗、助役之弊，与你政见龃龉，自请外放，通判杭州去了。本该眼不见为净，可他在江南，偏偏把所见所闻又写成了诗——

<span class="quote">汗流肩赪载入市，价贱乞与如糠粞。卖牛纳税拆屋炊，虑浅不及明年饥……龚黄满朝人更苦，不如却作河伯妇。</span>

诗里没有一句骂你，可字字都像针。他说：新法本为利民，可层层加码、胥吏盘剥之下，<span class="em2">田妇卖牛拆屋，反不如投河了断</span>。

这书生才高八斗、嘴也利，捧着他的诗，你一时竟不知该怒，还是该愧。`,
    choices:[
      { k:'甲', t:'书生不识国事艰难', d:'斥其只见一隅、不谋全局，变法岂能因几句牢骚而废。', fx:{reform:8,oldParty:10,people:-8,court:-5}, next:'rainreport' },
      { k:'乙', t:'民瘼当察，下令纠偏', d:'诗虽刺耳，所言非虚；命州县核查抑配盘剥，纠新法之弊。', fx:{people:16,reform:-6,oldParty:-8,emperor:4}, next:'rainreport' },
      { k:'丙', t:'政见虽异，许其自便', d:'道不同不相为谋，由他在外任上去，免得朝中再添口舌。',     fx:{court:-4,oldParty:-6,reform:4,people:4}, next:'rainreport' },
    ]
  },

  /* —— 第五幕：报雨量（地方虚报 · 掘地验雨） —— */
  rainreport: {
    turn:5, img:'pdf_img8', tag:'诸路 · 报雨', char:'shenzong', title:'第五幕 · 一寸报三寸',
    text:
`旱情要不要如实上闻，竟成了官场上的一桩学问。

为粉饰新法之效，州县报雨量层层注水——<span class="em">一寸则云三寸，三寸则云一尺，多不以其实</span>。纸面上甘霖普降，田垄里却赤地依旧。

官家也起了疑心，亲自验看，遣中使传话：

<span class="quote">朕宫中令人掘地及一尺五寸，土犹滋润，如此必可耕耨。</span>

掘地验雨，真假立判。面对这弥漫朝野的虚报之风，你怎么接？`,
    choices:[
      { k:'甲', t:'据实奏报，请罢谎报之官', d:'还旱情以本来面目，触怒一批人，却赢得民心与公道。', fx:{people:16,oldParty:8,reform:-4,emperor:-4,court:-4}, next:'famine' },
      { k:'乙', t:'附和粉饰，报喜不报忧', d:'顺着「一寸报三寸」糊弄过去，眼前太平，民怨暗涌。',   fx:{emperor:6,people:-18,oldParty:12,reform:4}, next:'famine' },
      { k:'丙', t:'请官家遣使核实、掘地验雨', d:'以皇帝亲验为据，按实蠲免赋税，稳妥而得君心。',     fx:{emperor:8,people:12,court:6,reform:-2}, next:'famine' },
    ]
  },

  /* —— 第六幕：熙宁大旱 · 流民图 —— */
  famine: {
    turn:6, img:'pdf_img11', tag:'熙宁 · 流民图', char:'zhengxia', title:'第六幕 · 流民图',
    text:
`天不遂人愿。赤地千里，流民塞道，扶老携幼，鬻儿卖女，食草根树皮于道旁。

监安上门的小吏<span class="em">郑侠</span>，把沿途所见画成一卷《流民图》，连同奏疏矫称密急、直送御前：

<span class="quote">臣伏睹去年大蝗，秋冬亢旱，迄今不雨，麦苗焦枯……旬日以来，米价暴贵，群情忧惶，十九惧死。</span>

他更以性命作保——<span class="em">若十日不雨，即乞斩臣，以正欺君之罪</span>；又进一言直指你：<span class="em2">天旱由王安石所致，若罢安石，天必雨。</span>

一图冲决禁城红墙，太皇太后垂泪：<span class="em">「安石乱天下。」</span>司马光、文彦博趁势上书请罢新法。这是变法以来最凶险的一关——<span class="em2">守，还是退？</span>`,
    choices:[
      { k:'甲', t:'力陈天灾非新法之过', d:'坚持到底，向官家死谏，赌上君臣之信。', fx:{oldParty:14,reform:8,emperor:-6,people:-6}, next:'court_final' },
      { k:'乙', t:'暂罢苛细，留其大端', d:'主动叫停最扰民的条目，以退为进。',     fx:{people:16,reform:-10,oldParty:-12,emperor:4}, next:'court_final' },
      { k:'丙', t:'开仓赈灾，免青苗息', d:'倾国库救灾、减免利息，先安民心。',     fx:{finance:14,people:22,reform:-6,emperor:6,oldParty:-8}, next:'court_final' },
    ]
  },

  /* —— 第七幕：崇政殿召对 —— */
  court_final: {
    turn:7, img:'pdf_img7', tag:'崇政殿 · 召对', char:'shenzong', title:'第七幕 · 君臣之间',
    text:
`雨终于落下，旱情稍解，可朝堂的雨却越下越大。弹劾你的奏章摞起来比人还高。

崇政殿上，官家屏退左右，只留你一人。烛火映着他年轻而疲惫的脸。

<span class="quote">王卿，朕用你变法，是信你能为大宋开一条生路。可如今谤议盈廷，连宫中也容不下。郑侠言「天必雨」，朕这心里……到底<span class="em">天变足畏</span>啊。这条路，还走得下去么？</span>

你心中那十五个字呼之欲出——<span class="em2"><b>天变不足畏</b>，祖宗不足法，流俗之言不足恤</span>。可君王的底线，偏偏是「<b>天变足畏</b>」。

成败，往往不取决于法令本身，而取决于此刻你如何回应一位动摇的君王。`,
    choices:[
      { k:'甲', t:'慷慨陈词，请君主坚定', d:'天变不足畏，祖宗不足法，流俗之言不足恤。', fx:{reform:10,oldParty:8,emperor:0}, next:'END' },
      { k:'乙', t:'请辞相位以全大局', d:'主动求去，为新法留一线生机，也为自己留身后名。', fx:{reform:-4,oldParty:-16,emperor:6,court:8}, next:'END' },
      { k:'丙', t:'举荐贤能，徐图后效', d:'交棒可信之人，把火种交付未来。',         fx:{reform:4,court:10,oldParty:-6,emperor:4}, next:'END' },
    ]
  },
};

/* ============ 结局判定 ============ */
function computeEnding(s){
  const score = s.reform*1.0 + (100-s.finance)*0.7 + s.people*0.5
              + s.emperor*0.4 + s.court*0.3 - s.oldParty*0.6;

  // 硬性失败优先
  if (s.emperor < 30)
    return ending('decline','罢相归田',
      `君心已凉。一纸诏书下来，你被罢去相位，出知江宁。变法失了最大的靠山，新党人人自危。<br>临行那日，你立马城门回望，写下绝句：<span class="em2">六年湖海老侵寻，千里归来一寸心。回望国门搔短发，九天宫阙五云深。</span><br>多年后你独游钟山，又写下「春风又绿江南岸」，却再无人问，明月何时照你还朝。<span class="em">呜呼！熙宁七年，果然是雨点小，而雷声大。</span>`,
      '皇帝信任跌破底线——再好的法，也敌不过君王的犹豫。',
      [
        {c:'shenzong', t:'朕非负卿，奈何谤议盈廷、众口铄金。新法，朕心里仍记着几分。'},
        {c:'simaguang',t:'安石既去，于国为幸。然其志洁、其学博，光未尝不敬之。'},
        {c:'sushi',    t:'介甫之失，在执拗太过；至若忧国忧民之心，岂可尽诬为奸？'},
        {c:'wanganshi',t:'知我罪我，其惟春秋。江宁钟山，且归去也。'},
      ]);
  if (s.oldParty > 88)
    return ending('decline','人亡政息',
      `你在位时尚能压住反对，可你一旦松手，旧党如潮水般涌回。司马光尽废新法，史称「元祐更化」。你毕生心血，化作史册上一行毁誉参半的评语。改革的难，从来不只是把法立起来，而是让它活得比你更久。`,
      '旧党反弹冲破临界——变法败给了它树敌太多。',
      [
        {c:'simaguang',t:'新法当尽罢之！还天下以祖宗旧制——元祐更化，自此始。'},
        {c:'sushi',    t:'尽改其法，亦未必尽是。矫枉而过正，吾所深惧也。'},
        {c:'shenzong', t:'党争一起，便再难收束。朕亦悔，当初用人之际太急。'},
        {c:'wanganshi',t:'法行于吾之在，废于吾之去。树敌太多，终是我之过。'},
      ]);
  if (s.finance > 90)
    return ending('decline','国库崩坏',
      `法令铺得太急，钱却没真正生出来。冗费未减，新政的本钱反被层层耗空。边关告急时，三司报上来的是一串赤字。富国未成，国用先匮——这是改革者最不愿见，却最常见的结局。`,
      '财政压力彻底失控——理想，终究要算得过账。',
      [
        {c:'simaguang',t:'天地所生财货百物，止有此数，不在民则在官。岂有不取于民而国用自饶？'},
        {c:'wanganshi',t:'善理财者，民不加赋而国用饶——惜乎操之过急，本钱反被耗空。'},
        {c:'shenzong', t:'朕要的是富国，何以推行数年，国用愈见匮乏？'},
        {c:'sushi',    t:'欲速则不达。介甫求治太急，遂使良法亦成厉政。'},
      ]);

  // 正向结局分级
  if (score >= 145 && s.people >= 50 && s.reform >= 60)
    return ending('prosper','千古名相',
      `数年之后，国库渐盈，边军换了新装，被豪强吞掉的田亩重新回到农户手中。你站在汴河边，看漕船往来如织。后世史家争论你几百年，但有一点无人否认——你曾真的让一个暮气沉沉的王朝，重新动了起来。<span class="em2">天变不足畏，祖宗不足法，人言不足恤。</span>这十五个字，你用一生写完了。`,
      '改革、财政、民心三者兼得——史上极罕见的圆满。',
      [
        {c:'shenzong', t:'卿不负朕，朕亦不负卿。大宋中兴，自卿之手而起！'},
        {c:'simaguang',t:'政见虽与公异，公之功，光不敢没。今日，光服矣。'},
        {c:'sushi',    t:'介甫真宰相也。轼向日所讥，今当引咎自责。'},
        {c:'wanganshi',t:'天变不足畏，祖宗不足法，人言不足恤——此十五字，今日方敢当之。'},
      ]);
  if (score >= 110 && s.reform >= 45)
    return ending('prosper','富国强兵',
      `新法站住了脚。财用稍宽，军备渐整，虽仍有怨声，但大宋的脊梁直了几分。你知道这不是终点，许多隐患仍在暗处，可至少，你为后来者趟出了一条路，也证明了这条路走得通。`,
      '主要目标达成——务实而扎实的一局。',
      [
        {c:'shenzong', t:'财用稍宽，军备渐整，朕心稍安。卿之劳，朕记之。'},
        {c:'wanganshi',t:'未竟全功，然路已趟通，后来者可循此而进。'},
        {c:'sushi',    t:'新法有得有失，公能持其平、纳其谏，殊为难得。'},
      ]);
  if (score >= 78)
    return ending('prosper','毁誉参半',
      `变法留下了一半的成果和一半的争议。青苗、市易诸法或存或废，国用略有起色，民间却也添了新的负担。后人提起这段，总要叹一句：王安石是真想做事的人，只是这天下，太难改了。`,
      '功过相抵——改革的常态，本就如此。',
      [
        {c:'sushi',    t:'介甫是真想做事的人，只是这天下，太难改了。'},
        {c:'simaguang',t:'半成半废，天下纷纷。是非功过，且留与后人去评说。'},
        {c:'wanganshi',t:'尽吾力而已矣。成败得失，岂能尽由人定？'},
      ]);

  return ending('decline','壮志未酬',
      `你拼尽全力，却终究没能扭过积重难返的大势。新法在反对声中渐渐褪色，你也黯然去国。<span class="em">呜呼！熙宁七年，果然是雨点小，而雷声大。</span>可哪怕在最孤独的夜里，你也不曾后悔动这把刀——有些事，明知极难，仍要有人去做。`,
      '综合国势未能扭转——但你已问心无愧。',
      [
        {c:'shenzong', t:'时也，势也，非战之罪。卿已尽力，朕知之。'},
        {c:'simaguang',t:'其法虽败，其志可悯。安石，非为一己之私也。'},
        {c:'sushi',    t:'明知不可为而为之——介甫，亦仁人志士也。'},
        {c:'wanganshi',t:'虽千万人，吾往矣。有些事明知极难，仍要有人去做。'},
      ]);

  function ending(bg,title,text,note,comments){ return {bg,title,text,note,comments:comments||[]}; }
}

/* ============ 引擎 ============ */
const Game = {
  state:null, cur:null,

  start(){ this.state = {...INIT}; this.go('s1'); switchScreen('game'); renderStats(true); BGM.start(); },

  go(id){
    if(id==='END'){ this.end(); return; }
    const sc = SCENES[id]; this.cur = sc;
    document.getElementById('turnNum').textContent = CN_NUM[sc.turn] || sc.turn;
    const img = document.getElementById('sceneImg');
    img.src = `assets/${sc.img}.png`;
    document.getElementById('sceneTag').textContent = sc.tag;
    const charEl = document.getElementById('sceneChar');
    if(sc.char && CHARS[sc.char]){
      const c = CHARS[sc.char];
      charEl.style.display = 'flex';
      charEl.innerHTML = `<img src="assets/${c.img}.png" alt="${c.name}">`+
        `<div><div class="ch-name">${c.name}</div><div class="ch-role">${c.role}</div></div>`;
    } else { charEl.style.display='none'; charEl.innerHTML=''; }
    document.getElementById('sceneTitle').textContent = sc.title;
    document.getElementById('sceneText').innerHTML = sc.text;
    // 重新触发卡片入场动画
    const card = document.getElementById('sceneCard');
    card.style.animation='none'; void card.offsetWidth; card.style.animation='';
    const box = document.getElementById('choices'); box.innerHTML='';
    sc.choices.forEach(ch=>{
      const b=document.createElement('button'); b.className='choice'; b.dataset.k=ch.k;
      b.innerHTML=`<div class="choice-t">${ch.t}</div><div class="choice-d">${ch.d}</div>`;
      b.onclick=()=>this.choose(ch);
      box.appendChild(b);
    });
    window.scrollTo({top:0,behavior:'smooth'});
  },

  choose(ch){
    const fx = ch.fx||{};
    for(const k in fx) this.state[k]=clamp(this.state[k]+fx[k]);
    renderStats();
    showFx(fx);
    setTimeout(()=>this.go(ch.next), 520);
  },

  end(){
    const r = computeEnding(this.state);
    document.getElementById('endBg').style.backgroundImage=`url('assets/${r.bg}.png')`;
    document.getElementById('endTitle').textContent=r.title;
    document.getElementById('endText').innerHTML=r.text;
    document.getElementById('endNote').textContent=r.note;
    document.getElementById('endTag').textContent = r.bg==='prosper' ? '功 成' : '终 章';
    const es=document.getElementById('endStats'); es.innerHTML='';
    STAT_META.forEach(m=>{
      const v=this.state[m.key];
      es.innerHTML+=`<span class="end-stat">${m.name} <b>${v}</b></span>`;
    });
    // 人物点评
    const ec=document.getElementById('endComments');
    if(ec){
      const cs = r.comments || [];
      if(cs.length){
        ec.style.display='block';
        ec.innerHTML = `<div class="ec-title">是非功过 · 时人评说</div>` +
          cs.map(it=>{
            const c = CHARS[it.c] || {name:'佚名',img:'p_wanganshi',role:''};
            return `<div class="ec-item">`+
              `<img class="ec-face" src="assets/${c.img}.png" alt="${c.name}">`+
              `<div class="ec-body"><div class="ec-name">${c.name}<span class="ec-role">${c.role||''}</span></div>`+
              `<div class="ec-quote">${it.t}</div></div></div>`;
          }).join('');
      } else { ec.style.display='none'; ec.innerHTML=''; }
    }
    switchScreen('ending');
    window.scrollTo({top:0});
  },

  restart(){ switchScreen('cover'); }
};

/* ============ 史海钩沉 · 史料出处弹层 ============ */
const Lore = {
  open(){ const m=document.getElementById('loreMask'); if(m) m.classList.add('show'); },
  close(){ const m=document.getElementById('loreMask'); if(m) m.classList.remove('show'); }
};
document.addEventListener('keydown',e=>{ if(e.key==='Escape') Lore.close(); });

/* ============ 渲染辅助 ============ */
function renderStats(build){
  const box=document.getElementById('stats');
  if(build) box.innerHTML='';
  STAT_META.forEach(m=>{
    const v=Game.state[m.key];
    let el=document.getElementById('stat-'+m.key);
    if(!el){
      el=document.createElement('div'); el.className='stat'; el.id='stat-'+m.key;
      el.innerHTML=`<div class="stat-head"><span class="stat-name">${m.name}</span>`+
        `<span class="stat-val" id="val-${m.key}"></span></div>`+
        `<div class="stat-bar"><div class="stat-fill" id="fill-${m.key}"></div></div>`;
      box.appendChild(el);
    }
    document.getElementById('val-'+m.key).textContent=v;
    document.getElementById('fill-'+m.key).style.width=v+'%';
    // 危险状态：invert 指标高 / 正向指标低 时变红
    el.className='stat '+riskClass(m,v);
  });
}
function riskClass(m,v){
  if(m.invert){ return v>=75?'danger':v>=50?'warn':'good'; }
  if(m.key==='reform'||m.key==='court') return v>=55?'gold':v>=30?'warn':'danger';
  return v>=55?'good':v>=30?'warn':'danger';
}

function showFx(fx){
  const t=document.getElementById('fxToast'); t.innerHTML='';
  const order=['emperor','court','people','finance','reform','oldParty'];
  order.forEach(k=>{
    if(!(k in fx)||fx[k]===0) return;
    const meta=STAT_META.find(m=>m.key===k);
    const delta=fx[k];
    // 对 invert 指标：数值下降是好事（绿），上升是坏事（红）
    const benefit = meta.invert ? delta<0 : delta>0;
    const chip=document.createElement('span');
    chip.className='fx-chip '+(benefit?'up':'down');
    chip.textContent=`${meta.name} ${delta>0?'+':''}${delta}`;
    t.appendChild(chip);
  });
  if(!t.children.length) return;
  t.classList.add('show');
  clearTimeout(showFx._t);
  showFx._t=setTimeout(()=>t.classList.remove('show'),1800);
}

function switchScreen(id){
  document.querySelectorAll('.screen').forEach(s=>s.classList.remove('active'));
  document.getElementById(id).classList.add('active');
}

/* 预加载图片，避免切换闪烁 */
['court','minister','farm','market','militia','prosper','decline',
 'p_wanganshi','p_shenzong','p_simaguang','p_zhengxia','p_sushi',
 'pdf_img5','pdf_img7','pdf_img8','pdf_img11','pdf_img13'].forEach(n=>{
  const i=new Image(); i.src=`assets/${n}.png`;
});

/* ============================================================================
   古风背景音乐 · 《雨过宣德》 —— Web Audio 实时合成，无任何外部音频文件
   ----------------------------------------------------------------------------
   设计：
   · 一段确定的 32 拍主旋律乐句（D 宫五声：宫D 商E 角F# 徵A 羽B），无缝循环；
     重复时在乐句高点做八度跳进 / 倚音加花，主干旋律固定。
   · 配器四层：古筝主旋律（双振荡 detune + 谐波 + 快起音指数衰减拨弦包络）、
     宫-徵-商五度叠置的柔和 pad 长音垫（带呼吸 LFO，极低音量做底色）、
     每小节一个低音根音给骨架、每拍一记低通木鱼稳节奏。
   · 混响：ConvolverNode + 程序生成的指数衰减白噪声脉冲响应（约 2.6s）。
   · 节拍：基于 AudioContext.currentTime 的 look-ahead 预排程
     （setInterval 25ms 检查、提前 0.12s 排音），节奏不漂不卡。
   · master 峰值 ~0.30，淡入约 2.6s。
   · 注意：此对象现作为「降级兜底」使用——仅当成品音频文件加载/播放失败时启用。
   ========================================================================== */
const BGMSynth = {
  ctx:null, master:null, reverb:null, wet:null, dry:null,
  timer:null, on:false,
  // —— 时基 ——
  tempo:60, ahead:0.12, lookahead:25,
  nextBeat:0, beatCount:0, LOOP:32,

  // D 宫五声音阶（宫商角徵羽），跨三个八度
  PENTA:[
    146.83,164.81,185.00,220.00,246.94,   // idx 0-4   低区（3区）
    293.66,329.63,369.99,440.00,493.88,   // idx 5-9   中区（4区）
    587.33,659.25,739.99,880.00,987.77    // idx 10-14 高区（5区）
  ],

  // —— 主旋律乐句：{b:起拍, i:音阶序号, d:时值(拍), v:力度} ——
  // 8 小节 4/4，共 32 拍，24 个音，起承转合可循环
  MELODY:[
    // 起：徵—羽—宫（4区落到5区宫）
    {b:0,i:8,d:1,v:.42},{b:1,i:9,d:1,v:.38},{b:2,i:10,d:2,v:.46},
    {b:4,i:7,d:1,v:.40},{b:5,i:8,d:1,v:.36},{b:6,i:6,d:2,v:.42},
    // 承：回到中区盘旋
    {b:8,i:5,d:1,v:.38},{b:9,i:7,d:1,v:.36},{b:10,i:8,d:1,v:.40},{b:11,i:7,d:1,v:.34},
    {b:12,i:6,d:2,v:.40},{b:14,i:5,d:2,v:.44},
    // 转：推到高区商音
    {b:16,i:8,d:1,v:.42},{b:17,i:10,d:1,v:.40},{b:18,i:11,d:2,v:.46},
    {b:20,i:10,d:1,v:.40},{b:21,i:9,d:1,v:.36},{b:22,i:8,d:2,v:.42},
    // 合：层层下行收束到宫
    {b:24,i:9,d:1,v:.38},{b:25,i:10,d:1,v:.40},{b:26,i:9,d:1,v:.36},{b:27,i:8,d:1,v:.34},
    {b:28,i:7,d:2,v:.40},{b:30,i:5,d:2,v:.44}
  ],
  // —— 低音根音：每小节一个（拍 0,4,8,…），D 宫调骨架 ——
  BASS:[ {b:0,f:73.42},{b:4,f:110.00},{b:8,f:82.41},{b:12,f:73.42},
         {b:16,f:110.00},{b:20,f:123.47},{b:24,f:110.00},{b:28,f:73.42} ],

  init(){
    if(this.ctx) return;
    const AC = window.AudioContext || window.webkitAudioContext;
    const ctx = this.ctx = new AC();
    this.master = ctx.createGain(); this.master.gain.value = 0.0001;
    this.master.connect(ctx.destination);
    // 混响：程序生成脉冲响应（指数衰减白噪声 ≈2.6s）
    this.reverb = ctx.createConvolver();
    this.reverb.buffer = this._makeIR(2.6, 2.4);
    this.wet = ctx.createGain(); this.wet.gain.value = 0.36;
    this.reverb.connect(this.wet); this.wet.connect(this.master);
    this.dry = ctx.createGain(); this.dry.gain.value = 0.92;
    this.dry.connect(this.master);
    // 和声铺底 pad：宫D-徵A-商E 五度叠置
    this._buildPad([146.83, 220.00, 329.63]);
  },

  // 生成混响脉冲响应
  _makeIR(dur, decay){
    const ctx=this.ctx, rate=ctx.sampleRate, len=Math.floor(rate*dur);
    const buf=ctx.createBuffer(2,len,rate);
    for(let c=0;c<2;c++){
      const d=buf.getChannelData(c);
      for(let i=0;i<len;i++) d[i]=(Math.random()*2-1)*Math.pow(1-i/len,decay);
    }
    return buf;
  },

  // 柔和长音和弦垫（带呼吸 LFO），常驻运行，由 master 控制总量
  _buildPad(freqs){
    const ctx=this.ctx;
    const pg=ctx.createGain(); pg.gain.value=0.0;
    const lp=ctx.createBiquadFilter(); lp.type='lowpass'; lp.frequency.value=820;
    pg.connect(lp); lp.connect(this.dry); lp.connect(this.reverb);
    freqs.forEach(f=>{
      const o =ctx.createOscillator(); o.type='triangle'; o.frequency.value=f;
      const o2=ctx.createOscillator(); o2.type='sine';     o2.frequency.value=f; o2.detune.value=6;
      const g =ctx.createGain(); g.gain.value=0.017;
      o.connect(g); o2.connect(g); g.connect(pg);
      o.start(); o2.start();
    });
    // 呼吸 LFO：让 pad 强弱缓慢起伏
    const lfo=ctx.createOscillator(); lfo.type='sine'; lfo.frequency.value=0.07;
    const la =ctx.createGain(); la.gain.value=0.45;
    const base=ctx.createConstantSource(); base.offset.value=0.62;
    lfo.connect(la); la.connect(pg.gain); base.connect(pg.gain);
    lfo.start(); base.start();
  },

  // 古筝拨弦：双振荡 detune 增厚 + 二次谐波 + 快起音指数衰减
  pluck(freq,t,dur,vel){
    const ctx=this.ctx;
    const g=ctx.createGain();
    g.gain.setValueAtTime(0.0001,t);
    g.gain.linearRampToValueAtTime(vel,t+0.006);
    g.gain.exponentialRampToValueAtTime(0.0001,t+dur);
    const lp=ctx.createBiquadFilter(); lp.type='lowpass';
    lp.frequency.setValueAtTime(6500,t);
    lp.frequency.exponentialRampToValueAtTime(1700,t+dur*0.85);
    g.connect(lp); lp.connect(this.dry); lp.connect(this.reverb);
    const o1=ctx.createOscillator(); o1.type='triangle'; o1.frequency.value=freq; o1.detune.value=-6;
    const o2=ctx.createOscillator(); o2.type='triangle'; o2.frequency.value=freq; o2.detune.value= 7;
    const h =ctx.createOscillator(); h.type='sine';      h.frequency.value=freq*2;
    const hg=ctx.createGain(); hg.gain.value=0.15; h.connect(hg); hg.connect(g);
    o1.connect(g); o2.connect(g);
    o1.start(t); o2.start(t); h.start(t);
    o1.stop(t+dur+0.06); o2.stop(t+dur+0.06); h.stop(t+dur+0.06);
  },

  // 低音根音：正弦+三角，低通，给节奏骨架
  bass(freq,t,dur,vel){
    const ctx=this.ctx;
    const g=ctx.createGain();
    g.gain.setValueAtTime(0.0001,t);
    g.gain.linearRampToValueAtTime(vel,t+0.03);
    g.gain.exponentialRampToValueAtTime(0.0001,t+dur);
    const lp=ctx.createBiquadFilter(); lp.type='lowpass'; lp.frequency.value=420;
    g.connect(lp); lp.connect(this.dry); lp.connect(this.reverb);
    const o =ctx.createOscillator(); o.type='sine';     o.frequency.value=freq;
    const o2=ctx.createOscillator(); o2.type='triangle'; o2.frequency.value=freq; o2.detune.value=4;
    const o2g=ctx.createGain(); o2g.gain.value=0.4; o2.connect(o2g); o2g.connect(g);
    o.connect(g);
    o.start(t); o2.start(t); o.stop(t+dur+0.05); o2.stop(t+dur+0.05);
  },

  // 木鱼：极短低通噪声脉冲，稳节奏
  woodfish(t,vel){
    const ctx=this.ctx;
    const len=Math.floor(ctx.sampleRate*0.06);
    const buf=ctx.createBuffer(1,len,ctx.sampleRate);
    const d=buf.getChannelData(0);
    for(let i=0;i<len;i++) d[i]=(Math.random()*2-1)*Math.pow(1-i/len,3);
    const src=ctx.createBufferSource(); src.buffer=buf;
    const lp=ctx.createBiquadFilter(); lp.type='lowpass'; lp.frequency.value=680;
    const g=ctx.createGain(); g.gain.value=vel;
    src.connect(lp); lp.connect(g); g.connect(this.dry); g.connect(this.reverb);
    src.start(t); src.stop(t+0.06);
  },

  // 排一拍的所有声部
  _scheduleBeat(count,t){
    const pos=count%this.LOOP, loopN=Math.floor(count/this.LOOP);
    const spb=60/this.tempo;
    // 主旋律
    const m=this.MELODY.find(n=>n.b===pos);
    if(m){
      let i=m.i;
      // 变奏：奇数轮在乐句高点做八度跳进 / 加花倚音，主干不变
      if(loopN%2===1){
        if(pos===2||pos===18) i=Math.min(i+5,14);            // 八度跳进
        if(pos===10||pos===26){                               // 前倚音加花
          const gt=t-spb*0.22;
          if(gt>this.ctx.currentTime)
            this.pluck(this.PENTA[Math.min(i+1,14)], gt, spb*0.3, m.v*0.5);
        }
      }
      this.pluck(this.PENTA[i], t, Math.max(m.d*spb*1.05,0.5), m.v);
    }
    // 低音：每小节根音
    const b=this.BASS.find(n=>n.b===pos);
    if(b) this.bass(b.f, t, spb*2.4, 0.22);
    // 木鱼：每拍，正拍稍重、弱拍更轻
    this.woodfish(t, pos%4===0?0.10:0.05);
  },

  // look-ahead 调度器
  _scheduler(){
    while(this.nextBeat < this.ctx.currentTime + this.ahead){
      this._scheduleBeat(this.beatCount, this.nextBeat);
      this.nextBeat += 60/this.tempo;
      this.beatCount++;
    }
  },

  start(){
    this.init();
    if(this.ctx.state==='suspended') this.ctx.resume();
    this.on=true;
    const now=this.ctx.currentTime;
    this.master.gain.cancelScheduledValues(now);
    this.master.gain.setValueAtTime(Math.max(this.master.gain.value,0.0001),now);
    this.master.gain.linearRampToValueAtTime(this.level, now+2.6);     // 柔和淡入
    if(!this.timer){
      this.beatCount=0; this.nextBeat=now+0.15;                  // 从乐句开头起
      this._scheduler();
      this.timer=setInterval(()=>{ if(this.on) this._scheduler(); }, this.lookahead);
    }
    const btn=document.getElementById('bgmBtn'); if(btn) btn.classList.add('playing');
  },

  toggle(){
    if(!this.ctx || !this.on){ this.start(); return; }
    this.on=false;
    const now=this.ctx.currentTime;
    this.master.gain.cancelScheduledValues(now);
    this.master.gain.setValueAtTime(this.master.gain.value,now);
    this.master.gain.linearRampToValueAtTime(0.0001, now+0.7);   // 淡出
    if(this.timer){ clearInterval(this.timer); this.timer=null; }
    const btn=document.getElementById('bgmBtn'); if(btn) btn.classList.remove('playing');
  },

  // 合成兜底版的音量：vol(0~1) 映射到主增益（0.5→0.30 与成品音量观感对齐）
  level:0.30,
  setVolume(v){
    this.level=Math.max(0.0001, Math.min(1, v))*0.6;
    if(this.master && this.on){
      const now=this.ctx.currentTime;
      this.master.gain.cancelScheduledValues(now);
      this.master.gain.linearRampToValueAtTime(this.level, now+0.15);
    }
  }
};


/* ============================================================================
   背景音乐 · 成品音频版（首选） + 合成兜底
   ----------------------------------------------------------------------------
   曲目：《Guzheng City》 by Kevin MacLeod (incompetech.com)
   授权：Creative Commons Attribution 4.0 (CC BY 4.0)
   文件：assets/bgm.mp3（古筝 + 鼓点，舒缓古风，loop 无缝循环）
   ----------------------------------------------------------------------------
   行为：
   · BGM.start()：在用户手势（点「入朝·开局」）中触发播放，音量 0→0.5 淡入约 2.6s，
     并给 #bgmBtn 加 .playing 呼吸动画。
   · BGM.toggle()：在播放 / 暂停间切换；暂停时淡出 0.7s 后 pause() 并移除 .playing。
   · 降级兜底：若音频文件加载失败（onerror）或 play() 被拒，自动回退到
     BGMSynth（Web Audio 实时合成版），保证一定有声音。
   ========================================================================== */
const BGM = {
  audio:null, on:false, usingSynth:false, fadeTimer:null,
  vol:(()=>{ const v=parseFloat(localStorage.getItem('songGameVol')); return isNaN(v)?0.5:Math.max(0,Math.min(1,v)); })(),

  _btn(){ return document.getElementById('bgmBtn'); },

  _ensure(){
    if(this.audio || this.usingSynth) return;
    const a = new Audio('assets/bgm.mp3');
    a.loop = true; a.preload = 'auto'; a.volume = 0;
    // 双保险：部分浏览器 loop 属性偶发失效时，结束后手动回到开头重播
    a.addEventListener('ended', ()=>{ if(this.on){ try{ a.currentTime=0; a.play(); }catch(e){} } });
    a.addEventListener('error', ()=>this._fallback());
    this.audio = a;
  },

  // 把滑条当前值同步成「已填充」渐变，并初始化为存储音量
  syncSlider(){
    const s=document.getElementById('volSlider'); if(!s) return;
    s.value=Math.round(this.vol*100);
    const p=s.value+'%';
    s.style.background='linear-gradient(90deg,#c7a85a 0%,#c7a85a '+p+
      ',rgba(230,200,120,.22) '+p+',rgba(230,200,120,.22) 100%)';
  },

  // 设置音量（0~1）：实时作用于成品音频 / 合成兜底，并持久化
  setVolume(v){
    v=Math.max(0,Math.min(1,v));
    this.vol=v;
    localStorage.setItem('songGameVol', v.toFixed(2));
    if(this.audio && !this.fadeTimer){ try{ this.audio.volume=v; }catch(e){} }
    if(this.usingSynth && typeof BGMSynth.setVolume==='function') BGMSynth.setVolume(v);
    this.syncSlider();
  },

  // 切换到合成兜底
  _fallback(){
    if(this.usingSynth) return;
    this.usingSynth = true;
    if(this.fadeTimer){ clearInterval(this.fadeTimer); this.fadeTimer=null; }
    try{ if(this.audio) this.audio.pause(); }catch(e){}
    this.audio = null;
    if(this.on){ BGMSynth.setVolume(this.vol); BGMSynth.start(); }   // 接力播放，按钮 .playing 由 BGMSynth 维护
  },

  // 音量淡变；target<=0 时淡出后自动 pause()
  _fadeTo(target, ms){
    const a=this.audio; if(!a) return;
    if(this.fadeTimer) clearInterval(this.fadeTimer);
    const startV=a.volume, steps=Math.max(1,Math.round(ms/40)); let i=0;
    this.fadeTimer=setInterval(()=>{
      i++; const t=i/steps;
      try{ a.volume=Math.max(0,Math.min(1,startV+(target-startV)*t)); }catch(e){}
      if(i>=steps){
        clearInterval(this.fadeTimer); this.fadeTimer=null;
        if(target<=0){ try{ a.pause(); }catch(e){} }
      }
    },40);
  },

  start(){
    // 已在用合成兜底
    if(this.usingSynth){ BGMSynth.setVolume(this.vol); BGMSynth.start(); this.on=true; return; }
    this._ensure();
    const a=this.audio; if(!a){ this._fallback(); return; }
    this.on=true;
    a.volume=0;
    const p=a.play();
    if(p && p.catch) p.catch(()=>this._fallback());   // 播放被拒 → 兜底
    const btn=this._btn(); if(btn) btn.classList.add('playing');
    this._fadeTo(this.vol, 2600);                      // 0 → 0.5 柔和淡入
  },

  toggle(){
    // 兜底模式下完全委托给合成器
    if(this.usingSynth){
      BGMSynth.toggle(); this.on = BGMSynth.on; return;
    }
    if(!this.audio || !this.on){ this.start(); return; }
    // 正在播放 → 淡出后暂停
    this.on=false;
    this._fadeTo(0, 700);
    const btn=this._btn(); if(btn) btn.classList.remove('playing');
  }
};

// 页面就绪后，把音量滑条同步到本地存储的音量值
if(document.readyState==='loading')
  document.addEventListener('DOMContentLoaded', ()=>BGM.syncSlider());
else
  BGM.syncSlider();
