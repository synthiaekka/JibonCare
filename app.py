import os
import secrets
import json
from flask import Flask, render_template, request, redirect, session, flash, url_for, jsonify
from pymongo import MongoClient
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from flask_mail import Mail, Message
from requests_oauthlib import OAuth2Session
from datetime import datetime
from bson import ObjectId
from twilio.rest import Client

# Load environment variables
load_dotenv()

from seller import init_seller_routes
from customer import init_customer_routes
from delivery import init_delivery_routes

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY") or 'SUPER_SECRET_KEY'

# MongoDB setup
MONGO_URI = os.getenv("MONGO_URI") or (
    "mongodb+srv://Synthia:3sx1zTjPh9HWcwnn@haatexpress.rgonj6q.mongodb.net/"
    "?retryWrites=true&w=majority&appName=haatexpress"
)
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

# Twilio client setup
TWILIO_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER", "+918453327570")
twilio_client = Client(TWILIO_SID, TWILIO_AUTH_TOKEN)

# Upload folder
UPLOAD_FOLDER = 'static/uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# GOOGLE OAUTH2 Credentials
with open("client_secret.json") as f:
    google_creds = json.load(f)["web"]

GOOGLE_CLIENT_ID = google_creds["client_id"]
GOOGLE_CLIENT_SECRET = google_creds["client_secret"]
GOOGLE_AUTHORIZATION_BASE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USER_INFO_URL = "https://www.googleapis.com/oauth2/v1/userinfo"


# Helper to create UPI payment URI with fixed merchant UPI ID
def create_upi_uri(amount):
    merchant_upi = "richachoudhury478-2@okaxis"
    payee_name = "HaatXpress"
    from urllib.parse import quote_plus
    params = {
        'pa': merchant_upi,
        'pn': payee_name,
        'am': f'{amount:.2f}',
        'cu': 'INR',
        'tn': 'HaatXpress Order Payment'
    }
    param_str = '&'.join(f"{key}={quote_plus(str(value))}" for key, value in params.items())
    return f"upi://pay?{param_str}"


# Helper to send payment request email with a PAY NOW button
def send_payment_email(to_email, order):
    try:
        upi_uri = create_upi_uri(order.get("total", 0))
        html_body = f"""
        <p>Dear Customer,</p>
        <p>You have a payment request for your recent order:</p>
        <ul>
            <li><b>Shop:</b> {order.get("shop_name", "")}</li>
            <li><b>Name:</b> {order.get("name", "")}</li>
            <li><b>Total Amount:</b> ₹{order.get("total", 0):.2f}</li>
        </ul>
        <p>Please complete your payment by clicking the button below:</p>
        <p style="text-align:center;">
          <a href="{upi_uri}" style="
            display:inline-block;
            padding:12px 24px;
            font-size:16px;
            color:#fff;
            background-color:#4CAF50;
            text-decoration:none;
            border-radius:6px;
          ">PAY NOW</a>
        </p>
        <p>Thank you for choosing HaatXpress!</p>
        """
        msg = Message(
            subject="HaatXpress Payment Request",
            sender=ADMIN_EMAIL,
            recipients=[to_email]
        )
        msg.html = html_body
        mail.send(msg)
        app.logger.info(f"Payment email sent to {to_email}")
        return True
    except Exception as e:
        app.logger.error(f"Failed to send email to {to_email}: {e}")
        return False


# Helper to send SMS payment request with UPI URI and details
def send_payment_sms(to_phone, order):
    try:
        upi_uri = create_upi_uri(order.get("total", 0))
        message_body = (
            f"HaatXpress Payment Request:\n"
            f"Shop: {order.get('shop_name', '')}\n"
            f"Name: {order.get('name', '')}\n"
            f"Total: ₹{order.get('total', 0):.2f}\n\n"
            f"Pay now using your UPI app: {upi_uri}"
        )
        message = twilio_client.messages.create(
            body=message_body,
            from_=TWILIO_PHONE_NUMBER,
            to=to_phone
        )
        app.logger.info(f"SMS sent to {to_phone}, SID: {message.sid}")
        return True
    except Exception as e:
        app.logger.error(f"Failed to send SMS to {to_phone}: {e}")
        return False


