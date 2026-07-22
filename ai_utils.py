"""Central AI provider — Google Gemini 2.0 Flash (new google-genai SDK)."""
import os
import asyncio
from google import genai
from google.genai import types


def _client():
    return genai.Client(api_key=os.getenv('GEMINI_API_KEY', ''))


def ask_ai(prompt: str, max_tokens: int = 1000) -> str:
    resp = _client().models.generate_content(
        model='gemini-2.0-flash',
        contents=prompt,
        config=types.GenerateContentConfig(max_output_tokens=max_tokens)
    )
    return resp.text.strip()


def ask_ai_with_system(system: str, user_prompt: str, max_tokens: int = 1000) -> str:
    resp = _client().models.generate_content(
        model='gemini-2.0-flash',
        contents=user_prompt,
        config=types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=max_tokens
        )
    )
    return resp.text.strip()


async def ask_ai_with_system_async(system: str, user_prompt: str, max_tokens: int = 1000) -> str:
    return await asyncio.to_thread(ask_ai_with_system, system, user_prompt, max_tokens)


def ask_ai_vision(prompt: str, image_b64: str, media_type: str = 'image/jpeg', max_tokens: int = 400) -> str:
    import base64
    image_bytes = base64.b64decode(image_b64)
    resp = _client().models.generate_content(
        model='gemini-2.0-flash',
        contents=[
            prompt,
            types.Part.from_bytes(data=image_bytes, mime_type=media_type)
        ],
        config=types.GenerateContentConfig(max_output_tokens=max_tokens)
    )
    return resp.text.strip()
