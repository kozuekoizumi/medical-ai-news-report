"""
医療AI週次ニュースレポート自動送信ツール
--------------------------------------------
毎週月曜の朝7時に自動で動き、医療AIの最新ニュースを
透析室ナース向けに要約してLINEに送信します。
"""

import feedparser
import anthropic
import requests
import os
from datetime import datetime, timezone, timedelta

# ── 設定 ────────────────────────────────────────────────────────────

# 日本時間のタイムゾーン
JST = timezone(timedelta(hours=9))

# 検索キーワード（Google News RSSで検索する言葉）
SEARCH_KEYWORDS = [
    "医療 AI",
    "透析 人工知能",
    "看護師 AI",
    "診療報酬 AI",
]

# Claudeへの指示（どんな視点で要約するかを決める）
SYSTEM_PROMPT = """あなたは透析室で働く看護師向けに医療AI情報を整理するアシスタントです。
提供されたニュース記事を、以下の3カテゴリに分類して、平易な日本語で要約してください。

カテゴリ：
1. 💧 透析・腎臓領域（透析、腎臓病、除水など透析室に直結する内容）
2. 🩺 看護・病院運営（看護師の働き方、診療報酬、病院経営に関する内容）
3. 🤖 医療AI全般（上記以外の医療AI・デジタルヘルス全般）

出力形式（この形式を必ず守ること）：
⚡ 今週のポイント
（2〜3文で今週の重要なトピックをまとめる）

💧 透析・腎臓領域
・【記事タイトル】
  （2文の要約）
  🔗 URL

🩺 看護・病院運営
・【記事タイトル】
  （2文の要約）
  🔗 URL

🤖 医療AI全般
・【記事タイトル】
  （2文の要約）
  🔗 URL

注意事項：
- 各カテゴリ最大2件まで
- 専門用語はできるだけ平易な言葉に言い換える
- 透析室の現場に役立つ視点でコメントを加える
- 関連記事がなければそのカテゴリは「今週は該当記事なし」と記載する
- URLはそのまま記載する（短縮しない）"""


# ── ステップ1：ニュースを取得する ─────────────────────────────────────

def fetch_news() -> list[dict]:
    """Google News RSS から医療AI関連ニュースを取得する"""
    articles = []
    one_week_ago = datetime.now(JST) - timedelta(days=7)

    for keyword in SEARCH_KEYWORDS:
        # Google News RSSのURL（キーワード検索・日本語・日本）
        url = (
            f"https://news.google.com/rss/search"
            f"?q={requests.utils.quote(keyword)}"
            f"&hl=ja&gl=JP&ceid=JP:ja"
        )
        feed = feedparser.parse(url)

        for entry in feed.entries[:3]:
            # 1週間以内の記事のみに絞り込む
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                pub_date = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                if pub_date < one_week_ago.astimezone(timezone.utc):
                    continue

            articles.append({
                "title": entry.get("title", "タイトルなし"),
                "url": entry.get("link", ""),
                "summary": entry.get("summary", ""),
                "keyword": keyword,
            })

    # 同じURLの記事が重複して入らないように除去する
    seen_urls = set()
    unique_articles = []
    for article in articles:
        if article["url"] not in seen_urls:
            seen_urls.add(article["url"])
            unique_articles.append(article)

    print(f"  → {len(unique_articles)} 件の記事を取得しました")
    return unique_articles


# ── ステップ2：Claude APIで要約する ──────────────────────────────────

def summarize_with_claude(articles: list[dict]) -> str:
    """Claude API でニュースを透析室ナース向けに要約する"""

    # 記事が0件のときの処理
    if not articles:
        return "今週は医療AI関連の新しいニュースが見つかりませんでした。\n来週また確認します。"

    # 記事一覧をテキスト形式に変換（最大12件）
    news_text = "\n\n".join([
        f"【記事{i+1}】\nタイトル: {a['title']}\nURL: {a['url']}\n概要: {a['summary']}"
        for i, a in enumerate(articles[:12])
    ])

    # Claude APIを呼び出す
    # 公式ドキュメント: https://docs.anthropic.com/en/about-claude/models
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",  # 最も安価なモデル（週1回なら年間数十円以下）
        max_tokens=1500,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"以下のニュース記事を、透析室ナース向けに整理してください。\n\n{news_text}",
            }
        ],
    )

    return message.content[0].text


# ── ステップ3：LINEに送信する ────────────────────────────────────────

def send_line_message(summary: str) -> None:
    """LINE Messaging API (Push Message) でレポートを自分のLINEに送信する"""

    today = datetime.now(JST).strftime("%Y年%m月%d日")

    # LINEに送るメッセージを組み立てる
    message_text = (
        f"🏥 医療AI週次レポート\n"
        f"📅 {today}\n"
        f"{'─' * 18}\n\n"
        f"{summary}\n\n"
        f"{'─' * 18}\n"
        f"📝 気になった記事はスプレッドシートにメモしよう"
    )

    # LINE Messaging APIにリクエストを送る
    response = requests.post(
        url="https://api.line.me/v2/bot/message/push",
        headers={
            "Authorization": f"Bearer {os.environ['LINE_CHANNEL_ACCESS_TOKEN']}",
            "Content-Type": "application/json",
        },
        json={
            "to": os.environ["LINE_USER_ID"],
            "messages": [{"type": "text", "text": message_text}],
        },
    )

    if response.status_code == 200:
        print("  → LINE送信成功 ✅")
    else:
        print(f"  → LINE送信エラー: {response.status_code}")
        print(f"     詳細: {response.text}")
        response.raise_for_status()


# ── メイン処理 ────────────────────────────────────────────────────────

def main():
    print("=" * 40)
    print("  医療AI週次レポート 生成開始")
    print(f"  実行日時: {datetime.now(JST).strftime('%Y-%m-%d %H:%M JST')}")
    print("=" * 40)

    print("\n[1/3] Google News からニュースを取得中...")
    articles = fetch_news()

    print("\n[2/3] Claude API で透析室ナース向けに要約中...")
    summary = summarize_with_claude(articles)

    print("\n[3/3] LINE に送信中...")
    send_line_message(summary)

    print("\n" + "=" * 40)
    print("  完了！LINEを確認してください 🏥")
    print("=" * 40)


if __name__ == "__main__":
    main()