# Existing user routes and APIs (register, login, password reset, etc.) — as you originally provided
@app.route('/')
def home():
    return render_template("index.html")

@app.route('/api/shops')
def api_shops():
    area = request.args.get('area', '').strip().lower()
    shops_query = {}

    if area:
        shops_query = {
            "$or": [
                {"shop_address": {"$regex": area, "$options": "i"}},
                {"shop_district": {"$regex": area, "$options": "i"}},
                {"shop_pincode": {"$regex": area, "$options": "i"}},
                {"shop_name": {"$regex": area, "$options": "i"}}
            ]
        }
    shops_cursor = sellers.find(shops_query)

    shops = []
    for shop in shops_cursor:
        shops.append({
            "name": shop.get("shop_name", "Unnamed Shop"),
            "category": shop.get("shop_type", "Unknown"),
            "image_url": shop.get("shop_photo", "/static/default-avatar.png"),
            "address": shop.get("shop_address", ""),
            "district": shop.get("shop_district", ""),
            "pincode": shop.get("shop_pincode", ""),
            "distance": None,
            "email": shop.get("email", "")
        })
    return jsonify({"shops": shops})

@app.route('/api/items')
def api_items():
    seller_email = request.args.get('seller_email')
    query = {}
    if seller_email:
        query['seller_email'] = seller_email

    items_cursor = items.find(query)
    items_list = []
    for item in items_cursor:
        items_list.append({
            "id": str(item['_id']),
            "name": item.get('name'),
            "type": item.get('type'),
            "price": item.get('price', 0),
            "image_url": item.get('image_url', '/static/default-avatar.png'),
            "description": item.get('description', '')
        })
    return jsonify({"items": items_list})

@app.route("/grocery")
def grocery():
    return render_template("grocery.html")

@app.route("/medicine")
def medicine():
    return render_template("medicine.html")

@app.route("/restaurant")
def restaurant():
    return render_template("restaurant.html")


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
        msg = Message("Your HaatExpress OTP Verification Code", recipients=[email])
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
    target_email = request.form.get('target_email', 'all')

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
@app.route('/api/set_delivery_districts', methods=['POST'])
def set_delivery_districts():
    print("SESSION CONTENT:", session)  # Add this

    if 'email' not in session:
        return jsonify({"error": "Not logged in"}), 401

# Initialize seller, customer, delivery blueprints
init_seller_routes(app, db, mail=mail, admin_email=ADMIN_EMAIL)
init_customer_routes(app, db, mail=mail, admin_email=ADMIN_EMAIL)
init_delivery_routes(app, db)

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


# Notify merchant endpoint — send payment notification email and sms
@app.route('/notify-merchant', methods=['POST'])
def notify_merchant():
    data = request.get_json()
    merchant_upi = data.get('merchant_upi', '')
    merchant_phone = data.get('merchant_phone', '')
    payment_method = data.get('payment_method', '')
    order = data.get('order', {})

    customer_email = order.get('email')
    customer_phone = order.get('phone')

    email_sent = False
    sms_sent = False

    if customer_email:
        email_sent = send_payment_email(customer_email, order)

    if customer_phone:
        normalized_phone = customer_phone
        if not customer_phone.startswith('+'):
            normalized_phone = '+91' + customer_phone  # Adjust country code as needed
        sms_sent = send_payment_sms(normalized_phone, order)

    return jsonify({
        "status": "notification attempted",
        "email_sent": email_sent,
        "sms_sent": sms_sent,
    }), 200

if __name__ == '__main__':
    app.run(debug=True)






