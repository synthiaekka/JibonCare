from flask import Blueprint, render_template, session, redirect, jsonify, request
from math import radians, cos, sin, sqrt, atan2
from flask_mail import Message
from datetime import datetime
from bson import ObjectId


def haversine(lat1, lng1, lat2, lng2):
    R = 6371.0
    lat1, lng1, lat2, lng2 = map(radians, [lat1, lng1, lat2, lng2])
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlng / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return R * c  # distance in km


def format_order_email(order):
    items = "\n".join(
        [f"- {item['name']} ×1 @ ₹{item['price']}" for item in order.get("items", [])]
    )
    return f"""New Order Placed!


Shop: {order.get("shop_name", "-")}
Customer: {order.get("name", "-")}
Phone: {order.get("phone", "-")}
Address: {order.get("address", "-")}


Order Items:
{items}


Total: ₹{order.get("total", "--")}
Payment: {order.get("payment", "--")}
Order Time: {order.get("timestamp", "-")}
"""


def init_customer_routes(app, db, mail=None, admin_email=None):
    customer_bp = Blueprint('customer', __name__)
    sellers_col = db['sellers']
    items_col = db['items']
    orders_col = db['orders']
    delivery_col = db['delivery_partners']


    # -------- Customer dashboard --------
    @customer_bp.route('/customer-dashboard')
    def customer_dashboard():
        if 'user' not in session or session.get('role') != 'customer':
            return redirect('/login')
        return render_template('customer.html', user_email=session.get('user'))


    # -------- Shops API with optional location & category filtering --------
    @customer_bp.route('/customer/shops')
    def customer_shops():
        category = request.args.get("category")
        user_lat = request.args.get('lat', type=float)
        user_lng = request.args.get('lng', type=float)
        query = {}
        if category:
            query["shop_type"] = category
        shoplist = list(sellers_col.find(
            query,
            {
                "shop_name": 1,
                "shop_address": 1,
                "shop_contact": 1,
                "shop_photo": 1,
                "email": 1,
                "shop_type": 1,
                "lat": 1,
                "lng": 1
            }
        ))
        if user_lat is not None and user_lng is not None:
            filtered = []
            for shop in shoplist:
                shoplat = shop.get("lat")
                shoplng = shop.get("lng")
                if shoplat is None or shoplng is None:
                    continue
                dist = haversine(user_lat, user_lng, float(shoplat), float(shoplng))
                if dist <= 5:
                    shop["distance_km"] = round(dist, 2)
                    filtered.append(shop)
            shoplist = filtered
        for shop in shoplist:
            shop["_id"] = str(shop["_id"])
        return jsonify(shoplist)


    # -------- Products for a specific shop --------
    @customer_bp.route('/customer/products/<shop_email>')
    def customer_products(shop_email):
        products = list(items_col.find({"seller_email": shop_email}))
        for p in products:
            p["_id"] = str(p["_id"])
        return jsonify(products)


    # -------- Search shops by matching product --------
    @customer_bp.route('/customer/search-shops-by-product')
    def search_shops_by_product():
        query_text = request.args.get('query', '').strip()
        user_lat = request.args.get('lat', type=float)
        user_lng = request.args.get('lng', type=float)


        if not query_text:
            return jsonify([])


        regex = {"$regex": query_text, "$options": "i"}


        # Find matching products by name
        products = list(items_col.find({"name": regex}, {"seller_email": 1, "name": 1}))
        if not products:
            return jsonify([])


        # Map seller email to product names
        shop_to_products = {}
        for item in products:
            email = item.get("seller_email")
            name = item.get("name")
            if email and name:
                shop_to_products.setdefault(email, []).append(name)


        seller_emails = list(shop_to_products)
        if not seller_emails:
            return jsonify([])


        # Find shops selling those products
        shop_query = {"email": {"$in": seller_emails}}
        projection = {
            "shop_name": 1,
            "shop_address": 1,
            "shop_contact": 1,
            "shop_photo": 1,
            "email": 1,
            "shop_type": 1,
            "lat": 1,
            "lng": 1
        }
        shoplist = list(sellers_col.find(shop_query, projection))


        # Optional 5km radius filter
        if user_lat is not None and user_lng is not None:
            filtered = []
            for shop in shoplist:
                shoplat = shop.get("lat")
                shoplng = shop.get("lng")
                if shoplat is None or shoplng is None:
                    continue
                dist = haversine(user_lat, user_lng, float(shoplat), float(shoplng))
                if dist <= 5:
                    shop["distance_km"] = round(dist, 2)
                    filtered.append(shop)
            shoplist = filtered


        # Attach matching products & stringify _id
        for shop in shoplist:
            shop["_id"] = str(shop["_id"])
            shop["matching_products"] = shop_to_products.get(shop["email"], [])


        return jsonify(shoplist)


    # -------- Customer's orders --------
    @customer_bp.route('/customer/my-orders')
    def my_orders():
        if 'user' not in session or session.get('role') != 'customer':
            return redirect('/login')
        email = session.get('user')
        orders = list(orders_col.find({"customer_email": email}))
        for o in orders:
            o["_id"] = str(o["_id"])
        return render_template("my_orders.html", orders=orders, user_email=email)


    # -------- Place an order --------
    @customer_bp.route('/customer/place-order', methods=['POST'])
    def place_order():
        if 'user' not in session or session.get('role') != 'customer':
            return jsonify({'success': False, 'message': 'Not logged in'})
        data = request.json
        data['customer_email'] = session.get('user')
        data['timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        data['paid_status'] = 'pending'


        # Shop lat/lng for delivery notification
        shop_doc = sellers_col.find_one({'email': data.get('shop_email')})
        shop_lat, shop_lng = None, None
        if shop_doc:
            shop_lat = shop_doc.get('lat')
            shop_lng = shop_doc.get('lng')
            if shop_lat is not None and shop_lng is not None:
                data["location"] = {"lat": shop_lat, "lng": shop_lng}


        orders_col.insert_one(data)


        # Notify seller, admin and delivery partners
        recipients = []
        seller_email = shop_doc.get('email') if shop_doc else None
        if seller_email:
            recipients.append(seller_email)
        if admin_email:
            recipients.append(admin_email)


        delivery_emails = []
        if shop_lat is not None and shop_lng is not None:
            delivery_partners = delivery_col.find({
                "current_lat": {"$ne": None},
                "current_lng": {"$ne": None}
            })
            for partner in delivery_partners:
                plat = partner.get("current_lat")
                plng = partner.get("current_lng")
                if plat is not None and plng is not None:
                    dist = haversine(float(shop_lat), float(shop_lng), float(plat), float(plng))
                    if dist <= 5:
                        pemail = partner.get("email")
                        if pemail and pemail not in recipients:
                            delivery_emails.append(pemail)
        else:
            delivery_emails = [p["email"] for p in delivery_col.find() if p.get("email") and p["email"] not in recipients]


        recipients += [e for e in delivery_emails if e not in recipients]


        email_body = format_order_email(data)
        subject = f"Order Placed on HaatExpress: {data.get('shop_name','(Shop)')}"
        if mail and recipients:
            try:
                msg = Message(subject, recipients=recipients, body=email_body)
                mail.send(msg)
            except Exception as e:
                print(f"Failed to send notification: {e}")


        return jsonify({'success': True, 'message': 'Order placed, notification sent!'})


    app.register_blueprint(customer_bp)
