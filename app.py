import numpy as np
import skfuzzy as fuzz
from skfuzzy import control as ctrl
import requests
from flask import Flask, render_template, request, jsonify
from datetime import datetime

app = Flask(__name__)

# ==========================================
# 1. HỆ THỐNG LOGIC MỜ (Đổi thành Đơn giá/km)
# ==========================================
distance = ctrl.Antecedent(np.arange(0, 101, 1), 'distance')
fare = ctrl.Consequent(np.arange(10, 26, 1), 'fare')

distance['near'] = fuzz.trimf(distance.universe, [0, 0, 10])
distance['medium'] = fuzz.trimf(distance.universe, [5, 25, 45])
distance['far'] = fuzz.trimf(distance.universe, [30, 100, 100])

fare['low'] = fuzz.trimf(fare.universe, [10, 10, 14])
fare['medium'] = fuzz.trimf(fare.universe, [13, 16, 19])
fare['high'] = fuzz.trimf(fare.universe, [18, 25, 25])

rules = [
    ctrl.Rule(distance['near'], fare['high']),
    ctrl.Rule(distance['medium'], fare['medium']),
    ctrl.Rule(distance['far'], fare['low'])
]
fuzzy_system = ctrl.ControlSystem(rules) 

# ==========================================
# 2. HÀM GỌI API LỘ TRÌNH
# ==========================================
def get_route_osrm(s_lat, s_lon, e_lat, e_lon):
    url = f"http://router.project-osrm.org/route/v1/driving/{s_lon},{s_lat};{e_lon},{e_lat}?overview=full&geometries=geojson"
    try:
        response = requests.get(url, timeout=5).json()
        path = response['routes'][0]['geometry']['coordinates']
        path_lat_lon = [[coord[1], coord[0]] for coord in path]
        distance_km = response['routes'][0]['distance'] / 1000
        return path_lat_lon, distance_km
    except:
        return [[s_lat, s_lon], [e_lat, e_lon]], 0

def get_weather(lat, lon):
    try:
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=relative_humidity_2m,rain"
        res = requests.get(url).json()
        return res['current']['relative_humidity_2m'], res['current']['rain']
    except: return 60, 0

# ==========================================
# 3. XỬ LÝ TÍNH CƯỚC
# ==========================================
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/calculate_fare', methods=['POST'])
def calculate_fare():
    data = request.json
    s_lat, s_lon = float(data['s_lat']), float(data['s_lon'])
    e_lat, e_lon = float(data['e_lat']), float(data['e_lon'])
    he_so_goc = float(data['he_so'])

    # 1. QUY ĐỔI HỆ SỐ & CƯỚC MỞ CỬA (Chuẩn Taxi thật)
    if he_so_goc == 1.0: # Xe máy
        real_he_so = 0.4
        min_fare = 15000
    elif he_so_goc == 1.5: # Taxi 4 chỗ
        real_he_so = 1.0
        min_fare = 20000
    else: # Taxi 7 chỗ
        real_he_so = 1.3
        min_fare = 30000

    # Lấy đường đi thực tế
    path, dist_km = get_route_osrm(s_lat, s_lon, e_lat, e_lon)
    if dist_km == 0: 
        dist_km = ((s_lat - e_lat)**2 + (s_lon - e_lon)**2)**0.5 * 111 * 1.3

    # 2. KHẮC PHỤC LỖI KẸT BỘ NHỚ (CACHE LOCK)
    fare_sim = ctrl.ControlSystemSimulation(fuzzy_system)
    fare_sim.input['distance'] = min(float(dist_km), 100)
    fare_sim.compute()
    
    # Ép kiểu float chống sập web
    price_per_km = float(fare_sim.output['fare']) * 1000
    
    # 3. CÔNG THỨC TAXI CHUẨN (Khắc phục lỗi trùng giá)
    if dist_km <= 1.0:
        base_price = min_fare
    else:
        base_price = min_fare + price_per_km * (dist_km - 1.0) * real_he_so
    
    # Phụ phí giờ cao điểm & thời tiết
    hour = datetime.now().hour
    peak_fee = base_price * 0.25 if (7 <= hour <= 9 or 16 <= hour <= 19) else 0
    
    hum, rain = get_weather(s_lat, s_lon)
    weather_fee = base_price * 0.2 if (rain > 0 or hum > 85) else 0

    # AI Tự động phát mã giảm giá
    discount_fee = 0
    discount_code = ""
    if rain > 0 or hum > 85:
        discount_fee = 10000
        discount_code = "MUA_10K"

    # Làm tròn số nguyên đồng bộ để không bị lệch bill
    base_price = int(round(base_price, -2))
    peak_fee = int(round(peak_fee, -2))
    weather_fee = int(round(weather_fee, -2))
    
    total_price = max(0, base_price + peak_fee + weather_fee - discount_fee)

    # CHỈ GIỮ LẠI 1 LỆNH RETURN JSONIFY
    return jsonify({
        "path": path,
        "dist": round(float(dist_km), 2),
        "breakdown": {
            "base": base_price,
            "peak": peak_fee,
            "weather": weather_fee,
            "discount": discount_fee,
            "discount_code": discount_code,
            "total": total_price
        }
    })

if __name__ == '__main__':
    app.run(debug=True)

