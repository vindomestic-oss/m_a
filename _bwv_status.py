"""Regenerate bwv_collection_status.txt from what the kern_reader menu really contains.
Run from the reader dir: python ../_bwv_status.py"""
import sys, re, json, collections, datetime
sys.path.insert(0, r'C:\m_a\reader')
import app

ROM = {'I':1,'II':2,'III':3,'IV':4,'V':5,'VI':6,'VII':7,'VIII':8,'IX':9,'X':10,'XI':11,'XII':12,'XIII':13,'XIV':14,'XV':15,'XIX':19}

def bwvs(rel):
    r = rel.replace(chr(92), '/'); low = r.lower()
    stem = low.rsplit('/', 1)[-1].rsplit('.', 1)[0]
    out = set(); chor = False
    for m in re.finditer(r'bwv[-_ ]?0*(\d+)', low): out.add(int(m.group(1)))
    m = re.match(r'wtc([12])[pf](\d+)', stem)
    if m: out.add((846 if m.group(1) == '1' else 870) + int(m.group(2)) - 1)
    m = re.match(r'(?:bach_)?inven(?:tion)?_?(\d+)', stem)
    if m and 1 <= int(m.group(1)) <= 15: out.add(771 + int(m.group(1)))
    m = re.match(r'bach-(\d+)-', stem)
    if m: out.add(int(m.group(1)))
    m = re.match(r'cantata_(\d+)', stem)
    if m: out.add(int(m.group(1)))
    m = re.search(r'french[_-]suite[_-](\d)', stem)
    if m: out.add(811 + int(m.group(1)))
    m = re.search(r'english_suite_(\d)', stem)
    if m: out.add(805 + int(m.group(1)))
    m = re.match(r'cellosuite(\d)', stem)
    if m: out.add(1006 + int(m.group(1)))
    m = re.search(r'partita(?:_|)(\d)', stem)
    if m and ('violin' in r or 'cello' in r):
        out.add({1: 1002, 2: 1004, 3: 1006}.get(int(m.group(1)), 0) or 0)
    m = re.match(r'sonata(\d)-', stem)
    if m and 'violin' in r: out.add({1: 1001, 2: 1003, 3: 1005}.get(int(m.group(1)), 0) or 0)
    m = re.match(r'bach_duet(\d)', stem)
    if m: out.add(801 + int(m.group(1)))
    if stem.startswith(('contrapunctus', 'f9', 'duetto')): out.add(1080)
    if r.startswith('craigsapp/bach/musical-offering'): out.add(1079)
    if stem.startswith('brandenburg1'): out.add(1046)
    if stem.startswith('brand5'): out.add(1050)
    if stem.startswith('concerto_in_e_major'): out.add(1042)
    if stem.startswith('concerto_in_d_minor'): out.add(1043)
    if stem.startswith('passacaglia'): out.add(582)
    if stem.startswith('toccatafugue'): out.add(565)
    if stem == 'wtk1_prelude1' or stem == 'wtk1_fugue1': out.add(846)
    if stem in ('wtk2prelude1', 'wtk2fuga1'): out.add(870)
    if re.match(r'chor\d+$', stem): chor = True
    out.discard(0)
    return out, chor

files = (app.find_generated_files() + app.find_lilypond_files() + app.find_kern_files(app.KERN_DIR)
         + app.find_tobis_files() + app.find_musedata_mxl_files())
cov = collections.defaultdict(int); nchor = 0
for rel, full in files:
    if app._composer_from_rel(rel) != 'Bach': continue
    s, chor = bwvs(rel)
    nchor += chor
    for n in s: cov[n] += 1
if nchor:                                   # craigsapp chorales are numbered by chorN, not BWV
    for n in range(253, 439): cov[n] = cov[n] or 1

ref = {}
for w in json.load(open(r'C:\m_a\bach_works.json', encoding='cp1252', errors='replace')):
    for m in re.finditer(r'BWV (\d+)', w['title']):
        ref.setdefault(int(m.group(1)), re.sub(r'\s*\(Bach.*', '', w['title']))

