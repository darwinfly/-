import os
import re
import time
import json
import sqlite3
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, session, send_from_directory
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv

# 加載環境變數 (.env)
load_dotenv()

app = Flask(__name__)

# 從環境變數讀取 Flask Secret Key，若無則使用開發預設值
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "product_intro_secret_key")

# 讀取雙模式切換變數 (預設為 sqlite 與 local)
DB_MODE = os.environ.get("DB_MODE", "sqlite").lower()
STORAGE_MODE = os.environ.get("STORAGE_MODE", "local").lower()
GCS_BUCKET_NAME = os.environ.get("GCS_BUCKET_NAME")

# 設定本地資料庫與上傳目錄路徑
DATABASE = os.path.join(app.root_path, 'product_intro.db')
UPLOAD_FOLDER = os.path.join(app.root_path, 'static', 'uploads')
IMAGE_FOLDER = os.path.join(app.root_path, 'static', 'images')
ALLOWED_PDF_EXTENSIONS = {'pdf'}
ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'gif'}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 限制最大 10MB

# 確保本地目錄存在
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(IMAGE_FOLDER, exist_ok=True)

# 讀取版本號
VERSION_FILE = os.path.join(app.root_path, 'version.txt')
current_version = "v1.4.0"
if os.path.exists(VERSION_FILE):
    try:
        with open(VERSION_FILE, 'r', encoding='utf-8') as f:
            current_version = f.read().strip()
    except Exception:
        pass

def allowed_file(filename, allowed_extensions):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions

def slugify(text):
    """將名稱轉換為安全的 ID slug"""
    text = text.lower().strip()
    text = re.sub(r'[\s\-]+', '_', text)
    text = re.sub(r'[^\w]', '', text)
    return text or f"product_{int(time.time())}"

# ==========================================================================
# SQLite 資料庫 Helper 函式
# ==========================================================================
def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

# ==========================================================================
# 預設產品資料（首次初始化時寫入資料庫）
# ==========================================================================
DEFAULT_PRODUCTS = [
    {
        "id": "novabuds_pro",
        "name": "NovaBuds Pro",
        "price": "NT$ 2,980",
        "image_url": "",
        "image_local": "earbuds.png",
        "summary": "主動降噪無線藍牙耳機，體驗極致純淨的音質與絕佳的配戴舒適度。",
        "specs": {
            "藍牙版本": "Bluetooth 5.3",
            "電池續航": "單次 8 小時 / 搭配充電盒達 30 小時",
            "降噪技術": "ANC 主動降噪 + ENC 通話降噪 (高達 45dB 降噪深度)",
            "防水等級": "IPX4 生活防汗防雨",
            "音訊解碼": "AAC, SBC, LDAC 高解析解碼",
            "重量": "單耳 4.5g / 充電盒 42g"
        }
    },
    {
        "id": "auraview_mini",
        "name": "AuraView Mini",
        "price": "NT$ 12,500",
        "image_url": "",
        "image_local": "projector.png",
        "summary": "可隨身攜帶的智慧投影機，內建 Android TV，隨處打造專屬的掌上影院。",
        "specs": {
            "投影解析度": "真實 1080P (支援 4K 解碼)",
            "投影亮度": "800 ANSI 流明",
            "投影尺寸": "40 - 120 吋 (投射比 1.2:1)",
            "智慧系統": "內建 Android TV 11.0 (支援 Netflix, YouTube 等)",
            "對焦校正": "全自動對焦 + 四角梯形自動校正",
            "內建喇叭": "5W x 2 雙聲道立體環繞音效",
            "連接埠": "HDMI 2.0, USB 2.0, 3.5mm 音訊孔, Wi-Fi 6, 藍牙 5.0"
        }
    },
    {
        "id": "zenithwatch_2",
        "name": "ZenithWatch 2",
        "price": "NT$ 5,800",
        "image_url": "",
        "image_local": "smartwatch.png",
        "summary": "全天候健康與運動監測的智慧手錶，配備 AMOLED 螢幕與強大續航力。",
        "specs": {
            "螢幕規格": "1.43 吋 AMOLED 觸控螢幕 (支援 Always-on 顯示)",
            "健康監測": "24小時心率、SpO2 血氧飽和度、睡眠追蹤、壓力指數",
            "運動模式": "120+ 種運動模式 (自動識別跑步、健走、單車)",
            "定位系統": "獨立雙頻五星 GPS 定位",
            "電池續航": "典型使用模式 14 天 / 重度使用模式 7 天",
            "錶身材質": "航太級鋁合金錶框 + 親膚矽膠錶帶 (防水等級 5ATM)"
        }
    }
]

