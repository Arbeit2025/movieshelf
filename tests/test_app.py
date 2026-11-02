import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["MOVIESHELF_DB"] = _tmp.name

import app as app_module  # noqa: E402


class MovieShelfTest(unittest.TestCase):
    def setUp(self):
        app_module.init_db()
        self.client = app_module.app.test_client()
        with app_module.app.app_context():
            conn = app_module.get_db()
            conn.execute("DELETE FROM movies")
            conn.commit()

    def add(self, **data):
        form = {"title": "サンプル映画", "status": "観たい", "rating": "", "year": "", "memo": ""}
        form.update(data)
        return self.client.post("/movies", data=form)

    def movies(self):
        with app_module.app.app_context():
            conn = app_module.get_db()
            return conn.execute("SELECT * FROM movies ORDER BY id").fetchall()

    def test_healthz(self):
        res = self.client.get("/healthz")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["status"], "ok")

    def test_index_empty(self):
        body = self.client.get("/").get_data(as_text=True)
        self.assertIn("おうち映画棚", body)
        self.assertIn("この棚はまだ空です", body)

    def test_add_movie_minimal(self):
        self.add(title="となりのトトロ", status="観た")
        rows = self.movies()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "となりのトトロ")
        self.assertEqual(rows[0]["status"], "観た")
        self.assertIsNone(rows[0]["rating"])
        self.assertIsNone(rows[0]["year"])

    def test_add_movie_full(self):
        self.add(title="バック・トゥ・ザ・フューチャー", status="観た", rating="5", year="1985", memo="何度見ても面白い")
        rows = self.movies()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["rating"], 5)
        self.assertEqual(rows[0]["year"], 1985)
        self.assertEqual(rows[0]["memo"], "何度見ても面白い")
        body = self.client.get("/").get_data(as_text=True)
        self.assertIn("バック・トゥ・ザ・フューチャー", body)
        self.assertIn("★★★★★", body)
        self.assertIn("1985年", body)

    def test_add_requires_title(self):
        self.add(title="  ")
        self.assertEqual(len(self.movies()), 0)

    def test_rating_out_of_range_rejected(self):
        self.add(title="評価ゼロ", rating="0")
        self.add(title="評価六", rating="6")
        self.add(title="評価文字", rating="abc")
        self.assertEqual(len(self.movies()), 0)

    def test_rating_boundaries_accepted(self):
        self.add(title="評価一", rating="1")
        self.add(title="評価五", rating="5")
        rows = self.movies()
        self.assertEqual([r["rating"] for r in rows], [1, 5])

    def test_parse_rating(self):
        self.assertEqual(app_module.parse_rating(""), (None, True))
        self.assertEqual(app_module.parse_rating(None), (None, True))
        self.assertEqual(app_module.parse_rating("3"), (3, True))
        self.assertEqual(app_module.parse_rating("0"), (None, False))
        self.assertEqual(app_module.parse_rating("6"), (None, False))
        self.assertEqual(app_module.parse_rating("x"), (None, False))

    def test_parse_year(self):
        self.assertIsNone(app_module.parse_year(""))
        self.assertIsNone(app_module.parse_year("abc"))
        self.assertEqual(app_module.parse_year("1999"), 1999)

    def test_invalid_status_defaults_to_want(self):
        self.add(title="状態不正", status="不明")
        rows = self.movies()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "観たい")

    def test_filter_by_status(self):
        self.add(title="ウィッシュリスト作品", status="観たい")
        self.add(title="鑑賞済み作品", status="観た")
        body_all = self.client.get("/").get_data(as_text=True)
        self.assertIn("ウィッシュリスト作品", body_all)
        self.assertIn("鑑賞済み作品", body_all)
        body_want = self.client.get("/?status=観たい").get_data(as_text=True)
        self.assertIn("ウィッシュリスト作品", body_want)
        self.assertNotIn("鑑賞済み作品", body_want)
        body_watched = self.client.get("/?status=観た").get_data(as_text=True)
        self.assertIn("鑑賞済み作品", body_watched)
        self.assertNotIn("ウィッシュリスト作品", body_watched)

    def test_filter_invalid_value_shows_all(self):
        self.add(title="鑑賞済み作品", status="観た")
        body = self.client.get("/?status=存在しない").get_data(as_text=True)
        self.assertIn("鑑賞済み作品", body)

    def test_delete_movie(self):
        self.add(title="消す映画")
        mid = self.movies()[0]["id"]
        self.client.post(f"/movies/{mid}/delete")
        self.assertEqual(len(self.movies()), 0)
        body = self.client.get("/").get_data(as_text=True)
        self.assertNotIn("消す映画", body)

    def test_escaping(self):
        self.add(title="<script>alert(1)</script>", memo="<b>太字</b>")
        body = self.client.get("/").get_data(as_text=True)
        self.assertNotIn("<script>alert(1)</script>", body)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", body)
        self.assertNotIn("<b>太字</b>", body)
        self.assertIn("&lt;b&gt;太字&lt;/b&gt;", body)

    def test_stars_label(self):
        self.assertEqual(app_module.stars_label(None), "未評価")
        self.assertEqual(app_module.stars_label(3), "★★★☆☆")


if __name__ == "__main__":
    unittest.main()
