#!/usr/bin/env python3
"""登録者が少ないのに再生が伸びている動画を、ジャンル別のキーワード検索から集める。

急上昇（mostPopular）には大きなチャンネルしか載らないため、
直近 N 日に公開された動画を再生数順に検索し、登録者数で絞り込む。

使い方:
  YOUTUBE_API_KEY=xxxx python3 scripts/collect_small.py [--profile general|knowledge] [--max-subs 5000]

プロファイル:
  general    いろいろなジャンル・ショートも含む（直近7日）→ data/small/
  knowledge  解説・勉強・知識系の横動画（4分以上・直近14日）。切り抜き等を除く → data/knowledge/
  games      建築・スローライフ・シミュレーション/クラフト系ゲームの横動画（4分以上・直近14日）→ data/games/
API 使用量: 検索 1 回 100 ユニット。general 約 3,000、knowledge 約 3,200、games 約 2,000
"""
import argparse, json, os, re, sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(__file__))
from collect import JST, MAX_TAGS, api_get, parse_duration, to_int, write_json

# (表示名, 検索キーワード)
GENRES = [
    ('ゲーム実況', 'ゲーム実況'), ('VTuber', 'VTuber'), ('雑談', '雑談'), ('料理', '料理'),
    ('vlog', 'vlog'), ('解説', '解説'), ('歌ってみた', '歌ってみた'), ('ペット', '猫|犬'),
    ('美容', 'メイク|スキンケア'), ('旅行', '旅行'), ('やってみた', 'やってみた|検証'),
    ('レビュー', 'レビュー'), ('勉強', '勉強|資格'), ('お金', '節約|投資'), ('筋トレ', '筋トレ|ダイエット'),
]

# 知識系の横動画向け（| は OR、空白は AND）
KNOWLEDGE = [
    ('解説', '解説'), ('ゆっくり解説', 'ゆっくり解説'), ('歴史', '歴史 解説'), ('雑学', '雑学'),
    ('科学', '科学|物理|化学'), ('生き物', '生物 解説|動物 解説'), ('宇宙', '宇宙'), ('心理学', '心理学'),
    ('経済', '経済 解説'), ('お金', 'お金 知識'), ('地理', '地理|地政学'), ('医学・健康', '医師 解説|健康 知識'),
    ('本の要約', '本 要約'), ('勉強法', '勉強法'), ('語学', '英語 勉強'), ('IT・AI', 'AI 解説|プログラミング'),
]

# スローライフ建築・シミュレーション/クラフト系ゲーム
GAMES = [
    ('マイクラ建築', 'マイクラ 建築|マインクラフト 建築'), ('マイクラ', 'マイクラ|マインクラフト'),
    ('ぽこあポケモン', 'ぽこあポケモン|ぽこポケ|ポコピア|Pokopia'), ('あつ森', 'あつ森|どうぶつの森'),
    ('スローライフ', 'スローライフ ゲーム'), ('スターデューバレー', 'スターデューバレー|Stardew'),
    ('Dressmaker', 'Dressmaker|ドレスメーカー'), ('シミュレーター', 'シミュレーター 実況|Simulator 実況'),
    ('経営シミュ', '経営 シミュレーション ゲーム|お店 経営 ゲーム'), ('クラフト', 'クラフト ゲーム 実況|サバイバルクラフト'),
]

PROFILES = {
    'general': {'genres': GENRES, 'days': 7, 'pages': 2, 'durations': [None], 'min_duration': 0,
                'exclude': None, 'dir': 'small'},
    # 切り抜き・転載・コメント読み上げなど、他人の素材が中心になりやすいものは除く
    'knowledge': {'genres': KNOWLEDGE, 'days': 14, 'pages': 1, 'durations': ['medium', 'long'], 'min_duration': 240,
                  'exclude': re.compile(r'切り抜き|切抜|反応集|名場面|海外の反応|#shorts|まとめ', re.I), 'dir': 'knowledge'},
    # ゲームの横動画（チャンネル規模は問わない。登録者で絞るときは --max-subs）
    'games': {'genres': GAMES, 'days': 14, 'pages': 1, 'durations': ['medium', 'long'], 'min_duration': 240,
              'exclude': None, 'dir': 'games'},
}


def search_ids(key, q, after, pages, duration=None):
    ids, token = [], None
    for _ in range(pages):
        params = {'part': 'id', 'type': 'video', 'q': q, 'order': 'viewCount', 'maxResults': 50,
                  'publishedAfter': after, 'regionCode': 'JP', 'relevanceLanguage': 'ja'}
        if duration:
            params['videoDuration'] = duration  # medium: 4〜20分, long: 20分超
        if token:
            params['pageToken'] = token
        res = api_get('search', params, key)
        ids += [it['id']['videoId'] for it in res.get('items', []) if it.get('id', {}).get('videoId')]
        token = res.get('nextPageToken')
        if not token:
            break
    return ids