# ==========================================================================
# 資料庫與儲存抽象介面層 (SQLite / Firestore, Local / GCS)
# ==========================================================================
def init_db():
    """初始化資料表或 Firestore 集合，建立預設管理者與預設產品"""
    if DB_MODE == "firestore":
        try:
            from google.cloud import firestore
            db_fs = firestore.Client()

            # 初始化與同步管理者密碼
            initial_password = os.environ.get("ADMIN_PASSWORD", "admin1234")
            hashed_pw = generate_password_hash(initial_password)
            doc_ref.set({"password_hash": hashed_pw})
            print("[INFO] Firestore admin password synced with environment variable.")

            # 初始化預設產品（若 products 集合為空）
            products_col = db_fs.collection("products")
            existing = list(products_col.limit(1).stream())
            if not existing:
                for p in DEFAULT_PRODUCTS:
                    products_col.document(p["id"]).set({
                        "id": p["id"],
                        "name": p["name"],
                        "price": p["price"],
                        "image_url": p["image_url"],
                        "image_local": p["image_local"],
                        "summary": p["summary"],
                        "specs": json.dumps(p["specs"], ensure_ascii=False),
                        "created_at": time.strftime('%Y-%m-%d %H:%M:%S')
                    })
                print("[INFO] Firestore: Default products seeded.")
        except Exception as e:
            print(f"[ERROR] Firestore initialization failed: {e}")
    else:
        # SQLite 模式
        try:
            with sqlite3.connect(DATABASE) as conn:
                cursor = conn.cursor()
                # 建立使用者帳號表
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS users (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        username TEXT UNIQUE NOT NULL,
                        password_hash TEXT NOT NULL
                    )
                ''')
                # 建立 PDF 文件紀錄表
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS pdfs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        product_id TEXT NOT NULL,
                        filename TEXT NOT NULL,
                        display_name TEXT NOT NULL,
                        url TEXT NOT NULL,
                        upload_time TEXT NOT NULL
                    )
                ''')
                # 建立產品資料表
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS products (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        price TEXT NOT NULL,
                        image_url TEXT DEFAULT '',
                        image_local TEXT DEFAULT '',
                        summary TEXT NOT NULL,
                        specs TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL
                    )
                ''')
                # 建立全域設定表
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS settings (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    )
                ''')
                conn.commit()

                # 初始化與同步管理者密碼
                initial_password = os.environ.get("ADMIN_PASSWORD", "admin1234")
                hashed_pw = generate_password_hash(initial_password)
                cursor.execute("DELETE FROM users WHERE username = 'admin'")
                cursor.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", ('admin', hashed_pw))
                conn.commit()
                print("[INFO] SQLite admin password synced with environment variable.")

                # 建立預設產品（若 products 表為空）
                cursor.execute("SELECT COUNT(*) FROM products")
                count = cursor.fetchone()[0]
                if count == 0:
                    for p in DEFAULT_PRODUCTS:
                        cursor.execute(
                            "INSERT OR IGNORE INTO products (id, name, price, image_url, image_local, summary, specs, created_at) VALUES (?,?,?,?,?,?,?,?)",
                            (p["id"], p["name"], p["price"], p["image_url"], p["image_local"],
                             p["summary"], json.dumps(p["specs"], ensure_ascii=False),
                             time.strftime('%Y-%m-%d %H:%M:%S'))
                        )
                    conn.commit()
                    print("[INFO] SQLite: Default products seeded.")
        except Exception as e:
            print(f"[ERROR] SQLite database initialization failed: {e}")



def db_get_setting(key, default_value=""):
    """讀取網站全域設定，優先從資料庫，其次環境變數，最後預設值"""
    # 1. 優先從資料庫讀取
    if DB_MODE == "firestore":
        try:
            from google.cloud import firestore
            db_fs = firestore.Client()
            doc = db_fs.collection("settings").document(key).get()
            if doc.exists:
                val = doc.to_dict().get("value")
                if val is not None:
                    return val
        except Exception as e:
            print(f"[ERROR] Firestore get setting failed: {e}")
    else:
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
            row = cursor.fetchone()
            conn.close()
            if row:
                return row['value']
        except Exception as e:
            print(f"[ERROR] SQLite get setting failed: {e}")

    # 2. 次要從環境變數讀取
    env_key = key.upper()
    env_val = os.environ.get(env_key)
    if env_val is not None and env_val != "":
        return env_val

    # 3. 最後返回預設值
    return default_value

def db_set_setting(key, value):
    """保存網站全域設定"""
    if DB_MODE == "firestore":
        try:
            from google.cloud import firestore
            db_fs = firestore.Client()
            db_fs.collection("settings").document(key).set({"value": value})
            return True
        except Exception as e:
            print(f"[ERROR] Firestore set setting failed: {e}")
            return False
    else:
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"[ERROR] SQLite set setting failed: {e}")
            return False


def _row_to_product(data, doc_id=None):
    """將資料庫 row dict 轉換為前端使用的 product dict"""
    specs_raw = data.get("specs", "{}")
    if isinstance(specs_raw, str):
        try:
            specs = json.loads(specs_raw)
        except Exception:
            specs = {}
    else:
        specs = specs_raw

    # 決定圖片來源：優先使用雲端 URL，其次 local filename
    image_url = data.get("image_url") or ""
    image_local = data.get("image_local") or data.get("image") or ""

    if image_url:
        resolved_image = image_url
    elif image_local:
        resolved_image = f"/static/images/{image_local}"
    else:
        # 預設展示圖片，保證絕不破圖
        resolved_image = "/static/images/earbuds.png"

    # 優先使用 data 內的 id，若為 None 則回退至 doc_id（Firestore 文件 ID）
    resolved_id = data.get("id") or doc_id or ""

    return {
        "id": resolved_id,
        "name": data.get("name") or "",
        "price": data.get("price") or "",
        "summary": data.get("summary") or "",
        "image_url": image_url,
        "image_local": image_local,
        "image": resolved_image,
        "specs": specs,
        "created_at": data.get("created_at", "")
    }


