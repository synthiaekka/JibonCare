import os
import secrets
import json
from flask import Flask, render_template, request, redirect, session, flash, url_for
from pymongo import MongoClient
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from flask_mail import Mail, Message
from requests_oauthlib import OAuth2Session
from datetime import datetime
from bson import ObjectId
from dotenv import load_dotenv
load_dotenv()

from seller import init_seller_routes
from customer import init_customer_routes
from delivery import init_delivery_routes

      # import your delivery initializer

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY") or 'SUPER_SECRET_KEY'

# MongoDB setup
MONGO_URI = os.getenv("MONGO_URI") or "mongodb+srv://Synthia:3sx1zTjPh9HWcwnn@haatexpress.rgonj6q.mongodb.net/?retryWrites=true&w=majority&appName=haatexpress"
client = MongoClient(MONGO_URI)
db = client["haatExpress"]
users = db["users"]
sellers = db["sellers"]
items = db["items"]
notices = db["notices"]
earnings = db["earnings"]
orders = db["orders"]

# Mail config
app.config['MAIL_SERVER'] = os.getenv("MAIL_SERVER", "smtp.gmail.com")
app.config['MAIL_PORT'] = int(os.getenv("MAIL_PORT", "587"))
app.config['MAIL_USE_TLS'] = os.getenv("MAIL_USE_TLS", "True") == 'True'
app.config['MAIL_USERNAME'] = os.getenv("MAIL_USERNAME", "rchoudhury0522@gmail.com")
app.config['MAIL_PASSWORD'] = os.getenv("MAIL_PASSWORD")
app.config['MAIL_DEFAULT_SENDER'] = app.config['MAIL_USERNAME']
ADMIN_EMAIL = app.config['MAIL_USERNAME']
app.config['ADMIN_EMAIL'] = ADMIN_EMAIL
mail = Mail(app)

# Upload folder
UPLOAD_FOLDER = 'static/uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# GOOGLE OAUTH2
with open("client_secret.json") as f:
    google_creds = json.load(f)["web"]

GOOGLE_CLIENT_ID = google_creds["client_id"]
GOOGLE_CLIENT_SECRET = google_creds["client_secret"]
GOOGLE_AUTHORIZATION_BASE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USER_INFO_URL = "https://www.googleapis.com/oauth2/v1/userinfo"


@app.route('/')
def home():
    return render_template("index.html")

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        if users.find_one({"email": email}):
            return "Email already registered!"
        otp = str(secrets.randbelow(1000000)).zfill(6)
        session['temp_user'] = {
            "full_name": request.form['full_name'],
            "phone": request.form['phone'],
            "email": email,
            "password": generate_password_hash(request.form['password']),
            "role": request.form['role'],
            "otp": otp
        }
        msg = Message("Your HaatExpress OTP Verification Code",
                      recipients=[email])
        msg.body = f"Your OTP is: {otp}"
        try:
            mail.send(msg)
        except Exception as e:
            return f"Email sending failed: {e}"
        return redirect('/verify-otp')
    return render_template("register.html")

