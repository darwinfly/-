# VERSION: v1.4.1 (Clean Frontpage Header)
# DATE: 2026-07-03
# CHANGES: Removed frontpage announcement label, enlarged shop avatar, and updated layout margins.
import os
import datetime
from typing import Optional
from fastapi import FastAPI, Request, Form, Cookie, Response, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from google.cloud import firestore

app = FastAPI(title="電商導流與會員系統規劃")

# Setup templates
templates = Jinja2Templates(directory="templates")



# Initialize Firestore
project_id = os.environ.get("GOOGLE_CLOUD_PROJECT") or "project-922520ec-5eb7-4ef0-878"

# Check if running in Cloud Run
is_cloud_run = "K_SERVICE" in os.environ

if is_cloud_run:
    db = firestore.Client(project=project_id)
else:
    try:
        db = firestore.Client(project=project_id)
        # Simple check to see if credentials work
        list(db.collection("products").limit(1).stream())
    except Exception as e:
        print(f"Default credentials failed: {e}. Falling back to gcloud credentials.")
        import subprocess
        import google.auth.credentials
        
        class GcloudCredentials(google.auth.credentials.Credentials):
            def __init__(self):
                super().__init__()
                self._refresh_token()
                
            def refresh(self, request):
                self._refresh_token()
                
            def _refresh_token(self):
                try:
                    res = subprocess.run(
                        ["cmd", "/c", "gcloud auth print-access-token"],
                        capture_output=True,
                        text=True
                    )
                    self.token = res.stdout.strip()
                except Exception as e:
                    print(f"Error getting gcloud token: {e}")
                    
        db = firestore.Client(project=project_id, credentials=GcloudCredentials())

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin1234")

def get_admin_password() -> str:
    try:
        cred_ref = db.collection("shop_profile").document("credentials").get()
        if cred_ref.exists:
            cred = cred_ref.to_dict()
            return cred.get("password") or ADMIN_PASSWORD
    except Exception as e:
        print(f"Error fetching admin password: {e}")
    return ADMIN_PASSWORD

# Helper function to check admin session
def is_admin(admin_session: Optional[str] = Cookie(None)) -> bool:
    return admin_session == "authenticated"

def get_shop_profile():
    try:
        profile_ref = db.collection("shop_profile").document("config").get()
        if profile_ref.exists:
            profile = profile_ref.to_dict()
            return {
                "shop_name": profile.get("shop_name") or "我的質感選物店",
                "shop_logo_url": profile.get("shop_logo_url") or "",
                "shop_description": profile.get("shop_description") or "精選醫美級保養與生活美學好物。快速登入會員，即可解鎖今日限定商品與專屬連結。"
            }
    except Exception as e:
        print(f"Error fetching shop profile: {e}")
    return {
        "shop_name": "我的質感選物店",
        "shop_logo_url": "",
        "shop_description": "精選醫美級保養與生活美學好物。快速登入會員，即可解鎖今日限定商品與專屬連結。"
    }

@app.get("/", response_class=HTMLResponse)
def get_index(request: Request, client_submitted: Optional[str] = Cookie(None)):
    is_locked = client_submitted != "true"
    
    # Get products from Firestore
    try:
        products_ref = db.collection("products").order_by("created_at", direction=firestore.Query.DESCENDING).stream()
        products = []
        for doc in products_ref:
            p = doc.to_dict()
            p["id"] = doc.id
            if "created_at" in p and p["created_at"]:
                if hasattr(p["created_at"], "isoformat"):
                    p["created_at"] = p["created_at"].isoformat()
            
            # 轉換 image_url 為 image_urls list
            image_url_str = p.get("image_url", "")
            p["image_urls"] = [url.strip() for url in image_url_str.split(",") if url.strip()] if image_url_str else []
            
            products.append(p)
    except Exception as e:
        print(f"Error fetching products: {e}")
        products = []
        
    shop_profile = get_shop_profile()
        
    return templates.TemplateResponse(
        request=request, 
        name="index.html", 
        context={"products": products, "is_locked": is_locked, "shop_profile": shop_profile}
    )

@app.post("/submit")
def post_submit(
    response: Response,
    name: str = Form(...),
    phone: str = Form(...),
    line_id: str = Form(...),
    privacy: Optional[str] = Form(None)  # checkbox: "on" when checked
):
    # Save to Firestore
    try:
        customer_ref = db.collection("customers").document()
        customer_ref.set({
            "name": name,
            "phone": phone,
            "line_id": line_id,
            "created_at": datetime.datetime.utcnow()
        })
    except Exception as e:
        print(f"Error saving customer to Firestore: {e}")
    
    # Set cookie and redirect back to index
    redirect = RedirectResponse(url="/", status_code=303)
    redirect.set_cookie(key="client_submitted", value="true", max_age=31536000) # 1 year
    return redirect

@app.get("/products", response_class=HTMLResponse)
def get_products():
    return RedirectResponse(url="/", status_code=303)