def db_get_all_products():
    """取得全部產品列表"""
    products = []
    if DB_MODE == "firestore":
        try:
            from google.cloud import firestore
            db_fs = firestore.Client()
            # 不使用 order_by 避免需要複合索引；改為取回後在 Python 端排序
            docs = db_fs.collection("products").stream()
            for doc in docs:
                # 將 Firestore 文件 ID 作為 id 的最終備援
                product = _row_to_product(doc.to_dict(), doc_id=doc.id)
                if product["id"]:  # 過濾掉 id 仍為空的異常文件
                    products.append(product)
            products.sort(key=lambda p: p.get("created_at", ""))
        except Exception as e:
            print(f"[ERROR] Firestore get all products failed: {e}")
    else:
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM products ORDER BY created_at")
            for row in cursor.fetchall():
                products.append(_row_to_product(dict(row)))
            conn.close()
        except Exception as e:
            print(f"[ERROR] SQLite get all products failed: {e}")
    return products


def db_get_product(product_id):
    """取得單一產品"""
    if DB_MODE == "firestore":
        try:
            from google.cloud import firestore
            db_fs = firestore.Client()
            doc = db_fs.collection("products").document(product_id).get()
            if doc.exists:
                return _row_to_product(doc.to_dict(), doc_id=doc.id)
        except Exception as e:
            print(f"[ERROR] Firestore get product failed: {e}")
        return None
    else:
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM products WHERE id = ?", (product_id,))
            row = cursor.fetchone()
            conn.close()
            if row:
                return _row_to_product(dict(row))
        except Exception as e:
            print(f"[ERROR] SQLite get product failed: {e}")
        return None


def db_create_product(product_id, name, price, summary, specs, image_url="", image_local=""):
    """建立新產品"""
    specs_json = json.dumps(specs, ensure_ascii=False)
    created_at = time.strftime('%Y-%m-%d %H:%M:%S')
    if DB_MODE == "firestore":
        try:
            from google.cloud import firestore
            db_fs = firestore.Client()
            db_fs.collection("products").document(product_id).set({
                "id": product_id, "name": name, "price": price,
                "image_url": image_url, "image_local": image_local,
                "summary": summary, "specs": specs_json, "created_at": created_at
            })
            return True
        except Exception as e:
            print(f"[ERROR] Firestore create product failed: {e}")
            return False
    else:
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO products (id, name, price, image_url, image_local, summary, specs, created_at) VALUES (?,?,?,?,?,?,?,?)",
                (product_id, name, price, image_url, image_local, summary, specs_json, created_at)
            )
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"[ERROR] SQLite create product failed: {e}")
            return False


def db_update_product(product_id, name, price, summary, specs, image_url=None, image_local=None):
    """更新產品資料"""
    specs_json = json.dumps(specs, ensure_ascii=False)
    if DB_MODE == "firestore":
        try:
            from google.cloud import firestore
            db_fs = firestore.Client()
            update_data = {
                "name": name, "price": price,
                "summary": summary, "specs": specs_json
            }
            if image_url is not None:
                update_data["image_url"] = image_url
            if image_local is not None:
                update_data["image_local"] = image_local
            db_fs.collection("products").document(product_id).update(update_data)
            return True
        except Exception as e:
            print(f"[ERROR] Firestore update product failed: {e}")
            return False
    else:
        try:
            conn = get_db()
            cursor = conn.cursor()
            if image_url is not None and image_local is not None:
                cursor.execute(
                    "UPDATE products SET name=?, price=?, summary=?, specs=?, image_url=?, image_local=? WHERE id=?",
                    (name, price, summary, specs_json, image_url, image_local, product_id)
                )
            elif image_local is not None:
                cursor.execute(
                    "UPDATE products SET name=?, price=?, summary=?, specs=?, image_local=? WHERE id=?",
                    (name, price, summary, specs_json, image_local, product_id)
                )
            else:
                cursor.execute(
                    "UPDATE products SET name=?, price=?, summary=?, specs=? WHERE id=?",
                    (name, price, summary, specs_json, product_id)
                )
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"[ERROR] SQLite update product failed: {e}")
            return False


def db_delete_product(product_id):
    """刪除產品及其 PDF 紀錄"""
    if DB_MODE == "firestore":
        try:
            from google.cloud import firestore
            db_fs = firestore.Client()
            db_fs.collection("products").document(product_id).delete()
            # 同時清除該產品的 PDF 紀錄
            pdfs = db_fs.collection("pdfs").where("product_id", "==", product_id).stream()
            for pdf in pdfs:
                pdf.reference.delete()
            return True
        except Exception as e:
            print(f"[ERROR] Firestore delete product failed: {e}")
            return False
    else:
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM products WHERE id = ?", (product_id,))
            cursor.execute("DELETE FROM pdfs WHERE product_id = ?", (product_id,))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"[ERROR] SQLite delete product failed: {e}")
            return False


