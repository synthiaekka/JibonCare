import os
import uuid
from flask import Blueprint, request, session, redirect, render_template, current_app, flash
from werkzeug.utils import secure_filename
from datetime import datetime
from bson import ObjectId
from flask_mail import Message

seller_bp = Blueprint('seller', __name__)
UPLOAD_FOLDER = 'static/uploads'

def send_order_notification(mail, subject, recipients, body):
    """Helper to send an email."""
    if mail and recipients:
        try:
            msg = Message(subject, recipients=recipients, body=body)
            mail.send(msg)
        except Exception as e:
            print("Could not send mail:", e)

def format_order_email(order):
    items_list = "\n".join([f"- {item['name']} ×1 @ ₹{item['price']}" for item in order.get('items', [])])
    return f"""New Order Received!
Shop: {order.get("shop_name", "-")}
Customer: {order.get("name", "-")}
Phone: {order.get("phone", "-")}
Address: {order.get("address", "-")}

Order Items:
{items_list}

Total: ₹{order.get("total", "--")}
Payment: {order.get("payment", "--")}
Order Time: {order.get("timestamp", "-")}
"""

def init_seller_routes(app, db, mail=None, admin_email=None):
    app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

    sellers_col = db['sellers']
    items_col = db['items']
    orders_col = db['orders']
    notices_col = db['notices']
    earnings_col = db['earnings']

    # Seller Dashboard
    @seller_bp.route('/seller/dashboard')
    def seller_dashboard():
        if 'user' not in session or session.get('role') != 'seller':
            return redirect('/login')
        email = session.get('user')
        shop_data = sellers_col.find_one({'email': email})
        seller_items = list(items_col.find({'seller_email': email}))

        # Fetch notices for "all" and for this seller, and format for template
        raw_notices = list(notices_col.find({'$or': [{"to": "all"}, {"to": email}]}).sort("timestamp", -1))
        notice_list = []
        for n in raw_notices:
            # Get date as string from timestamp (datetime or fallback)
            dt = n.get("timestamp")
            if isinstance(dt, datetime):
                date_str = dt.strftime('%Y-%m-%d %H:%M')
            elif isinstance(dt, str):
                date_str = dt
            else:
                date_str = n.get("date", "")
            notice_list.append({
                "message": n.get("message", ""),  # MUST have message field in DB
                "date": date_str
            })
        earnings_data = earnings_col.find_one({"seller_email": email}) or {}

        shop = None
        if shop_data:
            shop = {
                "name": shop_data.get("shop_name", ""),
                "shop_type": shop_data.get("shop_type", None),
                "contact": shop_data.get("shop_contact", ""),
                "address": shop_data.get("shop_address", ""),
                "photo_url": shop_data.get("shop_photo", "/static/default-avatar.png"),
                "lat": shop_data.get("lat", ""),
                "lng": shop_data.get("lng", "")
            }

        seller_orders = list(orders_col.find({"shop_email": email}))

        return render_template(
            "seller_dashboard.html",
            user_email=email,
            items=seller_items,
            notices=notice_list,
            earnings={
                "total_earnings": earnings_data.get("total_earnings", 0),
                "last_updated": earnings_data.get("last_updated", "N/A")
            },
            shop=shop,
            orders=seller_orders
        )

    # Register Shop
    @seller_bp.route('/seller/register-shop', methods=['POST'])
    def register_shop():
        if 'user' not in session or session.get('role') != 'seller':
            return redirect('/login')
        try:
            shop_type = request.form.get('shop_type', '').strip()
            shop_name = request.form['shop_name']
            shop_contact = request.form['shop_contact']
            shop_address = request.form['shop_address']
            photo = request.files.get('shop_photo')
            email = session.get('user')
            lat = request.form.get('lat', '').strip()
            lng = request.form.get('lng', '').strip()

            if not lat or not lng:
                return "Please use the 'Use Current Location' button to provide your shop location.", 400
            try:
                lat, lng = float(lat), float(lng)
            except Exception:
                return "Invalid latitude/longitude.", 400
            if not shop_type:
                return "Please select a Shop Type", 400

            photo_url = None
            if photo and photo.filename:
                filename = secure_filename(photo.filename)
                unique_filename = f"shop_{uuid.uuid4()}_{filename}"
                photo_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
                os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
                photo.save(photo_path)
                photo_url = f"/{photo_path.replace(os.sep, '/')}"
            sellers_col.update_one(
                {"email": email},
                {"$set": {
                    "shop_type": shop_type,
                    "shop_name": shop_name,
                    "shop_contact": shop_contact,
                    "shop_address": shop_address,
                    "shop_photo": photo_url,
                    "lat": lat,
                    "lng": lng
                }},
                upsert=True
            )
            return redirect('/seller/dashboard')
        except Exception as e:
            return f"Shop registration failed: {str(e)}", 500

    # Edit Shop
    @seller_bp.route('/seller/edit-shop', methods=['GET', 'POST'])
    def edit_shop():
        if 'user' not in session or session.get('role') != 'seller':
            return redirect('/login')
        email = session['user']
        shop = sellers_col.find_one({'email': email})
        if request.method == 'POST':
            try:
                shop_type = request.form.get('shop_type', '').strip()
                shop_name = request.form['shop_name']
                shop_contact = request.form['shop_contact']
                shop_address = request.form['shop_address']
                photo = request.files.get('shop_photo')
                if not shop_type:
                    return "Please select a Shop Type", 400
                update_data = {
                    "shop_type": shop_type,
                    "shop_name": shop_name,
                    "shop_contact": shop_contact,
                    "shop_address": shop_address,
                }
                if photo and photo.filename:
                    filename = secure_filename(photo.filename)
                    unique_filename = f"shop_{uuid.uuid4()}_{filename}"
                    photo_path = os.path.join(current_app.config['UPLOAD_FOLDER'], unique_filename)
                    os.makedirs(current_app.config['UPLOAD_FOLDER'], exist_ok=True)
                    photo.save(photo_path)
                    update_data["shop_photo"] = f"/{photo_path.replace(os.sep, '/')}"
                sellers_col.update_one({"email": email}, {"$set": update_data})
                return redirect('/seller/dashboard')
            except Exception as e:
                return f"Shop update failed: {str(e)}", 500
        return render_template('edit_shop.html', shop=shop)

    # Upload Item
    @seller_bp.route('/seller/upload-item', methods=['POST'])
    def upload_item():
        if 'user' not in session or session.get('role') != 'seller':
            return redirect('/login')
        try:
            item_type = request.form['item_type']
            item_name = request.form['item_name']
            price = float(request.form['price'])
            image = request.files.get('image')
            image_url = None
            if image and image.filename:
                filename = secure_filename(image.filename)
                unique_filename = f"{uuid.uuid4()}_{filename}"
                image_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
                os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
                image.save(image_path)
                image_url = f"/{image_path.replace(os.sep, '/')}"
            item = {
                "seller_email": session.get('user'),
                "type": item_type,
                "name": item_name,
                "price": price,
                "image_url": image_url,
                "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            items_col.insert_one(item)
            return redirect('/seller/dashboard?success=1')
        except Exception as e:
            return f"Upload failed: {str(e)}", 500

    # Delete Item
    @seller_bp.route('/seller/delete-item/<item_id>', methods=['POST'])
    def delete_item(item_id):
        if 'user' not in session or session.get('role') != 'seller':
            return redirect('/login')
        try:
            items_col.delete_one({"_id": ObjectId(item_id), "seller_email": session['user']})
            return redirect('/seller/dashboard')
        except Exception as e:
            return f"Delete failed: {str(e)}", 500

    # Seller Set Order Status
    @seller_bp.route('/seller/order-status/<order_id>', methods=['POST'])
    def seller_set_order_status(order_id):
        if 'user' not in session or session.get('role') != 'seller':
            return redirect('/login')
        try:
            new_status = request.form['paid_status']  # "pending" or "paid"
            order = orders_col.find_one({"_id": ObjectId(order_id), "shop_email": session['user']})
            if not order:
                return "Order not found.", 404
            orders_col.update_one({"_id": ObjectId(order_id)}, {"$set": {"paid_status": new_status}})
            earnings_doc = earnings_col.find_one({"seller_email": session['user']}) or {"total_earnings": 0}
            if new_status == "paid":
                total_earnings = float(earnings_doc.get("total_earnings", 0)) + float(order.get("total", 0))
                earnings_col.update_one({"seller_email": session['user']},
                                      {"$set": {"total_earnings": total_earnings,
                                                "last_updated": datetime.now().strftime('%Y-%m-%d %H:%M:%S')}},
                                      upsert=True)
            return redirect('/seller/dashboard')
        except Exception as e:
            return f"Order status update failed: {str(e)}", 500

    # Place Order with Email Notification
    def place_order(order_data, mail=None, admin_email=None):
        order_data['paid_status'] = "pending"
        order_data['timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        order_id = orders_col.insert_one(order_data).inserted_id

        shop_doc = sellers_col.find_one({'email': order_data['shop_email']})
        seller_email = shop_doc.get('email') if shop_doc else None
        all_recipients = []
        if seller_email:
            all_recipients.append(seller_email)
        if admin_email:
            all_recipients.append(admin_email)
        subject = f"New Order at {order_data.get('shop_name','Your Shop')}"
        body = format_order_email(order_data)
        send_order_notification(mail, subject, all_recipients, body)
        return str(order_id)

    app.register_blueprint(seller_bp)
    app.place_order = lambda *a, **k: place_order(*a, **k)
