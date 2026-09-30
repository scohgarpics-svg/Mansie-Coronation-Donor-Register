import os, io, csv, json, sqlite3, urllib.request
from datetime import datetime
from functools import wraps
from flask import Flask, request, redirect, session, render_template_string, Response, abort

# ---------- Settings: edit these ----------
ORG = "Mansie Divisional Council"
EVENT = "Yam Festival & Coronation of Nana Gyintadua Kwame Siakwan III (Mansiehene/Akwamuhene of Mo Traditional Council)"
EVENT_DATE = "4th October 2026"
PREFIX = "MDC-YF26"                      # receipts: MDC-YF26-0001, 0002, ...
CURRENCY = "GH₵"
LEVELS = [("Platinum", 5000), ("Gold", 1000), ("Silver", 500), ("Bronze", 100), ("Supporter", 0)]  # min amount
CATEGORIES = ["Individual", "Chief / Elder", "Family", "Association / Group", "Organisation", "Diaspora"]
MODES = ["Cash", "Mobile Money", "Bank Transfer", "Cheque"]
STATUSES = ["Paid", "Pledged"]
COLLECTORS = ["Collector 1", "Collector 2", "Collector 3"]
# Environment variables: ADMIN_PASSWORD, SECRET_KEY, ARKESEL_API_KEY, SMS_SENDER, DB_PATH
# ------------------------------------------

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-me")
DB = os.environ.get("DB_PATH", "donations.db")


def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


with db() as _c:
    _c.execute("""CREATE TABLE IF NOT EXISTS donations(
        id INTEGER PRIMARY KEY AUTOINCREMENT, receipt_no TEXT, name TEXT, phone TEXT,
        category TEXT, level TEXT, amount REAL, mode TEXT, status TEXT, collector TEXT,
        created_at TEXT, sms_status TEXT)""")


def level_for(a):
    for n, m in LEVELS:
        if a >= m:
            return n


def norm(p):
    p = "".join(ch for ch in p if ch.isdigit())
    return "233" + p[1:] if p.startswith("0") else p


def send_sms(phone, msg):
    key = os.environ.get("ARKESEL_API_KEY")
    if not phone:
        return "No phone"
    if not key:
        return "Not configured"
    try:
        req = urllib.request.Request(
            "https://sms.arkesel.com/api/v2/sms/send",
            data=json.dumps({"sender": os.environ.get("SMS_SENDER", "MansieDC"),
                             "message": msg, "recipients": [phone]}).encode(),
            headers={"api-key": key, "Content-Type": "application/json"})
        r = json.load(urllib.request.urlopen(req, timeout=10))
        return "Sent" if r.get("status") == "success" else "Failed"
    except Exception:
        return "Failed"


def notify(i):
    r = db().execute("SELECT * FROM donations WHERE id=?", (i,)).fetchone()
    word = "donation" if r["status"] == "Paid" else "pledge"
    msg = (f"Dear {r['name']}, {ORG} acknowledges your {word} of GHS {r['amount']:,.2f} "
           f"({r['mode']}) for the Yam Festival & Coronation, {EVENT_DATE}. "
           f"Receipt: {r['receipt_no']}. Thank you.")
    s = send_sms(r["phone"], msg)
    with db() as c:
        c.execute("UPDATE donations SET sms_status=? WHERE id=?", (s, i))


def auth(f):
    @wraps(f)
    def w(*a, **k):
        if not session.get("ok"):
            return redirect("/login")
        return f(*a, **k)
    return w


CSS = """body{font:15px system-ui,sans-serif;margin:0;color:#1d2a20}
header{background:#1f4d2b;color:#fff;padding:12px 16px;border-bottom:4px solid #c8952e}
header b{display:block;font-size:17px}main{max-width:1100px;margin:auto;padding:12px 16px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:8px}
input,select,button{font:inherit;padding:8px;border:1px solid #b9c2b5;border-radius:4px}
button{background:#1f4d2b;color:#fff;border:0;cursor:pointer}
table{border-collapse:collapse;width:100%}td,th{padding:6px 8px;border-bottom:1px solid #dde3d9;text-align:left}
.sc{overflow-x:auto}.rc{max-width:560px;margin:auto;border:2px solid #1f4d2b;padding:20px}
@media print{header,.np{display:none}}"""

LAYOUT = """<!doctype html><meta name=viewport content="width=device-width,initial-scale=1">
<title>{{org}}</title><style>{{css}}</style>
<header><b>{{org}}</b>{{event}} · {{date}}</header><main>{{body|safe}}</main>"""


def page(body, **ctx):
    inner = render_template_string(body, cur=CURRENCY, **ctx)
    return render_template_string(LAYOUT, body=inner, css=CSS, org=ORG, event="Yam Festival & Coronation", date=EVENT_DATE)


