"""おうち映画棚 movieshelf

観た映画・観たい映画を「棚」に並べて眺める視聴メモ。
映画をタイトル・状態（観たい／観た）・評価（1〜5）・公開年・メモつきで
登録し、棚のようなグリッド（カード）表示で一覧する。状態での絞り込み、
登録・削除ができる。外部 API は使わず、データは SQLite に保存する。
単一ファイル Flask + SQLite。
"""
import os
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from flask import Flask, g, jsonify, redirect, render_template_string, request, url_for

app = Flask(__name__)
JST = ZoneInfo("Asia/Tokyo")
DB_PATH = os.environ.get("MOVIESHELF_DB", os.path.join(os.path.dirname(__file__), "movieshelf.db"))

STATUSES = ["観たい", "観た"]
FILTERS = ["全部"] + STATUSES


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS movies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT '観たい',
            rating INTEGER,
            year INTEGER,
            memo TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );
        """
    )
    db.commit()
    db.close()


def now_str():
    return datetime.now(JST).strftime("%Y-%m-%d %H:%M")


def parse_rating(value):
    """評価のパース。空欄は None（未評価）。1〜5 の整数以外は不正として扱う。

    戻り値は (rating, ok)。ok が False のときは登録自体を受け付けない。
    """
    if value is None or str(value).strip() == "":
        return None, True
    try:
        rating = int(str(value).strip())
    except (TypeError, ValueError):
        return None, False
    if not 1 <= rating <= 5:
        return None, False
    return rating, True


def parse_year(value):
    """公開年のパース。空欄・数値でないものは None（未登録）。"""
    if value is None or str(value).strip() == "":
        return None
    try:
        year = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    if not 1800 <= year <= 2200:
        return None
    return year


def stars_label(rating):
    if rating is None:
        return "未評価"
    return "★" * rating + "☆" * (5 - rating)


INDEX = """<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>おうち映画棚</title>
<style>body{font-family:sans-serif;max-width:860px;margin:2em auto;padding:0 1em}
.shelf{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:1em;margin-top:1em}
.card{border:1px solid #b08d57;border-bottom:8px solid #8b6f47;border-radius:6px;padding:.8em;background:#fdf8f0}
.card h3{margin:.2em 0 .4em;font-size:1.05em}
.badge{display:inline-block;padding:.05em .5em;border-radius:1em;font-size:.8em;color:#fff}
.want{background:#5b8def}.watched{background:#4caf7d}
.stars{color:#e6a817;letter-spacing:.1em}
.memo{white-space:pre-wrap;color:#444;font-size:.9em}
.meta{color:#666;font-size:.85em}
.filters a{margin-right:.6em}
.filters a.current{font-weight:bold;text-decoration:none;color:#000}
input[type=number]{width:6em}textarea{width:100%}
.note{background:#f4f4f4;padding:.8em;border-radius:6px;font-size:.9em}</style>
</head><body>
<h1>🎬 おうち映画棚</h1>
<p>観た映画・観たい映画を棚に並べて眺める視聴メモです。</p>
<p class="note">データはこのアプリ内の SQLite に保存されます。無料プランでは再デプロイ等でデータが消える場合があります。</p>

<h2>映画を登録</h2>
<form method="post" action="{{ url_for('add_movie') }}">
  <label>タイトル <input type="text" name="title" required size="40"></label><br>
  <label>状態
    <select name="status">{% for s in statuses %}<option>{{ s }}</option>{% endfor %}</select></label>
  <label>評価
    <select name="rating">
      <option value="">未評価</option>
      {% for r in range(1, 6) %}<option value="{{ r }}">{{ r }}</option>{% endfor %}
    </select></label>
  <label>公開年 <input type="number" name="year" min="1800" max="2200" placeholder="任意"></label><br>
  <label>メモ<br><textarea name="memo" rows="2" placeholder="任意"></textarea></label><br>
  <button type="submit">棚に並べる</button>
</form>

<h2>棚（{{ movies|length }}件）</h2>
<p class="filters">絞り込み：
{% for f in filters %}
{% if f == current_filter %}<a class="current" href="{{ url_for('index', status=f) }}">{{ f }}</a>{% else %}<a href="{{ url_for('index', status=f) }}">{{ f }}</a>{% endif %}
{% endfor %}
</p>
<div class="shelf">
{% for m in movies %}
<div class="card">
  <span class="badge {% if m.status == '観たい' %}want{% else %}watched{% endif %}">{{ m.status }}</span>
  <h3>{{ m.title }}</h3>
  <div class="stars">{{ m.stars }}</div>
  <p class="meta">{% if m.year %}{{ m.year }}年{% else %}公開年未登録{% endif %}／登録：{{ m.created_at }}</p>
  {% if m.memo %}<p class="memo">{{ m.memo }}</p>{% endif %}
  <form method="post" action="{{ url_for('delete_movie', mid=m.id) }}" onsubmit="return confirm('この映画を棚から外しますか？')"><button>削除</button></form>
</div>
{% else %}
<p>この棚はまだ空です</p>
{% endfor %}
</div>
</body></html>"""


@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok"})


@app.route("/")
def index():
    status_filter = request.args.get("status", "全部")
    if status_filter not in FILTERS:
        status_filter = "全部"
    db = get_db()
    if status_filter == "全部":
        rows = db.execute("SELECT * FROM movies ORDER BY id DESC").fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM movies WHERE status = ? ORDER BY id DESC", (status_filter,)
        ).fetchall()
    movies = []
    for row in rows:
        item = dict(row)
        item["stars"] = stars_label(row["rating"])
        movies.append(item)
    return render_template_string(
        INDEX, movies=movies, statuses=STATUSES, filters=FILTERS, current_filter=status_filter
    )


@app.route("/movies", methods=["POST"])
def add_movie():
    title = (request.form.get("title") or "").strip()
    status = request.form.get("status", "観たい")
    if status not in STATUSES:
        status = "観たい"
    rating, ok = parse_rating(request.form.get("rating"))
    if title and ok:
        db = get_db()
        db.execute(
            "INSERT INTO movies(title, status, rating, year, memo, created_at) VALUES(?, ?, ?, ?, ?, ?)",
            (title, status, rating, parse_year(request.form.get("year")),
             (request.form.get("memo") or "").strip(), now_str()),
        )
        db.commit()
    return redirect(url_for("index"))


@app.route("/movies/<int:mid>/delete", methods=["POST"])
def delete_movie(mid):
    db = get_db()
    db.execute("DELETE FROM movies WHERE id = ?", (mid,))
    db.commit()
    return redirect(url_for("index"))


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))
