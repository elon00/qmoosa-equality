"""Real HTTP adapters. No synthetic model answers or payment confirmations."""
import json
import urllib.request
from urllib.parse import urlparse

def request_json(url, body=None, key=None):
    if urlparse(url).scheme != 'https':
        raise ValueError('HTTPS required')
    headers = {'Accept': 'application/json'}
    if key:
        headers['Authorization'] = 'Bearer ' + key
    data = None
    if body is not None:
        headers['Content-Type'] = 'application/json'
        data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)

def chat(endpoint, api_key, model, message):
    if not api_key or not model or not message or len(message) > 12000:
        raise ValueError('configured provider/model and bounded message required')
    result = request_json(endpoint, {
        'model': model, 'max_tokens': 512,
        'messages': [
            {'role': 'system', 'content': 'Explain inclusion and project services. Never promise returns, determine caste, or authorize payments.'},
            {'role': 'user', 'content': message}
        ]}, api_key)
    return result['choices'][0]['message']['content']

def bazaar_catalog(facilitator):
    return request_json(facilitator.rstrip('/') + '/discovery/resources')

def supported_payments(facilitator):
    return request_json(facilitator.rstrip('/') + '/supported')

def require_payment_integration():
    raise RuntimeError('Algorand x402 settlement is not implemented; access denied')