def db_get_password_hash():
    """取得加密密碼"""
    if DB_MODE == "firestore":
        try:
            from google.cloud import firestore
            db_fs = firestore.Client()
            doc = db_fs.collection("users").document("admin").get()
            if doc.exists:
                return doc.to_dict().get("password_hash")
        except Exception as e:
            print(f"[ERROR] Firestore get password failed: {e}")
        return None
    else:
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT password_hash FROM users WHERE username = 'admin'")
            row = cursor.fetchone()
            conn.close()
            if row:
                return row['password_hash']
        except Exception as e:
            print(f"[ERROR] SQLite get password failed: {e}")
        return None

def db_update_password_hash(new_hash):
    """變更加密密碼"""
    if DB_MODE == "firestore":
        try:
            from google.cloud import firestore
            db_fs = firestore.Client()
            db_fs.collection("users").document("admin").set({"password_hash": new_hash})
            return True
        except Exception as e:
            print(f"[ERROR] Firestore update password failed: {e}")
            return False
    else:
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET password_hash = ? WHERE username = 'admin'", (new_hash,))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"[ERROR] SQLite update password failed: {e}")
            return False

def db_save_pdf(product_id, filename, display_name, url, upload_time):
    """將 PDF 檔案紀錄存入資料庫"""
    if DB_MODE == "firestore":
        try:
            from google.cloud import firestore
            db_fs = firestore.Client()
            db_fs.collection("pdfs").add({
                "product_id": product_id,
                "filename": filename,
                "display_name": display_name,
                "url": url,
                "upload_time": upload_time
            })
            return True
        except Exception as e:
            print(f"[ERROR] Firestore save pdf failed: {e}")
            return False
    else:
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO pdfs (product_id, filename, display_name, url, upload_time)
                VALUES (?, ?, ?, ?, ?)
            """, (product_id, filename, display_name, url, upload_time))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"[ERROR] SQLite save pdf failed: {e}")
            return False

def db_get_product_pdfs(product_id):
    """查詢某個產品對應的 PDF 紀錄"""
    pdfs = []
    if DB_MODE == "firestore":
        try:
            from google.cloud import firestore
            db_fs = firestore.Client()
            docs = db_fs.collection("pdfs").where("product_id", "==", product_id).stream()
            for doc in docs:
                d = doc.to_dict()
                pdfs.append({
                    "id": doc.id,
                    "full_name": d.get("filename"),
                    "display_name": d.get("display_name"),
                    "url": d.get("url"),
                    "upload_time": d.get("upload_time")
                })
        except Exception as e:
            print(f"[ERROR] Firestore query pdfs failed: {e}")
    else:
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT id, filename, display_name, url, upload_time FROM pdfs WHERE product_id = ?", (product_id,))
            rows = cursor.fetchall()
            conn.close()
            for row in rows:
                pdfs.append({
                    "id": str(row['id']),
                    "full_name": row['filename'],
                    "display_name": row['display_name'],
                    "url": row['url'],
                    "upload_time": row['upload_time']
                })
        except Exception as e:
            print(f"[ERROR] SQLite query pdfs failed: {e}")

    pdfs.sort(key=lambda x: x['upload_time'], reverse=True)
    return pdfs

def db_get_all_pdfs():
    """查詢全站 PDF 紀錄 (後台用)"""
    pdfs = []
    if DB_MODE == "firestore":
        try:
            from google.cloud import firestore
            db_fs = firestore.Client()
            docs = db_fs.collection("pdfs").stream()
            for doc in docs:
                d = doc.to_dict()
                pdfs.append({
                    "id": doc.id,
                    "product_id": d.get("product_id"),
                    "full_name": d.get("filename"),
                    "display_name": d.get("display_name"),
                    "url": d.get("url"),
                    "upload_time": d.get("upload_time")
                })
        except Exception as e:
            print(f"[ERROR] Firestore query all pdfs failed: {e}")
    else:
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT id, product_id, filename, display_name, url, upload_time FROM pdfs")
            rows = cursor.fetchall()
            conn.close()
            for row in rows:
                pdfs.append({
                    "id": str(row['id']),
                    "product_id": row['product_id'],
                    "full_name": row['filename'],
                    "display_name": row['display_name'],
                    "url": row['url'],
                    "upload_time": row['upload_time']
                })
        except Exception as e:
            print(f"[ERROR] SQLite query all pdfs failed: {e}")

    pdfs.sort(key=lambda x: x['upload_time'], reverse=True)
    return pdfs

def db_get_pdf(pdf_id):
    """根據 ID 查詢 PDF 紀錄"""
    if DB_MODE == "firestore":
        try:
            from google.cloud import firestore
            db_fs = firestore.Client()
            doc = db_fs.collection("pdfs").document(pdf_id).get()
            if doc.exists:
                d = doc.to_dict()
                return {
                    "id": doc.id,
                    "product_id": d.get("product_id"),
                    "full_name": d.get("filename"),
                    "display_name": d.get("display_name"),
                    "url": d.get("url"),
                    "upload_time": d.get("upload_time")
                }
        except Exception as e:
            print(f"[ERROR] Firestore get pdf failed: {e}")
        return None
    else:
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT id, product_id, filename, display_name, url, upload_time FROM pdfs WHERE id = ?", (pdf_id,))
            row = cursor.fetchone()
            conn.close()
            if row:
                return {
                    "id": str(row['id']),
                    "product_id": row['product_id'],
                    "full_name": row['filename'],
                    "display_name": row['display_name'],
                    "url": row['url'],
                    "upload_time": row['upload_time']
                }
        except Exception as e:
            print(f"[ERROR] SQLite get pdf failed: {e}")
        return None

def db_delete_pdf(pdf_id):
    """從資料庫中刪除指定 ID 的 PDF 紀錄"""
    if DB_MODE == "firestore":
        try:
            from google.cloud import firestore
            db_fs = firestore.Client()
            db_fs.collection("pdfs").document(pdf_id).delete()
            return True
        except Exception as e:
            print(f"[ERROR] Firestore delete pdf failed: {e}")
            return False
    else:
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM pdfs WHERE id = ?", (pdf_id,))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"[ERROR] SQLite delete pdf failed: {e}")
            return False

def delete_pdf_file(filename):
    """從 GCS 或是本地刪除實體 PDF 檔案"""
    if STORAGE_MODE == "gcs":
        try:
            from google.cloud import storage
            client = storage.Client()
            bucket = client.bucket(GCS_BUCKET_NAME)
            blob = bucket.blob(f"uploads/{filename}")
            if blob.exists():
                blob.delete()
                print(f"[INFO] GCS file deleted: uploads/{filename}")
            return True
        except Exception as e:
            print(f"[ERROR] GCS file delete failed: {e}")
            return False
    else:
        try:
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            if os.path.exists(filepath):
                os.remove(filepath)
                print(f"[INFO] Local file deleted: {filepath}")
            return True
        except Exception as e:
            print(f"[ERROR] Local file delete failed: {e}")
            return False


def upload_file_to_storage(file, folder, filename):
    """通用檔案儲存介面：上傳至 GCS 或本地"""
    if STORAGE_MODE == "gcs":
        try:
            from google.cloud import storage
            client = storage.Client()
            bucket = client.bucket(GCS_BUCKET_NAME)
            blob = bucket.blob(f"{folder}/{filename}")
            content_type = 'application/pdf' if filename.lower().endswith('.pdf') else 'image/*'
            if filename.lower().endswith(('.png', '.jpg', '.jpeg')):
                content_type = f"image/{filename.rsplit('.', 1)[1].lower()}"
            elif filename.lower().endswith('.webp'):
                content_type = 'image/webp'
            blob.upload_from_file(file, content_type=content_type)
            url = f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{folder}/{filename}"
            return url
        except Exception as e:
            print(f"[ERROR] GCS upload failed: {e}")
            return None
    else:
        # Local 模式
        try:
            if folder == "uploads":
                dest_dir = app.config['UPLOAD_FOLDER']
            else:
                dest_dir = IMAGE_FOLDER
            filepath = os.path.join(dest_dir, filename)
            file.save(filepath)
            return filepath  # 本地回傳路徑
        except Exception as e:
            print(f"[ERROR] Local save failed: {e}")
            return None


def upload_pdf_file(file, product_id):
    """PDF 檔案儲存介面: 支援上傳至 GCS 或是本地"""
    sec_name = secure_filename(file.filename)
    if not sec_name or sec_name == '.pdf':
        sec_name = "presentation.pdf"

    timestamp = int(time.time())
    new_filename = f"{product_id}_{timestamp}_{sec_name}"

    if STORAGE_MODE == "gcs":
        try:
            from google.cloud import storage
            client = storage.Client()
            bucket = client.bucket(GCS_BUCKET_NAME)
            blob = bucket.blob(f"uploads/{new_filename}")
            blob.upload_from_file(file, content_type='application/pdf')
            url = f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/uploads/{new_filename}"
            return new_filename, sec_name, url
        except Exception as e:
            print(f"[ERROR] GCS upload failed: {e}")
            return None, None, None
    else:
        try:
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], new_filename)
            file.save(filepath)
            url = url_for('view_pdf', filename=new_filename)
            return new_filename, sec_name, url
        except Exception as e:
            print(f"[ERROR] Local save failed: {e}")
            return None, None, None


def upload_image_file(file, product_id):
    """產品圖片儲存介面：支援 GCS 或本地"""
    ext = file.filename.rsplit('.', 1)[1].lower()
    sec_name = f"{product_id}_{int(time.time())}.{ext}"

    if STORAGE_MODE == "gcs":
        try:
            from google.cloud import storage
            client = storage.Client()
            bucket = client.bucket(GCS_BUCKET_NAME)
            blob = bucket.blob(f"images/{sec_name}")
            content_type = f"image/{ext}" if ext not in ('jpg',) else "image/jpeg"
            blob.upload_from_file(file, content_type=content_type)
            url = f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/images/{sec_name}"
            return url, sec_name  # (cloud_url, local_filename)
        except Exception as e:
            print(f"[ERROR] GCS image upload failed: {e}")
            return None, None
    else:
        try:
            filepath = os.path.join(IMAGE_FOLDER, sec_name)
            file.save(filepath)
            return "", sec_name  # 本地：空 url，local filename
        except Exception as e:
            print(f"[ERROR] Local image save failed: {e}")
            return None, None


# 登入防護裝飾器
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            flash("此頁面受密碼保護，請先登入！", "error")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# 全域設定與版號上下文處理器
@app.context_processor
def inject_site_settings():
    site_name = db_get_setting("site_name", "TechShowcase")
    site_title = db_get_setting("site_title", "探索前沿科技產品")
    site_subtitle = db_get_setting("site_subtitle", "我們專注於打造融入生活的智慧硬體...")
    return dict(
        current_version=current_version,
        site_name=site_name,
        site_title=site_title,
        site_subtitle=site_subtitle
    )


# ==========================================================================
# 路由
# ==========================================================================

@app.route('/')
def index():
    products = db_get_all_products()
    return render_template('index.html', products=products)

@app.route('/product/<product_id>')
def detail(product_id):
    product = db_get_product(product_id)
    if not product:
        flash("找不到該項產品！", "error")
        return redirect(url_for('index'))
    pdfs = db_get_product_pdfs(product_id)
    return render_template('detail.html', product=product, pdfs=pdfs)

# 處理 PDF 簡報上傳
@app.route('/product/<product_id>/upload', methods=['POST'])
def upload_file(product_id):
    product = db_get_product(product_id)
    if not product:
        flash("找不到該項產品！無法上傳簡報。", "error")
        return redirect(url_for('index'))

    if 'pdf_file' not in request.files:
        flash("未偵測到上傳檔案欄位！", "error")
        return redirect(url_for('detail', product_id=product_id))

    file = request.files['pdf_file']
    if file.filename == '':
        flash("未選取任何檔案！", "error")
        return redirect(url_for('detail', product_id=product_id))

    if file and allowed_file(file.filename, ALLOWED_PDF_EXTENSIONS):
        new_filename, sec_name, url = upload_pdf_file(file, product_id)
        if new_filename and url:
            upload_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
            if db_save_pdf(product_id, new_filename, sec_name, url, upload_time):
                flash(f"簡報「{sec_name}」已成功儲存！", "success")
            else:
                flash("檔案上傳成功，但資料庫紀錄寫入失敗！", "error")
        else:
            flash("檔案儲存失敗，請確認儲存空間設定！", "error")
    else:
        flash("上傳失敗！僅支援上傳 PDF 格式的檔案。", "error")

    return redirect(url_for('detail', product_id=product_id))

# 登入頁面與邏輯
@app.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('logged_in'):
        return redirect(url_for('admin'))

    if request.method == 'POST':
        password_input = request.form.get('password')
        password_hash = db_get_password_hash()
        if not password_hash:
            flash("系統尚未初始化，或是資料庫存取失敗！", "error")
            return render_template('login.html')

        if check_password_hash(password_hash, password_input):
            session['logged_in'] = True
            if check_password_hash(password_hash, "admin123"):
                flash("登入成功！提示：您目前正使用預設密碼 'admin123'，為了安全，請立刻在下方更新密碼！", "success")
            else:
                flash("成功登入管理者後台！", "success")
            return redirect(url_for('admin'))
        else:
            flash("密碼錯誤，請再試一次！", "error")

    return render_template('login.html')

# 登出邏輯
@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    flash("您已成功登出！", "success")
    return redirect(url_for('index'))

# 管理者後台
@app.route('/admin')
@login_required
def admin():
    products = db_get_all_products()
    all_pdfs = db_get_all_pdfs()
    google_api_key = os.environ.get("GOOGLE_API_KEY", "")
    google_client_id = os.environ.get("GOOGLE_CLIENT_ID", "")
    return render_template(
        'admin.html',
        products=products,
        pdfs=all_pdfs,
        google_api_key=google_api_key,
        google_client_id=google_client_id
    )

# ==========================================================================
# Google 雲端硬碟檔案下載與匯入處理
# ==========================================================================
import requests

def save_pdf_bytes(data_bytes, filename, product_id):
    """保存從二進位 bytes 傳入的 PDF 簡報，支援本地與 GCS"""
    sec_name = secure_filename(filename)
    if not sec_name or not sec_name.lower().endswith('.pdf'):
        sec_name = "presentation.pdf"

    timestamp = int(time.time())
    new_filename = f"{product_id}_{timestamp}_{sec_name}"

    if STORAGE_MODE == "gcs":
        try:
            from google.cloud import storage
            client = storage.Client()
            bucket = client.bucket(GCS_BUCKET_NAME)
            blob = bucket.blob(f"uploads/{new_filename}")
            blob.upload_from_string(data_bytes, content_type='application/pdf')
            url = f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/uploads/{new_filename}"
            return new_filename, sec_name, url
        except Exception as e:
            print(f"[ERROR] GCS upload from bytes failed: {e}")
            return None, None, None
    else:
        try:
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], new_filename)
            with open(filepath, 'wb') as f:
                f.write(data_bytes)
            url = url_for('view_pdf', filename=new_filename)
            return new_filename, sec_name, url
        except Exception as e:
            print(f"[ERROR] Local save from bytes failed: {e}")
            return None, None, None

def save_image_bytes(data_bytes, filename, product_id):
    """保存從二進位 bytes 傳入的產品圖片，支援本地與 GCS"""
    ext = "png"
    if '.' in filename:
        ext_candidate = filename.rsplit('.', 1)[1].lower()
        if ext_candidate in ('png', 'jpg', 'jpeg', 'webp', 'gif'):
            ext = ext_candidate

    sec_name = f"{product_id}_{int(time.time())}.{ext}"

    if STORAGE_MODE == "gcs":
        try:
            from google.cloud import storage
            client = storage.Client()
            bucket = client.bucket(GCS_BUCKET_NAME)
            blob = bucket.blob(f"images/{sec_name}")
            content_type = f"image/{ext}" if ext not in ('jpg',) else "image/jpeg"
            blob.upload_from_string(data_bytes, content_type=content_type)
            url = f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/images/{sec_name}"
            return url, sec_name
        except Exception as e:
            print(f"[ERROR] GCS image upload from bytes failed: {e}")
            return None, None
    else:
        try:
            filepath = os.path.join(IMAGE_FOLDER, sec_name)
            with open(filepath, 'wb') as f:
                f.write(data_bytes)
            return "", sec_name
        except Exception as e:
            print(f"[ERROR] Local image save from bytes failed: {e}")
            return None, None

# 雲端硬碟檔案匯入路由
@app.route('/admin/google-drive/import', methods=['POST'])
@login_required
def import_google_drive_file():
    data = request.json or {}
    product_id = data.get('product_id')
    file_id = data.get('file_id')
    access_token = data.get('access_token')
    file_name = data.get('file_name', '').strip()
    mime_type = data.get('mime_type', '')
    import_type = data.get('import_type')  # 'image' 或是 'pdf'

    if not product_id or not file_id or not access_token or not import_type:
        return {"success": False, "message": "缺少必要參數！"}, 400

    # 驗證產品是否存在
    product = db_get_product(product_id)
    if not product:
        return {"success": False, "message": "產品不存在！"}, 404

    # 1. 決定下載/匯出 URL
    headers = {"Authorization": f"Bearer {access_token}"}
    
    # 如果是 Google Slides，自動匯出為 PDF 格式
    if mime_type == "application/vnd.google-apps.presentation":
        download_url = f"https://www.googleapis.com/drive/v3/files/{file_id}/export?mimeType=application/pdf"
        # 強制將副檔名設為 .pdf
        if not file_name.lower().endswith('.pdf'):
            file_name = file_name + ".pdf"
    else:
        # 常規二進位檔案下載
        download_url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media"

    # 2. 下載檔案內容
    try:
        r = requests.get(download_url, headers=headers)
        if r.status_code != 200:
            print(f"[ERROR] Google Drive download failed: status={r.status_code}, response={r.text}")
            return {"success": False, "message": f"從 Google Drive 下載檔案失敗 (HTTP {r.status_code})"}, 500
        file_bytes = r.content
    except Exception as e:
        print(f"[ERROR] Google Drive download exception: {e}")
        return {"success": False, "message": f"連接 Google Drive 時發生錯誤: {e}"}, 500

    # 3. 根據類型進行保存
    if import_type == "image":
        url, local_name = save_image_bytes(file_bytes, file_name, product_id)
        if local_name:
            if db_update_product(product_id, product['name'], product['price'], product['summary'], product['specs'], url, local_name):
                updated_product = db_get_product(product_id)
                flash(f"已成功從雲端硬碟匯入產品圖片！", "success")
                return {"success": True, "image_url": updated_product['image']}
            else:
                return {"success": False, "message": "檔案已下載，但更新資料庫失敗！"}, 500
        else:
            return {"success": False, "message": "儲存圖片檔案失敗！"}, 500

    elif import_type == "pdf":
        new_filename, sec_name, url = save_pdf_bytes(file_bytes, file_name, product_id)
        if new_filename and url:
            upload_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
            if db_save_pdf(product_id, new_filename, sec_name, url, upload_time):
                flash(f"已成功從雲端硬碟匯入簡報「{sec_name}」！", "success")
                return {"success": True, "url": url}
            else:
                return {"success": False, "message": "簡報已下載，但更新資料庫失敗！"}, 500
        else:
            return {"success": False, "message": "儲存簡報檔案失敗！"}, 500

    else:
        return {"success": False, "message": "不支援的匯入類型！"}, 400

# 新增產品
@app.route('/admin/product/create', methods=['POST'])
@login_required
def create_product():
    name = request.form.get('name', '').strip()
    price = request.form.get('price', '').strip()
    summary = request.form.get('summary', '').strip()

    if not name or not price or not summary:
        flash("產品名稱、價格和簡介皆為必填！", "error")
        return redirect(url_for('admin'))

    # 產生唯一 ID
    base_id = slugify(name)
    product_id = base_id
    # 確保 ID 唯一
    existing = db_get_product(product_id)
    if existing:
        product_id = f"{base_id}_{int(time.time())}"

    # 處理規格
    spec_keys = request.form.getlist('spec_keys[]')
    spec_values = request.form.getlist('spec_values[]')
    specs = {}
    for k, v in zip(spec_keys, spec_values):
        k, v = k.strip(), v.strip()
        if k:
            specs[k] = v

    # 處理圖片上傳
    image_url = ""
    image_local = ""
    if 'product_image' in request.files:
        file = request.files['product_image']
        if file and file.filename != '' and allowed_file(file.filename, ALLOWED_IMAGE_EXTENSIONS):
            img_url, img_local = upload_image_file(file, product_id)
            if img_url is not None:
                image_url = img_url
                image_local = img_local

    if db_create_product(product_id, name, price, summary, specs, image_url, image_local):
        flash(f"產品「{name}」已成功新增！", "success")
    else:
        flash("新增產品失敗，請稍後再試！", "error")

    return redirect(url_for('admin'))

# 更新產品資訊路由 (後台編輯)
@app.route('/admin/product/update', methods=['POST'])
@login_required
def update_product():
    product_id = request.form.get('product_id')
    product = db_get_product(product_id)

    if not product:
        flash("找不到要更新的產品！", "error")
        return redirect(url_for('admin'))

    name = request.form.get('name', '').strip()
    price = request.form.get('price', '').strip()
    summary = request.form.get('summary', '').strip()

    # 處理動態規格欄位
    spec_keys = request.form.getlist('spec_keys[]')
    spec_values = request.form.getlist('spec_values[]')
    specs = {}
    for key, val in zip(spec_keys, spec_values):
        key, val = key.strip(), val.strip()
        if key:
            specs[key] = val

    # 處理產品圖片上傳
    image_url = None
    image_local = None
    if 'product_image' in request.files:
        file = request.files['product_image']
        if file and file.filename != '' and allowed_file(file.filename, ALLOWED_IMAGE_EXTENSIONS):
            img_url, img_local = upload_image_file(file, product_id)
            if img_url is not None:
                image_url = img_url
                image_local = img_local
                flash(f"已成功更新「{name}」的產品圖片！", "success")

    if db_update_product(product_id, name, price, summary, specs, image_url, image_local):
        flash(f"產品「{name}」的資料已儲存！", "success")
    else:
        flash("資料儲存失敗，請檢查設定！", "error")

    return redirect(url_for('admin'))

# 刪除產品路由
@app.route('/admin/product/delete/<product_id>', methods=['POST'])
@login_required
def delete_product(product_id):
    product = db_get_product(product_id)
    if not product:
        flash("找不到要刪除的產品！", "error")
        return redirect(url_for('admin'))

    product_name = product.get('name', product_id)
    if db_delete_product(product_id):
        flash(f"產品「{product_name}」已成功刪除！", "success")
    else:
        flash("刪除產品失敗，請稍後再試！", "error")

    return redirect(url_for('admin'))

# 刪除 PDF 路由
@app.route('/admin/pdf/delete/<pdf_id>', methods=['POST'])
@login_required
def delete_pdf(pdf_id):
    pdf = db_get_pdf(pdf_id)
    if not pdf:
        flash("找不到要刪除的 PDF 簡報紀錄！", "error")
        return redirect(url_for('admin'))

    filename = pdf.get('full_name')
    display_name = pdf.get('display_name', filename)

    # 1. 刪除實體檔案 (GCS / 本地)
    delete_pdf_file(filename)

    # 2. 刪除資料庫紀錄
    if db_delete_pdf(pdf_id):
        flash(f"簡報「{display_name}」已成功刪除！", "success")
    else:
        flash("刪除簡報資料庫紀錄失敗！", "error")

    return redirect(url_for('admin'))

# 修改密碼路由
@app.route('/admin/change-password', methods=['POST'])
@login_required
def change_password():
    old_password = request.form.get('old_password')
    new_password = request.form.get('new_password')
    confirm_password = request.form.get('confirm_password')

    if not old_password or not new_password or not confirm_password:
        flash("所有密碼欄位皆必須填寫！", "error")
        return redirect(url_for('admin'))

    if new_password != confirm_password:
        flash("新密碼與確認新密碼不一致！", "error")
        return redirect(url_for('admin'))

    password_hash = db_get_password_hash()
    if not password_hash or not check_password_hash(password_hash, old_password):
        flash("舊密碼驗證錯誤，無法更新密碼！", "error")
        return redirect(url_for('admin'))

    hashed_new = generate_password_hash(new_password)
    if db_update_password_hash(hashed_new):
        session.pop('logged_in', None)
        flash("密碼修改成功！請使用新密碼重新登入。", "success")
        return redirect(url_for('login'))
    else:
        flash("密碼變更失敗，請確認資料庫設定！", "error")
        return redirect(url_for('admin'))

# 網站設定更新路由
@app.route('/admin/settings/update', methods=['POST'])
@login_required
def update_settings():
    site_name = request.form.get('site_name', '').strip()
    site_title = request.form.get('site_title', '').strip()
    site_subtitle = request.form.get('site_subtitle', '').strip()

    if site_name:
        db_set_setting("site_name", site_name)
    if site_title:
        db_set_setting("site_title", site_title)
    if site_subtitle:
        db_set_setting("site_subtitle", site_subtitle)

    flash("網站首頁與品牌設定已成功更新！", "success")
    return redirect(url_for('admin'))

# 本地模式下下載與檢視 PDF 的路由
@app.route('/download/<filename>')
def download_pdf(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename, as_attachment=True)

@app.route('/view/<filename>')
def view_pdf(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename, as_attachment=False)

# 初始化資料表或雲端集合
init_db()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