def fetch_videos(key, ids):
    out = {}
    for i in range(0, len(ids), 50):
        res = api_get('videos', {'part': 'snippet,contentDetails,statistics', 'id': ','.join(ids[i:i + 50])}, key)
        for it in res.get('items', []):
            out[it['id']] = it
    return out


def fetch_channels(key, ids):
    out = {}
    for i in range(0, len(ids), 50):
        res = api_get('channels', {'part': 'snippet,statistics', 'id': ','.join(ids[i:i + 50])}, key)
        for c in res.get('items', []):
            st = c.get('statistics', {})
            out[c['id']] = {
                'subs': None if st.get('hiddenSubscriberCount') else to_int(st.get('subscriberCount')),
                'videoCount': to_int(st.get('videoCount')),
                'createdAt': c.get('snippet', {}).get('publishedAt'),
                'desc': (c.get('snippet', {}).get('description') or '').strip()[:160],
            }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--profile', choices=PROFILES, default='general')
    ap.add_argument('--max-subs', type=int, default=5000)
    ap.add_argument('--days', type=int, help='直近何日の動画を探すか')
    ap.add_argument('--pages', type=int, help='1ジャンルあたりの検索ページ数（1ページ50件・100ユニット）')
    ap.add_argument('--data-dir')
    a = ap.parse_args()
    prof = PROFILES[a.profile]
    a.days = a.days or prof['days']
    a.pages = a.pages or prof['pages']
    a.data_dir = a.data_dir or os.path.join(os.path.dirname(__file__), '..', 'data', prof['dir'])
    key = os.environ.get('YOUTUBE_API_KEY')
    if not key:
        sys.exit('YOUTUBE_API_KEY が設定されていません')
    os.makedirs(a.data_dir, exist_ok=True)

    now = datetime.now(JST)
    after = (now - timedelta(days=a.days)).astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    genre_of = {}
    for label, q in prof['genres']:
        for duration in prof['durations']:
            for vid in search_ids(key, q, after, a.pages, duration):
                if label not in genre_of.setdefault(vid, []):
                    genre_of[vid].append(label)

    items = fetch_videos(key, list(genre_of))
    channels = fetch_channels(key, list({it['snippet']['channelId'] for it in items.values()}))

    videos = []
    for vid, it in items.items():
        sn, st, cd = it['snippet'], it.get('statistics', {}), it.get('contentDetails', {})
        ch = channels.get(sn['channelId'], {})
        subs, views = ch.get('subs'), to_int(st.get('viewCount'))
        # 自動生成のアーティストチャンネル（- Topic）と登録者非公開は除く
        if subs is None or subs > a.max_subs or views is None or sn.get('channelTitle', '').endswith(' - Topic'):
            continue
        if sn.get('liveBroadcastContent') in ('live', 'upcoming'):
            continue
        duration = parse_duration(cd.get('duration'))
        if duration < prof['min_duration']:
            continue
        if prof['exclude'] and prof['exclude'].search(sn.get('title', '') + ' ' + sn.get('channelTitle', '')):
            continue
        videos.append({
            'id': vid, 'title': sn.get('title', ''), 'channelId': sn['channelId'],
            'channelTitle': sn.get('channelTitle', ''), 'categoryId': sn.get('categoryId'),
            'publishedAt': sn.get('publishedAt'), 'duration': duration,
            'views': views, 'likes': to_int(st.get('likeCount')), 'comments': to_int(st.get('commentCount')),
            'subs': subs, 'channelVideos': ch.get('videoCount'), 'channelCreatedAt': ch.get('createdAt'),
            'channelDesc': ch.get('desc', ''),
            'tags': (sn.get('tags') or [])[:MAX_TAGS], 'genres': genre_of[vid],
        })
    videos.sort(key=lambda v: v['views'] / max(v['subs'], 1), reverse=True)

    today = now.strftime('%Y-%m-%d')
    snap = {'date': today, 'fetchedAt': now.isoformat(timespec='seconds'), 'profile': a.profile,
            'maxSubs': a.max_subs, 'days': a.days, 'minDuration': prof['min_duration'], 'searched': len(items),
            'genres': [g for g, _ in prof['genres']], 'videos': videos}
    write_json(os.path.join(a.data_dir, today + '.json'), snap)
    write_json(os.path.join(a.data_dir, 'latest.json'), snap)
    print(f'{today}: {len(items)} 本を調べ、登録者 {a.max_subs} 人以下の {len(videos)} 本を保存しました')


if __name__ == '__main__':
    main()
