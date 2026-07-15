import cv2

# เปิดกล้อง หรือรูปภาพที่จะใช้
cap = cv2.VideoCapture(0) 
ret, frame = cap.read()
frame = cv2.flip(frame, 1) # ถ้าใน app.py เราพลิกภาพ ตอนหาพิกัดก็ต้องพลิกด้วย

def get_mouse_clicks(event, x, y, flags, param):
    if event == cv2.EVENT_LBUTTONDOWN:
        print(f"คลิกที่พิกัด: x={x}, y={y}")
        # วาดวงกลมเล็กๆ ตรงที่คลิกเพื่อเตือนความจำ
        cv2.circle(frame, (x, y), 5, (0, 0, 255), -1)
        cv2.imshow("Get Coordinates", frame)

cv2.imshow("Get Coordinates", frame)
cv2.setMouseCallback("Get Coordinates", get_mouse_clicks)

print("--- วิธีใช้งาน ---")
print("คลิกเมาส์ 'มุมซ้ายบน' และ 'มุมขวาล่าง' ของช่องจอดแต่ละช่อง เพื่อดูตัวเลขใน Terminal")
print("กดปุ่ม ESC เพื่อออก")

cv2.waitKey(0)
cv2.destroyAllWindows()