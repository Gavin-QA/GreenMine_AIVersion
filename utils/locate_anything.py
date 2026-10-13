# Utility wrapper for the LocateAnything‑3B visual grounding model

"""This module provides a single function `locate_anything` that accepts a
base64‑encoded screenshot and a natural‑language instruction, invokes the locally‑
deployed LocateAnything model, and returns a JSON dict with at least the keys:

    {
        "found": bool,
        "x_percent": float,  # 0.0‑1.0 horizontal ratio
        "y_percent": float   # 0.0‑1.0 vertical ratio
    }

The implementation relies on HuggingFace `transformers` and `torch`. It expects
the model to be placed under `models/LocateAnything-3B` relative to the repository
root.
"""

import base64
import io
import json
import os
from typing import Dict

import torch
from PIL import Image
from transformers import AutoModelForCausalLM, AutoTokenizer

# Resolve model path relative to repository root
_MODEL_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "models", "LocateAnything-3B"))
if not os.path.isdir(_MODEL_DIR):
    raise RuntimeError(
        f"LocateAnything model not found at {_MODEL_DIR}.\n"
        "Please download the model (≈9 GB) from HuggingFace and place it under `models/LocateAnything-3B`."
    )

# Load tokenizer and model once (shared across calls)
_tokenizer = AutoTokenizer.from_pretrained(_MODEL_DIR, trust_remote_code=True)
_model = AutoModelForCausalLM.from_pretrained(
    _MODEL_DIR,
    torch_dtype=torch.float16,
    device_map="auto",
    trust_remote_code=True,
)

def _prepare_image(base64_image: str) -> Image.Image:
    """Decode a base64‑encoded PNG (optionally with data URI prefix) into a PIL Image."""
    if "," in base64_image:
        base64_image = base64_image.split(",", 1)[1]
    img_bytes = base64.b64decode(base64_image)
    return Image.open(io.BytesIO(img_bytes)).convert("RGB")

def locate_anything(base64_image: str, instruction: str) -> Dict:
    """Run LocateAnything‑3B on a screenshot.

    Parameters
    ----------
    base64_image: str
        Screenshot as a base64 string (with or without the ``data:image/...`` prefix).
    instruction: str
        Natural‑language description of the target UI element.

    Returns
    -------
    dict
        JSON‑compatible dict containing at least ``found``, ``x_percent`` and
        ``y_percent``. Additional fields may be present.
    """
    pil_img = _prepare_image(base64_image)
    prompt = f"<image>\n{instruction}"
    inputs = _tokenizer(prompt, return_tensors="pt").to(_model.device)
    image_tensor = _tokenizer.image_to_tensor(pil_img).unsqueeze(0).to(_model.device)
    inputs["pixel_values"] = image_tensor

    with torch.no_grad():
        output = _model.generate(**inputs, max_new_tokens=256, do_sample=False)
    response = _tokenizer.decode(output[0], skip_special_tokens=True)
    cleaned = response.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
    try:
        return json.loads(cleaned)
    except Exception as e:
        raise RuntimeError(f"Failed to parse LocateAnything response as JSON: {e}\nRaw response: {response}")
