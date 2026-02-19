from flask import jsonify
from werkzeug.http import HTTP_STATUS_CODES


def response_error(code_status, message=None):
    payload = {'error': HTTP_STATUS_CODES.get(code_status, "something went wrong")}
    if message:
        payload['message'] = message
    response = jsonify(payload)
    response.status_code = code_status
    return response


def bad_request(status_code=400, message=''):
    return response_error(code_status=status_code, message=message)


def sanitize_api_error(error) -> str:
    """
    Convert technical API errors to user-friendly messages.
    Works with both Exception objects and error message strings.
    """
    error_str = str(error).lower()
    if "503" in error_str or "unavailable" in error_str or "high demand" in error_str:
        return "The AI service is temporarily unavailable due to high demand. Please try again in a moment."
    if "429" in error_str or "rate limit" in error_str or "quota" in error_str:
        return "Rate limit exceeded. Please wait a moment before trying again."
    if "401" in error_str or "unauthorized" in error_str or "invalid api key" in error_str:
        return "Authentication error. Please check your API configuration."
    if "timeout" in error_str or "timed out" in error_str:
        return "The request timed out. Please try again."
    if "connection" in error_str or "network" in error_str:
        return "Network error. Please check your connection and try again."
    original = str(error)
    if len(original) > 200 or "{" in original or "traceback" in error_str:
        return "An error occurred while processing your request. Please try again later."
    return original
