from flask import jsonify
from werkzeug.http import HTTP_STATUS_CODES

def response_error(code_status,message=None):
    payload = {'error':HTTP_STATUS_CODES.get(code_status,"something went wrong")}
    if message:
        payload['message'] = message
    response = jsonify(payload)
    response.status_code = code_status
    return response

def bad_request(status_code=400,message=''):
    return response_error(code_status=status_code,message=message)