# app.py
from flask import Flask, request, jsonify
from flask_cors import CORS
from response_router import get_response
from logger import logger  # <-- use the shared logger (no get_logger, no basicConfig)
from dotenv import load_dotenv

app = Flask("Urja")
CORS(app, resources={r"/*": {"origins": "*"}})

load_dotenv()


@app.route("/get", methods=["GET"])
def handle_chat():
    try:
        user_input = request.args.get("msg", "").strip()
        if not user_input:
            return jsonify({"ok": False, "error": {"code": "EMPTY_REQUEST", "message": "Empty request"}}), 400

        logger.info(f"Received request: {user_input}")
        resp_obj = get_response(user_input)  # returns a dict
        return jsonify(resp_obj), (200 if resp_obj.get("ok") else 400)

    except Exception as e:
        logger.error(f"Error in handle_chat: {e}", exc_info=True)
        return jsonify({"ok": False, "error": {"code": "INTERNAL", "message": "Internal server error"}}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, debug=True)