SECTIONS = [
 ('Кантаты', 1, 224), ('Мотеты', 225, 231), ('Мессы / Магнификат / Sanctus', 232, 243),
 ('Пассионы и оратории', 244, 249), ('Хоралы (4-голосные)', 253, 438),
 ('Песни (Шемелли, Нотенбюхлайн)', 439, 524), ('Органные сонаты', 525, 530),
 ('Органные прелюдии, фуги, токкаты, фантазии', 531, 598),
 ('Orgelbüchlein', 599, 644), ('Шюблеровские хоралы', 645, 650),
 ('18 больших хоральных прелюдий', 651, 668), ('Clavier-Übung III и др. хоральные обработки', 669, 771),
 ('Инвенции и синфонии', 772, 801), ('Дуэты BWV 802–805', 802, 805),
 ('Французские и английские сюиты', 806, 817), ('Клавирные партиты', 825, 830),
 ('Увертюра, Итальянский концерт и др. большие клавирные', 831, 845),
 ('ХТК I и II', 846, 893), ('Прелюдии, фуги, фантазии, токкаты для клавира', 894, 923),
 ('Малые прелюдии и сюиты', 924, 987), ('Гольдберг и поздние клавирные', 988, 1000),
 ('Скрипка и виолончель соло', 1001, 1012), ('Камерные сонаты', 1013, 1040),
 ('Концерты', 1041, 1065), ('Оркестровые сюиты и каноны', 1066, 1078),
 ('Музыкальное приношение и Искусство фуги', 1079, 1080),
]

def rng(ns):
    out = []; s = p = None
    for n in ns:
        if s is None: s = p = n
        elif n == p + 1: p = n
        else: out.append((s, p)); s = p = n
    if s is not None: out.append((s, p))
    return out

L = ['СТАТУС КОЛЛЕКЦИИ BWV (автоматически из меню kern_reader)',
     'Дата: ' + datetime.date.today().isoformat(),
     'Источник "что есть": find_* из reader/app.py; "что должно быть": bach_works.json (IMSLP).',
     'Номера BWV извлечены из имён файлов; файлы с нестандартными именами могут быть не учтены.',
     '=' * 78, '']
tot_c = tot_all = 0
M = ['BWV, которых ещё нет в меню kern_reader',
     'Составлено ' + datetime.date.today().isoformat() + ' из bwv_collection_status.txt (то, что реально есть в меню) и bach_works.json (каталог IMSLP).',
     'Название берётся из каталога IMSLP; для номеров без названия оно пустое.',
     'Файлы MusicXML / .mxl кладутся в musicxml/musedata/ (меню подхватывает всё оттуда автоматически),',
     'kern — в kern/.. , после чего перезапуск kern_reader.',
     '=' * 78, '']
tot_miss = 0
for name, a, b in SECTIONS:
    universe = sorted({n for n in ref if a <= n <= b} | {n for n in cov if a <= n <= b})
    if name.startswith('ХТК'): universe = list(range(846, 894))
    if name.startswith('Инвенции'): universe = list(range(772, 802))
    if name.startswith('Дуэты'): universe = [802, 803, 804, 805]
    if name.startswith('Хоралы'): universe = [n for n in range(253, 439) if n != 259 and n != 264 and n != 269 and n != 347]
    have = [n for n in universe if cov.get(n)]
    miss = [n for n in universe if not cov.get(n)]
    tot_c += len(have); tot_all += len(universe)
    L.append(f'{name}  (BWV {a}–{b}):  {len(have)} из {len(universe)}')
    if miss and len(miss) <= 120:
        for x, y in rng(miss):
            t = ref.get(x, '')
            L.append(f'    нет  {x}' + (f'–{y}' if y != x else '') + (f'   {t[:60]}' if t else ''))
    elif miss:
        L.append(f'    нет  {len(miss)} номеров, первые: ' + ', '.join(map(str, miss[:15])))
    L.append('')
    M.append(f'{name}  (BWV {a}–{b}): нет {len(miss)} из {len(universe)}')
    tot_miss += len(miss)
    for x in miss: M.append(f'  BWV {x:<5} ' + ref.get(x, '')[:70])
    M.append('')
L.append(f'ИТОГО: {tot_c} из {tot_all} номеров BWV из списка')
open(r'C:\m_a\bwv_collection_status.txt', 'w', encoding='utf-8').write('\n'.join(L))
M.append(f'ВСЕГО отсутствует номеров: {tot_miss}')
open(r'C:\m_a\bwv_missing.txt', 'w', encoding='utf-8').write('\n'.join(M))
print('\n'.join(L))
