# =============================================================================
# マイ銘柄「本日の主な材料」生成器（第259・本番配信版／generator v3 由来）
# 出力: 標準出力に JSON（GitHub Actions が mycoin_extnews.json へ保存→raw配信）。
# 仕様（第258確定・ユーザー承認）:
#   (A) 当日ゲート＝published が直近24時間以内の見出しのみ採用。
#   (B) 材料フィルタ（Haiku相乗り material）＝価格材料になりうる見出しのみ true。
#   (C) 銘柄関連フィルタ（Haiku相乗り relevant）＝その銘柄自身の材料のみ true。
#   → material かつ relevant のみ新着順 top2 を採用。無ければ空（ページ側で非表示）。
#   → 因果は断定しない（第248）。枠名は「本日の主な材料」。AI要約はしない（見出しの翻訳のみ）。
# コスト: RSS取得¥0＋Haiku 1コール/実行。3時間ごと想定＝月¥100前後（承認済）。
# 法務: 見出し＋出典＋リンクのアグリゲーション（AI要約なし・リンクアウト）。非因果。
# キー: ANTHROPIC_API_KEY は環境変数（GitHub Secret）から読む。未設定なら分類不能＝空で出力（課金・crashなし）。
#   --no-llm : Haiku を呼ばず、直近24hの信頼媒体候補（分類前）を出力（ローカル¥0ドライラン用）。
# =============================================================================
# -*- coding: utf-8 -*-
import os, requests, xml.etree.ElementTree as ET, json, re, sys
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

_MODEL_HAIKU = "claude-haiku-4-5-20251001"
UA = {'User-Agent': 'Mozilla/5.0 (compatible; BittimesBot/1.0)'}
NS = '{http://news.google.com/rss}'
NO_LLM = '--no-llm' in sys.argv
WINDOW_HOURS = 24  # 直近24時間（ユーザー承認・第258）
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

COINS = {
    'BTC': 'Bitcoin BTC', 'ETH': 'Ethereum ETH', 'XRP': 'XRP Ripple',
    'SOL': 'Solana SOL', 'ADA': 'Cardano ADA', 'DOGE': 'Dogecoin DOGE',
    'SUI': 'Sui crypto',
    # v4（第262・構造修正）: マイ銘柄/タグボタンは10銘柄提供なのに生成器は7銘柄で、
    # LINK/SHIB/AVAX は「本日の主な材料」が構造的に永久非表示だった。10銘柄に一致させる。
    'LINK': 'Chainlink LINK', 'SHIB': 'Shiba Inu SHIB', 'AVAX': 'Avalanche AVAX',
}
ALLOWED_SOURCES = {
    'reuters', 'associated press', 'ap news', 'bloomberg', 'bloomberg.com',
    'financial times', 'ft', 'politico', 'politico.com',
    'coindesk', 'cointelegraph', 'the block', 'decrypt', 'cnbc',
    'forbes', 'fortune', 'yahoo finance',
    # v4（第262・判断1 A案・ユーザー承認）: 日本語の信頼金融/報道媒体を追加（海外英語24h媒体では
    # 拾えないアルト銘柄の空率を下げる）。自社(bittimes)・競合まとめ媒体(coinpost等)は入れない。
    'ロイター', 'reuters japan', 'ブルームバーグ', 'bloomberg.co.jp',
    '日本経済新聞', '日経', '日経クロステック', '日経bp',
    'coindesk japan', 'コインデスク・ジャパン', 'coindesk japan（コインデスク・ジャパン）',
    'cointelegraph japan', 'コインテレグラフ ジャパン', 'コインテレグラフジャパン',
    'forbes japan', 'forbes japan（フォーブス ジャパン）', 'cnbc japan',
}

