import base64
from typing import Optional

from openai import OpenAI

from config import get_openai_settings

settings = get_openai_settings()

PROMPTS = {
    "translate": "Translate the content into Chinese (if it's in another language) or English (if it's in Chinese). Only return the translated text.",
    "summarize": "Summarize the content concisely. Only return the summary.",
    "format": "Format the content to markdown format. Only return the formatted text. (Do not use ``` for markdown blocks.)",
    "improve": "Improve grammar, vocabulary, and style. Only return the improved text.",
    "explain": "Explain the content simply and clearly. Only return the explanation.",
    "ocr": "Perform Optical Character Recognition (OCR) on the provided image and extract the text. If the image contains equations, convert them into LaTeX format ($ ... $). Only return text inside the image.",
}


def _build_image_content(image: bytes) -> dict:
    b64 = base64.b64encode(image).decode("ascii")
    return {
        "type": "image_url",
        "image_url": {
            "url": f"data:image/png;base64,{b64}",
        },
    }


def llm_chat(
    text: str,
    image: Optional[bytes] = None,
    model_size: str = "medium",
    timeout: float = 120.0,
) -> str:
    """
    Call the configured LLM with optional image context.
    """
    model = settings["models"].get(model_size, settings["models"]["medium"])
    client = OpenAI(
        base_url=settings.get("base_url"),
        api_key=settings.get("api_key"),
        timeout=settings.get("timeout", timeout),
    )
    print(settings.get("base_url"), settings.get("api_key"))

    user_content: list[dict] = [{"type": "text", "text": text}]
    if image:
        user_content.append(_build_image_content(image))

    messages = [
        {
            "role": "system",
            "content": [
                {
                    "type": "text",
                    "text": "You are a helpful assistant.",
                }
            ],
        },
        {"role": "user", "content": user_content},
    ]

    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        max_completion_tokens=2000,
        temperature=0.6,
        timeout=timeout,
    )
    print(resp)
    return resp.choices[0].message.content or ""


def run_task(
    image: Optional[bytes], text: str, task: str, timeout: float = 120.0
) -> str:
    """
    Run a specific LLM task (OCR, Translate, Summarize, etc.) with the given text and optional image.
    """
    print("run_task:", task)
    prompt = PROMPTS.get(task.lower(), None)
    full_prompt = prompt + (f"\n\nContent:\n{text}" if text else "")
    return llm_chat(full_prompt, image=image, model_size="medium", timeout=timeout)
