from flask import Flask, render_template, jsonify, request
import cv2
import base64
import json
import os
from ultralytics import YOLO

# 1. สร้างแอปพลิเคชัน Flask เพื่อทำหน้าที่เป็น Web Server รับส่งข้อมูลกับหน้าเว็บ
app = Flask(__name__)

# 2. โหลดโมเดล YOLOv8 
# ใช้เวอร์ชัน Nano ('yolov8n.pt') เพราะมีขนาดเล็ก โหลดไว และทำงานได้รวดเร็วเหมาะกับคอมพิวเตอร์ทั่วไป
model = YOLO('yolov8n.pt')

# ==============================================================================
# 🟢 3. ตั้งค่าไฟล์สื่อ (Data Sources) สำหรับ 3 โซน
# ==============================================================================
MEDIA_PATHS = {
    "zone1": "abc.jpg",  # โซน 1: ใช้รูปภาพนิ่ง (เหมาะสำหรับทดสอบ)
    "zone2": "vdo1.mp4",        # โซน 2: ใช้วิดีโอ .mp4 (จำลองสถานการณ์จริง)
    "zone3": 0                  # โซน 3: ใช้เลข 0 เพื่อสั่งให้ OpenCV ดึงภาพจากกล้อง Webcam ตัวแรกของเครื่อง
}

# กำหนดชื่อไฟล์สำหรับเป็นฐานข้อมูล (Database) ขนาดเล็ก เพื่อจำพิกัดช่องจอด
ZONES_FILE = 'zones.json'

#  ใช้เก็บสถานะการเปิดกล้องหรือวิดีโอ (VideoCapture Object) 
# เพื่อให้กล้อง "เปิดค้างไว้" ตลอดเวลา ไม่ต้องเสียเวลาเปิดใหม่ทุกๆ 0.5 วินาที
video_caps = {}

# 4. ฟังก์ชันสำหรับโหลดพิกัดช่องจอดจากไฟล์ตอนเริ่มต้นเซิร์ฟเวอร์
def load_zones():
    if os.path.exists(ZONES_FILE):
        with open(ZONES_FILE, 'r') as f:
            data = json.load(f)
            # ถ้ามีไฟล์อยู่แล้ว เช็คให้แน่ใจว่ามีโครงสร้างครบทั้ง 3 โซน
            if "zone1" not in data: data["zone1"] = {}
            if "zone2" not in data: data["zone2"] = {}
            if "zone3" not in data: data["zone3"] = {}
            return data
    # ถ้ายังไม่มีไฟล์ (รันครั้งแรก) ให้สร้างค่าว่างๆ รอไว้
    return {"zone1": {}, "zone2": {}, "zone3": {}}

# โหลดข้อมูลใส่ตัวแปร PARKING_SPACES ทันทีที่เซิร์ฟเวอร์เริ่มทำงาน
PARKING_SPACES = load_zones()

# ==============================================================================
# 🟢 5. API Routes (จุดเชื่อมต่อระหว่างหน้าเว็บกับเซิร์ฟเวอร์)
# ==============================================================================

# 5.1 Route หน้าแรก: เมื่อเข้าเว็บ จะส่งไฟล์ index.html ไปแสดงผล
@app.route('/')
def index():
    return render_template('index.html')

# 5.2 API สำหรับรับพิกัดช่องจอดที่แอดมิน "วาดและกดบันทึก" จากหน้าเว็บ
@app.route('/update_zones', methods=['POST'])
def update_zones():
    global PARKING_SPACES
    data = request.json # รับข้อมูลพิกัด (JSON) ที่ส่งมาจาก JavaScript
    zone_id = data.get('zone_id', 'zone1') # เช็คว่าเซฟของโซนไหน
    
    # นำพิกัดใหม่มาอัปเดตทับในหน่วยความจำ (RAM)
    PARKING_SPACES[zone_id] = data.get('zones', {})
    
    # นำหน่วยความจำไปเขียนทับลงไฟล์ (Harddisk) เพื่อไม่ให้ข้อมูลหายตอนปิดโปรแกรม
    with open(ZONES_FILE, 'w') as f:
        json.dump(PARKING_SPACES, f)
        
    return jsonify({"status": "success", "message": f"บันทึกช่องจอด {zone_id} เรียบร้อย!"})