# 日本語ロケール用の検索語（ja-JP フィードは日本語名の方がヒットする）。
COINS_JA = {
    'BTC': 'ビットコイン', 'ETH': 'イーサリアム', 'XRP': 'リップル XRP',
    'SOL': 'ソラナ', 'ADA': 'カルダノ', 'DOGE': 'ドージコイン',
    'SUI': 'SUI 仮想通貨', 'LINK': 'チェーンリンク', 'SHIB': 'シバイヌ 仮想通貨',
    'AVAX': 'アバランチ 仮想通貨',
}
# 収集ロケール（英語圏＝海外速報／日本語圏＝国内信頼報道・A案で追加）。
LOCALES = (
    {'hl': 'en-US', 'gl': 'US', 'ceid': 'US:en', 'q': COINS},
    {'hl': 'ja',    'gl': 'JP', 'ceid': 'JP:ja', 'q': COINS_JA},
)

def source_of(item):
    el = item.find(NS + 'source') or item.find('source')
    return ((el.text if el is not None else '') or '').strip()

def clean_title(t, src):
    if src and t.endswith(' - ' + src):
        t = t[:-(len(src) + 3)]
    return t.strip()

def pubdt(s):
    try:
        d = parsedate_to_datetime(s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d
    except Exception:
        return datetime(1970, 1, 1, tzinfo=timezone.utc)

now = datetime.now(timezone.utc)
cutoff = now - timedelta(hours=WINDOW_HOURS)

# 1) 収集（銘柄別・厳格媒体・直近24h・新着順）。分類前に候補を最大6件保持（材料で絞った後に top2）。
#    v4（第262）: en-US（海外速報）＋ ja-JP（国内信頼報道）の2ロケールを収集し銘柄ごとに統合（新着順 top6）。
def fetch_locale(query, loc):
    rows = []
    try:
        r = requests.get('https://news.google.com/rss/search',
                         params={'q': f'{query} when:2d', 'hl': loc['hl'],
                                 'gl': loc['gl'], 'ceid': loc['ceid']},
                         headers=UA, timeout=25)
        root = ET.fromstring(r.content)
        for it in root.findall('.//item'):
            src = source_of(it)
            if src.lower() not in ALLOWED_SOURCES:
                continue
            dt = pubdt(it.findtext('pubDate') or '')
            if dt < cutoff:                     # (A) 直近24hゲート
                continue
            title = clean_title(it.findtext('title') or '', src)
            rows.append({'source': src, 'title_en': title, 'url': it.findtext('link') or '',
                         'published': it.findtext('pubDate') or '', '_dt': dt})
    except Exception:
        pass
    return rows

collected = {}
flat = []
for sym in COINS:
    merged = []
    seen = set()
    for loc in LOCALES:
        query = loc['q'].get(sym)
        if not query:
            continue
        for row in fetch_locale(query, loc):
            k = row['title_en'].lower()[:40]     # 見出し先頭で言語横断の重複を抑止
            if k in seen:
                continue
            seen.add(k)
            merged.append(row)
    merged.sort(key=lambda x: x['_dt'], reverse=True)
    cands = merged[:6]
    for p in cands:
        p['_sym'] = sym
    collected[sym] = cands
    for p in cands:
        flat.append(p)

# 2) 日本語化＋材料分類（Haiku 1コール相乗り）。キー未設定/--no-llm はスキップ。
if flat and not NO_LLM and ANTHROPIC_API_KEY:
    import anthropic
    numbered = "\n".join(f"{i}. [{p['_sym']}] {p['title_en']}" for i, p in enumerate(flat))
    sys_t = (
        "あなたは金融・仮想通貨ニュースの編集者兼翻訳者です。各見出しには対象銘柄が [SYM] で付きます。"
        "各見出しについて3つを行う:\n"
        "(1) 日本の金融メディアにふさわしい自然で簡潔な日本語見出しに訳す（誇張・憶測・因果を足さない・"
        "事実の見出しをそのまま訳す・固有名詞/数値は正確に）。**訳文(ja)には先頭の[SYM]タグを含めない**。\n"
        "(2) material: その見出しが『暗号資産の価格を動かす材料になりうるニュースか』(true/false)。"
        "材料になりうる=規制・法規制/当局承認・ETF/上場・上場廃止/ハッキング・資金流出/大口の売買・保有/"
        "主要企業や国家の採用・提携/要人発言(要人=当局者・著名投資家・企業CEO)/マクロ(金利・ドル・株価)。"
        "材料でない=価格予想だけの観測記事・比較記事(どっちを買うべき等)・使い方/解説・詐欺注意喚起・広告的内容。\n"
        "(3) relevant: その見出しが『対象銘柄[SYM]自身の値動き材料』として直接関係するか(true/false)。"
        "他銘柄が主題で[SYM]に偶然言及しただけ・一般市況(ビットコイン全体の話をETH枠で拾った等)は false。"
        "[SYM]自身の出来事・[SYM]を主対象にした材料のみ true。\n"
        "category には該当カテゴリを日本語1語で（規制/承認/上場/ハッキング/大口/採用/提携/発言/マクロ/その他）。\n"
        "出力は必ずJSON配列 [{\"i\":0,\"ja\":\"...\",\"material\":true,\"relevant\":true,\"category\":\"承認\"}, ...] のみ。"
    )
    usr_t = f"次の見出しを処理してJSON配列で返す（番号iを保持）:\n{numbered}"
    try:
        cli = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp = cli.messages.create(model=_MODEL_HAIKU, max_tokens=2200,
                                   system=[{"type": "text", "text": sys_t}],
                                   messages=[{"role": "user", "content": usr_t}])
        raw = resp.content[0].text.strip()
        m = re.search(r'\[.*\]', raw, re.S)
        arr = json.loads(m.group(0)) if m else []
        info = {int(o['i']): o for o in arr if 'i' in o}
        for i, p in enumerate(flat):
            o = info.get(i, {})
            ja = o.get('ja') or ''
            p['title_ja'] = re.sub(r'^\s*\[[A-Za-z0-9]+\]\s*', '', ja)  # 混入した[SYM]タグを除去（安全側）
            p['material'] = bool(o.get('material'))
            p['relevant'] = bool(o.get('relevant'))
            p['category'] = o.get('category') or ''
    except Exception:
        # 分類失敗時は fail-open せず「材料不明」を除外側に倒す（憶測で出さない）
        for p in flat:
            p['title_ja'] = p.get('title_ja') or ''
            p['material'] = False
            p['relevant'] = False
            p['category'] = ''
elif NO_LLM:
    for p in flat:
        p['title_ja'] = ''
        p['material'] = None  # 未判定（ドライランでは分類前）
        p['relevant'] = None
        p['category'] = ''
else:
    # ANTHROPIC_API_KEY 未設定（Secret未投入）＝分類不能＝空で出す（英語候補は出さない・課金なし）。
    for p in flat:
        p['title_ja'] = ''
        p['material'] = False
        p['relevant'] = False
        p['category'] = ''

# 3) 出力（material かつ relevant のみ・新着順 top2／--no-llm は分類前候補を top2）
out = {'generated_at': now.isoformat(timespec='seconds'),
       'window_hours': WINDOW_HOURS,
       'note': '本日の主な材料（直近24h・価格材料の見出しのみ・AI要約なし・出典明記・リンクアウト・非因果）',
       'coins': {}}
for sym, cands in collected.items():
    if NO_LLM:
        picks = cands[:2]
    else:
        picks = [p for p in cands if p.get('material') and p.get('relevant')][:2]
    out['coins'][sym] = [{'source': p['source'],
                          'title_ja': p.get('title_ja') or p['title_en'],
                          'title_en': p['title_en'], 'url': p['url'],
                          'published': p['published'],
                          'category': p.get('category', '')}
                         for p in picks]
print(json.dumps(out, ensure_ascii=False, indent=2))