INDEX = """
<h2>Record a donation</h2>
<form method=post action=/add class=grid>
<input name=name placeholder="Donor name" required>
<input name=phone placeholder="Phone e.g. 0244123456" inputmode=tel required>
<select name=category>{% for x in cats %}<option>{{x}}</option>{% endfor %}</select>
<input name=amount type=number step=0.01 min=0.01 placeholder="Amount ({{cur}})" required>
<select name=mode>{% for x in modes %}<option>{{x}}</option>{% endfor %}</select>
<select name=status>{% for x in stats %}<option>{{x}}</option>{% endfor %}</select>
<input name=collector list=col placeholder="Collector" required>
<datalist id=col>{% for x in collectors %}<option>{{x}}</option>{% endfor %}</datalist>
<button>Save and send SMS</button></form>
<h2>Summary</h2>
<p>{% for t in tot %}<b>{{t.status}}:</b> {{cur}}{{"{:,.2f}".format(t.s)}} ({{t.n}} donors) &nbsp; {% endfor %}</p>
<div class=grid>{% for title,g in groups %}<div><h3>{{title}} (paid)</h3><table>
{% for r in g %}<tr><td>{{r.k}}</td><td>{{r.n}}</td><td>{{cur}}{{"{:,.2f}".format(r.s)}}</td></tr>{% endfor %}</table></div>{% endfor %}</div>
<h2>Donations</h2>
<form class=np><input name=q value="{{q}}" placeholder="Search name, phone, receipt, collector"> <button>Search</button>
<a href=/export.csv>Export CSV</a> · <a href=/logout>Log out</a></form>
<div class=sc><table><tr><th>Receipt<th>Time<th>Name<th>Phone<th>Category<th>Level<th>Amount<th>Mode<th>Status<th>Collector<th>SMS<th></tr>
{% for r in rows %}<tr><td>{{r.receipt_no}}<td>{{r.created_at}}<td>{{r.name}}<td>{{r.phone}}<td>{{r.category}}<td>{{r.level}}
<td>{{cur}}{{"{:,.2f}".format(r.amount)}}<td>{{r.mode}}<td>{{r.status}}<td>{{r.collector}}<td>{{r.sms_status}}
<td><a href=/receipt/{{r.id}}>Receipt</a>
<form method=post action=/resend/{{r.id}} style=display:inline><button>Resend SMS</button></form></tr>{% endfor %}</table></div>"""

RECEIPT = """<div class=rc><h2>{{org}}</h2><p>{{event}}<br>{{date}}</p>
<h3>Official receipt {{r.receipt_no}}</h3><table>
<tr><td>Received from<td>{{r.name}}<tr><td>Phone<td>{{r.phone}}<tr><td>Donor category<td>{{r.category}}
<tr><td>Donor level<td>{{r.level}}<tr><td>Amount<td>{{cur}}{{"{:,.2f}".format(r.amount)}}
<tr><td>Mode of payment<td>{{r.mode}}<tr><td>Status<td>{{r.status}}<tr><td>Collected by<td>{{r.collector}}
<tr><td>Date and time<td>{{r.created_at}}</table><p>Thank you for your support.</p></div>
<p class=np><button onclick="window.print()">Print</button> <a href=/>Back</a></p>"""


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST" and request.form.get("p") == os.environ.get("ADMIN_PASSWORD", "changeme"):
        session["ok"] = True
        return redirect("/")
    return page("<h2>Log in</h2><form method=post><input type=password name=p placeholder=Password autofocus> <button>Log in</button></form>")


@app.get("/logout")
def logout():
    session.clear()
    return redirect("/login")


@app.get("/")
@auth
def index():
    q = request.args.get("q", "").strip()
    c = db()
    rows = c.execute("SELECT * FROM donations WHERE name LIKE ? OR phone LIKE ? OR receipt_no LIKE ? OR collector LIKE ? ORDER BY id DESC", [f"%{q}%"] * 4).fetchall()
    tot = c.execute("SELECT status, COALESCE(SUM(amount),0) s, COUNT(*) n FROM donations GROUP BY status").fetchall()

    def by(col):
        return c.execute(f"SELECT {col} k, COUNT(*) n, SUM(amount) s FROM donations WHERE status='Paid' GROUP BY {col} ORDER BY s DESC").fetchall()

    groups = [(t, by(col)) for t, col in [("Level", "level"), ("Payment mode", "mode"), ("Collector", "collector"), ("Donor category", "category")]]
    return page(INDEX, rows=rows, q=q, tot=tot, groups=groups, cats=CATEGORIES, modes=MODES, stats=STATUSES, collectors=COLLECTORS)


@app.post("/add")
@auth
def add():
    f = request.form
    try:
        amt = float(f["amount"])
    except (KeyError, ValueError):
        abort(400)
    if amt <= 0:
        abort(400)
    with db() as c:
        i = c.execute("INSERT INTO donations(name,phone,category,level,amount,mode,status,collector,created_at,sms_status) VALUES(?,?,?,?,?,?,?,?,?,?)",
                      (f["name"].strip(), norm(f["phone"]), f["category"], level_for(amt), amt, f["mode"], f["status"],
                       f["collector"].strip(), datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "Pending")).lastrowid
        c.execute("UPDATE donations SET receipt_no=? WHERE id=?", (f"{PREFIX}-{i:04d}", i))
    notify(i)
    return redirect(f"/receipt/{i}")


@app.post("/resend/<int:i>")
@auth
def resend(i):
    notify(i)
    return redirect("/")


@app.get("/receipt/<int:i>")
@auth
def receipt(i):
    r = db().execute("SELECT * FROM donations WHERE id=?", (i,)).fetchone() or abort(404)
    return page(RECEIPT, r=r, org=ORG, event=EVENT, date=EVENT_DATE)


@app.get("/export.csv")
@auth
def export():
    rows = db().execute("SELECT receipt_no,created_at,name,phone,category,level,amount,mode,status,collector,sms_status FROM donations ORDER BY id").fetchall()
    o = io.StringIO()
    w = csv.writer(o)
    w.writerow(["Receipt", "Time", "Name", "Phone", "Category", "Level", "Amount", "Mode", "Status", "Collector", "SMS"])
    w.writerows([list(r) for r in rows])
    return Response(o.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=donations.csv"})


if __name__ == "__main__":
    app.run(debug=True)