@app.route('/verify-otp', methods=['GET', 'POST'])
def verify_otp():
    if 'temp_user' not in session:
        return redirect('/register')
    if request.method == 'POST':
        entered_otp = request.form['otp']
        actual_otp = session['temp_user']['otp']
        if entered_otp == actual_otp:
            user_data = session.pop('temp_user')
            users.insert_one({
                "full_name": user_data['full_name'],
                "phone": user_data['phone'],
                "email": user_data['email'],
                "password": user_data['password'],
                "role": user_data['role']
            })
            return redirect('/login')
        else:
            return render_template('otp_verify.html', error="Invalid OTP. Please try again.")
    return render_template('otp_verify.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user = users.find_one({"email": email})
        if user and check_password_hash(user['password'], password):
            session['user'] = user['email']
            session['role'] = user['role']
            # Route based on role
            if user['role'] == 'admin':
                return redirect('/admin-dashboard')
            elif user['role'] == 'seller':
                return redirect('/seller/dashboard')
            elif user['role'] == 'customer':
                return redirect('/customer-dashboard')
            elif user['role'] == 'delivery':
                return redirect('/delivery-dashboard')
            else:
                return "Unknown role"
        return render_template("login.html", error="Invalid credentials.")
    return render_template("login.html")

# ---- GOOGLE LOGIN ----
@app.route('/google-login')
def google_login():
    google = OAuth2Session(
        GOOGLE_CLIENT_ID,
        redirect_uri=url_for('google_callback', _external=True),
        scope=['openid', 'email', 'profile']
    )
    authorization_url, state = google.authorization_url(
        GOOGLE_AUTHORIZATION_BASE_URL,
        access_type="offline",
        prompt="select_account"
    )
    session['oauth_state'] = state
    return redirect(authorization_url)

@app.route('/login/callback')
def google_callback():
    google = OAuth2Session(
        GOOGLE_CLIENT_ID,
        redirect_uri=url_for('google_callback', _external=True),
        state=session.get('oauth_state')
    )
    token = google.fetch_token(
        GOOGLE_TOKEN_URL,
        client_secret=GOOGLE_CLIENT_SECRET,
        authorization_response=request.url
    )
    userinfo = google.get(GOOGLE_USER_INFO_URL).json()
    email = userinfo.get("email")
    name = userinfo.get("name", "")
    user = users.find_one({"email": email})
    if not user:
        users.insert_one({
            "full_name": name,
            "email": email,
            "role": "customer",
            "password": "",
        })
        user = users.find_one({"email": email})

    session['user'] = email
    session['role'] = user['role']
    if user['role'] == 'admin':
        return redirect('/admin-dashboard')
    elif user['role'] == 'seller':
        return redirect('/seller/dashboard')
    elif user['role'] == 'customer':
        return redirect('/customer-dashboard')
    elif user['role'] == 'delivery':
        return redirect('/delivery-dashboard')
    else:
        return redirect('/')

# ---- PASSWORD RESET ----
@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form['email']
        user = users.find_one({'email': email})
        if not user:
            return render_template("forgot_password.html", error="No such email registered.")
        otp = str(secrets.randbelow(1000000)).zfill(6)
        session['reset_email'] = email
        session['reset_otp'] = otp

        msg = Message("Your HaatXpress Reset OTP", recipients=[email])
        msg.body = f"Your OTP for password reset is: {otp}"
        try:
            mail.send(msg)
        except Exception as e:
            return f"Could not send OTP: {e}"
        return redirect('/reset-password-otp')
    return render_template('forgot_password.html')

@app.route('/reset-password-otp', methods=['GET', 'POST'])
def reset_password_otp():
    if 'reset_email' not in session or 'reset_otp' not in session:
        return redirect('/forgot-password')
    if request.method == 'POST':
        otp_in = request.form['otp']
        if otp_in == session['reset_otp']:
            session['otp_verified'] = True
            return redirect('/set-new-password')
        else:
            return render_template("reset_password_otp.html", error="Invalid OTP. Please try again.")
    return render_template("reset_password_otp.html")

@app.route('/set-new-password', methods=['GET', 'POST'])
def set_new_password():
    if not session.get('otp_verified'):
        return redirect('/forgot-password')
    if request.method == 'POST':
        pw = request.form['password']
        cpw = request.form['confirm_password']
        if pw != cpw:
            return render_template("set_new_password.html", error="Passwords do not match.")
        hashed = generate_password_hash(pw)
        users.update_one({"email": session['reset_email']},
                         {"$set": {"password": hashed}})
        session.pop('reset_email', None)
        session.pop('reset_otp', None)
        session.pop('otp_verified', None)
        flash("Password reset successful. Please log in.")
        return redirect('/login')
    return render_template("set_new_password.html")

@app.route('/dashboard')
def dashboard():
    if 'user' in session:
        role = session.get('role')
        if role == 'seller':
            return redirect('/seller/dashboard')
        elif role == 'customer':
            return redirect('/customer-dashboard')
        elif role == 'delivery':
            return redirect('/delivery-dashboard')
        elif role == 'admin':
            return redirect('/admin-dashboard')
        else:
            return "Unknown role"
    return redirect('/login')

@app.route('/admin-dashboard')
def admin_dashboard():
    if 'user' not in session or session['role'] != 'admin':
        return redirect('/login')
    sellers_list = list(users.find({"role": "seller"}))
    grouped_items = {}
    grouped_earnings = {}
    grouped_orders = {}
    for seller in sellers_list:
        email = seller['email']
        shop = sellers.find_one({'email': email})
        if shop:
            seller.update({
                "shop_type": shop.get("shop_type"),
                "shop_name": shop.get("shop_name"),
                "shop_photo": shop.get("shop_photo"),
                "shop_address": shop.get("shop_address"),
                "shop_contact": shop.get("shop_contact"),
            })
        grouped_items[email] = list(items.find({"seller_email": email}))
        earning = earnings.find_one({"seller_email": email})
        grouped_earnings[email] = {
            'total_earnings': earning.get('total_earnings', 0) if earning else 0,
            'last_updated': earning.get('last_updated', "N/A") if earning else "N/A"
        }
        grouped_orders[email] = list(orders.find({"shop_email": email}))
    return render_template(
        'admin.html',
        sellers=sellers_list,
        grouped_items=grouped_items,
        grouped_earnings=grouped_earnings,
        grouped_orders=grouped_orders
    )

@app.route('/admin/mark-order-paid/<order_id>', methods=['POST'])
def admin_mark_order_paid(order_id):
    order = orders.find_one({"_id": ObjectId(order_id)})
    if not order:
        return "Order not found", 404
    orders.update_one({"_id": ObjectId(order_id)}, {"$set": {"paid_status": "paid"}})
    if order.get('paid_status') != 'paid':
        earning = earnings.find_one({"seller_email": order.get('shop_email')})
        total_earnings = earning.get('total_earnings', 0) if earning else 0
        new_total = float(total_earnings) + float(order.get('total', 0))
        earnings.update_one(
            {"seller_email": order.get('shop_email')},
            {"$set": {"total_earnings": new_total, "last_updated": datetime.now().strftime('%Y-%m-%d %H:%M:%S')}},
            upsert=True
        )
    return redirect('/admin-dashboard')

@app.route('/admin/post-notice', methods=['POST'])
def post_notice():
    if 'user' not in session or session.get('role') != 'admin':
        return redirect('/login')
    notice_msg = request.form['message'].strip()
    target_email = request.form.get('target_email', 'all') # "all" or one seller's email

    notice_doc = {
        "notice": notice_msg,
        "to": target_email,
        "from_admin_email": app.config['MAIL_USERNAME'] or "rchoudhury0522@gmail.com",
        "timestamp": datetime.now()
    }
    notices.insert_one(notice_doc)
    try:
        if target_email and target_email != "all":
            user = users.find_one({"email": target_email})
            if user:
                msg = Message(
                    "Notice from Admin",
                    sender=app.config['MAIL_USERNAME'] or "rchoudhury0522@gmail.com",
                    recipients=[target_email],
                    body=notice_msg
                )
                mail.send(msg)
        else:
            seller_emails = [s['email'] for s in users.find({"role": "seller"})]
            for email in seller_emails:
                msg = Message(
                    "Notice from Admin",
                    sender=app.config['MAIL_USERNAME'] or "rchoudhury0522@gmail.com",
                    recipients=[email],
                    body=notice_msg
                )
                mail.send(msg)
    except Exception as e:
        return f"Failed to send notice/email: {str(e)}", 500
    return redirect('/admin-dashboard')

@app.route('/admin/remove-seller/<email>', methods=['POST'])
def admin_remove_seller(email):
    if 'user' not in session or session.get('role') != 'admin':
        return redirect('/login')
    users.delete_one({"email": email})
    sellers.delete_one({"email": email})
    items.delete_many({"seller_email": email})
    earnings.delete_one({"seller_email": email})
    orders.delete_many({"shop_email": email})
    return redirect('/admin-dashboard')

# ---- SELLER and CUSTOMER ROUTES ----
init_seller_routes(app, db, mail=mail, admin_email=ADMIN_EMAIL)
init_customer_routes(app, db, mail=mail, admin_email=ADMIN_EMAIL)
init_delivery_routes(app, db)  # DELIVERY ROUTES - THIS ADDS/REGISTERS THE delivery_bp blueprint

@app.route("/debug-uri")
def debug_uri():
    return f"Redirect URI: {url_for('google_login', _external=True)}"

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')

@app.context_processor
def inject_user():
    user_email = session.get('user')
    user_data = None
    if user_email:
        user_data = users.find_one({'email': user_email})
    return {
        'user_email': user_email,
        'user_name': user_data['full_name'] if user_data else None
    }

if __name__ == '__main__':
    app.run(debug=True)
