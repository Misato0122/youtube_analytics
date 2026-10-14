#!/usr/bin/env python3
"""YouTube の急上昇（mostPopular）を取得して data/ に保存する。

使い方:
  YOUTUBE_API_KEY=xxxx python3 scripts/collect.py [--region JP] [--data-dir data]

出力:
  data/YYYY-MM-DD.json  その日のスナップショット（同じ日に再実行すると上書き）
  data/latest.json      最新のスナップショット
  data/index.json       日付の一覧と日ごとの集計（推移グラフ用）
"""
import argparse, json, os, re, sys, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone

API = 'https://www.googleapis.com/youtube/v3/'
JST = timezone(timedelta(hours=9))
MAX_TAGS = 15


def api_get(endpoint, params, key, retries=3):
    q = urllib.parse.urlencode({**params, 'key': key})
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(f'{API}{endpoint}?{q}', timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            body = e.read().decode('utf-8', 'replace')
            # 1日の上限超過はやり直しても無駄なので、わかりやすいメッセージで止める
            if 'quota' in body.lower():
                sys.exit(f'YouTube API の1日の上限を超えました（{e.code}）。日本時間16〜17時ごろにリセットされます')
            # 一時的な混雑（429）やサーバーエラーは少し待ってやり直す
            if (e.code == 429 or e.code >= 500) and attempt < retries:
                time.sleep(10 * 2 ** attempt)
                continue
            sys.exit(f'YouTube API エラー {e.code}: {body[:300]}')


def parse_duration(s):
    """ISO 8601 の期間（PT1H2M3S, P1DT2H など）を秒にする。"""
    m = re.fullmatch(r'P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?', s or '')
    if not m:
        return 0
    d, h, mi, se = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + se


def to_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def fetch_trending(key, region):
    items, token = [], None
    while len(items) < 200:
        params = {'part': 'snippet,contentDetails,statistics', 'chart': 'mostPopular',
                  'regionCode': region, 'maxResults': 50, 'hl': 'ja'}
        if token:
            params['pageToken'] = token
        res = api_get('videos', params, key)
        items += res.get('items', [])
        token = res.get('nextPageToken')
        if not token:
            break
    return items


def fetch_categories(key, region):
    res = api_get('videoCategories', {'part': 'snippet', 'regionCode': region, 'hl': 'ja'}, key)
    return {c['id']: c['snippet']['title'] for c in res.get('items', [])}


def fetch_subscribers(key, channel_ids):
    subs, ids = {}, list(dict.fromkeys(channel_ids))
    for i in range(0, len(ids), 50):
        res = api_get('channels', {'part': 'statistics', 'id': ','.join(ids[i:i + 50])}, key)
        for c in res.get('items', []):
            st = c.get('statistics', {})
            subs[c['id']] = None if st.get('hiddenSubscriberCount') else to_int(st.get('subscriberCount'))
    return subs


def build_videos(items, subs):
    videos = []
    for rank, it in enumerate(items, 1):
        sn, st, cd = it['snippet'], it.get('statistics', {}), it.get('contentDetails', {})
        videos.append({
            'id': it['id'], 'rank': rank, 'title': sn.get('title', ''),
            'channelId': sn.get('channelId'), 'channelTitle': sn.get('channelTitle', ''),
            'categoryId': sn.get('categoryId'), 'publishedAt': sn.get('publishedAt'),
            'duration': parse_duration(cd.get('duration')),
            'views': to_int(st.get('viewCount')), 'likes': to_int(st.get('likeCount')),
            'comments': to_int(st.get('commentCount')),
            'subs': subs.get(sn.get('channelId')),
            'tags': (sn.get('tags') or [])[:MAX_TAGS],
        })
    return videos


def add_history(videos, prev):
    """前回のスナップショットと比べて、前回順位・連続ランクイン日数・再生数の増加を付ける。"""
    prev_by_id = {v['id']: v for v in (prev or {}).get('videos', [])}
    for v in videos:
        p = prev_by_id.get(v['id'])
        v['prevRank'] = p['rank'] if p else None
        v['days'] = (p.get('days', 1) + 1) if p else 1
        v['viewsDelta'] = (v['views'] - p['views']) if p and v['views'] is not None and p.get('views') is not None else None


def summarize(snap):
    vs = snap['videos']
    cats = {}
    for v in vs:
        cats[v['categoryId']] = cats.get(v['categoryId'], 0) + 1
    views = sorted(v['views'] for v in vs if v['views'] is not None)
    durs = sorted(v['duration'] for v in vs)
    med = lambda a: a[len(a) // 2] if a else None
    return {
        'date': snap['date'], 'fetchedAt': snap['fetchedAt'], 'count': len(vs),
        'medianViews': med(views), 'medianDuration': med(durs),
        'shorts': sum(1 for d in durs if 0 < d <= 180),
        'newEntries': sum(1 for v in vs if v.get('prevRank') is None),
        'categories': cats,
    }


def load_json(path, default=None):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path, obj):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, separators=(',', ':'))
        f.write('\n')


def previous_snapshot(data_dir, today):
    dates = sorted(f[:-5] for f in os.listdir(data_dir) if re.fullmatch(r'\d{4}-\d{2}-\d{2}\.json', f))
    older = [d for d in dates if d < today]
    return load_json(os.path.join(data_dir, older[-1] + '.json')) if older else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--region', default='JP')
    ap.add_argument('--data-dir', default=os.path.join(os.path.dirname(__file__), '..', 'data'))
    a = ap.parse_args()
    key = os.environ.get('YOUTUBE_API_KEY')
    if not key:
        sys.exit('YOUTUBE_API_KEY が設定されていません')
    os.makedirs(a.data_dir, exist_ok=True)

    now = datetime.now(JST)
    today = now.strftime('%Y-%m-%d')
    items = fetch_trending(key, a.region)
    if not items:
        sys.exit('急上昇データが取得できませんでした')
    categories = fetch_categories(key, a.region)
    subs = fetch_subscribers(key, [it['snippet']['channelId'] for it in items])
    videos = build_videos(items, subs)
    add_history(videos, previous_snapshot(a.data_dir, today))

    snap = {'date': today, 'fetchedAt': now.isoformat(timespec='seconds'), 'region': a.region,
            'categories': categories, 'videos': videos}
    write_json(os.path.join(a.data_dir, today + '.json'), snap)
    write_json(os.path.join(a.data_dir, 'latest.json'), snap)

    index_path = os.path.join(a.data_dir, 'index.json')
    index = load_json(index_path, {'days': []})
    index['days'] = [d for d in index['days'] if d['date'] != today] + [summarize(snap)]
    index['days'].sort(key=lambda d: d['date'])
    index['categories'] = {**index.get('categories', {}), **categories}
    write_json(index_path, index)
    print(f'{today}: {len(videos)} 件を保存しました')


if __name__ == '__main__':
    main()
