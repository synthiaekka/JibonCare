from pymongo import MongoClient
from werkzeug.security import generate_password_hash
from dotenv import load_dotenv
from datetime import datetime
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

try:
    from termcolor import colored
except ImportError:
    def colored(text, *a, **k): return text

# ----------- SMTP Email Sending Function -----------
def send_email(to_email, subject, body):
    sender_email = os.getenv("SMTP_EMAIL")
    sender_password = os.getenv("SMTP_PASSWORD")
    smtp_server = "smtp.gmail.com"
    smtp_port = 587

    msg = MIMEMultipart()
    msg["From"] = sender_email
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(sender_email, sender_password)
        server.send_message(msg)
        server.quit()
        print(colored(f"   -> Email sent to {to_email}", "green"))
    except Exception as e:
        print(colored(f"   -> Failed to send email: {e}", "red"))

# ----------- Load configuration and connect DB -----------
load_dotenv()
client = MongoClient(os.getenv("MONGO_URI"))
db = client["haatExpress"]
users = db["users"]
sellers_col = db["sellers"]
items_col = db["items"]
earnings_col = db["earnings"]
orders_col = db["orders"]
notices_col = db["notices"]

email = "richachoudhury478@gmail.com"
password = "admin123"
hashed_pw = generate_password_hash(password)

admin_user = {
    "full_name": "Admin",
    "phone": "0000000000",
    "email": email,
    "password": hashed_pw,
    "role": "admin"
}

if not users.find_one({"email": email}):
    users.insert_one(admin_user)
    print(colored("Admin user created successfully.", "green"))
else:
    print("Admin already exists.")

print("\n" + "=" * 65)
print(colored("            🚀 Registered Sellers Summary", "cyan"))
print("=" * 65)

sellers = users.find({"role": "seller"})
for seller in sellers:
    seller_email = seller.get('email')
    shop = sellers_col.find_one({"email": seller_email})

    print(f"\n{'-' * 60}")
    print(colored(f"👤 Seller: {seller.get('full_name')} ({seller_email})", "yellow"))
    print(f"📱 Phone: {seller.get('phone')}")

    if shop:
        print(f"🏬 Shop Name: {shop.get('shop_name', '--')}")
        print(f"🏠 Address  : {shop.get('shop_address', '--')}")
        print(f"📞 Contact  : {shop.get('shop_contact', '--')}")
        print(f"🖼  Shop Img : {shop.get('shop_photo', '--')}")
    else:
        print(colored("❗ No shop registered yet.", "red"))

    # Earnings
    earning_doc = earnings_col.find_one({"seller_email": seller_email})
    total_earnings = earning_doc.get("total_earnings", 0) if earning_doc else 0
    last_updated = earning_doc.get("last_updated", "N/A") if earning_doc else "N/A"
    print(colored(f"💰 Total Earnings: ₹{total_earnings} (Last Updated: {last_updated})", "green"))

    # Products
    products = list(items_col.find({"seller_email": seller_email}))
    if products:
        print(f"📦 Products listed ({len(products)}):")
        for idx, product in enumerate(products, start=1):
            print(
                f"   {idx}. {product.get('name')} |"
                f" Type: {product.get('type', '-')},"
                f" Price: ₹{product.get('price', '-')},"
                f" Uploaded: {product.get('timestamp', '-')},"
                f" Image: {product.get('image_url', '-')}"
            )
    else:
        print("   No products uploaded.")

    # Orders and admin's ability to mark as paid
    shop_orders = list(orders_col.find({"shop_email": seller_email}))
    if shop_orders:
        print(colored(f"📜 Orders Received ({len(shop_orders)}):", "magenta"))
        for idx, order in enumerate(shop_orders, start=1):
            stat_color = "yellow" if order.get("paid_status") == "pending" else "green"
            status = order.get('paid_status', 'pending').upper()
            print(f"   {idx}. OrderID: {str(order.get('_id'))}")
            print(f"       Time: {order.get('timestamp', '-')}")
            print(f"       Customer: {order.get('name', '-')} | Phone: {order.get('phone', '-')}")
            print(f"       Address: {order.get('address', '-')}")
            print(f"       Payment: {order.get('payment', '-')}")
            print(colored(f"       Status: {status}", stat_color))
            print(f"       Items:")
            for i in order.get('items', []):
                print(f"         - {i.get('name')} (₹{i.get('price')})")
            print(f"       Total: ₹{order.get('total', '-')}")

            # Prompt to mark as paid (interactive only)
            if order.get("paid_status") == "pending":
                choice = input("       Mark as paid? (y/N): ").strip().lower()
                if choice == "y":
                    # Mark order as paid
                    orders_col.update_one({"_id": order["_id"]}, {"$set": {"paid_status": "paid"}})
                    # Add to earnings
                    earning_doc = earnings_col.find_one({"seller_email": seller_email})
                    curr_earn = earning_doc.get("total_earnings", 0) if earning_doc else 0
                    add_amt = float(order.get("total", 0))
                    new_total = float(curr_earn) + add_amt
                    earnings_col.update_one(
                        {"seller_email": seller_email},
                        {"$set": {"total_earnings": new_total, "last_updated": datetime.now().strftime('%Y-%m-%d %H:%M:%S')}},
                        upsert=True
                    )
                    print(colored("       -> Marked as PAID and earnings updated.", "green"))
    else:
        print(colored("   No orders received yet.", "blue"))

    # ==== ADMIN NOTICE SECTION ====
    print(colored("\n📢 Notices to this Seller:", "cyan"))
    this_seller_notices = list(notices_col.find({"seller_email": seller_email}).sort("timestamp", -1))
    if this_seller_notices:
        for notice in this_seller_notices:
            ts = notice.get('timestamp')
            date_str = ts.strftime("%Y-%m-%d %H:%M") if isinstance(ts, datetime) else str(ts)
            print(colored(f"   [{date_str}] {notice.get('notice')}", "magenta"))
    else:
        print("   No notices sent yet.")

    # Prompt to send a new notice AND email
    send_notice = input(colored("   Send a new notice to this seller? (y/N): ", "blue")).strip().lower()
    if send_notice == "y":
        notice_text = input("   Enter notice text: ").strip()
        if notice_text:
            # Save in DB
            notices_col.insert_one({
                "seller_email": seller_email,
                "notice": notice_text,
                "timestamp": datetime.now(),
                "from_admin_email": email
            })
            print(colored("   -> Notice saved and sent.", "green"))
            # Send email
            subject = "New Notice from Admin - HaatExpress"
            body = f"""Dear {seller.get('full_name')},

You have a new notice from the HaatExpress admin:

-------------------------
{notice_text}
-------------------------

Please check your seller dashboard for more details.

Best regards,
HaatExpress Admin
"""
            send_email(seller_email, subject, body)
        else:
            print(colored("   (Notice not sent. Empty message.)", "yellow"))

print("\n" + "=" * 65)
print(colored("Admin summary complete.\n", "cyan"))
