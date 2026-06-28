from flask import Blueprint, request, jsonify

site2_bp = Blueprint("site2", __name__)

ERR_CRASH = {"action": None, "response": "Une erreur inattendue s'est produite. Reessaie dans quelques secondes."}

# ── /1/conversation ────────────────────────────────────────────────────────────
@site2_bp.route("/1/conversation", methods=["POST"])
def site2_conversation():
    # Import ici pour éviter le circular import
    from echo_api import prepare_shared_context, run_paid_cascade, run_free_cascade, is_paid_tier
    try:
        data = request.json or {}
        ctx  = prepare_shared_context(data, source_override="chat")
        if is_paid_tier(ctx["user_tier"]):
            return jsonify(run_paid_cascade(ctx, page_timeout=15))
        steps = [
            ("ds", "deepseek", 8),
            ("z",  "glm",     15),
            ("or", "llama",   12),
        ]
        return jsonify(run_free_cascade(steps, ctx))
    except Exception as e:
        print(f"Erreur /1/conversation: {e}")
        return jsonify(ERR_CRASH), 500