@app.get("/journal", response_class=HTMLResponse)
def get_journal(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="journal.html",
        context={}
    )


@app.post("/api/ai-advisor")
async def api_ai_advisor(request: Request):
    """Proxy requests to the Gemini API using the server-side API Key."""
    try:
        body = await request.json()
        prompt = body.get("prompt")
        if not prompt:
            raise HTTPException(status_code=400, detail="Prompt is required")
            
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            return JSONResponse({
                "error": "Backend Gemini API Key is not configured. Please set GEMINI_API_KEY in your environment."
            }, status_code=500)
            
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
        headers = {"Content-Type": "application/json"}
        payload = {
            "contents": [{
                "parts": [{"text": prompt}]
            }]
        }
        
        import urllib.request
        import json
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST"
        )
        
        with urllib.request.urlopen(req, timeout=30) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            
        try:
            generated_text = res_data["candidates"][0]["content"]["parts"][0]["text"]
            return JSONResponse({"text": generated_text})
        except (KeyError, IndexError):
            return JSONResponse({"error": "Failed to parse response from Gemini", "raw": res_data}, status_code=502)
            
    except Exception as e:
        print(f"Error in /api/ai-advisor: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)



# ── JSON API for async fetch-based form submission ─────────────────────────────
@app.post("/api/submit")
async def api_submit(
    name: str = Form(...),
    phone: str = Form(...),
    line_id: str = Form(...),
    privacy: Optional[str] = Form(None)
):
    """Accepts form data and returns JSON {ok: true}. Used by frontend fetch()."""
    try:
        db.collection("customers").document().set({
            "name": name,
            "phone": phone,
            "line_id": line_id,
            "created_at": datetime.datetime.utcnow()
        })
    except Exception as e:
        print(f"Error saving customer via /api/submit: {e}")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    resp = JSONResponse({"ok": True})
    resp.set_cookie(key="client_submitted", value="true", max_age=31536000)  # 1 year
    return resp


# ── Server-side validation: check if phone still exists in Firestore ────────────
@app.get("/api/check-status")
async def api_check_status(phone: Optional[str] = None):
    """Returns {valid: true/false}. Frontend calls this on page load to verify
    that the user's localStorage token hasn't been revoked via admin deletion."""
    if not phone:
        return JSONResponse({"valid": False})
    try:
        results = db.collection("customers").where("phone", "==", phone).limit(1).stream()
        for _ in results:
            return JSONResponse({"valid": True})
        return JSONResponse({"valid": False})
    except Exception as e:
        print(f"Error in /api/check-status: {e}")
        # On error, keep user unlocked to avoid blocking legitimate users
        return JSONResponse({"valid": True})


# Admin routes
@app.get("/admin/login", response_class=HTMLResponse)
def get_admin_login(request: Request, error: Optional[str] = None):
    return templates.TemplateResponse(
        request=request, 
        name="admin_login.html", 
        context={"error": error}
    )

@app.post("/admin/login")
def post_admin_login(
    response: Response,
    password: str = Form(...)
):
    if password == get_admin_password():
        redirect = RedirectResponse(url="/admin", status_code=303)
        redirect.set_cookie(key="admin_session", value="authenticated", httponly=True)
        return redirect
    else:
        # FastAPI templates need the request in context, so we redirect or render with error
        return RedirectResponse(url="/admin/login?error=密碼錯誤", status_code=303)

@app.get("/admin/logout")
def get_admin_logout():
    redirect = RedirectResponse(url="/admin/login", status_code=303)
    redirect.delete_cookie(key="admin_session", path="/")
    return redirect

@app.get("/admin", response_class=HTMLResponse)
def get_admin_dashboard(
    request: Request, 
    admin_session: Optional[str] = Cookie(None),
    pwd_error: Optional[str] = None,
    pwd_success: Optional[str] = None
):
    if not is_admin(admin_session):
        return RedirectResponse(url="/admin/login", status_code=303)
    
    # Fetch customers
    customers_ref = db.collection("customers").order_by("created_at", direction=firestore.Query.DESCENDING).stream()
    customers = []
    for doc in customers_ref:
        c = doc.to_dict()
        c["id"] = doc.id
        # Format time for display
        if "created_at" in c and c["created_at"]:
            # Add UTC+8 offset for display
            utc_time = c["created_at"]
            local_time = utc_time + datetime.timedelta(hours=8)
            c["formatted_time"] = local_time.strftime("%Y-%m-%d %H:%M:%S")
        else:
            c["formatted_time"] = "-"
        customers.append(c)
        
    # Fetch products
    products_ref = db.collection("products").order_by("created_at", direction=firestore.Query.DESCENDING).stream()
    products = []
    for doc in products_ref:
        p = doc.to_dict()
        p["id"] = doc.id
        if "created_at" in p and p["created_at"]:
            if hasattr(p["created_at"], "isoformat"):
                p["created_at"] = p["created_at"].isoformat()
        
        # 轉換 image_url 為 image_urls list
        image_url_str = p.get("image_url", "")
        p["image_urls"] = [url.strip() for url in image_url_str.split(",") if url.strip()] if image_url_str else []
        
        products.append(p)
    shop_profile = get_shop_profile()
    
    return templates.TemplateResponse(
        request=request,
        name="admin_dashboard.html", 
        context={
            "customers": customers, 
            "products": products, 
            "shop_profile": shop_profile,
            "pwd_error": pwd_error,
            "pwd_success": pwd_success
        }
    )

@app.post("/admin/products/add")
def post_add_product(
    admin_session: Optional[str] = Cookie(None),
    title: str = Form(...),
    description: str = Form(...),
    image_url: str = Form(""),
    url: str = Form(...),
    price: Optional[str] = Form(None),
    spec: Optional[str] = Form(None)
):
    if not is_admin(admin_session):
        raise HTTPException(status_code=401, detail="Unauthorized")

    # 清理多張圖片網址格式，支援換行、全半形逗號與分號
    import re
    urls = re.split(r'[\n\r,，;；]+', image_url) if image_url else []
    cleaned_urls = ",".join([url.strip() for url in urls if url.strip()])

    product_ref = db.collection("products").document()
    product_ref.set({
        "title": title,
        "description": description,
        "image_url": cleaned_urls,
        "url": url,
        "price": price or "",
        "spec": spec or "",
        "created_at": datetime.datetime.utcnow()
    })
    return RedirectResponse(url="/admin", status_code=303)

@app.post("/admin/products/edit/{product_id}")
def post_edit_product(
    product_id: str,
    admin_session: Optional[str] = Cookie(None),
    title: str = Form(...),
    description: str = Form(...),
    image_url: str = Form(""),
    url: str = Form(...),
    price: Optional[str] = Form(None),
    spec: Optional[str] = Form(None)
):
    if not is_admin(admin_session):
        raise HTTPException(status_code=401, detail="Unauthorized")

    # 清理多張圖片網址格式，支援換行、全半形逗號與分號
    import re
    urls = re.split(r'[\n\r,，;；]+', image_url) if image_url else []
    cleaned_urls = ",".join([url.strip() for url in urls if url.strip()])

    product_ref = db.collection("products").document(product_id)
    product_ref.update({
        "title": title,
        "description": description,
        "image_url": cleaned_urls,
        "url": url,
        "price": price or "",
        "spec": spec or "",
    })
    return RedirectResponse(url="/admin", status_code=303)

@app.post("/admin/products/delete/{product_id}")
def post_delete_product(
    product_id: str,
    admin_session: Optional[str] = Cookie(None)
):
    if not is_admin(admin_session):
        raise HTTPException(status_code=401, detail="Unauthorized")
        
    product_ref = db.collection("products").document(product_id)
    product_ref.delete()
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/profile/save")
def post_save_profile(
    admin_session: Optional[str] = Cookie(None),
    shop_name: str = Form(...),
    shop_logo_url: str = Form(""),
    shop_description: str = Form("")
):
    if not is_admin(admin_session):
        raise HTTPException(status_code=401, detail="Unauthorized")
        
    db.collection("shop_profile").document("config").set({
        "shop_name": shop_name,
        "shop_logo_url": shop_logo_url,
        "shop_description": shop_description
    })
    return RedirectResponse(url="/admin", status_code=303)

@app.post("/admin/password/change")
def post_change_password(
    admin_session: Optional[str] = Cookie(None),
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...)
):
    if not is_admin(admin_session):
        return RedirectResponse(url="/admin/login", status_code=303)
        
    active_password = get_admin_password()
    
    if current_password != active_password:
        return RedirectResponse(url="/admin?tab=profile&pwd_error=目前密碼錯誤", status_code=303)
        
    if new_password != confirm_password:
        return RedirectResponse(url="/admin?tab=profile&pwd_error=新密碼與確認密碼不一致", status_code=303)
        
    try:
        db.collection("shop_profile").document("credentials").set({
            "password": new_password
        })
    except Exception as e:
        print(f"Error saving new password: {e}")
        return RedirectResponse(url="/admin?tab=profile&pwd_error=資料庫儲存失敗，請重試", status_code=303)
        
    return RedirectResponse(url="/admin?tab=profile&pwd_success=密碼已成功修改！", status_code=303)


@app.post("/admin/customers/delete/{customer_id}")
def post_delete_customer(
    customer_id: str,
    admin_session: Optional[str] = Cookie(None)
):
    if not is_admin(admin_session):
        raise HTTPException(status_code=401, detail="Unauthorized")
    db.collection("customers").document(customer_id).delete()
    return RedirectResponse(url="/admin", status_code=303)


@app.get("/{catchall:path}")
def read_index(catchall: str):
    return RedirectResponse(url="/", status_code=303)