# 5.3 API หลัก: การสแกนภาพและประมวลผล AI (ถูกหน้าเว็บเรียกทุกๆ 0.5 วินาที)
@app.route('/scan')
def scan_parking():
    zone_id = request.args.get('zone', 'zone1') # รับค่าว่าหน้าเว็บกำลังขอดูโซนไหน
    media_path = MEDIA_PATHS.get(zone_id)
    
    # ตรวจสอบว่าไฟล์รูป/วิดีโอมีอยู่จริงไหม (กันโปรแกรม Error ทะลุ)
    if media_path is None or (isinstance(media_path, str) and not os.path.exists(media_path)):
         return jsonify({"error": f"ไม่พบไฟล์หรือกล้อง: {media_path} กรุณาเช็คอีกครั้ง"}), 500

    # ---------------------------------------------------------
    # 🟢 ขั้นตอนที่ A: เตรียมภาพ (ดึงเฟรมจากรูป/วิดีโอ/กล้อง)
    # ---------------------------------------------------------
    if isinstance(media_path, int) or str(media_path) == "0":
        # กรณี A1: ถ้าเป็นกล้อง Webcam
        if zone_id not in video_caps:
            cap = cv2.VideoCapture(int(media_path)) # สั่งเปิดกล้อง
            if not cap.isOpened():
                return jsonify({"error": "เปิดกล้อง Webcam ไม่ได้"}), 500
            video_caps[zone_id] = cap
            
        cap = video_caps[zone_id]
        
        # เทคนิคเคลียร์ Buffer: ดึงภาพเก่าทิ้ง 4 เฟรม เพื่อให้ได้ภาพสดใหม่ที่สุด (Real-time ไม่ดีเลย์)
        for _ in range(4):
            cap.grab() 
        ret, frame = cap.read() # อ่านภาพเฟรมปัจจุบันมาใช้งาน
        
        if not ret or frame is None:
             return jsonify({"error": "อ่านภาพจากกล้อง Webcam ไม่ได้"}), 500

    elif isinstance(media_path, str) and media_path.lower().endswith(('.mp4', '.avi', '.mov')):
        # กรณี A2: ถ้าเป็นวิดีโอ (.mp4)
        if zone_id not in video_caps:
            cap = cv2.VideoCapture(media_path)
            if not cap.isOpened():
                return jsonify({"error": f"เปิดไฟล์วิดีโอไม่ได้: {media_path}"}), 500
            video_caps[zone_id] = cap
            
        cap = video_caps[zone_id]
        
        # เทคนิค Fast-Forward: อ่านข้ามไป 3 เฟรม เพื่อให้ภาพเล่นเร็วทันการประมวลผล
        for _ in range(3):
            ret, frame = cap.read()
            if not ret: 
                break # ถ้ายกเลิกแปลว่าวิดีโอจบแล้ว
        
        # เทคนิค Loop Video: ถ้ายกเลิก/วิดีโอจบ ให้ตั้งค่าเฟรมกลับไปที่ 0 (เริ่มเล่นใหม่)
        if not ret or frame is None:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret, frame = cap.read()
            
        if frame is None:
             return jsonify({"error": f"อ่านไฟล์วิดีโอไม่ได้: {media_path}"}), 500
             
    else:
        # กรณี A3: ถ้าเป็นรูปภาพนิ่ง (.jpg)
        frame = cv2.imread(media_path)

    if frame is None:
        return jsonify({"error": f"อ่านไฟล์ไม่ได้: {media_path}"}), 500
    
    # เก็บความกว้าง/ยาวของภาพจริงไว้ส่งให้หน้าเว็บคำนวณสเกล
    img_height, img_width = frame.shape[:2]

    # ---------------------------------------------------------
    # 🟢 ขั้นตอนที่ B: ประมวลผลด้วย AI (YOLOv8)
    # ---------------------------------------------------------
    # สั่ง AI หากล่องรอบวัตถุ (ตั้ง conf=0.05 คือมั่นใจแค่ 5% ก็ให้จับเป็นรถ ป้องกันปัญหารถโดนบัง)
    results = model(frame, conf=0.05, verbose=False)
    
    car_centers = [] # ลิสต์เก็บพิกัด "จุดกึ่งกลาง" ของรถทุกคัน
    for r in results:
        for box in r.boxes:
            # ดึงพิกัดซ้ายบนและขวาล่างของกรอบรถที่ AI เจอ
            cx1, cy1, cx2, cy2 = map(int, box.xyxy[0])
            
            # คำนวณหา "จุดศูนย์กลาง" (Centroid) แกน x และ y ของรถ
            # (ใช้จุดศูนย์กลางแทนขอบรถ จะแม่นยำกว่าเวลารถจอดเบียดกัน)
            center_x = (cx1 + cx2) // 2
            center_y = (cy1 + cy2) // 2
            car_centers.append((center_x, center_y))
            
            # วาดจุดสีฟ้าที่กึ่งกลางตัวรถบนรูป เพื่อให้มองเห็นง่ายๆ
            cv2.circle(frame, (center_x, center_y), 4, (255, 200, 0), -1)

    # ---------------------------------------------------------
    # 🟢 ขั้นตอนที่ C: คำนวณการทับซ้อนและวาดสถานะช่องจอด
    # ---------------------------------------------------------
    status_report = {} # เก็บสถานะของแต่ละช่อง (VACANT/OCCUPIED)
    
    # ดึงพิกัดกรอบที่เราวาดไว้ในโซนนี้ออกมาทั้งหมด
    current_zone_spaces = PARKING_SPACES.get(zone_id, {})
    total_spaces = len(current_zone_spaces)
    occupied_count = 0

    # วนลูปเช็คช่องจอดทีละช่อง
    for space_id, coords in current_zone_spaces.items():
        px1, py1, px2, py2 = coords # ขอบซ้ายบน(px1,py1) และ ขวาล่าง(px2,py2) ของช่องจอด
        is_occupied = False
        
        # นำจุดศูนย์กลางของรถทุกคันมาเช็ค
        for cx, cy in car_centers:
            # ถ้าแกน X และ Y ของรถ ตกเข้าไปอยู่ในกรอบสี่เหลี่ยมช่องจอด
            if px1 < cx < px2 and py1 < cy < py2:
                is_occupied = True
                break # ถือว่าช่องนี้มีรถจอดแล้ว ให้หยุดเช็คคันอื่นแล้วข้ามไปช่องถัดไปเลย
                
        # เลือกระบายสีตามสถานะ (OpenCV ใช้ระบบสี BGR แทน RGB)
        if is_occupied:
            color = (0, 0, 255) # สีแดง (ไม่ว่าง)
            status_report[space_id] = "OCCUPIED"
            occupied_count += 1
            
            # เทคนิคการระบายสีโปร่งแสง (Alpha Blending)
            overlay = frame.copy()
            cv2.rectangle(overlay, (px1, py1), (px2, py2), color, -1) # วาดสีแดงทึบลงบนแผ่นใส
            cv2.addWeighted(overlay, 0.3, frame, 0.7, 0, frame) # ผสมสีแผ่นใส 30% ทับบนรูปจริง 70%
        else:
            color = (0, 255, 0) # สีเขียว (ว่าง)
            status_report[space_id] = "VACANT"
            
        # วาดเส้นขอบช่องจอด และ ป้ายชื่อช่อง (เช่น P1, P2)
        cv2.rectangle(frame, (px1, py1), (px2, py2), color, 2)
        cv2.rectangle(frame, (px1, py1-18), (px1+35, py1), color, -1)
        cv2.putText(frame, space_id, (px1 + 3, py1 - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255,255,255), 1, cv2.LINE_AA)

    # ---------------------------------------------------------
    # 🟢 ขั้นตอนที่ D: แปลงรูปภาพส่งกลับไปให้หน้าเว็บ
    # ---------------------------------------------------------
    # บีบอัดเฟรมภาพจาก OpenCV ให้กลายเป็นไฟล์ .jpg
    _, buffer = cv2.imencode('.jpg', frame)
    # แปลงไฟล์รูปภาพให้เป็นสตริงข้อความ (Base64) เพื่อส่งผ่านระบบ API (อินเทอร์เน็ต)
    img_base64 = f"data:image/jpeg;base64,{base64.b64encode(buffer).decode('utf-8')}"
    
    vacant_count = total_spaces - occupied_count
    
    # ส่งก้อนข้อมูล (JSON) ทั้งรูปภาพ สถิติ และสถานะแต่ละช่อง กลับไปให้ JavaScript บนหน้าเว็บอัปเดตหน้าจอ
    return jsonify({
        "image": img_base64,
        "img_width": img_width,
        "img_height": img_height,
        "summary": {
            "total": total_spaces,
            "occupied": occupied_count,
            "vacant": vacant_count
        },
        "details": status_report
    })

# คำสั่งสำหรับเริ่มรันเซิร์ฟเวอร์
if __name__ == '__main__':
    app.run(debug=True, port=5000)