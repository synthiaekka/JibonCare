from flask import Blueprint, request, jsonify, session, render_template, redirect
from math import radians, cos, sin, sqrt, atan2
from datetime import datetime
from bson import ObjectId

delivery_bp = Blueprint('delivery', __name__)

# ========== Haversine Function ==========
def haversine(lat1, lng1, lat2, lng2):
    R = 6371.0
    lat1, lng1, lat2, lng2 = map(radians, [lat1, lng1, lat2, lng2])
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    a = sin(dlat/2)**2 + cos(lat1)*cos(lat2)*sin(dlng/2)**2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return R * c

# ========== Dashboard Page ==========
@delivery_bp.route('/delivery-dashboard')
def delivery_dashboard():
    if 'user' not in session or session.get('role') != 'delivery':
        return redirect('/login')
    return render_template('del.html')

# ========== Initialize All Delivery Routes ==========
def init_delivery_routes(app, db):
    delivery_col = db['delivery_partners']
    orders_col = db['orders']

    # ========== Get Nearby Unassigned Orders ==========
    @delivery_bp.route('/api/get_available_orders')
    def get_available_orders():
        lat = request.args.get('lat', type=float)
        lng = request.args.get('lng', type=float)
        print(f"[DEBUG] /api/get_available_orders lat={lat}, lng={lng}")
        if lat is None or lng is None:
            print("[DEBUG] Missing lat/lng")
            return jsonify({'orders': []})

        unassigned_orders = list(orders_col.find({"delivery_status": "pending"}))
        print(f"[DEBUG] Pending orders found: {len(unassigned_orders)}")
        nearby_orders = []

        for order in unassigned_orders:
            dest = order.get("location")
            if not (isinstance(dest, dict)
                    and isinstance(dest.get('lat'), (int, float))
                    and isinstance(dest.get('lng'), (int, float))):
                print(f"[DEBUG] Skipping order {order.get('_id')}, bad location: {dest}")
                continue
            dist = haversine(lat, lng, dest['lat'], dest['lng'])
            print(f"[DEBUG] Order {order.get('_id')} => {dist:.2f}km away")
            if dist <= 5:
                order["_id"] = str(order["_id"])
                nearby_orders.append(order)

        print(f"[DEBUG] Returning {len(nearby_orders)} nearby orders")
        return jsonify({'orders': nearby_orders})

    # ========== Accept an Order ==========
    @delivery_bp.route('/api/accept_order/<order_id>', methods=['POST'])
    def accept_order(order_id):
        if 'user' not in session or session.get('role') != 'delivery':
            return jsonify({'success': False, 'message': 'Unauthorized'}), 403

        try:
            oid = ObjectId(order_id)
        except:
            return jsonify({'success': False, 'message': 'Invalid order ID'}), 400

        result = orders_col.update_one(
            {"_id": oid, "delivery_status": "pending"},
            {
                "$set": {
                    "delivery_status": "assigned",
                    "assigned_to": session.get('user'),
                    "assigned_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
            }
        )

        if result.modified_count == 0:
            return jsonify({'success': False, 'message': 'Order not available'}), 400

        return jsonify({'success': True, 'message': 'Order accepted'})

    # ========== Get Current Assigned Order ==========
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
        return jsonify({'order': order})

    # ========== Mark Order as Delivered ==========
    @delivery_bp.route('/api/complete_order/<order_id>', methods=['POST'])
    def complete_order(order_id):
        if 'user' not in session or session.get('role') != 'delivery':
            return jsonify({'success': False, 'message': 'Unauthorized'}), 403
        try:
            oid = ObjectId(order_id)
        except:
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
            return jsonify({'success': False, 'message': 'Could not mark delivered (wrong order?)'}), 400
        delivery_col.update_one(
            {"email": session.get('user')},
            {"$inc": {"earnings": 30}}  # ₹30 per delivery
        )
        return jsonify({'success': True, 'message': 'Order marked as delivered'})

    # ========== Get Earnings ==========
    @delivery_bp.route('/api/get_earnings')
    def get_earnings():
        if 'user' not in session or session.get('role') != 'delivery':
            return jsonify({'earnings': 0})
        doc = delivery_col.find_one({"email": session.get('user')})
        return jsonify({'earnings': doc.get("earnings", 0) if doc else 0})

    # ========== Update Delivery Partner's Location ==========
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

    # Register blueprint after all routes
    app.register_blueprint(delivery_bp)
