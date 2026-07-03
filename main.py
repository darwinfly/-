# VERSION: v1.4.0 (Quill.js Rich Text Editor for Brand Bio)
# DATE: 2026-07-02
# CHANGES: Replaced plain textarea in admin brand settings with Quill.js rich text editor.
#          shop_description is now stored/rendered as HTML; frontend uses |safe filter.
import os
import datetime
from typing import Optional
from fastapi import FastAPI, Request, Form, Cookie, Response, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
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
                p["created_at"] = p["created_at"].isoformat()
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
    if password == ADMIN_PASSWORD:
        redirect = RedirectResponse(url="/admin", status_code=303)
        redirect.set_cookie(key="admin_session", value="authenticated", httponly=True)
        return redirect
    else:
        # FastAPI templates need the request in context, so we redirect or render with error
        return RedirectResponse(url="/admin/login?error=密碼錯誤", status_code=303)

@app.get("/admin/logout")
def get_admin_logout():
    redirect = RedirectResponse(url="/admin/login", status_code=303)
    redirect.delete_cookie(key="admin_session")
    return redirect

@app.get("/admin", response_class=HTMLResponse)
def get_admin_dashboard(request: Request, admin_session: Optional[str] = Cookie(None)):
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
            p["created_at"] = p["created_at"].isoformat()
        products.append(p)
    shop_profile = get_shop_profile()
    
    return templates.TemplateResponse(
        request=request,
        name="admin_dashboard.html", 
        context={"customers": customers, "products": products, "shop_profile": shop_profile}
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

    product_ref = db.collection("products").document()
    product_ref.set({
        "title": title,
        "description": description,
        "image_url": image_url,
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

    product_ref = db.collection("products").document(product_id)
    product_ref.update({
        "title": title,
        "description": description,
        "image_url": image_url,
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


@app.post("/admin/customers/delete/{customer_id}")
def post_delete_customer(
    customer_id: str,
    admin_session: Optional[str] = Cookie(None)
):
    if not is_admin(admin_session):
        raise HTTPException(status_code=401, detail="Unauthorized")
    db.collection("customers").document(customer_id).delete()
    return RedirectResponse(url="/admin", status_code=303)
