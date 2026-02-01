"""
Minimal Flask app wrapper to satisfy Vercel's build system.
The actual API logic is in api/check.py as a serverless function.
"""
from flask import Flask, jsonify
import os

app = Flask(__name__)

@app.route('/')
def index():
    return jsonify({
        'status': 'operational',
        'message': 'Stripe Checker API is running',
        'api_endpoint': '/api/check',
        'docs': 'Visit / for documentation'
    })

@app.route('/health')
def health():
    return jsonify({'status': 'healthy'})

# Vercel specifically looks for a variable named 'app'
# This satisfies their build system detection
