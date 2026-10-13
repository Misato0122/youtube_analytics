#!/usr/bin/env python3
"""登録者が少ないのに再生が伸びている動画を、ジャンル別のキーワード検索から集める。

急上昇（mostPopular）には大きなチャンネルしか載らないため、
直近 N 日に公開された動画を再生数順に検索し、登録者数で絞り込む。

使い方:
  YOUTUBE_API_KEY=xxxx python3 scripts/collect_small.py [--max-subs 5000] [--days 7]

出力: data/small/YYYY-MM-DD.json と data/small/latest.json
API 使用量: 検索 1 回 100 ユニット × ジャンル数 × ページ数（初期設定で約 3,000）
"""
import argparse, json, os, sys
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


def search_ids(key, q, after, pages):
    ids, token = [], None
    for _ in range(pages):
        params = {'part': 'id', 'type': 'video', 'q': q, 'order': 'viewCount', 'maxResults': 50,
                  'publishedAfter': after, 'regionCode': 'JP', 'relevanceLanguage': 'ja'}
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
            }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--max-subs', type=int, default=5000)
    ap.add_argument('--days', type=int, default=7)
    ap.add_argument('--pages', type=int, default=2, help='1ジャンルあたりの検索ページ数（1ページ50件・100ユニット）')
    ap.add_argument('--data-dir', default=os.path.join(os.path.dirname(__file__), '..', 'data', 'small'))
    a = ap.parse_args()
    key = os.environ.get('YOUTUBE_API_KEY')
    if not key:
        sys.exit('YOUTUBE_API_KEY が設定されていません')
    os.makedirs(a.data_dir, exist_ok=True)

    now = datetime.now(JST)
    after = (now - timedelta(days=a.days)).astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    genre_of = {}
    for label, q in GENRES:
        for vid in search_ids(key, q, after, a.pages):
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
        videos.append({
            'id': vid, 'title': sn.get('title', ''), 'channelId': sn['channelId'],
            'channelTitle': sn.get('channelTitle', ''), 'categoryId': sn.get('categoryId'),
            'publishedAt': sn.get('publishedAt'), 'duration': parse_duration(cd.get('duration')),
            'views': views, 'likes': to_int(st.get('likeCount')), 'comments': to_int(st.get('commentCount')),
            'subs': subs, 'channelVideos': ch.get('videoCount'), 'channelCreatedAt': ch.get('createdAt'),
            'tags': (sn.get('tags') or [])[:MAX_TAGS], 'genres': genre_of[vid],
        })
    videos.sort(key=lambda v: v['views'] / max(v['subs'], 1), reverse=True)

    today = now.strftime('%Y-%m-%d')
    snap = {'date': today, 'fetchedAt': now.isoformat(timespec='seconds'), 'maxSubs': a.max_subs,
            'days': a.days, 'searched': len(items), 'genres': [g for g, _ in GENRES], 'videos': videos}
    write_json(os.path.join(a.data_dir, today + '.json'), snap)
    write_json(os.path.join(a.data_dir, 'latest.json'), snap)
    print(f'{today}: {len(items)} 本を調べ、登録者 {a.max_subs} 人以下の {len(videos)} 本を保存しました')


if __name__ == '__main__':
    main()
