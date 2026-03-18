from flask import Flask, render_template, Response, jsonify, request, redirect, url_for, session, send_file
import cv2
import os
import pyodbc
import face_recognition
import numpy as np
from datetime import datetime
from openpyxl import Workbook
import io

app = Flask(__name__)
app.secret_key = "vuductu_key_2026"

# ================= 1. KẾT NỐI DATABASE =================
def get_db_connection():
    return pyodbc.connect(
        "DRIVER={ODBC Driver 17 for SQL Server};"
        "SERVER=DESKTOP-5RMPV43;"
        "DATABASE=Thuctap;"
        "Trusted_Connection=yes;"
    )

# ================= 2. NẠP DỮ LIỆU KHUÔN MẶT =================
known_face_encodings = []
known_face_names = []

def load_dataset():
    global known_face_encodings, known_face_names
    known_face_encodings.clear()
    known_face_names.clear()
    dataset_path = "dataset"
    if not os.path.exists(dataset_path): os.makedirs(dataset_path)
    
    for ms_sv in os.listdir(dataset_path):
        person_dir = os.path.join(dataset_path, ms_sv)
        if os.path.isdir(person_dir):
            for img in os.listdir(person_dir):
                img_path = os.path.join(person_dir, img)
                try:
                    image = face_recognition.load_image_file(img_path)
                    enc = face_recognition.face_encodings(image)
                    if enc:
                        known_face_encodings.append(enc[0])
                        known_face_names.append(ms_sv)
                except: continue
    print(f"Hệ thống: Đã nạp {len(known_face_names)} mẫu khuôn mặt.")

load_dataset()

# ================= 3. BIẾN ĐIỀU KHIỂN =================
is_running = False
current_buoi_id = None
attendance_list = [] 

