from flask import Blueprint, request, jsonify, session, render_template, redirect, current_app
from math import radians, cos, sin, sqrt, atan2
from datetime import datetime
from bson import ObjectId

delivery_bp = Blueprint('delivery', __name__)

# ---------- Haversine formula for distance calculation -----------
def haversine(lat1, lng1, lat2, lng2):
    R = 6371.0  # Earth radius in km
    lat1, lng1, lat2, lng2 = map(radians, [lat1, lng1, lat2, lng2])
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    a = sin(dlat/2)**2 + cos(lat1)*cos(lat2)*sin(dlng/2)**2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return R * c  # Distance in kilometers

def send_user_notification(user_email, user_phone, order_id, accepted=True):
    """
    Placeholder to notify user for delivery acceptance or rejection.
    Replace this with actual email/SMS notification logic as needed.
    """
    action = "accepted" if accepted else "rejected"
    current_app.logger.info(f"User ({user_email} / {user_phone}) notified that delivery {action} order {order_id}")
    # TODO: Integrate email or SMS notification here.

def init_delivery_routes(app, db):
    delivery_col = db['delivery_partners']
    orders_col = db['orders']
    users_col = db['users']  # Optional, in case you need user info

    # ----------- Registration Route -----------
    @delivery_bp.route('/register', methods=['GET', 'POST'])
    def register():
        if request.method == 'POST':
            email = request.form['email']
            password = request.form['password']
            role = request.form['role']  # expected: 'delivery', 'admin', or 'customer'

            if delivery_col.find_one({'email': email}):
                return "User already exists", 400

            delivery_col.insert_one({
                'email': email,
                'password': password,
                'role': role,
                'earnings': 0,
                'current_lat': None,
                'current_lng': None,
                'last_updated': None
            })
            return redirect('/login')
        # Simple form, customize this template for your app's style.
        return '''
            <form method="post">
                Email: <input name="email" type="email" required><br>
                Password: <input name="password" type="password" required><br>
                Role:
                <select name="role" required>
                    <option value="delivery">Delivery</option>
                    <option value="admin">Admin</option>
                    <option value="customer">Customer</option>
                </select><br>
                <button type="submit">Register</button>
            </form>
        '''

    # ----------- Login Route -----------
    @delivery_bp.route('/login', methods=['GET', 'POST'])
    def login():
        if request.method == 'POST':
            email = request.form['email']
            password = request.form['password']
            user = delivery_col.find_one({'email': email, 'password': password})
            if user:
                session['user'] = user['email']
                session['role'] = user.get('role', 'delivery')
                if user['role'] == 'delivery':
                    return redirect('/delivery-dashboard')
                else:
                    return redirect('/')  # adapt to admin/customer dashboards if any
            return "Login failed", 401
        # Simple login form, customize as needed
        return '''
            <form method="post">
                Email: <input name="email" type="email" required><br>
                Password: <input name="password" type="password" required><br>
                <button type="submit">Login</button>
            </form>
        '''

    # ----------- Logout Route -----------
    @delivery_bp.route('/logout')
    def logout():
        session.clear()
        return redirect('/login')

    # ----------- Delivery Dashboard -----------
    @delivery_bp.route('/delivery-dashboard')
    def delivery_dashboard():
        if 'user' not in session or session.get('role') != 'delivery':
            return redirect('/login')
        return render_template('del.html')  # Render your delivery partner dashboard template

    # ----------- Get Nearby Unassigned Orders based on lat/lng -----------
    @delivery_bp.route('/api/get_available_orders')
    def get_available_orders():
        lat = request.args.get('lat', type=float)
        lng = request.args.get('lng', type=float)
        if lat is None or lng is None:
            return jsonify({'orders': []})

        unassigned_orders = list(orders_col.find({"delivery_status": "pending"}))
        nearby_orders = []

        for order in unassigned_orders:
            dest = order.get("location")
            if not (isinstance(dest, dict)
                    and isinstance(dest.get('lat'), (int, float))
                    and isinstance(dest.get('lng'), (int, float))):
                continue
            dist = haversine(lat, lng, dest['lat'], dest['lng'])
            if dist <= 5:  # 5 km radius
                order["_id"] = str(order["_id"])
                nearby_orders.append(order)

        return jsonify({'orders': nearby_orders})

    # ----------- Get all Pending Deliveries for assignment -----------
    @delivery_bp.route('/api/pending_deliveries')
    def pending_deliveries():
        if 'user' not in session or session.get('role') != 'delivery':
            return jsonify({'orders': []}), 403

        pending_orders = list(orders_col.find({"delivery_status": "pending"}))
        result = []
        for order in pending_orders:
            order["_id"] = str(order["_id"])
            result.append({
                "order_id": order["_id"],
                "shop_name": order.get("shop_name", ""),
                "customer_name": order.get("name", ""),
                "customer_email": order.get('email', ''),
                "customer_phone": order.get('phone', ''),
                "address": order.get("address", ""),
                "items": order.get("items", []),
                "total": order.get("total", 0),
                "payment_mode": order.get("payment_mode", ""),
                "delivery_status": order.get("delivery_status", ""),
                "order_time": order.get("timestamp", ""),
            })
        return jsonify({"orders": result})

    # ----------- Accept a delivery assignment -----------
    @delivery_bp.route('/api/accept_delivery/<order_id>', methods=['POST'])
    def accept_delivery(order_id):
        if 'user' not in session or session.get('role') != 'delivery':
            return jsonify({'success': False, 'message': 'Unauthorized'}), 403

        try:
            oid = ObjectId(order_id)
        except Exception:
            return jsonify({'success': False, 'message': 'Invalid order ID'}), 400

        delivery_email = session.get('user')
        order = orders_col.find_one({"_id": oid})
        if not order:
            return jsonify({'success': False, 'message': 'Order not found'}), 404
        if order.get('delivery_status') != 'pending':
            return jsonify({'success': False, 'message': 'Order not available'}), 400

        result = orders_col.update_one(
            {"_id": oid, "delivery_status": "pending"},
            {
                "$set": {
                    "delivery_status": "assigned",
                    "assigned_to": delivery_email,
                    "assigned_to_email": delivery_email,
                    "assigned_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
            }
        )
        if result.modified_count == 0:
            return jsonify({'success': False, 'message': 'Order not available'}), 400

        # Notify user about acceptance
        user_email = order.get('email')
        user_phone = order.get('phone')
        send_user_notification(user_email, user_phone, order_id, accepted=True)

        return jsonify({'success': True, 'message': 'Order accepted'})

    # ----------- Reject a delivery order -----------
    @delivery_bp.route('/api/reject_delivery/<order_id>', methods=['POST'])
    def reject_delivery(order_id):
        if 'user' not in session or session.get('role') != 'delivery':
            return jsonify({'success': False, 'message': 'Unauthorized'}), 403

        try:
            oid = ObjectId(order_id)
        except Exception:
            return jsonify({'success': False, 'message': 'Invalid order ID'}), 400

        delivery_email = session.get('user')
        order = orders_col.find_one({"_id": oid})
        if not order:
            return jsonify({'success': False, 'message': 'Order not found'}), 404
        if order.get('assigned_to') != delivery_email:
            return jsonify({'success': False, 'message': 'You cannot reject this order'}), 400

        result = orders_col.update_one(
            {"_id": oid, "assigned_to": delivery_email},
            {
                "$set": {
                    "delivery_status": "pending",
                },
                "$unset": {
                    "assigned_to": "",
                    "assigned_to_email": "",
                    "assigned_time": ""
                }
            }
        )
        if result.modified_count == 0:
            return jsonify({'success': False, 'message': 'Could not reject order'}), 400

        # Notify user about rejection
        user_email = order.get('email')
        user_phone = order.get('phone')
        send_user_notification(user_email, user_phone, order_id, accepted=False)

        return jsonify({'success': True, 'message': 'Order rejected'})

    # ----------- Get Delivery Partner's current assigned order -----------
    @delivery_bp.route('/api/get_my_current_order')
    def get_my_current_order():
        if 'user' not in session or session.get('role') != 'delivery':
            return jsonify({'order': None})
        email = session.get('user')
        order = orders_col.find_one({
            "assigned_to": email,
            "delivery_status": {"$in": ["assigned", "picked_up"]}
        })
        if order:
            order["_id"] = str(order["_id"])
            if 'assigned_to_email' not in order and 'assigned_to' in order:
                order['assigned_to_email'] = order['assigned_to']
            return jsonify({'order': order})
        return jsonify({'order': None})

    # ----------- Mark Order as Delivered -----------
    @delivery_bp.route('/api/complete_order/<order_id>', methods=['POST'])
    def complete_order(order_id):
        if 'user' not in session or session.get('role') != 'delivery':
            return jsonify({'success': False, 'message': 'Unauthorized'}), 403

        try:
            oid = ObjectId(order_id)
        except Exception:
            return jsonify({'success': False, 'message': 'Invalid order ID'}), 400

        result = orders_col.update_one(
            {"_id": oid, "assigned_to": session.get('user')},
            {
                "$set": {
                    "delivery_status": "delivered",
                    "delivered_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
            }
        )
        if result.modified_count == 0:
            return jsonify({'success': False, 'message': 'Could not mark as delivered'}), 400

        # Add delivery earnings (example fixed ₹30 per delivery)
        delivery_col.update_one(
            {"email": session.get('user')},
            {"$inc": {"earnings": 30}}
        )
        return jsonify({'success': True, 'message': 'Order marked as delivered'})

    # ----------- Get Delivery Partner Earnings -----------
    @delivery_bp.route('/api/get_earnings')
    def get_earnings():
        if 'user' not in session or session.get('role') != 'delivery':
            return jsonify({'earnings': 0})
        doc = delivery_col.find_one({"email": session.get('user')})
        return jsonify({'earnings': doc.get("earnings", 0) if doc else 0})

    # ----------- Update Partner Location -----------
    @delivery_bp.route('/api/update_location', methods=['POST'])
    def update_location():
        if 'user' not in session or session.get('role') != 'delivery':
            return jsonify({'success': False, 'message': 'Unauthorized'}), 403
        data = request.json
        lat = data.get("lat")
        lng = data.get("lng")
        if lat is None or lng is None:
            return jsonify({'success': False, 'message': 'Invalid data'}), 400

        delivery_col.update_one(
            {"email": session.get('user')},
            {
                "$set": {
                    "current_lat": lat,
                    "current_lng": lng,
                    "last_updated": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
            }
        )
        return jsonify({'success': True, 'message': 'Location updated'})

    # ----------- Get Partner Location by email -----------
    @delivery_bp.route('/api/get_partner_location/<email>')
    def get_partner_location(email):
        doc = delivery_col.find_one({"email": email})
        if not doc or 'current_lat' not in doc or 'current_lng' not in doc:
            return jsonify({'lat': None, 'lng': None, 'last_updated': None})
        return jsonify({
            'lat': doc['current_lat'],
            'lng': doc['current_lng'],
            'last_updated': doc.get('last_updated')
        })

    # Register the blueprint
    app.register_blueprint(delivery_bp)
