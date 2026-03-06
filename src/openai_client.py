# -*- coding: utf-8 -*-
"""OpenAI client wrapper

- Uses the OpenAI Python SDK if installed (recommended).
- Falls back to raw HTTP (requests) if the SDK isn't installed.

This file targets the Responses API + Structured Outputs.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Tuple

import requests

class OpenAIResponsesClient:
    def __init__(self, api_key: Optional[str] = None, base_url: str = "https://api.openai.com/v1"):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is not set.")
        self.base_url = base_url.rstrip("/")

        # Try SDK lazily
        self._sdk_client = None
        try:
            from openai import OpenAI  # type: ignore
            self._sdk_client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        except Exception:
            self._sdk_client = None

    def create_response(
        self,
        model: str,
        input_messages: List[Dict[str, Any]],
        text_format: Dict[str, Any],
        temperature: float = 0.0,
        max_output_tokens: int = 2000,
    ) -> Dict[str, Any]:
        """Return parsed JSON (dict) from a structured output response."""

        if self._sdk_client is not None:
            # OpenAI SDK path
            resp = self._sdk_client.responses.create(
                model=model,
                input=input_messages,
                text={"format": text_format},
                temperature=temperature,
                max_output_tokens=max_output_tokens,
            )
            # SDKs differ slightly; be defensive:
            if hasattr(resp, "output_parsed") and resp.output_parsed is not None:
                return resp.output_parsed  # type: ignore
            # fallback: try output_text then json.loads
            out_text = getattr(resp, "output_text", None)
            if out_text:
                return json.loads(out_text)
            # last-resort: search for the first JSON-looking content
            raw = resp.model_dump() if hasattr(resp, "model_dump") else resp  # type: ignore
            return _extract_json_from_response_dump(raw)

        # HTTP fallback
        url = f"{self.base_url}/responses"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "input": input_messages,
            "text": {"format": text_format},
            "temperature": temperature,
            "max_output_tokens": max_output_tokens,
        }
        r = requests.post(url, headers=headers, data=json.dumps(payload), timeout=120)
        r.raise_for_status()
        data = r.json()
        return _extract_json_from_response_dump(data)

def _extract_json_from_response_dump(data: Dict[str, Any]) -> Dict[str, Any]:
    """Extract JSON content from a Responses API payload (SDK dump or HTTP response)."""
    # Newer responses often include output[...].content[...].text
    try:
        output = data.get("output", [])
        for item in output:
            content = item.get("content", [])
            for c in content:
                if c.get("type") in ("output_text", "text") and "text" in c:
                    txt = c["text"]
                    if isinstance(txt, str) and txt.strip().startswith("{"):
                        return json.loads(txt)
    except Exception:
        pass

    # Sometimes the assistant message is nested differently
    txt = None
    if "output_text" in data and isinstance(data["output_text"], str):
        txt = data["output_text"]

    if isinstance(txt, str) and txt.strip():
        return json.loads(txt)

    raise ValueError("Could not extract JSON from response payload.")