# ================= 4. XỬ LÝ CAMERA =================
def gen_frames():
    global is_running, attendance_list, current_buoi_id
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)

    while is_running:
        success, frame = cap.read()
        if not success: break

        # Resize để tăng tốc độ nhận diện
        small = cv2.resize(frame, (0,0), fx=0.25, fy=0.25)
        rgb_small = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)

        locations = face_recognition.face_locations(rgb_small)
        encodings = face_recognition.face_encodings(rgb_small, locations)

        for (top, right, bottom, left), face_enc in zip(locations, encodings):
            name_to_draw = "Unknown"
            if known_face_encodings:
                distances = face_recognition.face_distance(known_face_encodings, face_enc)
                best_index = np.argmin(distances)

                if distances[best_index] < 0.45:
                    ms_sv = known_face_names[best_index]
                    user_info = next((x for x in attendance_list if x["ms"] == ms_sv), None)
                    
                    if not user_info:
                        conn = get_db_connection(); cursor = conn.cursor()
                        cursor.execute("SELECT SinhvienId, Hoten, Lop FROM Sinhvien WHERE Masinhvien=?", (ms_sv,))
                        row = cursor.fetchone()
                        if row:
                            s_id, s_name, s_lop = row[0], row[1], row[2]
                            name_to_draw = s_name
                            
                            # Ghi nhận vào SQL
                            cursor.execute("SELECT 1 FROM Diemdanh WHERE BuoihocId=? AND SinhvienId=?", (current_buoi_id, s_id))
                            if not cursor.fetchone():
                                cursor.execute("INSERT INTO Diemdanh (BuoihocId, SinhvienId, Thoigiandiemdanh, Trangthai) VALUES (?, ?, GETDATE(), N'Có mặt')", (current_buoi_id, s_id))
                                conn.commit()
                            
                            attendance_list.append({
                                "ms": ms_sv, "name": s_name, "lop": s_lop,
                                "time": datetime.now().strftime("%H:%M:%S")
                            })
                        conn.close()
                    else:
                        name_to_draw = user_info["name"]

            # Vẽ khung
            top*=4; right*=4; bottom*=4; left*=4
            cv2.rectangle(frame, (left, top), (right, bottom), (0, 255, 0), 2)
            cv2.putText(frame, name_to_draw, (left, top-10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

        ret, buffer = cv2.imencode(".jpg", frame)
        yield (b"--frame\r\n" b"Content-Type: image/jpeg\r\n\r\n" + buffer.tobytes() + b"\r\n")
    cap.release()

# ================= 5. ROUTES CHÍNH =================
@app.route("/")
def index():
    if "user_id" not in session: return render_template("index.html", view="login")
    conn = get_db_connection(); cursor = conn.cursor()
    if session["role"] == "giaovien":
        cursor.execute("SELECT Hoten, Bomon FROM Giaovien WHERE TaikhoanId=?", (session["user_id"],))
        gv_info = cursor.fetchone()
        cursor.execute("SELECT b.BuoihocId, m.Tenmonhoc, b.Ngayhoc, b.Phonghoc FROM Buoihoc b JOIN Monhoc m ON b.MonhocId=m.MonhocId JOIN Giaovien g ON m.GiaovienId=g.GiaovienId WHERE g.TaikhoanId=?", (session["user_id"],))
        buoi_hocs = cursor.fetchall()
        conn.close()
        return render_template("index.html", view="giaovien", gv_info=gv_info, buoi_hocs=buoi_hocs)
    else:
        cursor.execute("SELECT SinhvienId, Masinhvien, Hoten, Lop FROM Sinhvien WHERE TaikhoanId=?", (session["user_id"],))
        sv = cursor.fetchone()
        cursor.execute("SELECT m.Tenmonhoc, b.Ngayhoc, d.Thoigiandiemdanh, d.Trangthai FROM Diemdanh d JOIN Buoihoc b ON d.BuoihocId=b.BuoihocId JOIN Monhoc m ON b.MonhocId=m.MonhocId WHERE d.SinhvienId=? ORDER BY d.Thoigiandiemdanh DESC", (sv[0],))
        history = cursor.fetchall()
        conn.close()
        return render_template("index.html", view="sinhvien", sv=sv, history=history)

@app.route("/start_session/<int:buoi_id>")
def start_session(buoi_id):
    global is_running, current_buoi_id, attendance_list
    is_running, current_buoi_id, attendance_list = True, buoi_id, []
    # Tải lại danh sách đã điểm danh từ trước trong buổi này
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute("""
        SELECT s.Masinhvien, s.Hoten, s.Lop, CONVERT(VARCHAR, d.Thoigiandiemdanh, 108) 
        FROM Diemdanh d JOIN Sinhvien s ON d.SinhvienId = s.SinhvienId WHERE d.BuoihocId = ?
    """, (buoi_id,))
    for r in cursor.fetchall():
        attendance_list.append({"ms": r[0], "name": r[1], "lop": r[2], "time": r[3]})
    conn.close()
    return jsonify({"status": "started"})

@app.route("/get_attendance")
def get_attendance():
    return jsonify(attendance_list)

@app.route("/video_feed")
def video_feed():
    return Response(gen_frames(), mimetype="multipart/x-mixed-replace; boundary=frame")

# ================= 6. XUẤT EXCEL (NEW) =================
@app.route("/export_excel/<int:buoi_id>")
def export_excel(buoi_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Truy vấn thông tin chung của buổi học (Môn, GV, Ngày)
    info_query = """
        SELECT m.Tenmonhoc, g.Hoten, b.Ngayhoc, b.Phonghoc
        FROM Buoihoc b
        JOIN Monhoc m ON b.MonhocId = m.MonhocId
        JOIN Giaovien g ON m.GiaovienId = g.GiaovienId
        WHERE b.BuoihocId = ?
    """
    cursor.execute(info_query, (buoi_id,))
    b_info = cursor.fetchone() # Lấy thông tin chung

    # 2. Truy vấn danh sách sinh viên đã điểm danh
    list_query = """
        SELECT s.Masinhvien, s.Hoten, s.Lop, d.Thoigiandiemdanh 
        FROM Diemdanh d 
        JOIN Sinhvien s ON d.SinhvienId = s.SinhvienId 
        WHERE d.BuoihocId = ? 
        ORDER BY d.Thoigiandiemdanh ASC
    """
    cursor.execute(list_query, (buoi_id,))
    rows = cursor.fetchall()
    conn.close()

    # 3. Khởi tạo file Excel
    wb = Workbook()
    ws = wb.active
    ws.title = "Bao Cao Diem Danh"

    # 4. Ghi thông tin tiêu đề (Header)
    ws.append(["DANH SÁCH ĐIỂM DANH SINH VIÊN"])
    ws.append([f"Môn học: {b_info[0]}"])
    ws.append([f"Giáo viên: {b_info[1]}"])
    ws.append([f"Ngày học: {b_info[2]}", f"Phòng: {b_info[3]}"])
    ws.append([]) # Dòng trống để ngăn cách

    # 5. Ghi tiêu đề bảng
    ws.append(["STT", "Mã Sinh Viên", "Họ Tên", "Lớp", "Giờ điểm danh"])

    # 6. Ghi dữ liệu sinh viên
    for i, r in enumerate(rows, 1):
        # r[3] là Thoigiandiemdanh (kiểu datetime trong SQL)
        ws.append([i, r[0], r[1], r[2], r[3].strftime("%H:%M:%S")])

    # Tùy chỉnh độ rộng cột sơ bộ cho đẹp
    ws.column_dimensions['B'].width = 15
    ws.column_dimensions['C'].width = 25
    ws.column_dimensions['D'].width = 15
    ws.column_dimensions['E'].width = 20

    # Xuất file
    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    
    filename = f"DiemDanh_{b_info[0].replace(' ', '_')}_{datetime.now().strftime('%d%m%Y')}.xlsx"
    return send_file(out, as_attachment=True, download_name=filename)

@app.route("/update_face_file", methods=["POST"])
def update_face_file():
    if "user_id" not in session: return jsonify({"status": "error"})
    file = request.files['file']
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute("SELECT Masinhvien FROM Sinhvien WHERE TaikhoanId=?", (session["user_id"],))
    ms_sv = cursor.fetchone()[0]; conn.close()
    path = os.path.join("dataset", ms_sv)
    if not os.path.exists(path): os.makedirs(path)
    file.save(os.path.join(path, f"{ms_sv}.jpg"))
    load_dataset()
    return jsonify({"status": "success"})

@app.route("/stop_session")
def stop_session():
    global is_running
    is_running = False
    return jsonify({"status": "stopped"})

@app.route("/login", methods=["POST"])
def login():
    username, password = request.form["username"], request.form["password"]
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute("SELECT TaikhoanId, Vaitro FROM Taikhoan WHERE Tendangnhap=? AND Matkhau=? AND Trangthai=1", (username, password))
    user = cursor.fetchone(); conn.close()
    if user:
        session["user_id"], session["role"] = user[0], user[1].strip().lower()
        return redirect(url_for("index"))
    return render_template("index.html", view="login", error="Sai tài khoản hoặc mật khẩu")

@app.route("/logout")
def logout():
    global is_running
    is_running = False
    session.clear()
    return redirect(url_for("index"))

if __name__ == "__main__":
    app.run(debug=True, use_reloader=False)